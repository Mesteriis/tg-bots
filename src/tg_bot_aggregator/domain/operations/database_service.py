from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.core.db import (
    create_engine,
    create_session_factory,
    is_postgres_database_url,
    is_sqlite_database_url,
    persist_runtime_database_override,
    run_migrations,
)
from tg_bot_aggregator.domain.backups.service import BackupService
from tg_bot_aggregator.domain.operations.repository import (
    RuntimeAdvancedSettingsRepository,
    RuntimeSettingsRepository,
)
from tg_bot_aggregator.domain.operations.schemas import RuntimeSettingsRead
from tg_bot_aggregator.infra.uow import UnitOfWork
from tg_bot_aggregator.runtime_settings import apply_runtime_settings, apply_runtime_settings_to_app


class RuntimeDatabaseSwitchError(RuntimeError):
    pass


def _runtime_settings_read_from_settings(settings: Settings) -> RuntimeSettingsRead:
    return RuntimeSettingsRead(
        app_host=settings.app_host,
        app_port=settings.app_port,
        database_url=settings.database_url,
        redis_url=settings.redis_url,
        telegram_api_id=settings.telegram_api_id,
        telegram_api_hash=settings.telegram_api_hash,
        telegram_bot_api_base_url=settings.telegram_bot_api_base_url,
        cors_allowed_origins=settings.cors_allowed_origins,
        mcp_allowed_origins=settings.mcp_allowed_origins,
        shared_media_root=settings.shared_media_root,
        shared_media_require_mount=settings.shared_media_require_mount,
        max_local_file_bytes=settings.max_local_file_bytes,
        telethon_session_dir=settings.telethon_session_dir,
        diagnostic_poll_timeout_seconds=settings.diagnostic_poll_timeout_seconds,
        diagnostic_retry_delay_seconds=settings.diagnostic_retry_delay_seconds,
        discovery_poll_timeout_seconds=settings.discovery_poll_timeout_seconds,
        discovery_retry_delay_seconds=settings.discovery_retry_delay_seconds,
        send_retry_max_attempts=settings.send_retry_max_attempts,
        send_retry_delay_seconds=settings.send_retry_delay_seconds,
        reliability_enabled=settings.reliability_enabled,
        send_default_mode=settings.send_default_mode,
        send_global_rate_per_minute=settings.send_global_rate_per_minute,
        send_bot_rate_per_minute=settings.send_bot_rate_per_minute,
        send_chat_rate_per_minute=settings.send_chat_rate_per_minute,
        send_destination_rate_per_minute=settings.send_destination_rate_per_minute,
        send_retry_base_delay_seconds=settings.send_retry_base_delay_seconds,
        send_retry_max_delay_seconds=settings.send_retry_max_delay_seconds,
        send_worker_lease_seconds=settings.send_worker_lease_seconds,
        send_stale_lock_grace_seconds=settings.send_stale_lock_grace_seconds,
        send_dedupe_window_seconds=settings.send_dedupe_window_seconds,
        protected_api_hosts=settings.protected_api_hosts,
        policy_enabled=settings.policy_enabled,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        quiet_hours_start=settings.quiet_hours_start,
        quiet_hours_end=settings.quiet_hours_end,
        callback_enabled=settings.callback_enabled,
        callback_url=settings.callback_url,
        backup_git_repo_url=settings.backup_git_repo_url,
        backup_git_branch=settings.backup_git_branch,
        backup_git_path=settings.backup_git_path,
        backup_git_service=settings.backup_git_service,
        backup_git_auth_method=settings.backup_git_auth_method,
        backup_git_api_base_url=settings.backup_git_api_base_url,
        backup_git_api_token=settings.backup_git_api_token,
        backup_include_secrets=settings.backup_include_secrets,
        backup_schedule_enabled=settings.backup_schedule_enabled,
        backup_schedule_interval_seconds=settings.backup_schedule_interval_seconds,
        backup_schedule_push_to_git=settings.backup_schedule_push_to_git,
        telegram_egress_mode=settings.telegram_egress_mode,
        telegram_egress_enabled=settings.telegram_egress_enabled,
        telegram_egress_provider=settings.telegram_egress_provider,
        telegram_egress_last_status="disconnected",
        telegram_egress_last_error=None,
        telegram_egress_connected_at=None,
        telegram_egress_last_handshake_at=None,
        telegram_egress_last_egress_ip=None,
    )


def _rewrite_snapshot_database_url(
    snapshot: dict[str, Any],
    target_database_url: str,
) -> dict[str, Any]:
    rewritten = deepcopy(snapshot)
    rows = rewritten.setdefault("runtime_advanced_settings", [])
    if rows:
        settings_json = rows[0].setdefault("settings_json", {})
        if isinstance(settings_json, dict):
            settings_json["database_url"] = target_database_url
    else:
        rows.append({"id": 1, "settings_json": {"database_url": target_database_url}})
    return rewritten


async def _load_effective_target_settings(
    base_settings: Settings,
    session: AsyncSession,
) -> Settings:
    return apply_runtime_settings(
        base_settings,
        await RuntimeSettingsRepository(session).get(),
        await RuntimeAdvancedSettingsRepository(session).get(),
    )


async def migrate_sqlite_to_postgres(
    *,
    app: Any,
    uow: UnitOfWork,
    target_database_url: str,
) -> Settings:
    current_settings: Settings = app.state.settings
    current_database_url = current_settings.database_url
    if target_database_url == current_database_url:
        return current_settings
    if not is_sqlite_database_url(current_database_url):
        raise RuntimeDatabaseSwitchError(
            "database migration is supported only from sqlite to postgres"
        )
    if not is_postgres_database_url(target_database_url):
        raise RuntimeDatabaseSwitchError(
            "reverse migration is not supported; target database_url must be postgres"
        )

    source_runtime_settings = _runtime_settings_read_from_settings(current_settings)
    snapshot, _ = await BackupService(uow.session, source_runtime_settings).export_snapshot(
        include_secrets=True
    )
    migrated_snapshot = _rewrite_snapshot_database_url(snapshot, target_database_url)
    target_settings = current_settings.model_copy(update={"database_url": target_database_url})
    await run_migrations(target_database_url)

    target_engine = create_engine(target_settings)
    target_session_factory = create_session_factory(target_engine)
    try:
        async with target_session_factory() as target_session:
            target_runtime_settings = _runtime_settings_read_from_settings(target_settings)
            await BackupService(target_session, target_runtime_settings).apply_import_snapshot(
                migrated_snapshot
            )
            await target_session.commit()
            effective_target_settings = await _load_effective_target_settings(
                target_settings,
                target_session,
            )
    except Exception:
        await target_engine.dispose()
        raise

    bootstrap_session_factory = getattr(
        app.state,
        "bootstrap_session_factory",
        app.state.session_factory,
    )
    await persist_runtime_database_override(bootstrap_session_factory, target_database_url)

    current_engine = getattr(app.state, "engine", None)
    bootstrap_engine = getattr(app.state, "bootstrap_engine", current_engine)
    app.state.engine = target_engine
    app.state.session_factory = target_session_factory
    app.state.settings = effective_target_settings
    app.state.uow_settings = effective_target_settings
    app.state.active_database_url = effective_target_settings.database_url
    app.state.bootstrap_session_factory = bootstrap_session_factory
    app.state.bootstrap_engine = bootstrap_engine
    apply_runtime_settings_to_app(app, effective_target_settings)
    return effective_target_settings
