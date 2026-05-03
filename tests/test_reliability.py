from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.models import utc_now
from tg_bot_aggregator.repositories import (
    BotRepository,
    SendAttemptRepository,
    SendHistoryRepository,
)


async def _create_leased_history(db_session: AsyncSession):
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    history = SendHistoryRepository(db_session)
    row = await history.create(
        bot_id=bot.id,
        chat_id="@ops",
        media_type="none",
        status="queued",
        send_mode="queued",
        request_payload_json={"method": "sendMessage", "chat_id": "@ops", "text": "hello"},
    )
    leased = await history.acquire_due_lease(
        row_id=row.id,
        worker_id="worker-a",
        now=utc_now(),
        lease_seconds=30,
    )

    assert leased is not None
    assert leased.locked_by == "worker-a"
    assert leased.lock_expires_at is not None
    return history, leased


@pytest.mark.asyncio
async def test_send_history_lease_prevents_double_processing(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    history = SendHistoryRepository(db_session)
    row = await history.create(
        bot_id=bot.id,
        chat_id="@ops",
        media_type="none",
        status="queued",
        send_mode="queued",
        request_payload_json={"method": "sendMessage", "chat_id": "@ops", "text": "hello"},
    )
    await db_session.commit()

    leased = await history.acquire_due_lease(
        row_id=row.id,
        worker_id="worker-a",
        now=utc_now(),
        lease_seconds=30,
    )
    duplicate = await history.acquire_due_lease(
        row_id=row.id,
        worker_id="worker-b",
        now=utc_now(),
        lease_seconds=30,
    )

    assert leased is not None
    assert leased.status == "sending"
    assert leased.locked_by == "worker-a"
    assert leased.lock_expires_at is not None
    assert duplicate is None


@pytest.mark.asyncio
async def test_send_history_mark_succeeded_clears_lease(
    db_session: AsyncSession,
) -> None:
    history, row = await _create_leased_history(db_session)

    await history.mark_succeeded(row, telegram_message_id=42, response={"ok": True})

    assert row.status == "succeeded"
    assert row.locked_at is None
    assert row.locked_by is None
    assert row.lock_expires_at is None


@pytest.mark.asyncio
async def test_send_history_mark_failed_clears_lease(
    db_session: AsyncSession,
) -> None:
    history, row = await _create_leased_history(db_session)

    await history.mark_failed(
        row,
        error_code="telegram_error",
        error_message="send failed",
        response={"ok": False},
    )

    assert row.status == "failed"
    assert row.locked_at is None
    assert row.locked_by is None
    assert row.lock_expires_at is None


@pytest.mark.asyncio
async def test_send_history_mark_cancelled_clears_lease(
    db_session: AsyncSession,
) -> None:
    history, row = await _create_leased_history(db_session)

    await history.mark_cancelled(row)

    assert row.status == "cancelled"
    assert row.locked_at is None
    assert row.locked_by is None
    assert row.lock_expires_at is None


@pytest.mark.asyncio
async def test_send_attempts_are_append_only(db_session: AsyncSession) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    history = SendHistoryRepository(db_session)
    row = await history.create(
        bot_id=bot.id,
        chat_id="@ops",
        media_type="none",
        status="queued",
        send_mode="queued",
        request_payload_json={"method": "sendMessage", "chat_id": "@ops", "text": "hello"},
    )
    attempts = SendAttemptRepository(db_session)
    await attempts.create(
        send_history_id=row.id,
        attempt_number=1,
        worker_id="worker-a",
        started_at=utc_now(),
        finished_at=utc_now() + timedelta(milliseconds=120),
        status="deferred",
        telegram_error_code="429",
        error_kind="telegram_rate_limit",
        error_message="Too Many Requests",
        retry_after_seconds=10,
        latency_ms=120,
        response_payload_json={"ok": False, "token": "***"},
    )
    await db_session.commit()

    rows = await attempts.list_for_send(row.id)

    assert len(rows) == 1
    assert rows[0].attempt_number == 1
    assert rows[0].status == "deferred"
    assert rows[0].error_kind == "telegram_rate_limit"
