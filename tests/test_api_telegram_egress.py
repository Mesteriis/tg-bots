import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.core.orm import Base
from tg_bot_aggregator.infra.telegram_client import TelegramBotApiClient
from tg_bot_aggregator.main import create_app


@pytest.fixture
async def telegram_egress_client(
    tmp_path,
) -> tuple[httpx.AsyncClient, async_sessionmaker]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app(
        Settings(
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            TELEGRAM_EGRESS_STATE_DIR=str(tmp_path),
        ),
        session_factory=session_factory,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, session_factory
    await engine.dispose()


async def test_get_telegram_egress_returns_runtime_status(
    telegram_egress_client: tuple[httpx.AsyncClient, async_sessionmaker],
) -> None:
    client, _ = telegram_egress_client

    response = await client.get("/api/v1/operations/telegram-egress")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "direct"
    assert payload["enabled"] is False
    assert payload["provider"] is None
    assert payload["provider_config_present"] is False
    assert payload["last_status"] == "disconnected"


async def test_patch_telegram_egress_updates_mode(
    telegram_egress_client: tuple[httpx.AsyncClient, async_sessionmaker],
) -> None:
    client, _ = telegram_egress_client

    response = await client.patch(
        "/api/v1/operations/telegram-egress",
        json={"mode": "wireguard", "enabled": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "wireguard"
    assert payload["enabled"] is True
    assert payload["provider"] == "wireguard"


async def test_check_telegram_egress_returns_provider_status(
    telegram_egress_client: tuple[httpx.AsyncClient, async_sessionmaker],
) -> None:
    client, _ = telegram_egress_client

    await client.patch(
        "/api/v1/operations/telegram-egress",
        json={"mode": "wireguard", "enabled": True},
    )
    response = await client.post("/api/v1/operations/telegram-egress/check")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "wireguard"
    assert payload["provider"] == "wireguard"
    assert payload["tunnel_state"] == "misconfigured"
    assert "profile.conf" in payload["last_error"]


async def test_upload_wireguard_config_marks_provider_present(
    telegram_egress_client: tuple[httpx.AsyncClient, async_sessionmaker],
) -> None:
    client, _ = telegram_egress_client

    await client.patch(
        "/api/v1/operations/telegram-egress",
        json={"mode": "wireguard", "enabled": True},
    )
    response = await client.post(
        "/api/v1/operations/telegram-egress/config",
        json={"provider": "wireguard", "profile_text": "[Interface]\nPrivateKey = x\n"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "wireguard"
    assert payload["provider_config_present"] is True


async def test_connect_wireguard_without_config_returns_400(
    telegram_egress_client: tuple[httpx.AsyncClient, async_sessionmaker],
) -> None:
    client, _ = telegram_egress_client

    await client.patch(
        "/api/v1/operations/telegram-egress",
        json={"mode": "wireguard", "enabled": True},
    )
    response = await client.post("/api/v1/operations/telegram-egress/connect")

    assert response.status_code == 400


async def test_check_openvpn_returns_provider_status(
    telegram_egress_client: tuple[httpx.AsyncClient, async_sessionmaker],
) -> None:
    client, _ = telegram_egress_client

    await client.patch(
        "/api/v1/operations/telegram-egress",
        json={"mode": "openvpn", "enabled": True},
    )
    await client.post(
        "/api/v1/operations/telegram-egress/config",
        json={"provider": "openvpn", "profile_text": "client\nremote vpn.example.com 1194\n"},
    )
    response = await client.post("/api/v1/operations/telegram-egress/check")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "openvpn"
    assert payload["provider"] == "openvpn"
    assert payload["tunnel_state"] == "disconnected"


async def test_connect_wireguard_updates_runtime_status_via_control_server(
    tmp_path,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT" and str(request.url) == "http://control/v1/vpn/status":
            return httpx.Response(200, json={"status": "running"})
        if request.method == "GET" and str(request.url) == "http://control/v1/vpn/status":
            return httpx.Response(200, json={"status": "running"})
        if request.method == "GET" and str(request.url) == "http://control/v1/publicip/ip":
            return httpx.Response(200, json={"public_ip": "198.51.100.11"})
        return httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "ops_bot"}})

    app = create_app(
        Settings(
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            TELEGRAM_EGRESS_STATE_DIR=str(tmp_path),
            TELEGRAM_EGRESS_CONTROL_URL="http://control",
        ),
        session_factory=session_factory,
        bot_api_client=TelegramBotApiClient(
            "https://api.telegram.org",
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await client.patch(
            "/api/v1/operations/telegram-egress",
            json={"mode": "wireguard", "enabled": True},
        )
        await client.post(
            "/api/v1/operations/telegram-egress/config",
            json={"provider": "wireguard", "profile_text": "[Interface]\nPrivateKey = x\n"},
        )
        response = await client.post("/api/v1/operations/telegram-egress/connect")
        state = await client.get("/api/v1/operations/telegram-egress")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tunnel_state"] == "connected"
    state_payload = state.json()
    assert state_payload["last_status"] == "connected"
    assert state_payload["last_egress_ip"] == "198.51.100.11"

    await engine.dispose()
