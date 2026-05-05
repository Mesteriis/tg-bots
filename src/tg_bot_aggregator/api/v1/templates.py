from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.deps import get_session, get_uow
from tg_bot_aggregator.domain.templates.renderer import validate_template_text
from tg_bot_aggregator.domain.templates.repository import (
    TemplateRepository,
    TemplateVersionRepository,
)
from tg_bot_aggregator.domain.templates.schemas import (
    TemplateCreate,
    TemplateRead,
    TemplateUpdate,
    TemplateValidateRead,
    TemplateValidateRequest,
    TemplateVersionRead,
)
from tg_bot_aggregator.infra.uow import UnitOfWork

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateRead])
async def list_templates(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await TemplateRepository(session).list()


@router.post("", response_model=TemplateRead, status_code=201)
async def create_template(
    payload: TemplateCreate, uow: UnitOfWork = Depends(get_uow)
) -> object:
    repo = uow.templates
    row = await repo.create(**payload.model_dump())
    await uow.template_versions.create_from_template(row)
    await uow.commit()
    return row


@router.post("/validate", response_model=TemplateValidateRead)
async def validate_template(payload: TemplateValidateRequest) -> TemplateValidateRead:
    result = validate_template_text(payload.text, payload.variables)
    return TemplateValidateRead(
        ok=result.ok,
        variables=result.variables,
        missing_variables=result.missing_variables,
        rendered_text=result.rendered_text,
        error_message=result.error_message,
    )


@router.get("/{template_id}", response_model=TemplateRead)
async def get_template(template_id: int, session: AsyncSession = Depends(get_session)) -> object:
    row = await TemplateRepository(session).get(template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="template not found")
    return row


@router.get("/{template_id}/versions", response_model=list[TemplateVersionRead])
async def list_template_versions(
    template_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[object]:
    if await TemplateRepository(session).get(template_id) is None:
        raise HTTPException(status_code=404, detail="template not found")
    return await TemplateVersionRepository(session).list_for_template(template_id)


@router.post("/{template_id}/rollback/{version_id}", response_model=TemplateRead)
async def rollback_template(
    template_id: int,
    version_id: int,
    uow: UnitOfWork = Depends(get_uow),
) -> object:
    templates = uow.templates
    versions = uow.template_versions
    template = await templates.get(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")
    version = await versions.get(version_id)
    if version is None or version.template_id != template_id:
        raise HTTPException(status_code=404, detail="template version not found")
    row = await templates.update(
        template_id,
        title=version.title,
        text=version.text,
        parse_mode=version.parse_mode,
        disable_web_page_preview=version.disable_web_page_preview,
    )
    await versions.create_from_template(row)
    await uow.commit()
    return row


@router.patch("/{template_id}", response_model=TemplateRead)
async def update_template(
    template_id: int,
    payload: TemplateUpdate,
    uow: UnitOfWork = Depends(get_uow),
) -> object:
    repo = uow.templates
    if await repo.get(template_id) is None:
        raise HTTPException(status_code=404, detail="template not found")
    row = await repo.update(template_id, **payload.model_dump(exclude_unset=True))
    await uow.template_versions.create_from_template(row)
    await uow.commit()
    return row


@router.delete("/{template_id}", status_code=204)
async def delete_template(template_id: int, uow: UnitOfWork = Depends(get_uow)) -> None:
    deleted = await uow.templates.delete(template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="template not found")
    await uow.commit()
