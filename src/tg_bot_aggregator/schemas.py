from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ApiScope = Literal["read", "send", "mcp_admin", "tg_compat", "ops_admin"]


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


class DiagnosticUpdateCreate(BaseModel):
    update_id: int
    update_kind: str = "message"
    chat_id: str | None = None
    chat_type: str | None = None
    chat_title: str | None = None
    chat_username: str | None = None
    message_id: int | None = None
    message_thread_id: int | None = None
    is_topic_message: bool | None = None
    sender_id: int | None = None
    sender_username: str | None = None
    text_preview: str | None = None
    raw_update: dict[str, Any] | None = None


class DiagnosticDestinationCreate(BaseModel):
    bot_id: int
    alias: str | None = None


class DiagnosticUpdateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    update_id: int
    update_kind: str
    chat_id: str | None
    chat_type: str | None
    chat_title: str | None
    chat_username: str | None
    message_id: int | None
    message_thread_id: int | None
    is_topic_message: bool | None
    sender_id: int | None
    sender_username: str | None
    text_preview: str | None
    raw_update_json: dict[str, Any] | None
    created_at: datetime


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scopes: list[ApiScope] = Field(
        default_factory=lambda: ["read", "send", "mcp_admin", "tg_compat", "ops_admin"]
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


class McpTransportInfo(BaseModel):
    name: str
    path: str
    enabled: bool


class McpConnectionInfoRead(BaseModel):
    streamable_http: McpTransportInfo
    legacy_sse: McpTransportInfo
    legacy_messages: McpTransportInfo
    protected_hosts: list[str]
    required_headers: list[str]
    enabled_tools: list[str]
    local_examples: dict[str, str]
    protected_host_examples: dict[str, str]


class OpsFactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fact_type: str
    bot_id: int | None
    chat_id: str | None
    message_thread_id: int | None
    source: str
    title: str | None
    username: str | None
    kind: str | None
    status: str
    confidence: int
    observed_at: datetime
    expires_at: datetime | None
    payload_json: dict[str, Any] | None


class OpsRecommendationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recommendation_type: str
    status: str
    risk: str
    bot_id: int | None
    destination_id: int | None
    fact_ids_json: list[int]
    title: str
    reason: str
    diff_json: dict[str, Any]
    action_payload_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    applied_at: datetime | None
    dismissed_at: datetime | None


class OpsActionPreviewRead(BaseModel):
    recommendation_id: int
    diff: dict[str, Any]
    run_id: int


class OpsActionApplyRead(BaseModel):
    recommendation_id: int
    status: str
    destination_id: int | None = None
    run_id: int | None = None


class OpsRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_key: str
    title: str
    mode: str
    is_enabled: bool
    is_paused: bool
    risk_limit: str
    config_json: dict[str, Any]
    last_run_at: datetime | None
    last_result: str | None
    created_at: datetime
    updated_at: datetime


class OpsRuleUpdate(BaseModel):
    mode: Literal["suggest_only", "auto_apply"] | None = None
    is_enabled: bool | None = None
    is_paused: bool | None = None
    risk_limit: Literal["low", "medium", "high"] | None = None
    config_json: dict[str, Any] | None = None


class OpsActionRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recommendation_id: int | None
    rule_id: int | None
    action_type: str
    source: str
    actor: str | None
    status: str
    preview_diff_json: dict[str, Any] | None
    request_payload_json: dict[str, Any] | None
    result_json: dict[str, Any] | None
    error_message: str | None
    rollback_hint: str | None
    created_at: datetime
    finished_at: datetime | None


class McpCoverageRead(BaseModel):
    rows: list[dict[str, Any]]
    missing_enabled_tools: list[str]
    missing_catalog_tools: list[str]


class McpSettingsUpdate(BaseModel):
    is_enabled: bool | None = None
    allow_legacy_sse: bool | None = None
    enabled_tools: list[str] | None = None


class RuntimeSettingsUpdate(BaseModel):
    app_host: str | None = None
    app_port: int | None = Field(default=None, ge=1, le=65535)
    database_url: str | None = None
    redis_url: str | None = None
    telegram_api_id: str | None = None
    telegram_api_hash: str | None = None
    telegram_bot_api_base_url: str | None = None
    cors_allowed_origins: list[str] | None = None
    mcp_allowed_origins: list[str] | None = None
    shared_media_root: str | None = None
    shared_media_require_mount: bool | None = None
    max_local_file_bytes: int | None = Field(default=None, ge=1)
    telethon_session_dir: str | None = None
    diagnostic_poll_timeout_seconds: int | None = Field(default=None, ge=1)
    diagnostic_retry_delay_seconds: float | None = Field(default=None, ge=0)
    discovery_poll_timeout_seconds: int | None = Field(default=None, ge=1)
    discovery_retry_delay_seconds: float | None = Field(default=None, ge=0)
    send_retry_max_attempts: int | None = Field(default=None, ge=1)
    send_retry_delay_seconds: float | None = Field(default=None, ge=0)
    reliability_enabled: bool | None = None
    send_default_mode: Literal["sync", "queued", "auto"] | None = None
    send_global_rate_per_minute: int | None = Field(default=None, ge=1)
    send_bot_rate_per_minute: int | None = Field(default=None, ge=1)
    send_chat_rate_per_minute: int | None = Field(default=None, ge=1)
    send_destination_rate_per_minute: int | None = Field(default=None, ge=1)
    send_retry_base_delay_seconds: float | None = Field(default=None, ge=0)
    send_retry_max_delay_seconds: float | None = Field(default=None, ge=0)
    send_worker_lease_seconds: int | None = Field(default=None, ge=1)
    send_stale_lock_grace_seconds: int | None = Field(default=None, ge=1)
    send_dedupe_window_seconds: int | None = Field(default=None, ge=1)
    protected_api_hosts: list[str] | None = None
    policy_enabled: bool | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1)
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    callback_enabled: bool | None = None
    callback_url: str | None = None
    backup_git_repo_url: str | None = None
    backup_git_branch: str | None = None
    backup_git_path: str | None = None
    backup_git_service: Literal["auto", "github", "gitea"] | None = None
    backup_git_auth_method: Literal["none", "token"] | None = None
    backup_git_api_base_url: str | None = None
    backup_git_api_token: str | None = None
    backup_include_secrets: bool | None = None
    backup_schedule_enabled: bool | None = None
    backup_schedule_interval_seconds: int | None = Field(default=None, ge=60)
    backup_schedule_push_to_git: bool | None = None


