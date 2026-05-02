import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.events import MemoryEventBus
from tg_bot_aggregator.main import create_app
from tg_bot_aggregator.models import Base
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient


async def test_analytics_target_crud_and_refresh_queue() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def enqueue(target_id: int, run_id: int) -> str:
        return f"task-{target_id}-{run_id}"

    app = create_app(
        settings=Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:"),
        session_factory=session_factory,
        event_bus=MemoryEventBus(),
        bot_api_client=TelegramBotApiClient("http://telegram-bot-api:8081"),
        enqueue_analytics_refresh=enqueue,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        target = (
            await client.post("/api/v1/analytics/targets", json={"peer_ref": "@channel"})
        ).json()
        assert target["peer_ref"] == "@channel"

        refresh = (
            await client.post("/api/v1/analytics/refresh", json={"target_id": target["id"]})
        ).json()
        assert refresh["status"] == "queued"
        assert refresh["task_id"].startswith("task-")

        runs = (await client.get("/api/v1/analytics/runs")).json()
        assert runs[0]["task_id"] == refresh["task_id"]

    await engine.dispose()
