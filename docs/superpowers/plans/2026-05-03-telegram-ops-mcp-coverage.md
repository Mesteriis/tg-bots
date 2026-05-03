# Telegram Ops And MCP Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a visible Telegram Ops layer that converts discovered bot/chat/topic facts into recommendations, controlled automation, and complete MCP coverage insight.

**Architecture:** Add a focused `telegram_ops.py` application service and `/api/v1/ops` router. Store facts, recommendations, rules, and action runs in additive SQLite tables; REST, UI, MCP, scheduler, and audit all call the same service methods. MCP coverage is computed from a static domain matrix plus the existing MCP tool catalog and settings.

**Tech Stack:** FastAPI, SQLAlchemy async, SQLite/Alembic, Vue 3 CDN, MCP FastMCP, pytest, ruff.

---

## File Structure

Create:

- `alembic/versions/0008_telegram_ops_mcp_coverage.py`: additive tables for ops facts, recommendations, automation rules, action runs, and optional MCP coverage snapshots.
- `src/tg_bot_aggregator/telegram_ops.py`: fact collection, recommendation generation, preview/apply, automation rules, action runs, and MCP coverage matrix.
- `src/tg_bot_aggregator/api/ops.py`: REST endpoints under `/api/v1/ops`.
- `tests/test_telegram_ops.py`: unit tests for fact collection, recommendations, preview/apply, auto-apply allowlist, and coverage matrix.
- `tests/test_api_ops.py`: REST integration tests for ops endpoints and protected-host scope behavior.

Modify:

- `src/tg_bot_aggregator/models.py`: add `OpsFact`, `OpsRecommendation`, `OpsAutomationRule`, `OpsActionRun`, and `McpCoverageSnapshot`; add `ops_admin` to `ApiToken` defaults.
- `src/tg_bot_aggregator/repositories.py`: add repositories for new ops tables.
- `src/tg_bot_aggregator/schemas.py`: add ops request/response schemas and extend API-token scope literals with `ops_admin`.
- `src/tg_bot_aggregator/auth_middleware.py`: require `ops_admin` for protected-host non-GET `/api/v1/ops/*`.
- `src/tg_bot_aggregator/main.py`: register ops router and pass ops services to MCP where needed.
- `src/tg_bot_aggregator/mcp_catalog.py`: register Telegram Ops and MCP coverage tools.
- `src/tg_bot_aggregator/mcp_server.py`: implement new tools through `TelegramOpsService`.
- `src/tg_bot_aggregator/scheduler.py`: enqueue/run ops automation rules on the existing scheduler loop.
- `src/tg_bot_aggregator/static/index.html`: expand `Автопоиск` into `Telegram Ops` with facts, recommendations, automation, action log, and MCP coverage.
- `tests/test_mcp_server.py`: add Telegram Ops and coverage tool tests.
- `tests/test_mcp_settings.py`: assert new tools appear disabled or enabled according to the intended defaults.
- `tests/test_api_auth.py`: add `ops_admin` protected-host checks.
- `tests/test_static_ui.py`: assert UI coverage and no feature loss.
- `README.md`: document Telegram Ops and MCP coverage.

---

### Task 1: Schema, Models, Repositories, And `ops_admin` Scope

**Files:**
- Create: `alembic/versions/0008_telegram_ops_mcp_coverage.py`
- Modify: `src/tg_bot_aggregator/models.py`
- Modify: `src/tg_bot_aggregator/repositories.py`
- Modify: `src/tg_bot_aggregator/schemas.py`
- Test: `tests/test_telegram_ops.py`
- Test: `tests/test_api_auth.py`

- [ ] **Step 1: Write failing model and repository tests**

Add to `tests/test_telegram_ops.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.models import utc_now
from tg_bot_aggregator.repositories import (
    BotRepository,
    OpsActionRunRepository,
    OpsAutomationRuleRepository,
    OpsFactRepository,
    OpsRecommendationRepository,
)


@pytest.mark.asyncio
async def test_ops_fact_recommendation_rule_and_action_run_repositories(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    facts = OpsFactRepository(db_session)
    recommendations = OpsRecommendationRepository(db_session)
    rules = OpsAutomationRuleRepository(db_session)
    runs = OpsActionRunRepository(db_session)

    fact = await facts.upsert_fact(
        fact_type="chat_seen",
        bot_id=bot.id,
        chat_id="-1001",
        message_thread_id=None,
        source="diagnostic_update",
        title="Ops Chat",
        username="ops_chat",
        kind="supergroup",
        status="active",
        confidence=100,
        payload_json={"chat_id": "-1001", "token": "redacted"},
    )
    recommendation = await recommendations.create(
        recommendation_type="create_destination_from_seen_chat",
        status="open",
        risk="low",
        bot_id=bot.id,
        fact_ids_json=[fact.id],
        title="Create destination Ops Chat",
        reason="Chat was observed but no destination exists.",
        diff_json={"create": {"chat_id": "-1001", "kind": "supergroup"}},
        action_payload_json={"bot_id": bot.id, "chat_id": "-1001"},
    )
    rule = await rules.upsert_by_key(
        "create_destination_from_seen_chat",
        title="Create destinations from observed chats",
        mode="suggest_only",
        is_enabled=True,
        is_paused=False,
        risk_limit="low",
        config_json={},
    )
    action_run = await runs.create(
        recommendation_id=recommendation.id,
        rule_id=rule.id,
        action_type="preview",
        source="dashboard",
        actor="local",
        status="succeeded",
        preview_diff_json=recommendation.diff_json,
        request_payload_json={"recommendation_id": recommendation.id},
        result_json={"status": "previewed"},
        rollback_hint="No data was changed.",
        finished_at=utc_now(),
    )
    await db_session.commit()

    assert (await facts.list())[0].chat_id == "-1001"
    assert (await recommendations.list(status="open"))[0].id == recommendation.id
    assert (await rules.list())[0].rule_key == "create_destination_from_seen_chat"
    assert (await runs.list())[0].id == action_run.id
```

