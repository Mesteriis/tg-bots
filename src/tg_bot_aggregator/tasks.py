from datetime import timedelta

import redis.asyncio as redis
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from tg_bot_aggregator.analytics_service import AnalyticsService
from tg_bot_aggregator.audit import record_audit_event
from tg_bot_aggregator.backup_service import BackupService, BackupServiceError
from tg_bot_aggregator.config import Settings, get_settings
from tg_bot_aggregator.db import create_engine, create_session_factory
from tg_bot_aggregator.events import RedisEventBus
from tg_bot_aggregator.models import utc_now
from tg_bot_aggregator.mtproto_service import MtprotoService
from tg_bot_aggregator.reliability import RedisRateLimitStore, SendRateLimiter
from tg_bot_aggregator.repositories import (
    BackupRunRepository,
    MtprotoSessionRepository,
    RuntimeAdvancedSettingsRepository,
    RuntimeSettingsRepository,
    SendHistoryRepository,
)
from tg_bot_aggregator.runtime_settings import apply_runtime_settings
from tg_bot_aggregator.send_service import SendService
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient
from tg_bot_aggregator.workflow_service import WorkflowService


def create_broker(settings: Settings | None = None) -> RedisStreamBroker:
    resolved = settings or get_settings()
    backend = RedisAsyncResultBackend(resolved.redis_url)
    return RedisStreamBroker(resolved.redis_url).with_result_backend(backend)


broker = create_broker()


def _create_send_rate_limiter(
    settings: Settings,
    redis_client: redis.Redis,
) -> SendRateLimiter:
    return SendRateLimiter(
        store=RedisRateLimitStore(redis_client),
        global_limit_per_minute=settings.send_global_rate_per_minute,
        bot_limit_per_minute=settings.send_bot_rate_per_minute,
        chat_limit_per_minute=settings.send_chat_rate_per_minute,
        destination_limit_per_minute=settings.send_destination_rate_per_minute,
    )


async def _close_redis_client(redis_client: redis.Redis | None) -> None:
    if redis_client is not None:
        await redis_client.aclose()


async def run_refresh_analytics_target(target_id: int, run_id: int | None = None) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            mtproto = MtprotoService(settings, MtprotoSessionRepository(session))
            events = RedisEventBus(settings.redis_url)
            service = AnalyticsService(session, mtproto, events)
            return await service.refresh_target(target_id, run_id)
    finally:
        await engine.dispose()


@broker.task
async def refresh_analytics_target(target_id: int, run_id: int | None = None) -> int:
    return await run_refresh_analytics_target(target_id, run_id)


@broker.task
async def refresh_all_analytics_targets() -> list[int]:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            mtproto = MtprotoService(settings, MtprotoSessionRepository(session))
            events = RedisEventBus(settings.redis_url)
            service = AnalyticsService(session, mtproto, events)
            return await service.refresh_all()
    finally:
        await engine.dispose()


async def run_send_history(send_history_id: int) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    redis_client: redis.Redis | None = None
    events: RedisEventBus | None = None
    try:
        async with session_factory() as session:
            settings = apply_runtime_settings(
                settings,
                await RuntimeSettingsRepository(session).get(),
                await RuntimeAdvancedSettingsRepository(session).get(),
            )
            redis_client = redis.from_url(settings.redis_url)
            rate_limiter = _create_send_rate_limiter(settings, redis_client)
            events = RedisEventBus(settings.redis_url)
            service = SendService(
                session,
                TelegramBotApiClient(settings.telegram_bot_api_base_url),
                settings,
                events,
                rate_limiter=rate_limiter,
            )
            row = await service.process_queued_send(
                send_history_id,
                worker_id="taskiq-send-history",
            )
            return row.id
    finally:
        if events is not None:
            await events.close()
        await _close_redis_client(redis_client)
        await engine.dispose()


@broker.task
async def send_history(send_history_id: int) -> int:
    return await run_send_history(send_history_id)


