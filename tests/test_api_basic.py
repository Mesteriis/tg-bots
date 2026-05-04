from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.infra.events import MemoryEventBus
from tg_bot_aggregator.infra.telegram_client import TelegramBotApiClient
from tg_bot_aggregator.main import create_app
from tg_bot_aggregator.models import Base


async def _client(
    handler: httpx.MockTransport | None = None,
    raise_app_exceptions: bool = True,
    settings: Settings | None = None,
    enqueue_send_history: Callable[[int], Awaitable[str | None]] | None = None,
) -> tuple[httpx.AsyncClient, MemoryEventBus]:
    resolved_settings = settings or Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:")
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
        settings=resolved_settings,
        session_factory=session_factory,
        event_bus=event_bus,
        bot_api_client=bot_api,
        enqueue_send_history=enqueue_send_history,
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=app,
            raise_app_exceptions=raise_app_exceptions,
        ),
        base_url="http://test",
    )
    return client, event_bus


async def test_media_listing_is_read_only_and_relative(tmp_path: Path) -> None:
    (tmp_path / "outbox").mkdir()
    (tmp_path / "outbox" / "release.mp4").write_bytes(b"video")
    client, _ = await _client(
        settings=Settings(
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            SHARED_MEDIA_ROOT=str(tmp_path),
        )
    )

    async with client:
        response = await client.get("/api/v1/media", params={"path": "outbox"})
        traversal = await client.get("/api/v1/media", params={"path": "../"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["relative_path"] == "outbox"
    assert payload["items"][0]["relative_path"] == "outbox/release.mp4"
    assert payload["items"][0]["media_type"] == "video"
    assert str(tmp_path) not in payload["items"][0]["relative_path"]
    assert traversal.status_code == 400


async def test_missing_shared_media_root_is_reported_cleanly(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing-media"
    client, _ = await _client(
        settings=Settings(
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            SHARED_MEDIA_ROOT=str(missing_root),
        )
    )

    async with client:
        health = await client.get("/api/v1/health")
        media = await client.get("/api/v1/media")

    health_payload = health.json()
    assert health_payload["shared_media_available"] is False
    assert "not available" in health_payload["shared_media_error"]
    assert health_payload["max_local_file_bytes"] == 2_097_152_000
    assert media.status_code == 400
    assert "not available" in media.json()["detail"]


async def test_shared_media_can_require_real_mountpoint(tmp_path: Path) -> None:
    client, _ = await _client(
        settings=Settings(
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            SHARED_MEDIA_ROOT=str(tmp_path),
            SHARED_MEDIA_REQUIRE_MOUNT=True,
        )
    )

    async with client:
        health = await client.get("/api/v1/health")

    payload = health.json()
    assert payload["shared_media_available"] is False
    assert payload["shared_media_mount_required"] is True
    assert payload["shared_media_mounted"] is False
    assert "not mounted" in payload["shared_media_error"]


async def test_favicon_and_mcp_connection_info_are_available() -> None:
    client, _ = await _client()

    async with client:
        favicon = await client.get("/favicon.ico")
        info = await client.get("/api/v1/mcp/connection-info")

    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/")
    payload = info.json()
    assert payload["streamable_http"]["path"] == "/mcp/v1/"
    assert payload["legacy_sse"]["path"] == "/mcp/v1/sse"
    assert "X-API-Token" in payload["required_headers"]
    assert "tg.sh-inc.ru" in payload["protected_hosts"]


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


async def test_create_duplicate_destination_returns_conflict() -> None:
    client, _ = await _client()
    async with client:
        bot = (await client.post("/api/v1/bots", json={"name": "ops", "token": "123:token"})).json()
        first = await client.post(
            "/api/v1/destinations",
            json={"bot_id": bot["id"], "kind": "channel", "chat_id": "@ops"},
        )
        duplicate = await client.post(
            "/api/v1/destinations",
            json={"bot_id": bot["id"], "kind": "channel", "chat_id": "@ops"},
        )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "destination with this bot, chat and thread already exists"


async def test_template_validation_endpoint_renders_valid_template() -> None:
    client, _ = await _client()
    async with client:
        response = await client.post(
            "/api/v1/templates/validate",
            json={
                "text": "Deploy {{name}} to {{env}} at {{date}}",
                "variables": {"name": "api", "env": "prod"},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["variables"] == ["date", "env", "name"]
    assert payload["missing_variables"] == []
    assert payload["rendered_text"].startswith("Deploy api to prod at ")
    assert payload["error_message"] is None


async def test_template_validation_endpoint_reports_missing_variables() -> None:
    client, _ = await _client()
    async with client:
        response = await client.post(
            "/api/v1/templates/validate",
            json={"text": "Deploy {{name}} to {{env}}", "variables": {"name": "api"}},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["variables"] == ["env", "name"]
    assert payload["missing_variables"] == ["env"]
    assert payload["rendered_text"] is None
    assert payload["error_message"] == "missing template variables: env"


async def test_template_validation_endpoint_reports_invalid_syntax() -> None:
    client, _ = await _client()
    async with client:
        response = await client.post(
            "/api/v1/templates/validate",
            json={"text": "Deploy {{name", "variables": {"name": "api"}},
        )

    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "variables": [],
        "missing_variables": [],
        "rendered_text": None,
        "error_message": "invalid template placeholder syntax; use {{name}}",
    }


async def test_template_versions_are_created_and_can_rollback() -> None:
    client, _ = await _client()
    async with client:
        created = (
            await client.post(
                "/api/v1/templates",
                json={"tag": "deploy", "title": "Deploy", "text": "v1"},
            )
        ).json()
        await client.patch(
            f"/api/v1/templates/{created['id']}",
            json={"title": "Deploy updated", "text": "v2"},
        )
        versions = (await client.get(f"/api/v1/templates/{created['id']}/versions")).json()
        rolled_back = (
            await client.post(
                f"/api/v1/templates/{created['id']}/rollback/{versions[0]['id']}"
            )
        ).json()
        final_versions = (await client.get(f"/api/v1/templates/{created['id']}/versions")).json()

    assert [version["version_number"] for version in versions] == [1, 2]
    assert versions[0]["text"] == "v1"
    assert rolled_back["title"] == "Deploy"
    assert rolled_back["text"] == "v1"
    assert final_versions[-1]["version_number"] == 3


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


async def test_dashboard_can_create_destination_from_diagnostic_update() -> None:
    client, _ = await _client()
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        created_update = (
            await client.post(
                "/api/v1/diagnostics/updates",
                json={
                    "update_id": 50,
                    "update_kind": "message",
                    "chat_id": "-100123",
                    "chat_type": "supergroup",
                    "chat_title": "Ops",
                    "message_id": 7,
                    "message_thread_id": 42,
                    "is_topic_message": True,
                    "raw_update": {"update_id": 50},
                },
            )
        ).json()
        destination = (
            await client.post(
                f"/api/v1/diagnostics/updates/{created_update['id']}/destination",
                json={"bot_id": bot["id"], "alias": "ops_topic"},
            )
        ).json()
        updates = (await client.get("/api/v1/diagnostics/updates")).json()

    assert destination["bot_id"] == bot["id"]
    assert destination["chat_id"] == "-100123"
    assert destination["message_thread_id"] == 42
    assert destination["alias"] == "ops_topic"
    assert updates[0]["chat_title"] == "Ops"


async def test_dashboard_can_manage_discovery_settings() -> None:
    client, _ = await _client()
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        listed = (await client.get("/api/v1/discovery/bots")).json()
        updated = (
            await client.patch(
                f"/api/v1/discovery/bots/{bot['id']}",
                json={"is_enabled": True},
            )
        ).json()

    assert listed == []
    assert updated["bot_id"] == bot["id"]
    assert updated["is_enabled"] is True


async def test_dashboard_can_manage_mcp_settings() -> None:
    client, _ = await _client()
    async with client:
        settings = (await client.get("/api/v1/mcp/settings")).json()
        patched = (
            await client.patch(
                "/api/v1/mcp/settings",
                json={"is_enabled": True, "enabled_tools": ["list_bots", "get_send_history"]},
            )
        ).json()

    assert settings["is_enabled"] is True
    assert settings["protected_hosts"] == ["tg.sh-inc.ru", "tg.sh-inc.dev"]
    assert {tool["name"] for tool in settings["tools"]} >= {"send_text", "create_api_token"}
    assert patched["tools_by_name"]["list_bots"]["enabled"] is True
    assert patched["tools_by_name"]["send_text"]["enabled"] is False


async def test_events_once_returns_sse_frame() -> None:
    client, event_bus = await _client()
    await event_bus.publish("send.created", {"send_history_id": 1})

    async with client:
        response = await client.get("/api/v1/events?once=true")

    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: send.created" in response.text


async def test_send_dry_run_does_not_create_history() -> None:
    client, _ = await _client()
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        destination = (
            await client.post(
                "/api/v1/destinations",
                json={
                    "bot_id": bot["id"],
                    "kind": "channel",
                    "chat_id": "@ops",
                    "alias": "ops_channel",
                },
            )
        ).json()
        dry_run = (
            await client.post(
                "/api/v1/send/text/dry-run",
                json={
                    "bot_id": bot["id"],
                    "destination_alias": "ops_channel",
                    "text": "hello",
                },
            )
        ).json()
        history = (await client.get("/api/v1/send-history")).json()

    assert destination["alias"] == "ops_channel"
    assert dry_run["method"] == "sendMessage"
    assert dry_run["payload"]["chat_id"] == "@ops"
    assert history == []


async def test_send_text_honors_idempotency_key() -> None:
    seen = {"send_count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/getMe"):
            return httpx.Response(
                200,
                json={"ok": True, "result": {"id": 123, "username": "ops_bot"}},
            )
        seen["send_count"] += 1
        return httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": seen["send_count"]}},
        )

    client, _ = await _client(handler=httpx.MockTransport(handler))
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        first = (
            await client.post(
                "/api/v1/send/text",
                json={"bot_id": bot["id"], "chat_id": "@ops", "text": "hello"},
                headers={"Idempotency-Key": "idem-rest-1"},
            )
        ).json()
        second = (
            await client.post(
                "/api/v1/send/text",
                json={"bot_id": bot["id"], "chat_id": "@ops", "text": "hello"},
                headers={"Idempotency-Key": "idem-rest-1"},
            )
        ).json()
        conflict = await client.post(
            "/api/v1/send/text",
            json={"bot_id": bot["id"], "chat_id": "@ops", "text": "changed"},
            headers={"Idempotency-Key": "idem-rest-1"},
        )

    assert first["id"] == second["id"]
    assert seen["send_count"] == 1
    assert conflict.status_code == 409


async def test_destination_check_updates_metadata_and_reports_partial_warnings() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/getMe"):
            return httpx.Response(
                200,
                json={"ok": True, "result": {"id": 123, "username": "ops_bot"}},
            )
        if str(request.url).endswith("/getChat"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "id": -100,
                        "type": "supergroup",
                        "title": "Updated Ops",
                        "username": "ops_chat",
                    },
                },
            )
        if str(request.url).endswith("/getChatMemberCount"):
            return httpx.Response(
                400,
                json={"ok": False, "error_code": 400, "description": "not enough rights"},
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    client, _ = await _client(handler=httpx.MockTransport(handler))
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        destination = (
            await client.post(
                "/api/v1/destinations",
                json={"bot_id": bot["id"], "kind": "channel", "chat_id": "-100"},
            )
        ).json()
        checked = (
            await client.post(f"/api/v1/destinations/{destination['id']}/check")
        ).json()
        loaded = (await client.get(f"/api/v1/destinations/{destination['id']}")).json()

    assert checked["ok"] is True
    assert checked["chat"]["title"] == "Updated Ops"
    assert checked["member_count"] is None
    assert checked["warnings"] == ["not enough rights"]
    assert loaded["title"] == "Updated Ops"
    assert loaded["username"] == "ops_chat"
    assert loaded["kind"] == "supergroup"


async def test_dashboard_can_manage_send_profiles() -> None:
    client, _ = await _client()
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        destination = (
            await client.post(
                "/api/v1/destinations",
                json={
                    "bot_id": bot["id"],
                    "kind": "channel",
                    "chat_id": "@ops",
                    "alias": "ops_channel",
                },
            )
        ).json()
        created_response = await client.post(
            "/api/v1/send-profiles",
            json={
                "name": "Deploy",
                "bot_id": bot["id"],
                "send_kind": "template",
                "destination_id": destination["id"],
                "template_tag": "deploy",
                "variables": {"service": "api"},
            },
        )
        created = created_response.json()
        listed = (await client.get("/api/v1/send-profiles")).json()
        patched = (
            await client.patch(
                f"/api/v1/send-profiles/{created['id']}",
                json={"name": "Deploy prod", "destination_alias": "ops_channel"},
            )
        ).json()
        loaded = (await client.get(f"/api/v1/send-profiles/{created['id']}")).json()
        deleted = await client.delete(f"/api/v1/send-profiles/{created['id']}")
        missing = await client.get(f"/api/v1/send-profiles/{created['id']}")

    assert created_response.status_code == 201
    assert created["variables"] == {"service": "api"}
    assert listed[0]["id"] == created["id"]
    assert patched["name"] == "Deploy prod"
    assert loaded["destination_alias"] == "ops_channel"
    assert deleted.status_code == 204
    assert missing.status_code == 404


async def test_unified_send_preview_does_not_create_history() -> None:
    client, _ = await _client()
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        destination = (
            await client.post(
                "/api/v1/destinations",
                json={"bot_id": bot["id"], "kind": "channel", "chat_id": "@ops"},
            )
        ).json()
        await client.post(
            "/api/v1/templates",
            json={"tag": "deploy", "title": "Deploy", "text": "Deploy {{service}}"},
        )
        preview_response = await client.post(
            "/api/v1/send/preview",
            json={
                "kind": "template",
                "bot_id": bot["id"],
                "destination_id": destination["id"],
                "tag": "deploy",
                "variables": {"service": "api"},
            },
        )
        history = (await client.get("/api/v1/send-history")).json()

    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["kind"] == "template"
    assert preview["method"] == "sendMessage"
    assert preview["payload"]["text"] == "Deploy api"
    assert history == []


async def test_send_history_retry_and_cancel_endpoints() -> None:
    seen = {"send_count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/getMe"):
            return httpx.Response(
                200,
                json={"ok": True, "result": {"id": 123, "username": "ops_bot"}},
            )
        seen["send_count"] += 1
        if seen["send_count"] == 1:
            return httpx.Response(
                500,
                json={"ok": False, "error_code": 500, "description": "boom"},
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    async def enqueue_send_history(send_history_id: int) -> str | None:
        return f"task-{send_history_id}"

    client, _ = await _client(
        handler=httpx.MockTransport(handler),
        enqueue_send_history=enqueue_send_history,
    )
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        failed = (
            await client.post(
                "/api/v1/send/text",
                json={"bot_id": bot["id"], "chat_id": "@ops", "text": "hello"},
            )
        ).json()
        retried = (
            await client.post(f"/api/v1/send-history/{failed['id']}/retry")
        ).json()
        queued = (
            await client.post(
                "/api/v1/send/text",
                json={
                    "bot_id": bot["id"],
                    "chat_id": "@ops",
                    "text": "queued",
                    "send_mode": "queued",
                },
            )
        ).json()
        cancelled = (
            await client.post(f"/api/v1/send-history/{queued['id']}/cancel")
        ).json()

    assert failed["status"] == "failed"
    assert retried["status"] == "queued"
    assert retried["queued_task_id"] == f"task-{failed['id']}"
    assert retried["telegram_message_id"] is None
    assert cancelled["status"] == "cancelled"


async def test_dashboard_can_create_list_and_load_send_batch() -> None:
    client, _ = await _client()
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        first = (
            await client.post(
                "/api/v1/destinations",
                json={"bot_id": bot["id"], "kind": "channel", "chat_id": "@one"},
            )
        ).json()
        second = (
            await client.post(
                "/api/v1/destinations",
                json={"bot_id": bot["id"], "kind": "channel", "chat_id": "@two"},
            )
        ).json()
        created_response = await client.post(
            "/api/v1/send-batches",
            json={
                "name": "Release",
                "bot_id": bot["id"],
                "send_kind": "text",
                "text": "hello",
                "destination_ids": [first["id"], second["id"]],
            },
        )
        created = created_response.json()
        listed = (await client.get("/api/v1/send-batches")).json()
        loaded = (await client.get(f"/api/v1/send-batches/{created['id']}")).json()

    assert created_response.status_code == 201
    assert created["status"] == "draft"
    assert len(created["items"]) == 2
    assert listed[0]["id"] == created["id"]
    assert loaded["items"][1]["chat_id"] == "@two"


async def test_send_batch_preview_enqueue_and_cancel_endpoints() -> None:
    async def enqueue_send_history(send_history_id: int) -> str | None:
        return f"task-{send_history_id}"

    client, _ = await _client(enqueue_send_history=enqueue_send_history)
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        destination = (
            await client.post(
                "/api/v1/destinations",
                json={"bot_id": bot["id"], "kind": "channel", "chat_id": "@ops"},
            )
        ).json()
        batch = (
            await client.post(
                "/api/v1/send-batches",
                json={
                    "name": "Release",
                    "bot_id": bot["id"],
                    "send_kind": "text",
                    "text": "hello",
                    "destination_ids": [destination["id"]],
                },
            )
        ).json()
        preview = (await client.post(f"/api/v1/send-batches/{batch['id']}/preview")).json()
        enqueued = (await client.post(f"/api/v1/send-batches/{batch['id']}/enqueue")).json()
        cancelled = (await client.post(f"/api/v1/send-batches/{batch['id']}/cancel")).json()

    assert preview["previews"][0]["payload"]["chat_id"] == "@ops"
    assert enqueued["status"] == "queued"
    assert enqueued["items"][0]["send_history_id"] is not None
    assert cancelled["status"] == "cancelled"


async def test_runtime_settings_patch_applies_without_restart() -> None:
    client, _ = await _client()
    async with client:
        before = (await client.get("/api/v1/health")).json()
        patched = (
            await client.patch(
                "/api/v1/operations/settings",
                json={
                    "max_local_file_bytes": 123456,
                    "telegram_bot_api_base_url": "http://127.0.0.1:9999",
                },
            )
        ).json()
        after = (await client.get("/api/v1/health")).json()

    assert before["max_local_file_bytes"] != 123456
    assert patched["max_local_file_bytes"] == 123456
    assert after["max_local_file_bytes"] == 123456
    assert after["bot_api_base_url"] == "http://127.0.0.1:9999"


async def test_runtime_settings_patch_persists_local_secret_and_infra_settings() -> None:
    client, _ = await _client()
    async with client:
        patched = (
            await client.patch(
                "/api/v1/operations/settings",
                json={
                    "database_url": "sqlite+aiosqlite:///./local.db",
                    "redis_url": "redis://:pass@redis:6379/2",
                    "telegram_api_id": "12345",
                    "telegram_api_hash": "secret-hash",
                    "telethon_session_dir": "./sessions",
                    "cors_allowed_origins": ["http://localhost:8000", "http://tg.local"],
                    "mcp_allowed_origins": ["http://localhost:8000"],
                    "diagnostic_poll_timeout_seconds": 10,
                    "diagnostic_retry_delay_seconds": 1.5,
                    "discovery_poll_timeout_seconds": 11,
                    "discovery_retry_delay_seconds": 2.5,
                    "backup_schedule_enabled": True,
                    "backup_schedule_interval_seconds": 3600,
                    "backup_schedule_push_to_git": True,
                },
            )
        ).json()
        loaded = (await client.get("/api/v1/operations/settings")).json()

    assert patched["telegram_api_id"] == "12345"
    assert patched["telegram_api_hash"] == "secret-hash"
    assert patched["redis_url"] == "redis://:pass@redis:6379/2"
    assert loaded["database_url"] == "sqlite+aiosqlite:///./local.db"
    assert loaded["cors_allowed_origins"] == ["http://localhost:8000", "http://tg.local"]
    assert loaded["diagnostic_retry_delay_seconds"] == 1.5
    assert patched["backup_schedule_enabled"] is True
    assert loaded["backup_schedule_interval_seconds"] == 3600
    assert loaded["backup_schedule_push_to_git"] is True


async def test_backup_run_exports_json_snapshot() -> None:
    client, _ = await _client()
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        await client.post(
            "/api/v1/templates",
            json={"tag": "deploy", "title": "Deploy", "text": "done"},
        )
        await client.patch(
            "/api/v1/operations/settings",
            json={
                "redis_url": "redis://:secret@redis:6379/0",
                "telegram_api_hash": "secret-hash",
            },
        )
        run = (
            await client.post(
                "/api/v1/operations/backup/run",
                json={"include_secrets": False},
            )
        ).json()

    assert run["status"] == "succeeded"
    assert run["items_exported"] >= 2
    assert run["snapshot"]["bots"][0]["id"] == bot["id"]
    assert "token" not in run["snapshot"]["bots"][0]
    assert run["snapshot"]["templates"][0]["tag"] == "deploy"
    advanced = run["snapshot"]["runtime_advanced_settings"][0]["settings_json"]
    assert "redis_url" not in advanced
    assert "telegram_api_hash" not in advanced


async def test_backup_run_includes_secrets_when_github_repo_is_private() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://api.github.com/repos/acme/tg-bots":
            return httpx.Response(200, json={"private": True, "full_name": "acme/tg-bots"})
        if str(request.url).endswith("/getMe"):
            return httpx.Response(
                200,
                json={"ok": True, "result": {"id": 123, "username": "ops_bot"}},
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 88}})

    client, _ = await _client(handler=httpx.MockTransport(handler))
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        await client.patch(
            "/api/v1/operations/settings",
            json={
                "backup_git_repo_url": "https://github.com/acme/tg-bots.git",
                "backup_git_service": "github",
                "backup_git_api_token": "github-token",
                "redis_url": "redis://:secret@redis:6379/0",
            },
        )
        run = (
            await client.post(
                "/api/v1/operations/backup/run",
                json={"include_secrets": False},
            )
        ).json()

    assert run["snapshot"]["backup_policy"]["repo"]["service"] == "github"
    assert run["snapshot"]["backup_policy"]["repo"]["is_private"] is True
    assert run["snapshot"]["backup_policy"]["include_secrets"] is True
    assert run["snapshot"]["bots"][0]["id"] == bot["id"]
    assert run["snapshot"]["bots"][0]["token"] == "123:token"
    assert (
        run["snapshot"]["runtime_advanced_settings"][0]["settings_json"]["redis_url"]
        == "redis://:secret@redis:6379/0"
    )


async def test_backup_run_excludes_secrets_when_gitea_repo_is_public() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://git.sh-inc.ru/api/v1/repos/avm/tg-bots":
            return httpx.Response(200, json={"private": False, "full_name": "avm/tg-bots"})
        if str(request.url).endswith("/getMe"):
            return httpx.Response(
                200,
                json={"ok": True, "result": {"id": 123, "username": "ops_bot"}},
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 88}})

    client, _ = await _client(handler=httpx.MockTransport(handler))
    async with client:
        await client.post("/api/v1/bots", json={"token": "123:token"})
        await client.patch(
            "/api/v1/operations/settings",
            json={
                "backup_git_repo_url": "https://git.sh-inc.ru/avm/tg-bots.git",
                "backup_git_service": "gitea",
                "backup_git_api_base_url": "https://git.sh-inc.ru/api/v1",
                "backup_git_api_token": "gitea-token",
                "redis_url": "redis://:secret@redis:6379/0",
            },
        )
        run = (
            await client.post(
                "/api/v1/operations/backup/run",
                json={"include_secrets": False},
            )
        ).json()

    assert run["snapshot"]["backup_policy"]["repo"]["service"] == "gitea"
    assert run["snapshot"]["backup_policy"]["repo"]["is_private"] is False
    assert run["snapshot"]["backup_policy"]["include_secrets"] is False
    assert "token" not in run["snapshot"]["bots"][0]
    advanced = run["snapshot"]["runtime_advanced_settings"][0]["settings_json"]
    assert "redis_url" not in advanced
    assert "backup_git_api_token" not in advanced


