from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import get_session
from tg_bot_aggregator.audit import record_audit_event
from tg_bot_aggregator.domain.auth.service import (
    API_TOKEN_COOKIE,
    api_token_prefix,
    generate_api_token,
    hash_api_token,
    normalize_token_scopes,
)
from tg_bot_aggregator.repositories import ApiTokenRepository
from tg_bot_aggregator.schemas import (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenRead,
    ApiTokenSessionRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/tokens", response_model=list[ApiTokenRead])
async def list_api_tokens(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await ApiTokenRepository(session).list()


@router.post("/tokens", response_model=ApiTokenCreated, status_code=201)
async def create_api_token(
    payload: ApiTokenCreate,
    session: AsyncSession = Depends(get_session),
) -> ApiTokenCreated:
    token = generate_api_token()
    row = await ApiTokenRepository(session).create(
        name=payload.name,
        token_hash=hash_api_token(token),
        token_prefix=api_token_prefix(token),
        scopes_json=normalize_token_scopes(payload.scopes),
    )
    await record_audit_event(
        session,
        source="api",
        action="auth.tokens.create",
        status="succeeded",
        entity_type="api_token",
        entity_id=row.id,
        metadata={"scopes": row.scopes_json},
    )
    await session.commit()
    return ApiTokenCreated(
        id=row.id,
        name=row.name,
        token_prefix=row.token_prefix,
        scopes_json=row.scopes_json,
        is_active=row.is_active,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        token=token,
    )


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_api_token(
    token_id: int,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> None:
    deleted = await ApiTokenRepository(session).revoke(token_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="api token not found")
    await record_audit_event(
        session,
        source="api",
        action="auth.tokens.revoke",
        status="succeeded",
        entity_type="api_token",
        entity_id=token_id,
    )
    await session.commit()
    response.delete_cookie(API_TOKEN_COOKIE)


@router.post("/session", status_code=204)
async def create_api_token_session(
    payload: ApiTokenSessionRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await ApiTokenRepository(session).get_by_hash(hash_api_token(payload.token))
    if row is None or not row.is_active:
        raise HTTPException(status_code=401, detail="invalid api token")
    await ApiTokenRepository(session).mark_used(row)
    await record_audit_event(
        session,
        source="api",
        action="auth.session.create",
        status="succeeded",
        request=request,
        api_token_id=row.id,
    )
    await session.commit()
    secure = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").lower() == "https"
    )
    response.set_cookie(
        API_TOKEN_COOKIE,
        payload.token,
        httponly=True,
        secure=secure,
        samesite="lax",
    )
