from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tg_bot_aggregator.core.orm import Base
from tg_bot_aggregator.core.time import utc_now

if TYPE_CHECKING:
    from tg_bot_aggregator.domain.destinations.models import Destination
    from tg_bot_aggregator.domain.diagnostics.models import DiagnosticBotSettings


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

    destinations: Mapped[list[Destination]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )
    diagnostic_settings: Mapped[DiagnosticBotSettings | None] = relationship(
        back_populates="bot"
    )

__all__ = ["Bot", "utc_now"]
