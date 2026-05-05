from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from tg_bot_aggregator.core.orm import Base
from tg_bot_aggregator.core.time import utc_now


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

__all__ = ["AnalyticsRun", "AnalyticsSnapshot", "AnalyticsTarget", "MtprotoSession", "utc_now"]
