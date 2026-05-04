from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import get_session
from tg_bot_aggregator.audit import record_audit_event
from tg_bot_aggregator.backup_service import (
    BackupService,
    BackupServiceError,
    RepositoryPrivacy,
    summarize_snapshot_diff,
)
from tg_bot_aggregator.repositories import (
    BackupRunRepository,
    RuntimeAdvancedSettingsRepository,
    RuntimeSettingsRepository,
)
from tg_bot_aggregator.runtime_settings import (
    apply_runtime_settings,
    apply_runtime_settings_to_app,
    runtime_settings_read,
    split_runtime_update_values,
)
from tg_bot_aggregator.schemas import (
    BackupDiffRead,
    BackupImportApplyRead,
    BackupImportApplyRequest,
    BackupImportPreviewRead,
    BackupImportPreviewRequest,
    BackupPreflightRead,
    BackupRepositoryPrivacyRead,
    BackupRunRead,
    BackupRunRequest,
    BackupRunRestoreApplyRequest,
    BackupRunRestorePreviewRequest,
    RuntimeSettingsRead,
    RuntimeSettingsUpdate,
)

router = APIRouter(prefix="/operations", tags=["operations"])


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
    session: AsyncSession = Depends(get_session),
) -> RuntimeSettingsRead:
    repo = RuntimeSettingsRepository(session)
    advanced_repo = RuntimeAdvancedSettingsRepository(session)
    model_values, advanced_values = split_runtime_update_values(
        payload.model_dump(exclude_unset=True)
    )
    row = await repo.upsert(**model_values) if model_values else await repo.get_or_create()
    advanced = (
        await advanced_repo.upsert(**advanced_values)
        if advanced_values
        else await advanced_repo.get_or_create()
    )
    effective = apply_runtime_settings(request.app.state.settings, row, advanced)
    apply_runtime_settings_to_app(request.app, effective)
    await session.commit()
    return runtime_settings_read(effective, row, advanced)


@router.get("/backup/runs", response_model=list[BackupRunRead])
async def list_backup_runs(session: AsyncSession = Depends(get_session)) -> list[BackupRunRead]:
    return [_backup_run_read(row) for row in await BackupRunRepository(session).list()]


