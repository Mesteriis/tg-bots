from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from tg_bot_aggregator.core.orm import Base
from tg_bot_aggregator.core.time import utc_now


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

__all__ = ["BackupRun", "utc_now"]
