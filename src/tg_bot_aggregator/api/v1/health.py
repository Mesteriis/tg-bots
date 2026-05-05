from functools import partial

from anyio import to_thread
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.deps import get_session
from tg_bot_aggregator.domain.auth.admin_service import AdminAuthService
from tg_bot_aggregator.domain.backups.repository import BackupRunRepository
from tg_bot_aggregator.domain.media.paths import check_shared_media_root
from tg_bot_aggregator.domain.operations.telegram_egress_service import (
    TelegramEgressService,
)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    settings = request.app.state.settings
    shared_media_status = await to_thread.run_sync(
        partial(
            check_shared_media_root,
            settings.shared_media_root,
            require_mount=settings.shared_media_require_mount,
        ),
    )
    latest_backup = (await BackupRunRepository(session).list(limit=1))
    backup = latest_backup[0] if latest_backup else None
    auth = AdminAuthService(settings).diagnostics()
    telegram_egress = await TelegramEgressService(session, settings).read_state()
    return {
        "status": "ok",
        "api_version": "v1",
        "bot_api_base_url": settings.telegram_bot_api_base_url,
        "shared_media_root": settings.shared_media_root,
        "shared_media_available": shared_media_status.available,
        "shared_media_error": shared_media_status.error,
        "shared_media_mounted": shared_media_status.mounted,
        "shared_media_mount_required": shared_media_status.mount_required,
        "max_local_file_bytes": settings.max_local_file_bytes,
        "local_bot_api": settings.is_local_bot_api,
        "backup_configured": bool(settings.backup_git_repo_url),
        "backup_include_secrets": settings.backup_include_secrets,
        "backup_git_service": settings.backup_git_service,
        "backup_git_auth_method": settings.backup_git_auth_method,
        "backup_last_run_id": backup.id if backup else None,
        "backup_last_status": backup.status if backup else None,
        "backup_last_error": backup.error_message if backup else None,
        "backup_last_finished_at": (
            backup.finished_at.isoformat() if backup and backup.finished_at else None
        ),
        "admin_auth_file_path": auth.auth_file_path,
        "admin_auth_file_exists": auth.auth_file_exists,
        "admin_auth_file_readable": auth.auth_file_readable,
        "admin_auth_bootstrap_required": auth.bootstrap_required,
        "admin_auth_username": auth.username,
        "admin_auth_passkey_configured": auth.passkey_configured,
        "telegram_egress_mode": telegram_egress.mode,
        "telegram_egress_enabled": telegram_egress.enabled,
        "telegram_egress_provider": telegram_egress.provider,
        "telegram_egress_provider_config_present": telegram_egress.provider_config_present,
        "telegram_egress_last_status": telegram_egress.last_status,
        "telegram_egress_last_error": telegram_egress.last_error,
        "telegram_egress_last_egress_ip": telegram_egress.last_egress_ip,
        "telegram_egress_connected_at": (
            telegram_egress.connected_at.isoformat()
            if telegram_egress.connected_at
            else None
        ),
        "telegram_egress_last_handshake_at": (
            telegram_egress.last_handshake_at.isoformat()
            if telegram_egress.last_handshake_at
            else None
        ),
    }
