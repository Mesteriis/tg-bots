from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.core.errors import NotFoundError
from tg_bot_aggregator.domain.templates.models import (
    MessageTemplate,
    MessageTemplateVersion,
    utc_now,
)


async def _get_or_none(session: AsyncSession, model: type[Any], row_id: int) -> Any | None:
    return await session.get(model, row_id)


async def _list(session: AsyncSession, statement: Select[tuple[Any]]) -> list[Any]:
    return list((await session.execute(statement)).scalars().all())


def _optional_equals(column: Any, value: Any) -> Any:
    return column.is_(None) if value is None else column == value


def _ops_fact_identity_key(values: dict[str, Any]) -> str:
    identity = [
        values["fact_type"],
        values.get("bot_id"),
        values.get("chat_id"),
        values.get("message_thread_id"),
        values["source"],
    ]
    payload = json.dumps(identity, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> MessageTemplate:
        template = MessageTemplate(**values)
        self.session.add(template)
        await self.session.flush()
        return template

    async def list(self) -> list[MessageTemplate]:
        return await _list(self.session, select(MessageTemplate).order_by(MessageTemplate.id))

    async def get(self, template_id: int) -> MessageTemplate | None:
        return await _get_or_none(self.session, MessageTemplate, template_id)

    async def get_by_tag(self, tag: str) -> MessageTemplate | None:
        statement = select(MessageTemplate).where(MessageTemplate.tag == tag)
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def update(self, template_id: int, **values: Any) -> MessageTemplate:
        template = await self.get(template_id)
        if template is None:
            raise NotFoundError(f"template {template_id} not found")
        for key, value in values.items():
            setattr(template, key, value)
        template.updated_at = utc_now()
        await self.session.flush()
        return template

    async def delete(self, template_id: int) -> bool:
        template = await self.get(template_id)
        if template is None:
            return False
        await self.session.delete(template)
        await self.session.flush()
        return True

class TemplateVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_version_number(self, template_id: int) -> int:
        statement = select(func.max(MessageTemplateVersion.version_number)).where(
            MessageTemplateVersion.template_id == template_id
        )
        current = (await self.session.execute(statement)).scalar_one()
        return int(current or 0) + 1

    async def create_from_template(self, template: MessageTemplate) -> MessageTemplateVersion:
        row = MessageTemplateVersion(
            template_id=template.id,
            version_number=await self.next_version_number(template.id),
            title=template.title,
            text=template.text,
            parse_mode=template.parse_mode,
            disable_web_page_preview=template.disable_web_page_preview,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_for_template(self, template_id: int) -> list[MessageTemplateVersion]:
        statement = (
            select(MessageTemplateVersion)
            .where(MessageTemplateVersion.template_id == template_id)
            .order_by(MessageTemplateVersion.version_number)
        )
        return await _list(self.session, statement)

    async def get(self, version_id: int) -> MessageTemplateVersion | None:
        return await _get_or_none(self.session, MessageTemplateVersion, version_id)

__all__ = [
    "TemplateRepository",
    "TemplateVersionRepository",
]
