import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import tg_bot_aggregator.tasks as tasks_module
from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.domain.bots.repository import BotRepository
from tg_bot_aggregator.domain.destinations.repository import DestinationRepository
from tg_bot_aggregator.domain.ops.repository import (
    OpsAutomationRuleRepository,
    OpsRecommendationRepository,
)
from tg_bot_aggregator.models import Base, SendHistory
from tg_bot_aggregator.tasks import (
    backup_snapshot,
    create_broker,
    due_send_history,
    ops_automation_rules,
    run_due_send_history,
    run_ops_automation_rules,
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
    assert hasattr(ops_automation_rules, "kiq")


class _FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


class _FakeSessionContext:
    async def __aenter__(self) -> object:
        return _FakeSession()

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
        self.published: list[tuple[str, dict[str, Any]]] = []
        self.instances.append(self)

    async def publish(self, event_type: str, data: dict[str, Any]) -> str:
        self.published.append((event_type, data))
        return str(len(self.published))

    async def close(self) -> None:
        self.closed = True


class _RuntimeSettingsRepository:
    def __init__(self, session: object) -> None:
        self.session = session

    async def get(self) -> None:
        return None


class _RuntimeAdvancedSettingsRepository(_RuntimeSettingsRepository):
    pass


class _FakeAdvancedRuntimeSettings:
    def __init__(self, settings_json: dict[str, Any]) -> None:
        self.settings_json = settings_json


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

        async def release_stale_locks(self, now: object) -> int:
            calls["released_stale_locks"] = True
            calls["stale_cutoff"] = now
            return 1

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
    assert calls["released_stale_locks"] is True
    assert calls["stale_cutoff"] is not None
    assert calls["used_ready_for_lease"] is True
    assert calls["limit"] == 7
    assert calls["worker_ids"] == ["taskiq-due-send-history"]
    assert calls["rate_limiter"] is not None
    assert redis_client.closed is True
    assert len(_FakeEventBus.instances) == 1
    assert _FakeEventBus.instances[0].closed is True
    assert engine.disposed is True


@pytest.mark.asyncio
async def test_refresh_analytics_target_closes_event_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(REDIS_URL="redis://localhost:6379/15")
    engine = _FakeEngine()
    _FakeEventBus.instances = []

    class FakeMtprotoService:
        def __init__(self, *args: object) -> None:
            pass

    class FakeAnalyticsService:
        def __init__(self, session: object, mtproto: object, events: object) -> None:
            self.events = events

        async def refresh_target(self, target_id: int, run_id: int | None = None) -> int:
            assert target_id == 7
            assert run_id == 9
            return 11

    monkeypatch.setattr(tasks_module, "get_settings", lambda: settings)
    monkeypatch.setattr(tasks_module, "create_engine", lambda settings: engine)
    monkeypatch.setattr(tasks_module, "create_session_factory", lambda engine: _FakeSessionContext)
    monkeypatch.setattr(tasks_module, "MtprotoService", FakeMtprotoService)
    monkeypatch.setattr(tasks_module, "AnalyticsService", FakeAnalyticsService)
    monkeypatch.setattr(tasks_module, "RedisEventBus", _FakeEventBus)

    result = await tasks_module.run_refresh_analytics_target(7, 9)

    assert result == 11
    assert len(_FakeEventBus.instances) == 1
    assert _FakeEventBus.instances[0].closed is True
    assert engine.disposed is True


@pytest.mark.asyncio
async def test_refresh_all_analytics_targets_closes_event_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(REDIS_URL="redis://localhost:6379/15")
    engine = _FakeEngine()
    _FakeEventBus.instances = []

    class FakeMtprotoService:
        def __init__(self, *args: object) -> None:
            pass

    class FakeAnalyticsService:
        def __init__(self, session: object, mtproto: object, events: object) -> None:
            self.events = events

        async def refresh_all(self) -> list[int]:
            return [1, 2]

    monkeypatch.setattr(tasks_module, "get_settings", lambda: settings)
    monkeypatch.setattr(tasks_module, "create_engine", lambda settings: engine)
    monkeypatch.setattr(tasks_module, "create_session_factory", lambda engine: _FakeSessionContext)
    monkeypatch.setattr(tasks_module, "MtprotoService", FakeMtprotoService)
    monkeypatch.setattr(tasks_module, "AnalyticsService", FakeAnalyticsService)
    monkeypatch.setattr(tasks_module, "RedisEventBus", _FakeEventBus)

    result = await tasks_module.refresh_all_analytics_targets()

    assert result == [1, 2]
    assert len(_FakeEventBus.instances) == 1
    assert _FakeEventBus.instances[0].closed is True
    assert engine.disposed is True


@pytest.mark.asyncio
async def test_send_batch_closes_event_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(REDIS_URL="redis://localhost:6379/15")
    engine = _FakeEngine()
    _FakeEventBus.instances = []

    class FakeWorkflowService:
        def __init__(self, send_service: object) -> None:
            self.send_service = send_service

        async def enqueue_batch(self, batch_id: int) -> object:
            assert batch_id == 12
            return type("Batch", (), {"id": 34})()

    class FakeSendService:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

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
    monkeypatch.setattr(tasks_module, "SendService", FakeSendService)
    monkeypatch.setattr(tasks_module, "WorkflowService", FakeWorkflowService)
    monkeypatch.setattr(tasks_module, "RedisEventBus", _FakeEventBus)

    result = await tasks_module.run_send_batch(12)

    assert result == 34
    assert len(_FakeEventBus.instances) == 1
    assert _FakeEventBus.instances[0].closed is True
    assert engine.disposed is True


@pytest.mark.asyncio
async def test_run_ops_automation_rules_applies_low_risk_create_and_publishes_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'ops-task.db'}"
    settings = Settings(
        DATABASE_URL=database_url,
        REDIS_URL="redis://localhost:6379/15",
    )
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            bot = await BotRepository(session).create(name="ops", token="123:abc")
            await OpsRecommendationRepository(session).create(
                recommendation_type="create_destination_from_seen_chat",
                status="open",
                risk="low",
                bot_id=bot.id,
                fact_ids_json=[],
                title="Create destination",
                reason="Observed chat has no destination.",
                diff_json={
                    "operation": "create",
                    "after": {
                        "bot_id": bot.id,
                        "chat_id": "-1001",
                        "message_thread_id": None,
                        "kind": "supergroup",
                        "title": "Ops Chat",
                        "username": None,
                        "is_active": True,
                    },
                },
                action_payload_json={
                    "bot_id": bot.id,
                    "chat_id": "-1001",
                    "message_thread_id": None,
                    "kind": "supergroup",
                    "title": "Ops Chat",
                    "username": None,
                    "is_active": True,
                },
            )
            await OpsAutomationRuleRepository(session).upsert_by_key(
                "create_destination_from_seen_chat",
                title="Create destinations",
                mode="auto_apply",
                is_enabled=True,
                is_paused=False,
                risk_limit="low",
                config_json={},
            )
            await session.commit()
    finally:
        await engine.dispose()

    _FakeEventBus.instances = []
    monkeypatch.setattr(tasks_module, "get_settings", lambda: settings)
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
    monkeypatch.setattr(tasks_module, "RedisEventBus", _FakeEventBus)

    result = await run_ops_automation_rules()

    verify_engine = create_async_engine(database_url)
    verify_session_factory = async_sessionmaker(verify_engine, expire_on_commit=False)
    try:
        async with verify_session_factory() as session:
            destinations = await DestinationRepository(session).list()
    finally:
        await verify_engine.dispose()

    assert result == {"applied": 1, "skipped": 0, "failed": 0, "rules_checked": 1}
    assert len(destinations) == 1
    assert destinations[0].chat_id == "-1001"
    assert len(_FakeEventBus.instances) == 1
    assert _FakeEventBus.instances[0].published == [("ops.automation.ran", result)]
    assert _FakeEventBus.instances[0].closed is True


