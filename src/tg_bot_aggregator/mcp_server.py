import inspect
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import redis.asyncio as redis
from mcp.server.fastmcp import FastMCP
from redis.exceptions import RedisError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.applications import Starlette

from tg_bot_aggregator.api_tokens import (
    api_token_prefix,
    generate_api_token,
    hash_api_token,
    normalize_token_scopes,
)
from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.events import MemoryEventBus
from tg_bot_aggregator.media_browser import MediaBrowser
from tg_bot_aggregator.models import SendAttempt, SendHistory, utc_now
from tg_bot_aggregator.reliability import (
    RateBucketSnapshot,
    RedisRateLimitStore,
    ReliabilityReadService,
    SendRateLimiter,
)
from tg_bot_aggregator.repositories import (
    AnalyticsRepository,
    ApiTokenRepository,
    AuditRepository,
    BotDiscoverySettingsRepository,
    BotRepository,
    DestinationRepository,
    DiagnosticUpdateRepository,
    McpSettingsRepository,
    NotFoundError,
    SendAttemptRepository,
    SendBatchRepository,
    SendHistoryRepository,
    SendProfileRepository,
    TemplateRepository,
)
from tg_bot_aggregator.send_service import SendService, SendServiceError
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient, TelegramBotApiError
from tg_bot_aggregator.workflow_service import WorkflowService

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


async def _close_redis_client(redis_client: object | None) -> None:
    if redis_client is None:
        return

    close = getattr(redis_client, "aclose", None)
    if close is None:
        close = getattr(redis_client, "close", None)
    if close is None:
        return

    result = close()
    if inspect.isawaitable(result):
        await result


async def _count_recent_sends(
    session: AsyncSession,
    since: datetime,
    *conditions: object,
) -> int:
    statement = (
        select(func.count())
        .select_from(SendAttempt)
        .join(SendHistory, SendAttempt.send_history_id == SendHistory.id)
        .where(
            SendAttempt.started_at >= since,
            or_(
                SendAttempt.error_kind.is_(None),
                SendAttempt.error_kind.not_in(
                    ("rate_limit", "worker_error", "worker_cancelled")
                ),
            ),
            *conditions,
        )
    )
    return int((await session.execute(statement)).scalar_one())


async def _sqlite_rate_bucket_snapshots(
    *,
    session: AsyncSession,
    settings: Settings,
    bot_id: int,
    chat_id: str,
    destination_id: int | None,
) -> list[RateBucketSnapshot]:
    since = utc_now() - timedelta(seconds=60)
    snapshots: list[RateBucketSnapshot] = []
    if settings.send_global_rate_per_minute is not None:
        snapshots.append(
            RateBucketSnapshot(
                bucket_key="send:global",
                limit=settings.send_global_rate_per_minute,
                used=await _count_recent_sends(session, since),
                retry_after_seconds=None,
            )
        )
    if settings.send_bot_rate_per_minute is not None:
        snapshots.append(
            RateBucketSnapshot(
                bucket_key=f"send:bot:{bot_id}",
                limit=settings.send_bot_rate_per_minute,
                used=await _count_recent_sends(session, since, SendHistory.bot_id == bot_id),
                retry_after_seconds=None,
            )
        )
    if settings.send_chat_rate_per_minute is not None:
        snapshots.append(
            RateBucketSnapshot(
                bucket_key=f"send:chat:{chat_id}",
                limit=settings.send_chat_rate_per_minute,
                used=await _count_recent_sends(session, since, SendHistory.chat_id == chat_id),
                retry_after_seconds=None,
            )
        )
    if settings.send_destination_rate_per_minute is not None and destination_id is not None:
        snapshots.append(
            RateBucketSnapshot(
                bucket_key=f"send:destination:{destination_id}",
                limit=settings.send_destination_rate_per_minute,
                used=await _count_recent_sends(
                    session,
                    since,
                    SendHistory.destination_id == destination_id,
                ),
                retry_after_seconds=None,
            )
        )
    return snapshots


