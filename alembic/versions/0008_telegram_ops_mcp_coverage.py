"""telegram ops mcp coverage

Revision ID: 0008_telegram_ops_mcp_coverage
Revises: 0007_send_reliability_layer
Create Date: 2026-05-03
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_telegram_ops_mcp_coverage"
down_revision: str | None = "0007_send_reliability_layer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_API_TOKEN_SCOPES = '["read", "send", "mcp_admin", "tg_compat"]'
API_TOKEN_SCOPES_WITH_OPS_ADMIN = '["read", "send", "mcp_admin", "tg_compat", "ops_admin"]'


def _loads_scopes(value: object) -> list[str]:
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    if not isinstance(parsed, list):
        return []
    return [scope for scope in parsed if isinstance(scope, str)]


def backfill_ops_admin_scope(bind: sa.engine.Connection | None = None) -> None:
    connection = bind or op.get_bind()
    api_tokens = sa.table(
        "api_tokens",
        sa.column("id", sa.Integer()),
        sa.column("scopes_json", sa.JSON()),
    )
    rows = connection.execute(sa.select(api_tokens.c.id, api_tokens.c.scopes_json)).all()
    for token_id, scopes_value in rows:
        scopes = _loads_scopes(scopes_value)
        if "mcp_admin" not in scopes or "ops_admin" in scopes:
            continue
        connection.execute(
            api_tokens.update()
            .where(api_tokens.c.id == token_id)
            .values(scopes_json=[*scopes, "ops_admin"])
        )


def upgrade() -> None:
    backfill_ops_admin_scope()
    with op.batch_alter_table("api_tokens") as batch_op:
        batch_op.alter_column(
            "scopes_json",
            existing_type=sa.JSON(),
            server_default=API_TOKEN_SCOPES_WITH_OPS_ADMIN,
        )
    op.create_table(
        "ops_facts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identity_key", sa.String(length=128), nullable=False),
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
        sa.UniqueConstraint("identity_key", name="uq_ops_fact_identity"),
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
    with op.batch_alter_table("api_tokens") as batch_op:
        batch_op.alter_column(
            "scopes_json",
            existing_type=sa.JSON(),
            server_default=OLD_API_TOKEN_SCOPES,
        )
