from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tg_bot_aggregator.core.orm import Base
from tg_bot_aggregator.core.time import utc_now

if TYPE_CHECKING:
    from tg_bot_aggregator.domain.bots.models import Bot


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

    bot: Mapped["Bot"] = relationship(back_populates="destinations")
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

__all__ = ["Destination", "DestinationHealth", "utc_now"]
