from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from tg_bot_aggregator.api_tokens import API_TOKEN_COOKIE, API_TOKEN_HEADER, hash_api_token
from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.repositories import ApiTokenRepository
from tg_bot_aggregator.security import is_protected_host_request


class ProtectedHostAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not self._requires_api_token(request):
            return await call_next(request)

        token = self._extract_token(request)
        if token is None:
            return self._unauthorized()

        session_factory = request.app.state.session_factory
        async with session_factory() as session:
            row = await ApiTokenRepository(session).get_by_hash(hash_api_token(token))
            if row is None or not row.is_active:
                return self._unauthorized()
            await ApiTokenRepository(session).mark_used(row)
            await session.commit()
            request.state.api_token_id = row.id

        return await call_next(request)

    def _requires_api_token(self, request: Request) -> bool:
        if request.method == "OPTIONS":
            return False
        path = request.url.path
        if path == "/" or path == f"{self.settings.api_v1_prefix}/auth/session":
            return False
        if not (
            path.startswith(self.settings.api_v1_prefix)
            or path.startswith(self.settings.mcp_v1_prefix)
        ):
            return False
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        origin = request.headers.get("origin")
        return is_protected_host_request(
            host=host,
            origin=origin,
            protected_hosts=self.settings.protected_api_hosts,
        )

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
