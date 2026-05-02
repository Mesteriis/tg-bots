from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import get_session
from tg_bot_aggregator.repositories import TemplateRepository
from tg_bot_aggregator.schemas import TemplateCreate, TemplateRead, TemplateUpdate

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateRead])
async def list_templates(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await TemplateRepository(session).list()


@router.post("", response_model=TemplateRead, status_code=201)
async def create_template(
    payload: TemplateCreate, session: AsyncSession = Depends(get_session)
) -> object:
    row = await TemplateRepository(session).create(**payload.model_dump())
    await session.commit()
    return row


@router.get("/{template_id}", response_model=TemplateRead)
async def get_template(template_id: int, session: AsyncSession = Depends(get_session)) -> object:
    row = await TemplateRepository(session).get(template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="template not found")
    return row


@router.patch("/{template_id}", response_model=TemplateRead)
async def update_template(
    template_id: int,
    payload: TemplateUpdate,
    session: AsyncSession = Depends(get_session),
) -> object:
    repo = TemplateRepository(session)
    if await repo.get(template_id) is None:
        raise HTTPException(status_code=404, detail="template not found")
    row = await repo.update(template_id, **payload.model_dump(exclude_unset=True))
    await session.commit()
    return row


@router.delete("/{template_id}", status_code=204)
async def delete_template(template_id: int, session: AsyncSession = Depends(get_session)) -> None:
    deleted = await TemplateRepository(session).delete(template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="template not found")
    await session.commit()

