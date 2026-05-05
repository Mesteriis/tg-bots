from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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
    telegram_egress_mode: Literal["direct", "wireguard", "openvpn"] | None = None
    telegram_egress_enabled: bool | None = None
    telegram_egress_provider: Literal["wireguard", "openvpn"] | None = None


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
    telegram_egress_mode: Literal["direct", "wireguard", "openvpn"] = "direct"
    telegram_egress_enabled: bool = False
    telegram_egress_provider: Literal["wireguard", "openvpn"] | None = None
    telegram_egress_last_status: str | None = "disconnected"
    telegram_egress_last_error: str | None = None
    telegram_egress_connected_at: datetime | None = None
    telegram_egress_last_handshake_at: datetime | None = None
    telegram_egress_last_egress_ip: str | None = None