def _serialize_rate_bucket_snapshot(item: RateBucketSnapshot) -> dict[str, Any]:
    return {
        "bucket_key": item.bucket_key,
        "limit": item.limit,
        "used": item.used,
        "retry_after_seconds": item.retry_after_seconds,
    }


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
    async def get_reliability_summary() -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "get_reliability_summary")
        async with get_session_factory()() as session:
            return await ReliabilityReadService(session).summary()

    @mcp.tool()
    async def get_reliability_graph() -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "get_reliability_graph")
        async with get_session_factory()() as session:
            return await ReliabilityReadService(session).graph()

    @mcp.tool()
    async def list_send_attempts(limit: int = 100) -> list[dict[str, Any]]:
        await ensure_mcp_tool_enabled(get_session_factory(), "list_send_attempts")
        async with get_session_factory()() as session:
            attempts = await SendAttemptRepository(session).list(limit=limit)
            return [
                {
                    "id": item.id,
                    "send_history_id": item.send_history_id,
                    "attempt_number": item.attempt_number,
                    "worker_id": item.worker_id,
                    "started_at": item.started_at.isoformat(),
                    "finished_at": item.finished_at.isoformat()
                    if item.finished_at is not None
                    else None,
                    "status": item.status,
                    "telegram_error_code": item.telegram_error_code,
                    "error_kind": item.error_kind,
                    "error_message": item.error_message,
                    "retry_after_seconds": item.retry_after_seconds,
                    "latency_ms": item.latency_ms,
                    "response_payload_json": item.response_payload_json,
                }
                for item in attempts
            ]

    @mcp.tool()
    async def list_rate_limit_buckets(
        bot_id: int = 0,
        chat_id: str = "*",
        destination_id: int | None = None,
    ) -> list[dict[str, Any]]:
        await ensure_mcp_tool_enabled(get_session_factory(), "list_rate_limit_buckets")
        async with get_session_factory()() as session:
            redis_client: object | None = None
            try:
                redis_client = redis.from_url(settings.redis_url)
                limiter = SendRateLimiter(
                    store=RedisRateLimitStore(redis_client),
                    global_limit_per_minute=settings.send_global_rate_per_minute,
                    bot_limit_per_minute=settings.send_bot_rate_per_minute,
                    chat_limit_per_minute=settings.send_chat_rate_per_minute,
                    destination_limit_per_minute=settings.send_destination_rate_per_minute,
                )
                snapshots = await limiter.snapshots(
                    bot_id=bot_id,
                    chat_id=chat_id,
                    destination_id=destination_id,
                )
            except RedisError:
                snapshots = await _sqlite_rate_bucket_snapshots(
                    session=session,
                    settings=settings,
                    bot_id=bot_id,
                    chat_id=chat_id,
                    destination_id=destination_id,
                )
            finally:
                await _close_redis_client(redis_client)
        return [_serialize_rate_bucket_snapshot(item) for item in snapshots]

    @mcp.tool()
    async def release_stale_send_locks() -> dict[str, int]:
        await ensure_mcp_tool_enabled(get_session_factory(), "release_stale_send_locks")
        async with get_session_factory()() as session:
            released = await SendHistoryRepository(session).release_stale_locks(utc_now())
            await session.commit()
            await event_bus.publish("send.released", {"released": released})
            return {"released": released}

    @mcp.tool()
    async def bulk_retry_sends(send_history_ids: list[int]) -> dict[str, int]:
        await ensure_mcp_tool_enabled(get_session_factory(), "bulk_retry_sends")
        changed = 0
        skipped = 0
        async with get_session_factory()() as session:
            service = SendService(session, bot_api_client, settings, event_bus)
            for send_history_id in send_history_ids:
                try:
                    await service.retry_history(send_history_id)
                except (NotFoundError, ValueError, SendServiceError):
                    skipped += 1
                else:
                    changed += 1
        return {"changed": changed, "skipped": skipped}

    @mcp.tool()
    async def bulk_cancel_sends(send_history_ids: list[int]) -> dict[str, int]:
        await ensure_mcp_tool_enabled(get_session_factory(), "bulk_cancel_sends")
        changed = 0
        skipped = 0
        async with get_session_factory()() as session:
            service = SendService(session, bot_api_client, settings, event_bus)
            for send_history_id in send_history_ids:
                try:
                    await service.cancel_history(send_history_id)
                except (NotFoundError, ValueError, SendServiceError):
                    skipped += 1
                else:
                    changed += 1
        return {"changed": changed, "skipped": skipped}

    @mcp.tool()
    async def list_media(path: str = "") -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "list_media")
        listing = MediaBrowser(
            settings.shared_media_root,
            require_mount=settings.shared_media_require_mount,
        ).list_directory(path)
        return {
            "relative_path": listing.relative_path,
            "items": [
                {
                    "name": item.name,
                    "relative_path": item.relative_path,
                    "kind": item.kind,
                    "size_bytes": item.size_bytes,
                    "modified_at": item.modified_at.isoformat(),
                    "media_type": item.media_type,
                }
                for item in listing.items
            ],
        }

    @mcp.tool()
    async def list_send_profiles() -> list[dict[str, Any]]:
        await ensure_mcp_tool_enabled(get_session_factory(), "list_send_profiles")
        async with get_session_factory()() as session:
            rows = await SendProfileRepository(session).list()
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "bot_id": row.bot_id,
                    "send_kind": row.send_kind,
                    "destination_id": row.destination_id,
                    "destination_alias": row.destination_alias,
                    "template_tag": row.template_tag,
                    "media_type": row.media_type,
                    "is_active": row.is_active,
                }
                for row in rows
            ]

    @mcp.tool()
    async def create_send_profile(
        name: str,
        bot_id: int,
        send_kind: str,
        destination_id: int | None = None,
        destination_alias: str | None = None,
        chat_id: str | None = None,
        template_tag: str | None = None,
        text: str | None = None,
        media_type: str = "none",
        file_relative_path: str | None = None,
        caption: str | None = None,
    ) -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "create_send_profile")
        async with get_session_factory()() as session:
            row = await SendProfileRepository(session).create(
                name=name,
                bot_id=bot_id,
                send_kind=send_kind,
                destination_id=destination_id,
                destination_alias=destination_alias,
                chat_id=chat_id,
                template_tag=template_tag,
                text=text,
                media_type=media_type,
                file_relative_path=file_relative_path,
                caption=caption,
                variables_json={},
                is_active=True,
            )
            await session.commit()
            return {"id": row.id, "name": row.name, "send_kind": row.send_kind}

    @mcp.tool()
    async def list_send_batches() -> list[dict[str, Any]]:
        await ensure_mcp_tool_enabled(get_session_factory(), "list_send_batches")
        async with get_session_factory()() as session:
            repo = SendBatchRepository(session)
            rows = await repo.list_batches()
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "bot_id": row.bot_id,
                    "send_kind": row.send_kind,
                    "status": row.status,
                    "items_count": len(await repo.list_items(row.id)),
                }
                for row in rows
            ]

    @mcp.tool()
    async def create_send_batch(
        name: str,
        bot_id: int,
        send_kind: str,
        destination_ids: list[int],
        text: str | None = None,
        template_tag: str | None = None,
    ) -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "create_send_batch")
        async with get_session_factory()() as session:
            repo = SendBatchRepository(session)
            batch = await repo.create_batch(
                name=name,
                bot_id=bot_id,
                send_kind=send_kind,
                text=text,
                template_tag=template_tag,
                variables_json={},
            )
            destinations = DestinationRepository(session)
            for destination_id in destination_ids:
                destination = await destinations.get(destination_id)
                if destination is None:
                    raise ValueError(f"destination {destination_id} not found")
                await repo.add_item(
                    batch.id,
                    destination_id=destination.id,
                    chat_id=destination.chat_id,
                    message_thread_id=destination.message_thread_id,
                )
            await session.commit()
            return {"id": batch.id, "status": batch.status}

    @mcp.tool()
    async def preview_send_batch(batch_id: int) -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "preview_send_batch")
        async with get_session_factory()() as session:
            service = WorkflowService(SendService(session, bot_api_client, settings, event_bus))
            return await service.preview_batch(batch_id)

    @mcp.tool()
    async def enqueue_send_batch(batch_id: int) -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "enqueue_send_batch")
        async with get_session_factory()() as session:
            service = WorkflowService(SendService(session, bot_api_client, settings, event_bus))
            batch = await service.enqueue_batch(batch_id)
            return {"id": batch.id, "status": batch.status}

    @mcp.tool()
    async def cancel_send_batch(batch_id: int) -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "cancel_send_batch")
        async with get_session_factory()() as session:
            service = WorkflowService(SendService(session, bot_api_client, settings, event_bus))
            batch = await service.cancel_batch(batch_id)
            return {"id": batch.id, "status": batch.status}

    @mcp.tool()
    async def list_diagnostic_updates(limit: int = 20) -> list[dict[str, Any]]:
        await ensure_mcp_tool_enabled(get_session_factory(), "list_diagnostic_updates")
        async with get_session_factory()() as session:
            rows = await DiagnosticUpdateRepository(session).list(limit=limit)
            return [
                {
                    "id": row.id,
                    "update_id": row.update_id,
                    "chat_id": row.chat_id,
                    "chat_type": row.chat_type,
                    "chat_title": row.chat_title,
                    "message_thread_id": row.message_thread_id,
                }
                for row in rows
            ]

    @mcp.tool()
    async def create_destination_from_diagnostic_update(
        update_id: int,
        bot_id: int,
        alias: str | None = None,
    ) -> dict[str, Any]:
        await ensure_mcp_tool_enabled(
            get_session_factory(), "create_destination_from_diagnostic_update"
        )
        async with get_session_factory()() as session:
            update = await DiagnosticUpdateRepository(session).get(update_id)
            if update is None or update.chat_id is None:
                raise ValueError(f"diagnostic update {update_id} not found")
            kind = (
                "forum_topic"
                if update.message_thread_id is not None
                else update.chat_type or "group"
            )
            destination = await DestinationRepository(session).upsert_by_chat(
                bot_id=bot_id,
                chat_id=update.chat_id,
                message_thread_id=update.message_thread_id,
                kind=kind,
                alias=alias,
                title=update.chat_title,
                username=update.chat_username,
                is_active=True,
            )
            await session.commit()
            return {"id": destination.id, "chat_id": destination.chat_id}

    @mcp.tool()
    async def get_mcp_connection_info() -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "get_mcp_connection_info")
        async with get_session_factory()() as session:
            mcp_settings = await McpSettingsRepository(session).get_or_create()
            await session.commit()
            first_protected_host = (
                settings.protected_api_hosts[0] if settings.protected_api_hosts else ""
            )
            return {
                "streamable_http": {
                    "path": f"{settings.mcp_v1_prefix}/",
                    "enabled": mcp_settings.is_enabled,
                },
                "legacy_sse": {
                    "path": f"{settings.mcp_v1_prefix}/sse",
                    "enabled": mcp_settings.is_enabled and mcp_settings.allow_legacy_sse,
                },
                "legacy_messages": {
                    "path": f"{settings.mcp_v1_prefix}/messages/",
                    "enabled": mcp_settings.is_enabled and mcp_settings.allow_legacy_sse,
                },
                "protected_hosts": settings.protected_api_hosts,
                "required_headers": ["X-API-Token"],
                "enabled_tools": list(mcp_settings.enabled_tools_json or []),
                "local_examples": {
                    "streamable_http": (
                        f"http://127.0.0.1:{settings.app_port}{settings.mcp_v1_prefix}/"
                    ),
                },
                "protected_host_examples": {
                    "streamable_http": (
                        f"https://{first_protected_host}{settings.mcp_v1_prefix}/"
                        if first_protected_host
                        else ""
                    ),
                    "header": "X-API-Token: <token>",
                },
            }

    @mcp.tool()
    async def dry_run_send(
        bot_id: int,
        text: str | None = None,
        tag: str | None = None,
        destination_id: int | None = None,
        destination_alias: str | None = None,
        chat_id: str | None = None,
        message_thread_id: int | None = None,
        variables: dict[str, Any] | None = None,
        media_type: str | None = None,
        file_relative_path: str | None = None,
        caption: str | None = None,
    ) -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "dry_run_send")
        async with get_session_factory()() as session:
            service = SendService(session, bot_api_client, settings, event_bus)
            if file_relative_path:
                return await service.dry_run_file(
                    bot_id=bot_id,
                    media_type=media_type or "document",
                    file_relative_path=file_relative_path,
                    destination_id=destination_id,
                    destination_alias=destination_alias,
                    chat_id=chat_id,
                    caption=caption,
                    message_thread_id=message_thread_id,
                    variables=variables,
                )
            if tag:
                return await service.dry_run_template(
                    bot_id=bot_id,
                    tag=tag,
                    destination_id=destination_id,
                    destination_alias=destination_alias,
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    variables=variables,
                )
            return await service.dry_run_text(
                bot_id=bot_id,
                text=text or "",
                destination_id=destination_id,
                destination_alias=destination_alias,
                chat_id=chat_id,
                message_thread_id=message_thread_id,
            )

    @mcp.tool()
    async def list_audit_events(limit: int = 20) -> list[dict[str, Any]]:
        await ensure_mcp_tool_enabled(get_session_factory(), "list_audit_events")
        async with get_session_factory()() as session:
            rows = await AuditRepository(session).list(limit=limit)
            return [
                {
                    "id": item.id,
                    "created_at": item.created_at.isoformat(),
                    "source": item.source,
                    "action": item.action,
                    "status": item.status,
                    "entity_type": item.entity_type,
                    "entity_id": item.entity_id,
                    "message": item.message,
                }
                for item in rows
            ]

    @mcp.tool()
    async def get_discovery_settings() -> list[dict[str, Any]]:
        await ensure_mcp_tool_enabled(get_session_factory(), "get_discovery_settings")
        async with get_session_factory()() as session:
            rows = await BotDiscoverySettingsRepository(session).list()
            return [
                {
                    "bot_id": item.bot_id,
                    "is_enabled": item.is_enabled,
                    "last_update_id": item.last_update_id,
                    "last_error": item.last_error,
                }
                for item in rows
            ]

    @mcp.tool()
    async def update_discovery_settings(bot_id: int, is_enabled: bool) -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "update_discovery_settings")
        async with get_session_factory()() as session:
            bot = await BotRepository(session).get(bot_id)
            if bot is None:
                raise ValueError(f"bot {bot_id} not found")
            row = await BotDiscoverySettingsRepository(session).upsert_for_bot(
                bot_id,
                is_enabled=is_enabled,
            )
            await session.commit()
            return {"bot_id": row.bot_id, "is_enabled": row.is_enabled}

    @mcp.tool()
    async def check_destination(destination_id: int) -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "check_destination")
        async with get_session_factory()() as session:
            destinations = DestinationRepository(session)
            destination = await destinations.get(destination_id)
            if destination is None:
                raise ValueError(f"destination {destination_id} not found")
            bot = await BotRepository(session).get(destination.bot_id)
            if bot is None or not bot.is_active:
                raise ValueError("destination bot is missing or inactive")
            chat_response = await bot_api_client.get_chat(bot.token, destination.chat_id)
            chat = chat_response.get("result") if isinstance(chat_response, dict) else {}
            if not isinstance(chat, dict):
                chat = {}
            warnings: list[str] = []
            member_count: int | None = None
            try:
                member_count = await bot_api_client.get_chat_member_count(
                    bot.token,
                    destination.chat_id,
                )
            except TelegramBotApiError as exc:
                warnings.append(exc.description)
            await destinations.update(
                destination_id,
                kind=str(chat.get("type") or destination.kind),
                title=chat.get("title") or chat.get("first_name") or destination.title,
                username=chat.get("username") or destination.username,
                is_active=True,
            )
            await session.commit()
            return {
                "destination_id": destination_id,
                "ok": True,
                "chat": chat,
                "member_count": member_count,
                "warnings": warnings,
            }

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
    async def create_api_token(name: str, scopes: list[str] | None = None) -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "create_api_token")
        token = generate_api_token()
        async with get_session_factory()() as session:
            row = await ApiTokenRepository(session).create(
                name=name,
                token_hash=hash_api_token(token),
                token_prefix=api_token_prefix(token),
                scopes_json=normalize_token_scopes(scopes),
            )
            await session.commit()
            return {
                "id": row.id,
                "name": row.name,
                "token_prefix": row.token_prefix,
                "scopes": row.scopes_json,
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
