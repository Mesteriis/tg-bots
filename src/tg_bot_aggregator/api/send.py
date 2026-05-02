from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import create_send_service, get_session
from tg_bot_aggregator.repositories import NotFoundError, SendHistoryRepository
from tg_bot_aggregator.schemas import (
    SendFileRequest,
    SendHistoryRead,
    SendTemplateRequest,
    SendTextRequest,
)
from tg_bot_aggregator.send_service import SendServiceError

router = APIRouter(tags=["send"])


@router.post("/send/text", response_model=SendHistoryRead)
async def send_text(
    payload: SendTextRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    service = create_send_service(session, request)
    try:
        return await service.send_text(**payload.model_dump())
    except (NotFoundError, SendServiceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/send/template", response_model=SendHistoryRead)
async def send_template(
    payload: SendTemplateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    service = create_send_service(session, request)
    try:
        return await service.send_template(**payload.model_dump())
    except (NotFoundError, SendServiceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/send/file", response_model=SendHistoryRead)
async def send_file(
    payload: SendFileRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    service = create_send_service(session, request)
    try:
        return await service.send_file(**payload.model_dump())
    except (NotFoundError, SendServiceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/send-history", response_model=list[SendHistoryRead])
async def list_send_history(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await SendHistoryRepository(session).list()

