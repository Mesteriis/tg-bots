from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import get_session
from tg_bot_aggregator.infra.audit import AuditRepository
from tg_bot_aggregator.schemas import AuditEventRead

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditEventRead])
async def list_audit_events(
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
) -> list[object]:
    return await AuditRepository(session).list(limit=limit)
