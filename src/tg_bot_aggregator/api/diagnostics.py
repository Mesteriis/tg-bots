from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import get_session
from tg_bot_aggregator.models import DiagnosticBotSettings
from tg_bot_aggregator.repositories import BotRepository, DiagnosticSettingsRepository
from tg_bot_aggregator.schemas import DiagnosticBotSettingsRead, DiagnosticBotSettingsUpdate

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
