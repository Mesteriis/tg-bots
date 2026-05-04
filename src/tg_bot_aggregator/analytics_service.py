from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.domain.analytics.mtproto import MtprotoService
from tg_bot_aggregator.infra.events import MemoryEventBus
from tg_bot_aggregator.repositories import AnalyticsRepository, NotFoundError


class AnalyticsService:
    def __init__(
        self,
        session: AsyncSession,
        mtproto: MtprotoService,
        events: MemoryEventBus,
    ) -> None:
        self.session = session
        self.mtproto = mtproto
        self.events = events
        self.analytics = AnalyticsRepository(session)

    async def refresh_target(self, target_id: int, run_id: int | None = None) -> int:
        target = await self.analytics.get_target(target_id)
        if target is None:
            raise NotFoundError(f"analytics target {target_id} not found")

        run = await self.analytics.get_run(run_id) if run_id is not None else None
        if run is None:
            run = await self.analytics.create_run(target_id=target_id, status="queued")

        await self.analytics.mark_run_started(run)
        await self.session.commit()
        await self.events.publish(
            "analytics.run.started", {"run_id": run.id, "target_id": target_id}
        )

        try:
            metrics = await self.mtproto.collect_metrics(target.peer_ref)
            snapshot = await self.analytics.create_snapshot(
                target_id=target_id,
                participants_count=metrics.participants_count,
                recent_messages_count=metrics.recent_messages_count,
                recent_views_total=metrics.recent_views_total,
                recent_forwards_total=metrics.recent_forwards_total,
                recent_replies_total=metrics.recent_replies_total,
                raw_metrics_json=metrics.raw_metrics,
            )
            await self.analytics.update_target(
                target_id,
                title=metrics.title or target.title,
                username=metrics.username or target.username,
                kind=metrics.kind or target.kind,
                last_snapshot_at=snapshot.captured_at,
            )
            await self.analytics.mark_run_finished(run, snapshots_created=1)
            await self.session.commit()
            await self.events.publish(
                "analytics.snapshot.created",
                {"target_id": target_id, "snapshot_id": snapshot.id},
            )
            await self.events.publish("analytics.run.finished", {"run_id": run.id})
            return snapshot.id
        except Exception as exc:
            await self.analytics.mark_run_failed(run, str(exc))
            await self.session.commit()
            await self.events.publish("analytics.run.failed", {"run_id": run.id})
            raise

    async def refresh_all(self) -> list[int]:
        snapshots: list[int] = []
        for target in await self.analytics.list_targets(active_only=True):
            snapshots.append(await self.refresh_target(target.id))
        return snapshots


class StaticMtprotoMetrics:
    def __init__(self, metrics: Any) -> None:
        self.metrics = metrics

    async def collect_metrics(self, peer_ref: str) -> Any:
        return self.metrics
