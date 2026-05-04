from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import get_session
from tg_bot_aggregator.domain.bots.repository import BotRepository
from tg_bot_aggregator.domain.discovery.repository import (
    BotDiscoveryEventRepository,
    BotDiscoverySettingsRepository,
)
from tg_bot_aggregator.schemas import (
    BotDiscoveryEventRead,
    BotDiscoverySettingsRead,
    BotDiscoverySettingsUpdate,
)

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/bots", response_model=list[BotDiscoverySettingsRead])
async def list_discovery_settings(
    session: AsyncSession = Depends(get_session),
) -> list[object]:
    return await BotDiscoverySettingsRepository(session).list()


@router.patch("/bots/{bot_id}", response_model=BotDiscoverySettingsRead)
async def update_discovery_settings(
    bot_id: int,
    payload: BotDiscoverySettingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> object:
    bot = await BotRepository(session).get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")
    values = payload.model_dump(exclude_unset=True)
    row = await BotDiscoverySettingsRepository(session).upsert_for_bot(bot_id, **values)
    await session.commit()
    return row


@router.get("/events", response_model=list[BotDiscoveryEventRead])
async def list_discovery_events(
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
) -> list[object]:
    return await BotDiscoveryEventRepository(session).list(limit=limit)
