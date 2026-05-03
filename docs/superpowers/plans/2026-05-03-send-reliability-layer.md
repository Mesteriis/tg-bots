# Send Reliability Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build reliable Telegram send processing with leases, explicit backoff, rate buckets, attempt history, dead-letter/blocked states, REST/MCP/SSE visibility, and a live dashboard graph while preserving all existing dashboard workflows.

**Architecture:** Extend the existing `SendService`, `send_history`, Taskiq, Redis, and SQLite path. Add focused reliability services for policy, rate limiting, and queue leases; `send_history` remains the canonical current state and `send_attempts` is append-only diagnostics. REST, MCP, and UI call the same reliability services and do not bypass redaction, audit, or existing send validation.

**Tech Stack:** FastAPI, SQLAlchemy async, SQLite/Alembic, Taskiq, Redis, Vue 3 CDN, pytest, ruff.

---

## File Structure

Create:

- `src/tg_bot_aggregator/reliability.py`: policy decisions, failure classification, backoff calculation, rate limiter, queue lease service, graph/summary builder.
- `src/tg_bot_aggregator/api/reliability.py`: REST endpoints under `/api/v1/reliability`.
- `alembic/versions/0007_send_reliability_layer.py`: additive DB migration.
- `tests/test_reliability.py`: unit tests for policy, backoff, leases, attempts, and summaries.
- `tests/test_api_reliability.py`: REST integration tests.

Modify:

- `src/tg_bot_aggregator/models.py`: add reliability fields to `SendHistory` and add `SendAttempt`.
- `src/tg_bot_aggregator/repositories.py`: add `SendAttemptRepository` and reliability methods on `SendHistoryRepository`.
- `src/tg_bot_aggregator/schemas.py`: add reliability request/response schemas and runtime settings fields.
- `src/tg_bot_aggregator/config.py`: add reliability runtime settings with env aliases.
- `src/tg_bot_aggregator/runtime_settings.py`: expose reliability fields in runtime settings.
- `src/tg_bot_aggregator/send_service.py`: route queued processing through reliability decisions while preserving sync behavior.
- `src/tg_bot_aggregator/tasks.py`: use lease-based due processing and avoid worker sleep loops.
- `src/tg_bot_aggregator/main.py`: register reliability router.
- `src/tg_bot_aggregator/mcp_catalog.py`: register reliability MCP tools.
- `src/tg_bot_aggregator/mcp_server.py`: implement reliability MCP tools through the same service.
- `src/tg_bot_aggregator/static/index.html`: add `Надежность` graph/drill-down while keeping all current tabs and controls.
- `tests/test_send_service.py`: update queued retry expectations for deferred/dead-letter/blocked states.
- `tests/test_tasks.py`: add worker lease/due regression coverage.
- `tests/test_mcp_server.py`: add MCP reliability tool coverage.
- `tests/test_static_ui.py`: prove all existing dashboard features remain and graph UI exists.
- `README.md`: document reliability behavior and endpoints.

---

### Task 1: Schema, Models, And Repository Primitives

**Files:**
- Create: `alembic/versions/0007_send_reliability_layer.py`
- Modify: `src/tg_bot_aggregator/models.py`
- Modify: `src/tg_bot_aggregator/repositories.py`
- Test: `tests/test_reliability.py`

- [ ] **Step 1: Write failing repository tests**

Add these tests to `tests/test_reliability.py`:

```python
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.models import utc_now
from tg_bot_aggregator.repositories import BotRepository, SendAttemptRepository, SendHistoryRepository


@pytest.mark.asyncio
async def test_send_history_lease_prevents_double_processing(db_session: AsyncSession) -> None:
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_reliability.py -q
```

Expected: FAIL because `SendAttemptRepository` and `acquire_due_lease` do not exist.

- [ ] **Step 3: Add model fields and `SendAttempt`**

Modify `src/tg_bot_aggregator/models.py`.

Add these fields to `SendHistory` after `next_retry_at`:

```python
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(200))
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer)
    last_error_kind: Mapped[str | None] = mapped_column(String(80))
    dedupe_window_key: Mapped[str | None] = mapped_column(String(200))
```

Add this model after `SendHistory`:

```python
class SendAttempt(Base):
    __tablename__ = "send_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    send_history_id: Mapped[int] = mapped_column(
        ForeignKey("send_history.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    telegram_error_code: Mapped[str | None] = mapped_column(String(100))
    error_kind: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    response_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
```

- [ ] **Step 4: Add Alembic migration**

Create `alembic/versions/0007_send_reliability_layer.py`:

```python
"""send reliability layer

Revision ID: 0007_send_reliability_layer
Revises: 0006_operations_layer
Create Date: 2026-05-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_send_reliability_layer"
down_revision: str | None = "0006_operations_layer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("send_history", sa.Column("priority", sa.Integer(), nullable=False, server_default="100"))
    op.add_column("send_history", sa.Column("locked_at", sa.DateTime(timezone=True)))
    op.add_column("send_history", sa.Column("locked_by", sa.String(length=200)))
    op.add_column("send_history", sa.Column("lock_expires_at", sa.DateTime(timezone=True)))
    op.add_column("send_history", sa.Column("last_attempt_at", sa.DateTime(timezone=True)))
    op.add_column("send_history", sa.Column("retry_after_seconds", sa.Integer()))
    op.add_column("send_history", sa.Column("last_error_kind", sa.String(length=80)))
    op.add_column("send_history", sa.Column("dedupe_window_key", sa.String(length=200)))
    op.create_index("ix_send_history_due_priority", "send_history", ["status", "next_retry_at", "priority", "id"])
    op.create_index("ix_send_history_lock_expires", "send_history", ["status", "lock_expires_at"])
    op.create_table(
        "send_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("send_history_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=200)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("telegram_error_code", sa.String(length=100)),
        sa.Column("error_kind", sa.String(length=80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("retry_after_seconds", sa.Integer()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("response_payload_json", sa.JSON()),
        sa.ForeignKeyConstraint(["send_history_id"], ["send_history.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_send_attempts_send_history_id", "send_attempts", ["send_history_id"])


def downgrade() -> None:
    op.drop_index("ix_send_attempts_send_history_id", table_name="send_attempts")
    op.drop_table("send_attempts")
    op.drop_index("ix_send_history_lock_expires", table_name="send_history")
    op.drop_index("ix_send_history_due_priority", table_name="send_history")
    op.drop_column("send_history", "dedupe_window_key")
    op.drop_column("send_history", "last_error_kind")
    op.drop_column("send_history", "retry_after_seconds")
    op.drop_column("send_history", "last_attempt_at")
    op.drop_column("send_history", "lock_expires_at")
    op.drop_column("send_history", "locked_by")
    op.drop_column("send_history", "locked_at")
    op.drop_column("send_history", "priority")
```

- [ ] **Step 5: Add repository methods**

Modify `src/tg_bot_aggregator/repositories.py`.

Import `or_` from SQLAlchemy:

```python
from sqlalchemy import func, or_, select
```

Import `SendAttempt` from models.

Add these methods to `SendHistoryRepository`:

```python
    async def acquire_due_lease(
        self,
        row_id: int,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> SendHistory | None:
        row = await self.get(row_id)
        if row is None:
            return None
        if row.status not in {"queued", "deferred", "created"}:
            return None
        if row.next_retry_at is not None and row.next_retry_at > now:
            return None
        if row.lock_expires_at is not None and row.lock_expires_at > now:
            return None
        row.status = "sending"
        row.locked_at = now
        row.locked_by = worker_id
        row.lock_expires_at = now + timedelta(seconds=lease_seconds)
        await self.session.flush()
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
```

Add repository:

```python
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
```

