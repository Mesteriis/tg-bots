from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.deps import get_bot_api_client, get_session, get_uow
from tg_bot_aggregator.domain.destinations.repository import (
    DestinationHealthRepository,
    DestinationRepository,
)
from tg_bot_aggregator.domain.destinations.schemas import (
    DestinationCheckRead,
    DestinationCreate,
    DestinationHealthRead,
    DestinationRead,
    DestinationUpdate,
)
from tg_bot_aggregator.infra.telegram_client import TelegramBotApiClient, TelegramBotApiError
from tg_bot_aggregator.infra.uow import UnitOfWork

router = APIRouter(prefix="/destinations", tags=["destinations"])


@router.get("", response_model=list[DestinationRead])
async def list_destinations(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await DestinationRepository(session).list()


@router.post("", response_model=DestinationRead, status_code=201)
async def create_destination(
    payload: DestinationCreate, uow: UnitOfWork = Depends(get_uow)
) -> object:
    try:
        row = await uow.destinations.create(**payload.model_dump())
    except IntegrityError as exc:
        await uow.rollback()
        raise HTTPException(
            status_code=409,
            detail="destination with this bot, chat and thread already exists",
        ) from exc
    await uow.commit()
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
    uow: UnitOfWork = Depends(get_uow),
) -> object:
    repo = uow.destinations
    if await repo.get(destination_id) is None:
        raise HTTPException(status_code=404, detail="destination not found")
    try:
        row = await repo.update(destination_id, **payload.model_dump(exclude_unset=True))
    except IntegrityError as exc:
        await uow.rollback()
        raise HTTPException(
            status_code=409,
            detail="destination with this bot, chat and thread already exists",
        ) from exc
    await uow.commit()
    return row


@router.delete("/{destination_id}", status_code=204)
async def delete_destination(
    destination_id: int, uow: UnitOfWork = Depends(get_uow)
) -> None:
    deleted = await uow.destinations.delete(destination_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="destination not found")
    await uow.commit()


@router.post("/{destination_id}/check", response_model=DestinationCheckRead)
async def check_destination(
    destination_id: int,
    uow: UnitOfWork = Depends(get_uow),
    bot_api: TelegramBotApiClient = Depends(get_bot_api_client),
) -> object:
    destinations = uow.destinations
    health = uow.destination_health
    destination = await destinations.get(destination_id)
    if destination is None:
        raise HTTPException(status_code=404, detail="destination not found")
    bot = await uow.bots.get(destination.bot_id)
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
        await uow.commit()
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
    await uow.commit()
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
