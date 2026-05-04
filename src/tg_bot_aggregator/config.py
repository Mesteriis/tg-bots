from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_csv(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return value
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_host: str = Field(default="127.0.0.1", validation_alias="APP_HOST")
    app_port: int = Field(default=8000, validation_alias="APP_PORT")
    api_v1_prefix: str = "/api/v1"
    mcp_v1_prefix: str = "/mcp/v1"

    database_url: str = Field(
        default="sqlite+aiosqlite:////data/app.db", validation_alias="DATABASE_URL"
    )
    redis_url: str = Field(default="redis://redis:6379/0", validation_alias="REDIS_URL")

    telegram_api_id: str | None = Field(default=None, validation_alias="TELEGRAM_API_ID")
    telegram_api_hash: str | None = Field(default=None, validation_alias="TELEGRAM_API_HASH")
    telegram_bot_api_base_url: str = Field(
        default="http://telegram-bot-api:8081", validation_alias="TELEGRAM_BOT_API_BASE_URL"
    )

    shared_media_root: str = Field(default="/shared/media", validation_alias="SHARED_MEDIA_ROOT")
    shared_media_require_mount: bool = Field(
        default=False,
        validation_alias="SHARED_MEDIA_REQUIRE_MOUNT",
    )
    max_local_file_bytes: int = Field(
        default=2_097_152_000, validation_alias="MAX_LOCAL_FILE_BYTES"
    )

    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://127.0.0.1:8000", "http://localhost:8000"],
        validation_alias="CORS_ALLOWED_ORIGINS",
    )
    mcp_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://127.0.0.1:8000", "http://localhost:8000"],
        validation_alias="MCP_ALLOWED_ORIGINS",
    )
    protected_api_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["tg.sh-inc.ru", "tg.sh-inc.dev"],
        validation_alias="PROTECTED_API_HOSTS",
    )
    telethon_session_dir: str = Field(
        default="/data/telethon", validation_alias="TELETHON_SESSION_DIR"
    )
    diagnostic_poll_timeout_seconds: int = Field(
        default=30, validation_alias="DIAGNOSTIC_POLL_TIMEOUT_SECONDS"
    )
    diagnostic_retry_delay_seconds: float = Field(
        default=5.0, validation_alias="DIAGNOSTIC_RETRY_DELAY_SECONDS"
    )
    discovery_poll_timeout_seconds: int = Field(
        default=30, validation_alias="DISCOVERY_POLL_TIMEOUT_SECONDS"
    )
    discovery_retry_delay_seconds: float = Field(
        default=5.0, validation_alias="DISCOVERY_RETRY_DELAY_SECONDS"
    )
    send_retry_max_attempts: int = Field(default=3, validation_alias="SEND_RETRY_MAX_ATTEMPTS")
    send_retry_delay_seconds: float = Field(
        default=1.0,
        validation_alias="SEND_RETRY_DELAY_SECONDS",
    )
    reliability_enabled: bool = Field(default=False, validation_alias="RELIABILITY_ENABLED")
    send_default_mode: Literal["sync", "queued", "auto"] = Field(
        default="sync",
        validation_alias="SEND_DEFAULT_MODE",
    )
    send_global_rate_per_minute: int | None = Field(
        default=None,
        validation_alias="SEND_GLOBAL_RATE_PER_MINUTE",
    )
    send_bot_rate_per_minute: int | None = Field(
        default=None,
        validation_alias="SEND_BOT_RATE_PER_MINUTE",
    )
    send_chat_rate_per_minute: int | None = Field(
        default=None,
        validation_alias="SEND_CHAT_RATE_PER_MINUTE",
    )
    send_destination_rate_per_minute: int | None = Field(
        default=None,
        validation_alias="SEND_DESTINATION_RATE_PER_MINUTE",
    )
    send_retry_base_delay_seconds: float = Field(
        default=1.0,
        validation_alias="SEND_RETRY_BASE_DELAY_SECONDS",
    )
    send_retry_max_delay_seconds: float = Field(
        default=300.0,
        validation_alias="SEND_RETRY_MAX_DELAY_SECONDS",
    )
    send_worker_lease_seconds: int = Field(
        default=60,
        validation_alias="SEND_WORKER_LEASE_SECONDS",
    )
    send_stale_lock_grace_seconds: int = Field(
        default=30,
        validation_alias="SEND_STALE_LOCK_GRACE_SECONDS",
    )
    send_dedupe_window_seconds: int | None = Field(
        default=None,
        validation_alias="SEND_DEDUPE_WINDOW_SECONDS",
    )
    policy_enabled: bool = Field(default=False, validation_alias="POLICY_ENABLED")
    rate_limit_per_minute: int | None = Field(
        default=None,
        validation_alias="RATE_LIMIT_PER_MINUTE",
    )
    quiet_hours_start: str | None = Field(default=None, validation_alias="QUIET_HOURS_START")
    quiet_hours_end: str | None = Field(default=None, validation_alias="QUIET_HOURS_END")
    callback_enabled: bool = Field(default=False, validation_alias="CALLBACK_ENABLED")
    callback_url: str | None = Field(default=None, validation_alias="CALLBACK_URL")
    backup_git_repo_url: str | None = Field(default=None, validation_alias="BACKUP_GIT_REPO_URL")
    backup_git_branch: str = Field(default="main", validation_alias="BACKUP_GIT_BRANCH")
    backup_git_path: str = Field(default="tg-bots.json", validation_alias="BACKUP_GIT_PATH")
    backup_git_service: Literal["auto", "github", "gitea"] = Field(
        default="auto",
        validation_alias="BACKUP_GIT_SERVICE",
    )
    backup_git_auth_method: Literal["none", "token"] = Field(
        default="token",
        validation_alias="BACKUP_GIT_AUTH_METHOD",
    )
    backup_git_api_base_url: str | None = Field(
        default=None,
        validation_alias="BACKUP_GIT_API_BASE_URL",
    )
    backup_git_api_token: str | None = Field(
        default=None,
        validation_alias="BACKUP_GIT_API_TOKEN",
    )
    backup_include_secrets: bool = Field(
        default=False,
        validation_alias="BACKUP_INCLUDE_SECRETS",
    )
    backup_schedule_enabled: bool = Field(
        default=False,
        validation_alias="BACKUP_SCHEDULE_ENABLED",
    )
    backup_schedule_interval_seconds: int = Field(
        default=86_400,
        validation_alias="BACKUP_SCHEDULE_INTERVAL_SECONDS",
    )
    backup_schedule_push_to_git: bool = Field(
        default=False,
        validation_alias="BACKUP_SCHEDULE_PUSH_TO_GIT",
    )

    @field_validator(
        "cors_allowed_origins",
        "mcp_allowed_origins",
        "protected_api_hosts",
        mode="before",
    )
    @classmethod
    def parse_origins(cls, value: str | list[str]) -> list[str]:
        return _split_csv(value)

    @property
    def is_local_bot_api(self) -> bool:
        local_prefixes = ("http://telegram-bot-api", "http://localhost", "http://127.0.0.1")
        return self.telegram_bot_api_base_url.startswith(local_prefixes)


@lru_cache
def get_settings() -> Settings:
    return Settings()
