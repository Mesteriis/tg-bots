from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.applications import Starlette

from tg_bot_aggregator.api_tokens import api_token_prefix, generate_api_token, hash_api_token
from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.events import MemoryEventBus
from tg_bot_aggregator.repositories import (
    AnalyticsRepository,
    ApiTokenRepository,
    BotRepository,
    DestinationRepository,
    McpSettingsRepository,
    SendHistoryRepository,
    TemplateRepository,
)
from tg_bot_aggregator.send_service import SendService
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient

SessionFactoryProvider = Callable[[], async_sessionmaker[AsyncSession]]


async def ensure_mcp_tool_enabled(
    session_factory: async_sessionmaker[AsyncSession],
    tool_name: str,
) -> None:
    async with session_factory() as session:
        settings = await McpSettingsRepository(session).get_or_create()
        await session.commit()
        if not settings.is_enabled:
            raise PermissionError("MCP protocol is disabled")
        if tool_name not in set(settings.enabled_tools_json or []):
            raise PermissionError(f"MCP tool '{tool_name}' is disabled")


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
        await ensure_mcp_tool_enabled(get_session_factory(), "list_bots")
        async with get_session_factory()() as session:
            bots = await BotRepository(session).list()
            return [{"id": bot.id, "name": bot.name, "username": bot.username} for bot in bots]

    @mcp.tool()
    async def list_destinations() -> list[dict[str, Any]]:
        await ensure_mcp_tool_enabled(get_session_factory(), "list_destinations")
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
        await ensure_mcp_tool_enabled(get_session_factory(), "list_message_templates")
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
        await ensure_mcp_tool_enabled(get_session_factory(), "send_text")
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
        await ensure_mcp_tool_enabled(get_session_factory(), "send_template")
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
        await ensure_mcp_tool_enabled(get_session_factory(), "send_file_from_shared_path")
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
        await ensure_mcp_tool_enabled(get_session_factory(), "refresh_analytics")
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
        await ensure_mcp_tool_enabled(get_session_factory(), "get_analytics_summary")
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
        await ensure_mcp_tool_enabled(get_session_factory(), "get_send_history")
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

    @mcp.tool()
    async def list_api_tokens() -> list[dict[str, Any]]:
        await ensure_mcp_tool_enabled(get_session_factory(), "list_api_tokens")
        async with get_session_factory()() as session:
            rows = await ApiTokenRepository(session).list()
            return [
                {
                    "id": item.id,
                    "name": item.name,
                    "token_prefix": item.token_prefix,
                    "is_active": item.is_active,
                    "created_at": item.created_at.isoformat(),
                    "last_used_at": item.last_used_at.isoformat() if item.last_used_at else None,
                    "revoked_at": item.revoked_at.isoformat() if item.revoked_at else None,
                }
                for item in rows
            ]

    @mcp.tool()
    async def create_api_token(name: str) -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "create_api_token")
        token = generate_api_token()
        async with get_session_factory()() as session:
            row = await ApiTokenRepository(session).create(
                name=name,
                token_hash=hash_api_token(token),
                token_prefix=api_token_prefix(token),
            )
            await session.commit()
            return {
                "id": row.id,
                "name": row.name,
                "token_prefix": row.token_prefix,
                "token": token,
            }

    @mcp.tool()
    async def revoke_api_token(token_id: int) -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "revoke_api_token")
        async with get_session_factory()() as session:
            deleted = await ApiTokenRepository(session).revoke(token_id)
            await session.commit()
            return {"token_id": token_id, "revoked": deleted}

    return mcp


def create_mcp_asgi_app(mcp: FastMCP) -> Starlette:
    streamable = mcp.streamable_http_app()
    sse = mcp.sse_app()
    return Starlette(routes=[*streamable.routes, *sse.routes])