Add to `tests/test_api_auth.py`:

```python
async def test_protected_host_ops_writes_require_ops_admin_scope(client_factory) -> None:
    client = await client_factory(protected_hosts=["tg.sh-inc.test"])
    token_response = await client.post(
        "/api/v1/auth/tokens",
        json={"name": "read-only", "scopes": ["read"]},
        headers={"host": "localhost"},
    )
    token = token_response.json()["token"]

    denied = await client.post(
        "/api/v1/ops/scan",
        headers={"host": "tg.sh-inc.test", "x-api-token": token},
    )

    assert denied.status_code == 403
    assert "ops_admin" in denied.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_telegram_ops.py tests/test_api_auth.py::test_protected_host_ops_writes_require_ops_admin_scope -q
```

Expected: FAIL with missing ops repository classes and missing `/api/v1/ops/scan`.

- [ ] **Step 3: Add Alembic migration**

Create `alembic/versions/0008_telegram_ops_mcp_coverage.py`:

```python
"""telegram ops mcp coverage

Revision ID: 0008_telegram_ops_mcp_coverage
Revises: 0007_send_reliability_layer
Create Date: 2026-05-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_telegram_ops_mcp_coverage"
down_revision: str | None = "0007_send_reliability_layer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ops_facts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fact_type", sa.String(length=80), nullable=False),
        sa.Column("bot_id", sa.Integer(), sa.ForeignKey("bots.id", ondelete="CASCADE")),
        sa.Column("chat_id", sa.String(length=200)),
        sa.Column("message_thread_id", sa.Integer()),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=300)),
        sa.Column("username", sa.String(length=200)),
        sa.Column("kind", sa.String(length=40)),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("payload_json", sa.JSON()),
        sa.UniqueConstraint(
            "fact_type",
            "bot_id",
            "chat_id",
            "message_thread_id",
            "source",
            name="uq_ops_fact_identity",
        ),
    )
    op.create_table(
        "ops_recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recommendation_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="open"),
        sa.Column("risk", sa.String(length=40), nullable=False),
        sa.Column("bot_id", sa.Integer(), sa.ForeignKey("bots.id", ondelete="CASCADE")),
        sa.Column(
            "destination_id",
            sa.Integer(),
            sa.ForeignKey("destinations.id", ondelete="SET NULL"),
        ),
        sa.Column("fact_ids_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("diff_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("action_payload_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "ops_automation_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_key", sa.String(length=120), nullable=False, unique=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("mode", sa.String(length=40), nullable=False, server_default="suggest_only"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("risk_limit", sa.String(length=40), nullable=False, server_default="low"),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_result", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "ops_action_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "recommendation_id",
            sa.Integer(),
            sa.ForeignKey("ops_recommendations.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "rule_id",
            sa.Integer(),
            sa.ForeignKey("ops_automation_rules.id", ondelete="SET NULL"),
        ),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=120)),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("preview_diff_json", sa.JSON()),
        sa.Column("request_payload_json", sa.JSON()),
        sa.Column("result_json", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("rollback_hint", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "mcp_coverage_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("captured_at", sa.DateTime(timezone=True)),
        sa.Column("matrix_json", sa.JSON(), nullable=False),
        sa.Column("missing_required_tools_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("warnings_json", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_ops_facts_fact_type", "ops_facts", ["fact_type"])
    op.create_index("ix_ops_recommendations_status", "ops_recommendations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ops_recommendations_status", table_name="ops_recommendations")
    op.drop_index("ix_ops_facts_fact_type", table_name="ops_facts")
    op.drop_table("mcp_coverage_snapshots")
    op.drop_table("ops_action_runs")
    op.drop_table("ops_automation_rules")
    op.drop_table("ops_recommendations")
    op.drop_table("ops_facts")
```

- [ ] **Step 4: Add ORM models**

Modify `src/tg_bot_aggregator/models.py` after `BotDiscoveryEvent`:

```python
class OpsFact(Base):
    __tablename__ = "ops_facts"
    __table_args__ = (
        UniqueConstraint(
            "fact_type",
            "bot_id",
            "chat_id",
            "message_thread_id",
            "source",
            name="uq_ops_fact_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    bot_id: Mapped[int | None] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    chat_id: Mapped[str | None] = mapped_column(String(200))
    message_thread_id: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    username: Mapped[str | None] = mapped_column(String(200))
    kind: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
```

Add `OpsRecommendation`, `OpsAutomationRule`, `OpsActionRun`, and `McpCoverageSnapshot` with fields exactly matching the migration. Use `Mapped[dict[str, Any]]` for JSON objects that default to `{}` and `Mapped[list[int]]` or `Mapped[list[str]]` for JSON arrays.

Update `ApiToken.scopes_json` default:

```python
default=lambda: ["read", "send", "mcp_admin", "tg_compat", "ops_admin"],
```

- [ ] **Step 5: Add repositories**

Modify `src/tg_bot_aggregator/repositories.py` imports to include the new models. Add repository classes:

