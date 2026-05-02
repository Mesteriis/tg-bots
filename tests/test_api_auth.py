import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.events import MemoryEventBus
from tg_bot_aggregator.main import create_app
from tg_bot_aggregator.models import Base
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient


async def _client() -> httpx.AsyncClient:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app(
        settings=Settings(
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            PROTECTED_API_HOSTS="tg.sh-inc.ru,tg.sh-inc.dev",
        ),
        session_factory=session_factory,
        event_bus=MemoryEventBus(),
        bot_api_client=TelegramBotApiClient("http://telegram-bot-api:8081"),
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8000",
    )


async def test_local_api_does_not_require_api_token() -> None:
    client = await _client()

    async with client:
        response = await client.get("/api/v1/health", headers={"Host": "127.0.0.1:8000"})

    assert response.status_code == 200


async def test_protected_domain_requires_api_token() -> None:
    client = await _client()

    async with client:
        response = await client.get("/api/v1/health", headers={"Host": "tg.sh-inc.ru"})

    assert response.status_code == 401
    assert response.json() == {"detail": "api token required for protected host"}


async def test_dashboard_can_create_and_use_permanent_api_token_for_protected_domain() -> None:
    client = await _client()

    async with client:
        created = await client.post(
            "/api/v1/auth/tokens",
            json={"name": "nginx-ui"},
            headers={"Host": "127.0.0.1:8000"},
        )
        token = created.json()["token"]
        protected = await client.get(
            "/api/v1/health",
            headers={"Host": "tg.sh-inc.dev", "X-API-Token": token},
        )
        listed = await client.get(
            "/api/v1/auth/tokens",
            headers={"Host": "tg.sh-inc.dev", "Authorization": f"Bearer {token}"},
        )

    assert created.status_code == 201
    assert token.startswith("tga_")
    assert protected.status_code == 200
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "nginx-ui"
    assert "token" not in listed.json()[0]


async def test_auth_session_sets_cookie_for_eventsource() -> None:
    client = await _client()

    async with client:
        token = (
            await client.post(
                "/api/v1/auth/tokens",
                json={"name": "browser"},
                headers={"Host": "127.0.0.1:8000"},
            )
        ).json()["token"]
        session_response = await client.post(
            "/api/v1/auth/session",
            json={"token": token},
            headers={"Host": "tg.sh-inc.ru"},
        )
        health = await client.get("/api/v1/health", headers={"Host": "tg.sh-inc.ru"})

    assert session_response.status_code == 204
    assert "tg_api_token" in session_response.cookies
    assert health.status_code == 200


async def test_revoked_api_token_is_rejected() -> None:
    client = await _client()

    async with client:
        created = await client.post(
            "/api/v1/auth/tokens",
            json={"name": "temporary"},
            headers={"Host": "127.0.0.1:8000"},
        )
        token_payload = created.json()
        deleted = await client.delete(
            f"/api/v1/auth/tokens/{token_payload['id']}",
            headers={"Host": "tg.sh-inc.dev", "X-API-Token": token_payload["token"]},
        )
        protected = await client.get(
            "/api/v1/health",
            headers={"Host": "tg.sh-inc.dev", "X-API-Token": token_payload["token"]},
        )

    assert deleted.status_code == 204
    assert protected.status_code == 401
