from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from tg_bot_aggregator.core.orm import Base
from tg_bot_aggregator.core.time import utc_now
from tg_bot_aggregator.domain.mcp.catalog import MCP_DEFAULT_ENABLED_TOOL_NAMES


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


class McpCoverageSnapshot(Base):
    __tablename__ = "mcp_coverage_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    matrix_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    missing_required_tools_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    warnings_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

__all__ = ["McpCoverageSnapshot", "McpSettings", "utc_now"]
