from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReliabilitySummaryRead(BaseModel):
    status_counts: dict[str, int]
    stale_locks: int
    degraded: bool = False


class ReliabilityGraphNode(BaseModel):
    id: str
    label: str
    status: str
    count: int


class ReliabilityGraphEdge(BaseModel):
    source: str
    target: str
    status: str
    active: bool


class ReliabilityGraphRead(BaseModel):
    nodes: list[ReliabilityGraphNode]
    edges: list[ReliabilityGraphEdge]


class RateBucketRead(BaseModel):
    bucket_key: str
    limit: int
    used: int
    retry_after_seconds: int | None


class SendAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    send_history_id: int
    attempt_number: int
    worker_id: str | None
    started_at: datetime
    finished_at: datetime | None
    status: str
    telegram_error_code: str | None
    error_kind: str | None
    error_message: str | None
    retry_after_seconds: int | None
    latency_ms: int | None
    response_payload_json: dict[str, Any] | None


class BulkSendHistoryRequest(BaseModel):
    send_history_ids: list[int] = Field(min_length=1)


class BulkSendHistoryResult(BaseModel):
    changed: int
    skipped: int
