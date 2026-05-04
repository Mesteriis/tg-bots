"""operations layer

Revision ID: 0006_operations_layer
Revises: 0005_workflow_layer
Create Date: 2026-05-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_operations_layer"
down_revision: str | None = "0005_workflow_layer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_bot_api_base_url", sa.String(length=500)),
        sa.Column("shared_media_root", sa.Text()),
        sa.Column("shared_media_require_mount", sa.Boolean()),
        sa.Column("max_local_file_bytes", sa.Integer()),
        sa.Column("send_retry_max_attempts", sa.Integer()),
        sa.Column("send_retry_delay_seconds", sa.Float()),
        sa.Column("protected_api_hosts_json", sa.JSON()),
        sa.Column("policy_enabled", sa.Boolean()),
        sa.Column("rate_limit_per_minute", sa.Integer()),
        sa.Column("quiet_hours_start", sa.String(length=5)),
        sa.Column("quiet_hours_end", sa.String(length=5)),
        sa.Column("callback_enabled", sa.Boolean()),
        sa.Column("callback_url", sa.Text()),
        sa.Column("backup_git_repo_url", sa.Text()),
        sa.Column("backup_git_branch", sa.String(length=200)),
        sa.Column("backup_git_path", sa.Text()),
        sa.Column("backup_include_secrets", sa.Boolean()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "backup_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="created"),
        sa.Column("items_exported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("backup_json", sa.JSON()),
        sa.Column("git_commit", sa.String(length=100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "runtime_advanced_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("settings_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "destination_health",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("destination_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_member_count", sa.Integer()),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("raw_chat_json", sa.JSON()),
        sa.ForeignKeyConstraint(["destination_id"], ["destinations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("destination_id", name="uq_destination_health_destination_id"),
    )
    op.create_table(
        "message_template_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("parse_mode", sa.String(length=40)),
        sa.Column("disable_web_page_preview", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["template_id"], ["message_templates.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_message_template_versions_template_number",
        ),
    )


def downgrade() -> None:
    op.drop_table("message_template_versions")
    op.drop_table("destination_health")
    op.drop_table("runtime_advanced_settings")
    op.drop_table("backup_runs")
    op.drop_table("runtime_settings")