async def test_backup_repo_check_uses_configured_token_auth_without_oauth() -> None:
    seen: dict[str, str | None] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://api.github.com/repos/acme/tg-bots":
            seen["authorization"] = request.headers.get("authorization")
            return httpx.Response(200, json={"private": True, "full_name": "acme/tg-bots"})
        if str(request.url).endswith("/getMe"):
            return httpx.Response(
                200,
                json={"ok": True, "result": {"id": 123, "username": "ops_bot"}},
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 88}})

    client, _ = await _client(handler=httpx.MockTransport(handler))
    async with client:
        await client.patch(
            "/api/v1/operations/settings",
            json={
                "backup_git_repo_url": "https://github.com/acme/tg-bots.git",
                "backup_git_service": "github",
                "backup_git_auth_method": "token",
                "backup_git_api_token": "github-token",
            },
        )
        check = (await client.post("/api/v1/operations/backup/check-repo")).json()

    assert seen["authorization"] == "Bearer github-token"
    assert check["service"] == "github"
    assert check["is_private"] is True
    assert check["verified"] is True


async def test_backup_repo_check_can_skip_auth_header() -> None:
    seen: dict[str, str | None] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://git.sh-inc.ru/api/v1/repos/avm/tg-bots":
            seen["authorization"] = request.headers.get("authorization")
            return httpx.Response(200, json={"private": False, "full_name": "avm/tg-bots"})
        if str(request.url).endswith("/getMe"):
            return httpx.Response(
                200,
                json={"ok": True, "result": {"id": 123, "username": "ops_bot"}},
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 88}})

    client, _ = await _client(handler=httpx.MockTransport(handler))
    async with client:
        await client.patch(
            "/api/v1/operations/settings",
            json={
                "backup_git_repo_url": "https://git.sh-inc.ru/avm/tg-bots.git",
                "backup_git_service": "gitea",
                "backup_git_auth_method": "none",
                "backup_git_api_base_url": "https://git.sh-inc.ru/api/v1",
                "backup_git_api_token": "stored-but-disabled",
            },
        )
        check = (await client.post("/api/v1/operations/backup/check-repo")).json()

    assert seen["authorization"] is None
    assert check["service"] == "gitea"
    assert check["is_private"] is False
    assert check["verified"] is True


