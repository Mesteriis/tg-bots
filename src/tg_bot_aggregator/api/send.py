from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import create_send_service, get_session
from tg_bot_aggregator.repositories import NotFoundError, SendHistoryRepository
from tg_bot_aggregator.schemas import (
    SendDryRunRead,
    SendFileRequest,
    SendHistoryRead,
    SendTemplateRequest,
    SendTextRequest,
)
from tg_bot_aggregator.send_service import IdempotencyConflictError, SendServiceError
from tg_bot_aggregator.template_renderer import TemplateRenderError

router = APIRouter(tags=["send"])


async def _enqueue_if_needed(row: object, request: Request, session: AsyncSession) -> object:
    if getattr(row, "status", None) != "queued" or getattr(row, "queued_task_id", None):
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
        return await service.dry_run_file(**data)
    except (NotFoundError, SendServiceError, TemplateRenderError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/send-history", response_model=list[SendHistoryRead])
async def list_send_history(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await SendHistoryRepository(session).list()
