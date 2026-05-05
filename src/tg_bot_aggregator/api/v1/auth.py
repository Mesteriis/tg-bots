from dataclasses import asdict
from time import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import options_to_json
from webauthn.helpers.structs import AuthenticatorTransport, PublicKeyCredentialDescriptor

from tg_bot_aggregator.api.deps import get_session, get_uow
from tg_bot_aggregator.audit import record_audit_event
from tg_bot_aggregator.core.security import (
    base64url_decode,
    base64url_encode,
    generate_secret_token,
    normalize_host,
)
from tg_bot_aggregator.domain.auth.admin_service import (
    ADMIN_SESSION_COOKIE,
    AdminAuthService,
    BootstrapRequiredError,
    InvalidCredentialsError,
)
from tg_bot_aggregator.domain.auth.repository import ApiTokenRepository
from tg_bot_aggregator.domain.auth.schemas import (
    AdminAuthStateRead,
    AdminBootstrapRotateRequest,
    AdminChangeCredentialsRequest,
    AdminLoginRequest,
    AdminPasskeyAuthOptionsRead,
    AdminPasskeyRead,
    AdminPasskeyRegisterOptionsRead,
    AdminPasskeyRegisterOptionsRequest,
    AdminPasskeyVerifyRequest,
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenRead,
    ApiTokenSessionRequest,
)
from tg_bot_aggregator.domain.auth.service import (
    API_TOKEN_COOKIE,
    api_token_prefix,
    generate_api_token,
    hash_api_token,
    normalize_token_scopes,
)
from tg_bot_aggregator.infra.uow import UnitOfWork

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_admin_session_cookie(request: Request, response: Response, token: str) -> None:
    secure = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").lower() == "https"
    )
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
    )


def _admin_auth_service(request: Request) -> AdminAuthService:
    return AdminAuthService(request.app.state.settings)


def _admin_state_read(state) -> AdminAuthStateRead:
    return AdminAuthStateRead(**asdict(state))


def _current_admin_token(request: Request) -> str | None:
    return request.cookies.get(ADMIN_SESSION_COOKIE)


def _require_admin_session(request: Request) -> None:
    try:
        _admin_auth_service(request).require_authenticated(_current_admin_token(request))
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error


def _current_rp_id_and_origin(request: Request) -> tuple[str, str]:
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    scheme = forwarded_proto or request.url.scheme or "http"
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
    )
    rp_id = normalize_host(host)
    if not host or not rp_id:
        raise HTTPException(status_code=400, detail="unable to resolve passkey origin")
    return rp_id, f"{scheme}://{host}"


def _challenge_store(request: Request) -> dict[str, dict]:
    store = request.app.state.admin_webauthn_challenges
    now_ts = int(time())
    expired = [
        challenge_id
        for challenge_id, item in store.items()
        if int(item.get("expires_at", 0)) <= now_ts
    ]
    for challenge_id in expired:
        store.pop(challenge_id, None)
    return store


def _issue_challenge(
    request: Request,
    *,
    kind: str,
    rp_id: str,
    origin: str,
    challenge: bytes,
    label: str | None = None,
) -> str:
    challenge_id = generate_secret_token(16)
    _challenge_store(request)[challenge_id] = {
        "kind": kind,
        "rp_id": rp_id,
        "origin": origin,
        "challenge": challenge,
        "label": label,
        "expires_at": int(time()) + 300,
    }
    return challenge_id


def _consume_challenge(
    request: Request,
    challenge_id: str,
    *,
    expected_kind: str,
) -> dict:
    item = _challenge_store(request).pop(challenge_id, None)
    if item is None or item.get("kind") != expected_kind:
        raise HTTPException(status_code=409, detail="passkey challenge is missing or expired")
    if int(item.get("expires_at", 0)) <= int(time()):
        raise HTTPException(status_code=409, detail="passkey challenge is missing or expired")
    return item


def _descriptor_transports(transports: list[str]) -> list[AuthenticatorTransport]:
    values: list[AuthenticatorTransport] = []
    for item in transports:
        try:
            values.append(AuthenticatorTransport(item))
        except ValueError:
            continue
    return values


def _passkey_read(item) -> AdminPasskeyRead:
    return AdminPasskeyRead(**asdict(item))


@router.get("/admin/state", response_model=AdminAuthStateRead)
async def get_admin_state(request: Request) -> AdminAuthStateRead:
    state = _admin_auth_service(request).state_from_session_token(
        request.cookies.get(ADMIN_SESSION_COOKIE)
    )
    return _admin_state_read(state)