async def test_backup_preflight_reports_diff_policy_and_audit() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://api.github.com/repos/acme/tg-bots":
            return httpx.Response(200, json={"private": True, "full_name": "acme/tg-bots"})
        if str(request.url).endswith("/getMe"):
            return httpx.Response(
                200,
                json={"ok": True, "result": {"id": 123, "username": "ops_bot"}},
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 88}})

    client, _ = await _client(handler=httpx.MockTransport(handler))
    async with client:
        await client.patch(
            "/api/v1/operations/settings",
            json={
                "backup_git_repo_url": "https://github.com/acme/tg-bots.git",
                "backup_git_service": "github",
                "backup_git_api_token": "github-token",
            },
        )
        await client.post("/api/v1/bots", json={"token": "123:token"})
        await client.post(
            "/api/v1/templates",
            json={"tag": "deploy", "title": "Deploy", "text": "v1"},
        )
        first_run = (
            await client.post(
                "/api/v1/operations/backup/run",
                json={"include_secrets": False},
            )
        ).json()
        await client.post(
            "/api/v1/templates",
            json={"tag": "rollback", "title": "Rollback", "text": "v2"},
        )
        preflight = (
            await client.post(
                "/api/v1/operations/backup/preflight",
                json={"include_secrets": False, "push_to_git": False},
            )
        ).json()
        audit = (await client.get("/api/v1/audit")).json()

    assert preflight["ok"] is True
    assert preflight["include_secrets"] is True
    assert preflight["repo"]["is_private"] is True
    assert preflight["diff"]["base_run_id"] == first_run["id"]
    sections = {item["section"]: item for item in preflight["diff"]["sections"]}
    assert sections["templates"]["changed"] is True
    assert sections["templates"]["before_count"] == 1
    assert sections["templates"]["after_count"] == 2
    actions = [event["action"] for event in audit]
    assert "backup.run" in actions
    assert "backup.preflight" in actions


