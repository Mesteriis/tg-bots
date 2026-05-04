from collections.abc import Callable
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.domain.auth.repository import ApiTokenRepository
from tg_bot_aggregator.domain.backups.repository import BackupRunRepository
from tg_bot_aggregator.domain.batches.repository import SendBatchRepository
from tg_bot_aggregator.domain.bots.repository import BotRepository
from tg_bot_aggregator.domain.destinations.repository import DestinationRepository
from tg_bot_aggregator.domain.ops.repository import OpsRecommendationRepository
from tg_bot_aggregator.domain.sending.repository import SendAttemptRepository, SendHistoryRepository
from tg_bot_aggregator.domain.templates.repository import TemplateRepository
from tg_bot_aggregator.infra.audit import AuditRepository


class UnitOfWork:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self.session_factory = session_factory

    async def __aenter__(self) -> "UnitOfWork":
        self.session = self.session_factory()
        self.bots = BotRepository(self.session)
        self.tokens = ApiTokenRepository(self.session)
        self.destinations = DestinationRepository(self.session)
        self.templates = TemplateRepository(self.session)
        self.sending = SendHistoryRepository(self.session)
        self.attempts = SendAttemptRepository(self.session)
        self.batches = SendBatchRepository(self.session)
        self.backups = BackupRunRepository(self.session)
        self.ops = OpsRecommendationRepository(self.session)
        self.audit = AuditRepository(self.session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            await self.session.commit()
        else:
            await self.session.rollback()
        await self.session.close()