```python
class OpsFactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_fact(self, **values: Any) -> OpsFact:
        statement = select(OpsFact).where(
            OpsFact.fact_type == values["fact_type"],
            OpsFact.bot_id.is_(values.get("bot_id"))
            if values.get("bot_id") is None
            else OpsFact.bot_id == values.get("bot_id"),
            OpsFact.chat_id.is_(values.get("chat_id"))
            if values.get("chat_id") is None
            else OpsFact.chat_id == values.get("chat_id"),
            OpsFact.message_thread_id.is_(values.get("message_thread_id"))
            if values.get("message_thread_id") is None
            else OpsFact.message_thread_id == values.get("message_thread_id"),
            OpsFact.source == values["source"],
        )
        row = (await self.session.execute(statement)).scalar_one_or_none()
        if row is None:
            row = OpsFact(**values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.observed_at = utc_now()
        await self.session.flush()
        return row

    async def list(self, limit: int = 200) -> list[OpsFact]:
        statement = select(OpsFact).order_by(OpsFact.id.desc()).limit(limit)
        return await _list(self.session, statement)
```

Add analogous `create`, `get`, `list`, and status update methods for `OpsRecommendationRepository`, `OpsAutomationRuleRepository`, and `OpsActionRunRepository`. Keep methods explicit: `mark_previewed`, `mark_applied`, `mark_dismissed`, `mark_stale`, `mark_failed`.

- [ ] **Step 6: Update schemas and auth scope literals**

Modify `src/tg_bot_aggregator/schemas.py`:

```python
ApiScope = Literal["read", "send", "mcp_admin", "tg_compat", "ops_admin"]
```

Use `ApiScope` in `ApiTokenCreate.scopes`.

Add read/update models:

```python
class OpsFactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fact_type: str
    bot_id: int | None
    chat_id: str | None
    message_thread_id: int | None
    source: str
    title: str | None
    username: str | None
    kind: str | None
    status: str
    confidence: int
    observed_at: datetime
    expires_at: datetime | None
    payload_json: dict[str, Any] | None
```

Add `OpsRecommendationRead`, `OpsActionPreviewRead`, `OpsRuleRead`, `OpsRuleUpdate`, `OpsActionRunRead`, and `McpCoverageRead`. The `OpsRuleUpdate.mode` field must be `Literal["suggest_only", "auto_apply"] | None`; `risk_limit` must be `Literal["low", "medium", "high"] | None`.

- [ ] **Step 7: Update protected-host auth**

Modify `ProtectedHostAuthMiddleware._scope_for_path` before the general non-GET fallback:

```python
if path.startswith(f"{settings.api_v1_prefix}/ops") and method not in {"GET", "HEAD"}:
    return "ops_admin"
```

Also update fallback scopes:

```python
scopes = set(row.scopes_json or ["read", "send", "mcp_admin", "tg_compat", "ops_admin"])
```

- [ ] **Step 8: Run model/auth tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_telegram_ops.py tests/test_api_auth.py -q
```

Expected: repository tests PASS; the protected-host test still fails until the ops router exists.

- [ ] **Step 9: Commit schema primitives**

```bash
git add alembic/versions/0008_telegram_ops_mcp_coverage.py src/tg_bot_aggregator/models.py src/tg_bot_aggregator/repositories.py src/tg_bot_aggregator/schemas.py src/tg_bot_aggregator/auth_middleware.py tests/test_telegram_ops.py tests/test_api_auth.py
git commit -m "feat: add telegram ops persistence"
```

---

### Task 2: Telegram Ops Service

**Files:**
- Create: `src/tg_bot_aggregator/telegram_ops.py`
- Modify: `tests/test_telegram_ops.py`

- [ ] **Step 1: Write failing service tests**

Add to `tests/test_telegram_ops.py`:

```python
from tg_bot_aggregator.telegram_ops import (
    McpCoverageService,
    TelegramOpsService,
    build_destination_diff,
)


