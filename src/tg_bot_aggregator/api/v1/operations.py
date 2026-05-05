from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.deps import get_session, get_uow
from tg_bot_aggregator.domain.backups.repository import BackupRunRepository
from tg_bot_aggregator.domain.backups.schemas import (
    BackupRepositoryPrivacyRead,
    BackupRunRead,
    BackupRunRequest,
)
from tg_bot_aggregator.domain.backups.service import RepositoryPrivacy
from tg_bot_aggregator.domain.operations.database_service import (
    RuntimeDatabaseSwitchError,
    migrate_sqlite_to_postgres,
)
from tg_bot_aggregator.domain.operations.repository import (
    RuntimeAdvancedSettingsRepository,
    RuntimeSettingsRepository,
)
from tg_bot_aggregator.domain.operations.schemas import RuntimeSettingsRead, RuntimeSettingsUpdate
from tg_bot_aggregator.domain.operations.telegram_egress_providers import (
    TelegramEgressProviderError,
)
from tg_bot_aggregator.domain.operations.telegram_egress_schemas import (
    TelegramEgressConfigUpload,
    TelegramEgressStateRead,
    TelegramEgressStatusRead,
    TelegramEgressUpdate,
)
from tg_bot_aggregator.domain.operations.telegram_egress_service import TelegramEgressService
from tg_bot_aggregator.infra.uow import UnitOfWork
from tg_bot_aggregator.runtime_settings import (
    apply_runtime_settings,
    apply_runtime_settings_to_app,
    runtime_settings_read,
    split_runtime_update_values,
)

router = APIRouter(prefix="/operations", tags=["operations"])


def _telegram_egress_service(request: Request, session: AsyncSession) -> TelegramEgressService:
    return TelegramEgressService(
        session,
        request.app.state.settings,
        http_client=_shared_http_client(request),
    )


def _resolved_egress_provider(mode: str, provider: str | None) -> str | None:
    if provider is not None:
        return provider
    if mode == "wireguard":
        return "wireguard"
    if mode == "openvpn":
        return "openvpn"
    return None


def _backup_run_read(row: object) -> BackupRunRead:
    return BackupRunRead(
        id=row.id,
        status=row.status,
        items_exported=row.items_exported,
        snapshot=row.backup_json,
        git_commit=row.git_commit,
        error_message=row.error_message,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


def _privacy_read(privacy: RepositoryPrivacy) -> BackupRepositoryPrivacyRead:
    return BackupRepositoryPrivacyRead.model_validate(asdict(privacy))


async def _get_backup_run_snapshot(
    session: AsyncSession,
    run_id: int,
) -> dict[str, Any]:
    run = await BackupRunRepository(session).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="backup run not found")
    if not run.backup_json:
        raise HTTPException(status_code=400, detail="backup run does not contain snapshot JSON")
    return run.backup_json


async def _get_effective_settings(
    request: Request,
    session: AsyncSession,
) -> RuntimeSettingsRead:
    settings_row = await RuntimeSettingsRepository(session).get_or_create()
    advanced = await RuntimeAdvancedSettingsRepository(session).get_or_create()
    return runtime_settings_read(request.app.state.settings, settings_row, advanced)


async def _read_effective_settings(
    request: Request,
    session: AsyncSession,
) -> RuntimeSettingsRead:
    settings_row = await RuntimeSettingsRepository(session).get()
    advanced = await RuntimeAdvancedSettingsRepository(session).get()
    return runtime_settings_read(request.app.state.settings, settings_row, advanced)


def _shared_http_client(request: Request) -> Any:
    return getattr(request.app.state.bot_api_client, "_client", None)


def _requested_include_secrets(payload: BackupRunRequest, settings: RuntimeSettingsRead) -> bool:
    value = (
        payload.include_secrets
        if payload.include_secrets is not None
        else settings.backup_include_secrets
    )
    return bool(value)