async def test_backup_diff_endpoint_uses_latest_successful_snapshot() -> None:
    client, _ = await _client()
    async with client:
        await client.post(
            "/api/v1/templates",
            json={"tag": "deploy", "title": "Deploy", "text": "v1"},
        )
        first_run = (
            await client.post(
                "/api/v1/operations/backup/run",
                json={"include_secrets": False},
            )
        ).json()
        await client.post(
            "/api/v1/templates",
            json={"tag": "ops", "title": "Ops", "text": "v2"},
        )
        diff = (await client.post("/api/v1/operations/backup/diff")).json()

    assert diff["base_run_id"] == first_run["id"]
    sections = {item["section"]: item for item in diff["sections"]}
    assert sections["templates"] == {
        "section": "templates",
        "before_count": 1,
        "after_count": 2,
        "changed": True,
        "row_changes": 1,
    }
    assert diff["rows"][0]["section"] == "templates"
    assert diff["rows"][0]["action"] == "added"


async def test_health_reports_backup_configuration_and_last_run() -> None:
    client, _ = await _client()
    async with client:
        await client.patch(
            "/api/v1/operations/settings",
            json={"backup_git_repo_url": "https://github.com/acme/tg-bots.git"},
        )
        run = (
            await client.post(
                "/api/v1/operations/backup/run",
                json={"include_secrets": False},
            )
        ).json()
        health = (await client.get("/api/v1/health")).json()

    assert health["backup_configured"] is True
    assert health["backup_last_status"] == "succeeded"
    assert health["backup_last_run_id"] == run["id"]
    assert health["backup_last_error"] is None