class RuntimeSettingsRead(BaseModel):
    app_host: str
    app_port: int
    database_url: str
    redis_url: str
    telegram_api_id: str | None
    telegram_api_hash: str | None
    telegram_bot_api_base_url: str
    cors_allowed_origins: list[str]
    mcp_allowed_origins: list[str]
    shared_media_root: str
    shared_media_require_mount: bool
    max_local_file_bytes: int
    telethon_session_dir: str
    diagnostic_poll_timeout_seconds: int
    diagnostic_retry_delay_seconds: float
    discovery_poll_timeout_seconds: int
    discovery_retry_delay_seconds: float
    send_retry_max_attempts: int
    send_retry_delay_seconds: float
    reliability_enabled: bool
    send_default_mode: Literal["sync", "queued", "auto"]
    send_global_rate_per_minute: int | None
    send_bot_rate_per_minute: int | None
    send_chat_rate_per_minute: int | None
    send_destination_rate_per_minute: int | None
    send_retry_base_delay_seconds: float
    send_retry_max_delay_seconds: float
    send_worker_lease_seconds: int
    send_stale_lock_grace_seconds: int
    send_dedupe_window_seconds: int | None
    protected_api_hosts: list[str]
    policy_enabled: bool
    rate_limit_per_minute: int | None
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    callback_enabled: bool
    callback_url: str | None
    backup_git_repo_url: str | None
    backup_git_branch: str
    backup_git_path: str
    backup_git_service: Literal["auto", "github", "gitea"]
    backup_git_auth_method: Literal["none", "token"]
    backup_git_api_base_url: str | None
    backup_git_api_token: str | None
    backup_include_secrets: bool
    backup_schedule_enabled: bool
    backup_schedule_interval_seconds: int
    backup_schedule_push_to_git: bool


