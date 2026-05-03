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
    op.add_column("runtime_settings", sa.Column("reliability_enabled", sa.Boolean()))
    op.add_column("runtime_settings", sa.Column("send_default_mode", sa.String(length=40)))
    op.add_column("runtime_settings", sa.Column("send_global_rate_per_minute", sa.Integer()))
    op.add_column("runtime_settings", sa.Column("send_bot_rate_per_minute", sa.Integer()))
    op.add_column("runtime_settings", sa.Column("send_chat_rate_per_minute", sa.Integer()))
    op.add_column("runtime_settings", sa.Column("send_destination_rate_per_minute", sa.Integer()))
    op.add_column("runtime_settings", sa.Column("send_retry_base_delay_seconds", sa.Float()))
    op.add_column("runtime_settings", sa.Column("send_retry_max_delay_seconds", sa.Float()))
    op.add_column("runtime_settings", sa.Column("send_worker_lease_seconds", sa.Integer()))
    op.add_column("runtime_settings", sa.Column("send_stale_lock_grace_seconds", sa.Integer()))
    op.add_column("runtime_settings", sa.Column("send_dedupe_window_seconds", sa.Integer()))
    op.add_column(
        "send_history",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
    )
    op.add_column("send_history", sa.Column("locked_at", sa.DateTime(timezone=True)))
    op.add_column("send_history", sa.Column("locked_by", sa.String(length=200)))
    op.add_column("send_history", sa.Column("lock_expires_at", sa.DateTime(timezone=True)))
    op.add_column("send_history", sa.Column("last_attempt_at", sa.DateTime(timezone=True)))
    op.add_column("send_history", sa.Column("retry_after_seconds", sa.Integer()))
    op.add_column("send_history", sa.Column("last_error_kind", sa.String(length=80)))
    op.add_column("send_history", sa.Column("dedupe_window_key", sa.String(length=200)))
    op.create_index(
        "ix_send_history_due_priority",
        "send_history",
        ["status", "next_retry_at", "priority", "id"],
    )
    op.create_index(
        "ix_send_history_lock_expires",
        "send_history",
        ["status", "lock_expires_at"],
    )
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
    op.create_index(
        "ix_send_attempts_send_history_id",
        "send_attempts",
        ["send_history_id"],
    )


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
    op.drop_column("runtime_settings", "send_dedupe_window_seconds")
    op.drop_column("runtime_settings", "send_stale_lock_grace_seconds")
    op.drop_column("runtime_settings", "send_worker_lease_seconds")
    op.drop_column("runtime_settings", "send_retry_max_delay_seconds")
    op.drop_column("runtime_settings", "send_retry_base_delay_seconds")
    op.drop_column("runtime_settings", "send_destination_rate_per_minute")
    op.drop_column("runtime_settings", "send_chat_rate_per_minute")
    op.drop_column("runtime_settings", "send_bot_rate_per_minute")
    op.drop_column("runtime_settings", "send_global_rate_per_minute")
    op.drop_column("runtime_settings", "send_default_mode")
    op.drop_column("runtime_settings", "reliability_enabled")