async def test_backup_import_preview_and_apply_restore_snapshot() -> None:
    client, _ = await _client()
    async with client:
        await client.post(
            "/api/v1/templates",
            json={"tag": "deploy", "title": "Deploy", "text": "v1"},
        )
        backup = (
            await client.post(
                "/api/v1/operations/backup/run",
                json={"include_secrets": True},
            )
        ).json()["snapshot"]
        await client.post(
            "/api/v1/templates",
            json={"tag": "ops", "title": "Ops", "text": "v2"},
        )
        preview = (
            await client.post(
                "/api/v1/operations/backup/import/preview",
                json={"snapshot": backup},
            )
        ).json()
        rejected = await client.post(
            "/api/v1/operations/backup/import/apply",
            json={"snapshot": backup, "confirm": "NOPE"},
        )
        applied = (
            await client.post(
                "/api/v1/operations/backup/import/apply",
                json={"snapshot": backup, "confirm": "RESTORE"},
            )
        ).json()
        templates = (await client.get("/api/v1/templates")).json()
        backup_runs = (await client.get("/api/v1/operations/backup/runs")).json()
        audit = (await client.get("/api/v1/audit")).json()

    assert preview["ok"] is True
    assert preview["diff"]["changed_sections"] >= 1
    assert preview["diff"]["sections_by_name"]["templates"]["before_count"] == 2
    assert preview["diff"]["sections_by_name"]["templates"]["after_count"] == 1
    assert rejected.status_code == 400
    assert applied["status"] == "restored"
    assert applied["restored_sections"] >= 1
    assert applied["safety_backup_run_id"] is not None
    assert [template["tag"] for template in templates] == ["deploy"]
    safety_run = next(run for run in backup_runs if run["id"] == applied["safety_backup_run_id"])
    assert safety_run["status"] == "pre_restore"
    assert [template["tag"] for template in safety_run["snapshot"]["templates"]] == [
        "deploy",
        "ops",
    ]
    assert "backup.import_preview" in [event["action"] for event in audit]
    assert "backup.import_apply" in [event["action"] for event in audit]


