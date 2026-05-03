from typing import Any

import pytest

import tg_bot_aggregator.tasks as tasks_module
from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.models import SendHistory
from tg_bot_aggregator.tasks import (
    backup_snapshot,
    create_broker,
    due_send_history,
    run_due_send_history,
    scheduled_backup_if_due,
    send_batch,
    send_history,
)


def test_taskiq_broker_can_be_constructed() -> None:
    broker = create_broker(Settings(REDIS_URL="redis://localhost:6379/15"))

    assert broker is not None
    assert hasattr(broker, "task")
    assert hasattr(send_batch, "kiq")
    assert hasattr(send_history, "kiq")
    assert hasattr(due_send_history, "kiq")
    assert hasattr(backup_snapshot, "kiq")
    assert hasattr(scheduled_backup_if_due, "kiq")


class _FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class _FakeSessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakeRedis:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeEventBus:
    instances: list["_FakeEventBus"] = []

    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url
        self.closed = False
        self.instances.append(self)

    async def close(self) -> None:
        self.closed = True


class _RuntimeSettingsRepository:
    def __init__(self, session: object) -> None:
        self.session = session

    async def get(self) -> None:
        return None


class _RuntimeAdvancedSettingsRepository(_RuntimeSettingsRepository):
    pass


@pytest.mark.asyncio
async def test_due_send_history_uses_ready_for_lease_and_closes_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(REDIS_URL="redis://localhost:6379/15")
    engine = _FakeEngine()
    redis_client = _FakeRedis()
    _FakeEventBus.instances = []
    calls: dict[str, Any] = {"worker_ids": [], "used_ready_for_lease": False}
    rows = [
        SendHistory(
            id=11,
            bot_id=1,
            chat_id="@ops",
            media_type="none",
            status="queued",
            send_mode="queued",
        )
    ]

    class FakeSendHistoryRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        async def list_ready_for_lease(self, now: object, limit: int = 100) -> list[SendHistory]:
            calls["used_ready_for_lease"] = True
            calls["limit"] = limit
            return rows

        async def list_due(self, now: object, limit: int = 100) -> list[SendHistory]:
            raise AssertionError("list_due must not be used for lease-based due processing")

    class FakeSendService:
        def __init__(self, *args: object, rate_limiter: object | None = None) -> None:
            calls["rate_limiter"] = rate_limiter

        async def process_queued_send(
            self,
            send_history_id: int,
            worker_id: str = "worker",
        ) -> SendHistory:
            calls["worker_ids"].append(worker_id)
            return rows[0]

    monkeypatch.setattr(tasks_module, "get_settings", lambda: settings)
    monkeypatch.setattr(tasks_module, "create_engine", lambda settings: engine)
    monkeypatch.setattr(tasks_module, "create_session_factory", lambda engine: _FakeSessionContext)
    monkeypatch.setattr(
        tasks_module,
        "apply_runtime_settings",
        lambda settings, basic, advanced: settings,
    )
    monkeypatch.setattr(tasks_module, "RuntimeSettingsRepository", _RuntimeSettingsRepository)
    monkeypatch.setattr(
        tasks_module,
        "RuntimeAdvancedSettingsRepository",
        _RuntimeAdvancedSettingsRepository,
    )
    monkeypatch.setattr(tasks_module, "SendHistoryRepository", FakeSendHistoryRepository)
    monkeypatch.setattr(tasks_module, "SendService", FakeSendService)
    monkeypatch.setattr(tasks_module.redis, "from_url", lambda url: redis_client)
    monkeypatch.setattr(tasks_module, "RedisEventBus", _FakeEventBus)

    processed = await run_due_send_history(limit=7)

    assert processed == [11]
    assert calls["used_ready_for_lease"] is True
    assert calls["limit"] == 7
    assert calls["worker_ids"] == ["taskiq-due-send-history"]
    assert calls["rate_limiter"] is not None
    assert redis_client.closed is True
    assert len(_FakeEventBus.instances) == 1
    assert _FakeEventBus.instances[0].closed is True
    assert engine.disposed is True