- [ ] **Step 6: Run repository tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_reliability.py -q
```

Expected: PASS for the two repository tests.

- [ ] **Step 7: Commit schema primitives**

```bash
git add alembic/versions/0007_send_reliability_layer.py src/tg_bot_aggregator/models.py src/tg_bot_aggregator/repositories.py tests/test_reliability.py
git commit -m "feat: add send reliability persistence"
```

---

### Task 2: Runtime Settings, Failure Classification, And Backoff Policy

**Files:**
- Create: `src/tg_bot_aggregator/reliability.py`
- Modify: `src/tg_bot_aggregator/config.py`
- Modify: `src/tg_bot_aggregator/runtime_settings.py`
- Modify: `src/tg_bot_aggregator/schemas.py`
- Test: `tests/test_reliability.py`

- [ ] **Step 1: Add failing policy tests**

Append to `tests/test_reliability.py`:

```python
from datetime import UTC, datetime

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.reliability import (
    RetryDecision,
    classify_telegram_error,
    compute_retry_decision,
)
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiError


def test_classify_telegram_rate_limit() -> None:
    exc = TelegramBotApiError(
        method="sendMessage",
        error_code=429,
        description="Too Many Requests",
        payload={"parameters": {"retry_after": 17}},
    )

    assert classify_telegram_error(exc) == "telegram_rate_limit"


def test_retry_after_uses_telegram_delay() -> None:
    settings = Settings(
        send_retry_max_attempts=3,
        send_retry_base_delay_seconds=1.0,
        send_retry_max_delay_seconds=60.0,
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=UTC)
    exc = TelegramBotApiError(
        method="sendMessage",
        error_code=429,
        description="Too Many Requests",
        payload={"parameters": {"retry_after": 17}},
    )

    decision = compute_retry_decision(settings=settings, error=exc, attempt_number=1, now=now)

    assert decision == RetryDecision(
        retry=True,
        terminal_status="deferred",
        error_kind="telegram_rate_limit",
        retry_after_seconds=17,
        next_retry_at=datetime(2026, 5, 3, 12, 0, 17, tzinfo=UTC),
    )


def test_exhausted_retry_budget_goes_dead_letter() -> None:
    settings = Settings(send_retry_max_attempts=2)
    now = datetime(2026, 5, 3, 12, 0, tzinfo=UTC)
    exc = TelegramBotApiError(
        method="sendMessage",
        error_code=502,
        description="Bad Gateway",
        payload={"ok": False},
    )

    decision = compute_retry_decision(settings=settings, error=exc, attempt_number=2, now=now)

    assert decision.retry is False
    assert decision.terminal_status == "dead_letter"
    assert decision.error_kind == "telegram_server"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_reliability.py -q
```

Expected: FAIL because `tg_bot_aggregator.reliability` and new settings fields do not exist.

- [ ] **Step 3: Add reliability settings**

Modify `src/tg_bot_aggregator/config.py`.

Import `Literal` already exists. Add fields to `Settings` after existing send retry fields:

```python
    reliability_enabled: bool = Field(default=False, validation_alias="RELIABILITY_ENABLED")
    send_default_mode: Literal["sync", "queued", "auto"] = Field(
        default="sync",
        validation_alias="SEND_DEFAULT_MODE",
    )
    send_global_rate_per_minute: int | None = Field(
        default=None,
        validation_alias="SEND_GLOBAL_RATE_PER_MINUTE",
    )
    send_bot_rate_per_minute: int | None = Field(
        default=None,
        validation_alias="SEND_BOT_RATE_PER_MINUTE",
    )
    send_chat_rate_per_minute: int | None = Field(
        default=None,
        validation_alias="SEND_CHAT_RATE_PER_MINUTE",
    )
    send_destination_rate_per_minute: int | None = Field(
        default=None,
        validation_alias="SEND_DESTINATION_RATE_PER_MINUTE",
    )
    send_retry_base_delay_seconds: float = Field(
        default=1.0,
        validation_alias="SEND_RETRY_BASE_DELAY_SECONDS",
    )
    send_retry_max_delay_seconds: float = Field(
        default=300.0,
        validation_alias="SEND_RETRY_MAX_DELAY_SECONDS",
    )
    send_worker_lease_seconds: int = Field(
        default=60,
        validation_alias="SEND_WORKER_LEASE_SECONDS",
    )
    send_stale_lock_grace_seconds: int = Field(
        default=30,
        validation_alias="SEND_STALE_LOCK_GRACE_SECONDS",
    )
    send_dedupe_window_seconds: int | None = Field(
        default=None,
        validation_alias="SEND_DEDUPE_WINDOW_SECONDS",
    )
```

Modify `src/tg_bot_aggregator/schemas.py`.

Add the same fields to `RuntimeSettingsUpdate` and `RuntimeSettingsRead` with matching types. Use `Field(default=None, ge=1)` for nullable positive integers and `Field(default=None, ge=0)` for nullable floats in update schemas where applicable.

Modify `src/tg_bot_aggregator/runtime_settings.py`.

Add these names to `SETTING_MODEL_FIELDS`:

```python
    "reliability_enabled",
    "send_default_mode",
    "send_global_rate_per_minute",
    "send_bot_rate_per_minute",
    "send_chat_rate_per_minute",
    "send_destination_rate_per_minute",
    "send_retry_base_delay_seconds",
    "send_retry_max_delay_seconds",
    "send_worker_lease_seconds",
    "send_stale_lock_grace_seconds",
    "send_dedupe_window_seconds",
```

Add these values to `runtime_settings_read(...)`:

```python
        reliability_enabled=effective.reliability_enabled,
        send_default_mode=effective.send_default_mode,
        send_global_rate_per_minute=effective.send_global_rate_per_minute,
        send_bot_rate_per_minute=effective.send_bot_rate_per_minute,
        send_chat_rate_per_minute=effective.send_chat_rate_per_minute,
        send_destination_rate_per_minute=effective.send_destination_rate_per_minute,
        send_retry_base_delay_seconds=effective.send_retry_base_delay_seconds,
        send_retry_max_delay_seconds=effective.send_retry_max_delay_seconds,
        send_worker_lease_seconds=effective.send_worker_lease_seconds,
        send_stale_lock_grace_seconds=effective.send_stale_lock_grace_seconds,
        send_dedupe_window_seconds=effective.send_dedupe_window_seconds,
```

Modify `RuntimeSettings` in `src/tg_bot_aggregator/models.py` and migration `0007_send_reliability_layer.py` to store these runtime fields as nullable columns on `runtime_settings`.

- [ ] **Step 4: Implement failure classification and retry decisions**

Create `src/tg_bot_aggregator/reliability.py` with:

```python
from dataclasses import dataclass
from datetime import datetime, timedelta

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiError


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    terminal_status: str
    error_kind: str
    retry_after_seconds: int | None
    next_retry_at: datetime | None


def _retry_after_from_payload(payload: dict | None) -> int | None:
    if not isinstance(payload, dict):
        return None
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict):
        return None
    retry_after = parameters.get("retry_after")
    if isinstance(retry_after, int) and retry_after > 0:
        return retry_after
    return None


def classify_telegram_error(error: TelegramBotApiError) -> str:
    if error.error_code == 429:
        return "telegram_rate_limit"
    if error.error_code is None:
        return "network"
    if 500 <= error.error_code <= 599:
        return "telegram_server"
    if 400 <= error.error_code <= 499:
        return "telegram_client"
    return "unknown"


def _bounded_backoff(settings: Settings, attempt_number: int) -> int:
    base = max(0.0, settings.send_retry_base_delay_seconds)
    cap = max(base, settings.send_retry_max_delay_seconds)
    delay = base * (2 ** max(0, attempt_number - 1))
    return int(min(cap, delay))


def compute_retry_decision(
    *,
    settings: Settings,
    error: TelegramBotApiError,
    attempt_number: int,
    now: datetime,
) -> RetryDecision:
    error_kind = classify_telegram_error(error)
    retryable = error_kind in {"telegram_rate_limit", "telegram_server", "network"}
    if not retryable:
        return RetryDecision(
            retry=False,
            terminal_status="blocked",
            error_kind=error_kind,
            retry_after_seconds=None,
            next_retry_at=None,
        )
    if attempt_number >= max(1, settings.send_retry_max_attempts):
        return RetryDecision(
            retry=False,
            terminal_status="dead_letter",
            error_kind=error_kind,
            retry_after_seconds=None,
            next_retry_at=None,
        )
    retry_after = _retry_after_from_payload(error.payload)
    delay = retry_after if retry_after is not None else _bounded_backoff(settings, attempt_number)
    return RetryDecision(
        retry=True,
        terminal_status="deferred",
        error_kind=error_kind,
        retry_after_seconds=delay,
        next_retry_at=now + timedelta(seconds=delay),
    )
