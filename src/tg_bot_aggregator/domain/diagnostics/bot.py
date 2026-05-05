import argparse
import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tg_bot_aggregator.core.config import get_settings
from tg_bot_aggregator.core.db import resolve_runtime_database_state
from tg_bot_aggregator.domain.bots.repository import BotRepository
from tg_bot_aggregator.domain.diagnostics.formatter import (
    build_copy_keyboard,
    chunk_report,
    format_update_report,
)
from tg_bot_aggregator.domain.diagnostics.repository import (
    DiagnosticSettingsRepository,
    DiagnosticUpdateRepository,
)
from tg_bot_aggregator.infra.telegram_client import TelegramBotApiClient, TelegramBotApiError

logger = logging.getLogger(__name__)

ALLOWED_UPDATES = ["message", "edited_message", "channel_post", "edited_channel_post"]


class DiagnosticBotApi(Protocol):
    async def delete_webhook(
        self,
        token: str,
        drop_pending_updates: bool = True,
    ) -> dict[str, Any]:
        ...

    async def get_updates(
        self,
        token: str,
        offset: int | None = None,
        poll_timeout: int = 30,
        allowed_updates: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        ...

    async def send_message(
        self,
        token: str,
        chat_id: str,
        text: str,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
        message_thread_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ActiveDiagnosticBot:
    token: str
    offset: int | None


class DiagnosticPollingBot:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bot_api: DiagnosticBotApi,
        poll_timeout: int = 30,
        retry_delay_seconds: float = 5.0,
    ) -> None:
        self.session_factory = session_factory
        self.bot_api = bot_api
        self.poll_timeout = poll_timeout
        self.retry_delay_seconds = retry_delay_seconds

    async def _active_bot(self) -> ActiveDiagnosticBot | None:
        async with self.session_factory() as session:
            settings = await DiagnosticSettingsRepository(session).get()
            if settings is None or not settings.is_enabled or settings.bot_id is None:
                return None
            bot = await BotRepository(session).get(settings.bot_id)
            if bot is None or not bot.is_active:
                await DiagnosticSettingsRepository(session).upsert(
                    last_error="selected diagnostic bot is missing or inactive"
                )
                await session.commit()
                return None
            offset = settings.last_update_id + 1 if settings.last_update_id is not None else None
            return ActiveDiagnosticBot(token=bot.token, offset=offset)

    async def _store_progress(self, update_id: int, last_error: str | None = None) -> None:
        async with self.session_factory() as session:
            await DiagnosticSettingsRepository(session).upsert(
                last_update_id=update_id,
                last_error=last_error,
            )
            await session.commit()

    async def initialize(self) -> str:
        active = await self._active_bot()
        if active is None:
            return "disabled"
        await self.bot_api.delete_webhook(active.token, drop_pending_updates=False)
        return "ready"

    async def _store_update(self, report: Any, update: dict[str, Any]) -> None:
        metadata = report.metadata
        if metadata.update_id is None:
            return
        async with self.session_factory() as session:
            repo = DiagnosticUpdateRepository(session)
            if await repo.get_by_update_id(metadata.update_id) is not None:
                return
            await repo.create(
                update_id=metadata.update_id,
                update_kind=metadata.update_kind,
                chat_id=metadata.chat_id,
                chat_type=metadata.chat_type,
                chat_title=metadata.chat_title,
                chat_username=metadata.chat_username,
                message_id=metadata.message_id,
                message_thread_id=metadata.message_thread_id,
                is_topic_message=metadata.is_topic_message,
                sender_id=metadata.sender_id,
                sender_username=metadata.sender_username,
                text_preview=metadata.text_preview,
                raw_update_json=update,
            )
            await session.commit()

    async def _reply_to_update(self, token: str, update: dict[str, Any]) -> None:
        report = format_update_report(update)
        await self._store_update(report, update)
        if report.reply_chat_id is None:
            return
        chunks = chunk_report(report.text)
        keyboard = build_copy_keyboard(report.identifiers)
        for index, chunk in enumerate(chunks):
            await self.bot_api.send_message(
                token=token,
                chat_id=report.reply_chat_id,
                text=chunk,
                message_thread_id=report.reply_message_thread_id,
                reply_markup=keyboard if index == 0 else None,
            )

    async def run_once(self) -> str:
        active = await self._active_bot()
        if active is None:
            return "disabled"
        updates = await self.bot_api.get_updates(
            active.token,
            offset=active.offset,
            poll_timeout=self.poll_timeout,
            allowed_updates=ALLOWED_UPDATES,
        )
        for update in updates:
            update_id = update.get("update_id")
            if not isinstance(update_id, int):
                continue
            try:
                await self._reply_to_update(active.token, update)
                await self._store_progress(update_id)
            except TelegramBotApiError as exc:
                await self._store_progress(update_id, last_error=exc.description)
                logger.warning("failed to reply to diagnostic update: %s", exc.description)
        return f"processed:{len(updates)}"

    async def run_forever(self) -> None:
        await self.initialize()
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except TelegramBotApiError as exc:
                logger.warning("diagnostic polling error: %s", exc.description)
                await asyncio.sleep(self.retry_delay_seconds)


async def async_main(once: bool = False) -> int:
    runtime_db = await resolve_runtime_database_state(get_settings(), create_sqlite_schema=True)
    settings = runtime_db.settings
    session_factory = runtime_db.session_factory
    bot = DiagnosticPollingBot(
        session_factory=session_factory,
        bot_api=TelegramBotApiClient(settings.telegram_bot_api_base_url),
        poll_timeout=settings.diagnostic_poll_timeout_seconds,
        retry_delay_seconds=settings.diagnostic_retry_delay_seconds,
    )
    try:
        if once:
            print(await bot.run_once())
            return 0
        await bot.run_forever()
        return 0
    finally:
        await runtime_db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the dashboard-managed diagnostic bot.")
    parser.add_argument("--once", action="store_true", help="Run one polling iteration and exit.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(async_main(once=args.once)))


if __name__ == "__main__":
    main()