async def test_backup_run_restore_preview_and_apply_selected_sections_with_row_diff() -> None:
    client, _ = await _client()
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        await client.post(
            "/api/v1/templates",
            json={"tag": "deploy", "title": "Deploy", "text": "v1"},
        )
        destination = (
            await client.post(
                "/api/v1/destinations",
                json={"bot_id": bot["id"], "kind": "channel", "chat_id": "@ops"},
            )
        ).json()
        backup_run = (
            await client.post(
                "/api/v1/operations/backup/run",
                json={"include_secrets": True},
            )
        ).json()
        template = (await client.get("/api/v1/templates")).json()[0]
        await client.patch(
            f"/api/v1/templates/{template['id']}",
            json={"text": "v2"},
        )
        await client.post(
            "/api/v1/templates",
            json={"tag": "ops", "title": "Ops", "text": "new"},
        )
        await client.post(
            "/api/v1/destinations",
            json={"bot_id": bot["id"], "kind": "channel", "chat_id": "@keep"},
        )

        preview = (
            await client.post(
                f"/api/v1/operations/backup/runs/{backup_run['id']}/restore-preview",
                json={"sections": ["templates"]},
            )
        ).json()
        rejected = await client.post(
            f"/api/v1/operations/backup/runs/{backup_run['id']}/restore",
            json={"sections": ["templates"], "confirm": "NOPE"},
        )
        applied = (
            await client.post(
                f"/api/v1/operations/backup/runs/{backup_run['id']}/restore",
                json={"sections": ["templates"], "confirm": "RESTORE"},
            )
        ).json()
        templates = (await client.get("/api/v1/templates")).json()
        destinations = (await client.get("/api/v1/destinations")).json()
        audit = (await client.get("/api/v1/audit")).json()

    assert preview["ok"] is True
    assert preview["selected_sections"] == ["templates"]
    assert preview["expanded_sections"] == ["templates", "template_versions"]
    assert preview["diff"]["sections_by_name"]["templates"]["changed"] is True
    assert preview["diff"]["sections_by_name"]["templates"]["row_changes"] >= 1
    assert any(
        row["section"] == "templates" and row["action"] in {"changed", "removed"}
        for row in preview["diff"]["rows"]
    )
    assert rejected.status_code == 400
    assert applied["status"] == "restored"
    assert applied["restored_sections"] == 2
    assert applied["selected_sections"] == ["templates"]
    assert [template["tag"] for template in templates] == ["deploy"]
    assert templates[0]["text"] == "v1"
    assert {item["chat_id"] for item in destinations} == {destination["chat_id"], "@keep"}
    assert "backup.restore_run_preview" in [event["action"] for event in audit]
    assert "backup.restore_run_apply" in [event["action"] for event in audit]


