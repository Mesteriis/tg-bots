from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.core.errors import NotFoundError
from tg_bot_aggregator.models import (
    AnalyticsRun,
    AnalyticsSnapshot,
    AnalyticsTarget,
    MtprotoSession,
    utc_now,
)


async def _get_or_none(session: AsyncSession, model: type[Any], row_id: int) -> Any | None:
    return await session.get(model, row_id)


async def _list(session: AsyncSession, statement: Select[tuple[Any]]) -> list[Any]:
    return list((await session.execute(statement)).scalars().all())


def _optional_equals(column: Any, value: Any) -> Any:
    return column.is_(None) if value is None else column == value


def _ops_fact_identity_key(values: dict[str, Any]) -> str:
    identity = [
        values["fact_type"],
        values.get("bot_id"),
        values.get("chat_id"),
        values.get("message_thread_id"),
        values["source"],
    ]
    payload = json.dumps(identity, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class MtprotoSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_default(self) -> MtprotoSession | None:
        statement = select(MtprotoSession).where(MtprotoSession.session_name == "default")
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def upsert_default(self, **values: Any) -> MtprotoSession:
        row = await self.get_default()
        if row is None:
            row = MtprotoSession(session_name="default", **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
        await self.session.flush()
        return row

class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_target(self, **values: Any) -> AnalyticsTarget:
        target = AnalyticsTarget(**values)
        self.session.add(target)
        await self.session.flush()
        return target

    async def list_targets(self, active_only: bool = False) -> list[AnalyticsTarget]:
        statement = select(AnalyticsTarget).order_by(AnalyticsTarget.id)
        if active_only:
            statement = statement.where(AnalyticsTarget.is_active.is_(True))
        return await _list(self.session, statement)

    async def get_target(self, target_id: int) -> AnalyticsTarget | None:
        return await _get_or_none(self.session, AnalyticsTarget, target_id)

    async def update_target(self, target_id: int, **values: Any) -> AnalyticsTarget:
        target = await self.get_target(target_id)
        if target is None:
            raise NotFoundError(f"analytics target {target_id} not found")
        for key, value in values.items():
            setattr(target, key, value)
        target.updated_at = utc_now()
        await self.session.flush()
        return target

    async def delete_target(self, target_id: int) -> bool:
        target = await self.get_target(target_id)
        if target is None:
            return False
        await self.session.delete(target)
        await self.session.flush()
        return True

    async def create_run(self, **values: Any) -> AnalyticsRun:
        run = AnalyticsRun(**values)
        self.session.add(run)
        await self.session.flush()
        return run

    async def get_run(self, run_id: int) -> AnalyticsRun | None:
        return await _get_or_none(self.session, AnalyticsRun, run_id)

    async def mark_run_started(self, run: AnalyticsRun) -> AnalyticsRun:
        run.status = "started"
        run.started_at = utc_now()
        await self.session.flush()
        return run

    async def mark_run_finished(self, run: AnalyticsRun, snapshots_created: int) -> AnalyticsRun:
        run.status = "finished"
        run.finished_at = utc_now()
        run.snapshots_created = snapshots_created
        await self.session.flush()
        return run

    async def mark_run_failed(self, run: AnalyticsRun, error_message: str) -> AnalyticsRun:
        run.status = "failed"
        run.finished_at = utc_now()
        run.error_message = error_message
        await self.session.flush()
        return run

    async def create_snapshot(self, **values: Any) -> AnalyticsSnapshot:
        snapshot = AnalyticsSnapshot(**values)
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def list_runs(self, limit: int = 100) -> list[AnalyticsRun]:
        statement = select(AnalyticsRun).order_by(AnalyticsRun.id.desc()).limit(limit)
        return await _list(self.session, statement)

    async def list_snapshots(
        self, target_id: int | None = None, limit: int = 100
    ) -> list[AnalyticsSnapshot]:
        statement = select(AnalyticsSnapshot).order_by(AnalyticsSnapshot.id.desc()).limit(limit)
        if target_id is not None:
            statement = statement.where(AnalyticsSnapshot.target_id == target_id)
        return await _list(self.session, statement)

__all__ = [
    "MtprotoSessionRepository",
    "AnalyticsRepository",
]
