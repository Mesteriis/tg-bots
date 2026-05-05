from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class MtprotoLoginStartRequest(BaseModel):
    phone: str


class MtprotoCodeRequest(BaseModel):
    phone: str
    code: str


class MtprotoPasswordRequest(BaseModel):
    password: str


class MtprotoStatusRead(BaseModel):
    status: str
    configured: bool = False
    api_credentials_missing: bool = False
    phone: str | None = None
    last_error: str | None = None


class AnalyticsTargetCreate(BaseModel):
    peer_ref: str
    title: str | None = None
    username: str | None = None
    kind: str | None = None
    is_active: bool = True
    refresh_interval_seconds: int | None = None


class AnalyticsTargetUpdate(BaseModel):
    peer_ref: str | None = None
    title: str | None = None
    username: str | None = None
    kind: str | None = None
    is_active: bool | None = None
    refresh_interval_seconds: int | None = None


class AnalyticsTargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    peer_ref: str
    title: str | None
    username: str | None
    kind: str | None
    is_active: bool
    refresh_interval_seconds: int | None
    last_snapshot_at: datetime | None


class AnalyticsRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: str | None
    target_id: int | None
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    snapshots_created: int


class AnalyticsSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_id: int
    captured_at: datetime
    participants_count: int | None
    recent_messages_count: int | None
    recent_views_total: int | None
    recent_forwards_total: int | None
    recent_replies_total: int | None
    raw_metrics_json: dict[str, Any] | None


class AnalyticsRefreshRequest(BaseModel):
    target_id: int | None = None


class AnalyticsRefreshResponse(BaseModel):
    run_id: int
    status: str
    task_id: str | None = None
