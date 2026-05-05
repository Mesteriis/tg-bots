from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.deps import get_session, get_uow
from tg_bot_aggregator.api.v1.operations import (
    _backup_run_read,
    _get_backup_run_snapshot,
    _get_effective_settings,
    _preflight_checks,
    _privacy_read,
    _requested_include_secrets,
    _shared_http_client,
)
from tg_bot_aggregator.audit import record_audit_event
from tg_bot_aggregator.domain.backups.repository import BackupRunRepository
from tg_bot_aggregator.domain.backups.schemas import (
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
)
from tg_bot_aggregator.domain.backups.service import (
    BackupService,
    BackupServiceError,
    summarize_snapshot_diff,
)
from tg_bot_aggregator.infra.uow import UnitOfWork
from tg_bot_aggregator.runtime_settings import apply_runtime_settings, apply_runtime_settings_to_app

router = APIRouter(prefix="/operations/backup", tags=["backups"])


@router.get("/runs", response_model=list[BackupRunRead])
async def list_backup_runs(session: AsyncSession = Depends(get_session)) -> list[BackupRunRead]:
    return [_backup_run_read(row) for row in await BackupRunRepository(session).list()]


@router.post("/check-repo", response_model=BackupRepositoryPrivacyRead)
async def check_backup_repository(
    request: Request,
    uow: UnitOfWork = Depends(get_uow),
) -> BackupRepositoryPrivacyRead:
    settings = await _get_effective_settings(request, uow.session)
    service = BackupService(uow.session, settings, http_client=_shared_http_client(request))
    privacy = await service.inspect_repository_privacy()
    await record_audit_event(
        uow.session,
        source="operations",
        action="backup.check_repo",
        status="succeeded" if privacy.verified else "warning",
        request=request,
        entity_type="backup",
        message=privacy.message,
        metadata=asdict(privacy),
    )
    await uow.commit()
    return _privacy_read(privacy)


@router.post("/diff", response_model=BackupDiffRead)
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


@router.post("/preflight", response_model=BackupPreflightRead)
async def backup_preflight(
    payload: BackupRunRequest,
    request: Request,
    uow: UnitOfWork = Depends(get_uow),
) -> BackupPreflightRead:
    settings = await _get_effective_settings(request, uow.session)
    service = BackupService(uow.session, settings, http_client=_shared_http_client(request))
    privacy = await service.inspect_repository_privacy()
    requested_include = _requested_include_secrets(payload, settings)
    include_secrets = requested_include or privacy.is_private is True
    snapshot, _ = await service.export_snapshot(
        include_secrets=include_secrets,
        repo_privacy=privacy,
        requested_include_secrets=requested_include,
    )
    previous = await uow.backups.latest_successful()
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
        uow.session,
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
    await uow.commit()
    return BackupPreflightRead.model_validate(result)


