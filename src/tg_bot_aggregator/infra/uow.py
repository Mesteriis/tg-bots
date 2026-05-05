import asyncio
import logging
from collections.abc import Callable
from hashlib import sha256
from types import TracebackType

import redis.asyncio as redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.core.db import is_sqlite_database_url, is_sqlite_memory_database_url
from tg_bot_aggregator.domain.analytics.repository import (
    AnalyticsRepository,
    MtprotoSessionRepository,
)
from tg_bot_aggregator.domain.auth.repository import ApiTokenRepository
from tg_bot_aggregator.domain.backups.repository import BackupRunRepository
from tg_bot_aggregator.domain.batches.repository import SendBatchRepository
from tg_bot_aggregator.domain.bots.repository import BotRepository
from tg_bot_aggregator.domain.destinations.repository import (
    DestinationHealthRepository,
    DestinationRepository,
)
from tg_bot_aggregator.domain.operations.repository import (
    RuntimeAdvancedSettingsRepository,
    RuntimeSettingsRepository,
)
from tg_bot_aggregator.domain.ops.repository import OpsRecommendationRepository
from tg_bot_aggregator.domain.sending.repository import (
    SendAttemptRepository,
    SendHistoryRepository,
    SendProfileRepository,
)
from tg_bot_aggregator.domain.templates.repository import (
    TemplateRepository,
    TemplateVersionRepository,
)
from tg_bot_aggregator.infra.audit import AuditRepository

logger = logging.getLogger(__name__)
_PROCESS_LOCAL_SQLITE_LOCKS: dict[str, asyncio.Lock] = {}


class UnitOfWork:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        settings: Settings | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self._completed = False
        self._lock_client: redis.Redis | None = None
        self._lock = None
        self._process_lock: asyncio.Lock | None = None

    async def __aenter__(self) -> "UnitOfWork":
        await self._acquire_sqlite_lock()
        self.session = self.session_factory()
        self.bots = BotRepository(self.session)
        self.tokens = ApiTokenRepository(self.session)
        self.destinations = DestinationRepository(self.session)
        self.destination_health = DestinationHealthRepository(self.session)
        self.templates = TemplateRepository(self.session)
        self.template_versions = TemplateVersionRepository(self.session)
        self.sending = SendHistoryRepository(self.session)
        self.attempts = SendAttemptRepository(self.session)
        self.profiles = SendProfileRepository(self.session)
        self.batches = SendBatchRepository(self.session)
        self.backups = BackupRunRepository(self.session)
        self.runtime_settings = RuntimeSettingsRepository(self.session)
        self.runtime_advanced_settings = RuntimeAdvancedSettingsRepository(self.session)
        self.analytics = AnalyticsRepository(self.session)
        self.mtproto_sessions = MtprotoSessionRepository(self.session)
        self.ops = OpsRecommendationRepository(self.session)
        self.audit = AuditRepository(self.session)
        return self

    async def commit(self) -> None:
        await self.session.commit()
        self._completed = True

    async def rollback(self) -> None:
        await self.session.rollback()
        self._completed = True

    def _has_active_transaction(self) -> bool:
        in_transaction = getattr(self.session, "in_transaction", None)
        if callable(in_transaction):
            return bool(in_transaction())
        return False

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None:
                if self._has_active_transaction() or not self._completed:
                    await self.session.commit()
            elif self._has_active_transaction() or not self._completed:
                await self.session.rollback()
        finally:
            await self.session.close()
            await self._release_sqlite_lock()

    async def _acquire_sqlite_lock(self) -> None:
        settings = self.settings
        if settings is None:
            return
        if not settings.sqlite_uow_lock_enabled:
            return
        if not is_sqlite_database_url(settings.database_url):
            return
        if is_sqlite_memory_database_url(settings.database_url):
            return
        lock_key = "tg-bot-aggregator:sqlite-uow:" + sha256(
            settings.database_url.encode("utf-8")
        ).hexdigest()
        self._lock_client = redis.from_url(settings.redis_url)
        self._lock = self._lock_client.lock(
            lock_key,
            timeout=settings.sqlite_uow_lock_timeout_seconds,
            blocking_timeout=settings.sqlite_uow_lock_wait_seconds,
        )
        try:
            acquired = await self._lock.acquire()
        except RedisConnectionError:
            await self._fallback_to_process_local_sqlite_lock(
                lock_key, settings.sqlite_uow_lock_wait_seconds
            )
            return
        if not acquired:
            await self._lock_client.aclose()
            self._lock_client = None
            self._lock = None
            raise RuntimeError("failed to acquire sqlite database write lock")

    async def _release_sqlite_lock(self) -> None:
        try:
            if self._lock is not None:
                await self._lock.release()
            if self._process_lock is not None and self._process_lock.locked():
                self._process_lock.release()
        finally:
            if self._lock_client is not None:
                await self._lock_client.aclose()
        self._lock = None
        self._lock_client = None
        self._process_lock = None

    async def _fallback_to_process_local_sqlite_lock(
        self, lock_key: str, wait_seconds: int
    ) -> None:
        if self._lock_client is not None:
            await self._lock_client.aclose()
        self._lock_client = None
        self._lock = None
        process_lock = _PROCESS_LOCAL_SQLITE_LOCKS.setdefault(lock_key, asyncio.Lock())
        try:
            await asyncio.wait_for(process_lock.acquire(), timeout=wait_seconds)
        except TimeoutError as exc:
            raise RuntimeError("failed to acquire sqlite database write lock") from exc
        self._process_lock = process_lock
        logger.warning(
            "Redis sqlite lock backend is unavailable; using process-local sqlite UoW lock."
        )
