"""workflow layer

Revision ID: 0005_workflow_layer
Revises: 0004_ops_automation
Create Date: 2026-05-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_workflow_layer"
down_revision: str | None = "0004_ops_automation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "send_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "bot_id",
            sa.Integer(),
            sa.ForeignKey("bots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("send_kind", sa.String(length=40), nullable=False),
        sa.Column(
            "destination_id",
            sa.Integer(),
            sa.ForeignKey("destinations.id", ondelete="SET NULL"),
        ),
        sa.Column("destination_alias", sa.String(length=100)),
        sa.Column("chat_id", sa.String(length=200)),
        sa.Column("message_thread_id", sa.Integer()),
        sa.Column("template_tag", sa.String(length=100)),
        sa.Column("text", sa.Text()),
        sa.Column("media_type", sa.String(length=40), nullable=False, server_default="none"),
        sa.Column("file_relative_path", sa.Text()),
        sa.Column("caption", sa.Text()),
        sa.Column("parse_mode", sa.String(length=40)),
        sa.Column("disable_web_page_preview", sa.Boolean()),
        sa.Column("variables_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "send_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "bot_id",
            sa.Integer(),
            sa.ForeignKey("bots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("send_kind", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("template_tag", sa.String(length=100)),
        sa.Column("text", sa.Text()),
        sa.Column("media_type", sa.String(length=40), nullable=False, server_default="none"),
        sa.Column("file_relative_path", sa.Text()),
        sa.Column("caption", sa.Text()),
        sa.Column("parse_mode", sa.String(length=40)),
        sa.Column("disable_web_page_preview", sa.Boolean()),
        sa.Column("variables_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("queued_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "send_batch_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Integer(),
            sa.ForeignKey("send_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "destination_id",
            sa.Integer(),
            sa.ForeignKey("destinations.id", ondelete="SET NULL"),
        ),
        sa.Column("chat_id", sa.String(length=200), nullable=False),
        sa.Column("message_thread_id", sa.Integer()),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column(
            "send_history_id",
            sa.Integer(),
            sa.ForeignKey("send_history.id", ondelete="SET NULL"),
        ),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "diagnostic_updates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("update_id", sa.Integer(), nullable=False),
        sa.Column("update_kind", sa.String(length=60), nullable=False),
        sa.Column("chat_id", sa.String(length=200)),
        sa.Column("chat_type", sa.String(length=40)),
        sa.Column("chat_title", sa.String(length=300)),
        sa.Column("chat_username", sa.String(length=200)),
        sa.Column("message_id", sa.Integer()),
        sa.Column("message_thread_id", sa.Integer()),
        sa.Column("is_topic_message", sa.Boolean()),
        sa.Column("sender_id", sa.Integer()),
        sa.Column("sender_username", sa.String(length=200)),
        sa.Column("text_preview", sa.Text()),
        sa.Column("raw_update_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("update_id", name="uq_diagnostic_updates_update_id"),
    )


def downgrade() -> None:
    op.drop_table("diagnostic_updates")
    op.drop_table("send_batch_items")
    op.drop_table("send_batches")
    op.drop_table("send_profiles")
