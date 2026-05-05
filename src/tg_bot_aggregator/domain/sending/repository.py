from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.core.errors import NotFoundError
from tg_bot_aggregator.domain.sending.models import (
    SendAttempt,
    SendHistory,
    SendProfile,
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


class SendProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> SendProfile:
        row = SendProfile(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self, active_only: bool = False) -> list[SendProfile]:
        statement = select(SendProfile).order_by(SendProfile.id)
        if active_only:
            statement = statement.where(SendProfile.is_active.is_(True))
        return await _list(self.session, statement)

    async def get(self, profile_id: int) -> SendProfile | None:
        return await _get_or_none(self.session, SendProfile, profile_id)

    async def update(self, profile_id: int, **values: Any) -> SendProfile:
        row = await self.get(profile_id)
        if row is None:
            raise NotFoundError(f"send profile {profile_id} not found")
        for key, value in values.items():
            setattr(row, key, value)
        row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def delete(self, profile_id: int) -> bool:
        row = await self.get(profile_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

class SendHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> SendHistory:
        row = SendHistory(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, row_id: int) -> SendHistory | None:
        return await _get_or_none(self.session, SendHistory, row_id)

    async def get_by_idempotency_key(self, idempotency_key: str) -> SendHistory | None:
        statement = select(SendHistory).where(SendHistory.idempotency_key == idempotency_key)
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list(self, limit: int = 100) -> list[SendHistory]:
        statement = select(SendHistory).order_by(SendHistory.id.desc()).limit(limit)
        return await _list(self.session, statement)

    async def list_failed(self, limit: int = 100) -> list[SendHistory]:
        statement = (
            select(SendHistory)
            .where(SendHistory.status == "failed")
            .order_by(SendHistory.id.desc())
            .limit(limit)
        )
        return await _list(self.session, statement)

    async def list_due(self, now: datetime, limit: int = 100) -> list[SendHistory]:
        statement = (
            select(SendHistory)
            .where(
                SendHistory.status == "queued",
                SendHistory.next_retry_at.is_not(None),
                SendHistory.next_retry_at <= now,
            )
            .order_by(SendHistory.next_retry_at, SendHistory.id)
            .limit(limit)
        )
        return await _list(self.session, statement)

    async def acquire_due_lease(
        self,
        row_id: int,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> SendHistory | None:
        statement = (
            update(SendHistory)
            .where(
                SendHistory.id == row_id,
                SendHistory.status.in_(("queued", "deferred", "created")),
                or_(SendHistory.next_retry_at.is_(None), SendHistory.next_retry_at <= now),
                or_(SendHistory.lock_expires_at.is_(None), SendHistory.lock_expires_at <= now),
            )
            .values(
                status="sending",
                locked_at=now,
                locked_by=worker_id,
                lock_expires_at=now + timedelta(seconds=lease_seconds),
            )
            .execution_options(synchronize_session=False)
        )
        result = await self.session.execute(statement)
        if result.rowcount != 1:
            return None
        await self.session.flush()
        row = await self.get(row_id)
        if row is not None:
            await self.session.refresh(row)
        return row

    async def list_ready_for_lease(self, now: datetime, limit: int = 100) -> list[SendHistory]:
        statement = (
            select(SendHistory)
            .where(
                SendHistory.status.in_(("queued", "deferred")),
                or_(SendHistory.next_retry_at.is_(None), SendHistory.next_retry_at <= now),
                or_(SendHistory.lock_expires_at.is_(None), SendHistory.lock_expires_at <= now),
            )
            .order_by(SendHistory.priority, SendHistory.next_retry_at, SendHistory.id)
            .limit(limit)
        )
        return await _list(self.session, statement)

    async def list_stale_locks(self, now: datetime, limit: int = 100) -> list[SendHistory]:
        statement = (
            select(SendHistory)
            .where(SendHistory.status == "sending", SendHistory.lock_expires_at <= now)
            .order_by(SendHistory.lock_expires_at, SendHistory.id)
            .limit(limit)
        )
        return await _list(self.session, statement)

    async def count_for_bot_since(self, bot_id: int, since: datetime) -> int:
        statement = select(func.count()).select_from(SendHistory).where(
            SendHistory.bot_id == bot_id,
            SendHistory.created_at >= since,
            SendHistory.status.in_(("created", "sending", "queued", "succeeded")),
        )
        return int((await self.session.execute(statement)).scalar_one())

    async def mark_succeeded(
        self,
        row: SendHistory,
        telegram_message_id: int | None,
        response: dict[str, Any],
    ) -> SendHistory:
        row.status = "succeeded"
        row.error_code = None
        row.error_message = None
        row.telegram_message_id = telegram_message_id
        row.response_payload_json = response
        row.sent_at = utc_now()
        row.locked_at = None
        row.locked_by = None
        row.lock_expires_at = None
        await self.session.flush()
        return row

    async def mark_queued(self, row: SendHistory, task_id: str | None = None) -> SendHistory:
        row.status = "queued"
        row.queued_task_id = task_id
        await self.session.flush()
        return row

    async def mark_sending(self, row: SendHistory, attempt_count: int) -> SendHistory:
        row.status = "sending"
        row.attempt_count = attempt_count
        await self.session.flush()
        return row

    async def mark_failed(
        self,
        row: SendHistory,
        error_code: str,
        error_message: str,
        response: dict[str, Any] | None = None,
    ) -> SendHistory:
        row.status = "failed"
        row.error_code = error_code
        row.error_message = error_message
        row.response_payload_json = response
        row.failed_at = utc_now()
        row.locked_at = None
        row.locked_by = None
        row.lock_expires_at = None
        await self.session.flush()
        return row

    async def mark_cancelled(
        self,
        row: SendHistory,
        error_message: str = "cancelled by user",
    ) -> SendHistory:
        row.status = "cancelled"
        row.error_code = "cancelled"
        row.error_message = error_message
        row.queued_task_id = None
        row.next_retry_at = None
        row.locked_at = None
        row.locked_by = None
        row.lock_expires_at = None
        await self.session.flush()
        return row

    async def mark_deferred(
        self,
        row: SendHistory,
        error_code: str | None,
        error_message: str,
        error_kind: str,
        next_retry_at: datetime,
        retry_after_seconds: int | None,
        response: dict[str, Any] | None = None,
    ) -> SendHistory:
        row.status = "deferred"
        row.error_code = error_code
        row.error_message = error_message
        row.last_error_kind = error_kind
        row.next_retry_at = next_retry_at
        row.retry_after_seconds = retry_after_seconds
        row.response_payload_json = response
        row.locked_at = None
        row.locked_by = None
        row.lock_expires_at = None
        await self.session.flush()
        return row

    async def mark_dead_letter(
        self,
        row: SendHistory,
        error_code: str | None,
        error_message: str,
        error_kind: str,
        response: dict[str, Any] | None = None,
    ) -> SendHistory:
        row.status = "dead_letter"
        row.error_code = error_code
        row.error_message = error_message
        row.last_error_kind = error_kind
        row.response_payload_json = response
        row.failed_at = utc_now()
        row.locked_at = None
        row.locked_by = None
        row.lock_expires_at = None
        await self.session.flush()
        return row

    async def mark_blocked(
        self,
        row: SendHistory,
        error_code: str | None,
        error_message: str,
        error_kind: str,
    ) -> SendHistory:
        row.status = "blocked"
        row.error_code = error_code
        row.error_message = error_message
        row.last_error_kind = error_kind
        row.failed_at = utc_now()
        row.locked_at = None
        row.locked_by = None
        row.lock_expires_at = None
        await self.session.flush()
        return row

    async def release_stale_locks(self, now: datetime) -> int:
        rows = await self.list_stale_locks(now, limit=1000)
        for row in rows:
            row.status = "queued"
            row.locked_at = None
            row.locked_by = None
            row.lock_expires_at = None
        await self.session.flush()
        return len(rows)

class SendAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> SendAttempt:
        row = SendAttempt(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_for_send(self, send_history_id: int) -> list[SendAttempt]:
        statement = (
            select(SendAttempt)
            .where(SendAttempt.send_history_id == send_history_id)
            .order_by(SendAttempt.attempt_number, SendAttempt.id)
        )
        return await _list(self.session, statement)

    async def list(self, limit: int = 100) -> list[SendAttempt]:
        statement = select(SendAttempt).order_by(SendAttempt.id.desc()).limit(limit)
        return await _list(self.session, statement)

__all__ = [
    "SendProfileRepository",
    "SendHistoryRepository",
    "SendAttemptRepository",
]
