from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BotCreate(BaseModel):
    name: str | None = None
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


class DiagnosticBotSettingsUpdate(BaseModel):
    bot_id: int | None = None
    is_enabled: bool | None = None


class DiagnosticBotSettingsRead(BaseModel):
    bot_id: int | None
    bot_name: str | None
    bot_username: str | None
    is_enabled: bool
    last_update_id: int | None
    last_error: str | None
    updated_at: datetime | None


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scopes: list[Literal["read", "send", "mcp_admin", "tg_compat"]] = Field(
        default_factory=lambda: ["read", "send", "mcp_admin", "tg_compat"]
    )


class ApiTokenSessionRequest(BaseModel):
    token: str = Field(min_length=1)


class ApiTokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    token_prefix: str
    scopes_json: list[str] = Field(serialization_alias="scopes")
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiTokenCreated(ApiTokenRead):
    token: str


class McpToolRead(BaseModel):
    name: str
    title: str
    category: str
    risk: str
    enabled: bool


class McpSettingsRead(BaseModel):
    is_enabled: bool
    allow_legacy_sse: bool
    protected_hosts: list[str]
    transports: list[dict[str, str | bool]]
    tools: list[McpToolRead]
    tools_by_name: dict[str, McpToolRead]


class McpSettingsUpdate(BaseModel):
    is_enabled: bool | None = None
    allow_legacy_sse: bool | None = None
    enabled_tools: list[str] | None = None


class DestinationCreate(BaseModel):
    bot_id: int
    kind: Literal["private", "group", "supergroup", "channel", "forum_topic"]
    chat_id: str
    message_thread_id: int | None = None
    alias: str | None = None
    title: str | None = None
    username: str | None = None
    is_active: bool = True


class DestinationUpdate(BaseModel):
    kind: Literal["private", "group", "supergroup", "channel", "forum_topic"] | None = None
    chat_id: str | None = None
    message_thread_id: int | None = None
    alias: str | None = None
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
    alias: str | None
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
    destination_alias: str | None = None
    chat_id: str | None = None
    tag: str | None = None
    parse_mode: str | None = None
    disable_web_page_preview: bool | None = None
    message_thread_id: int | None = None
    send_mode: Literal["sync", "queued"] = "sync"


class SendTemplateRequest(BaseModel):
    bot_id: int
    tag: str
    destination_id: int | None = None
    destination_alias: str | None = None
    chat_id: str | None = None
    message_thread_id: int | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    send_mode: Literal["sync", "queued"] = "sync"


class SendFileRequest(BaseModel):
    bot_id: int
    media_type: Literal["document", "video"]
    file_relative_path: str
    destination_id: int | None = None
    destination_alias: str | None = None
    chat_id: str | None = None
    caption: str | None = None
    tag: str | None = None
    parse_mode: str | None = None
    message_thread_id: int | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    send_mode: Literal["sync", "queued"] = "sync"


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
    send_mode: str
    idempotency_key: str | None
    attempt_count: int
    queued_task_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    sent_at: datetime | None
    failed_at: datetime | None


class EventEnvelope(BaseModel):
    schema_version: str = "v1"
    event_type: str
    data: dict[str, Any] = Field(default_factory=dict)


class SendDryRunRead(BaseModel):
    ok: bool = True
    method: str
    bot_id: int
    chat_id: str
    message_thread_id: int | None = None
    destination_id: int | None = None
    payload: dict[str, Any]


class DestinationCheckRead(BaseModel):
    destination_id: int
    ok: bool
    chat: dict[str, Any] | None = None
    member_count: int | None = None
    warnings: list[str] = Field(default_factory=list)


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    source: str
    action: str
    status: str
    api_token_id: int | None
    host: str | None
    path: str | None
    method: str | None
    entity_type: str | None
    entity_id: str | None
    message: str | None
    metadata_json: dict[str, Any] | None


class BotDiscoverySettingsUpdate(BaseModel):
    is_enabled: bool | None = None


class BotDiscoverySettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bot_id: int
    is_enabled: bool
    last_update_id: int | None
    last_error: str | None
    updated_at: datetime


class BotDiscoveryEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bot_id: int
    update_id: int
    chat_id: str
    kind: str
    old_status: str | None
    new_status: str | None
    raw_update_json: dict[str, Any] | None
    created_at: datetime


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