async def run_due_send_history(limit: int = 100) -> list[int]:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    redis_client: redis.Redis | None = None
    events: RedisEventBus | None = None
    try:
        async with session_factory() as session:
            settings = apply_runtime_settings(
                settings,
                await RuntimeSettingsRepository(session).get(),
                await RuntimeAdvancedSettingsRepository(session).get(),
            )
            redis_client = redis.from_url(settings.redis_url)
            rate_limiter = _create_send_rate_limiter(settings, redis_client)
            events = RedisEventBus(settings.redis_url)
            service = SendService(
                session,
                TelegramBotApiClient(settings.telegram_bot_api_base_url),
                settings,
                events,
                rate_limiter=rate_limiter,
            )
            due_rows = await SendHistoryRepository(session).list_ready_for_lease(
                utc_now(),
                limit=limit,
            )
            processed: list[int] = []
            for row in due_rows:
                processed.append(
                    (
                        await service.process_queued_send(
                            row.id,
                            worker_id="taskiq-due-send-history",
                        )
                    ).id
                )
            return processed
    finally:
        if events is not None:
            await events.close()
        await _close_redis_client(redis_client)
        await engine.dispose()


@broker.task
async def due_send_history(limit: int = 100) -> list[int]:
    return await run_due_send_history(limit)


async def run_send_batch(batch_id: int) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            settings = apply_runtime_settings(
                settings,
                await RuntimeSettingsRepository(session).get(),
                await RuntimeAdvancedSettingsRepository(session).get(),
            )
            events = RedisEventBus(settings.redis_url)
            service = WorkflowService(
                SendService(
                    session,
                    TelegramBotApiClient(settings.telegram_bot_api_base_url),
                    settings,
                    events,
                )
            )
            batch = await service.enqueue_batch(batch_id)
            return batch.id
    finally:
        await engine.dispose()


@broker.task
async def send_batch(batch_id: int) -> int:
    return await run_send_batch(batch_id)


async def run_backup_snapshot(push_to_git: bool | None = None) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            settings = apply_runtime_settings(
                settings,
                await RuntimeSettingsRepository(session).get(),
                await RuntimeAdvancedSettingsRepository(session).get(),
            )
            runs = BackupRunRepository(session)
            run = await runs.create(status="started")
            service = BackupService(session, settings)
            resolved_push_to_git = (
                settings.backup_schedule_push_to_git if push_to_git is None else push_to_git
            )
            try:
                repo_privacy = await service.inspect_repository_privacy()
                include_secrets = (
                    settings.backup_include_secrets or repo_privacy.is_private is True
                )
                snapshot, count = await service.export_snapshot(
                    include_secrets=include_secrets,
                    repo_privacy=repo_privacy,
                    requested_include_secrets=settings.backup_include_secrets,
                )
                commit = await service.push_snapshot(snapshot) if resolved_push_to_git else None
                await runs.mark_finished(
                    run,
                    status="succeeded",
                    items_exported=count,
                    backup_json=snapshot,
                    git_commit=commit,
                )
                await record_audit_event(
                    session,
                    source="scheduler",
                    action="backup.run",
                    status="succeeded",
                    entity_type="backup_run",
                    entity_id=run.id,
                    message="scheduled backup run succeeded",
                    metadata={
                        "include_secrets": include_secrets,
                        "push_to_git": resolved_push_to_git,
                        "git_commit": commit,
                    },
                )
            except BackupServiceError as exc:
                await runs.mark_finished(
                    run,
                    status="failed",
                    items_exported=0,
                    error_message=str(exc),
                )
                await record_audit_event(
                    session,
                    source="scheduler",
                    action="backup.run",
                    status="failed",
                    entity_type="backup_run",
                    entity_id=run.id,
                    message=str(exc),
                    metadata={"push_to_git": resolved_push_to_git},
                )
                await session.commit()
                raise
            await session.commit()
            return run.id
    finally:
        await engine.dispose()


@broker.task
async def backup_snapshot(push_to_git: bool | None = None) -> int:
    return await run_backup_snapshot(push_to_git)


async def run_scheduled_backup_if_due() -> int | None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            settings = apply_runtime_settings(
                settings,
                await RuntimeSettingsRepository(session).get(),
                await RuntimeAdvancedSettingsRepository(session).get(),
            )
            if not settings.backup_schedule_enabled:
                return None
            latest_runs = await BackupRunRepository(session).list(limit=1)
            latest = latest_runs[0] if latest_runs else None
            if latest and latest.finished_at:
                next_due_at = latest.finished_at + timedelta(
                    seconds=settings.backup_schedule_interval_seconds
                )
                if utc_now() < next_due_at:
                    return None
    finally:
        await engine.dispose()
    return await run_backup_snapshot(settings.backup_schedule_push_to_git)


@broker.task
async def scheduled_backup_if_due() -> int | None:
    return await run_scheduled_backup_if_due()