def _preflight_checks(
    *,
    settings: RuntimeSettingsRead,
    privacy: RepositoryPrivacy,
    include_secrets: bool,
    requested_include_secrets: bool,
    push_to_git: bool,
    changed_sections: int,
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    checks.append(
        {
            "name": "repository",
            "status": "ok" if settings.backup_git_repo_url else "warning",
            "message": "git repository configured"
            if settings.backup_git_repo_url
            else "git repository is not configured; local JSON snapshot still works",
        }
    )
    checks.append(
        {
            "name": "privacy",
            "status": "ok" if privacy.verified else "warning",
            "message": privacy.message,
        }
    )
    secret_status = "warning" if include_secrets else "ok"
    secret_message = "secrets will be included in backup" if include_secrets else "secrets excluded"
    if requested_include_secrets:
        secret_message = "secrets will be included by manual override"
    elif privacy.is_private is True:
        secret_message = "secrets will be included because repo is verified private"
    checks.append({"name": "secrets", "status": secret_status, "message": secret_message})
    if push_to_git and not settings.backup_git_repo_url:
        checks.append(
            {
                "name": "git_push",
                "status": "error",
                "message": "git push requested but repository URL is missing",
            }
        )
    else:
        checks.append(
            {
                "name": "git_push",
                "status": "ok" if push_to_git else "skipped",
                "message": "git push will run" if push_to_git else "git push is not requested",
            }
        )
    checks.append(
        {
            "name": "diff",
            "status": "ok",
            "message": f"{changed_sections} backup sections changed",
        }
    )
    return checks


@router.get("/settings", response_model=RuntimeSettingsRead)
async def get_runtime_settings(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> RuntimeSettingsRead:
    return await _read_effective_settings(request, session)


@router.patch("/settings", response_model=RuntimeSettingsRead)
async def update_runtime_settings(
    payload: RuntimeSettingsUpdate,
    request: Request,
    uow: UnitOfWork = Depends(get_uow),
) -> RuntimeSettingsRead:
    repo = uow.runtime_settings
    advanced_repo = uow.runtime_advanced_settings
    model_values, advanced_values = split_runtime_update_values(
        payload.model_dump(exclude_unset=True)
    )
    requested_database_url = advanced_values.pop("database_url", None)
    row = await repo.upsert(**model_values) if model_values else await repo.get_or_create()
    advanced = (
        await advanced_repo.upsert(**advanced_values)
        if advanced_values
        else await advanced_repo.get_or_create()
    )
    current_database_url = request.app.state.settings.database_url
    if requested_database_url and requested_database_url != current_database_url:
        try:
            effective = await migrate_sqlite_to_postgres(
                app=request.app,
                uow=uow,
                target_database_url=requested_database_url,
            )
        except RuntimeDatabaseSwitchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await uow.commit()
        return runtime_settings_read(effective, row, advanced)

    if requested_database_url:
        advanced = await advanced_repo.upsert(database_url=requested_database_url)

    await uow.commit()
    effective = apply_runtime_settings(request.app.state.settings, row, advanced)
    apply_runtime_settings_to_app(request.app, effective)
    return runtime_settings_read(effective, row, advanced)


@router.get("/telegram-egress", response_model=TelegramEgressStateRead)
async def get_telegram_egress(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TelegramEgressStateRead:
    state = await _telegram_egress_service(request, session).read_state()
    return TelegramEgressStateRead.model_validate(asdict(state))


@router.patch("/telegram-egress", response_model=TelegramEgressStateRead)
async def patch_telegram_egress(
    payload: TelegramEgressUpdate,
    request: Request,
    uow: UnitOfWork = Depends(get_uow),
) -> TelegramEgressStateRead:
    current = await _read_effective_settings(request, uow.session)
    mode = payload.mode or current.telegram_egress_mode
    enabled = current.telegram_egress_enabled if payload.enabled is None else payload.enabled
    provider = _resolved_egress_provider(mode, payload.provider)
    row = await uow.runtime_settings.upsert(
        telegram_egress_mode=mode,
        telegram_egress_enabled=enabled,
        telegram_egress_provider=provider,
    )
    advanced = await uow.runtime_advanced_settings.get()
    await uow.commit()
    effective = apply_runtime_settings(request.app.state.settings, row, advanced)
    apply_runtime_settings_to_app(request.app, effective)
    state = await TelegramEgressService(
        uow.session,
        request.app.state.settings,
        http_client=_shared_http_client(request),
    ).read_state()
    return TelegramEgressStateRead.model_validate(asdict(state))


@router.post("/telegram-egress/check", response_model=TelegramEgressStatusRead)
async def check_telegram_egress(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TelegramEgressStatusRead:
    status = await _telegram_egress_service(request, session).status()
    return TelegramEgressStatusRead.model_validate(asdict(status))


@router.post("/telegram-egress/config", response_model=TelegramEgressStateRead)
async def upload_telegram_egress_config(
    payload: TelegramEgressConfigUpload,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TelegramEgressStateRead:
    service = _telegram_egress_service(request, session)
    try:
        state = await service.configure(
            provider=payload.provider,
            profile_text=payload.profile_text,
            auth_text=payload.auth_text,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return TelegramEgressStateRead.model_validate(asdict(state))


@router.post("/telegram-egress/connect", response_model=TelegramEgressStatusRead)
async def connect_telegram_egress(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TelegramEgressStatusRead:
    service = _telegram_egress_service(request, session)
    try:
        status = await service.connect()
    except TelegramEgressProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return TelegramEgressStatusRead.model_validate(asdict(status))


@router.post("/telegram-egress/disconnect", response_model=TelegramEgressStatusRead)
async def disconnect_telegram_egress(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TelegramEgressStatusRead:
    service = _telegram_egress_service(request, session)
    try:
        status = await service.disconnect()
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return TelegramEgressStatusRead.model_validate(asdict(status))


@router.post("/telegram-egress/restart", response_model=TelegramEgressStatusRead)
async def restart_telegram_egress(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TelegramEgressStatusRead:
    service = _telegram_egress_service(request, session)
    try:
        status = await service.restart()
    except TelegramEgressProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return TelegramEgressStatusRead.model_validate(asdict(status))