@router.post("/import/preview", response_model=BackupImportPreviewRead)
async def preview_backup_import(
    payload: BackupImportPreviewRequest,
    request: Request,
    uow: UnitOfWork = Depends(get_uow),
) -> BackupImportPreviewRead:
    settings = await _get_effective_settings(request, uow.session)
    service = BackupService(uow.session, settings, http_client=_shared_http_client(request))
    try:
        preview = await service.preview_import_snapshot(payload.snapshot, payload.sections)
    except BackupServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await record_audit_event(
        uow.session,
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
    await uow.commit()
    return BackupImportPreviewRead.model_validate(preview)


@router.post("/import/apply", response_model=BackupImportApplyRead)
async def apply_backup_import(
    payload: BackupImportApplyRequest,
    request: Request,
    uow: UnitOfWork = Depends(get_uow),
) -> BackupImportApplyRead:
    if payload.confirm != "RESTORE":
        raise HTTPException(status_code=400, detail="confirm must be RESTORE")
    settings = await _get_effective_settings(request, uow.session)
    service = BackupService(uow.session, settings, http_client=_shared_http_client(request))
    try:
        preview = await service.preview_import_snapshot(payload.snapshot, payload.sections)
        safety_snapshot, safety_count = await service.export_snapshot(include_secrets=True)
        safety_run = await uow.backups.create(
            status="pre_restore",
            items_exported=safety_count,
            backup_json=safety_snapshot,
        )
        restored_rows = await service.apply_import_snapshot(payload.snapshot, payload.sections)
    except BackupServiceError as exc:
        await uow.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await uow.commit()
    row = await uow.runtime_settings.get()
    advanced = await uow.runtime_advanced_settings.get()
    effective = apply_runtime_settings(request.app.state.settings, row, advanced)
    apply_runtime_settings_to_app(request.app, effective)
    await record_audit_event(
        uow.session,
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
    await uow.commit()
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


@router.post("/runs/{run_id}/restore-preview", response_model=BackupImportPreviewRead)
async def preview_backup_run_restore(
    run_id: int,
    payload: BackupRunRestorePreviewRequest,
    request: Request,
    uow: UnitOfWork = Depends(get_uow),
) -> BackupImportPreviewRead:
    snapshot = await _get_backup_run_snapshot(uow.session, run_id)
    settings = await _get_effective_settings(request, uow.session)
    service = BackupService(uow.session, settings, http_client=_shared_http_client(request))
    try:
        preview = await service.preview_import_snapshot(snapshot, payload.sections)
    except BackupServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await record_audit_event(
        uow.session,
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
    await uow.commit()
    return BackupImportPreviewRead.model_validate(preview)


@router.post("/runs/{run_id}/restore", response_model=BackupImportApplyRead)
async def apply_backup_run_restore(
    run_id: int,
    payload: BackupRunRestoreApplyRequest,
    request: Request,
    uow: UnitOfWork = Depends(get_uow),
) -> BackupImportApplyRead:
    if payload.confirm != "RESTORE":
        raise HTTPException(status_code=400, detail="confirm must be RESTORE")
    snapshot = await _get_backup_run_snapshot(uow.session, run_id)
    settings = await _get_effective_settings(request, uow.session)
    service = BackupService(uow.session, settings, http_client=_shared_http_client(request))
    try:
        preview = await service.preview_import_snapshot(snapshot, payload.sections)
        safety_snapshot, safety_count = await service.export_snapshot(include_secrets=True)
        safety_run = await uow.backups.create(
            status="pre_restore",
            items_exported=safety_count,
            backup_json=safety_snapshot,
        )
        restored_rows = await service.apply_import_snapshot(snapshot, payload.sections)
    except BackupServiceError as exc:
        await uow.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await uow.commit()
    row = await uow.runtime_settings.get()
    advanced = await uow.runtime_advanced_settings.get()
    effective = apply_runtime_settings(request.app.state.settings, row, advanced)
    apply_runtime_settings_to_app(request.app, effective)
    await record_audit_event(
        uow.session,
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
    await uow.commit()
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


@router.post("/run", response_model=BackupRunRead, status_code=201)
async def run_backup(
    payload: BackupRunRequest,
    request: Request,
    uow: UnitOfWork = Depends(get_uow),
) -> BackupRunRead:
    settings = await _get_effective_settings(request, uow.session)
    requested_include_secrets = _requested_include_secrets(payload, settings)
    push_to_git = bool(payload.push_to_git)
    runs = uow.backups
    run = await runs.create(status="started")
    service = BackupService(uow.session, settings, http_client=_shared_http_client(request))
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
            uow.session,
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
            uow.session,
            source="operations",
            action="backup.run",
            status="failed",
            request=request,
            entity_type="backup_run",
            entity_id=run.id,
            message=str(exc),
            metadata={"push_to_git": push_to_git},
        )
        await uow.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await uow.commit()
    return _backup_run_read(run)