```

- [ ] **Step 5: Run policy tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_reliability.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit policy layer**

```bash
git add src/tg_bot_aggregator/config.py src/tg_bot_aggregator/runtime_settings.py src/tg_bot_aggregator/schemas.py src/tg_bot_aggregator/reliability.py src/tg_bot_aggregator/models.py alembic/versions/0007_send_reliability_layer.py tests/test_reliability.py
git commit -m "feat: add reliability policy settings"
```

---

### Task 3: Redis Rate Buckets And Degraded Fallback

**Files:**
- Modify: `src/tg_bot_aggregator/reliability.py`
- Test: `tests/test_reliability.py`

- [ ] **Step 1: Add failing rate limiter tests**

Append to `tests/test_reliability.py`:

```python
from collections import defaultdict

from tg_bot_aggregator.reliability import MemoryRateLimitStore, SendRateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_blocks_when_bot_bucket_is_full() -> None:
    store = MemoryRateLimitStore()
    limiter = SendRateLimiter(
        store=store,
        global_limit_per_minute=None,
        bot_limit_per_minute=2,
        chat_limit_per_minute=None,
        destination_limit_per_minute=None,
    )

    first = await limiter.check_and_increment(bot_id=1, chat_id="@ops", destination_id=None)
    second = await limiter.check_and_increment(bot_id=1, chat_id="@ops", destination_id=None)
    third = await limiter.check_and_increment(bot_id=1, chat_id="@ops", destination_id=None)

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.bucket_key == "send:bot:1"
    assert third.retry_after_seconds is not None


@pytest.mark.asyncio
async def test_rate_limiter_reports_bucket_snapshots() -> None:
    store = MemoryRateLimitStore()
    limiter = SendRateLimiter(
        store=store,
        global_limit_per_minute=10,
        bot_limit_per_minute=2,
        chat_limit_per_minute=5,
        destination_limit_per_minute=4,
    )

    await limiter.check_and_increment(bot_id=7, chat_id="-1001", destination_id=3)
    snapshots = await limiter.snapshots(bot_id=7, chat_id="-1001", destination_id=3)

    by_key = {item.bucket_key: item for item in snapshots}
    assert by_key["send:global"].limit == 10
    assert by_key["send:bot:7"].used == 1
    assert by_key["send:chat:-1001"].used == 1
    assert by_key["send:destination:3"].used == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_reliability.py -q
```

Expected: FAIL because `MemoryRateLimitStore` and `SendRateLimiter` do not exist.

- [ ] **Step 3: Add rate bucket models and store protocol**

Modify `src/tg_bot_aggregator/reliability.py`.

Add:

```python
from collections import defaultdict
from typing import Protocol


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    bucket_key: str | None
    retry_after_seconds: int | None
    message: str | None


@dataclass(frozen=True)
class RateBucketSnapshot:
    bucket_key: str
    limit: int
    used: int
    retry_after_seconds: int | None


class RateLimitStore(Protocol):
    async def increment_window(self, key: str, window_seconds: int) -> int:
        ...

    async def get_count(self, key: str) -> int:
        ...

    async def retry_after(self, key: str) -> int | None:
        ...


class MemoryRateLimitStore:
    def __init__(self) -> None:
        self.counts: dict[str, int] = defaultdict(int)

    async def increment_window(self, key: str, window_seconds: int) -> int:
        self.counts[key] += 1
        return self.counts[key]

    async def get_count(self, key: str) -> int:
        return self.counts[key]

    async def retry_after(self, key: str) -> int | None:
        return 60
```

The protocol uses `...` because it is a Python protocol body, not an unresolved implementation.

- [ ] **Step 4: Add Redis-backed store**

Add:

```python
class RedisRateLimitStore:
    def __init__(self, redis_client) -> None:
        self.redis = redis_client

    async def increment_window(self, key: str, window_seconds: int) -> int:
        value = await self.redis.incr(key)
        if value == 1:
            await self.redis.expire(key, window_seconds)
        return int(value)

    async def get_count(self, key: str) -> int:
        value = await self.redis.get(key)
        return int(value or 0)

    async def retry_after(self, key: str) -> int | None:
        ttl = await self.redis.ttl(key)
        if ttl is None or int(ttl) < 0:
            return None
        return int(ttl)
```

- [ ] **Step 5: Add `SendRateLimiter`**

Add:

```python
class SendRateLimiter:
    def __init__(
        self,
        *,
        store: RateLimitStore,
        global_limit_per_minute: int | None,
        bot_limit_per_minute: int | None,
        chat_limit_per_minute: int | None,
        destination_limit_per_minute: int | None,
    ) -> None:
        self.store = store
        self.limits = {
            "send:global": global_limit_per_minute,
            "send:bot": bot_limit_per_minute,
            "send:chat": chat_limit_per_minute,
            "send:destination": destination_limit_per_minute,
        }

    def _bucket_limits(
        self,
        *,
        bot_id: int,
        chat_id: str,
        destination_id: int | None,
    ) -> list[tuple[str, int]]:
        buckets: list[tuple[str, int]] = []
        global_limit = self.limits["send:global"]
        bot_limit = self.limits["send:bot"]
        chat_limit = self.limits["send:chat"]
        destination_limit = self.limits["send:destination"]
        if global_limit is not None:
            buckets.append(("send:global", global_limit))
        if bot_limit is not None:
            buckets.append((f"send:bot:{bot_id}", bot_limit))
        if chat_limit is not None:
            buckets.append((f"send:chat:{chat_id}", chat_limit))
        if destination_limit is not None and destination_id is not None:
            buckets.append((f"send:destination:{destination_id}", destination_limit))
        return buckets

    async def check_and_increment(
        self,
        *,
        bot_id: int,
        chat_id: str,
        destination_id: int | None,
    ) -> RateLimitDecision:
        for key, limit in self._bucket_limits(
            bot_id=bot_id,
            chat_id=chat_id,
            destination_id=destination_id,
        ):
            current = await self.store.get_count(key)
            if current >= limit:
                return RateLimitDecision(
                    allowed=False,
                    bucket_key=key,
                    retry_after_seconds=await self.store.retry_after(key),
                    message=f"rate limit exceeded for {key}",
                )
        for key, _limit in self._bucket_limits(
            bot_id=bot_id,
            chat_id=chat_id,
            destination_id=destination_id,
        ):
            await self.store.increment_window(key, 60)
        return RateLimitDecision(
            allowed=True,
            bucket_key=None,
            retry_after_seconds=None,
            message=None,
        )

    async def snapshots(
        self,
        *,
        bot_id: int,
        chat_id: str,
        destination_id: int | None,
    ) -> list[RateBucketSnapshot]:
        rows: list[RateBucketSnapshot] = []
        for key, limit in self._bucket_limits(
            bot_id=bot_id,
            chat_id=chat_id,
            destination_id=destination_id,
        ):
            rows.append(
                RateBucketSnapshot(
                    bucket_key=key,
                    limit=limit,
                    used=await self.store.get_count(key),
                    retry_after_seconds=await self.store.retry_after(key),
                )
            )
        return rows
```

- [ ] **Step 6: Run rate limiter tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_reliability.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit rate buckets**

```bash
git add src/tg_bot_aggregator/reliability.py tests/test_reliability.py
git commit -m "feat: add send rate buckets"
```

---

### Task 4: Lease-Based Queued Processing And Attempt Recording

**Files:**
- Modify: `src/tg_bot_aggregator/reliability.py`
- Modify: `src/tg_bot_aggregator/send_service.py`
- Modify: `src/tg_bot_aggregator/tasks.py`
- Test: `tests/test_send_service.py`
- Test: `tests/test_tasks.py`

- [ ] **Step 1: Add failing send processing tests**

Append to `tests/test_send_service.py`:

```python
from tg_bot_aggregator.reliability import SendQueueService


