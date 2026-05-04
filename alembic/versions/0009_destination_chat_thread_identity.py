"""destination chat thread identity

Revision ID: 0009_destination_chat_thread_identity
Revises: 0008_telegram_ops_mcp_coverage
Create Date: 2026-05-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_destination_chat_thread_identity"
down_revision: str | None = "0008_telegram_ops_mcp_coverage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_destinations_bot_chat_thread",
        "destinations",
        [
            "bot_id",
            "chat_id",
            sa.text("coalesce(message_thread_id, -1)"),
        ],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_destinations_bot_chat_thread", table_name="destinations")
