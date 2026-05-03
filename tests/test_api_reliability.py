from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
import pytest
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.events import MemoryEventBus
from tg_bot_aggregator.main import create_app
from tg_bot_aggregator.models import Base, utc_now
from tg_bot_aggregator.repositories import (
    BotRepository,
    SendAttemptRepository,
    SendHistoryRepository,
)


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False)

    await engine.dispose()


def _settings() -> Settings:
    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        SEND_GLOBAL_RATE_PER_MINUTE=60,
        SEND_BOT_RATE_PER_MINUTE=30,
        SEND_CHAT_RATE_PER_MINUTE=20,
        SEND_DESTINATION_RATE_PER_MINUTE=10,
    )


async def _client(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    event_bus: MemoryEventBus | None = None,
    enqueue_send_history=None,
) -> httpx.AsyncClient:
    app = create_app(
        settings=_settings(),
        session_factory=session_factory,
        event_bus=event_bus,
        enqueue_send_history=enqueue_send_history,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


@pytest.mark.asyncio
async def test_reliability_summary_reports_status_counts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        bot = await BotRepository(session).create(name="ops", token="123:abc")
        history = SendHistoryRepository(session)
        await history.create(bot_id=bot.id, chat_id="@ops", media_type="none", status="queued")
        await history.create(bot_id=bot.id, chat_id="@ops", media_type="none", status="deferred")
        await history.create(
            bot_id=bot.id,
            chat_id="@ops",
            media_type="none",
            status="dead_letter",
        )
        await session.commit()

    async with await _client(session_factory) as client:
        response = await client.get("/api/v1/reliability/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["status_counts"]["queued"] == 1
    assert data["status_counts"]["deferred"] == 1
    assert data["status_counts"]["dead_letter"] == 1
    assert data["stale_locks"] == 0
    assert data["degraded"] is False


@pytest.mark.asyncio
async def test_release_stale_locks_returns_count_and_publishes_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        bot = await BotRepository(session).create(name="ops", token="123:abc")
        history = SendHistoryRepository(session)
        row = await history.create(
            bot_id=bot.id,
            chat_id="@ops",
            media_type="none",
            status="queued",
        )
        leased = await history.acquire_due_lease(row.id, "worker-a", utc_now(), lease_seconds=1)
        assert leased is not None
        leased.lock_expires_at = utc_now() - timedelta(seconds=1)
        await session.commit()

    event_bus = MemoryEventBus()
    async with await _client(session_factory, event_bus=event_bus) as client:
        count = await client.get("/api/v1/reliability/stale-locks")
        response = await client.post("/api/v1/reliability/stale-locks/release")

    assert count.status_code == 200
    assert count.json() == {"count": 1}
    assert response.status_code == 200
    assert response.json() == {"released": 1}
    latest = await event_bus.latest()
    assert latest is not None
    assert latest.event_type == "send.released"


@pytest.mark.asyncio
async def test_reliability_graph_and_attempts_are_exposed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        bot = await BotRepository(session).create(name="ops", token="123:abc")
        row = await SendHistoryRepository(session).create(
            bot_id=bot.id,
            chat_id="@ops",
            media_type="none",
            status="queued",
        )
        await SendAttemptRepository(session).create(
            send_history_id=row.id,
            attempt_number=1,
            worker_id="worker-a",
            started_at=utc_now(),
            finished_at=utc_now(),
            status="deferred",
            telegram_error_code="429",
            error_kind="telegram_rate_limit",
            error_message="Too Many Requests",
            retry_after_seconds=10,
            latency_ms=120,
            response_payload_json={"ok": False},
        )
        await session.commit()

    async with await _client(session_factory) as client:
        graph = await client.get("/api/v1/reliability/graph")
        attempts = await client.get("/api/v1/reliability/attempts")

    assert graph.status_code == 200
    graph_payload = graph.json()
    assert [node["id"] for node in graph_payload["nodes"]] == [
        "source",
        "queue",
        "policy",
        "worker",
        "bot",
        "chat",
        "telegram",
        "result",
    ]
    assert graph_payload["nodes"][1]["count"] == 1
    assert graph_payload["edges"][0]["active"] is True

    assert attempts.status_code == 200
    attempts_payload = attempts.json()
    assert attempts_payload[0]["send_history_id"] == row.id
    assert attempts_payload[0]["status"] == "deferred"


class _FakeRedisClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.closed = False

    async def get(self, key: str) -> int:
        if self.fail:
            raise RedisError("redis down")
        return 3 if key == "send:global" else 0

    async def ttl(self, key: str) -> int:
        if self.fail:
            raise RedisError("redis down")
        return 42 if key == "send:global" else -1

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_buckets_use_redis_store_and_close_client(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = _FakeRedisClient()
    monkeypatch.setattr("redis.asyncio.from_url", lambda *_args, **_kwargs: redis_client)

    async with await _client(session_factory) as client:
        response = await client.get(
            "/api/v1/reliability/buckets",
            params={"bot_id": 7, "chat_id": "@ops", "destination_id": 9},
        )

    assert response.status_code == 200
    assert response.headers["X-Reliability-Degraded"] == "false"
    payload = response.json()
    assert payload[0] == {
        "bucket_key": "send:global",
        "limit": 60,
        "used": 3,
        "retry_after_seconds": 42,
    }
    assert {row["bucket_key"] for row in payload} == {
        "send:global",
        "send:bot:7",
        "send:chat:@ops",
        "send:destination:9",
    }
    assert redis_client.closed is True


@pytest.mark.asyncio
async def test_buckets_support_default_query_parameters(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = _FakeRedisClient()
    monkeypatch.setattr("redis.asyncio.from_url", lambda *_args, **_kwargs: redis_client)

    async with await _client(session_factory) as client:
        response = await client.get("/api/v1/reliability/buckets")

    assert response.status_code == 200
    assert {row["bucket_key"] for row in response.json()} == {
        "send:global",
        "send:bot:0",
        "send:chat:*",
    }
    assert redis_client.closed is True


@pytest.mark.asyncio
async def test_buckets_fall_back_to_memory_store_on_redis_error(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = _FakeRedisClient(fail=True)
    monkeypatch.setattr("redis.asyncio.from_url", lambda *_args, **_kwargs: redis_client)

    async with await _client(session_factory) as client:
        response = await client.get(
            "/api/v1/reliability/buckets",
            params={"bot_id": 7, "chat_id": "@ops"},
        )

    assert response.status_code == 200
    assert response.headers["X-Reliability-Degraded"] == "true"
    assert response.json() == [
        {
            "bucket_key": "send:global",
            "limit": 60,
            "used": 0,
            "retry_after_seconds": None,
        },
        {
            "bucket_key": "send:bot:7",
            "limit": 30,
            "used": 0,
            "retry_after_seconds": None,
        },
        {
            "bucket_key": "send:chat:@ops",
            "limit": 20,
            "used": 0,
            "retry_after_seconds": None,
        },
    ]
    assert redis_client.closed is True


@pytest.mark.asyncio
async def test_bulk_retry_preserves_future_retry_without_enqueueing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    future_retry_at = utc_now() + timedelta(hours=1)
    async with session_factory() as session:
        bot = await BotRepository(session).create(name="ops", token="123:abc")
        row = await SendHistoryRepository(session).create(
            bot_id=bot.id,
            chat_id="@ops",
            media_type="none",
            status="dead_letter",
            next_retry_at=future_retry_at,
        )
        await session.commit()

    enqueued: list[int] = []

    async def enqueue_send_history(send_history_id: int) -> str:
        enqueued.append(send_history_id)
        return f"task-{send_history_id}"

    async with await _client(
        session_factory,
        enqueue_send_history=enqueue_send_history,
    ) as client:
        response = await client.post(
            "/api/v1/reliability/send-history/bulk-retry",
            json={"send_history_ids": [row.id]},
        )

    assert response.status_code == 200
    assert response.json() == {"changed": 1, "skipped": 0}
    assert enqueued == []

    async with session_factory() as session:
        retried = await SendHistoryRepository(session).get(row.id)
        assert retried is not None
        assert retried.status == "queued"
        assert retried.queued_task_id is None
        assert retried.next_retry_at is not None
        assert retried.next_retry_at.replace(tzinfo=None) == future_retry_at.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_bulk_retry_retries_ready_rows_and_skips_invalid_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        bot = await BotRepository(session).create(name="ops", token="123:abc")
        history = SendHistoryRepository(session)
        failed = await history.create(
            bot_id=bot.id,
            chat_id="@ops",
            media_type="none",
            status="dead_letter",
        )
        queued = await history.create(
            bot_id=bot.id,
            chat_id="@ops",
            media_type="none",
            status="queued",
        )
        await session.commit()

    enqueued: list[int] = []

    async def enqueue_send_history(send_history_id: int) -> str:
        enqueued.append(send_history_id)
        return f"task-{send_history_id}"

    async with await _client(
        session_factory,
        enqueue_send_history=enqueue_send_history,
    ) as client:
        response = await client.post(
            "/api/v1/reliability/send-history/bulk-retry",
            json={"send_history_ids": [failed.id, queued.id, 9999]},
        )

    assert response.status_code == 200
    assert response.json() == {"changed": 1, "skipped": 2}
    assert enqueued == [failed.id]

    async with session_factory() as session:
        retried = await SendHistoryRepository(session).get(failed.id)
        assert retried is not None
        assert retried.queued_task_id == f"task-{failed.id}"


@pytest.mark.asyncio
async def test_bulk_cancel_cancels_allowed_rows_and_skips_invalid_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        bot = await BotRepository(session).create(name="ops", token="123:abc")
        history = SendHistoryRepository(session)
        queued = await history.create(
            bot_id=bot.id,
            chat_id="@ops",
            media_type="none",
            status="queued",
        )
        succeeded = await history.create(
            bot_id=bot.id,
            chat_id="@ops",
            media_type="none",
            status="succeeded",
        )
        await session.commit()

    async with await _client(session_factory) as client:
        response = await client.post(
            "/api/v1/reliability/send-history/bulk-cancel",
            json={"send_history_ids": [queued.id, succeeded.id, 9999]},
        )

    assert response.status_code == 200
    assert response.json() == {"changed": 1, "skipped": 2}

    async with session_factory() as session:
        cancelled = await SendHistoryRepository(session).get(queued.id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"
