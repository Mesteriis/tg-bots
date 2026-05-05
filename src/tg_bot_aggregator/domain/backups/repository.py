from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.domain.backups.models import BackupRun, utc_now


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


class BackupRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> BackupRun:
        row = BackupRun(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self, limit: int = 50) -> list[BackupRun]:
        statement = select(BackupRun).order_by(BackupRun.id.desc()).limit(limit)
        return await _list(self.session, statement)

    async def get(self, run_id: int) -> BackupRun | None:
        return await _get_or_none(self.session, BackupRun, run_id)

    async def latest_successful(self) -> BackupRun | None:
        statement = (
            select(BackupRun)
            .where(BackupRun.status == "succeeded", BackupRun.backup_json.is_not(None))
            .order_by(BackupRun.id.desc())
            .limit(1)
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def mark_finished(
        self,
        row: BackupRun,
        *,
        status: str,
        items_exported: int,
        backup_json: dict[str, Any] | None = None,
        git_commit: str | None = None,
        error_message: str | None = None,
    ) -> BackupRun:
        row.status = status
        row.items_exported = items_exported
        row.backup_json = backup_json
        row.git_commit = git_commit
        row.error_message = error_message
        row.finished_at = utc_now()
        await self.session.flush()
        return row

__all__ = [
    "BackupRunRepository",
]
