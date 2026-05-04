import inspect
from datetime import timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.events import MemoryEventBus
from tg_bot_aggregator.mcp_catalog import MCP_DEFAULT_ENABLED_TOOL_NAMES, MCP_TOOL_DEFINITIONS
from tg_bot_aggregator.mcp_server import create_mcp_asgi_app, create_mcp_server
from tg_bot_aggregator.models import Base, utc_now
from tg_bot_aggregator.repositories import (
    BotRepository,
    DestinationRepository,
    DiagnosticUpdateRepository,
    McpSettingsRepository,
    SendAttemptRepository,
    SendHistoryRepository,
)
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient


def test_mcp_catalog_contains_reliability_tools() -> None:
    tools = {tool.name: tool for tool in MCP_TOOL_DEFINITIONS}

    expected = {
        "get_reliability_summary": ("read", "read"),
        "get_reliability_graph": ("read", "read"),
        "list_send_attempts": ("read", "read"),
        "list_rate_limit_buckets": ("read", "read"),
        "release_stale_send_locks": ("task", "write"),
        "bulk_retry_sends": ("send", "write"),
        "bulk_cancel_sends": ("send", "write"),
    }

    for name, (category, risk) in expected.items():
        assert name in tools
        assert tools[name].category == category
        assert tools[name].risk == risk


def test_mcp_catalog_contains_telegram_ops_tools() -> None:
    tools = {tool.name: tool for tool in MCP_TOOL_DEFINITIONS}

    expected = {
        "inspect_bot_access": ("ops", "read"),
        "list_ops_facts": ("ops", "read"),
        "run_ops_scan": ("ops", "write"),
        "list_ops_recommendations": ("ops", "read"),
        "preview_ops_action": ("ops", "write"),
        "apply_ops_action": ("ops", "admin"),
        "dismiss_ops_recommendation": ("ops", "write"),
        "list_ops_rules": ("ops", "read"),
        "update_ops_rule": ("ops", "admin"),
        "run_ops_rule": ("ops", "admin"),
        "pause_ops_rule": ("ops", "admin"),
        "resume_ops_rule": ("ops", "admin"),
        "explain_failed_send": ("ops", "read"),
        "get_mcp_coverage_matrix": ("ops", "read"),
        "recommend_mcp_preset": ("ops", "read"),
    }

    for name, (category, risk) in expected.items():
        assert name in tools
        assert tools[name].category == category
        assert tools[name].risk == risk


def test_mcp_default_enabled_contains_only_read_telegram_ops_tools() -> None:
    tools = {tool.name: tool for tool in MCP_TOOL_DEFINITIONS if tool.category == "ops"}
    default_ops_tools = set(MCP_DEFAULT_ENABLED_TOOL_NAMES) & set(tools)

    assert default_ops_tools == {
        "list_ops_facts",
        "list_ops_recommendations",
        "list_ops_rules",
        "explain_failed_send",
        "get_mcp_coverage_matrix",
        "recommend_mcp_preset",
    }
    assert {tools[name].risk for name in default_ops_tools} == {"read"}


async def test_mcp_server_exposes_expected_tools() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    mcp = create_mcp_server(
        settings=Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:"),
        get_session_factory=lambda: session_factory,
        event_bus=MemoryEventBus(),
        bot_api_client=TelegramBotApiClient("http://telegram-bot-api:8081"),
    )

    maybe_tools = mcp.list_tools()
    tools = await maybe_tools if inspect.isawaitable(maybe_tools) else maybe_tools
    names = {tool.name for tool in tools}

    assert {
        "list_bots",
        "list_destinations",
        "list_message_templates",
        "send_text",
        "send_template",
        "send_file_from_shared_path",
        "refresh_analytics",
        "get_analytics_summary",
        "get_send_history",
        "list_api_tokens",
        "create_api_token",
        "revoke_api_token",
        "dry_run_send",
        "list_audit_events",
        "get_discovery_settings",
        "update_discovery_settings",
        "check_destination",
        "get_mcp_connection_info",
        "list_media",
        "list_send_profiles",
        "create_send_profile",
        "list_send_batches",
        "create_send_batch",
        "preview_send_batch",
        "enqueue_send_batch",
        "cancel_send_batch",
        "list_diagnostic_updates",
        "create_destination_from_diagnostic_update",
        "get_reliability_summary",
        "get_reliability_graph",
        "list_send_attempts",
        "list_rate_limit_buckets",
        "release_stale_send_locks",
        "bulk_retry_sends",
        "bulk_cancel_sends",
        "inspect_bot_access",
        "list_ops_facts",
        "run_ops_scan",
        "list_ops_recommendations",
        "preview_ops_action",
        "apply_ops_action",
        "dismiss_ops_recommendation",
        "list_ops_rules",
        "update_ops_rule",
        "run_ops_rule",
        "pause_ops_rule",
        "resume_ops_rule",
        "explain_failed_send",
        "get_mcp_coverage_matrix",
        "recommend_mcp_preset",
    }.issubset(names)
    await engine.dispose()


