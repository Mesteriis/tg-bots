from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.deps import get_session
from tg_bot_aggregator.domain.analytics.mtproto import MtprotoConfigurationError, MtprotoService
from tg_bot_aggregator.domain.analytics.repository import MtprotoSessionRepository
from tg_bot_aggregator.domain.analytics.schemas import (
    MtprotoCodeRequest,
    MtprotoLoginStartRequest,
    MtprotoPasswordRequest,
    MtprotoStatusRead,
)

router = APIRouter(prefix="/mtproto", tags=["mtproto"])


def _service(request: Request, session: AsyncSession) -> MtprotoService:
    return MtprotoService(request.app.state.settings, MtprotoSessionRepository(session))


@router.get("/status", response_model=MtprotoStatusRead)
async def status(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object | None]:
    return await _service(request, session).status()


@router.post("/login/start", response_model=MtprotoStatusRead)
async def start_login(
    payload: MtprotoLoginStartRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object | None]:
    try:
        result = await _service(request, session).start_login(payload.phone)
    except MtprotoConfigurationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    await request.app.state.event_bus.publish("mtproto.login.status_changed", result)
    return result


@router.post("/login/confirm-code", response_model=MtprotoStatusRead)
async def confirm_code(
    payload: MtprotoCodeRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object | None]:
    try:
        result = await _service(request, session).confirm_code(payload.phone, payload.code)
    except MtprotoConfigurationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    await request.app.state.event_bus.publish("mtproto.login.status_changed", result)
    return result


@router.post("/login/confirm-password", response_model=MtprotoStatusRead)
async def confirm_password(
    payload: MtprotoPasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object | None]:
    try:
        result = await _service(request, session).confirm_password(payload.password)
    except MtprotoConfigurationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    await request.app.state.event_bus.publish("mtproto.login.status_changed", result)
    return result
