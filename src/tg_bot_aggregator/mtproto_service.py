from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.repositories import MtprotoSessionRepository


@dataclass(frozen=True)
class AnalyticsMetrics:
    title: str | None
    username: str | None
    kind: str | None
    participants_count: int | None
    recent_messages_count: int | None
    recent_views_total: int | None
    recent_forwards_total: int | None
    recent_replies_total: int | None
    raw_metrics: dict[str, Any]


class MtprotoConfigurationError(RuntimeError):
    pass


class MtprotoService:
    def __init__(
        self,
        settings: Settings,
        session_repo: MtprotoSessionRepository,
        client_factory: Callable[[str, int, str], Any] | None = None,
    ) -> None:
        self.settings = settings
        self.session_repo = session_repo
        self.client_factory = client_factory or TelegramClient

    def _client(self) -> Any:
        if not self.settings.telegram_api_id or not self.settings.telegram_api_hash:
            raise MtprotoConfigurationError("TELEGRAM_API_ID and TELEGRAM_API_HASH are required")
        session_dir = Path(self.settings.telethon_session_dir)
        session_dir.mkdir(parents=True, exist_ok=True)
        return self.client_factory(
            str(session_dir / "default"),
            int(self.settings.telegram_api_id),
            self.settings.telegram_api_hash,
        )

    async def status(self) -> dict[str, str | None]:
        row = await self.session_repo.get_default()
        if row is None:
            return {"status": "missing", "phone": None, "last_error": None}
        return {"status": row.status, "phone": row.phone, "last_error": row.last_error}

    async def start_login(self, phone: str) -> dict[str, str | None]:
        async with self._client() as client:
            await client.send_code_request(phone)
        row = await self.session_repo.upsert_default(phone=phone, status="code_requested")
        return {"status": row.status, "phone": row.phone, "last_error": row.last_error}

    async def confirm_code(self, phone: str, code: str) -> dict[str, str | None]:
        try:
            async with self._client() as client:
                await client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            row = await self.session_repo.upsert_default(phone=phone, status="password_required")
            return {"status": row.status, "phone": row.phone, "last_error": row.last_error}
        row = await self.session_repo.upsert_default(phone=phone, status="ready", last_error=None)
        return {"status": row.status, "phone": row.phone, "last_error": row.last_error}

    async def confirm_password(self, password: str) -> dict[str, str | None]:
        row = await self.session_repo.get_default()
        phone = row.phone if row is not None else None
        async with self._client() as client:
            await client.sign_in(password=password)
        row = await self.session_repo.upsert_default(phone=phone, status="ready", last_error=None)
        return {"status": row.status, "phone": row.phone, "last_error": row.last_error}

    async def collect_metrics(self, peer_ref: str, recent_limit: int = 50) -> AnalyticsMetrics:
        async with self._client() as client:
            entity = await client.get_entity(peer_ref)
            title = getattr(entity, "title", None) or getattr(entity, "first_name", None)
            username = getattr(entity, "username", None)
            kind = type(entity).__name__
            participants_count = (
                getattr(entity, "participants_count", None)
                or getattr(entity, "members_count", None)
                or getattr(entity, "participants", None)
            )
            messages = []
            async for message in client.iter_messages(entity, limit=recent_limit):
                messages.append(message)

        views = [getattr(message, "views", None) for message in messages]
        forwards = [getattr(message, "forwards", None) for message in messages]
        replies = [
            getattr(getattr(message, "replies", None), "replies", None) for message in messages
        ]

        return AnalyticsMetrics(
            title=title,
            username=username,
            kind=kind,
            participants_count=participants_count,
            recent_messages_count=len(messages),
            recent_views_total=sum(value for value in views if value is not None) or None,
            recent_forwards_total=sum(value for value in forwards if value is not None) or None,
            recent_replies_total=sum(value for value in replies if value is not None) or None,
            raw_metrics={
                "peer_ref": peer_ref,
                "messages_sampled": len(messages),
                "has_views": any(value is not None for value in views),
            },
        )