@pytest.mark.asyncio
async def test_run_ops_automation_rules_uses_base_database_for_settings_and_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_database_url = f"sqlite+aiosqlite:///{tmp_path / 'base.db'}"
    alternate_database_url = f"sqlite+aiosqlite:///{tmp_path / 'alternate.db'}"
    settings = Settings(
        DATABASE_URL=base_database_url,
        REDIS_URL="redis://localhost:6379/15",
    )
    base_engine = create_async_engine(base_database_url)
    alternate_engine = create_async_engine(alternate_database_url)
    try:
        async with base_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with alternate_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        base_session_factory = async_sessionmaker(base_engine, expire_on_commit=False)
        async with base_session_factory() as session:
            bot = await BotRepository(session).create(name="ops", token="123:abc")
            await OpsRecommendationRepository(session).create(
                recommendation_type="create_destination_from_seen_chat",
                status="open",
                risk="low",
                bot_id=bot.id,
                fact_ids_json=[],
                title="Create destination",
                reason="Observed chat has no destination.",
                diff_json={"operation": "create", "after": {"bot_id": bot.id}},
                action_payload_json={
                    "bot_id": bot.id,
                    "chat_id": "-1002",
                    "message_thread_id": None,
                    "kind": "supergroup",
                    "title": "Ops Chat",
                    "username": None,
                    "is_active": True,
                },
            )
            await OpsAutomationRuleRepository(session).upsert_by_key(
                "create_destination_from_seen_chat",
                title="Create destinations",
                mode="auto_apply",
                is_enabled=True,
                is_paused=False,
                risk_limit="low",
                config_json={},
            )
            await session.commit()
    finally:
        await base_engine.dispose()
        await alternate_engine.dispose()

    class AdvancedRepositoryWithDatabaseOverride(_RuntimeSettingsRepository):
        async def get(self) -> _FakeAdvancedRuntimeSettings:
            return _FakeAdvancedRuntimeSettings({"database_url": alternate_database_url})

    _FakeEventBus.instances = []
    monkeypatch.setattr(tasks_module, "get_settings", lambda: settings)
    monkeypatch.setattr(tasks_module, "RuntimeSettingsRepository", _RuntimeSettingsRepository)
    monkeypatch.setattr(
        tasks_module,
        "RuntimeAdvancedSettingsRepository",
        AdvancedRepositoryWithDatabaseOverride,
    )
    monkeypatch.setattr(tasks_module, "RedisEventBus", _FakeEventBus)

    result = await run_ops_automation_rules()

    verify_base_engine = create_async_engine(base_database_url)
    verify_alternate_engine = create_async_engine(alternate_database_url)
    try:
        verify_base_factory = async_sessionmaker(verify_base_engine, expire_on_commit=False)
        verify_alternate_factory = async_sessionmaker(
            verify_alternate_engine,
            expire_on_commit=False,
        )
        async with verify_base_factory() as session:
            base_destinations = await DestinationRepository(session).list()
        async with verify_alternate_factory() as session:
            alternate_destinations = await DestinationRepository(session).list()
    finally:
        await verify_base_engine.dispose()
        await verify_alternate_engine.dispose()

    assert result == {"applied": 1, "skipped": 0, "failed": 0, "rules_checked": 1}
    assert [destination.chat_id for destination in base_destinations] == ["-1002"]
    assert alternate_destinations == []


