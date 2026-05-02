from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.repositories import AuditRepository
from tg_bot_aggregator.security import redact_secrets


async def record_audit_event(
    session: AsyncSession,
    *,
    source: str,
    action: str,
    status: str,
    request: Request | None = None,
    api_token_id: int | None = None,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await AuditRepository(session).create(
        source=source,
        action=action,
        status=status,
        api_token_id=api_token_id,
        host=_host(request) if request else None,
        path=request.url.path if request else None,
        method=request.method if request else None,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        request_id=request.headers.get("x-request-id") if request else None,
        message=message,
        metadata_json=redact_secrets(metadata) if metadata is not None else None,
    )


def _host(request: Request) -> str | None:
    return request.headers.get("x-forwarded-host") or request.headers.get("host")
