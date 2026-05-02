from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BotCreate(BaseModel):
    name: str
    token: str
    description: str | None = None
    is_active: bool = True


class BotUpdate(BaseModel):
    name: str | None = None
    token: str | None = None
    description: str | None = None
    is_active: bool | None = None


class BotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    username: str | None
    telegram_bot_id: int | None
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None


class DestinationCreate(BaseModel):
    bot_id: int
    kind: Literal["private", "group", "supergroup", "channel", "forum_topic"]
    chat_id: str
    message_thread_id: int | None = None
    title: str | None = None
    username: str | None = None
    is_active: bool = True


class DestinationUpdate(BaseModel):
    kind: Literal["private", "group", "supergroup", "channel", "forum_topic"] | None = None
    chat_id: str | None = None
    message_thread_id: int | None = None
    title: str | None = None
    username: str | None = None
    is_active: bool | None = None


class DestinationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bot_id: int
    kind: str
    chat_id: str
    message_thread_id: int | None
    title: str | None
    username: str | None
    is_active: bool


class TemplateCreate(BaseModel):
    tag: str
    title: str
    text: str
    parse_mode: str | None = None
    disable_web_page_preview: bool = False


class TemplateUpdate(BaseModel):
    title: str | None = None
    text: str | None = None
    parse_mode: str | None = None
    disable_web_page_preview: bool | None = None


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tag: str
    title: str
    text: str
    parse_mode: str | None
    disable_web_page_preview: bool


class SendTextRequest(BaseModel):
    bot_id: int
    text: str
    destination_id: int | None = None
    chat_id: str | None = None
    tag: str | None = None
    parse_mode: str | None = None
    disable_web_page_preview: bool | None = None
    message_thread_id: int | None = None


class SendTemplateRequest(BaseModel):
    bot_id: int
    tag: str
    destination_id: int | None = None
    chat_id: str | None = None
    message_thread_id: int | None = None


class SendFileRequest(BaseModel):
    bot_id: int
    media_type: Literal["document", "video"]
    file_relative_path: str
    destination_id: int | None = None
    chat_id: str | None = None
    caption: str | None = None
    tag: str | None = None
    parse_mode: str | None = None
    message_thread_id: int | None = None


class SendHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bot_id: int | None
    destination_id: int | None
    chat_id: str
    message_thread_id: int | None
    tag: str | None
    text: str | None
    media_type: str
    file_relative_path: str | None
    file_size_bytes: int | None
    telegram_message_id: int | None
    status: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    sent_at: datetime | None
    failed_at: datetime | None


class EventEnvelope(BaseModel):
    schema_version: str = "v1"
    event_type: str
    data: dict[str, Any] = Field(default_factory=dict)


class MtprotoLoginStartRequest(BaseModel):
    phone: str


class MtprotoCodeRequest(BaseModel):
    phone: str
    code: str


class MtprotoPasswordRequest(BaseModel):
    password: str


class MtprotoStatusRead(BaseModel):
    status: str
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
