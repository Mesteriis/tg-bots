import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.events import MemoryEventBus
from tg_bot_aggregator.main import create_app
from tg_bot_aggregator.models import Base
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient


async def _client(
    handler: httpx.MockTransport | None = None,
    raise_app_exceptions: bool = True,
) -> tuple[httpx.AsyncClient, MemoryEventBus]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    event_bus = MemoryEventBus()

    async def default_handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/getMe"):
            return httpx.Response(
                200, json={"ok": True, "result": {"id": 123, "username": "ops_bot"}}
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 88}})

    bot_api = TelegramBotApiClient(
        "http://telegram-bot-api:8081",
        httpx.AsyncClient(transport=handler or httpx.MockTransport(default_handler)),
    )
    app = create_app(
        settings=Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:"),
        session_factory=session_factory,
        event_bus=event_bus,
        bot_api_client=bot_api,
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=app,
            raise_app_exceptions=raise_app_exceptions,
        ),
        base_url="http://test",
    )
    return client, event_bus


async def test_health_and_crud_and_send_flow() -> None:
    client, _ = await _client()
    async with client:
        health = await client.get("/api/v1/health")
        assert health.json()["status"] == "ok"

        bot = (await client.post("/api/v1/bots", json={"name": "ops", "token": "123:token"})).json()
        checked = (await client.post(f"/api/v1/bots/{bot['id']}/check")).json()
        assert checked["username"] == "ops_bot"

        destination = (
            await client.post(
                "/api/v1/destinations",
                json={"bot_id": bot["id"], "kind": "channel", "chat_id": "@ops"},
            )
        ).json()
        template = (
            await client.post(
                "/api/v1/templates",
                json={"tag": "deploy", "title": "Deploy", "text": "done"},
            )
        ).json()
        assert template["tag"] == "deploy"

        sent = (
            await client.post(
                "/api/v1/send/text",
                json={"bot_id": bot["id"], "destination_id": destination["id"], "text": "hello"},
            )
        ).json()
        assert sent["status"] == "succeeded"

        history = (await client.get("/api/v1/send-history")).json()
        assert history[0]["telegram_message_id"] == 88


async def test_create_bot_with_token_fetches_metadata_immediately() -> None:
    client, event_bus = await _client()
    async with client:
        response = await client.post("/api/v1/bots", json={"token": "123:token"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "@ops_bot"
    assert payload["username"] == "ops_bot"
    assert payload["telegram_bot_id"] == 123
    assert payload["last_checked_at"] is not None
    assert (await event_bus.latest()).event_type == "bot.checked"


async def test_create_bot_returns_gateway_error_when_bot_api_unreachable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed", request=request)

    client, _ = await _client(
        handler=httpx.MockTransport(handler),
        raise_app_exceptions=False,
    )
    async with client:
        response = await client.post("/api/v1/bots", json={"token": "123:token"})

    assert response.status_code == 502
    assert response.json() == {
        "detail": "Telegram Bot API request failed: name resolution failed"
    }


async def test_dashboard_can_manage_diagnostic_bot_settings() -> None:
    client, _ = await _client()
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        missing = (await client.get("/api/v1/diagnostics/bot")).json()
        updated_response = await client.patch(
            "/api/v1/diagnostics/bot",
            json={"bot_id": bot["id"], "is_enabled": True},
        )
        updated = updated_response.json()

    assert missing["bot_id"] is None
    assert missing["is_enabled"] is False
    assert updated_response.status_code == 200
    assert updated["bot_id"] == bot["id"]
    assert updated["bot_name"] == "@ops_bot"
    assert updated["bot_username"] == "ops_bot"
    assert updated["is_enabled"] is True
    assert updated["last_update_id"] is None


async def test_events_once_returns_sse_frame() -> None:
    client, event_bus = await _client()
    await event_bus.publish("send.created", {"send_history_id": 1})

    async with client:
        response = await client.get("/api/v1/events?once=true")

    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: send.created" in response.text
