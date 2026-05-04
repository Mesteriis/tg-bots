from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tg_bot_aggregator.api.router import create_api_router
from tg_bot_aggregator.core.config import Settings, get_settings
from tg_bot_aggregator.core.db import create_engine, create_session_factory
from tg_bot_aggregator.core.security import install_secret_log_filters
from tg_bot_aggregator.domain.auth.middleware import ProtectedHostAuthMiddleware
from tg_bot_aggregator.domain.mcp.server import create_mcp_asgi_app, create_mcp_server
from tg_bot_aggregator.domain.operations.repository import (
    RuntimeAdvancedSettingsRepository,
    RuntimeSettingsRepository,
)
from tg_bot_aggregator.infra.events import MemoryEventBus
from tg_bot_aggregator.infra.telegram_client import TelegramBotApiClient
from tg_bot_aggregator.models import Base
from tg_bot_aggregator.runtime_settings import apply_runtime_settings, apply_runtime_settings_to_app

FAVICON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    b'<rect width="64" height="64" rx="14" fill="#282c34"/>'
    b'<path d="M14 31 50 16 42 50 31 39 24 46 25 35z" fill="#61afef"/>'
    b"</svg>"
)


def create_app(
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    event_bus: MemoryEventBus | None = None,
    bot_api_client: TelegramBotApiClient | None = None,
    enqueue_analytics_refresh: Callable[[int, int], Awaitable[str | None]] | None = None,
    enqueue_send_history: Callable[[int], Awaitable[str | None]] | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    install_secret_log_filters()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = None
        if session_factory is None:
            engine = create_engine(resolved_settings)
            app.state.session_factory = create_session_factory(engine)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        async with app.state.session_factory() as session:
            effective_settings = apply_runtime_settings(
                resolved_settings,
                await RuntimeSettingsRepository(session).get(),
                await RuntimeAdvancedSettingsRepository(session).get(),
            )
        apply_runtime_settings_to_app(app, effective_settings)
        yield
        if engine is not None:
            await engine.dispose()

    app = FastAPI(title="Telegram Bot Aggregator", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.session_factory = session_factory
    app.state.event_bus = event_bus or MemoryEventBus()
    app.state.bot_api_client = bot_api_client or TelegramBotApiClient(
        resolved_settings.telegram_bot_api_base_url
    )

    async def default_enqueue_analytics_refresh(target_id: int, run_id: int) -> str | None:
        from tg_bot_aggregator.tasks import refresh_analytics_target

        task = await refresh_analytics_target.kiq(target_id, run_id)
        return task.task_id

    app.state.enqueue_analytics_refresh = (
        enqueue_analytics_refresh or default_enqueue_analytics_refresh
    )

    async def default_enqueue_send_history(send_history_id: int) -> str | None:
        from tg_bot_aggregator.tasks import send_history

        task = await send_history.kiq(send_history_id)
        return task.task_id

    app.state.enqueue_send_history = enqueue_send_history or default_enqueue_send_history

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    app.add_middleware(ProtectedHostAuthMiddleware, settings=resolved_settings)

    app.include_router(create_api_router(resolved_settings.api_v1_prefix))

    def mcp_session_factory() -> async_sessionmaker[AsyncSession]:
        return app.state.session_factory

    mcp = create_mcp_server(
        settings=resolved_settings,
        get_session_factory=mcp_session_factory,
        event_bus=app.state.event_bus,
        bot_api_client=app.state.bot_api_client,
        enqueue_send_history=app.state.enqueue_send_history,
    )
    app.state.mcp_server = mcp
    app.mount(resolved_settings.mcp_v1_prefix, create_mcp_asgi_app(mcp))

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse("src/tg_bot_aggregator/static/index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(FAVICON_SVG, media_type="image/svg+xml")

    return app


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "tg_bot_aggregator.main:create_app",
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
    )
