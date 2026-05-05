from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.domain.audit.models import AuditEvent


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> AuditEvent:
        row = AuditEvent(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self, limit: int = 100) -> list[AuditEvent]:
        statement = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
        return list((await self.session.execute(statement)).scalars().all())


__all__ = ["AuditRepository"]
