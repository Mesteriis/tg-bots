from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.models import ApiToken, utc_now


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


class ApiTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> ApiToken:
        row = ApiToken(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self, active_only: bool = False) -> list[ApiToken]:
        statement = select(ApiToken).order_by(ApiToken.id.desc())
        if active_only:
            statement = statement.where(ApiToken.is_active.is_(True))
        return await _list(self.session, statement)

    async def get(self, token_id: int) -> ApiToken | None:
        return await _get_or_none(self.session, ApiToken, token_id)

    async def get_by_hash(self, token_hash: str) -> ApiToken | None:
        statement = select(ApiToken).where(ApiToken.token_hash == token_hash)
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def mark_used(self, row: ApiToken) -> ApiToken:
        row.last_used_at = utc_now()
        row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def revoke(self, token_id: int) -> bool:
        row = await self.get(token_id)
        if row is None:
            return False
        row.is_active = False
        row.revoked_at = utc_now()
        row.updated_at = utc_now()
        await self.session.flush()
        return True

__all__ = [
    "ApiTokenRepository",
]