async def test_mcp_get_coverage_matrix_uses_default_tools_without_settings_row() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    mcp = create_mcp_server(
        settings=Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:"),
        get_session_factory=lambda: session_factory,
        event_bus=MemoryEventBus(),
        bot_api_client=TelegramBotApiClient("http://telegram-bot-api:8081"),
    )

    _content, structured = await mcp.call_tool("get_mcp_coverage_matrix", {})

    domains = {row["domain"] for row in structured["rows"]}
    assert {"telegram_ops", "send", "reliability", "operations_backup"} <= domains
    telegram_ops = next(row for row in structured["rows"] if row["domain"] == "telegram_ops")
    assert "run_ops_scan" in telegram_ops["missing_enabled_tools"]
    assert "run_ops_scan" not in structured["missing_catalog_tools"]
    async with session_factory() as session:
        assert await McpSettingsRepository(session).get() is None
    await engine.dispose()


async def test_mcp_recommend_read_only_preset_excludes_write_and_admin_tools() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    mcp = create_mcp_server(
        settings=Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:"),
        get_session_factory=lambda: session_factory,
        event_bus=MemoryEventBus(),
        bot_api_client=TelegramBotApiClient("http://telegram-bot-api:8081"),
    )

    _content, structured = await mcp.call_tool(
        "recommend_mcp_preset", {"preset": "read_only"}
    )

    tools_by_name = {tool.name: tool for tool in MCP_TOOL_DEFINITIONS}
    assert structured["preset"] == "read_only"
    assert "list_ops_facts" in structured["tools"]
    assert "run_ops_scan" not in structured["tools"]
    assert "preview_ops_action" not in structured["tools"]
    assert "apply_ops_action" not in structured["tools"]
    assert {tools_by_name[name].risk for name in structured["tools"]} == {"read"}
    async with session_factory() as session:
        assert await McpSettingsRepository(session).get() is None
    await engine.dispose()


async def test_mcp_connection_info_uses_default_tools_without_settings_row() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    mcp = create_mcp_server(
        settings=Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:"),
        get_session_factory=lambda: session_factory,
        event_bus=MemoryEventBus(),
        bot_api_client=TelegramBotApiClient("http://telegram-bot-api:8081"),
    )

    _content, structured = await mcp.call_tool("get_mcp_connection_info", {})

    assert structured["streamable_http"]["enabled"] is True
    assert structured["legacy_sse"]["enabled"] is True
    assert "list_bots" in structured["enabled_tools"]
    async with session_factory() as session:
        assert await McpSettingsRepository(session).get() is None
    await engine.dispose()


async def test_mcp_asgi_app_has_streamable_and_sse_routes() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    mcp = create_mcp_server(
        settings=Settings(),
        get_session_factory=lambda: session_factory,
        event_bus=MemoryEventBus(),
        bot_api_client=TelegramBotApiClient("http://telegram-bot-api:8081"),
    )

    app = create_mcp_asgi_app(mcp)
    paths = {getattr(route, "path", "") for route in app.routes}

    assert "/" in paths
    assert "/sse" in paths
    assert "/messages" in paths
    await engine.dispose()


async def test_mcp_bulk_retry_preserves_future_retry_schedule() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    future_retry_at = utc_now() + timedelta(minutes=10)

    async with session_factory() as session:
        bot = await BotRepository(session).create(name="ops", token="123:abc")
        row = await SendHistoryRepository(session).create(
            bot_id=bot.id,
            chat_id="@ops",
            media_type="none",
            status="dead_letter",
            send_mode="queued",
            next_retry_at=future_retry_at,
            request_payload_json={"method": "sendMessage", "chat_id": "@ops", "text": "hello"},
        )
        await McpSettingsRepository(session).upsert(
            is_enabled=True,
            enabled_tools_json=["bulk_retry_sends"],
        )
        await session.commit()
        row_id = row.id

    enqueued: list[int] = []

    async def enqueue_send_history(send_history_id: int) -> str | None:
        enqueued.append(send_history_id)
        return f"task-{send_history_id}"

    mcp = create_mcp_server(
        settings=Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:"),
        get_session_factory=lambda: session_factory,
        event_bus=MemoryEventBus(),
        bot_api_client=TelegramBotApiClient("http://telegram-bot-api:8081"),
        enqueue_send_history=enqueue_send_history,
    )

    _content, structured = await mcp.call_tool(
        "bulk_retry_sends", {"send_history_ids": [row_id]}
    )

    async with session_factory() as session:
        retried = await SendHistoryRepository(session).get(row_id)

    assert structured == {"changed": 1, "skipped": 0}
    assert retried is not None
    assert retried.status == "queued"
    assert retried.next_retry_at is not None
    assert retried.next_retry_at.replace(tzinfo=future_retry_at.tzinfo) == future_retry_at
    assert retried.queued_task_id is None
    assert enqueued == []
    await engine.dispose()


