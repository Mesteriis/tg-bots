from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.applications import Starlette

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.events import MemoryEventBus
from tg_bot_aggregator.repositories import (
    AnalyticsRepository,
    BotRepository,
    DestinationRepository,
    SendHistoryRepository,
    TemplateRepository,
)
from tg_bot_aggregator.send_service import SendService
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient

SessionFactoryProvider = Callable[[], async_sessionmaker[AsyncSession]]


def create_mcp_server(
    settings: Settings,
    get_session_factory: SessionFactoryProvider,
    event_bus: MemoryEventBus,
    bot_api_client: TelegramBotApiClient,
) -> FastMCP:
    mcp = FastMCP(
        "Telegram Bot Aggregator",
        streamable_http_path="/",
        sse_path="/sse",
        message_path="/messages/",
        json_response=True,
    )

    @mcp.tool()
    async def list_bots() -> list[dict[str, Any]]:
        async with get_session_factory()() as session:
            bots = await BotRepository(session).list()
            return [{"id": bot.id, "name": bot.name, "username": bot.username} for bot in bots]

    @mcp.tool()
    async def list_destinations() -> list[dict[str, Any]]:
        async with get_session_factory()() as session:
            destinations = await DestinationRepository(session).list()
            return [
                {
                    "id": item.id,
                    "bot_id": item.bot_id,
                    "kind": item.kind,
                    "chat_id": item.chat_id,
                    "message_thread_id": item.message_thread_id,
                    "title": item.title,
                }
                for item in destinations
            ]

    @mcp.tool()
    async def list_message_templates() -> list[dict[str, Any]]:
        async with get_session_factory()() as session:
            templates = await TemplateRepository(session).list()
            return [
                {"id": item.id, "tag": item.tag, "title": item.title, "text": item.text}
                for item in templates
            ]

    @mcp.tool()
    async def send_text(
        bot_id: int,
        text: str,
        destination_id: int | None = None,
        chat_id: str | None = None,
        tag: str | None = None,
        message_thread_id: int | None = None,
    ) -> dict[str, Any]:
        async with get_session_factory()() as session:
            service = SendService(session, bot_api_client, settings, event_bus)
            row = await service.send_text(
                bot_id=bot_id,
                text=text,
                destination_id=destination_id,
                chat_id=chat_id,
                tag=tag,
                message_thread_id=message_thread_id,
            )
            return {"send_history_id": row.id, "status": row.status}

    @mcp.tool()
    async def send_template(
        bot_id: int,
        tag: str,
        destination_id: int | None = None,
        chat_id: str | None = None,
        message_thread_id: int | None = None,
    ) -> dict[str, Any]:
        async with get_session_factory()() as session:
            service = SendService(session, bot_api_client, settings, event_bus)
            row = await service.send_template(
                bot_id=bot_id,
                tag=tag,
                destination_id=destination_id,
                chat_id=chat_id,
                message_thread_id=message_thread_id,
            )
            return {"send_history_id": row.id, "status": row.status}

    @mcp.tool()
    async def send_file_from_shared_path(
        bot_id: int,
        media_type: str,
        file_relative_path: str,
        destination_id: int | None = None,
        chat_id: str | None = None,
        caption: str | None = None,
        tag: str | None = None,
        message_thread_id: int | None = None,
    ) -> dict[str, Any]:
        async with get_session_factory()() as session:
            service = SendService(session, bot_api_client, settings, event_bus)
            row = await service.send_file(
                bot_id=bot_id,
                media_type=media_type,
                file_relative_path=file_relative_path,
                destination_id=destination_id,
                chat_id=chat_id,
                caption=caption,
                tag=tag,
                message_thread_id=message_thread_id,
            )
            return {"send_history_id": row.id, "status": row.status}

    @mcp.tool()
    async def refresh_analytics(target_id: int) -> dict[str, Any]:
        async with get_session_factory()() as session:
            repo = AnalyticsRepository(session)
            run = await repo.create_run(target_id=target_id, status="queued")
            await session.commit()
            await event_bus.publish(
                "analytics.run.queued", {"run_id": run.id, "target_id": target_id}
            )
            return {"run_id": run.id, "status": run.status}

    @mcp.tool()
    async def get_analytics_summary(target_id: int | None = None) -> list[dict[str, Any]]:
        async with get_session_factory()() as session:
            snapshots = await AnalyticsRepository(session).list_snapshots(target_id=target_id)
            return [
                {
                    "id": item.id,
                    "target_id": item.target_id,
                    "captured_at": item.captured_at.isoformat(),
                    "participants_count": item.participants_count,
                    "recent_messages_count": item.recent_messages_count,
                    "recent_views_total": item.recent_views_total,
                }
                for item in snapshots
            ]

    @mcp.tool()
    async def get_send_history(limit: int = 20) -> list[dict[str, Any]]:
        async with get_session_factory()() as session:
            rows = await SendHistoryRepository(session).list(limit=limit)
            return [
                {
                    "id": item.id,
                    "chat_id": item.chat_id,
                    "tag": item.tag,
                    "status": item.status,
                    "error_message": item.error_message,
                }
                for item in rows
            ]

    return mcp


def create_mcp_asgi_app(mcp: FastMCP) -> Starlette:
    streamable = mcp.streamable_http_app()
    sse = mcp.sse_app()
    return Starlette(routes=[*streamable.routes, *sse.routes])

