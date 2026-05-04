import json
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.infra.events import MemoryEventBus
from tg_bot_aggregator.infra.telegram_client import TelegramBotApiClient
from tg_bot_aggregator.main import create_app
from tg_bot_aggregator.models import Base


async def _client(
    seen: dict[str, Any] | None = None,
) -> httpx.AsyncClient:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    seen = seen if seen is not None else {}

    async def handler(request: httpx.Request) -> httpx.Response:
        method = str(request.url).rsplit("/", 1)[-1]
        payload = json.loads(request.content or b"{}")
        seen.setdefault("calls", []).append({"method": method, "payload": payload})
        if method == "getMe":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "id": 123,
                        "is_bot": True,
                        "first_name": "Ops",
                        "username": "ops_bot",
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 88,
                    "date": 1_714_000_000,
                    "chat": {
                        "id": -100123,
                        "type": "supergroup",
                        "title": "Ops chat",
                        "username": "ops_chat",
                    },
                    "text": payload.get("text"),
                },
            },
        )

    app = create_app(
        settings=Settings(
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            PROTECTED_API_HOSTS="tg.sh-inc.ru,tg.sh-inc.dev",
        ),
        session_factory=session_factory,
        event_bus=MemoryEventBus(),
        bot_api_client=TelegramBotApiClient(
            "http://telegram-bot-api:8081",
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8000",
    )


async def _create_bot(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.post("/api/v1/bots", json={"token": "123456:ABCdef_123456789012345"})
    assert response.status_code == 201
    return response.json()


async def test_telegram_compatible_get_me_uses_stored_bot_by_token() -> None:
    client = await _client()
    async with client:
        await _create_bot(client)
        response = await client.post("/bot123456:ABCdef_123456789012345/getMe")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "result": {
            "id": 123,
            "is_bot": True,
            "first_name": "@ops_bot",
            "username": "ops_bot",
        },
    }


async def test_telegram_compatible_send_message_records_history_and_destination() -> None:
    seen: dict[str, Any] = {}
    client = await _client(seen)
    async with client:
        await _create_bot(client)
        response = await client.post(
            "/bot123456:ABCdef_123456789012345/sendMessage",
            json={"chat_id": -100123, "text": "hello", "message_thread_id": 77},
        )
        history = (await client.get("/api/v1/send-history")).json()
        destinations = (await client.get("/api/v1/destinations")).json()

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["result"]["message_id"] == 88
    assert seen["calls"][-1]["method"] == "sendMessage"
    assert seen["calls"][-1]["payload"]["message_thread_id"] == 77
    assert history[0]["telegram_message_id"] == 88
    assert destinations[0]["chat_id"] == "-100123"
    assert destinations[0]["message_thread_id"] == 77
    assert destinations[0]["title"] == "Ops chat"


async def test_telegram_compatible_send_message_accepts_form_payload() -> None:
    client = await _client()
    async with client:
        await _create_bot(client)
        response = await client.post(
            "/bot123456:ABCdef_123456789012345/sendMessage",
            content="chat_id=-100123&text=form+hello",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert response.status_code == 200
    assert response.json()["result"]["text"] == "form hello"


async def test_telegram_compatible_send_document_uses_standard_document_field() -> None:
    seen: dict[str, Any] = {}
    client = await _client(seen)
    async with client:
        await _create_bot(client)
        response = await client.post(
            "/bot123456:ABCdef_123456789012345/sendDocument",
            json={"chat_id": -100123, "document": "telegram-file-id", "caption": "doc"},
        )
        history = (await client.get("/api/v1/send-history")).json()

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert seen["calls"][-1]["method"] == "sendDocument"
    assert seen["calls"][-1]["payload"]["document"] == "telegram-file-id"
    assert history[0]["media_type"] == "document"


async def test_telegram_compatible_unknown_token_returns_telegram_error() -> None:
    client = await _client()
    async with client:
        response = await client.post(
            "/bot123456:missing_123456789012345/sendMessage",
            json={"chat_id": -100123, "text": "hello"},
        )

    assert response.status_code == 401
    assert response.json() == {
        "ok": False,
        "error_code": 401,
        "description": "Unauthorized",
    }


async def test_protected_domain_requires_permanent_api_token_for_telegram_compat() -> None:
    client = await _client()
    async with client:
        await _create_bot(client)
        blocked = await client.post(
            "/bot123456:ABCdef_123456789012345/sendMessage",
            json={"chat_id": -100123, "text": "hello"},
            headers={"Host": "tg.sh-inc.ru"},
        )
        token = (
            await client.post(
                "/api/v1/auth/tokens",
                json={"name": "telegram-compat"},
                headers={"Host": "127.0.0.1:8000"},
            )
        ).json()["token"]
        allowed = await client.post(
            "/bot123456:ABCdef_123456789012345/sendMessage",
            json={"chat_id": -100123, "text": "hello"},
            headers={"Host": "tg.sh-inc.ru", "X-API-Token": token},
        )

    assert blocked.status_code == 401
    assert allowed.status_code == 200
