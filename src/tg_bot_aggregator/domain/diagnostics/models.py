from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tg_bot_aggregator.core.orm import Base
from tg_bot_aggregator.core.time import utc_now

if TYPE_CHECKING:
    from tg_bot_aggregator.domain.bots.models import Bot


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

__all__ = ["DiagnosticBotSettings", "DiagnosticUpdate", "utc_now"]
