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
    assert "create_send_batch" not in settings.enabled_tools_json
    assert "create_destination_from_diagnostic_update" not in settings.enabled_tools_json


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
