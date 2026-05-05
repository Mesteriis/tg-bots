import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.core.orm import Base
from tg_bot_aggregator.infra.events import MemoryEventBus
from tg_bot_aggregator.infra.telegram_client import TelegramBotApiClient
from tg_bot_aggregator.main import create_app


async def _client(tmp_path: Path) -> tuple[httpx.AsyncClient, Path]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    auth_file = tmp_path / "admin-auth.json"
    app = create_app(
        settings=Settings(
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            ADMIN_AUTH_FILE=str(auth_file),
            PROTECTED_API_HOSTS="tg.sh-inc.ru,tg.sh-inc.dev",
        ),
        session_factory=session_factory,
        event_bus=MemoryEventBus(),
        bot_api_client=TelegramBotApiClient("http://telegram-bot-api:8081"),
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost:8000",
    )
    return client, auth_file


async def test_admin_state_reports_bootstrap_mode_when_auth_file_is_missing(tmp_path: Path) -> None:
    client, auth_file = await _client(tmp_path)

    async with client:
        response = await client.get("/api/v1/auth/admin/state")

    assert not auth_file.exists()
    assert response.status_code == 200
    assert response.json()["bootstrap_required"] is True
    assert response.json()["username"] == "admin"
    assert response.json()["authenticated"] is False
    assert response.json()["passkey_configured"] is False


async def test_local_admin_api_requires_browser_session(tmp_path: Path) -> None:
    client, _ = await _client(tmp_path)

    async with client:
        response = await client.get("/api/v1/health", headers={"Host": "localhost:8000"})

    assert response.status_code == 401
    assert response.json() == {"detail": "admin session required"}


async def test_bootstrap_rotate_creates_auth_file_and_opens_admin_session(tmp_path: Path) -> None:
    client, auth_file = await _client(tmp_path)

    async with client:
        rotated = await client.post(
            "/api/v1/auth/admin/bootstrap",
            json={
                "current_username": "admin",
                "current_password": "12345678",
                "new_username": "owner",
                "new_password": "change-me-123",
            },
        )
        health = await client.get("/api/v1/health", headers={"Host": "localhost:8000"})
        state = await client.get("/api/v1/auth/admin/state")

    assert rotated.status_code == 204
    assert auth_file.exists()
    assert "tg_admin_session" in rotated.cookies
    assert health.status_code == 200
    assert state.json()["authenticated"] is True
    assert state.json()["bootstrap_required"] is False
    assert state.json()["username"] == "owner"


async def test_password_login_and_logout_roundtrip(tmp_path: Path) -> None:
    client, _ = await _client(tmp_path)

    async with client:
        await client.post(
            "/api/v1/auth/admin/bootstrap",
            json={
                "current_username": "admin",
                "current_password": "12345678",
                "new_username": "owner",
                "new_password": "change-me-123",
            },
        )
        logout = await client.post("/api/v1/auth/admin/logout")
        denied = await client.get("/api/v1/health", headers={"Host": "localhost:8000"})
        login = await client.post(
            "/api/v1/auth/admin/login",
            json={"username": "owner", "password": "change-me-123"},
        )
        allowed = await client.get("/api/v1/health", headers={"Host": "localhost:8000"})

    assert logout.status_code == 204
    assert denied.status_code == 401
    assert login.status_code == 200
    assert login.json()["authenticated"] is True
    assert allowed.status_code == 200


async def test_protected_domain_api_token_flow_remains_available_without_admin_session(
    tmp_path: Path,
) -> None:
    client, _ = await _client(tmp_path)

    async with client:
        await client.post(
            "/api/v1/auth/admin/bootstrap",
            json={
                "current_username": "admin",
                "current_password": "12345678",
                "new_username": "owner",
                "new_password": "change-me-123",
            },
        )
        created = await client.post(
            "/api/v1/auth/tokens",
            json={"name": "nginx-ui"},
            headers={"Host": "localhost:8000"},
        )
        await client.post("/api/v1/auth/admin/logout")
        token = created.json()["token"]
        protected = await client.get(
            "/api/v1/health",
            headers={"Host": "tg.sh-inc.dev", "X-API-Token": token},
        )

    assert created.status_code == 201
    assert protected.status_code == 200


