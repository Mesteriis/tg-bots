import argparse
import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tg_bot_aggregator.config import get_settings
from tg_bot_aggregator.db import create_engine, create_session_factory
from tg_bot_aggregator.models import Base
from tg_bot_aggregator.repositories import (
    BotDiscoveryEventRepository,
    BotDiscoverySettingsRepository,
    BotRepository,
    DestinationRepository,
)
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient, TelegramBotApiError

logger = logging.getLogger(__name__)

ALLOWED_UPDATES = ["my_chat_member"]
ACTIVE_STATUSES = {"member", "administrator", "creator"}


class DiscoveryBotApi(Protocol):
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


@dataclass(frozen=True)
class ActiveDiscoveryBot:
    bot_id: int
    token: str
    offset: int | None


class DiscoveryPollingBot:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bot_api: DiscoveryBotApi,
        poll_timeout: int = 30,
        retry_delay_seconds: float = 5.0,
    ) -> None:
        self.session_factory = session_factory
        self.bot_api = bot_api
        self.poll_timeout = poll_timeout
        self.retry_delay_seconds = retry_delay_seconds

    async def _active_bots(self) -> list[ActiveDiscoveryBot]:
        async with self.session_factory() as session:
            settings_rows = await BotDiscoverySettingsRepository(session).list_enabled()
            bots = BotRepository(session)
            active: list[ActiveDiscoveryBot] = []
            for settings in settings_rows:
                bot = await bots.get(settings.bot_id)
                if bot is None or not bot.is_active:
                    await BotDiscoverySettingsRepository(session).upsert_for_bot(
                        settings.bot_id,
                        last_error="selected discovery bot is missing or inactive",
                    )
                    continue
                offset = (
                    settings.last_update_id + 1 if settings.last_update_id is not None else None
                )
                active.append(ActiveDiscoveryBot(bot_id=bot.id, token=bot.token, offset=offset))
            await session.commit()
            return active

    async def initialize(self) -> str:
        active = await self._active_bots()
        if not active:
            return "disabled"
        for bot in active:
            await self.bot_api.delete_webhook(bot.token, drop_pending_updates=False)
        return f"ready:{len(active)}"

    async def _store_progress(
        self,
        bot_id: int,
        update_id: int,
        last_error: str | None = None,
    ) -> None:
        async with self.session_factory() as session:
            await BotDiscoverySettingsRepository(session).upsert_for_bot(
                bot_id,
                last_update_id=update_id,
                last_error=last_error,
            )
            await session.commit()

    async def _process_update(self, bot_id: int, update: dict[str, Any]) -> None:
        membership = update.get("my_chat_member")
        update_id = update.get("update_id")
        if not isinstance(membership, dict) or not isinstance(update_id, int):
            return
        chat = membership.get("chat")
        if not isinstance(chat, dict):
            await self._store_progress(bot_id, update_id)
            return
        chat_id = str(chat.get("id"))
        kind = str(chat.get("type") or "group")
        if kind not in {"private", "group", "supergroup", "channel"}:
            kind = "group"
        title = chat.get("title") or chat.get("first_name") or chat.get("username") or chat_id
        username = chat.get("username")
        old_status = _status(membership.get("old_chat_member"))
        new_status = _status(membership.get("new_chat_member"))

        async with self.session_factory() as session:
            is_active = new_status in ACTIVE_STATUSES
            await DestinationRepository(session).upsert_by_chat(
                bot_id=bot_id,
                chat_id=chat_id,
                kind=kind,
                title=str(title) if title is not None else None,
                username=str(username) if username is not None else None,
                is_active=is_active,
            )
            await BotDiscoveryEventRepository(session).create(
                bot_id=bot_id,
                update_id=update_id,
                chat_id=chat_id,
                kind=kind,
                old_status=old_status,
                new_status=new_status,
                raw_update_json=update,
            )
            await BotDiscoverySettingsRepository(session).upsert_for_bot(
                bot_id,
                last_update_id=update_id,
                last_error=None,
            )
            await session.commit()

    async def run_once(self) -> str:
        active = await self._active_bots()
        if not active:
            return "disabled"
        processed = 0
        for bot in active:
            updates = await self.bot_api.get_updates(
                bot.token,
                offset=bot.offset,
                poll_timeout=self.poll_timeout,
                allowed_updates=ALLOWED_UPDATES,
            )
            for update in updates:
                update_id = update.get("update_id")
                if not isinstance(update_id, int):
                    continue
                try:
                    await self._process_update(bot.bot_id, update)
                    processed += 1
                except TelegramBotApiError as exc:
                    await self._store_progress(bot.bot_id, update_id, last_error=exc.description)
                    logger.warning("failed to process discovery update: %s", exc.description)
        return f"processed:{processed}"

    async def run_forever(self) -> None:
        await self.initialize()
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except TelegramBotApiError as exc:
                logger.warning("discovery polling error: %s", exc.description)
                await asyncio.sleep(self.retry_delay_seconds)


def _status(value: Any) -> str | None:
    return str(value.get("status")) if isinstance(value, dict) and value.get("status") else None


async def async_main(once: bool = False) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    bot = DiscoveryPollingBot(
        session_factory=session_factory,
        bot_api=TelegramBotApiClient(settings.telegram_bot_api_base_url),
        poll_timeout=settings.discovery_poll_timeout_seconds,
        retry_delay_seconds=settings.discovery_retry_delay_seconds,
    )
    try:
        if once:
            print(await bot.run_once())
            return 0
        await bot.run_forever()
        return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run bot chat discovery polling.")
    parser.add_argument("--once", action="store_true", help="Run one polling iteration and exit.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(async_main(once=args.once)))


if __name__ == "__main__":
    main()