async def test_backup_run_restore_destinations_blocks_missing_bot_references() -> None:
    client, _ = await _client()
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        await client.post(
            "/api/v1/destinations",
            json={"bot_id": bot["id"], "kind": "channel", "chat_id": "@ops"},
        )
        backup_run = (
            await client.post(
                "/api/v1/operations/backup/run",
                json={"include_secrets": True},
            )
        ).json()
        await client.delete(f"/api/v1/bots/{bot['id']}")

        preview = (
            await client.post(
                f"/api/v1/operations/backup/runs/{backup_run['id']}/restore-preview",
                json={"sections": ["destinations"]},
            )
        ).json()
        applied = await client.post(
            f"/api/v1/operations/backup/runs/{backup_run['id']}/restore",
            json={"sections": ["destinations"], "confirm": "RESTORE"},
        )

    assert preview["ok"] is False
    assert preview["blocked_sections"] == ["destinations"]
    assert "missing bot IDs: 1" in " ".join(preview["warnings"])
    assert applied.status_code == 400
    assert "missing bot IDs: 1" in applied.json()["detail"]


async def test_backup_import_rejects_redacted_snapshot_with_missing_required_secrets() -> None:
    client, _ = await _client()
    async with client:
        await client.post("/api/v1/bots", json={"token": "123:token"})
        redacted = (
            await client.post(
                "/api/v1/operations/backup/run",
                json={"include_secrets": False},
            )
        ).json()["snapshot"]
        preview = (
            await client.post(
                "/api/v1/operations/backup/import/preview",
                json={"snapshot": redacted},
            )
        ).json()
        applied = await client.post(
            "/api/v1/operations/backup/import/apply",
            json={"snapshot": redacted, "confirm": "RESTORE"},
        )

    assert preview["ok"] is False
    assert "bots" in preview["blocked_sections"]
    assert applied.status_code == 400
    assert "missing required fields" in applied.json()["detail"]


