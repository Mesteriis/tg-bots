from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tg_bot_aggregator.domain.bots.repository import BotRepository
from tg_bot_aggregator.domain.destinations.repository import DestinationRepository
from tg_bot_aggregator.domain.discovery.bot import DiscoveryPollingBot
from tg_bot_aggregator.domain.discovery.repository import (
    BotDiscoveryEventRepository,
    BotDiscoverySettingsRepository,
)
from tg_bot_aggregator.models import Base


class FakeDiscoveryApi:
    def __init__(self, updates: list[dict[str, Any]] | None = None) -> None:
        self.updates = updates or []
        self.deleted_webhooks: list[str] = []
        self.get_updates_calls: list[dict[str, Any]] = []

    async def delete_webhook(
        self,
        token: str,
        drop_pending_updates: bool = True,
    ) -> dict[str, Any]:
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
            {"token": token, "offset": offset, "allowed_updates": allowed_updates}
        )
        return self.updates


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def test_discovery_runner_is_disabled_without_enabled_bots(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    runner = DiscoveryPollingBot(session_factory, FakeDiscoveryApi(), poll_timeout=0)

    assert await runner.run_once() == "disabled"


async def test_discovery_runner_initializes_enabled_bot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    api = FakeDiscoveryApi()
    async with session_factory() as session:
        bot = await BotRepository(session).create(name="ops", token="123:token")
        await BotDiscoverySettingsRepository(session).upsert_for_bot(bot.id, is_enabled=True)
        await session.commit()

    runner = DiscoveryPollingBot(session_factory, api, poll_timeout=0)

    assert await runner.initialize() == "ready:1"
    assert api.deleted_webhooks == ["123:token"]


async def test_discovery_runner_upserts_destination_from_membership_update(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    update = {
        "update_id": 42,
        "my_chat_member": {
            "chat": {
                "id": -100,
                "type": "supergroup",
                "title": "Ops Forum",
                "username": "ops_forum",
            },
            "old_chat_member": {"status": "left"},
            "new_chat_member": {"status": "administrator"},
        },
    }
    api = FakeDiscoveryApi([update])
    async with session_factory() as session:
        bot = await BotRepository(session).create(name="ops", token="123:token")
        await BotDiscoverySettingsRepository(session).upsert_for_bot(bot.id, is_enabled=True)
        await session.commit()

    runner = DiscoveryPollingBot(session_factory, api, poll_timeout=0)

    assert await runner.run_once() == "processed:1"

    async with session_factory() as session:
        destination = await DestinationRepository(session).get_by_chat(bot.id, "-100")
        settings = await BotDiscoverySettingsRepository(session).get_for_bot(bot.id)
        events = await BotDiscoveryEventRepository(session).list()

    assert api.get_updates_calls[0]["allowed_updates"] == ["my_chat_member"]
    assert destination is not None
    assert destination.kind == "supergroup"
    assert destination.title == "Ops Forum"
    assert destination.username == "ops_forum"
    assert settings.last_update_id == 42
    assert events[0].new_status == "administrator"