@pytest.mark.asyncio
async def test_queued_send_rate_limit_error_is_deferred_with_attempt(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    client = _bot_api_client(
        {},
        error=TelegramBotApiError(
            method="sendMessage",
            error_code=429,
            description="Too Many Requests",
            payload={"parameters": {"retry_after": 9}},
        ),
    )
    settings = Settings(
        reliability_enabled=True,
        send_retry_max_attempts=3,
        send_worker_lease_seconds=60,
    )
    service = SendService(db_session, client, settings)
    row = await service.send_text(bot.id, "hello", chat_id="@ops", send_mode="queued")

    processed = await service.process_queued_send(row.id, worker_id="worker-a")
    attempts = await SendAttemptRepository(db_session).list_for_send(row.id)

    assert processed.status == "deferred"
    assert processed.retry_after_seconds == 9
    assert processed.next_retry_at is not None
    assert processed.locked_by is None
    assert attempts[0].status == "deferred"
    assert attempts[0].error_kind == "telegram_rate_limit"


@pytest.mark.asyncio
async def test_exhausted_retry_budget_moves_to_dead_letter(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    client = _bot_api_client(
        {},
        error=TelegramBotApiError(
            method="sendMessage",
            error_code=502,
            description="Bad Gateway",
            payload={"ok": False},
        ),
    )
    service = SendService(
        db_session,
        client,
        Settings(reliability_enabled=True, send_retry_max_attempts=1),
    )
    row = await service.send_text(bot.id, "hello", chat_id="@ops", send_mode="queued")

    processed = await service.process_queued_send(row.id, worker_id="worker-a")

    assert processed.status == "dead_letter"
    assert processed.last_error_kind == "telegram_server"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_send_service.py -q
```

Expected: FAIL because `process_queued_send` has no `worker_id` argument and still sleeps/retries in a loop.

- [ ] **Step 3: Add attempt recording helpers**

Modify `src/tg_bot_aggregator/reliability.py`.

Add:

```python
from time import monotonic
from typing import Any

from tg_bot_aggregator.models import SendHistory, utc_now
from tg_bot_aggregator.repositories import SendAttemptRepository, SendHistoryRepository
from tg_bot_aggregator.security import redact_secrets


def latency_ms_since(start: float) -> int:
    return int((monotonic() - start) * 1000)


class SendQueueService:
    def __init__(self, history: SendHistoryRepository, attempts: SendAttemptRepository) -> None:
        self.history = history
        self.attempts = attempts

    async def acquire_lease(
        self,
        row: SendHistory,
        worker_id: str,
        lease_seconds: int,
    ) -> SendHistory | None:
        return await self.history.acquire_due_lease(
            row_id=row.id,
            worker_id=worker_id,
            now=utc_now(),
            lease_seconds=lease_seconds,
        )

    async def record_attempt(
        self,
        *,
        row: SendHistory,
        worker_id: str,
        started_at,
        finished_at,
        status: str,
        telegram_error_code: str | None,
        error_kind: str | None,
        error_message: str | None,
        retry_after_seconds: int | None,
        latency_ms: int | None,
        response_payload: dict[str, Any] | None,
    ) -> None:
        await self.attempts.create(
            send_history_id=row.id,
            attempt_number=row.attempt_count,
            worker_id=worker_id,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            telegram_error_code=telegram_error_code,
            error_kind=error_kind,
            error_message=error_message,
            retry_after_seconds=retry_after_seconds,
            latency_ms=latency_ms,
            response_payload_json=redact_secrets(response_payload),
        )
```

- [ ] **Step 4: Update queued processing**

Modify `src/tg_bot_aggregator/send_service.py`.

Import:

```python
from time import monotonic

from tg_bot_aggregator.reliability import (
    SendQueueService,
    SendRateLimiter,
    compute_retry_decision,
    latency_ms_since,
)
```

In `__init__`, add:

```python
        self.rate_limiter = rate_limiter
        self.attempts = SendAttemptRepository(session)
        self.queue = SendQueueService(self.history, self.attempts)
```

Change the constructor signature to accept the optional limiter:

```python
        rate_limiter: SendRateLimiter | None = None,
```

Change signature:

```python
    async def process_queued_send(
        self,
        send_history_id: int,
        worker_id: str = "worker",
    ) -> SendHistory:
```

Replace the retry loop inside `process_queued_send` with this flow:

```python
        if row.status in {"succeeded", "cancelled", "dead_letter", "blocked"}:
            return row
        if self._is_future_send(row.next_retry_at):
            return row
        leased = await self.queue.acquire_lease(
            row,
            worker_id=worker_id,
            lease_seconds=self.settings.send_worker_lease_seconds,
        )
        if leased is None:
            return row
        row = leased
        token = await self._bot_token(row.bot_id)
        attempt = row.attempt_count + 1
        await self.history.mark_sending(row, attempt)
        row.last_attempt_at = utc_now()
        await self.session.commit()
        await self.events.publish("send.locked", {"send_history_id": row.id, "worker_id": worker_id})
        if self.settings.reliability_enabled and self.rate_limiter is not None:
            rate_decision = await self.rate_limiter.check_and_increment(
                bot_id=row.bot_id,
                chat_id=row.chat_id,
                destination_id=row.destination_id,
            )
            if not rate_decision.allowed:
                next_retry_at = utc_now() + timedelta(seconds=rate_decision.retry_after_seconds or 60)
                await self.history.mark_deferred(
                    row,
                    "rate_limit",
                    rate_decision.message or "rate limit exceeded",
                    "policy",
                    next_retry_at,
                    rate_decision.retry_after_seconds or 60,
                    None,
                )
                await self.session.commit()
                await self.events.publish(
                    "send.deferred",
                    {"send_history_id": row.id, "next_retry_at": row.next_retry_at.isoformat()},
                )
                return row
        started_at = utc_now()
        started_timer = monotonic()
        try:
            response = await self._execute_row_once(token, row)
        except TelegramBotApiError as exc:
            decision = compute_retry_decision(
                settings=self.settings,
                error=exc,
                attempt_number=attempt,
                now=utc_now(),
            )
            finished_at = utc_now()
            await self.queue.record_attempt(
                row=row,
                worker_id=worker_id,
                started_at=started_at,
                finished_at=finished_at,
                status=decision.terminal_status,
                telegram_error_code=str(exc.error_code) if exc.error_code is not None else None,
                error_kind=decision.error_kind,
                error_message=exc.description,
                retry_after_seconds=decision.retry_after_seconds,
                latency_ms=latency_ms_since(started_timer),
                response_payload=exc.payload,
            )
            if decision.retry and decision.next_retry_at is not None:
                await self.history.mark_deferred(
                    row,
                    str(exc.error_code) if exc.error_code is not None else None,
                    exc.description,
                    decision.error_kind,
                    decision.next_retry_at,
                    decision.retry_after_seconds,
                    redact_secrets(exc.payload),
                )
                await self.session.commit()
                await self.events.publish(
                    "send.deferred",
                    {"send_history_id": row.id, "next_retry_at": row.next_retry_at.isoformat()},
                )
                return row
            if decision.terminal_status == "blocked":
                await self.history.mark_blocked(
                    row,
                    str(exc.error_code) if exc.error_code is not None else None,
                    exc.description,
                    decision.error_kind,
                )
                await self.session.commit()
                await self.events.publish("send.blocked", {"send_history_id": row.id})
                await self._publish_terminal_callback("send.blocked", row)
                return row
            await self.history.mark_dead_letter(
                row,
                str(exc.error_code) if exc.error_code is not None else None,
                exc.description,
                decision.error_kind,
                redact_secrets(exc.payload),
            )
            await self.session.commit()
            await self.events.publish("send.dead_letter", {"send_history_id": row.id})
            await self._publish_terminal_callback("send.dead_letter", row)
            return row
        finished_at = utc_now()
        await self.queue.record_attempt(
            row=row,
            worker_id=worker_id,
            started_at=started_at,
            finished_at=finished_at,
            status="succeeded",
            telegram_error_code=None,
            error_kind=None,
            error_message=None,
            retry_after_seconds=None,
            latency_ms=latency_ms_since(started_timer),
            response_payload=response,
        )
        return await self._mark_success_from_response(row, response)
```

Update `_mark_success_from_response` to clear lease fields before flush:

```python
        row.locked_at = None
        row.locked_by = None
        row.lock_expires_at = None
```

- [ ] **Step 5: Update retry and cancel state support**

Modify `retry_history` so `failed`, `dead_letter`, and `blocked` can be retried:

```python
        if row.status not in {"failed", "dead_letter", "blocked"}:
            raise SendServiceError("only failed, dead-letter, or blocked send history rows can be retried")
        row.status = "queued"
        row.error_code = None
        row.error_message = None
        row.last_error_kind = None
        row.failed_at = None
        row.queued_task_id = None
        row.next_retry_at = None
        row.retry_after_seconds = None
        row.locked_at = None
        row.locked_by = None
        row.lock_expires_at = None
        await self.session.commit()
        await self.events.publish("send.retry_scheduled", {"send_history_id": row.id})
        return row
```

Modify `cancel_history` accepted states:

```python
        if row.status not in {"created", "queued", "deferred"}:
            raise SendServiceError("only created, queued, or deferred send history rows can be cancelled")
```

- [ ] **Step 6: Update tasks due processing**

Modify `src/tg_bot_aggregator/tasks.py`.

Import Redis and rate limiter helpers:

```python
import redis.asyncio as redis

from tg_bot_aggregator.reliability import RedisRateLimitStore, SendRateLimiter
```

Build the limiter inside `run_send_history` and `run_due_send_history`:

```python
            redis_client = redis.from_url(settings.redis_url)
            rate_limiter = SendRateLimiter(
                store=RedisRateLimitStore(redis_client),
                global_limit_per_minute=settings.send_global_rate_per_minute,
                bot_limit_per_minute=settings.send_bot_rate_per_minute,
                chat_limit_per_minute=settings.send_chat_rate_per_minute,
                destination_limit_per_minute=settings.send_destination_rate_per_minute,
            )
```

In `run_send_history`, call:

```python
            service = SendService(
                session,
                TelegramBotApiClient(settings.telegram_bot_api_base_url),
                settings,
                events,
                rate_limiter=rate_limiter,
            )
            row = await service.process_queued_send(send_history_id, worker_id="taskiq-send-history")
```

In `run_due_send_history`, replace `list_due` with `list_ready_for_lease`:

```python
            service = SendService(
                session,
                TelegramBotApiClient(settings.telegram_bot_api_base_url),
                settings,
                events,
                rate_limiter=rate_limiter,
            )
            due_rows = await SendHistoryRepository(session).list_ready_for_lease(utc_now(), limit=limit)
            processed: list[int] = []
            for row in due_rows:
                processed.append(
                    (await service.process_queued_send(row.id, worker_id="taskiq-due-send-history")).id
                )
            return processed
```

- [ ] **Step 7: Run focused send tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_send_service.py tests/test_tasks.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit queued reliability execution**

```bash
git add src/tg_bot_aggregator/reliability.py src/tg_bot_aggregator/send_service.py src/tg_bot_aggregator/tasks.py tests/test_send_service.py tests/test_tasks.py
git commit -m "feat: process sends with leases and backoff"
```

---

### Task 5: Reliability REST API, Summaries, Buckets, Bulk Actions, And SSE

**Files:**
- Create: `src/tg_bot_aggregator/api/reliability.py`
- Modify: `src/tg_bot_aggregator/reliability.py`
- Modify: `src/tg_bot_aggregator/schemas.py`
- Modify: `src/tg_bot_aggregator/main.py`
- Test: `tests/test_api_reliability.py`

- [ ] **Step 1: Add failing API tests**

Create `tests/test_api_reliability.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from tg_bot_aggregator.main import create_app
from tg_bot_aggregator.models import utc_now
from tg_bot_aggregator.repositories import BotRepository, SendHistoryRepository


@pytest.mark.asyncio
async def test_reliability_summary_reports_status_counts(session_factory) -> None:
    async with session_factory() as session:
        bot = await BotRepository(session).create(name="ops", token="123:abc")
        history = SendHistoryRepository(session)
        await history.create(bot_id=bot.id, chat_id="@ops", media_type="none", status="queued")
        await history.create(bot_id=bot.id, chat_id="@ops", media_type="none", status="deferred")
        await history.create(bot_id=bot.id, chat_id="@ops", media_type="none", status="dead_letter")
        await session.commit()

    app = create_app(session_factory=session_factory)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/v1/reliability/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["status_counts"]["queued"] == 1
    assert data["status_counts"]["deferred"] == 1
    assert data["status_counts"]["dead_letter"] == 1


@pytest.mark.asyncio
async def test_release_stale_locks_returns_count(session_factory) -> None:
    async with session_factory() as session:
        bot = await BotRepository(session).create(name="ops", token="123:abc")
        history = SendHistoryRepository(session)
        row = await history.create(bot_id=bot.id, chat_id="@ops", media_type="none", status="queued")
        leased = await history.acquire_due_lease(row.id, "worker-a", utc_now(), lease_seconds=1)
        assert leased is not None
        leased.lock_expires_at = utc_now()
        await session.commit()

    app = create_app(session_factory=session_factory)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/api/v1/reliability/stale-locks/release")

    assert response.status_code == 200
    assert response.json()["released"] == 1


@pytest.mark.asyncio
async def test_reliability_graph_and_buckets_are_exposed(session_factory) -> None:
    app = create_app(session_factory=session_factory)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        graph = await client.get("/api/v1/reliability/graph")
        buckets = await client.get("/api/v1/reliability/buckets?bot_id=1&chat_id=@ops")

    assert graph.status_code == 200
    assert "nodes" in graph.json()
    assert buckets.status_code == 200
    assert isinstance(buckets.json(), list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api_reliability.py -q
```

Expected: FAIL with 404 for reliability routes.

- [ ] **Step 3: Add schemas**

Modify `src/tg_bot_aggregator/schemas.py`:

```python
class ReliabilitySummaryRead(BaseModel):
    status_counts: dict[str, int]
    stale_locks: int
    degraded: bool = False


class ReliabilityGraphNode(BaseModel):
    id: str
    label: str
    status: str
    count: int


class ReliabilityGraphEdge(BaseModel):
    source: str
    target: str
    status: str
    active: bool


class ReliabilityGraphRead(BaseModel):
    nodes: list[ReliabilityGraphNode]
    edges: list[ReliabilityGraphEdge]


class RateBucketRead(BaseModel):
    bucket_key: str
    limit: int
    used: int
    retry_after_seconds: int | None


class SendAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    send_history_id: int
    attempt_number: int
    worker_id: str | None
    started_at: datetime
    finished_at: datetime | None
    status: str
    telegram_error_code: str | None
    error_kind: str | None
    error_message: str | None
    retry_after_seconds: int | None
    latency_ms: int | None
    response_payload_json: dict[str, Any] | None


class BulkSendHistoryRequest(BaseModel):
    send_history_ids: list[int] = Field(min_length=1)


class BulkSendHistoryResult(BaseModel):
    changed: int
    skipped: int
```

- [ ] **Step 4: Add summary and graph builders**

Modify `src/tg_bot_aggregator/reliability.py`.

Add:

```python
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.models import SendHistory


class ReliabilityReadService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.history = SendHistoryRepository(session)
        self.attempts = SendAttemptRepository(session)

    async def summary(self) -> dict[str, Any]:
        statement = select(SendHistory.status, func.count()).group_by(SendHistory.status)
        rows = (await self.session.execute(statement)).all()
        stale = await self.history.list_stale_locks(utc_now(), limit=1000)
        return {
            "status_counts": {str(status): int(count) for status, count in rows},
            "stale_locks": len(stale),
            "degraded": False,
        }

    async def graph(self) -> dict[str, Any]:
        summary = await self.summary()
        counts = summary["status_counts"]
        nodes = [
            {"id": "source", "label": "Batch / Manual", "status": "ok", "count": counts.get("created", 0)},
            {"id": "queue", "label": "Queue", "status": "ok", "count": counts.get("queued", 0)},
            {"id": "policy", "label": "Policy gate", "status": "warning", "count": counts.get("deferred", 0)},
            {"id": "worker", "label": "Worker lease", "status": "ok", "count": counts.get("sending", 0)},
            {"id": "bot", "label": "Bot bucket", "status": "ok", "count": 0},
            {"id": "chat", "label": "Chat bucket", "status": "ok", "count": 0},
            {"id": "telegram", "label": "Telegram", "status": "ok", "count": counts.get("succeeded", 0)},
            {"id": "result", "label": "Result", "status": "danger", "count": counts.get("dead_letter", 0) + counts.get("blocked", 0)},
        ]
        edges = [
            {"source": "source", "target": "queue", "status": "ok", "active": counts.get("queued", 0) > 0},
            {"source": "queue", "target": "policy", "status": "warning", "active": counts.get("deferred", 0) > 0},
            {"source": "policy", "target": "worker", "status": "ok", "active": counts.get("sending", 0) > 0},
            {"source": "worker", "target": "bot", "status": "ok", "active": counts.get("sending", 0) > 0},
            {"source": "bot", "target": "chat", "status": "ok", "active": counts.get("sending", 0) > 0},
            {"source": "chat", "target": "telegram", "status": "ok", "active": counts.get("succeeded", 0) > 0},
            {"source": "telegram", "target": "result", "status": "danger", "active": counts.get("dead_letter", 0) + counts.get("blocked", 0) > 0},
        ]
        return {"nodes": nodes, "edges": edges}
```

- [ ] **Step 5: Add REST router**

Create `src/tg_bot_aggregator/api/reliability.py`:

```python
import redis.asyncio as redis
from fastapi import APIRouter, Depends, Request
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.db import get_session
from tg_bot_aggregator.models import utc_now
from tg_bot_aggregator.reliability import (
    MemoryRateLimitStore,
    RedisRateLimitStore,
    ReliabilityReadService,
    SendRateLimiter,
)
from tg_bot_aggregator.repositories import SendAttemptRepository, SendHistoryRepository
from tg_bot_aggregator.schemas import (
    BulkSendHistoryRequest,
    BulkSendHistoryResult,
    RateBucketRead,
    ReliabilityGraphRead,
    ReliabilitySummaryRead,
    SendAttemptRead,
)

router = APIRouter(prefix="/reliability", tags=["reliability"])


@router.get("/summary", response_model=ReliabilitySummaryRead)
async def reliability_summary(session: AsyncSession = Depends(get_session)) -> dict:
    return await ReliabilityReadService(session).summary()


@router.get("/graph", response_model=ReliabilityGraphRead)
async def reliability_graph(session: AsyncSession = Depends(get_session)) -> dict:
    return await ReliabilityReadService(session).graph()


@router.get("/attempts", response_model=list[SendAttemptRead])
async def list_attempts(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await SendAttemptRepository(session).list()


@router.get("/buckets", response_model=list[RateBucketRead])
async def list_buckets(
    request: Request,
    bot_id: int = 0,
    chat_id: str = "*",
    destination_id: int | None = None,
) -> list[object]:
    settings = request.app.state.settings
    redis_client = redis.from_url(settings.redis_url)
    limiter = SendRateLimiter(
        store=RedisRateLimitStore(redis_client),
        global_limit_per_minute=settings.send_global_rate_per_minute,
        bot_limit_per_minute=settings.send_bot_rate_per_minute,
        chat_limit_per_minute=settings.send_chat_rate_per_minute,
        destination_limit_per_minute=settings.send_destination_rate_per_minute,
    )
    try:
        return await limiter.snapshots(
            bot_id=bot_id,
            chat_id=chat_id,
            destination_id=destination_id,
        )
    except RedisError:
        degraded_limiter = SendRateLimiter(
            store=MemoryRateLimitStore(),
            global_limit_per_minute=settings.send_global_rate_per_minute,
            bot_limit_per_minute=settings.send_bot_rate_per_minute,
            chat_limit_per_minute=settings.send_chat_rate_per_minute,
            destination_limit_per_minute=settings.send_destination_rate_per_minute,
        )
        return await degraded_limiter.snapshots(
            bot_id=bot_id,
            chat_id=chat_id,
            destination_id=destination_id,
        )


@router.get("/stale-locks")
async def stale_locks(session: AsyncSession = Depends(get_session)) -> dict[str, int]:
    rows = await SendHistoryRepository(session).list_stale_locks(utc_now())
    return {"count": len(rows)}


@router.post("/stale-locks/release")
async def release_stale_locks(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    released = await SendHistoryRepository(session).release_stale_locks(utc_now())
    await session.commit()
    await request.app.state.event_bus.publish("send.released", {"released": released})
    return {"released": released}


@router.post("/send-history/bulk-retry", response_model=BulkSendHistoryResult)
async def bulk_retry_sends(
    payload: BulkSendHistoryRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BulkSendHistoryResult:
    changed = 0
    skipped = 0
    from tg_bot_aggregator.send_service import SendService

    sender = SendService(session, request.app.state.bot_api_client, request.app.state.settings, request.app.state.event_bus)
    for row_id in payload.send_history_ids:
        try:
            await sender.retry_history(row_id)
            changed += 1
        except ValueError:
            skipped += 1
    return BulkSendHistoryResult(changed=changed, skipped=skipped)


@router.post("/send-history/bulk-cancel", response_model=BulkSendHistoryResult)
async def bulk_cancel_sends(
    payload: BulkSendHistoryRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BulkSendHistoryResult:
    changed = 0
    skipped = 0
    from tg_bot_aggregator.send_service import SendService

    sender = SendService(session, request.app.state.bot_api_client, request.app.state.settings, request.app.state.event_bus)
    for row_id in payload.send_history_ids:
        try:
            await sender.cancel_history(row_id)
            changed += 1
        except ValueError:
            skipped += 1
    return BulkSendHistoryResult(changed=changed, skipped=skipped)
```

- [ ] **Step 6: Register router**

Modify `src/tg_bot_aggregator/main.py`:

```python
from tg_bot_aggregator.api import reliability
```

and include:

```python
    app.include_router(reliability.router, prefix=prefix)
```

- [ ] **Step 7: Run API tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api_reliability.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit REST reliability API**

```bash
git add src/tg_bot_aggregator/api/reliability.py src/tg_bot_aggregator/reliability.py src/tg_bot_aggregator/schemas.py src/tg_bot_aggregator/main.py tests/test_api_reliability.py
git commit -m "feat: expose send reliability api"
```

---

### Task 6: MCP Reliability Tools

**Files:**
- Modify: `src/tg_bot_aggregator/mcp_catalog.py`
- Modify: `src/tg_bot_aggregator/mcp_server.py`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Add failing MCP tests**

Append to `tests/test_mcp_server.py`:

```python
def test_mcp_catalog_contains_reliability_tools() -> None:
    from tg_bot_aggregator.mcp_catalog import MCP_TOOL_NAMES

    assert "get_reliability_summary" in MCP_TOOL_NAMES
    assert "get_reliability_graph" in MCP_TOOL_NAMES
    assert "list_send_attempts" in MCP_TOOL_NAMES
    assert "list_rate_limit_buckets" in MCP_TOOL_NAMES
    assert "release_stale_send_locks" in MCP_TOOL_NAMES
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_mcp_server.py::test_mcp_catalog_contains_reliability_tools -q
```

Expected: FAIL because tools are not registered.

- [ ] **Step 3: Register MCP tool metadata**

Modify `src/tg_bot_aggregator/mcp_catalog.py` and add:

```python
    McpToolDefinition("get_reliability_summary", "Get reliability summary", "read", "read"),
    McpToolDefinition("get_reliability_graph", "Get reliability graph", "read", "read"),
    McpToolDefinition("list_send_attempts", "List send attempts", "read", "read"),
    McpToolDefinition("list_rate_limit_buckets", "List rate limit buckets", "read", "read"),
    McpToolDefinition("release_stale_send_locks", "Release stale send locks", "task", "write"),
    McpToolDefinition("bulk_retry_sends", "Bulk retry sends", "send", "write"),
    McpToolDefinition("bulk_cancel_sends", "Bulk cancel sends", "send", "write"),
```

- [ ] **Step 4: Add MCP tool implementations**

Modify `src/tg_bot_aggregator/mcp_server.py`.

Import:

```python
from tg_bot_aggregator.models import utc_now
from tg_bot_aggregator.reliability import MemoryRateLimitStore, ReliabilityReadService, SendRateLimiter
```

Add tools inside `create_mcp_server`:

```python
    @mcp.tool()
    async def get_reliability_summary() -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "get_reliability_summary")
        async with get_session_factory()() as session:
            return await ReliabilityReadService(session).summary()

    @mcp.tool()
    async def get_reliability_graph() -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "get_reliability_graph")
        async with get_session_factory()() as session:
            return await ReliabilityReadService(session).graph()

    @mcp.tool()
    async def list_send_attempts(limit: int = 100) -> list[dict[str, Any]]:
        await ensure_mcp_tool_enabled(get_session_factory(), "list_send_attempts")
        async with get_session_factory()() as session:
            attempts = await SendAttemptRepository(session).list(limit=limit)
            return [
                {
                    "id": item.id,
                    "send_history_id": item.send_history_id,
                    "attempt_number": item.attempt_number,
                    "status": item.status,
                    "error_kind": item.error_kind,
                    "retry_after_seconds": item.retry_after_seconds,
                    "latency_ms": item.latency_ms,
                }
                for item in attempts
            ]

    @mcp.tool()
    async def list_rate_limit_buckets(
        bot_id: int = 0,
        chat_id: str = "*",
        destination_id: int | None = None,
    ) -> list[dict[str, Any]]:
        await ensure_mcp_tool_enabled(get_session_factory(), "list_rate_limit_buckets")
        limiter = SendRateLimiter(
            store=MemoryRateLimitStore(),
            global_limit_per_minute=settings.send_global_rate_per_minute,
            bot_limit_per_minute=settings.send_bot_rate_per_minute,
            chat_limit_per_minute=settings.send_chat_rate_per_minute,
            destination_limit_per_minute=settings.send_destination_rate_per_minute,
        )
        snapshots = await limiter.snapshots(
            bot_id=bot_id,
            chat_id=chat_id,
            destination_id=destination_id,
        )
        return [
            {
                "bucket_key": item.bucket_key,
                "limit": item.limit,
                "used": item.used,
                "retry_after_seconds": item.retry_after_seconds,
            }
            for item in snapshots
        ]

    @mcp.tool()
    async def release_stale_send_locks() -> dict[str, int]:
        await ensure_mcp_tool_enabled(get_session_factory(), "release_stale_send_locks")
        async with get_session_factory()() as session:
            released = await SendHistoryRepository(session).release_stale_locks(utc_now())
            await session.commit()
            return {"released": released}
```

Add `SendAttemptRepository` to the repository imports.

- [ ] **Step 5: Run MCP tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_mcp_server.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit MCP tools**

```bash
git add src/tg_bot_aggregator/mcp_catalog.py src/tg_bot_aggregator/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: add reliability mcp tools"
```

---

### Task 7: Dashboard Reliability Graph Without Losing Existing Controls

**Files:**
- Modify: `src/tg_bot_aggregator/static/index.html`
- Test: `tests/test_static_ui.py`

- [ ] **Step 1: Add failing static UI regression tests**

Append to `tests/test_static_ui.py`:

```python
def test_static_ui_exposes_reliability_graph_and_preserves_existing_tabs() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert '{ id: "reliability", label: "Надежность", icon: "activity"' in html
    assert "reliabilityGraph" in html
    assert "reliabilitySummary" in html
    assert "reliabilityNode" in html
    assert "Batch / Manual" in html
    assert "Policy gate" in html
    assert "Worker lease" in html
    assert "Bot bucket" in html
    assert "Chat bucket" in html
    assert "Telegram" in html
    assert "Result" in html
    assert "@keyframes edgeFlow" in html

    for tab in [
        "Боты",
        "Адресаты",
        "Шаблоны",
        "Отправка",
        "История",
        "MTProto",
        "Аналитика",
        "Диагностика",
        "Автопоиск",
        "MCP",
        "Аудит",
        "Операции",
        "Состояние",
    ]:
        assert tab in html


def test_static_ui_reliability_calls_new_api_and_keeps_history_actions() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert 'this.api("/reliability/summary"' in html
    assert 'this.api("/reliability/graph"' in html
    assert 'this.api("/reliability/attempts"' in html
    assert 'this.api("/reliability/stale-locks/release"' in html
    assert "retrySendHistory" in html
    assert "cancelSendHistory" in html
    assert "deadLetter" in html
    assert "dueHistory" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_static_ui.py -q
```

Expected: FAIL because the `Надежность` tab and graph bindings do not exist.

- [ ] **Step 3: Add reliability tab and state**

Modify the `tabs` array in `src/tg_bot_aggregator/static/index.html`:

```javascript
{ id: "reliability", label: "Надежность", icon: "activity", description: "Живой граф очередей, rate limit, worker locks и результата отправки." },
```

Add Vue state:

```javascript
reliabilitySummary: { status_counts: {}, stale_locks: 0, degraded: false },
reliabilityGraph: { nodes: [], edges: [] },
reliabilityAttempts: [],
selectedReliabilityNode: "queue",
```

Add methods:

```javascript
async refreshReliability() {
  const [summary, graph, attempts] = await Promise.all([
    this.api("/reliability/summary"),
    this.api("/reliability/graph"),
    this.api("/reliability/attempts"),
  ]);
  this.reliabilitySummary = summary;
  this.reliabilityGraph = graph;
  this.reliabilityAttempts = attempts;
},
selectReliabilityNode(id) {
  this.selectedReliabilityNode = id;
},
async releaseStaleLocks() {
  await this.api("/reliability/stale-locks/release", { method: "POST" });
  await this.refreshAll();
},
reliabilityNode(id) {
  return this.reliabilityGraph.nodes.find((node) => node.id === id) || { id, label: id, status: "ok", count: 0 };
},
```

Call `this.api("/reliability/summary")`, `this.api("/reliability/graph")`, and `this.api("/reliability/attempts")` in `refreshAll`.

- [ ] **Step 4: Add graph markup**

Add an `activeTab === 'reliability'` section:

```html
<section v-if="activeTab === 'reliability'" class="stack-layout">
  <div class="panel full-span">
    <h3 class="panel-title">Живой граф отправки</h3>
    <p class="panel-description">Показывает путь сообщений через очередь, policy gate, worker lock, rate buckets и Telegram.</p>
    <div class="reliability-graph">
      <button
        v-for="node in reliabilityGraph.nodes"
        :key="node.id"
        class="graph-node"
        :class="[node.status, { selected: selectedReliabilityNode === node.id }]"
        @click="selectReliabilityNode(node.id)"
      >
        <span>{{ node.label }}</span>
        <strong>{{ node.count }}</strong>
      </button>
      <div
        v-for="edge in reliabilityGraph.edges"
        :key="`${edge.source}-${edge.target}`"
        class="graph-edge"
        :class="[edge.status, { active: edge.active }]"
      ></div>
    </div>
  </div>
  <div class="grid">
    <div class="panel">
      <h3 class="panel-title">Сводка</h3>
      <p class="panel-description">Статусы очереди и stale locks.</p>
      <div class="health-grid">
        <div class="health-card" v-for="(count, status) in reliabilitySummary.status_counts" :key="status">
          <p class="health-card-title">{{ statusLabel(status) }}</p>
          <span class="badge">{{ count }}</span>
        </div>
        <div class="health-card">
          <p class="health-card-title">Stale locks</p>
          <span class="badge" :class="{ danger: reliabilitySummary.stale_locks > 0 }">{{ reliabilitySummary.stale_locks }}</span>
        </div>
      </div>
      <button class="btn" @click="releaseStaleLocks"><i data-lucide="unlock"></i> Release stale locks</button>
    </div>
    <div class="panel">
      <h3 class="panel-title">Попытки</h3>
      <p class="panel-description">Append-only журнал попыток выбранных отправок.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>Send</th><th>Попытка</th><th>Статус</th><th>Ошибка</th><th>Latency</th></tr></thead>
          <tbody>
            <tr v-for="attempt in reliabilityAttempts" :key="attempt.id">
              <td>{{ attempt.id }}</td>
              <td>{{ attempt.send_history_id }}</td>
              <td>{{ attempt.attempt_number }}</td>
              <td>{{ statusLabel(attempt.status) }}</td>
              <td>{{ attempt.error_kind || '-' }}</td>
              <td>{{ attempt.latency_ms ?? '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</section>
```

- [ ] **Step 5: Add OneDark graph CSS**

Add CSS:

```css
.reliability-graph {
  position: relative;
  display: grid;
  grid-template-columns: repeat(8, minmax(92px, 1fr));
  gap: 14px;
  align-items: center;
  min-height: 180px;
  overflow-x: auto;
}
.graph-node {
  min-height: 86px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel-strong);
  color: var(--text);
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 8px;
}
.graph-node strong {
  color: var(--accent);
  font-size: 24px;
}
.graph-node.warning {
  border-color: var(--warning);
}
.graph-node.danger {
  border-color: var(--danger);
}
.graph-node.selected {
  box-shadow: 0 0 0 2px var(--accent);
}
.graph-edge {
  height: 2px;
  background: var(--border);
}
.graph-edge.active {
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  background-size: 120px 2px;
  animation: edgeFlow 1.2s linear infinite;
}
.graph-edge.warning.active {
  background-image: linear-gradient(90deg, transparent, var(--warning), transparent);
}
.graph-edge.danger.active {
  background-image: linear-gradient(90deg, transparent, var(--danger), transparent);
}
@keyframes edgeFlow {
  from { background-position: 0 0; }
  to { background-position: 120px 0; }
}
```

- [ ] **Step 6: Wire SSE refresh**

Extend the event list in `connectEvents` to include:

```javascript
"send.deferred",
"send.dead_letter",
"send.blocked",
"send.locked",
"send.released",
"send.retry_scheduled",
"reliability.bucket.updated",
"reliability.graph.updated",
```

Inside the event handler, call `this.refreshReliability()` for these event names.

- [ ] **Step 7: Run static UI tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_static_ui.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit dashboard graph**

```bash
git add src/tg_bot_aggregator/static/index.html tests/test_static_ui.py
git commit -m "feat: add send reliability dashboard"
```

---

### Task 8: Documentation, Full Verification, And Browser Check

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [ ] **Step 1: Document reliability settings and behavior**

Add to `README.md` after `Sending Conveniences`:

```markdown
## Send Reliability

The `Надежность` dashboard tab shows a live flow graph for Telegram sends:

```text
Batch / Manual -> Queue -> Policy gate -> Worker lease -> Bot bucket -> Chat bucket -> Telegram -> Result
```

Queued sends use worker leases so two workers do not process the same send row at the same time. Retryable Telegram failures are deferred with `next_retry_at`; exhausted sends move to `dead_letter`; non-retryable operational problems move to `blocked`.

Reliability endpoints:

```text
GET /api/v1/reliability/summary
GET /api/v1/reliability/graph
GET /api/v1/reliability/attempts
GET /api/v1/reliability/stale-locks
POST /api/v1/reliability/stale-locks/release
POST /api/v1/reliability/send-history/bulk-retry
POST /api/v1/reliability/send-history/bulk-cancel
```

Runtime settings include `RELIABILITY_ENABLED`, `SEND_DEFAULT_MODE`, rate limits, retry backoff, worker lease duration, and stale lock grace.
```

- [ ] **Step 2: Add `.env.example` settings**

Add:

```text
RELIABILITY_ENABLED=false
SEND_DEFAULT_MODE=sync
SEND_GLOBAL_RATE_PER_MINUTE=
SEND_BOT_RATE_PER_MINUTE=
SEND_CHAT_RATE_PER_MINUTE=
SEND_DESTINATION_RATE_PER_MINUTE=
SEND_RETRY_BASE_DELAY_SECONDS=1
SEND_RETRY_MAX_DELAY_SECONDS=300
SEND_WORKER_LEASE_SECONDS=60
SEND_STALE_LOCK_GRACE_SECONDS=30
SEND_DEDUPE_WINDOW_SECONDS=
```

- [ ] **Step 3: Run full test and lint suite**

Run:

```bash
PYTHONPATH=src python3.11 -m ruff check .
PYTHONPATH=src python3.11 -m pytest -q
bash -n deploy/proxmox/configure-lxc.sh deploy/proxmox/ct-ip.sh deploy/nginx/update-nginx-ui.sh
```

Expected:

```text
All checks passed!
<pytest count> passed
```

`bash -n` should produce no output.

- [ ] **Step 4: Restart local server if needed**

If the current server is still running on port `8000`, stop only that uvicorn process and start it again with the same local env used during development:

```bash
lsof -tiTCP:8000 -sTCP:LISTEN | xargs -r kill
PYTHONPATH=src DATABASE_URL=sqlite+aiosqlite:///./data/app.db TELETHON_SESSION_DIR=./data/telethon SHARED_MEDIA_ROOT=/mnt/omw-media SHARED_MEDIA_REQUIRE_MOUNT=true TELEGRAM_BOT_API_BASE_URL=https://api.telegram.org python3.11 -m uvicorn tg_bot_aggregator.main:create_app --factory --host 0.0.0.0 --port 8000
```

Expected: uvicorn reports it is running on `http://0.0.0.0:8000`.

- [ ] **Step 5: Browser smoke check**

Open `http://localhost:8000/` in the in-app browser and verify:

- The `Надежность` tab is visible.
- The live graph nodes do not overlap at desktop width.
- Existing tabs from the non-loss requirement are still visible.
- `История` still has retry/cancel controls.
- `Отправка` still has text/template/file subtabs.
- `Операции` still has backup/restore controls.

- [ ] **Step 6: Commit docs**

```bash
git add README.md .env.example
git commit -m "docs: document send reliability controls"
```

---

## Self-Review

Spec coverage:

- Architecture: Tasks 2, 3, 4, and 5.
- New states and persistence: Task 1.
- Backoff policy: Task 2 and Task 4.
- Rate buckets and degraded fallback: Task 3 and Task 5.
- Leases and stale lock release: Task 1, Task 4, and Task 5.
- Attempts history: Task 1, Task 4, Task 5, and Task 7.
- REST API: Task 5.
- SSE events: Task 4 and Task 7.
- MCP tools: Task 6.
- Dashboard graph with no feature loss: Task 7 and Task 8.
- Documentation and verification: Task 8.

Placeholder scan:

- No task uses unresolved requirement placeholders.
- Code names introduced in later tasks are defined earlier in the plan.

Risk notes:

- SQLite does not provide row-level locks. Lease acquisition is still sufficient for this local service when workers respect `lock_expires_at`; if heavy multi-worker contention appears later, the repository method can be tightened with an atomic SQL update.
- `reliability_enabled=false` preserves existing local behavior until the dashboard/user enables the full mode.