@router.post("/admin/login", response_model=AdminAuthStateRead)
async def admin_login(
    payload: AdminLoginRequest,
    request: Request,
    response: Response,
) -> AdminAuthStateRead:
    try:
        state, token = _admin_auth_service(request).verify_login(payload.username, payload.password)
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    if token:
        _set_admin_session_cookie(request, response, token)
    return _admin_state_read(state)


@router.post("/admin/bootstrap", status_code=204)
async def admin_bootstrap_rotate(
    payload: AdminBootstrapRotateRequest,
    request: Request,
    response: Response,
) -> None:
    try:
        _, token = _admin_auth_service(request).bootstrap_rotate(
            current_username=payload.current_username,
            current_password=payload.current_password,
            new_username=payload.new_username,
            new_password=payload.new_password,
        )
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    _set_admin_session_cookie(request, response, token)


@router.post("/admin/change", response_model=AdminAuthStateRead)
async def admin_change_credentials(
    payload: AdminChangeCredentialsRequest,
    request: Request,
    response: Response,
) -> AdminAuthStateRead:
    try:
        _admin_auth_service(request).require_authenticated(request.cookies.get(ADMIN_SESSION_COOKIE))
        state, token = _admin_auth_service(request).change_credentials(
            current_password=payload.current_password,
            new_username=payload.new_username,
            new_password=payload.new_password,
        )
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except BootstrapRequiredError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    _set_admin_session_cookie(request, response, token)
    return _admin_state_read(state)


@router.post("/admin/logout", status_code=204)
async def admin_logout(response: Response) -> None:
    response.delete_cookie(ADMIN_SESSION_COOKIE)


@router.get("/admin/passkeys", response_model=list[AdminPasskeyRead])
async def list_admin_passkeys(request: Request) -> list[AdminPasskeyRead]:
    _require_admin_session(request)
    return [_passkey_read(item) for item in _admin_auth_service(request).list_passkeys()]


@router.post(
    "/admin/passkeys/register/options",
    response_model=AdminPasskeyRegisterOptionsRead,
)
async def admin_passkey_register_options(
    payload: AdminPasskeyRegisterOptionsRequest,
    request: Request,
) -> AdminPasskeyRegisterOptionsRead:
    _require_admin_session(request)
    service = _admin_auth_service(request)
    record = service.require_configured_record()
    rp_id, origin = _current_rp_id_and_origin(request)
    challenge = base64url_decode(generate_secret_token(24))
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name="Telegram Bot Aggregator",
        user_name=record.username,
        user_id=record.user_handle.encode("utf-8"),
        user_display_name=record.username,
        challenge=challenge,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(
                id=base64url_decode(item.credential_id),
                transports=_descriptor_transports(item.transports),
            )
            for item in service.list_passkeys_for_rp(rp_id)
        ]
        or None,
    )
    challenge_id = _issue_challenge(
        request,
        kind="register",
        rp_id=rp_id,
        origin=origin,
        challenge=challenge,
        label=payload.label,
    )
    return AdminPasskeyRegisterOptionsRead(
        challenge_id=challenge_id,
        options_json=options_to_json(options),
        rp_id=rp_id,
        origin=origin,
    )


@router.post(
    "/admin/passkeys/register/verify",
    response_model=AdminPasskeyRead,
    status_code=201,
)
async def admin_passkey_register_verify(
    payload: AdminPasskeyVerifyRequest,
    request: Request,
) -> AdminPasskeyRead:
    _require_admin_session(request)
    service = _admin_auth_service(request)
    service.require_configured_record()
    context = _consume_challenge(request, payload.challenge_id, expected_kind="register")
    credential_id = payload.credential.get("id")
    if not isinstance(credential_id, str) or not credential_id:
        raise HTTPException(status_code=400, detail="passkey credential id is required")
    try:
        verified = verify_registration_response(
            credential=payload.credential,
            expected_challenge=context["challenge"],
            expected_rp_id=context["rp_id"],
            expected_origin=context["origin"],
            require_user_verification=True,
        )
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail=f"passkey registration failed: {error}",
        ) from error
    transports = payload.credential.get("response", {}).get("transports", [])
    if not isinstance(transports, list):
        transports = []
    created = service.add_passkey(
        credential_id=credential_id,
        public_key=base64url_encode(verified.credential_public_key),
        sign_count=int(verified.sign_count),
        rp_id=context["rp_id"],
        transports=[str(item) for item in transports if isinstance(item, str)],
        label=context.get("label"),
    )
    return _passkey_read(created)


