from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.core.errors import NotFoundError
from tg_bot_aggregator.models import Bot, utc_now


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


class BotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> Bot:
        bot = Bot(**values)
        self.session.add(bot)
        await self.session.flush()
        return bot

    async def list(self) -> list[Bot]:
        return await _list(self.session, select(Bot).order_by(Bot.id))

    async def get(self, bot_id: int) -> Bot | None:
        return await _get_or_none(self.session, Bot, bot_id)

    async def get_by_token(self, token: str) -> Bot | None:
        statement = select(Bot).where(Bot.token == token)
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def update(self, bot_id: int, **values: Any) -> Bot:
        bot = await self.get(bot_id)
        if bot is None:
            raise NotFoundError(f"bot {bot_id} not found")
        for key, value in values.items():
            setattr(bot, key, value)
        bot.updated_at = utc_now()
        await self.session.flush()
        return bot

    async def delete(self, bot_id: int) -> bool:
        bot = await self.get(bot_id)
        if bot is None:
            return False
        await self.session.delete(bot)
        await self.session.flush()
        return True

__all__ = [
    "BotRepository",
]
