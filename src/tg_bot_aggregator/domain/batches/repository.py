from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.models import SendBatch, SendBatchItem, utc_now


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


class SendBatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_batch(self, **values: Any) -> SendBatch:
        row = SendBatch(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def add_item(self, batch_id: int, **values: Any) -> SendBatchItem:
        row = SendBatchItem(batch_id=batch_id, **values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_batches(self, limit: int = 100) -> list[SendBatch]:
        statement = select(SendBatch).order_by(SendBatch.id.desc()).limit(limit)
        return await _list(self.session, statement)

    async def get_batch(self, batch_id: int) -> SendBatch | None:
        return await _get_or_none(self.session, SendBatch, batch_id)

    async def list_items(self, batch_id: int) -> list[SendBatchItem]:
        statement = select(SendBatchItem).where(SendBatchItem.batch_id == batch_id).order_by(
            SendBatchItem.id
        )
        return await _list(self.session, statement)

    async def get_item(self, item_id: int) -> SendBatchItem | None:
        return await _get_or_none(self.session, SendBatchItem, item_id)

    async def mark_batch_status(self, batch: SendBatch, status: str) -> SendBatch:
        batch.status = status
        batch.updated_at = utc_now()
        if status == "queued":
            batch.queued_at = utc_now()
        if status in {"finished", "failed", "cancelled"}:
            batch.finished_at = utc_now()
        await self.session.flush()
        return batch

    async def mark_item_status(
        self,
        item: SendBatchItem,
        status: str,
        send_history_id: int | None = None,
        error_message: str | None = None,
    ) -> SendBatchItem:
        item.status = status
        if send_history_id is not None:
            item.send_history_id = send_history_id
        item.error_message = error_message
        item.updated_at = utc_now()
        await self.session.flush()
        return item

__all__ = [
    "SendBatchRepository",
]
