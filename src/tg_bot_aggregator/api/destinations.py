from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import get_session
from tg_bot_aggregator.repositories import DestinationRepository
from tg_bot_aggregator.schemas import DestinationCreate, DestinationRead, DestinationUpdate

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