@router.post("/backup/check-repo", response_model=BackupRepositoryPrivacyRead)
async def check_backup_repository(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BackupRepositoryPrivacyRead:
    settings = await _get_effective_settings(request, session)
    service = BackupService(session, settings, http_client=_shared_http_client(request))
    privacy = await service.inspect_repository_privacy()
    await record_audit_event(
        session,
        source="operations",
        action="backup.check_repo",
        status="succeeded" if privacy.verified else "warning",
        request=request,
        entity_type="backup",
        message=privacy.message,
        metadata=asdict(privacy),
    )
    await session.commit()
    return _privacy_read(privacy)


@router.post("/backup/diff", response_model=BackupDiffRead)
async def backup_diff(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BackupDiffRead:
    settings = await _get_effective_settings(request, session)
    service = BackupService(session, settings, http_client=_shared_http_client(request))
    snapshot, _ = await service.export_snapshot(include_secrets=False)
    previous = await BackupRunRepository(session).latest_successful()
    diff = summarize_snapshot_diff(
        snapshot,
        previous.backup_json if previous else None,
        previous.id if previous else None,
    )
    return BackupDiffRead.model_validate(diff)


@router.post("/backup/preflight", response_model=BackupPreflightRead)
async def backup_preflight(
    payload: BackupRunRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BackupPreflightRead:
    settings = await _get_effective_settings(request, session)
    service = BackupService(session, settings, http_client=_shared_http_client(request))
    privacy = await service.inspect_repository_privacy()
    requested_include = _requested_include_secrets(payload, settings)
    include_secrets = requested_include or privacy.is_private is True
    snapshot, _ = await service.export_snapshot(
        include_secrets=include_secrets,
        repo_privacy=privacy,
        requested_include_secrets=requested_include,
    )
    previous = await BackupRunRepository(session).latest_successful()
    diff = summarize_snapshot_diff(
        snapshot,
        previous.backup_json if previous else None,
        previous.id if previous else None,
    )
    push_to_git = bool(payload.push_to_git)
    checks = _preflight_checks(
        settings=settings,
        privacy=privacy,
        include_secrets=include_secrets,
        requested_include_secrets=requested_include,
        push_to_git=push_to_git,
        changed_sections=diff["changed_sections"],
    )
    result = {
        "ok": not any(check["status"] == "error" for check in checks),
        "include_secrets": include_secrets,
        "requested_include_secrets": requested_include,
        "push_to_git": push_to_git,
        "repo": asdict(privacy),
        "diff": diff,
        "checks": checks,
    }
    await record_audit_event(
        session,
        source="operations",
        action="backup.preflight",
        status="succeeded" if result["ok"] else "failed",
        request=request,
        entity_type="backup",
        message="backup preflight completed",
        metadata={
            "include_secrets": include_secrets,
            "push_to_git": push_to_git,
            "repo": asdict(privacy),
            "changed_sections": diff["changed_sections"],
        },
    )
    await session.commit()
    return BackupPreflightRead.model_validate(result)


@router.post("/backup/import/preview", response_model=BackupImportPreviewRead)
async def preview_backup_import(
    payload: BackupImportPreviewRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BackupImportPreviewRead:
    settings = await _get_effective_settings(request, session)
    service = BackupService(session, settings, http_client=_shared_http_client(request))
    try:
        preview = await service.preview_import_snapshot(payload.snapshot, payload.sections)
    except BackupServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await record_audit_event(
        session,
        source="operations",
        action="backup.import_preview",
        status="succeeded" if preview["ok"] else "warning",
        request=request,
        entity_type="backup",
        message="backup import preview completed",
        metadata={
            "blocked_sections": preview["blocked_sections"],
            "changed_sections": preview["diff"]["changed_sections"],
            "selected_sections": preview["selected_sections"],
            "expanded_sections": preview["expanded_sections"],
        },
    )
    await session.commit()
    return BackupImportPreviewRead.model_validate(preview)


@router.post("/backup/import/apply", response_model=BackupImportApplyRead)
async def apply_backup_import(
    payload: BackupImportApplyRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BackupImportApplyRead:
    if payload.confirm != "RESTORE":
        raise HTTPException(status_code=400, detail="confirm must be RESTORE")
    settings = await _get_effective_settings(request, session)
    service = BackupService(session, settings, http_client=_shared_http_client(request))
    try:
        preview = await service.preview_import_snapshot(payload.snapshot, payload.sections)
        safety_snapshot, safety_count = await service.export_snapshot(include_secrets=True)
        safety_run = await BackupRunRepository(session).create(
            status="pre_restore",
            items_exported=safety_count,
            backup_json=safety_snapshot,
        )
        restored_rows = await service.apply_import_snapshot(payload.snapshot, payload.sections)
    except BackupServiceError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row = await RuntimeSettingsRepository(session).get()
    advanced = await RuntimeAdvancedSettingsRepository(session).get()
    effective = apply_runtime_settings(request.app.state.settings, row, advanced)
    apply_runtime_settings_to_app(request.app, effective)
    await record_audit_event(
        session,
        source="operations",
        action="backup.import_apply",
        status="succeeded",
        request=request,
        entity_type="backup",
        message="backup import applied",
        metadata={
            "restored_rows": restored_rows,
            "safety_backup_run_id": safety_run.id,
            "changed_sections": preview["diff"]["changed_sections"],
            "selected_sections": preview["selected_sections"],
            "expanded_sections": preview["expanded_sections"],
        },
    )
    await session.commit()
    return BackupImportApplyRead.model_validate(
        {
            "status": "restored",
            "restored_rows": restored_rows,
            "restored_sections": len(preview["expanded_sections"]),
            "safety_backup_run_id": safety_run.id,
            "diff": preview["diff"],
            "selected_sections": preview["selected_sections"],
            "expanded_sections": preview["expanded_sections"],
        }
    )


@router.post("/backup/runs/{run_id}/restore-preview", response_model=BackupImportPreviewRead)
async def preview_backup_run_restore(
    run_id: int,
    payload: BackupRunRestorePreviewRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BackupImportPreviewRead:
    snapshot = await _get_backup_run_snapshot(session, run_id)
    settings = await _get_effective_settings(request, session)
    service = BackupService(session, settings, http_client=_shared_http_client(request))
    try:
        preview = await service.preview_import_snapshot(snapshot, payload.sections)
    except BackupServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await record_audit_event(
        session,
        source="operations",
        action="backup.restore_run_preview",
        status="succeeded" if preview["ok"] else "warning",
        request=request,
        entity_type="backup_run",
        entity_id=run_id,
        message="backup run restore preview completed",
        metadata={
            "blocked_sections": preview["blocked_sections"],
            "changed_sections": preview["diff"]["changed_sections"],
            "selected_sections": preview["selected_sections"],
            "expanded_sections": preview["expanded_sections"],
        },
    )
    await session.commit()
    return BackupImportPreviewRead.model_validate(preview)


@router.post("/backup/runs/{run_id}/restore", response_model=BackupImportApplyRead)
async def apply_backup_run_restore(
    run_id: int,
    payload: BackupRunRestoreApplyRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BackupImportApplyRead:
    if payload.confirm != "RESTORE":
        raise HTTPException(status_code=400, detail="confirm must be RESTORE")
    snapshot = await _get_backup_run_snapshot(session, run_id)
    settings = await _get_effective_settings(request, session)
    service = BackupService(session, settings, http_client=_shared_http_client(request))
    try:
        preview = await service.preview_import_snapshot(snapshot, payload.sections)
        safety_snapshot, safety_count = await service.export_snapshot(include_secrets=True)
        safety_run = await BackupRunRepository(session).create(
            status="pre_restore",
            items_exported=safety_count,
            backup_json=safety_snapshot,
        )
        restored_rows = await service.apply_import_snapshot(snapshot, payload.sections)
    except BackupServiceError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row = await RuntimeSettingsRepository(session).get()
    advanced = await RuntimeAdvancedSettingsRepository(session).get()
    effective = apply_runtime_settings(request.app.state.settings, row, advanced)
    apply_runtime_settings_to_app(request.app, effective)
    await record_audit_event(
        session,
        source="operations",
        action="backup.restore_run_apply",
        status="succeeded",
        request=request,
        entity_type="backup_run",
        entity_id=run_id,
        message="backup run restore applied",
        metadata={
            "restored_rows": restored_rows,
            "safety_backup_run_id": safety_run.id,
            "changed_sections": preview["diff"]["changed_sections"],
            "selected_sections": preview["selected_sections"],
            "expanded_sections": preview["expanded_sections"],
        },
    )
    await session.commit()
    return BackupImportApplyRead.model_validate(
        {
            "status": "restored",
            "restored_rows": restored_rows,
            "restored_sections": len(preview["expanded_sections"]),
            "safety_backup_run_id": safety_run.id,
            "diff": preview["diff"],
            "selected_sections": preview["selected_sections"],
            "expanded_sections": preview["expanded_sections"],
        }
    )


@router.post("/backup/run", response_model=BackupRunRead, status_code=201)
async def run_backup(
    payload: BackupRunRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BackupRunRead:
    settings = await _get_effective_settings(request, session)
    requested_include_secrets = _requested_include_secrets(payload, settings)
    push_to_git = bool(payload.push_to_git)
    runs = BackupRunRepository(session)
    run = await runs.create(status="started")
    service = BackupService(session, settings, http_client=_shared_http_client(request))
    try:
        repo_privacy = await service.inspect_repository_privacy()
        include_secrets = requested_include_secrets or repo_privacy.is_private is True
        snapshot, count = await service.export_snapshot(
            include_secrets=include_secrets,
            repo_privacy=repo_privacy,
            requested_include_secrets=requested_include_secrets,
        )
        commit = await service.push_snapshot(snapshot) if push_to_git else None
        await runs.mark_finished(
            run,
            status="succeeded",
            items_exported=count,
            backup_json=snapshot,
            git_commit=commit,
        )
        await record_audit_event(
            session,
            source="operations",
            action="backup.run",
            status="succeeded",
            request=request,
            entity_type="backup_run",
            entity_id=run.id,
            message="backup run succeeded",
            metadata={
                "include_secrets": include_secrets,
                "push_to_git": push_to_git,
                "git_commit": commit,
                "items_exported": count,
                "repo": asdict(repo_privacy),
            },
        )
    except BackupServiceError as exc:
        await runs.mark_finished(
            run,
            status="failed",
            items_exported=0,
            error_message=str(exc),
        )
        await record_audit_event(
            session,
            source="operations",
            action="backup.run",
            status="failed",
            request=request,
            entity_type="backup_run",
            entity_id=run.id,
            message=str(exc),
            metadata={"push_to_git": push_to_git},
        )
        await session.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return _backup_run_read(run)
