from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.domain.operations.models import (
    RuntimeAdvancedSettings,
    RuntimeSettings,
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


class RuntimeSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> RuntimeSettings | None:
        return await _get_or_none(self.session, RuntimeSettings, 1)

    async def get_or_create(self) -> RuntimeSettings:
        row = await self.get()
        if row is None:
            row = RuntimeSettings(id=1)
            self.session.add(row)
            await self.session.flush()
        return row

    async def upsert(self, **values: Any) -> RuntimeSettings:
        row = await self.get()
        if row is None:
            row = RuntimeSettings(id=1, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
        await self.session.flush()
        return row

class RuntimeAdvancedSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> RuntimeAdvancedSettings | None:
        return await _get_or_none(self.session, RuntimeAdvancedSettings, 1)

    async def get_or_create(self) -> RuntimeAdvancedSettings:
        row = await self.get()
        if row is None:
            row = RuntimeAdvancedSettings(id=1, settings_json={})
            self.session.add(row)
            await self.session.flush()
        return row

    async def upsert(self, **values: Any) -> RuntimeAdvancedSettings:
        row = await self.get_or_create()
        merged = dict(row.settings_json or {})
        merged.update(values)
        row.settings_json = merged
        row.updated_at = utc_now()
        await self.session.flush()
        return row

__all__ = [
    "RuntimeSettingsRepository",
    "RuntimeAdvancedSettingsRepository",
]