async def test_send_preflight_returns_checks_without_sending() -> None:
    seen: dict[str, int] = {"send_count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/getMe"):
            return httpx.Response(
                200,
                json={"ok": True, "result": {"id": 123, "username": "ops_bot"}},
            )
        seen["send_count"] += 1
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 10}})

    client, _ = await _client(handler=httpx.MockTransport(handler))
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        preflight = (
            await client.post(
                "/api/v1/send/preflight",
                json={"kind": "text", "bot_id": bot["id"], "chat_id": "@ops", "text": "hello"},
            )
        ).json()

    assert preflight["ok"] is True
    assert {check["name"] for check in preflight["checks"]} >= {"bot", "target", "payload"}
    assert seen["send_count"] == 0


async def test_send_policy_rate_limit_rejects_excess_sends() -> None:
    client, _ = await _client()
    async with client:
        await client.patch(
            "/api/v1/operations/settings",
            json={"policy_enabled": True, "rate_limit_per_minute": 1},
        )
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        first = await client.post(
            "/api/v1/send/text",
            json={"bot_id": bot["id"], "chat_id": "@ops", "text": "one"},
        )
        second = await client.post(
            "/api/v1/send/text",
            json={"bot_id": bot["id"], "chat_id": "@ops", "text": "two"},
        )

    assert first.status_code == 200
    assert second.status_code == 400
    assert "rate limit" in second.json()["detail"]


async def test_destination_check_persists_health_snapshot() -> None:
    client, _ = await _client()
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        destination = (
            await client.post(
                "/api/v1/destinations",
                json={"bot_id": bot["id"], "kind": "channel", "chat_id": "@ops"},
            )
        ).json()
        await client.post(f"/api/v1/destinations/{destination['id']}/check")
        health = (await client.get(f"/api/v1/destinations/{destination['id']}/health")).json()

    assert health["status"] == "ok"
    assert health["destination_id"] == destination["id"]
    assert health["last_member_count"] is None


async def test_dead_letter_and_scheduled_send_are_exposed() -> None:
    seen: dict[str, int] = {"send_count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/getMe"):
            return httpx.Response(
                200,
                json={"ok": True, "result": {"id": 123, "username": "ops_bot"}},
            )
        seen["send_count"] += 1
        return httpx.Response(
            500,
            json={"ok": False, "error_code": 500, "description": "boom"},
        )

    send_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    client, _ = await _client(handler=httpx.MockTransport(handler))
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        failed = (
            await client.post(
                "/api/v1/send/text",
                json={"bot_id": bot["id"], "chat_id": "@ops", "text": "fail"},
            )
        ).json()
        scheduled = (
            await client.post(
                "/api/v1/send/text",
                json={
                    "bot_id": bot["id"],
                    "chat_id": "@ops",
                    "text": "later",
                    "send_at": send_at,
                },
            )
        ).json()
        dead_letter = (await client.get("/api/v1/send-history/dead-letter")).json()
        due = (await client.get("/api/v1/send-history/due")).json()

    assert failed["status"] == "failed"
    assert scheduled["status"] == "queued"
    assert datetime.fromisoformat(scheduled["next_retry_at"].replace("Z", "+00:00")) == (
        datetime.fromisoformat(send_at)
    )
    assert [row["id"] for row in dead_letter] == [failed["id"]]
    assert due == []
    assert seen["send_count"] == 1


async def test_batch_read_includes_progress_counters() -> None:
    client, _ = await _client()
    async with client:
        bot = (await client.post("/api/v1/bots", json={"token": "123:token"})).json()
        batch = (
            await client.post(
                "/api/v1/send-batches",
                json={
                    "name": "Release",
                    "bot_id": bot["id"],
                    "send_kind": "text",
                    "text": "hello",
                    "chat_ids": ["@one", "@two"],
                },
            )
        ).json()
        loaded = (await client.get(f"/api/v1/send-batches/{batch['id']}")).json()

    assert loaded["progress"] == {"pending": 2, "total": 2}
