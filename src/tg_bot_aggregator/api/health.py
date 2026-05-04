from functools import partial

from anyio import to_thread
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import get_session
from tg_bot_aggregator.repositories import BackupRunRepository
from tg_bot_aggregator.shared_paths import check_shared_media_root

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
    }