class BackupRepositoryPrivacyRead(BaseModel):
    service: str | None
    auth_method: str | None
    host: str | None
    owner: str | None
    repo: str | None
    api_url: str | None
    is_private: bool | None
    verified: bool
    message: str


class BackupDiffSectionRead(BaseModel):
    section: str
    before_count: int
    after_count: int
    changed: bool
    row_changes: int


class BackupRowDiffRead(BaseModel):
    section: str
    key: str
    action: Literal["added", "removed", "changed"]
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class BackupDiffRead(BaseModel):
    base_run_id: int | None
    changed_sections: int
    sections: list[BackupDiffSectionRead]
    sections_by_name: dict[str, BackupDiffSectionRead]
    rows: list[BackupRowDiffRead]


class BackupPreflightCheckRead(BaseModel):
    name: str
    status: Literal["ok", "warning", "error", "skipped"]
    message: str


class BackupPreflightRead(BaseModel):
    ok: bool
    include_secrets: bool
    requested_include_secrets: bool
    push_to_git: bool
    repo: BackupRepositoryPrivacyRead
    diff: BackupDiffRead
    checks: list[BackupPreflightCheckRead]


class BackupRunRequest(BaseModel):
    include_secrets: bool | None = None
    push_to_git: bool | None = None


class BackupImportPreviewRequest(BaseModel):
    snapshot: dict[str, Any]
    sections: list[str] | None = None


class BackupImportApplyRequest(BaseModel):
    snapshot: dict[str, Any]
    confirm: str
    sections: list[str] | None = None


class BackupRunRestorePreviewRequest(BaseModel):
    sections: list[str] | None = None


class BackupRunRestoreApplyRequest(BaseModel):
    confirm: str
    sections: list[str] | None = None


class BackupImportPreviewRead(BaseModel):
    ok: bool
    schema_version: str | None
    diff: BackupDiffRead
    blocked_sections: list[str]
    warnings: list[str]
    selected_sections: list[str]
    expanded_sections: list[str]


class BackupImportApplyRead(BaseModel):
    status: str
    restored_rows: int
    restored_sections: int
    safety_backup_run_id: int
    diff: BackupDiffRead
    selected_sections: list[str]
    expanded_sections: list[str]


class BackupRunRead(BaseModel):
    id: int
    status: str
    items_exported: int
    snapshot: dict[str, Any] | None = None
    git_commit: str | None = None
    error_message: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


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


class TemplateVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template_id: int
    version_number: int
    title: str
    text: str
    parse_mode: str | None
    disable_web_page_preview: bool
    created_at: datetime


class TemplateValidateRequest(BaseModel):
    text: str
    variables: dict[str, Any] = Field(default_factory=dict)


class TemplateValidateRead(BaseModel):
    ok: bool
    variables: list[str]
    missing_variables: list[str]
    rendered_text: str | None = None
    error_message: str | None = None


class SendProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    bot_id: int
    send_kind: Literal["text", "template", "file"]
    destination_id: int | None = None
    destination_alias: str | None = None
    chat_id: str | None = None
    message_thread_id: int | None = None
    template_tag: str | None = None
    text: str | None = None
    media_type: Literal["none", "document", "video"] = "none"
    file_relative_path: str | None = None
    caption: str | None = None
    parse_mode: str | None = None
    disable_web_page_preview: bool | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class SendProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    bot_id: int | None = None
    send_kind: Literal["text", "template", "file"] | None = None
    destination_id: int | None = None
    destination_alias: str | None = None
    chat_id: str | None = None
    message_thread_id: int | None = None
    template_tag: str | None = None
    text: str | None = None
    media_type: Literal["none", "document", "video"] | None = None
    file_relative_path: str | None = None
    caption: str | None = None
    parse_mode: str | None = None
    disable_web_page_preview: bool | None = None
    variables: dict[str, Any] | None = None
    is_active: bool | None = None


class SendProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    bot_id: int
    send_kind: str
    destination_id: int | None
    destination_alias: str | None
    chat_id: str | None
    message_thread_id: int | None
    template_tag: str | None
    text: str | None
    media_type: str
    file_relative_path: str | None
    caption: str | None
    parse_mode: str | None
    disable_web_page_preview: bool | None
    variables: dict[str, Any] = Field(default_factory=dict, validation_alias="variables_json")
    is_active: bool
    created_at: datetime
    updated_at: datetime


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
    send_at: datetime | None = None


class SendTemplateRequest(BaseModel):
    bot_id: int
    tag: str
    destination_id: int | None = None
    destination_alias: str | None = None
    chat_id: str | None = None
    message_thread_id: int | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    send_mode: Literal["sync", "queued"] = "sync"
    send_at: datetime | None = None


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
    send_at: datetime | None = None


class SendPreviewRequest(BaseModel):
    kind: Literal["text", "template", "file"]
    bot_id: int
    text: str | None = None
    tag: str | None = None
    destination_id: int | None = None
    destination_alias: str | None = None
    chat_id: str | None = None
    message_thread_id: int | None = None
    parse_mode: str | None = None
    disable_web_page_preview: bool | None = None
    media_type: Literal["document", "video"] | None = None
    file_relative_path: str | None = None
    caption: str | None = None
    variables: dict[str, Any] = Field(default_factory=dict)


class SendPreviewRead(BaseModel):
    ok: bool = True
    kind: str
    method: str
    bot_id: int
    chat_id: str
    message_thread_id: int | None = None
    destination_id: int | None = None
    tag: str | None = None
    payload: dict[str, Any]


class SendPreflightCheckRead(BaseModel):
    name: str
    status: Literal["ok", "warning", "error"]
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class SendPreflightRead(BaseModel):
    ok: bool
    checks: list[SendPreflightCheckRead]
    preview: SendPreviewRead | None = None


class SendBatchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    bot_id: int
    send_kind: Literal["text", "template", "file"]
    destination_ids: list[int] = Field(default_factory=list)
    chat_ids: list[str] = Field(default_factory=list)
    template_tag: str | None = None
    text: str | None = None
    media_type: Literal["none", "document", "video"] = "none"
    file_relative_path: str | None = None
    caption: str | None = None
    parse_mode: str | None = None
    disable_web_page_preview: bool | None = None
    variables: dict[str, Any] = Field(default_factory=dict)


class SendBatchItemRead(BaseModel):
    id: int
    batch_id: int
    destination_id: int | None
    chat_id: str
    message_thread_id: int | None
    status: str
    send_history_id: int | None
    error_message: str | None


class SendBatchRead(BaseModel):
    id: int
    name: str
    description: str | None
    bot_id: int
    send_kind: str
    status: str
    template_tag: str | None
    text: str | None
    media_type: str
    file_relative_path: str | None
    caption: str | None
    parse_mode: str | None
    disable_web_page_preview: bool | None
    variables: dict[str, Any]
    progress: dict[str, int]
    items: list[SendBatchItemRead]
    created_at: datetime
    updated_at: datetime
    queued_at: datetime | None
    finished_at: datetime | None


class SendBatchPreviewRead(BaseModel):
    batch_id: int
    previews: list[SendPreviewRead]


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
    next_retry_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    sent_at: datetime | None
    failed_at: datetime | None


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


class EventEnvelope(BaseModel):
    schema_version: str = "v1"
    event_type: str
    data: dict[str, Any] = Field(default_factory=dict)


class MediaItemRead(BaseModel):
    name: str
    relative_path: str
    kind: Literal["directory", "file"]
    size_bytes: int | None
    modified_at: datetime
    media_type: str


class MediaListingRead(BaseModel):
    relative_path: str
    items: list[MediaItemRead]


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


class DestinationHealthRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    destination_id: int
    status: str
    last_error: str | None
    last_member_count: int | None
    checked_at: datetime
    raw_chat_json: dict[str, Any] | None


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
