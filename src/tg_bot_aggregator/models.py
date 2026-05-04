from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from tg_bot_aggregator.mcp_catalog import MCP_DEFAULT_ENABLED_TOOL_NAMES


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    token: Mapped[str] = mapped_column(String(512), nullable=False)
    username: Mapped[str | None] = mapped_column(String(200))
    telegram_bot_id: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    destinations: Mapped[list["Destination"]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )
    diagnostic_settings: Mapped["DiagnosticBotSettings | None"] = relationship(
        back_populates="bot",
    )


class DiagnosticBotSettings(Base):
    __tablename__ = "diagnostic_bot_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    bot_id: Mapped[int | None] = mapped_column(ForeignKey("bots.id", ondelete="SET NULL"))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_update_id: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    bot: Mapped[Bot | None] = relationship(back_populates="diagnostic_settings")


class DiagnosticUpdate(Base):
    __tablename__ = "diagnostic_updates"
    __table_args__ = (UniqueConstraint("update_id", name="uq_diagnostic_updates_update_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    update_id: Mapped[int] = mapped_column(Integer, nullable=False)
    update_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    chat_id: Mapped[str | None] = mapped_column(String(200))
    chat_type: Mapped[str | None] = mapped_column(String(40))
    chat_title: Mapped[str | None] = mapped_column(String(300))
    chat_username: Mapped[str | None] = mapped_column(String(200))
    message_id: Mapped[int | None] = mapped_column(Integer)
    message_thread_id: Mapped[int | None] = mapped_column(Integer)
    is_topic_message: Mapped[bool | None] = mapped_column(Boolean)
    sender_id: Mapped[int | None] = mapped_column(Integer)
    sender_username: Mapped[str | None] = mapped_column(String(200))
    text_preview: Mapped[str | None] = mapped_column(Text)
    raw_update_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    token_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    scopes_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=lambda: ["read", "send", "mcp_admin", "tg_compat", "ops_admin"],
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class McpSettings(Base):
    __tablename__ = "mcp_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enabled_tools_json: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: list(MCP_DEFAULT_ENABLED_TOOL_NAMES), nullable=False
    )
    allow_legacy_sse: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class RuntimeSettings(Base):
    __tablename__ = "runtime_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    telegram_bot_api_base_url: Mapped[str | None] = mapped_column(String(500))
    shared_media_root: Mapped[str | None] = mapped_column(Text)
    shared_media_require_mount: Mapped[bool | None] = mapped_column(Boolean)
    max_local_file_bytes: Mapped[int | None] = mapped_column(Integer)
    send_retry_max_attempts: Mapped[int | None] = mapped_column(Integer)
    send_retry_delay_seconds: Mapped[float | None] = mapped_column(Float)
    reliability_enabled: Mapped[bool | None] = mapped_column(Boolean)
    send_default_mode: Mapped[str | None] = mapped_column(String(40))
    send_global_rate_per_minute: Mapped[int | None] = mapped_column(Integer)
    send_bot_rate_per_minute: Mapped[int | None] = mapped_column(Integer)
    send_chat_rate_per_minute: Mapped[int | None] = mapped_column(Integer)
    send_destination_rate_per_minute: Mapped[int | None] = mapped_column(Integer)
    send_retry_base_delay_seconds: Mapped[float | None] = mapped_column(Float)
    send_retry_max_delay_seconds: Mapped[float | None] = mapped_column(Float)
    send_worker_lease_seconds: Mapped[int | None] = mapped_column(Integer)
    send_stale_lock_grace_seconds: Mapped[int | None] = mapped_column(Integer)
    send_dedupe_window_seconds: Mapped[int | None] = mapped_column(Integer)
    protected_api_hosts_json: Mapped[list[str] | None] = mapped_column(JSON)
    policy_enabled: Mapped[bool | None] = mapped_column(Boolean)
    rate_limit_per_minute: Mapped[int | None] = mapped_column(Integer)
    quiet_hours_start: Mapped[str | None] = mapped_column(String(5))
    quiet_hours_end: Mapped[str | None] = mapped_column(String(5))
    callback_enabled: Mapped[bool | None] = mapped_column(Boolean)
    callback_url: Mapped[str | None] = mapped_column(Text)
    backup_git_repo_url: Mapped[str | None] = mapped_column(Text)
    backup_git_branch: Mapped[str | None] = mapped_column(String(200))
    backup_git_path: Mapped[str | None] = mapped_column(Text)
    backup_include_secrets: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class RuntimeAdvancedSettings(Base):
    __tablename__ = "runtime_advanced_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class BackupRun(Base):
    __tablename__ = "backup_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(40), default="created", nullable=False)
    items_exported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    backup_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    git_commit: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Destination(Base):
    __tablename__ = "destinations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(200), nullable=False)
    message_thread_id: Mapped[int | None] = mapped_column(Integer)
    alias: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(String(300))
    username: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    bot: Mapped[Bot] = relationship(back_populates="destinations")
    __table_args__ = (
        UniqueConstraint("bot_id", "alias", name="uq_destinations_bot_alias"),
        Index(
            "uq_destinations_bot_chat_thread",
            "bot_id",
            "chat_id",
            func.coalesce(message_thread_id, -1),
            unique=True,
        ),
    )


class DestinationHealth(Base):
    __tablename__ = "destination_health"
    __table_args__ = (
        UniqueConstraint("destination_id", name="uq_destination_health_destination_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    destination_id: Mapped[int] = mapped_column(
        ForeignKey("destinations.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_member_count: Mapped[int | None] = mapped_column(Integer)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    raw_chat_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class MessageTemplate(Base):
    __tablename__ = "message_templates"
    __table_args__ = (UniqueConstraint("tag", name="uq_message_templates_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tag: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    parse_mode: Mapped[str | None] = mapped_column(String(40))
    disable_web_page_preview: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class MessageTemplateVersion(Base):
    __tablename__ = "message_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_message_template_versions_template_number",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("message_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    parse_mode: Mapped[str | None] = mapped_column(String(40))
    disable_web_page_preview: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SendProfile(Base):
    __tablename__ = "send_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    send_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    destination_id: Mapped[int | None] = mapped_column(
        ForeignKey("destinations.id", ondelete="SET NULL")
    )
    destination_alias: Mapped[str | None] = mapped_column(String(100))
    chat_id: Mapped[str | None] = mapped_column(String(200))
    message_thread_id: Mapped[int | None] = mapped_column(Integer)
    template_tag: Mapped[str | None] = mapped_column(String(100))
    text: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(40), default="none", nullable=False)
    file_relative_path: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    parse_mode: Mapped[str | None] = mapped_column(String(40))
    disable_web_page_preview: Mapped[bool | None] = mapped_column(Boolean)
    variables_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SendBatch(Base):
    __tablename__ = "send_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    send_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    template_tag: Mapped[str | None] = mapped_column(String(100))
    text: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(40), default="none", nullable=False)
    file_relative_path: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    parse_mode: Mapped[str | None] = mapped_column(String(40))
    disable_web_page_preview: Mapped[bool | None] = mapped_column(Boolean)
    variables_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SendBatchItem(Base):
    __tablename__ = "send_batch_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("send_batches.id", ondelete="CASCADE"), nullable=False
    )
    destination_id: Mapped[int | None] = mapped_column(
        ForeignKey("destinations.id", ondelete="SET NULL")
    )
    chat_id: Mapped[str] = mapped_column(String(200), nullable=False)
    message_thread_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    send_history_id: Mapped[int | None] = mapped_column(
        ForeignKey("send_history.id", ondelete="SET NULL")
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SendHistory(Base):
    __tablename__ = "send_history"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_send_history_idempotency_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="SET NULL"), nullable=True)
    destination_id: Mapped[int | None] = mapped_column(
        ForeignKey("destinations.id", ondelete="SET NULL")
    )
    chat_id: Mapped[str] = mapped_column(String(200), nullable=False)
    message_thread_id: Mapped[int | None] = mapped_column(Integer)
    tag: Mapped[str | None] = mapped_column(String(100))
    text: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(40), default="none", nullable=False)
    file_relative_path: Mapped[str | None] = mapped_column(Text)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="created", nullable=False)
    send_mode: Mapped[str] = mapped_column(String(40), default="sync", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    idempotency_fingerprint: Mapped[str | None] = mapped_column(String(128))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    queued_task_id: Mapped[str | None] = mapped_column(String(200))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(200))
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer)
    last_error_kind: Mapped[str | None] = mapped_column(String(80))
    dedupe_window_key: Mapped[str | None] = mapped_column(String(200))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    request_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    response_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    api_token_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_tokens.id", ondelete="SET NULL")
    )
    host: Mapped[str | None] = mapped_column(String(300))
    path: Mapped[str | None] = mapped_column(String(500))
    method: Mapped[str | None] = mapped_column(String(20))
    entity_type: Mapped[str | None] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(120))
    request_id: Mapped[str | None] = mapped_column(String(120))
    message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class BotDiscoverySettings(Base):
    __tablename__ = "bot_discovery_settings"
    __table_args__ = (UniqueConstraint("bot_id", name="uq_bot_discovery_settings_bot_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_update_id: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class BotDiscoveryEvent(Base):
    __tablename__ = "bot_discovery_events"
    __table_args__ = (
        UniqueConstraint("bot_id", "update_id", name="uq_bot_discovery_event_update"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    update_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chat_id: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(40))
    new_status: Mapped[str | None] = mapped_column(String(40))
    raw_update_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OpsFact(Base):
    __tablename__ = "ops_facts"
    __table_args__ = (UniqueConstraint("identity_key", name="uq_ops_fact_identity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_key: Mapped[str] = mapped_column(String(128), nullable=False)
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


class OpsRecommendation(Base):
    __tablename__ = "ops_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recommendation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="open", nullable=False)
    risk: Mapped[str] = mapped_column(String(40), nullable=False)
    bot_id: Mapped[int | None] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    destination_id: Mapped[int | None] = mapped_column(
        ForeignKey("destinations.id", ondelete="SET NULL")
    )
    fact_ids_json: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    diff_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    action_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OpsAutomationRule(Base):
    __tablename__ = "ops_automation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    mode: Mapped[str] = mapped_column(String(40), default="suggest_only", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    risk_limit: Mapped[str] = mapped_column(String(40), default="low", nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_result: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class OpsActionRun(Base):
    __tablename__ = "ops_action_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recommendation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ops_recommendations.id", ondelete="SET NULL")
    )
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("ops_automation_rules.id", ondelete="SET NULL")
    )
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    preview_diff_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    request_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    rollback_hint: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class McpCoverageSnapshot(Base):
    __tablename__ = "mcp_coverage_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    matrix_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    missing_required_tools_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    warnings_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class MtprotoSession(Base):
    __tablename__ = "mtproto_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_name: Mapped[str] = mapped_column(String(200), default="default", nullable=False)
    phone: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="missing", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class AnalyticsTarget(Base):
    __tablename__ = "analytics_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    peer_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    username: Mapped[str | None] = mapped_column(String(200))
    kind: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    refresh_interval_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    last_snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[int] = mapped_column(
        ForeignKey("analytics_targets.id", ondelete="CASCADE"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    participants_count: Mapped[int | None] = mapped_column(Integer)
    recent_messages_count: Mapped[int | None] = mapped_column(Integer)
    recent_views_total: Mapped[int | None] = mapped_column(Integer)
    recent_forwards_total: Mapped[int | None] = mapped_column(Integer)
    recent_replies_total: Mapped[int | None] = mapped_column(Integer)
    raw_metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class AnalyticsRun(Base):
    __tablename__ = "analytics_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str | None] = mapped_column(String(200))
    target_id: Mapped[int | None] = mapped_column(
        ForeignKey("analytics_targets.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    snapshots_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