@pytest.mark.asyncio
async def test_scheduler_enqueues_ops_automation_without_sleeping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tg_bot_aggregator.scheduler as scheduler

    enqueued: list[str] = []

    class FakeTask:
        def __init__(self, name: str) -> None:
            self.name = name

        async def kiq(self) -> None:
            enqueued.append(self.name)

    async def stop_after_first_loop(_interval: int) -> None:
        raise asyncio.CancelledError

    monkeypatch.setenv("SCHEDULER_INTERVAL_SECONDS", "1")
    monkeypatch.setattr(
        scheduler,
        "refresh_all_analytics_targets",
        FakeTask("refresh_all_analytics_targets"),
    )
    monkeypatch.setattr(scheduler, "due_send_history", FakeTask("due_send_history"))
    monkeypatch.setattr(scheduler, "scheduled_backup_if_due", FakeTask("scheduled_backup_if_due"))
    monkeypatch.setattr(scheduler, "ops_automation_rules", FakeTask("ops_automation_rules"))
    monkeypatch.setattr(scheduler.asyncio, "sleep", stop_after_first_loop)

    with pytest.raises(asyncio.CancelledError):
        await scheduler.main()

    assert enqueued == [
        "refresh_all_analytics_targets",
        "due_send_history",
        "scheduled_backup_if_due",
        "ops_automation_rules",
    ]


