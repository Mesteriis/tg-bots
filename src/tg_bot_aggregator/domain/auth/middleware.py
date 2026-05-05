from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from tg_bot_aggregator.audit import record_audit_event
from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.core.security import is_protected_host_request
from tg_bot_aggregator.domain.auth.admin_service import ADMIN_SESSION_COOKIE, AdminAuthService
from tg_bot_aggregator.domain.auth.repository import ApiTokenRepository
from tg_bot_aggregator.domain.auth.service import API_TOKEN_COOKIE, API_TOKEN_HEADER, hash_api_token


class AdminSessionAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not self._requires_admin_session(request):
            return await call_next(request)

        service = AdminAuthService(request.app.state.settings)
        state = service.state_from_session_token(request.cookies.get(ADMIN_SESSION_COOKIE))
        if not state.authenticated:
            return Response(
                '{"detail":"admin session required"}',
                status_code=401,
                media_type="application/json",
            )
        request.state.admin_username = state.username
        request.state.admin_authenticated = True
        return await call_next(request)

    def _requires_admin_session(self, request: Request) -> bool:
        if not getattr(request.app.state, "admin_auth_enabled", True):
            return False
        path = request.url.path
        settings = getattr(request.app.state, "settings", self.settings)
        if path in {"/", "/favicon.ico"}:
            return False
        if path.startswith(settings.mcp_v1_prefix) or path.startswith("/bot"):
            return False
        if path.startswith(f"{settings.api_v1_prefix}/auth/admin"):
            return False
        if path == f"{settings.api_v1_prefix}/auth/session":
            return False
        if not path.startswith(settings.api_v1_prefix):
            return False
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        origin = request.headers.get("origin")
        if is_protected_host_request(
            host=host,
            origin=origin,
            protected_hosts=settings.protected_api_hosts,
        ):
            return False
        return True


class ProtectedHostAuthMiddleware(BaseHTTPMiddleware):
    _READ_METHODS = {"GET", "HEAD"}

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        required_scope = self._required_scope(request)
        if required_scope is None:
            return await call_next(request)

        token = self._extract_token(request)
        if token is None:
            await self._record_rejected(request, None, "missing", "api token required")
            return self._unauthorized()

        session_factory = request.app.state.session_factory
        async with session_factory() as session:
            row = await ApiTokenRepository(session).get_by_hash(hash_api_token(token))
            if row is None or not row.is_active:
                await self._record_rejected(request, None, "invalid", "invalid api token")
                return self._unauthorized()
            scopes = set(row.scopes_json or ["read", "send", "mcp_admin", "tg_compat", "ops_admin"])
            if required_scope not in scopes:
                await record_audit_event(
                    session,
                    source="auth",
                    action="protected_host.scope",
                    status="denied",
                    request=request,
                    api_token_id=row.id,
                    message=f"api token scope '{required_scope}' required",
                    metadata={"required_scope": required_scope, "scopes": sorted(scopes)},
                )
                await session.commit()
                return self._forbidden(required_scope)
            await ApiTokenRepository(session).mark_used(row)
            await session.commit()
            request.state.api_token_id = row.id
            request.state.api_token_scopes = sorted(scopes)

        return await call_next(request)

    def _required_scope(self, request: Request) -> str | None:
        settings = getattr(request.app.state, "settings", self.settings)
        if request.method == "OPTIONS":
            return None
        path = request.url.path
        if path == "/" or path == f"{settings.api_v1_prefix}/auth/session":
            return None
        if not (
            path.startswith(settings.api_v1_prefix)
            or path.startswith(settings.mcp_v1_prefix)
            or path.startswith("/bot")
        ):
            return None
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        origin = request.headers.get("origin")
        if not is_protected_host_request(
            host=host,
            origin=origin,
            protected_hosts=settings.protected_api_hosts,
        ):
            return None
        return self._scope_for_path(path, request.method, settings)

    def _scope_for_path(self, path: str, method: str, settings: Settings) -> str:
        if path.startswith("/bot"):
            return "tg_compat"
        if path.startswith(settings.mcp_v1_prefix):
            return "mcp_admin"
        if path.startswith(f"{settings.api_v1_prefix}/send"):
            return "send"
        if path.startswith(f"{settings.api_v1_prefix}/auth/tokens"):
            return "mcp_admin"
        if path.startswith(f"{settings.api_v1_prefix}/mcp"):
            return "mcp_admin"
        ops_admin_write_prefixes = (
            f"{settings.api_v1_prefix}/ops",
            f"{settings.api_v1_prefix}/config",
            f"{settings.api_v1_prefix}/backup",
            f"{settings.api_v1_prefix}/operations/backup",
            f"{settings.api_v1_prefix}/operations/settings",
        )
        if method not in self._READ_METHODS and path.startswith(ops_admin_write_prefixes):
            return "ops_admin"
        if method in self._READ_METHODS:
            return "read"
        return "mcp_admin"

    def _extract_token(self, request: Request) -> str | None:
        header_token = request.headers.get(API_TOKEN_HEADER)
        if header_token:
            return header_token.strip()
        authorization = request.headers.get("authorization")
        if authorization and authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        cookie_token = request.cookies.get(API_TOKEN_COOKIE)
        return cookie_token.strip() if cookie_token else None

    def _unauthorized(self) -> Response:
        return Response(
            '{"detail":"api token required for protected host"}',
            status_code=401,
            media_type="application/json",
        )

    def _forbidden(self, required_scope: str) -> Response:
        return Response(
            f'{{"detail":"api token scope \'{required_scope}\' required"}}',
            status_code=403,
            media_type="application/json",
        )

    async def _record_rejected(
        self,
        request: Request,
        api_token_id: int | None,
        status: str,
        message: str,
    ) -> None:
        session_factory = request.app.state.session_factory
        async with session_factory() as session:
            await record_audit_event(
                session,
                source="auth",
                action="protected_host.token",
                status=status,
                request=request,
                api_token_id=api_token_id,
                message=message,
            )
            await session.commit()
