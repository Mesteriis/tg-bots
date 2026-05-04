from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import create_send_service, get_session
from tg_bot_aggregator.domain.batches.service import WorkflowService
from tg_bot_aggregator.domain.operations.service import OperationsService
from tg_bot_aggregator.domain.sending.service import IdempotencyConflictError, SendServiceError
from tg_bot_aggregator.domain.templates.renderer import TemplateRenderError
from tg_bot_aggregator.models import utc_now
from tg_bot_aggregator.repositories import NotFoundError, SendHistoryRepository
from tg_bot_aggregator.schemas import (
    SendDryRunRead,
    SendFileRequest,
    SendHistoryRead,
    SendPreflightRead,
    SendPreviewRead,
    SendPreviewRequest,
    SendTemplateRequest,
    SendTextRequest,
)

router = APIRouter(tags=["send"])


async def _enqueue_if_needed(row: object, request: Request, session: AsyncSession) -> object:
    if getattr(row, "status", None) != "queued" or getattr(row, "queued_task_id", None):
        return row
    next_retry_at = getattr(row, "next_retry_at", None)
    if next_retry_at is not None:
        now = utc_now()
        resolved_next_retry_at = (
            next_retry_at
            if next_retry_at.tzinfo is not None
            else next_retry_at.replace(tzinfo=now.tzinfo)
        )
        if resolved_next_retry_at > now:
            return row
    enqueue = getattr(request.app.state, "enqueue_send_history", None)
    if enqueue is None:
        return row
    task_id = await enqueue(row.id)
    if task_id:
        repo = SendHistoryRepository(session)
        await repo.mark_queued(row, task_id=task_id)
        await session.commit()
    return row


def _idempotency_key(request: Request) -> str | None:
    value = request.headers.get("Idempotency-Key")
    return value.strip() if value else None


def _send_error(exc: Exception) -> HTTPException:
    if isinstance(exc, IdempotencyConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/send/text", response_model=SendHistoryRead)
async def send_text(
    payload: SendTextRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    service = create_send_service(session, request)
    try:
        row = await service.send_text(
            **payload.model_dump(),
            idempotency_key=_idempotency_key(request),
        )
        return await _enqueue_if_needed(row, request, session)
    except (NotFoundError, SendServiceError, TemplateRenderError) as exc:
        raise _send_error(exc) from exc


@router.post("/send/template", response_model=SendHistoryRead)
async def send_template(
    payload: SendTemplateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    service = create_send_service(session, request)
    try:
        row = await service.send_template(
            **payload.model_dump(),
            idempotency_key=_idempotency_key(request),
        )
        return await _enqueue_if_needed(row, request, session)
    except (NotFoundError, SendServiceError, TemplateRenderError) as exc:
        raise _send_error(exc) from exc


@router.post("/send/file", response_model=SendHistoryRead)
async def send_file(
    payload: SendFileRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    service = create_send_service(session, request)
    try:
        row = await service.send_file(
            **payload.model_dump(),
            idempotency_key=_idempotency_key(request),
        )
        return await _enqueue_if_needed(row, request, session)
    except (NotFoundError, SendServiceError, TemplateRenderError) as exc:
        raise _send_error(exc) from exc


@router.post("/send/preview", response_model=SendPreviewRead)
async def preview_send(
    payload: SendPreviewRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    service = WorkflowService(create_send_service(session, request))
    try:
        data = payload.model_dump()
        kind = data.pop("kind")
        return await service.preview_send(kind=kind, **data)
    except (NotFoundError, SendServiceError, TemplateRenderError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/send/preflight", response_model=SendPreflightRead)
async def preflight_send(
    payload: SendPreviewRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SendPreflightRead:
    service = OperationsService(create_send_service(session, request))
    data = payload.model_dump()
    kind = data.pop("kind")
    return await service.preflight_send(kind=kind, **data)


@router.post("/send/text/dry-run", response_model=SendDryRunRead)
async def dry_run_text(
    payload: SendTextRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    service = create_send_service(session, request)
    try:
        data = payload.model_dump()
        data.pop("send_mode", None)
        data.pop("send_at", None)
        return await service.dry_run_text(**data)
    except (NotFoundError, SendServiceError, TemplateRenderError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/send/template/dry-run", response_model=SendDryRunRead)
async def dry_run_template(
    payload: SendTemplateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    service = create_send_service(session, request)
    try:
        data = payload.model_dump()
        data.pop("send_mode", None)
        data.pop("send_at", None)
        return await service.dry_run_template(**data)
    except (NotFoundError, SendServiceError, TemplateRenderError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/send/file/dry-run", response_model=SendDryRunRead)
async def dry_run_file(
    payload: SendFileRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    service = create_send_service(session, request)
    try:
        data = payload.model_dump()
        data.pop("send_mode", None)
        data.pop("send_at", None)
        return await service.dry_run_file(**data)
    except (NotFoundError, SendServiceError, TemplateRenderError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/send-history", response_model=list[SendHistoryRead])
async def list_send_history(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await SendHistoryRepository(session).list()


@router.get("/send-history/dead-letter", response_model=list[SendHistoryRead])
async def list_dead_letter(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await SendHistoryRepository(session).list_failed()


@router.get("/send-history/due", response_model=list[SendHistoryRead])
async def list_due_send_history(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await SendHistoryRepository(session).list_due(utc_now())


@router.post("/send-history/{send_history_id}/retry", response_model=SendHistoryRead)
async def retry_send_history(
    send_history_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    service = create_send_service(session, request)
    try:
        row = await service.retry_history(send_history_id)
        return await _enqueue_if_needed(row, request, session)
    except (NotFoundError, SendServiceError) as exc:
        raise _send_error(exc) from exc


@router.post("/send-history/{send_history_id}/cancel", response_model=SendHistoryRead)
async def cancel_send_history(
    send_history_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    service = create_send_service(session, request)
    try:
        return await service.cancel_history(send_history_id)
    except (NotFoundError, SendServiceError) as exc:
        raise _send_error(exc) from exc
