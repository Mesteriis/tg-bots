from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.domain.discovery.models import (
    BotDiscoveryEvent,
    BotDiscoverySettings,
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


class BotDiscoverySettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> list[BotDiscoverySettings]:
        statement = select(BotDiscoverySettings).order_by(BotDiscoverySettings.id)
        return await _list(self.session, statement)

    async def get(self, settings_id: int) -> BotDiscoverySettings | None:
        return await _get_or_none(self.session, BotDiscoverySettings, settings_id)

    async def get_for_bot(self, bot_id: int) -> BotDiscoverySettings | None:
        statement = select(BotDiscoverySettings).where(BotDiscoverySettings.bot_id == bot_id)
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def upsert_for_bot(self, bot_id: int, **values: Any) -> BotDiscoverySettings:
        row = await self.get_for_bot(bot_id)
        if row is None:
            row = BotDiscoverySettings(bot_id=bot_id, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def list_enabled(self) -> list[BotDiscoverySettings]:
        statement = select(BotDiscoverySettings).where(BotDiscoverySettings.is_enabled.is_(True))
        return await _list(self.session, statement.order_by(BotDiscoverySettings.id))

class BotDiscoveryEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> BotDiscoveryEvent:
        row = BotDiscoveryEvent(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self, limit: int = 100) -> list[BotDiscoveryEvent]:
        statement = select(BotDiscoveryEvent).order_by(BotDiscoveryEvent.id.desc()).limit(limit)
        return await _list(self.session, statement)

__all__ = [
    "BotDiscoverySettingsRepository",
    "BotDiscoveryEventRepository",
]