async def test_mcp_bulk_retry_enqueues_ready_rows() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        bot = await BotRepository(session).create(name="ops", token="123:abc")
        row = await SendHistoryRepository(session).create(
            bot_id=bot.id,
            chat_id="@ops",
            media_type="none",
            status="failed",
            send_mode="queued",
            request_payload_json={"method": "sendMessage", "chat_id": "@ops", "text": "hello"},
        )
        await McpSettingsRepository(session).upsert(
            is_enabled=True,
            enabled_tools_json=["bulk_retry_sends"],
        )
        await session.commit()
        row_id = row.id

    enqueued: list[int] = []

    async def enqueue_send_history(send_history_id: int) -> str | None:
        enqueued.append(send_history_id)
        return f"task-{send_history_id}"

    mcp = create_mcp_server(
        settings=Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:"),
        get_session_factory=lambda: session_factory,
        event_bus=MemoryEventBus(),
        bot_api_client=TelegramBotApiClient("http://telegram-bot-api:8081"),
        enqueue_send_history=enqueue_send_history,
    )

    _content, structured = await mcp.call_tool(
        "bulk_retry_sends", {"send_history_ids": [row_id]}
    )

    async with session_factory() as session:
        retried = await SendHistoryRepository(session).get(row_id)

    assert structured == {"changed": 1, "skipped": 0}
    assert retried is not None
    assert retried.status == "queued"
    assert retried.next_retry_at is None
    assert retried.queued_task_id == f"task-{row_id}"
    assert enqueued == [row_id]
    await engine.dispose()


async def test_mcp_telegram_ops_scan_preview_and_apply_flow() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        bot = await BotRepository(session).create(name="ops", token="123:abc")
        await DiagnosticUpdateRepository(session).create(
            update_id=500,
            update_kind="message",
            chat_id="-100500",
            chat_type="supergroup",
            chat_title="Ops Chat",
            chat_username="ops_chat",
            message_thread_id=77,
            is_topic_message=True,
            raw_update_json={"update_id": 500},
        )
        await McpSettingsRepository(session).upsert(
            is_enabled=True,
            enabled_tools_json=[
                "run_ops_scan",
                "list_ops_recommendations",
                "preview_ops_action",
                "apply_ops_action",
            ],
        )
        await session.commit()
        bot_id = bot.id

    mcp = create_mcp_server(
        settings=Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:"),
        get_session_factory=lambda: session_factory,
        event_bus=MemoryEventBus(),
        bot_api_client=TelegramBotApiClient("http://telegram-bot-api:8081"),
    )

    _content, scan = await mcp.call_tool("run_ops_scan", {})
    _content, recommendations = await mcp.call_tool(
        "list_ops_recommendations", {"status": "open"}
    )
    recommendations = recommendations["result"]
    recommendation_id = recommendations[0]["id"]
    _content, preview = await mcp.call_tool(
        "preview_ops_action", {"recommendation_id": recommendation_id}
    )
    _content, applied = await mcp.call_tool(
        "apply_ops_action", {"recommendation_id": recommendation_id}
    )

    async with session_factory() as session:
        destinations = await DestinationRepository(session).list()

    assert scan == {"facts_created": 1, "recommendations_created": 1}
    assert recommendations[0]["bot_id"] == bot_id
    assert preview["recommendation_id"] == recommendation_id
    assert preview["diff"]["operation"] == "create"
    assert applied["status"] == "applied"
    assert destinations[0].chat_id == "-100500"
    assert destinations[0].message_thread_id == 77
    await engine.dispose()


async def test_mcp_explain_failed_send_includes_attempts() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        bot = await BotRepository(session).create(name="ops", token="123:abc")
        row = await SendHistoryRepository(session).create(
            bot_id=bot.id,
            chat_id="@ops",
            media_type="none",
            status="deferred",
            send_mode="queued",
            error_code="429",
            error_message="Too Many Requests",
            last_error_kind="telegram_rate_limit",
            retry_after_seconds=30,
            request_payload_json={"method": "sendMessage", "chat_id": "@ops", "text": "hello"},
        )
        await SendAttemptRepository(session).create(
            send_history_id=row.id,
            attempt_number=1,
            status="deferred",
            telegram_error_code="429",
            error_kind="telegram_rate_limit",
            error_message="Too Many Requests",
            retry_after_seconds=30,
        )
        await session.commit()
        row_id = row.id

    mcp = create_mcp_server(
        settings=Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:"),
        get_session_factory=lambda: session_factory,
        event_bus=MemoryEventBus(),
        bot_api_client=TelegramBotApiClient("http://telegram-bot-api:8081"),
    )

    _content, structured = await mcp.call_tool(
        "explain_failed_send", {"send_history_id": row_id}
    )

    assert structured["send_history_id"] == row_id
    assert structured["status"] == "deferred"
    assert structured["last_error_kind"] == "telegram_rate_limit"
    assert structured["attempts"][0]["attempt_number"] == 1
    assert structured["attempts"][0]["retry_after_seconds"] == 30
    assert "429" in structured["summary"]
    await engine.dispose()
