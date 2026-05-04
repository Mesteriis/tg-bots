from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tg_bot_aggregator.domain.bots.repository import BotRepository
from tg_bot_aggregator.domain.diagnostics.bot import DiagnosticPollingBot
from tg_bot_aggregator.domain.diagnostics.repository import (
    DiagnosticSettingsRepository,
    DiagnosticUpdateRepository,
)
from tg_bot_aggregator.models import Base


class FakeBotApi:
    def __init__(self, updates: list[dict[str, Any]]) -> None:
        self.updates = updates
        self.deleted_webhooks: list[str] = []
        self.get_updates_calls: list[dict[str, Any]] = []
        self.sent_messages: list[dict[str, Any]] = []

    async def delete_webhook(self, token: str, drop_pending_updates: bool = True) -> dict[str, Any]:
        self.deleted_webhooks.append(token)
        return {"ok": True, "result": True}

    async def get_updates(
        self,
        token: str,
        offset: int | None = None,
        poll_timeout: int = 30,
        allowed_updates: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        self.get_updates_calls.append(
            {
                "token": token,
                "offset": offset,
                "timeout": poll_timeout,
                "allowed_updates": allowed_updates,
            }
        )
        return self.updates

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
        self.sent_messages.append(
            {
                "token": token,
                "chat_id": chat_id,
                "text": text,
                "message_thread_id": message_thread_id,
                "reply_markup": reply_markup,
            }
        )
        return {"ok": True, "result": {"message_id": 99}}


async def _session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _configured_factory(
    enabled: bool = True,
    last_update_id: int | None = None,
) -> async_sessionmaker[AsyncSession]:
    session_factory = await _session_factory()
    async with session_factory() as session:
        bot = await BotRepository(session).create(name="diag", token="123:token")
        await DiagnosticSettingsRepository(session).upsert(
            bot_id=bot.id,
            is_enabled=enabled,
            last_update_id=last_update_id,
        )
        await session.commit()
    return session_factory


async def _diagnostic_settings(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Any]:
    async with session_factory() as session:
        yield await DiagnosticSettingsRepository(session).get()


async def test_initialize_deletes_webhook_for_selected_dashboard_bot() -> None:
    session_factory = await _configured_factory()
    fake_api = FakeBotApi([])
    bot = DiagnosticPollingBot(session_factory=session_factory, bot_api=fake_api)

    assert await bot.initialize() == "ready"

    assert fake_api.deleted_webhooks == ["123:token"]


async def test_run_once_replies_with_thread_id_and_advances_offset() -> None:
    session_factory = await _configured_factory(last_update_id=10)
    fake_api = FakeBotApi(
        [
            {
                "update_id": 11,
                "message": {
                    "message_id": 5,
                    "message_thread_id": 42,
                    "is_topic_message": True,
                    "chat": {"id": -100123, "type": "supergroup", "title": "Ops"},
                    "from": {"id": 777, "first_name": "Alice"},
                    "text": "ping",
                },
            }
        ]
    )
    bot = DiagnosticPollingBot(session_factory=session_factory, bot_api=fake_api, poll_timeout=5)

    assert await bot.run_once() == "processed:1"

    assert fake_api.get_updates_calls[0]["offset"] == 11
    assert fake_api.get_updates_calls[0]["timeout"] == 5
    assert fake_api.sent_messages[0]["chat_id"] == "-100123"
    assert fake_api.sent_messages[0]["message_thread_id"] == 42
    assert "message_thread_id: 42" in fake_api.sent_messages[0]["text"]
    assert fake_api.sent_messages[0]["reply_markup"]["inline_keyboard"]
    async for settings in _diagnostic_settings(session_factory):
        assert settings.last_update_id == 11
    async with session_factory() as session:
        updates = await DiagnosticUpdateRepository(session).list(limit=10)
        assert updates[0].update_id == 11
        assert updates[0].chat_id == "-100123"
        assert updates[0].message_thread_id == 42


async def test_run_once_advances_offset_for_non_message_update_without_reply() -> None:
    session_factory = await _configured_factory()
    fake_api = FakeBotApi([{"update_id": 12, "callback_query": {"id": "abc"}}])
    bot = DiagnosticPollingBot(session_factory=session_factory, bot_api=fake_api)

    assert await bot.run_once() == "processed:1"

    assert fake_api.sent_messages == []
    async for settings in _diagnostic_settings(session_factory):
        assert settings.last_update_id == 12


async def test_run_once_returns_disabled_without_dashboard_selection() -> None:
    session_factory = await _session_factory()
    fake_api = FakeBotApi([])
    bot = DiagnosticPollingBot(session_factory=session_factory, bot_api=fake_api)

    assert await bot.run_once() == "disabled"

    assert fake_api.get_updates_calls == []