@pytest.mark.asyncio
async def test_ops_scan_creates_destination_recommendation_from_diagnostic_update(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    await DiagnosticUpdateRepository(db_session).create(
        update_id=100,
        update_kind="message",
        chat_id="-1001",
        chat_type="supergroup",
        chat_title="Ops Chat",
        chat_username="ops_chat",
        message_thread_id=77,
        is_topic_message=True,
        raw_update_json={"update_id": 100},
    )
    service = TelegramOpsService(db_session)

    result = await service.scan(source="test")
    await db_session.commit()
    recommendations = await OpsRecommendationRepository(db_session).list(status="open")

    assert result["facts_created"] == 1
    assert recommendations[0].recommendation_type == "create_destination_from_seen_chat"
    assert recommendations[0].diff_json["after"]["message_thread_id"] == 77


def test_build_destination_diff_is_stable_and_human_readable() -> None:
    diff = build_destination_diff(
        before=None,
        after={
            "bot_id": 1,
            "chat_id": "-1001",
            "message_thread_id": 77,
            "kind": "forum_topic",
            "title": "Ops Chat",
            "username": "ops_chat",
            "is_active": True,
        },
    )

    assert diff["operation"] == "create"
    assert diff["before"] is None
    assert diff["after"]["chat_id"] == "-1001"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_telegram_ops.py::test_ops_scan_creates_destination_recommendation_from_diagnostic_update tests/test_telegram_ops.py::test_build_destination_diff_is_stable_and_human_readable -q
```

Expected: FAIL because `telegram_ops.py` does not exist.

- [ ] **Step 3: Implement constants and diff helpers**

Create `src/tg_bot_aggregator/telegram_ops.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.models import Destination, OpsRecommendation, utc_now
from tg_bot_aggregator.repositories import (
    DestinationHealthRepository,
    DestinationRepository,
    DiagnosticUpdateRepository,
    OpsActionRunRepository,
    OpsAutomationRuleRepository,
    OpsFactRepository,
    OpsRecommendationRepository,
)
from tg_bot_aggregator.security import redact_secrets

OpsRisk = Literal["low", "medium", "high"]

AUTO_APPLY_ACTIONS: frozenset[str] = frozenset(
    {
        "create_destination_from_seen_chat",
        "update_destination_metadata",
        "record_forum_topic_thread",
        "mark_destination_unhealthy",
    }
)

RISK_RANK: dict[str, int] = {"low": 1, "medium": 2, "high": 3}


class TelegramOpsError(ValueError):
    pass


def normalize_destination_kind(chat_type: str | None, message_thread_id: int | None) -> str:
    if message_thread_id is not None:
        return "forum_topic"
    if chat_type in {"private", "group", "supergroup", "channel"}:
        return chat_type
    return "group"


def build_destination_diff(
    before: Destination | dict[str, Any] | None,
    after: dict[str, Any],
) -> dict[str, Any]:
    before_data = None
    if isinstance(before, Destination):
        before_data = {
            "bot_id": before.bot_id,
            "chat_id": before.chat_id,
            "message_thread_id": before.message_thread_id,
            "kind": before.kind,
            "title": before.title,
            "username": before.username,
            "is_active": before.is_active,
        }
    elif before is not None:
        before_data = dict(before)
    operation = "create" if before_data is None else "update"
    changed = {
        key: {"before": None if before_data is None else before_data.get(key), "after": value}
        for key, value in after.items()
        if before_data is None or before_data.get(key) != value
    }
    return {"operation": operation, "before": before_data, "after": after, "changed": changed}
```

- [ ] **Step 4: Implement scan and advisor**

Add `TelegramOpsService.scan`:

```python
class TelegramOpsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.facts = OpsFactRepository(session)
        self.recommendations = OpsRecommendationRepository(session)
        self.rules = OpsAutomationRuleRepository(session)
        self.runs = OpsActionRunRepository(session)
        self.destinations = DestinationRepository(session)

    async def scan(self, source: str = "dashboard") -> dict[str, int]:
        created_facts = 0
        created_recommendations = 0
        updates = await DiagnosticUpdateRepository(self.session).list(limit=500)
        for update in updates:
            if update.chat_id is None:
                continue
            kind = normalize_destination_kind(update.chat_type, update.message_thread_id)
            fact = await self.facts.upsert_fact(
                fact_type="chat_seen",
                bot_id=None,
                chat_id=update.chat_id,
                message_thread_id=update.message_thread_id,
                source="diagnostic_update",
                title=update.chat_title,
                username=update.chat_username,
                kind=kind,
                status="active",
                confidence=90,
                payload_json=redact_secrets(update.raw_update_json or {}),
            )
            created_facts += 1
            recommendation = await self._recommend_destination_from_fact(fact)
            if recommendation is not None:
                created_recommendations += 1
        await self._ensure_default_rules()
        return {
            "facts_created": created_facts,
            "recommendations_created": created_recommendations,
        }
```

Implement `_recommend_destination_from_fact` so it skips a fact when no bot exists. For version 1, use the first active bot as the target bot when the fact has no `bot_id`. If a destination already exists, create `update_destination_metadata` only when title, username, kind, or `message_thread_id` differs.

- [ ] **Step 5: Implement preview, apply, dismiss, and rules**

Add service methods:

```python
async def preview_action(
    self,
    recommendation_id: int,
    *,
    source: str,
    actor: str,
) -> dict[str, Any]:
    recommendation = await self._get_open_recommendation(recommendation_id)
    run = await self.runs.create(
        recommendation_id=recommendation.id,
        rule_id=None,
        action_type="preview",
        source=source,
        actor=actor,
        status="succeeded",
        preview_diff_json=recommendation.diff_json,
        request_payload_json={"recommendation_id": recommendation.id},
        result_json={"status": "previewed"},
        rollback_hint="No data was changed.",
        finished_at=utc_now(),
    )
    await self.recommendations.mark_previewed(recommendation)
    return {"recommendation_id": recommendation.id, "diff": recommendation.diff_json, "run_id": run.id}
```

Implement `apply_action` so it:

- rejects non-open, non-previewed recommendations;
- rejects recommendation types not in `AUTO_APPLY_ACTIONS` when called with `auto_apply=True`;
- creates or updates destinations through `DestinationRepository.upsert_by_chat`;
- updates recommendation status to `applied`;
- creates an action run with `status="succeeded"`;
- returns `{"recommendation_id": id, "status": "applied", "destination_id": destination.id}`.

Implement `dismiss_recommendation`, `list_rules`, `update_rule`, `run_rule`, `pause_rule`, and `resume_rule`.

- [ ] **Step 6: Implement MCP coverage service**

Add:

```python
@dataclass(frozen=True)
class McpDomainCoverage:
    domain: str
    rest: bool
    ui: bool
    mcp_read_tools: tuple[str, ...]
    mcp_preview_tools: tuple[str, ...]
    mcp_apply_tools: tuple[str, ...]
    required_scopes: tuple[str, ...]
    risk: str
```

Add `REQUIRED_MCP_COVERAGE` with rows for the domains in the spec. Implement:

```python
class McpCoverageService:
    def __init__(self, enabled_tools: set[str]) -> None:
        self.enabled_tools = enabled_tools

    def matrix(self) -> dict[str, Any]:
        rows = []
        missing_required_tools: list[str] = []
        for coverage in REQUIRED_MCP_COVERAGE:
            tools = (
                list(coverage.mcp_read_tools)
                + list(coverage.mcp_preview_tools)
                + list(coverage.mcp_apply_tools)
            )
            missing = [tool for tool in tools if tool not in self.enabled_tools]
            missing_required_tools.extend(missing)
            rows.append(
                {
                    "domain": coverage.domain,
                    "rest": coverage.rest,
                    "ui": coverage.ui,
                    "mcp_read_tools": list(coverage.mcp_read_tools),
                    "mcp_preview_tools": list(coverage.mcp_preview_tools),
                    "mcp_apply_tools": list(coverage.mcp_apply_tools),
                    "required_scopes": list(coverage.required_scopes),
                    "risk": coverage.risk,
                    "enabled": [tool for tool in tools if tool in self.enabled_tools],
                    "missing": missing,
                }
            )
        return {"rows": rows, "missing_required_tools": sorted(set(missing_required_tools))}
```

- [ ] **Step 7: Run service tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_telegram_ops.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit ops service**

```bash
git add src/tg_bot_aggregator/telegram_ops.py tests/test_telegram_ops.py
git commit -m "feat: add telegram ops service"
```

---

### Task 3: REST API, Audit, And Events

**Files:**
- Create: `src/tg_bot_aggregator/api/ops.py`
- Modify: `src/tg_bot_aggregator/main.py`
- Modify: `tests/test_api_ops.py`
- Modify: `tests/test_api_auth.py`

- [ ] **Step 1: Write failing REST tests**

Create `tests/test_api_ops.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.main import create_app
from tg_bot_aggregator.models import utc_now
from tg_bot_aggregator.repositories import (
    BotRepository,
    DiagnosticUpdateRepository,
    OpsActionRunRepository,
)


@pytest.mark.asyncio
async def test_ops_scan_preview_apply_and_audit(db_session) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    await DiagnosticUpdateRepository(db_session).create(
        update_id=200,
        update_kind="message",
        chat_id="-1002",
        chat_type="supergroup",
        chat_title="Ops Two",
        message_thread_id=None,
        raw_update_json={"update_id": 200},
        created_at=utc_now(),
    )
    await db_session.commit()
    app = create_app(
        Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:"),
        session_factory=lambda: db_session,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        scan = await client.post("/api/v1/ops/scan")
        recommendations = await client.get("/api/v1/ops/recommendations")
        recommendation_id = recommendations.json()[0]["id"]
        preview = await client.post(f"/api/v1/ops/recommendations/{recommendation_id}/preview")
        applied = await client.post(f"/api/v1/ops/recommendations/{recommendation_id}/apply")
        runs = await client.get("/api/v1/ops/action-runs")

    assert scan.status_code == 200
    assert preview.json()["diff"]["operation"] == "create"
    assert applied.json()["status"] == "applied"
    assert runs.json()[0]["status"] == "succeeded"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api_ops.py -q
```

Expected: FAIL because `api/ops.py` is missing.

- [ ] **Step 3: Add API router**

Create `src/tg_bot_aggregator/api/ops.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import get_session
from tg_bot_aggregator.audit import record_audit_event
from tg_bot_aggregator.repositories import (
    McpSettingsRepository,
    OpsActionRunRepository,
    OpsAutomationRuleRepository,
    OpsFactRepository,
    OpsRecommendationRepository,
)
from tg_bot_aggregator.schemas import (
    McpCoverageRead,
    OpsActionPreviewRead,
    OpsActionRunRead,
    OpsFactRead,
    OpsRecommendationRead,
    OpsRuleRead,
    OpsRuleUpdate,
)
from tg_bot_aggregator.telegram_ops import McpCoverageService, TelegramOpsError, TelegramOpsService

router = APIRouter(prefix="/ops", tags=["ops"])
```

Add endpoints exactly matching the spec. Each write endpoint must:

- call `TelegramOpsService`;
- record an audit event through `record_audit_event`;
- publish an event when `request.app.state.event_bus` exists;
- commit on success;
- return `400` for `TelegramOpsError`.

- [ ] **Step 4: Register router**

Modify `src/tg_bot_aggregator/main.py` imports:

```python
    ops,
```

Register:

```python
app.include_router(ops.router, prefix=prefix)
```

- [ ] **Step 5: Run REST and auth tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_api_ops.py tests/test_api_auth.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit REST API**

```bash
git add src/tg_bot_aggregator/api/ops.py src/tg_bot_aggregator/main.py tests/test_api_ops.py tests/test_api_auth.py
git commit -m "feat: expose telegram ops api"
```

---

### Task 4: MCP Tools And Coverage Matrix

**Files:**
- Modify: `src/tg_bot_aggregator/mcp_catalog.py`
- Modify: `src/tg_bot_aggregator/mcp_server.py`
- Modify: `tests/test_mcp_server.py`
- Modify: `tests/test_mcp_settings.py`

- [ ] **Step 1: Write failing MCP tests**

Add to `tests/test_mcp_server.py`:

```python
def test_mcp_catalog_contains_telegram_ops_tools() -> None:
    tools = {tool.name: tool for tool in MCP_TOOL_DEFINITIONS}
    expected = {
        "inspect_bot_access": ("ops", "read"),
        "list_ops_facts": ("ops", "read"),
        "run_ops_scan": ("ops", "write"),
        "list_ops_recommendations": ("ops", "read"),
        "preview_ops_action": ("ops", "read"),
        "apply_ops_action": ("ops", "admin"),
        "dismiss_ops_recommendation": ("ops", "write"),
        "list_ops_rules": ("ops", "read"),
        "update_ops_rule": ("ops", "admin"),
        "run_ops_rule": ("ops", "admin"),
        "pause_ops_rule": ("ops", "admin"),
        "resume_ops_rule": ("ops", "admin"),
        "explain_failed_send": ("ops", "read"),
        "get_mcp_coverage_matrix": ("ops", "read"),
        "recommend_mcp_preset": ("ops", "read"),
    }
    for name, (category, risk) in expected.items():
        assert name in tools
        assert tools[name].category == category
        assert tools[name].risk == risk
```

Add an async test that calls `get_mcp_coverage_matrix` and asserts the response contains `telegram_ops`, `send`, `reliability`, and `operations_backup` domains.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_mcp_server.py tests/test_mcp_settings.py -q
```

Expected: FAIL with missing tool catalog entries.

- [ ] **Step 3: Add MCP catalog definitions**

Modify `MCP_TOOL_DEFINITIONS`:

```python
    McpToolDefinition("inspect_bot_access", "Inspect bot access", "ops", "read"),
    McpToolDefinition("list_ops_facts", "List Telegram Ops facts", "ops", "read"),
    McpToolDefinition("run_ops_scan", "Run Telegram Ops scan", "ops", "write"),
    McpToolDefinition("list_ops_recommendations", "List Telegram Ops recommendations", "ops", "read"),
    McpToolDefinition("preview_ops_action", "Preview Telegram Ops action", "ops", "read"),
    McpToolDefinition("apply_ops_action", "Apply Telegram Ops action", "ops", "admin"),
    McpToolDefinition("dismiss_ops_recommendation", "Dismiss Telegram Ops recommendation", "ops", "write"),
    McpToolDefinition("list_ops_rules", "List Telegram Ops rules", "ops", "read"),
    McpToolDefinition("update_ops_rule", "Update Telegram Ops rule", "ops", "admin"),
    McpToolDefinition("run_ops_rule", "Run Telegram Ops rule", "ops", "admin"),
    McpToolDefinition("pause_ops_rule", "Pause Telegram Ops rule", "ops", "admin"),
    McpToolDefinition("resume_ops_rule", "Resume Telegram Ops rule", "ops", "admin"),
    McpToolDefinition("explain_failed_send", "Explain failed send", "ops", "read"),
    McpToolDefinition("get_mcp_coverage_matrix", "Get MCP coverage matrix", "ops", "read"),
    McpToolDefinition("recommend_mcp_preset", "Recommend MCP preset", "ops", "read"),
```

Do not add admin/write ops tools to `MCP_DEFAULT_ENABLED_TOOL_NAMES`. Add only:

```python
    "list_ops_facts",
    "list_ops_recommendations",
    "list_ops_rules",
    "explain_failed_send",
    "get_mcp_coverage_matrix",
    "recommend_mcp_preset",
```

- [ ] **Step 4: Implement MCP tools**

Modify `src/tg_bot_aggregator/mcp_server.py`. For each tool:

- call `ensure_mcp_tool_enabled`;
- open a session from `get_session_factory()`;
- call `TelegramOpsService`;
- commit for write tools;
- return plain JSON-serializable dictionaries/lists.

Example:

```python
    @mcp.tool()
    async def get_mcp_coverage_matrix() -> dict[str, Any]:
        await ensure_mcp_tool_enabled(get_session_factory(), "get_mcp_coverage_matrix")
        async with get_session_factory()() as session:
            settings = await McpSettingsRepository(session).get_or_create()
            return McpCoverageService(set(settings.enabled_tools_json or [])).matrix()
```

Implement `explain_failed_send(send_history_id: int)` by reading send history and attempts. Return:

```python
{
    "send_history_id": send_history_id,
    "status": row.status,
    "error_code": row.error_code,
    "error_message": row.error_message,
    "last_error_kind": row.last_error_kind,
    "attempts": [...],
    "summary": "Telegram returned 429; retry is deferred." | "No failure details are recorded.",
}
```

- [ ] **Step 5: Run MCP tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_mcp_server.py tests/test_mcp_settings.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit MCP coverage**

```bash
git add src/tg_bot_aggregator/mcp_catalog.py src/tg_bot_aggregator/mcp_server.py tests/test_mcp_server.py tests/test_mcp_settings.py
git commit -m "feat: add telegram ops mcp tools"
```

---

### Task 5: Scheduler Auto-Apply And SSE Events

**Files:**
- Modify: `src/tg_bot_aggregator/tasks.py`
- Modify: `src/tg_bot_aggregator/scheduler.py`
- Modify: `tests/test_tasks.py`
- Modify: `tests/test_telegram_ops.py`

- [ ] **Step 1: Write failing auto-apply tests**

Add to `tests/test_telegram_ops.py`:

```python
@pytest.mark.asyncio
async def test_auto_apply_rule_only_applies_allowlisted_low_risk_recommendations(
    db_session: AsyncSession,
) -> None:
    bot = await BotRepository(db_session).create(name="ops", token="123:abc")
    service = TelegramOpsService(db_session)
    await OpsRecommendationRepository(db_session).create(
        recommendation_type="create_destination_from_seen_chat",
        status="open",
        risk="low",
        bot_id=bot.id,
        fact_ids_json=[],
        title="Create destination",
        reason="Observed chat has no destination.",
        diff_json={
            "operation": "create",
            "after": {
                "bot_id": bot.id,
                "chat_id": "-1001",
                "message_thread_id": None,
                "kind": "supergroup",
                "title": "Ops Chat",
                "username": None,
                "is_active": True,
            },
        },
        action_payload_json={
            "bot_id": bot.id,
            "chat_id": "-1001",
            "message_thread_id": None,
            "kind": "supergroup",
            "title": "Ops Chat",
            "username": None,
            "is_active": True,
        },
    )
    rule = await OpsAutomationRuleRepository(db_session).upsert_by_key(
        "create_destination_from_seen_chat",
        title="Create destinations",
        mode="auto_apply",
        is_enabled=True,
        is_paused=False,
        risk_limit="low",
        config_json={},
    )

    result = await service.run_rule(rule.id, source="scheduler", actor="scheduler")
    await db_session.commit()

    assert result["applied"] == 1
    assert (await DestinationRepository(db_session).get_by_chat(bot.id, "-1001")) is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_telegram_ops.py::test_auto_apply_rule_only_applies_allowlisted_low_risk_recommendations -q
```

Expected: FAIL until `run_rule` handles auto-apply.

- [ ] **Step 3: Implement auto-apply run path**

In `TelegramOpsService.run_rule`, enforce:

```python
if rule.mode != "auto_apply":
    return {"applied": 0, "skipped": 0, "mode": rule.mode}
if not rule.is_enabled or rule.is_paused:
    return {"applied": 0, "skipped": 0, "mode": rule.mode}
```

For each open recommendation with matching `recommendation_type`, apply only when:

```python
recommendation.recommendation_type in AUTO_APPLY_ACTIONS
RISK_RANK[recommendation.risk] <= RISK_RANK[rule.risk_limit]
```

Update `rule.last_run_at` and `rule.last_result` before returning.

- [ ] **Step 4: Add Taskiq task and scheduler call**

Modify `src/tg_bot_aggregator/tasks.py`:

```python
@broker.task
async def run_ops_automation_rules() -> dict[str, int]:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    applied = 0
    skipped = 0
    try:
        async with session_factory() as session:
            service = TelegramOpsService(session)
            for rule in await OpsAutomationRuleRepository(session).list():
                result = await service.run_rule(rule.id, source="scheduler", actor="scheduler")
                applied += int(result.get("applied", 0))
                skipped += int(result.get("skipped", 0))
            await session.commit()
        return {"applied": applied, "skipped": skipped}
    finally:
        await engine.dispose()
```

Modify `src/tg_bot_aggregator/scheduler.py`:

```python
from tg_bot_aggregator.tasks import run_ops_automation_rules
...
await run_ops_automation_rules.kiq()
```

- [ ] **Step 5: Run task tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_telegram_ops.py tests/test_tasks.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit automation**

```bash
git add src/tg_bot_aggregator/telegram_ops.py src/tg_bot_aggregator/tasks.py src/tg_bot_aggregator/scheduler.py tests/test_telegram_ops.py tests/test_tasks.py
git commit -m "feat: run telegram ops automation"
```

---

### Task 6: Dashboard UI

**Files:**
- Modify: `src/tg_bot_aggregator/static/index.html`
- Modify: `tests/test_static_ui.py`

- [ ] **Step 1: Write failing static UI tests**

Add to `tests/test_static_ui.py`:

```python
def test_static_ui_exposes_telegram_ops_sections() -> None:
    html = INDEX.read_text()

    assert '{ id: "discovery", label: "Telegram Ops"' in html
    for text in [
        "Факты",
        "Рекомендации",
        "Автоматизация",
        "Журнал действий",
        "MCP покрытие",
        "Preview",
        "Apply",
        "suggest_only",
        "auto_apply",
    ]:
        assert text in html


def test_static_ui_calls_ops_and_preserves_existing_tabs() -> None:
    html = INDEX.read_text()

    for endpoint in [
        'this.api("/ops/facts"',
        'this.api("/ops/scan"',
        'this.api("/ops/recommendations"',
        'this.api("/ops/action-runs"',
        'this.api("/ops/mcp-coverage"',
    ]:
        assert endpoint in html

    for label in ["Боты", "Адресаты", "Шаблоны", "Отправка", "История", "Надежность", "MCP", "Операции"]:
        assert label in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_static_ui.py::test_static_ui_exposes_telegram_ops_sections tests/test_static_ui.py::test_static_ui_calls_ops_and_preserves_existing_tabs -q
```

Expected: FAIL until UI is updated.

- [ ] **Step 3: Add UI state and load calls**

In Vue `data()`, add:

```javascript
opsFacts: [],
opsRecommendations: [],
opsRules: [],
opsActionRuns: [],
opsCoverage: { rows: [], missing_required_tools: [] },
selectedOpsRecommendation: null,
```

In `loadAll()`, add API calls for:

```javascript
this.api("/ops/facts"),
this.api("/ops/recommendations"),
this.api("/ops/rules"),
this.api("/ops/action-runs"),
this.api("/ops/mcp-coverage"),
```

- [ ] **Step 4: Rename/expand discovery tab**

Change the tab label:

```javascript
{ id: "discovery", label: "Telegram Ops", icon: "radar", description: "Автопоиск чатов, рекомендации, auto-apply правила и MCP coverage." },
```

Replace the `activeTab === 'discovery'` content with subtabs or stacked panels:

- `Факты`: table of facts.
- `Рекомендации`: cards with diff and buttons.
- `Автоматизация`: rules table with mode selector, pause/resume, run.
- `Журнал действий`: action runs table.
- `MCP покрытие`: matrix table.

Keep existing discovery settings controls inside the first panel or a compact side panel so no current functionality disappears.

- [ ] **Step 5: Add UI methods**

Add methods:

```javascript
async refreshOps() { ... }
async runOpsScan() { ... }
async previewOpsAction(recommendation) { ... }
async applyOpsAction(recommendation) { ... }
async dismissOpsRecommendation(recommendation) { ... }
async updateOpsRule(rule) { ... }
async runOpsRule(rule) { ... }
```

Each write method calls `await this.refreshOps()` after success.

- [ ] **Step 6: Run static UI tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_static_ui.py -q
```

Expected: PASS.

- [ ] **Step 7: Browser smoke**

With the local server running, open `http://localhost:8000/` and verify:

- `Telegram Ops` appears in navigation.
- Existing tabs still appear.
- Facts/recommendations/rules/action log/coverage sections render.
- No UI card overlaps at desktop viewport.
- Browser console has no errors.

- [ ] **Step 8: Commit dashboard**

```bash
git add src/tg_bot_aggregator/static/index.html tests/test_static_ui.py
git commit -m "feat: add telegram ops dashboard"
```

---

### Task 7: Documentation, Migrations, And Full Verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example` if scheduler interval or ops env is added.

- [ ] **Step 1: Document Telegram Ops**

Add a README section after `MCP Workflow Tools` or before `Shared Media`:

```markdown
## Telegram Ops

The `Telegram Ops` dashboard tab turns discovery and diagnostic facts into visible recommendations. The service separates facts, recommendations, preview, apply, and auto-apply:

- facts are observed Telegram state;
- recommendations explain what can be changed and why;
- preview returns a structured diff;
- apply changes data through the same repositories as the REST/UI flows;
- auto-apply is limited to low-risk reversible actions and every run is visible in the action log.

Auto-apply never sends messages, restores backups, enables secret backups, changes protected hosts, expands API-token scopes, enables write MCP tools, or deletes data.

REST endpoints live under `/api/v1/ops`. MCP tools include `list_ops_facts`, `list_ops_recommendations`, `preview_ops_action`, `apply_ops_action`, `list_ops_rules`, `run_ops_scan`, `explain_failed_send`, and `get_mcp_coverage_matrix`.
```

- [ ] **Step 2: Run migration smoke on a temporary SQLite database**

Run:

```bash
tmp_db="$(mktemp -t tg-ops.XXXXXX.db)"
DATABASE_URL="sqlite+aiosqlite:///$tmp_db" PYTHONPATH=src python3.11 -m alembic upgrade head
sqlite3 "$tmp_db" ".tables" | rg "ops_facts|ops_recommendations|ops_automation_rules|ops_action_runs"
rm -f "$tmp_db"
```

Expected: Alembic reaches head and the four ops tables exist.

- [ ] **Step 3: Run full validation**

Run:

```bash
PYTHONPATH=src python3.11 -m ruff check .
PYTHONPATH=src python3.11 -m pytest -q
bash -n deploy/proxmox/configure-lxc.sh deploy/proxmox/ct-ip.sh deploy/nginx/update-nginx-ui.sh
git diff --check
```

Expected:

```text
All checks passed!
<pytest count> passed
```

`bash -n` and `git diff --check` produce no output.

- [ ] **Step 4: Restart local server**

Run:

```bash
pids="$(lsof -tiTCP:8000 -sTCP:LISTEN || true)"
if [ -n "$pids" ]; then kill $pids; fi
PYTHONPATH=src DATABASE_URL=sqlite+aiosqlite:///./data/app.db TELETHON_SESSION_DIR=./data/telethon SHARED_MEDIA_ROOT=/Users/avm/projects/Personal/tg-bots/data/omw-media SHARED_MEDIA_REQUIRE_MOUNT=true TELEGRAM_BOT_API_BASE_URL=https://api.telegram.org python3.11 -m uvicorn tg_bot_aggregator.main:create_app --factory --host 0.0.0.0 --port 8000
```

Expected: uvicorn reports `Application startup complete`.

- [ ] **Step 5: Browser smoke**

Open `http://localhost:8000/` in the in-app browser and verify:

- `GET /api/v1/ops/mcp-coverage` returns rows for every required domain.
- `Telegram Ops` dashboard has facts, recommendations, rules, action log, and MCP coverage.
- Existing `Отправка`, `История`, `Надежность`, `MCP`, and `Операции` tabs remain usable.
- Console errors list is empty.

- [ ] **Step 6: Commit docs**

```bash
git add README.md .env.example
git commit -m "docs: document telegram ops"
```

---

## Self-Review

Spec coverage:

- Facts, recommendations, rules, action runs, and optional MCP coverage snapshots are implemented in Task 1.
- Fact collection, advisor, preview/apply, auto-apply allowlist, and coverage matrix are implemented in Task 2.
- REST endpoints, audit, and events are implemented in Task 3.
- MCP tools and matrix exposure are implemented in Task 4.
- Scheduler auto-apply path is implemented in Task 5.
- Dashboard visibility is implemented in Task 6.
- Docs, migration smoke, full validation, and browser smoke are implemented in Task 7.

Placeholder scan:

- No task contains unresolved placeholders.
- Every command includes expected output or pass/fail expectation.

Type and naming consistency:

- Model and repository names use the `Ops*` prefix consistently.
- REST path prefix is consistently `/api/v1/ops`.
- MCP tool names match the design spec and catalog tests.
- New scope is consistently named `ops_admin`.

Scope check:

- The plan does not add automatic sending, deletion, backup restore automation, secret backup automation, or token-scope expansion automation.
- Auto-apply is limited to low-risk reversible Telegram destination hygiene actions.
