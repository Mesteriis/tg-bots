from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from tg_bot_aggregator.core.orm import Base
from tg_bot_aggregator.core.time import utc_now


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
    telegram_egress_mode: Mapped[str | None] = mapped_column(String(32))
    telegram_egress_enabled: Mapped[bool | None] = mapped_column(Boolean)
    telegram_egress_provider: Mapped[str | None] = mapped_column(String(32))
    telegram_egress_last_status: Mapped[str | None] = mapped_column(String(32))
    telegram_egress_last_error: Mapped[str | None] = mapped_column(Text)
    telegram_egress_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_egress_last_handshake_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    telegram_egress_last_egress_ip: Mapped[str | None] = mapped_column(String(128))
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

__all__ = ["RuntimeAdvancedSettings", "RuntimeSettings", "utc_now"]
