import importlib.util
from pathlib import Path

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_bot_aggregator.api_tokens import api_token_prefix, hash_api_token
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
    assert set(listed.json()[0]["scopes"]) == {
        "read",
        "send",
        "mcp_admin",
        "tg_compat",
        "ops_admin",
    }
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


async def test_protected_domain_enforces_api_token_scopes() -> None:
    client = await _client()

    async with client:
        read_token = (
            await client.post(
                "/api/v1/auth/tokens",
                json={"name": "reader", "scopes": ["read"]},
                headers={"Host": "127.0.0.1:8000"},
            )
        ).json()["token"]
        send_token = (
            await client.post(
                "/api/v1/auth/tokens",
                json={"name": "sender", "scopes": ["send"]},
                headers={"Host": "127.0.0.1:8000"},
            )
        ).json()["token"]

        read_ok = await client.get(
            "/api/v1/health",
            headers={"Host": "tg.sh-inc.ru", "X-API-Token": read_token},
        )
        read_denied_for_send = await client.post(
            "/api/v1/send/text",
            json={"bot_id": 1, "chat_id": "@ops", "text": "hello"},
            headers={"Host": "tg.sh-inc.ru", "X-API-Token": read_token},
        )
        send_denied_for_read = await client.get(
            "/api/v1/health",
            headers={"Host": "tg.sh-inc.ru", "X-API-Token": send_token},
        )

    assert read_ok.status_code == 200
    assert read_denied_for_send.status_code == 403
    assert read_denied_for_send.json() == {"detail": "api token scope 'send' required"}
    assert send_denied_for_read.status_code == 403
    assert send_denied_for_read.json() == {"detail": "api token scope 'read' required"}


async def test_dashboard_can_list_audit_events() -> None:
    client = await _client()

    async with client:
        created = await client.post(
            "/api/v1/auth/tokens",
            json={"name": "audited", "scopes": ["read"]},
            headers={"Host": "127.0.0.1:8000"},
        )
        audit = await client.get("/api/v1/audit", headers={"Host": "127.0.0.1:8000"})

    assert created.status_code == 201
    assert audit.status_code == 200
    assert audit.json()[0]["action"] == "auth.tokens.create"
    assert audit.json()[0]["status"] == "succeeded"


async def test_protected_host_ops_writes_require_ops_admin_scope() -> None:
    client = await _client()

    async with client:
        token = (
            await client.post(
                "/api/v1/auth/tokens",
                json={"name": "read-only", "scopes": ["read"]},
                headers={"Host": "127.0.0.1:8000"},
            )
        ).json()["token"]
        denied = await client.post(
            "/api/v1/ops/scan",
            headers={"Host": "tg.sh-inc.dev", "X-API-Token": token},
        )

    assert denied.status_code == 403
    assert "ops_admin" in denied.json()["detail"]


async def test_protected_host_ops_writes_allow_default_full_scope_token() -> None:
    client = await _client()

    async with client:
        token = (
            await client.post(
                "/api/v1/auth/tokens",
                json={"name": "ops-admin"},
                headers={"Host": "127.0.0.1:8000"},
            )
        ).json()["token"]
        allowed = await client.post(
            "/api/v1/ops/scan",
            headers={"Host": "tg.sh-inc.dev", "X-API-Token": token},
        )

    assert allowed.status_code == 200


async def test_protected_host_config_and_backup_writes_require_ops_admin_scope() -> None:
    client = await _client()

    async with client:
        token = (
            await client.post(
                "/api/v1/auth/tokens",
                json={"name": "read-only", "scopes": ["read"]},
                headers={"Host": "127.0.0.1:8000"},
            )
        ).json()["token"]
        responses = [
            await client.post(
                path,
                headers={"Host": "tg.sh-inc.dev", "X-API-Token": token},
                json={},
            )
            for path in (
                "/api/v1/config",
                "/api/v1/backup",
                "/api/v1/operations/backup/run",
            )
        ]

    assert [response.status_code for response in responses] == [403, 403, 403]
    assert all("ops_admin" in response.json()["detail"] for response in responses)


async def test_protected_host_operations_settings_requires_ops_admin_scope() -> None:
    client = await _client()

    async with client:
        mcp_admin_token = (
            await client.post(
                "/api/v1/auth/tokens",
                json={"name": "mcp-admin", "scopes": ["read", "mcp_admin"]},
                headers={"Host": "127.0.0.1:8000"},
            )
        ).json()["token"]
        full_token = (
            await client.post(
                "/api/v1/auth/tokens",
                json={"name": "full-admin"},
                headers={"Host": "127.0.0.1:8000"},
            )
        ).json()["token"]
        denied = await client.patch(
            "/api/v1/operations/settings",
            headers={"Host": "tg.sh-inc.dev", "X-API-Token": mcp_admin_token},
            json={"send_retry_max_attempts": 4},
        )
        allowed = await client.patch(
            "/api/v1/operations/settings",
            headers={"Host": "tg.sh-inc.dev", "X-API-Token": full_token},
            json={"send_retry_max_attempts": 4},
        )

    assert denied.status_code == 403
    assert denied.json() == {"detail": "api token scope 'ops_admin' required"}
    assert allowed.status_code == 200
    assert allowed.json()["send_retry_max_attempts"] == 4


async def test_legacy_mcp_admin_token_backfill_preserves_config_backup_write_access(
    tmp_path,
) -> None:
    db_path = tmp_path / "legacy-token.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    legacy_token = "tga_legacy"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            sa.text(
                """
                INSERT INTO api_tokens
                    (
                        name,
                        token_hash,
                        token_prefix,
                        scopes_json,
                        is_active,
                        created_at,
                        updated_at
                    )
                VALUES
                    (
                        :name,
                        :token_hash,
                        :token_prefix,
                        :scopes_json,
                        1,
                        CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP
                    )
                """
            ),
            {
                "name": "legacy-admin",
                "token_hash": hash_api_token(legacy_token),
                "token_prefix": api_token_prefix(legacy_token),
                "scopes_json": '["read", "send", "mcp_admin", "tg_compat"]',
            },
        )

        def run_backfill(sync_conn) -> None:
            migration_path = (
                Path(__file__).resolve().parents[1]
                / "alembic"
                / "versions"
                / "0008_telegram_ops_mcp_coverage.py"
            )
            spec = importlib.util.spec_from_file_location("migration_0008", migration_path)
            assert spec is not None
            assert spec.loader is not None
            migration_0008 = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration_0008)
            migration_0008.backfill_ops_admin_scope(sync_conn)

        await conn.run_sync(run_backfill)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app(
        settings=Settings(
            DATABASE_URL=f"sqlite+aiosqlite:///{db_path}",
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
        response = await client.post(
            "/api/v1/operations/backup/run",
            headers={"Host": "tg.sh-inc.dev", "X-API-Token": legacy_token},
            json={},
        )

    await engine.dispose()
    assert response.status_code != 403
