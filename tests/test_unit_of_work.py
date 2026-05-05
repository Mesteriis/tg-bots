import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

import tg_bot_aggregator.infra.uow as uow_module
from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.infra.uow import UnitOfWork


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.commit_calls = 0
        self.rolled_back = False
        self.rollback_calls = 0
        self.closed = False

    async def commit(self) -> None:
        self.commit_calls += 1
        self.committed = True

    async def rollback(self) -> None:
        self.rollback_calls += 1
        self.rolled_back = True

    async def close(self) -> None:
        self.closed = True

    def in_transaction(self) -> bool:
        return not (self.committed or self.rolled_back)


class FakeLock:
    def __init__(self) -> None:
        self.acquired = False
        self.released = False

    async def acquire(self) -> bool:
        self.acquired = True
        return True

    async def release(self) -> None:
        self.released = True


class FakeRedisClient:
    def __init__(self, lock: FakeLock) -> None:
        self.lock_instance = lock
        self.closed = False
        self.keys: list[str] = []

    def lock(self, key: str, timeout: int, blocking_timeout: int) -> FakeLock:
        self.keys.append(key)
        assert timeout == 60
        assert blocking_timeout == 60
        return self.lock_instance

    async def aclose(self) -> None:
        self.closed = True


class FailingRedisLock:
    async def acquire(self) -> bool:
        raise RedisConnectionError("redis unavailable")

    async def release(self) -> None:
        return None


class FailingRedisClient:
    def __init__(self) -> None:
        self.closed = False

    def lock(
        self, key: str, timeout: int, blocking_timeout: int
    ) -> FailingRedisLock:
        return FailingRedisLock()

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_unit_of_work_commits_and_closes_on_success() -> None:
    session = FakeSession()

    async with UnitOfWork(lambda: session) as uow:
        assert uow.session is session
        assert uow.bots
        assert uow.tokens
        assert uow.destinations
        assert uow.templates
        assert uow.sending
        assert uow.attempts
        assert uow.batches
        assert uow.backups
        assert uow.ops
        assert uow.audit

    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True
    assert session.commit_calls == 1


@pytest.mark.asyncio
async def test_unit_of_work_rolls_back_and_closes_on_error() -> None:
    session = FakeSession()

    with pytest.raises(RuntimeError):
        async with UnitOfWork(lambda: session):
            raise RuntimeError("boom")

    assert session.committed is False
    assert session.rolled_back is True
    assert session.closed is True
    assert session.rollback_calls == 1


@pytest.mark.asyncio
async def test_unit_of_work_supports_manual_commit_without_double_commit() -> None:
    session = FakeSession()

    async with UnitOfWork(lambda: session) as uow:
        await uow.commit()

    assert session.committed is True
    assert session.closed is True
    assert session.commit_calls == 1


@pytest.mark.asyncio
async def test_unit_of_work_supports_manual_rollback_without_double_rollback() -> None:
    session = FakeSession()

    async with UnitOfWork(lambda: session) as uow:
        await uow.rollback()

    assert session.rolled_back is True
    assert session.closed is True
    assert session.rollback_calls == 1


@pytest.mark.asyncio
async def test_unit_of_work_acquires_and_releases_sqlite_redis_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    lock = FakeLock()
    client = FakeRedisClient(lock)
    monkeypatch.setattr(uow_module.redis, "from_url", lambda url: client)

    async with UnitOfWork(
        lambda: session,
        settings=Settings(
            DATABASE_URL="sqlite+aiosqlite:////tmp/test.db",
            REDIS_URL="redis://localhost:6379/15",
        ),
    ):
        pass

    assert lock.acquired is True
    assert lock.released is True
    assert client.closed is True
    assert client.keys[0].startswith("tg-bot-aggregator:sqlite-uow:")


@pytest.mark.asyncio
async def test_unit_of_work_falls_back_when_sqlite_redis_lock_backend_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    client = FailingRedisClient()
    monkeypatch.setattr(uow_module.redis, "from_url", lambda url: client)

    async with UnitOfWork(
        lambda: session,
        settings=Settings(
            DATABASE_URL="sqlite+aiosqlite:////tmp/test.db",
            REDIS_URL="redis://redis:6379/15",
        ),
    ):
        pass

    assert session.committed is True
    assert session.closed is True
    assert client.closed is True