@router.post(
    "/admin/passkeys/auth/options",
    response_model=AdminPasskeyAuthOptionsRead,
)
async def admin_passkey_auth_options(request: Request) -> AdminPasskeyAuthOptionsRead:
    service = _admin_auth_service(request)
    service.require_configured_record()
    rp_id, origin = _current_rp_id_and_origin(request)
    passkeys = service.list_passkeys_for_rp(rp_id)
    if not passkeys:
        raise HTTPException(status_code=409, detail="no passkeys configured for this host")
    challenge = base64url_decode(generate_secret_token(24))
    options = generate_authentication_options(
        rp_id=rp_id,
        challenge=challenge,
        allow_credentials=[
            PublicKeyCredentialDescriptor(
                id=base64url_decode(item.credential_id),
                transports=_descriptor_transports(item.transports),
            )
            for item in passkeys
        ],
    )
    challenge_id = _issue_challenge(
        request,
        kind="authenticate",
        rp_id=rp_id,
        origin=origin,
        challenge=challenge,
    )
    return AdminPasskeyAuthOptionsRead(
        challenge_id=challenge_id,
        options_json=options_to_json(options),
        rp_id=rp_id,
        origin=origin,
    )


@router.post(
    "/admin/passkeys/auth/verify",
    response_model=AdminAuthStateRead,
)
async def admin_passkey_auth_verify(
    payload: AdminPasskeyVerifyRequest,
    request: Request,
    response: Response,
) -> AdminAuthStateRead:
    service = _admin_auth_service(request)
    record = service.require_configured_record()
    context = _consume_challenge(request, payload.challenge_id, expected_kind="authenticate")
    credential_id = payload.credential.get("id")
    if not isinstance(credential_id, str) or not credential_id:
        raise HTTPException(status_code=400, detail="passkey credential id is required")
    passkey = service.get_passkey(credential_id, context["rp_id"])
    if passkey is None:
        raise HTTPException(status_code=401, detail="unknown passkey")
    try:
        verified = verify_authentication_response(
            credential=payload.credential,
            expected_challenge=context["challenge"],
            expected_rp_id=context["rp_id"],
            expected_origin=context["origin"],
            credential_public_key=base64url_decode(passkey.public_key),
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=True,
        )
    except Exception as error:
        raise HTTPException(
            status_code=401,
            detail=f"passkey authentication failed: {error}",
        ) from error
    service.update_passkey_sign_count(credential_id, context["rp_id"], int(verified.new_sign_count))
    token = service.create_session_token(record)
    _set_admin_session_cookie(request, response, token)
    return _admin_state_read(service.state_from_session_token(token))


@router.delete("/admin/passkeys/{credential_id}", status_code=204)
async def delete_admin_passkey(
    credential_id: str,
    rp_id: str,
    request: Request,
) -> None:
    _require_admin_session(request)
    deleted = _admin_auth_service(request).delete_passkey(credential_id, rp_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="passkey not found")


@router.get("/tokens", response_model=list[ApiTokenRead])
async def list_api_tokens(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await ApiTokenRepository(session).list()


@router.post("/tokens", response_model=ApiTokenCreated, status_code=201)
async def create_api_token(
    payload: ApiTokenCreate,
    uow: UnitOfWork = Depends(get_uow),
) -> ApiTokenCreated:
    token = generate_api_token()
    row = await uow.tokens.create(
        name=payload.name,
        token_hash=hash_api_token(token),
        token_prefix=api_token_prefix(token),
        scopes_json=normalize_token_scopes(payload.scopes),
    )
    await record_audit_event(
        uow.session,
        source="api",
        action="auth.tokens.create",
        status="succeeded",
        entity_type="api_token",
        entity_id=row.id,
        metadata={"scopes": row.scopes_json},
    )
    await uow.commit()
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
    uow: UnitOfWork = Depends(get_uow),
) -> None:
    deleted = await uow.tokens.revoke(token_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="api token not found")
    await record_audit_event(
        uow.session,
        source="api",
        action="auth.tokens.revoke",
        status="succeeded",
        entity_type="api_token",
        entity_id=token_id,
    )
    await uow.commit()
    response.delete_cookie(API_TOKEN_COOKIE)


@router.post("/session", status_code=204)
async def create_api_token_session(
    payload: ApiTokenSessionRequest,
    request: Request,
    response: Response,
    uow: UnitOfWork = Depends(get_uow),
) -> None:
    row = await uow.tokens.get_by_hash(hash_api_token(payload.token))
    if row is None or not row.is_active:
        raise HTTPException(status_code=401, detail="invalid api token")
    await uow.tokens.mark_used(row)
    await record_audit_event(
        uow.session,
        source="api",
        action="auth.session.create",
        status="succeeded",
        request=request,
        api_token_id=row.id,
    )
    await uow.commit()
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
