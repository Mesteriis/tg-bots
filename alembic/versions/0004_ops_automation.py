"""ops automation

Revision ID: 0004_ops_automation
Revises: 0003_api_tokens_mcp_settings
Create Date: 2026-05-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_ops_automation"
down_revision: str | None = "0003_api_tokens_mcp_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALL_SCOPES = '["read", "send", "mcp_admin", "tg_compat"]'


def upgrade() -> None:
    op.add_column(
        "api_tokens",
        sa.Column("scopes_json", sa.JSON(), nullable=False, server_default=ALL_SCOPES),
    )

    op.add_column("destinations", sa.Column("alias", sa.String(length=100), nullable=True))
    with op.batch_alter_table("destinations") as batch_op:
        batch_op.create_unique_constraint("uq_destinations_bot_alias", ["bot_id", "alias"])

    op.add_column(
        "send_history",
        sa.Column("send_mode", sa.String(length=40), nullable=False, server_default="sync"),
    )
    op.add_column(
        "send_history",
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "send_history", sa.Column("idempotency_fingerprint", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "send_history",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("send_history", sa.Column("queued_task_id", sa.String(length=200), nullable=True))
    op.add_column("send_history", sa.Column("next_retry_at", sa.DateTime(timezone=True)))
    with op.batch_alter_table("send_history") as batch_op:
        batch_op.create_unique_constraint("uq_send_history_idempotency_key", ["idempotency_key"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column(
            "api_token_id",
            sa.Integer(),
            sa.ForeignKey("api_tokens.id", ondelete="SET NULL"),
        ),
        sa.Column("host", sa.String(length=300)),
        sa.Column("path", sa.String(length=500)),
        sa.Column("method", sa.String(length=20)),
        sa.Column("entity_type", sa.String(length=80)),
        sa.Column("entity_id", sa.String(length=120)),
        sa.Column("request_id", sa.String(length=120)),
        sa.Column("message", sa.Text()),
        sa.Column("metadata_json", sa.JSON()),
    )
    op.create_table(
        "bot_discovery_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "bot_id",
            sa.Integer(),
            sa.ForeignKey("bots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("last_update_id", sa.Integer()),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("bot_id", name="uq_bot_discovery_settings_bot_id"),
    )
    op.create_table(
        "bot_discovery_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "bot_id",
            sa.Integer(),
            sa.ForeignKey("bots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("update_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("old_status", sa.String(length=40)),
        sa.Column("new_status", sa.String(length=40)),
        sa.Column("raw_update_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("bot_id", "update_id", name="uq_bot_discovery_event_update"),
    )


def downgrade() -> None:
    op.drop_table("bot_discovery_events")
    op.drop_table("bot_discovery_settings")
    op.drop_table("audit_events")
    with op.batch_alter_table("send_history") as batch_op:
        batch_op.drop_constraint("uq_send_history_idempotency_key", type_="unique")
        batch_op.drop_column("next_retry_at")
        batch_op.drop_column("queued_task_id")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("idempotency_fingerprint")
        batch_op.drop_column("idempotency_key")
        batch_op.drop_column("send_mode")
    with op.batch_alter_table("destinations") as batch_op:
        batch_op.drop_constraint("uq_destinations_bot_alias", type_="unique")
    op.drop_column("destinations", "alias")
    op.drop_column("api_tokens", "scopes_json")
