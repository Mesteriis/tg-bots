from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import get_bot_api_client, get_session
from tg_bot_aggregator.domain.bots.repository import BotRepository
from tg_bot_aggregator.infra.telegram_client import TelegramBotApiClient, TelegramBotApiError
from tg_bot_aggregator.schemas import BotCreate, BotRead, BotUpdate

router = APIRouter(prefix="/bots", tags=["bots"])


@router.get("", response_model=list[BotRead])
async def list_bots(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await BotRepository(session).list()


@router.post("", response_model=BotRead, status_code=201)
async def create_bot(
    payload: BotCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    bot_api: TelegramBotApiClient = Depends(get_bot_api_client),
) -> object:
    try:
        response = await bot_api.get_me(payload.token)
    except TelegramBotApiError as exc:
        raise HTTPException(status_code=502, detail=exc.description) from exc

    result = response.get("result", {})
    username = result.get("username")
    fallback_name = (
        f"@{username}"
        if username
        else result.get("first_name") or f"bot-{result.get('id')}"
    )
    bot = await BotRepository(session).create(
        name=payload.name or fallback_name,
        token=payload.token,
        username=username,
        telegram_bot_id=result.get("id"),
        description=payload.description,
        is_active=payload.is_active,
        last_checked_at=datetime.now(UTC),
    )
    await session.commit()
    await request.app.state.event_bus.publish("bot.checked", {"bot_id": bot.id})
    return bot


@router.get("/{bot_id}", response_model=BotRead)
async def get_bot(bot_id: int, session: AsyncSession = Depends(get_session)) -> object:
    bot = await BotRepository(session).get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")
    return bot


@router.patch("/{bot_id}", response_model=BotRead)
async def update_bot(
    bot_id: int, payload: BotUpdate, session: AsyncSession = Depends(get_session)
) -> object:
    repo = BotRepository(session)
    bot = await repo.get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")
    updated = await repo.update(bot_id, **payload.model_dump(exclude_unset=True))
    await session.commit()
    return updated


@router.delete("/{bot_id}", status_code=204)
async def delete_bot(bot_id: int, session: AsyncSession = Depends(get_session)) -> None:
    deleted = await BotRepository(session).delete(bot_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="bot not found")
    await session.commit()


@router.post("/{bot_id}/check", response_model=BotRead)
async def check_bot(
    bot_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    bot_api: TelegramBotApiClient = Depends(get_bot_api_client),
) -> object:
    repo = BotRepository(session)
    bot = await repo.get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")
    try:
        response = await bot_api.get_me(bot.token)
    except TelegramBotApiError as exc:
        raise HTTPException(status_code=502, detail=exc.description) from exc
    result = response.get("result", {})
    updated = await repo.update(
        bot_id,
        username=result.get("username"),
        telegram_bot_id=result.get("id"),
        last_checked_at=datetime.now(UTC),
    )
    await session.commit()
    await request.app.state.event_bus.publish("bot.checked", {"bot_id": bot_id})
    return updated
