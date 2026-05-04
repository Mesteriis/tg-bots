from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import get_session
from tg_bot_aggregator.domain.bots.repository import BotRepository
from tg_bot_aggregator.domain.destinations.repository import DestinationRepository
from tg_bot_aggregator.domain.diagnostics.repository import (
    DiagnosticSettingsRepository,
    DiagnosticUpdateRepository,
)
from tg_bot_aggregator.models import DiagnosticBotSettings
from tg_bot_aggregator.schemas import (
    DestinationRead,
    DiagnosticBotSettingsRead,
    DiagnosticBotSettingsUpdate,
    DiagnosticDestinationCreate,
    DiagnosticUpdateCreate,
    DiagnosticUpdateRead,
)

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


def _read_model(
    settings: DiagnosticBotSettings | None,
    bot_name: str | None = None,
    bot_username: str | None = None,
) -> DiagnosticBotSettingsRead:
    if settings is None:
        return DiagnosticBotSettingsRead(
            bot_id=None,
            bot_name=None,
            bot_username=None,
            is_enabled=False,
            last_update_id=None,
            last_error=None,
            updated_at=None,
        )
    return DiagnosticBotSettingsRead(
        bot_id=settings.bot_id,
        bot_name=bot_name,
        bot_username=bot_username,
        is_enabled=settings.is_enabled,
        last_update_id=settings.last_update_id,
        last_error=settings.last_error,
        updated_at=settings.updated_at,
    )


@router.get("/bot", response_model=DiagnosticBotSettingsRead)
async def get_diagnostic_bot(
    session: AsyncSession = Depends(get_session),
) -> DiagnosticBotSettingsRead:
    settings = await DiagnosticSettingsRepository(session).get()
    bot_name = None
    bot_username = None
    if settings is not None and settings.bot_id is not None:
        bot = await BotRepository(session).get(settings.bot_id)
        if bot is not None:
            bot_name = bot.name
            bot_username = bot.username
    return _read_model(settings, bot_name=bot_name, bot_username=bot_username)


@router.get("/updates", response_model=list[DiagnosticUpdateRead])
async def list_diagnostic_updates(
    session: AsyncSession = Depends(get_session),
) -> list[object]:
    return await DiagnosticUpdateRepository(session).list()


@router.post("/updates", response_model=DiagnosticUpdateRead, status_code=201)
async def create_diagnostic_update(
    payload: DiagnosticUpdateCreate,
    session: AsyncSession = Depends(get_session),
) -> object:
    values = payload.model_dump()
    values["raw_update_json"] = values.pop("raw_update")
    row = await DiagnosticUpdateRepository(session).create(**values)
    await session.commit()
    return row


@router.post("/updates/{update_id}/destination", response_model=DestinationRead)
async def create_destination_from_diagnostic_update(
    update_id: int,
    payload: DiagnosticDestinationCreate,
    session: AsyncSession = Depends(get_session),
) -> object:
    update = await DiagnosticUpdateRepository(session).get(update_id)
    if update is None:
        raise HTTPException(status_code=404, detail="diagnostic update not found")
    if update.chat_id is None:
        raise HTTPException(status_code=400, detail="diagnostic update has no chat_id")
    if await BotRepository(session).get(payload.bot_id) is None:
        raise HTTPException(status_code=404, detail="bot not found")
    kind = "forum_topic" if update.message_thread_id is not None else update.chat_type or "group"
    if kind not in {"private", "group", "supergroup", "channel", "forum_topic"}:
        kind = "group"
    destination = await DestinationRepository(session).upsert_by_chat(
        bot_id=payload.bot_id,
        chat_id=update.chat_id,
        message_thread_id=update.message_thread_id,
        kind=kind,
        alias=payload.alias,
        title=update.chat_title,
        username=update.chat_username,
        is_active=True,
    )
    await session.commit()
    return destination


@router.patch("/bot", response_model=DiagnosticBotSettingsRead)
async def update_diagnostic_bot(
    payload: DiagnosticBotSettingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> DiagnosticBotSettingsRead:
    values = payload.model_dump(exclude_unset=True)
    bot_name = None
    bot_username = None
    if "bot_id" in values and values["bot_id"] is not None:
        bot = await BotRepository(session).get(values["bot_id"])
        if bot is None:
            raise HTTPException(status_code=404, detail="bot not found")
        bot_name = bot.name
        bot_username = bot.username
    elif "bot_id" not in values:
        existing = await DiagnosticSettingsRepository(session).get()
        if existing is not None and existing.bot_id is not None:
            bot = await BotRepository(session).get(existing.bot_id)
            if bot is not None:
                bot_name = bot.name
                bot_username = bot.username

    settings = await DiagnosticSettingsRepository(session).upsert(**values)
    await session.commit()
    return _read_model(settings, bot_name=bot_name, bot_username=bot_username)