@pytest.mark.asyncio
async def test_scheduler_continues_after_enqueue_failure_and_still_sleeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tg_bot_aggregator.scheduler as scheduler

    enqueued: list[str] = []
    slept: list[int] = []

    class FakeTask:
        def __init__(self, name: str, *, fail: bool = False) -> None:
            self.name = name
            self.fail = fail

        async def kiq(self) -> None:
            enqueued.append(self.name)
            if self.fail:
                raise RuntimeError(f"{self.name} failed")

    async def stop_after_first_sleep(interval: int) -> None:
        slept.append(interval)
        raise asyncio.CancelledError

    monkeypatch.setenv("SCHEDULER_INTERVAL_SECONDS", "5")
    monkeypatch.setattr(
        scheduler,
        "refresh_all_analytics_targets",
        FakeTask("refresh_all_analytics_targets"),
    )
    monkeypatch.setattr(
        scheduler,
        "due_send_history",
        FakeTask("due_send_history", fail=True),
    )
    monkeypatch.setattr(scheduler, "scheduled_backup_if_due", FakeTask("scheduled_backup_if_due"))
    monkeypatch.setattr(scheduler, "ops_automation_rules", FakeTask("ops_automation_rules"))
    monkeypatch.setattr(scheduler.asyncio, "sleep", stop_after_first_sleep)

    with pytest.raises(asyncio.CancelledError):
        await scheduler.main()

    assert enqueued == [
        "refresh_all_analytics_targets",
        "due_send_history",
        "scheduled_backup_if_due",
        "ops_automation_rules",
    ]
    assert slept == [5]


@pytest.mark.asyncio
async def test_scheduled_backup_if_due_accepts_naive_finished_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        REDIS_URL="redis://localhost:6379/15",
        BACKUP_SCHEDULE_ENABLED=True,
        BACKUP_SCHEDULE_INTERVAL_SECONDS=3600,
    )
    engine = _FakeEngine()
    latest_run = type(
        "Run",
        (),
        {"finished_at": datetime(2026, 5, 4, 12, 0, 0)},
    )()

    class FakeBackupRunRepository:
        def __init__(self, session: object) -> None:
            self.session = session

        async def list(self, limit: int = 1) -> list[object]:
            assert limit == 1
            return [latest_run]

    called: dict[str, object] = {}

    async def fake_run_backup_snapshot(push_to_git: bool | None = None) -> int:
        called["push_to_git"] = push_to_git
        return 77

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
    monkeypatch.setattr(tasks_module, "BackupRunRepository", FakeBackupRunRepository)
    monkeypatch.setattr(
        tasks_module,
        "utc_now",
        lambda: datetime(2026, 5, 4, 14, 0, 1, tzinfo=tasks_module.UTC),
    )
    monkeypatch.setattr(tasks_module, "run_backup_snapshot", fake_run_backup_snapshot)

    result = await tasks_module.run_scheduled_backup_if_due()

    assert result == 77
    assert called["push_to_git"] is False
    assert engine.disposed is True
