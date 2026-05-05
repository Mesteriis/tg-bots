from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.deps import get_session, get_uow
from tg_bot_aggregator.domain.sending.repository import SendProfileRepository
from tg_bot_aggregator.domain.sending.schemas import (
    SendProfileCreate,
    SendProfileRead,
    SendProfileUpdate,
)
from tg_bot_aggregator.infra.uow import UnitOfWork

router = APIRouter(prefix="/send-profiles", tags=["send-profiles"])


def _profile_values(payload: SendProfileCreate | SendProfileUpdate) -> dict[str, object]:
    values = payload.model_dump(exclude_unset=True)
    if "variables" in values:
        values["variables_json"] = values.pop("variables")
    return values


async def _validate_refs(uow: UnitOfWork, values: dict[str, object]) -> None:
    bot_id = values.get("bot_id")
    if isinstance(bot_id, int) and await uow.bots.get(bot_id) is None:
        raise HTTPException(status_code=400, detail="bot not found")

    destination_id = values.get("destination_id")
    if isinstance(destination_id, int):
        destination = await uow.destinations.get(destination_id)
        if destination is None:
            raise HTTPException(status_code=400, detail="destination not found")
        if isinstance(bot_id, int) and destination.bot_id != bot_id:
            raise HTTPException(status_code=400, detail="destination belongs to another bot")


@router.get("", response_model=list[SendProfileRead])
async def list_send_profiles(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await SendProfileRepository(session).list()


@router.post("", response_model=SendProfileRead, status_code=201)
async def create_send_profile(
    payload: SendProfileCreate,
    uow: UnitOfWork = Depends(get_uow),
) -> object:
    values = _profile_values(payload)
    await _validate_refs(uow, values)
    row = await uow.profiles.create(**values)
    await uow.commit()
    return row


@router.get("/{profile_id}", response_model=SendProfileRead)
async def get_send_profile(
    profile_id: int,
    session: AsyncSession = Depends(get_session),
) -> object:
    row = await SendProfileRepository(session).get(profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="send profile not found")
    return row


@router.patch("/{profile_id}", response_model=SendProfileRead)
async def update_send_profile(
    profile_id: int,
    payload: SendProfileUpdate,
    uow: UnitOfWork = Depends(get_uow),
) -> object:
    repo = uow.profiles
    current = await repo.get(profile_id)
    if current is None:
        raise HTTPException(status_code=404, detail="send profile not found")
    values = _profile_values(payload)
    merged_refs = {
        "bot_id": values.get("bot_id", current.bot_id),
        "destination_id": values.get("destination_id", current.destination_id),
    }
    await _validate_refs(uow, merged_refs)
    row = await repo.update(profile_id, **values)
    await uow.commit()
    return row


@router.delete("/{profile_id}", status_code=204)
async def delete_send_profile(
    profile_id: int,
    uow: UnitOfWork = Depends(get_uow),
) -> None:
    deleted = await uow.profiles.delete(profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="send profile not found")
    await uow.commit()
