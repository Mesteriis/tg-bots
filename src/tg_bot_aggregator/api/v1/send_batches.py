from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.deps import create_send_service, get_session, get_uow
from tg_bot_aggregator.core.errors import NotFoundError
from tg_bot_aggregator.domain.batches.repository import SendBatchRepository
from tg_bot_aggregator.domain.batches.schemas import (
    SendBatchCreate,
    SendBatchPreviewRead,
    SendBatchRead,
)
from tg_bot_aggregator.domain.batches.service import WorkflowService
from tg_bot_aggregator.domain.sending.service import SendServiceError
from tg_bot_aggregator.infra.uow import UnitOfWork

router = APIRouter(prefix="/send-batches", tags=["send-batches"])


def _serialize_item(item: object) -> dict[str, Any]:
    return {
        "id": item.id,
        "batch_id": item.batch_id,
        "destination_id": item.destination_id,
        "chat_id": item.chat_id,
        "message_thread_id": item.message_thread_id,
        "status": item.status,
        "send_history_id": item.send_history_id,
        "error_message": item.error_message,
    }


async def _serialize_batch(repo: SendBatchRepository, batch: object) -> dict[str, Any]:
    items = await repo.list_items(batch.id)
    progress: dict[str, int] = {"total": len(items)}
    for item in items:
        progress[item.status] = progress.get(item.status, 0) + 1
    return {
        "id": batch.id,
        "name": batch.name,
        "description": batch.description,
        "bot_id": batch.bot_id,
        "send_kind": batch.send_kind,
        "status": batch.status,
        "template_tag": batch.template_tag,
        "text": batch.text,
        "media_type": batch.media_type,
        "file_relative_path": batch.file_relative_path,
        "caption": batch.caption,
        "parse_mode": batch.parse_mode,
        "disable_web_page_preview": batch.disable_web_page_preview,
        "variables": batch.variables_json or {},
        "progress": progress,
        "items": [_serialize_item(item) for item in items],
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
        "queued_at": batch.queued_at,
        "finished_at": batch.finished_at,
    }


async def _create_batch_items(
    uow: UnitOfWork,
    repo: SendBatchRepository,
    batch_id: int,
    bot_id: int,
    destination_ids: list[int],
    chat_ids: list[str],
) -> None:
    destinations = uow.destinations
    for destination_id in destination_ids:
        destination = await destinations.get(destination_id)
        if destination is None or destination.bot_id != bot_id:
            raise HTTPException(status_code=400, detail="destination not found")
        await repo.add_item(
            batch_id,
            destination_id=destination.id,
            chat_id=destination.chat_id,
            message_thread_id=destination.message_thread_id,
        )
    for chat_id in chat_ids:
        if chat_id.strip():
            await repo.add_item(batch_id, chat_id=chat_id.strip())


@router.get("", response_model=list[SendBatchRead])
async def list_send_batches(session: AsyncSession = Depends(get_session)) -> list[object]:
    repo = SendBatchRepository(session)
    rows = await repo.list_batches()
    return [await _serialize_batch(repo, row) for row in rows]


@router.post("", response_model=SendBatchRead, status_code=201)
async def create_send_batch(
    payload: SendBatchCreate,
    uow: UnitOfWork = Depends(get_uow),
) -> object:
    if await uow.bots.get(payload.bot_id) is None:
        raise HTTPException(status_code=400, detail="bot not found")
    if not payload.destination_ids and not payload.chat_ids:
        raise HTTPException(status_code=400, detail="at least one destination is required")
    repo = uow.batches
    batch = await repo.create_batch(
        name=payload.name,
        description=payload.description,
        bot_id=payload.bot_id,
        send_kind=payload.send_kind,
        template_tag=payload.template_tag,
        text=payload.text,
        media_type=payload.media_type,
        file_relative_path=payload.file_relative_path,
        caption=payload.caption,
        parse_mode=payload.parse_mode,
        disable_web_page_preview=payload.disable_web_page_preview,
        variables_json=payload.variables,
    )
    await _create_batch_items(
        uow,
        repo,
        batch.id,
        payload.bot_id,
        payload.destination_ids,
        payload.chat_ids,
    )
    await uow.commit()
    return await _serialize_batch(repo, batch)


@router.get("/{batch_id}", response_model=SendBatchRead)
async def get_send_batch(
    batch_id: int,
    session: AsyncSession = Depends(get_session),
) -> object:
    repo = SendBatchRepository(session)
    batch = await repo.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="send batch not found")
    return await _serialize_batch(repo, batch)


@router.post("/{batch_id}/preview", response_model=SendBatchPreviewRead)
async def preview_send_batch(
    batch_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    service = WorkflowService(create_send_service(session, request))
    try:
        return await service.preview_batch(batch_id)
    except (NotFoundError, SendServiceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{batch_id}/enqueue", response_model=SendBatchRead)
async def enqueue_send_batch(
    batch_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    service = WorkflowService(create_send_service(session, request))
    try:
        batch = await service.enqueue_batch(batch_id)
    except (NotFoundError, SendServiceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _serialize_batch(SendBatchRepository(session), batch)


@router.post("/{batch_id}/cancel", response_model=SendBatchRead)
async def cancel_send_batch(
    batch_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    service = WorkflowService(create_send_service(session, request))
    try:
        batch = await service.cancel_batch(batch_id)
    except (NotFoundError, SendServiceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _serialize_batch(SendBatchRepository(session), batch)
