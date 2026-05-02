import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.analytics_service import AnalyticsService
from tg_bot_aggregator.events import MemoryEventBus
from tg_bot_aggregator.mtproto_service import AnalyticsMetrics
from tg_bot_aggregator.repositories import AnalyticsRepository


class FakeMtproto:
    async def collect_metrics(self, peer_ref: str) -> AnalyticsMetrics:
        return AnalyticsMetrics(
            title="Channel",
            username="channel",
            kind="Channel",
            participants_count=None,
            recent_messages_count=2,
            recent_views_total=15,
            recent_forwards_total=None,
            recent_replies_total=None,
            raw_metrics={"peer_ref": peer_ref, "partial": True},
        )


class FailingMtproto:
    async def collect_metrics(self, peer_ref: str) -> AnalyticsMetrics:
        raise RuntimeError(f"cannot resolve {peer_ref}")


async def test_refresh_target_writes_partial_snapshot(db_session: AsyncSession) -> None:
    repo = AnalyticsRepository(db_session)
    target = await repo.create_target(peer_ref="@channel")
    await db_session.commit()
    bus = MemoryEventBus()
    service = AnalyticsService(db_session, FakeMtproto(), bus)

    snapshot_id = await service.refresh_target(target.id)

    snapshots = await repo.list_snapshots(target_id=target.id)
    runs = await repo.list_runs()
    assert snapshots[0].id == snapshot_id
    assert snapshots[0].participants_count is None
    assert snapshots[0].recent_views_total == 15
    assert runs[0].status == "finished"
    assert (await bus.latest()).event_type == "analytics.run.finished"


async def test_refresh_target_marks_run_failed(db_session: AsyncSession) -> None:
    repo = AnalyticsRepository(db_session)
    target = await repo.create_target(peer_ref="@missing")
    await db_session.commit()
    service = AnalyticsService(db_session, FailingMtproto(), MemoryEventBus())

    with pytest.raises(RuntimeError):
        await service.refresh_target(target.id)

    assert (await repo.list_runs())[0].status == "failed"

