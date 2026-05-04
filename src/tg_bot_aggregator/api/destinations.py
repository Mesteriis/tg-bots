from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import get_bot_api_client, get_session
from tg_bot_aggregator.infra.telegram_client import TelegramBotApiClient, TelegramBotApiError
from tg_bot_aggregator.repositories import (
    BotRepository,
    DestinationHealthRepository,
    DestinationRepository,
)
from tg_bot_aggregator.schemas import (
    DestinationCheckRead,
    DestinationCreate,
    DestinationHealthRead,
    DestinationRead,
    DestinationUpdate,
)

router = APIRouter(prefix="/destinations", tags=["destinations"])


@router.get("", response_model=list[DestinationRead])
async def list_destinations(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await DestinationRepository(session).list()


@router.post("", response_model=DestinationRead, status_code=201)
async def create_destination(
    payload: DestinationCreate, session: AsyncSession = Depends(get_session)
) -> object:
    row = await DestinationRepository(session).create(**payload.model_dump())
    await session.commit()
    return row


@router.get("/{destination_id}", response_model=DestinationRead)
async def get_destination(
    destination_id: int, session: AsyncSession = Depends(get_session)
) -> object:
    row = await DestinationRepository(session).get(destination_id)
    if row is None:
        raise HTTPException(status_code=404, detail="destination not found")
    return row


@router.patch("/{destination_id}", response_model=DestinationRead)
async def update_destination(
    destination_id: int,
    payload: DestinationUpdate,
    session: AsyncSession = Depends(get_session),
) -> object:
    repo = DestinationRepository(session)
    if await repo.get(destination_id) is None:
        raise HTTPException(status_code=404, detail="destination not found")
    row = await repo.update(destination_id, **payload.model_dump(exclude_unset=True))
    await session.commit()
    return row


@router.delete("/{destination_id}", status_code=204)
async def delete_destination(
    destination_id: int, session: AsyncSession = Depends(get_session)
) -> None:
    deleted = await DestinationRepository(session).delete(destination_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="destination not found")
    await session.commit()


@router.post("/{destination_id}/check", response_model=DestinationCheckRead)
async def check_destination(
    destination_id: int,
    session: AsyncSession = Depends(get_session),
    bot_api: TelegramBotApiClient = Depends(get_bot_api_client),
) -> object:
    destinations = DestinationRepository(session)
    health = DestinationHealthRepository(session)
    destination = await destinations.get(destination_id)
    if destination is None:
        raise HTTPException(status_code=404, detail="destination not found")
    bot = await BotRepository(session).get(destination.bot_id)
    if bot is None or not bot.is_active:
        raise HTTPException(status_code=400, detail="destination bot is missing or inactive")

    warnings: list[str] = []
    try:
        chat_response = await bot_api.get_chat(bot.token, destination.chat_id)
    except TelegramBotApiError as exc:
        await health.upsert_for_destination(
            destination_id,
            status="failed",
            last_error=exc.description,
            last_member_count=None,
            raw_chat_json=None,
        )
        await session.commit()
        raise HTTPException(status_code=502, detail=exc.description) from exc

    chat = chat_response.get("result")
    if not isinstance(chat, dict):
        chat = {}
    kind = str(chat.get("type") or destination.kind)
    if destination.message_thread_id is not None:
        kind = "forum_topic"
    await destinations.update(
        destination_id,
        kind=kind,
        title=chat.get("title") or chat.get("first_name") or destination.title,
        username=chat.get("username") or destination.username,
        is_active=True,
    )

    member_count: int | None = None
    try:
        member_count = await bot_api.get_chat_member_count(bot.token, destination.chat_id)
    except TelegramBotApiError as exc:
        warnings.append(exc.description)

    await health.upsert_for_destination(
        destination_id,
        status="ok",
        last_error="; ".join(warnings) if warnings else None,
        last_member_count=member_count,
        raw_chat_json=chat,
    )
    await session.commit()
    return {
        "destination_id": destination_id,
        "ok": True,
        "chat": chat,
        "member_count": member_count,
        "warnings": warnings,
    }


@router.get("/{destination_id}/health", response_model=DestinationHealthRead)
async def get_destination_health(
    destination_id: int,
    session: AsyncSession = Depends(get_session),
) -> object:
    if await DestinationRepository(session).get(destination_id) is None:
        raise HTTPException(status_code=404, detail="destination not found")
    row = await DestinationHealthRepository(session).get_for_destination(destination_id)
    if row is None:
        raise HTTPException(status_code=404, detail="destination health not found")
    return row
