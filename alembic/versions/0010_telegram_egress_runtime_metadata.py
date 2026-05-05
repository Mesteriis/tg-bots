"""telegram egress runtime metadata

Revision ID: 0010_telegram_egress_runtime_metadata
Revises: 0009_destination_chat_thread_identity
Create Date: 2026-05-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_telegram_egress_runtime_metadata"
down_revision: str | None = "0009_destination_chat_thread_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runtime_settings",
        sa.Column("telegram_egress_mode", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "runtime_settings",
        sa.Column("telegram_egress_enabled", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "runtime_settings",
        sa.Column("telegram_egress_provider", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "runtime_settings",
        sa.Column("telegram_egress_last_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "runtime_settings",
        sa.Column("telegram_egress_last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "runtime_settings",
        sa.Column("telegram_egress_connected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "runtime_settings",
        sa.Column(
            "telegram_egress_last_handshake_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "runtime_settings",
        sa.Column("telegram_egress_last_egress_ip", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("runtime_settings", "telegram_egress_last_egress_ip")
    op.drop_column("runtime_settings", "telegram_egress_last_handshake_at")
    op.drop_column("runtime_settings", "telegram_egress_connected_at")
    op.drop_column("runtime_settings", "telegram_egress_last_error")
    op.drop_column("runtime_settings", "telegram_egress_last_status")
    op.drop_column("runtime_settings", "telegram_egress_provider")
    op.drop_column("runtime_settings", "telegram_egress_enabled")
    op.drop_column("runtime_settings", "telegram_egress_mode")
