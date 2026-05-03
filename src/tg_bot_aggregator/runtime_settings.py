from typing import Any

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.models import RuntimeAdvancedSettings, RuntimeSettings
from tg_bot_aggregator.schemas import RuntimeSettingsRead
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient

SETTING_MODEL_FIELDS = {
    "telegram_bot_api_base_url",
    "shared_media_root",
    "shared_media_require_mount",
    "max_local_file_bytes",
    "send_retry_max_attempts",
    "send_retry_delay_seconds",
    "reliability_enabled",
    "send_default_mode",
    "send_global_rate_per_minute",
    "send_bot_rate_per_minute",
    "send_chat_rate_per_minute",
    "send_destination_rate_per_minute",
    "send_retry_base_delay_seconds",
    "send_retry_max_delay_seconds",
    "send_worker_lease_seconds",
    "send_stale_lock_grace_seconds",
    "send_dedupe_window_seconds",
    "protected_api_hosts",
    "policy_enabled",
    "rate_limit_per_minute",
    "quiet_hours_start",
    "quiet_hours_end",
    "callback_enabled",
    "callback_url",
    "backup_git_repo_url",
    "backup_git_branch",
    "backup_git_path",
    "backup_include_secrets",
}

ADVANCED_SETTING_FIELDS = {
    "app_host",
    "app_port",
    "database_url",
    "redis_url",
    "telegram_api_id",
    "telegram_api_hash",
    "cors_allowed_origins",
    "mcp_allowed_origins",
    "telethon_session_dir",
    "diagnostic_poll_timeout_seconds",
    "diagnostic_retry_delay_seconds",
    "discovery_poll_timeout_seconds",
    "discovery_retry_delay_seconds",
    "backup_git_service",
    "backup_git_auth_method",
    "backup_git_api_base_url",
    "backup_git_api_token",
    "backup_schedule_enabled",
    "backup_schedule_interval_seconds",
    "backup_schedule_push_to_git",
}


def split_runtime_update_values(
    values: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    model_values: dict[str, Any] = {}
    advanced_values: dict[str, Any] = {}
    for key, value in values.items():
        if key in ADVANCED_SETTING_FIELDS:
            advanced_values[key] = value
        elif key == "protected_api_hosts":
            model_values["protected_api_hosts_json"] = value
        elif key in SETTING_MODEL_FIELDS:
            model_values[key] = value
    return model_values, advanced_values


def runtime_update_to_model_values(values: dict[str, Any]) -> dict[str, Any]:
    model_values, _ = split_runtime_update_values(values)
    return model_values


def apply_runtime_settings(
    base: Settings,
    row: RuntimeSettings | None,
    advanced: RuntimeAdvancedSettings | None = None,
) -> Settings:
    update: dict[str, Any] = {}
    if row is not None:
        for field in SETTING_MODEL_FIELDS:
            column = "protected_api_hosts_json" if field == "protected_api_hosts" else field
            value = getattr(row, column)
            if value is not None:
                update[field] = value
    if advanced is not None:
        for field in ADVANCED_SETTING_FIELDS:
            value = (advanced.settings_json or {}).get(field)
            if value is not None:
                update[field] = value
    return base.model_copy(update=update)


def runtime_settings_read(
    base: Settings,
    row: RuntimeSettings | None,
    advanced: RuntimeAdvancedSettings | None = None,
) -> RuntimeSettingsRead:
    effective = apply_runtime_settings(base, row, advanced)
    return RuntimeSettingsRead(
        app_host=effective.app_host,
        app_port=effective.app_port,
        database_url=effective.database_url,
        redis_url=effective.redis_url,
        telegram_api_id=effective.telegram_api_id,
        telegram_api_hash=effective.telegram_api_hash,
        telegram_bot_api_base_url=effective.telegram_bot_api_base_url,
        cors_allowed_origins=effective.cors_allowed_origins,
        mcp_allowed_origins=effective.mcp_allowed_origins,
        shared_media_root=effective.shared_media_root,
        shared_media_require_mount=effective.shared_media_require_mount,
        max_local_file_bytes=effective.max_local_file_bytes,
        telethon_session_dir=effective.telethon_session_dir,
        diagnostic_poll_timeout_seconds=effective.diagnostic_poll_timeout_seconds,
        diagnostic_retry_delay_seconds=effective.diagnostic_retry_delay_seconds,
        discovery_poll_timeout_seconds=effective.discovery_poll_timeout_seconds,
        discovery_retry_delay_seconds=effective.discovery_retry_delay_seconds,
        send_retry_max_attempts=effective.send_retry_max_attempts,
        send_retry_delay_seconds=effective.send_retry_delay_seconds,
        reliability_enabled=effective.reliability_enabled,
        send_default_mode=effective.send_default_mode,
        send_global_rate_per_minute=effective.send_global_rate_per_minute,
        send_bot_rate_per_minute=effective.send_bot_rate_per_minute,
        send_chat_rate_per_minute=effective.send_chat_rate_per_minute,
        send_destination_rate_per_minute=effective.send_destination_rate_per_minute,
        send_retry_base_delay_seconds=effective.send_retry_base_delay_seconds,
        send_retry_max_delay_seconds=effective.send_retry_max_delay_seconds,
        send_worker_lease_seconds=effective.send_worker_lease_seconds,
        send_stale_lock_grace_seconds=effective.send_stale_lock_grace_seconds,
        send_dedupe_window_seconds=effective.send_dedupe_window_seconds,
        protected_api_hosts=effective.protected_api_hosts,
        policy_enabled=effective.policy_enabled,
        rate_limit_per_minute=effective.rate_limit_per_minute,
        quiet_hours_start=effective.quiet_hours_start,
        quiet_hours_end=effective.quiet_hours_end,
        callback_enabled=effective.callback_enabled,
        callback_url=effective.callback_url,
        backup_git_repo_url=effective.backup_git_repo_url,
        backup_git_branch=effective.backup_git_branch,
        backup_git_path=effective.backup_git_path,
        backup_git_service=effective.backup_git_service,
        backup_git_auth_method=effective.backup_git_auth_method,
        backup_git_api_base_url=effective.backup_git_api_base_url,
        backup_git_api_token=effective.backup_git_api_token,
        backup_include_secrets=effective.backup_include_secrets,
        backup_schedule_enabled=effective.backup_schedule_enabled,
        backup_schedule_interval_seconds=effective.backup_schedule_interval_seconds,
        backup_schedule_push_to_git=effective.backup_schedule_push_to_git,
    )


def apply_runtime_settings_to_app(app: Any, settings: Settings) -> None:
    previous_settings = app.state.settings
    app.state.settings = settings
    if previous_settings.telegram_bot_api_base_url != settings.telegram_bot_api_base_url:
        app.state.bot_api_client = TelegramBotApiClient(settings.telegram_bot_api_base_url)
