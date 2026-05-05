from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.deps import get_session
from tg_bot_aggregator.domain.audit.schemas import AuditEventRead
from tg_bot_aggregator.infra.audit import AuditRepository

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditEventRead])
async def list_audit_events(
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
) -> list[object]:
    return await AuditRepository(session).list(limit=limit)
