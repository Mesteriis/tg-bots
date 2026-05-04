import pytest
from mcp.server.fastmcp.exceptions import ToolError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.events import MemoryEventBus
from tg_bot_aggregator.mcp_server import create_mcp_server
from tg_bot_aggregator.models import Base
from tg_bot_aggregator.repositories import McpSettingsRepository
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient


async def test_mcp_settings_default_to_core_and_reliability_tools(db_session) -> None:
    settings = await McpSettingsRepository(db_session).get_or_create()

    assert settings.is_enabled is True
    assert "send_text" in settings.enabled_tools_json
    assert "create_api_token" in settings.enabled_tools_json
    assert "bulk_retry_sends" in settings.enabled_tools_json
    assert "get_reliability_summary" in settings.enabled_tools_json
    assert "list_ops_facts" in settings.enabled_tools_json
    assert "list_ops_recommendations" in settings.enabled_tools_json
    assert "list_ops_rules" in settings.enabled_tools_json
    assert "explain_failed_send" in settings.enabled_tools_json
    assert "get_mcp_coverage_matrix" in settings.enabled_tools_json
    assert "recommend_mcp_preset" in settings.enabled_tools_json
    assert "create_send_batch" not in settings.enabled_tools_json
    assert "create_destination_from_diagnostic_update" not in settings.enabled_tools_json
    assert "inspect_bot_access" not in settings.enabled_tools_json
    assert "run_ops_scan" not in settings.enabled_tools_json
    assert "preview_ops_action" not in settings.enabled_tools_json
    assert "apply_ops_action" not in settings.enabled_tools_json
    assert "dismiss_ops_recommendation" not in settings.enabled_tools_json
    assert "update_ops_rule" not in settings.enabled_tools_json
    assert "run_ops_rule" not in settings.enabled_tools_json
    assert "pause_ops_rule" not in settings.enabled_tools_json
    assert "resume_ops_rule" not in settings.enabled_tools_json


async def test_mcp_tool_call_is_rejected_when_tool_is_disabled() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await McpSettingsRepository(session).upsert(
            is_enabled=True,
            enabled_tools_json=["list_bots"],
        )
        await session.commit()

    mcp = create_mcp_server(
        settings=Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:"),
        get_session_factory=lambda: session_factory,
        event_bus=MemoryEventBus(),
        bot_api_client=TelegramBotApiClient("http://telegram-bot-api:8081"),
    )

    with pytest.raises(ToolError, match="MCP tool 'send_text' is disabled"):
        await mcp.call_tool("send_text", {"bot_id": 1, "text": "blocked", "chat_id": "@ops"})

    await engine.dispose()


async def test_mcp_no_settings_row_uses_read_only_bootstrap_tools() -> None:
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

    _content, structured = await mcp.call_tool("list_bots", {})

    assert structured == {"result": []}
    with pytest.raises(ToolError, match="MCP tool 'send_text' is disabled"):
        await mcp.call_tool("send_text", {"bot_id": 1, "text": "blocked", "chat_id": "@ops"})
    with pytest.raises(ToolError, match="MCP tool 'create_api_token' is disabled"):
        await mcp.call_tool("create_api_token", {"name": "blocked"})
    async with session_factory() as session:
        assert await McpSettingsRepository(session).get() is None
    await engine.dispose()


async def test_telegram_ops_mcp_tool_call_is_rejected_when_tool_is_disabled() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await McpSettingsRepository(session).upsert(
            is_enabled=True,
            enabled_tools_json=["list_bots"],
        )
        await session.commit()

    mcp = create_mcp_server(
        settings=Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:"),
        get_session_factory=lambda: session_factory,
        event_bus=MemoryEventBus(),
        bot_api_client=TelegramBotApiClient("http://telegram-bot-api:8081"),
    )

    with pytest.raises(ToolError, match="MCP tool 'run_ops_scan' is disabled"):
        await mcp.call_tool("run_ops_scan", {})

    await engine.dispose()
