import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.domain.bots.repository import BotRepository
from tg_bot_aggregator.domain.reliability.service import (
    MemoryRateLimitStore,
    RedisRateLimitStore,
    RetryDecision,
    SendRateLimiter,
    classify_telegram_error,
    compute_retry_decision,
)
from tg_bot_aggregator.domain.sending.repository import (
    SendAttemptRepository,
    SendHistoryRepository,
)
from tg_bot_aggregator.infra.telegram_client import TelegramBotApiError
from tg_bot_aggregator.models import Base, utc_now


async def _create_leased_history(db_session: AsyncSession):
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    history = SendHistoryRepository(db_session)
    row = await history.create(
        bot_id=bot.id,
        chat_id="@ops",
        media_type="none",
        status="queued",
        send_mode="queued",
        request_payload_json={"method": "sendMessage", "chat_id": "@ops", "text": "hello"},
    )
    leased = await history.acquire_due_lease(
        row_id=row.id,
        worker_id="worker-a",
        now=utc_now(),
        lease_seconds=30,
    )

    assert leased is not None
    assert leased.locked_by == "worker-a"
    assert leased.lock_expires_at is not None
    return history, leased


@pytest.mark.asyncio
async def test_send_history_lease_prevents_double_processing(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    history = SendHistoryRepository(db_session)
    row = await history.create(
        bot_id=bot.id,
        chat_id="@ops",
        media_type="none",
        status="queued",
        send_mode="queued",
        request_payload_json={"method": "sendMessage", "chat_id": "@ops", "text": "hello"},
    )
    await db_session.commit()

    leased = await history.acquire_due_lease(
        row_id=row.id,
        worker_id="worker-a",
        now=utc_now(),
        lease_seconds=30,
    )
    duplicate = await history.acquire_due_lease(
        row_id=row.id,
        worker_id="worker-b",
        now=utc_now(),
        lease_seconds=30,
    )

    assert leased is not None
    assert leased.status == "sending"
    assert leased.locked_by == "worker-a"
    assert leased.lock_expires_at is not None
    assert duplicate is None


@pytest.mark.asyncio
async def test_send_history_lease_acquisition_is_atomic_across_sessions(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'reliability.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as setup_session:
            bot = await BotRepository(setup_session).create(name="ops", token="123:abc")
            row = await SendHistoryRepository(setup_session).create(
                bot_id=bot.id,
                chat_id="@ops",
                media_type="none",
                status="queued",
                send_mode="queued",
                request_payload_json={
                    "method": "sendMessage",
                    "chat_id": "@ops",
                    "text": "hello",
                },
            )
            row_id = row.id
            await setup_session.commit()

        async with session_factory() as first_session, session_factory() as second_session:
            first_history = SendHistoryRepository(first_session)
            second_history = SendHistoryRepository(second_session)

            cached = await second_history.get(row_id)
            assert cached is not None
            assert cached.status == "queued"

            first_lease = await first_history.acquire_due_lease(
                row_id=row_id,
                worker_id="worker-a",
                now=utc_now(),
                lease_seconds=30,
            )
            await first_session.commit()

            second_lease = await second_history.acquire_due_lease(
                row_id=row_id,
                worker_id="worker-b",
                now=utc_now(),
                lease_seconds=30,
            )

            assert first_lease is not None
            assert first_lease.locked_by == "worker-a"
            assert second_lease is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_send_history_mark_succeeded_clears_lease(
    db_session: AsyncSession,
) -> None:
    history, row = await _create_leased_history(db_session)

    await history.mark_succeeded(row, telegram_message_id=42, response={"ok": True})

    assert row.status == "succeeded"
    assert row.locked_at is None
    assert row.locked_by is None
    assert row.lock_expires_at is None


@pytest.mark.asyncio
async def test_send_history_mark_failed_clears_lease(
    db_session: AsyncSession,
) -> None:
    history, row = await _create_leased_history(db_session)

    await history.mark_failed(
        row,
        error_code="telegram_error",
        error_message="send failed",
        response={"ok": False},
    )

    assert row.status == "failed"
    assert row.locked_at is None
    assert row.locked_by is None
    assert row.lock_expires_at is None


@pytest.mark.asyncio
async def test_send_history_mark_cancelled_clears_lease(
    db_session: AsyncSession,
) -> None:
    history, row = await _create_leased_history(db_session)

    await history.mark_cancelled(row)

    assert row.status == "cancelled"
    assert row.locked_at is None
    assert row.locked_by is None
    assert row.lock_expires_at is None


@pytest.mark.asyncio
async def test_send_attempts_are_append_only(db_session: AsyncSession) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    history = SendHistoryRepository(db_session)
    row = await history.create(
        bot_id=bot.id,
        chat_id="@ops",
        media_type="none",
        status="queued",
        send_mode="queued",
        request_payload_json={"method": "sendMessage", "chat_id": "@ops", "text": "hello"},
    )
    attempts = SendAttemptRepository(db_session)
    await attempts.create(
        send_history_id=row.id,
        attempt_number=1,
        worker_id="worker-a",
        started_at=utc_now(),
        finished_at=utc_now() + timedelta(milliseconds=120),
        status="deferred",
        telegram_error_code="429",
        error_kind="telegram_rate_limit",
        error_message="Too Many Requests",
        retry_after_seconds=10,
        latency_ms=120,
        response_payload_json={"ok": False, "token": "***"},
    )
    await db_session.commit()

    rows = await attempts.list_for_send(row.id)

    assert len(rows) == 1
    assert rows[0].attempt_number == 1
    assert rows[0].status == "deferred"
    assert rows[0].error_kind == "telegram_rate_limit"


def test_classify_telegram_rate_limit() -> None:
    exc = TelegramBotApiError(
        method="sendMessage",
        error_code=429,
        description="Too Many Requests",
        payload={"parameters": {"retry_after": 17}},
    )

    assert classify_telegram_error(exc) == "telegram_rate_limit"


def test_retry_after_uses_telegram_delay() -> None:
    settings = Settings(
        send_retry_max_attempts=3,
        send_retry_base_delay_seconds=1.0,
        send_retry_max_delay_seconds=60.0,
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=UTC)
    exc = TelegramBotApiError(
        method="sendMessage",
        error_code=429,
        description="Too Many Requests",
        payload={"parameters": {"retry_after": 17}},
    )

    decision = compute_retry_decision(settings=settings, error=exc, attempt_number=1, now=now)

    assert decision == RetryDecision(
        retry=True,
        terminal_status="deferred",
        error_kind="telegram_rate_limit",
        retry_after_seconds=17,
        next_retry_at=datetime(2026, 5, 3, 12, 0, 17, tzinfo=UTC),
    )


def test_exhausted_retry_budget_goes_dead_letter() -> None:
    settings = Settings(send_retry_max_attempts=2)
    now = datetime(2026, 5, 3, 12, 0, tzinfo=UTC)
    exc = TelegramBotApiError(
        method="sendMessage",
        error_code=502,
        description="Bad Gateway",
        payload={"ok": False},
    )

    decision = compute_retry_decision(settings=settings, error=exc, attempt_number=2, now=now)

    assert decision.retry is False
    assert decision.terminal_status == "dead_letter"
    assert decision.error_kind == "telegram_server"


def test_fractional_base_backoff_schedules_positive_delay() -> None:
    settings = Settings(
        send_retry_max_attempts=3,
        send_retry_base_delay_seconds=0.5,
        send_retry_max_delay_seconds=60.0,
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=UTC)
    exc = TelegramBotApiError(
        method="sendMessage",
        error_code=502,
        description="Bad Gateway",
        payload={"ok": False},
    )

    decision = compute_retry_decision(settings=settings, error=exc, attempt_number=1, now=now)

    assert decision.retry is True
    assert decision.retry_after_seconds == 1
    assert decision.next_retry_at == datetime(2026, 5, 3, 12, 0, 1, tzinfo=UTC)


def test_exponential_backoff_is_capped_by_max_delay() -> None:
    settings = Settings(
        send_retry_max_attempts=5,
        send_retry_base_delay_seconds=3.0,
        send_retry_max_delay_seconds=5.0,
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=UTC)
    exc = TelegramBotApiError(
        method="sendMessage",
        error_code=502,
        description="Bad Gateway",
        payload={"ok": False},
    )

    decision = compute_retry_decision(settings=settings, error=exc, attempt_number=3, now=now)

    assert decision.retry is True
    assert decision.retry_after_seconds == 5
    assert decision.next_retry_at == datetime(2026, 5, 3, 12, 0, 5, tzinfo=UTC)


@pytest.mark.asyncio
async def test_rate_limiter_blocks_when_bot_bucket_is_full() -> None:
    store = MemoryRateLimitStore()
    limiter = SendRateLimiter(
        store=store,
        global_limit_per_minute=None,
        bot_limit_per_minute=2,
        chat_limit_per_minute=None,
        destination_limit_per_minute=None,
    )

    first = await limiter.check_and_increment(bot_id=1, chat_id="@ops", destination_id=None)
    second = await limiter.check_and_increment(bot_id=1, chat_id="@ops", destination_id=None)
    third = await limiter.check_and_increment(bot_id=1, chat_id="@ops", destination_id=None)

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.bucket_key == "send:bot:1"
    assert third.retry_after_seconds is not None


@pytest.mark.asyncio
async def test_rate_limiter_reports_bucket_snapshots() -> None:
    store = MemoryRateLimitStore()
    limiter = SendRateLimiter(
        store=store,
        global_limit_per_minute=10,
        bot_limit_per_minute=2,
        chat_limit_per_minute=5,
        destination_limit_per_minute=4,
    )

    await limiter.check_and_increment(bot_id=7, chat_id="-1001", destination_id=3)
    snapshots = await limiter.snapshots(bot_id=7, chat_id="-1001", destination_id=3)

    by_key = {item.bucket_key: item for item in snapshots}
    assert by_key["send:global"].limit == 10
    assert by_key["send:global"].used == 1
    assert by_key["send:bot:7"].limit == 2
    assert by_key["send:bot:7"].used == 1
    assert by_key["send:chat:-1001"].limit == 5
    assert by_key["send:chat:-1001"].used == 1
    assert by_key["send:destination:3"].limit == 4
    assert by_key["send:destination:3"].used == 1


@pytest.mark.asyncio
async def test_memory_rate_limiter_expires_fixed_window() -> None:
    current_time = 100.0

    def monotonic_time() -> float:
        return current_time

    store = MemoryRateLimitStore(clock=monotonic_time)
    limiter = SendRateLimiter(
        store=store,
        global_limit_per_minute=None,
        bot_limit_per_minute=1,
        chat_limit_per_minute=None,
        destination_limit_per_minute=None,
    )

    first = await limiter.check_and_increment(bot_id=1, chat_id="@ops", destination_id=None)
    blocked = await limiter.check_and_increment(bot_id=1, chat_id="@ops", destination_id=None)
    current_time = 161.0
    after_window = await limiter.check_and_increment(bot_id=1, chat_id="@ops", destination_id=None)

    assert first.allowed is True
    assert blocked.allowed is False
    assert blocked.retry_after_seconds == 60
    assert after_window.allowed is True


@pytest.mark.asyncio
async def test_memory_rate_limiter_admits_only_one_concurrent_sender() -> None:
    store = MemoryRateLimitStore()
    limiter = SendRateLimiter(
        store=store,
        global_limit_per_minute=None,
        bot_limit_per_minute=1,
        chat_limit_per_minute=None,
        destination_limit_per_minute=None,
    )

    decisions = await asyncio.gather(
        limiter.check_and_increment(bot_id=1, chat_id="@ops", destination_id=None),
        limiter.check_and_increment(bot_id=1, chat_id="@ops", destination_id=None),
    )

    assert [decision.allowed for decision in decisions].count(True) == 1
    assert [decision.allowed for decision in decisions].count(False) == 1


@pytest.mark.asyncio
async def test_redis_rate_limiter_atomic_script_returns_finite_ttl_for_persistent_block() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.eval_args = None

        async def eval(self, *args):
            self.eval_args = args
            return [0, "send:bot:1", 60]

    redis = FakeRedis()
    store = RedisRateLimitStore(redis)

    decision = await store.check_and_increment_window([("send:bot:1", 1)], 60)

    assert decision.allowed is False
    assert decision.bucket_key == "send:bot:1"
    assert decision.retry_after_seconds == 60
    assert redis.eval_args is not None
