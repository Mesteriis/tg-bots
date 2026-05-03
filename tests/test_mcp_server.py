import inspect
from datetime import timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.events import MemoryEventBus
from tg_bot_aggregator.mcp_catalog import MCP_TOOL_DEFINITIONS
from tg_bot_aggregator.mcp_server import create_mcp_asgi_app, create_mcp_server
from tg_bot_aggregator.models import Base, utc_now
from tg_bot_aggregator.repositories import BotRepository, SendHistoryRepository
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
    }.issubset(names)
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
