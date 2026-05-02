from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return value
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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
    max_local_file_bytes: int = Field(
        default=2_097_152_000, validation_alias="MAX_LOCAL_FILE_BYTES"
    )

    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:8000", "http://localhost:8000"],
        validation_alias="CORS_ALLOWED_ORIGINS",
    )
    mcp_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:8000", "http://localhost:8000"],
        validation_alias="MCP_ALLOWED_ORIGINS",
    )
    telethon_session_dir: str = Field(
        default="/data/telethon", validation_alias="TELETHON_SESSION_DIR"
    )

    @field_validator("cors_allowed_origins", "mcp_allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: str | list[str]) -> list[str]:
        return _split_csv(value)

    @property
    def is_local_bot_api(self) -> bool:
        return self.telegram_bot_api_base_url.startswith(("http://telegram-bot-api", "http://localhost", "http://127.0.0.1"))


@lru_cache
def get_settings() -> Settings:
    return Settings()

