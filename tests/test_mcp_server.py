import inspect

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.events import MemoryEventBus
from tg_bot_aggregator.mcp_server import create_mcp_asgi_app, create_mcp_server
from tg_bot_aggregator.models import Base
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient


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