async def test_injected_session_test_app_keeps_local_api_open_without_explicit_admin_auth_file(
) -> None:
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
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8000",
    ) as client:
        response = await client.get("/api/v1/health", headers={"Host": "127.0.0.1:8000"})

    assert response.status_code == 200


async def test_passkey_registration_roundtrip_persists_credential(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, _ = await _client(tmp_path)

    monkeypatch.setattr(
        "tg_bot_aggregator.api.v1.auth.verify_registration_response",
        lambda **_kwargs: SimpleNamespace(
            credential_id=b"cred-1",
            credential_public_key=b"\x01\x02\x03",
            sign_count=7,
        ),
    )

    async with client:
        await client.post(
            "/api/v1/auth/admin/bootstrap",
            json={
                "current_username": "admin",
                "current_password": "12345678",
                "new_username": "owner",
                "new_password": "change-me-123",
            },
        )
        options = await client.post(
            "/api/v1/auth/admin/passkeys/register/options",
            json={"label": "MacBook Touch ID"},
        )
        challenge_id = options.json()["challenge_id"]
        verified = await client.post(
            "/api/v1/auth/admin/passkeys/register/verify",
            json={
                "challenge_id": challenge_id,
                "credential": {
                    "id": "cred-1",
                    "response": {"transports": ["internal"]},
                },
            },
        )
        listed = await client.get("/api/v1/auth/admin/passkeys")
        state = await client.get("/api/v1/auth/admin/state")

    assert options.status_code == 200
    assert json.loads(options.json()["options_json"])["rp"]["id"] == "localhost"
    assert verified.status_code == 201
    assert listed.status_code == 200
    assert listed.json()[0]["label"] == "MacBook Touch ID"
    assert listed.json()[0]["transports"] == ["internal"]
    assert state.json()["passkey_configured"] is True


async def test_passkey_auth_roundtrip_restores_admin_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, _ = await _client(tmp_path)

    monkeypatch.setattr(
        "tg_bot_aggregator.api.v1.auth.verify_registration_response",
        lambda **_kwargs: SimpleNamespace(
            credential_id=b"cred-1",
            credential_public_key=b"\xAA\xBB",
            sign_count=3,
        ),
    )
    monkeypatch.setattr(
        "tg_bot_aggregator.api.v1.auth.verify_authentication_response",
        lambda **_kwargs: SimpleNamespace(new_sign_count=4),
    )

    async with client:
        await client.post(
            "/api/v1/auth/admin/bootstrap",
            json={
                "current_username": "admin",
                "current_password": "12345678",
                "new_username": "owner",
                "new_password": "change-me-123",
            },
        )
        options = await client.post(
            "/api/v1/auth/admin/passkeys/register/options",
            json={"label": "MacBook Touch ID"},
        )
        await client.post(
            "/api/v1/auth/admin/passkeys/register/verify",
            json={
                "challenge_id": options.json()["challenge_id"],
                "credential": {
                    "id": "cred-1",
                    "response": {"transports": ["internal"]},
                },
            },
        )
        await client.post("/api/v1/auth/admin/logout")
        auth_options = await client.post("/api/v1/auth/admin/passkeys/auth/options")
        verified = await client.post(
            "/api/v1/auth/admin/passkeys/auth/verify",
            json={
                "challenge_id": auth_options.json()["challenge_id"],
                "credential": {"id": "cred-1"},
            },
        )
        health = await client.get("/api/v1/health", headers={"Host": "localhost:8000"})

    assert auth_options.status_code == 200
    payload = json.loads(auth_options.json()["options_json"])
    assert payload["rpId"] == "localhost"
    assert verified.status_code == 200
    assert verified.json()["authenticated"] is True
    assert "tg_admin_session" in verified.cookies
    assert health.status_code == 200
