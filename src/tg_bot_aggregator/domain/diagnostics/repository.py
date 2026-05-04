from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.models import DiagnosticBotSettings, DiagnosticUpdate, utc_now


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


class DiagnosticSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> DiagnosticBotSettings | None:
        return await _get_or_none(self.session, DiagnosticBotSettings, 1)

    async def upsert(self, **values: Any) -> DiagnosticBotSettings:
        row = await self.get()
        if row is None:
            row = DiagnosticBotSettings(id=1, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
        await self.session.flush()
        return row

class DiagnosticUpdateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> DiagnosticUpdate:
        row = DiagnosticUpdate(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self, limit: int = 100) -> list[DiagnosticUpdate]:
        statement = select(DiagnosticUpdate).order_by(DiagnosticUpdate.id.desc()).limit(limit)
        return await _list(self.session, statement)

    async def get(self, update_id: int) -> DiagnosticUpdate | None:
        return await _get_or_none(self.session, DiagnosticUpdate, update_id)

    async def get_by_update_id(self, update_id: int) -> DiagnosticUpdate | None:
        statement = select(DiagnosticUpdate).where(DiagnosticUpdate.update_id == update_id)
        return (await self.session.execute(statement)).scalar_one_or_none()

__all__ = [
    "DiagnosticSettingsRepository",
    "DiagnosticUpdateRepository",
]
