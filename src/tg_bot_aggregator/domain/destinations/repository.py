from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.core.errors import NotFoundError
from tg_bot_aggregator.models import Destination, DestinationHealth, utc_now


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


class DestinationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> Destination:
        destination = Destination(**values)
        self.session.add(destination)
        await self.session.flush()
        return destination

    async def list(self) -> list[Destination]:
        return await _list(self.session, select(Destination).order_by(Destination.id))

    async def get(self, destination_id: int) -> Destination | None:
        return await _get_or_none(self.session, Destination, destination_id)

    async def get_by_chat(
        self,
        bot_id: int,
        chat_id: str,
        message_thread_id: int | None = None,
    ) -> Destination | None:
        statement = select(Destination).where(
            Destination.bot_id == bot_id,
            Destination.chat_id == chat_id,
            Destination.message_thread_id.is_(message_thread_id)
            if message_thread_id is None
            else Destination.message_thread_id == message_thread_id,
        )
        return (await self.session.execute(statement)).scalars().first()

    async def get_by_alias(self, bot_id: int, alias: str) -> Destination | None:
        statement = select(Destination).where(
            Destination.bot_id == bot_id,
            Destination.alias == alias,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def upsert_by_chat(
        self,
        bot_id: int,
        chat_id: str,
        message_thread_id: int | None = None,
        **values: Any,
    ) -> Destination:
        row = await self.get_by_chat(bot_id, chat_id, message_thread_id)
        if row is None:
            nested = await self.session.begin_nested()
            try:
                row = Destination(
                    bot_id=bot_id,
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    **values,
                )
                self.session.add(row)
                await self.session.flush()
            except IntegrityError:
                await nested.rollback()
                row = await self.get_by_chat(bot_id, chat_id, message_thread_id)
                if row is None:
                    raise
                for key, value in values.items():
                    setattr(row, key, value)
                row.updated_at = utc_now()
            else:
                await nested.commit()
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def update(self, destination_id: int, **values: Any) -> Destination:
        destination = await self.get(destination_id)
        if destination is None:
            raise NotFoundError(f"destination {destination_id} not found")
        for key, value in values.items():
            setattr(destination, key, value)
        destination.updated_at = utc_now()
        await self.session.flush()
        return destination

    async def delete(self, destination_id: int) -> bool:
        destination = await self.get(destination_id)
        if destination is None:
            return False
        await self.session.delete(destination)
        await self.session.flush()
        return True

class DestinationHealthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_destination(self, destination_id: int) -> DestinationHealth | None:
        statement = select(DestinationHealth).where(
            DestinationHealth.destination_id == destination_id
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def upsert_for_destination(
        self,
        destination_id: int,
        **values: Any,
    ) -> DestinationHealth:
        row = await self.get_for_destination(destination_id)
        if row is None:
            row = DestinationHealth(destination_id=destination_id, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.checked_at = utc_now()
        await self.session.flush()
        return row

__all__ = [
    "DestinationRepository",
    "DestinationHealthRepository",
]
