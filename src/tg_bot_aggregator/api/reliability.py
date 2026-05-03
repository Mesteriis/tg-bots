import inspect
from datetime import datetime

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Request, Response
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import create_send_service, get_session
from tg_bot_aggregator.models import SendHistory, utc_now
from tg_bot_aggregator.reliability import (
    MemoryRateLimitStore,
    RateBucketSnapshot,
    RateLimitStore,
    RedisRateLimitStore,
    ReliabilityReadService,
    SendRateLimiter,
)
from tg_bot_aggregator.repositories import (
    NotFoundError,
    SendAttemptRepository,
    SendHistoryRepository,
)
from tg_bot_aggregator.schemas import (
    BulkSendHistoryRequest,
    BulkSendHistoryResult,
    RateBucketRead,
    ReliabilityGraphRead,
    ReliabilitySummaryRead,
    SendAttemptRead,
)
from tg_bot_aggregator.send_service import SendServiceError

router = APIRouter(prefix="/reliability", tags=["reliability"])


@router.get("/summary", response_model=ReliabilitySummaryRead)
async def reliability_summary(
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return await ReliabilityReadService(session).summary()


@router.get("/graph", response_model=ReliabilityGraphRead)
async def reliability_graph(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    return await ReliabilityReadService(session).graph()


@router.get("/attempts", response_model=list[SendAttemptRead])
async def list_attempts(
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
) -> list[object]:
    return await SendAttemptRepository(session).list(limit=limit)


async def _rate_bucket_snapshots(
    *,
    request: Request,
    store: RateLimitStore,
    bot_id: int,
    chat_id: str,
    destination_id: int | None,
) -> list[RateBucketSnapshot]:
    settings = request.app.state.settings
    limiter = SendRateLimiter(
        store=store,
        global_limit_per_minute=settings.send_global_rate_per_minute,
        bot_limit_per_minute=settings.send_bot_rate_per_minute,
        chat_limit_per_minute=settings.send_chat_rate_per_minute,
        destination_limit_per_minute=settings.send_destination_rate_per_minute,
    )
    return await limiter.snapshots(
        bot_id=bot_id,
        chat_id=chat_id,
        destination_id=destination_id,
    )


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


@router.get("/buckets", response_model=list[RateBucketRead])
async def list_buckets(
    request: Request,
    response: Response,
    bot_id: int,
    chat_id: str,
    destination_id: int | None = None,
) -> list[RateBucketSnapshot]:
    redis_client: object | None = None
    try:
        redis_client = redis.from_url(request.app.state.settings.redis_url)
        response.headers["X-Reliability-Degraded"] = "false"
        return await _rate_bucket_snapshots(
            request=request,
            store=RedisRateLimitStore(redis_client),
            bot_id=bot_id,
            chat_id=chat_id,
            destination_id=destination_id,
        )
    except RedisError:
        response.headers["X-Reliability-Degraded"] = "true"
        return await _rate_bucket_snapshots(
            request=request,
            store=MemoryRateLimitStore(),
            bot_id=bot_id,
            chat_id=chat_id,
            destination_id=destination_id,
        )
    finally:
        await _close_redis_client(redis_client)


@router.get("/stale-locks")
async def stale_locks(session: AsyncSession = Depends(get_session)) -> dict[str, int]:
    rows = await SendHistoryRepository(session).list_stale_locks(utc_now(), limit=1000)
    return {"count": len(rows)}


@router.post("/stale-locks/release")
async def release_stale_locks(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    released = await SendHistoryRepository(session).release_stale_locks(utc_now())
    await session.commit()
    await request.app.state.event_bus.publish("send.released", {"released": released})
    return {"released": released}


def _is_ready_for_enqueue(row: SendHistory, now: datetime) -> bool:
    if row.status != "queued" or row.queued_task_id:
        return False
    if row.next_retry_at is None:
        return True
    next_retry_at = (
        row.next_retry_at
        if row.next_retry_at.tzinfo is not None
        else row.next_retry_at.replace(tzinfo=now.tzinfo)
    )
    return next_retry_at <= now


async def _enqueue_if_ready(
    row: SendHistory,
    request: Request,
    session: AsyncSession,
) -> None:
    if not _is_ready_for_enqueue(row, utc_now()):
        return

    enqueue = getattr(request.app.state, "enqueue_send_history", None)
    if enqueue is None:
        return

    task_id = await enqueue(row.id)
    if task_id:
        await SendHistoryRepository(session).mark_queued(row, task_id=task_id)
        await session.commit()


@router.post("/send-history/bulk-retry", response_model=BulkSendHistoryResult)
async def bulk_retry_sends(
    payload: BulkSendHistoryRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BulkSendHistoryResult:
    service = create_send_service(session, request)
    changed = 0
    skipped = 0
    for send_history_id in payload.send_history_ids:
        try:
            row = await service.retry_history(send_history_id)
            await _enqueue_if_ready(row, request, session)
        except (ValueError, SendServiceError, NotFoundError):
            skipped += 1
        else:
            changed += 1
    return BulkSendHistoryResult(changed=changed, skipped=skipped)


@router.post("/send-history/bulk-cancel", response_model=BulkSendHistoryResult)
async def bulk_cancel_sends(
    payload: BulkSendHistoryRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BulkSendHistoryResult:
    service = create_send_service(session, request)
    changed = 0
    skipped = 0
    for send_history_id in payload.send_history_ids:
        try:
            await service.cancel_history(send_history_id)
        except (ValueError, SendServiceError, NotFoundError):
            skipped += 1
        else:
            changed += 1
    return BulkSendHistoryResult(changed=changed, skipped=skipped)
