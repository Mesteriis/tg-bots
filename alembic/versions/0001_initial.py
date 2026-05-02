"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column("username", sa.String(length=200)),
        sa.Column("telegram_bot_id", sa.Integer()),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "message_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tag", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("parse_mode", sa.String(length=40)),
        sa.Column("disable_web_page_preview", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tag", name="uq_message_templates_tag"),
    )
    op.create_table(
        "mtproto_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_name", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=80)),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("last_connected_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
    )
    op.create_table(
        "analytics_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("peer_ref", sa.String(length=300), nullable=False),
        sa.Column("title", sa.String(length=300)),
        sa.Column("username", sa.String(length=200)),
        sa.Column("kind", sa.String(length=40)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("refresh_interval_seconds", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("last_snapshot_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "destinations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bot_id", sa.Integer(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("chat_id", sa.String(length=200), nullable=False),
        sa.Column("message_thread_id", sa.Integer()),
        sa.Column("title", sa.String(length=300)),
        sa.Column("username", sa.String(length=200)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "analytics_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(length=200)),
        sa.Column(
            "target_id", sa.Integer(), sa.ForeignKey("analytics_targets.id", ondelete="SET NULL")
        ),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.Column("snapshots_created", sa.Integer(), nullable=False),
    )
    op.create_table(
        "analytics_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "target_id", sa.Integer(), sa.ForeignKey("analytics_targets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True)),
        sa.Column("participants_count", sa.Integer()),
        sa.Column("recent_messages_count", sa.Integer()),
        sa.Column("recent_views_total", sa.Integer()),
        sa.Column("recent_forwards_total", sa.Integer()),
        sa.Column("recent_replies_total", sa.Integer()),
        sa.Column("raw_metrics_json", sa.JSON()),
    )
    op.create_table(
        "send_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bot_id", sa.Integer(), sa.ForeignKey("bots.id", ondelete="SET NULL")),
        sa.Column(
            "destination_id", sa.Integer(), sa.ForeignKey("destinations.id", ondelete="SET NULL")
        ),
        sa.Column("chat_id", sa.String(length=200), nullable=False),
        sa.Column("message_thread_id", sa.Integer()),
        sa.Column("tag", sa.String(length=100)),
        sa.Column("text", sa.Text()),
        sa.Column("media_type", sa.String(length=40), nullable=False),
        sa.Column("file_relative_path", sa.Text()),
        sa.Column("file_size_bytes", sa.Integer()),
        sa.Column("telegram_message_id", sa.Integer()),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("request_payload_json", sa.JSON()),
        sa.Column("response_payload_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("send_history")
    op.drop_table("analytics_snapshots")
    op.drop_table("analytics_runs")
    op.drop_table("destinations")
    op.drop_table("analytics_targets")
    op.drop_table("mtproto_sessions")
    op.drop_table("message_templates")
    op.drop_table("bots")

