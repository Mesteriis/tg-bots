from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from tg_bot_aggregator.core.orm import Base
from tg_bot_aggregator.core.time import utc_now
from tg_bot_aggregator.domain.bots.models import Bot
from tg_bot_aggregator.domain.destinations.models import Destination
from tg_bot_aggregator.domain.templates.models import MessageTemplate


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

__all__ = [
    "Bot",
    "Destination",
    "MessageTemplate",
    "SendAttempt",
    "SendHistory",
    "SendProfile",
    "utc_now",
]
