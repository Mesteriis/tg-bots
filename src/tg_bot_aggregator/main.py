from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tg_bot_aggregator.api import (
    analytics,
    audit,
    auth,
    bots,
    destinations,
    diagnostics,
    discovery,
    events,
    health,
    mcp_settings,
    mtproto,
    reliability,
    send,
    telegram_compat,
    templates,
)
from tg_bot_aggregator.auth_middleware import ProtectedHostAuthMiddleware
from tg_bot_aggregator.config import Settings, get_settings
from tg_bot_aggregator.db import create_engine, create_session_factory
from tg_bot_aggregator.events import MemoryEventBus
from tg_bot_aggregator.mcp_server import create_mcp_asgi_app, create_mcp_server
from tg_bot_aggregator.models import Base
from tg_bot_aggregator.security import install_secret_log_filters
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient


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

    prefix = resolved_settings.api_v1_prefix
    app.include_router(health.router, prefix=prefix)
    app.include_router(audit.router, prefix=prefix)
    app.include_router(auth.router, prefix=prefix)
    app.include_router(bots.router, prefix=prefix)
    app.include_router(destinations.router, prefix=prefix)
    app.include_router(diagnostics.router, prefix=prefix)
    app.include_router(discovery.router, prefix=prefix)
    app.include_router(templates.router, prefix=prefix)
    app.include_router(reliability.router, prefix=prefix)
    app.include_router(send.router, prefix=prefix)
    app.include_router(mtproto.router, prefix=prefix)
    app.include_router(mcp_settings.router, prefix=prefix)
    app.include_router(analytics.router, prefix=prefix)
    app.include_router(events.router, prefix=prefix)
    app.include_router(telegram_compat.router)

    def mcp_session_factory() -> async_sessionmaker[AsyncSession]:
        return app.state.session_factory

    mcp = create_mcp_server(
        settings=resolved_settings,
        get_session_factory=mcp_session_factory,
        event_bus=app.state.event_bus,
        bot_api_client=app.state.bot_api_client,
    )
    app.state.mcp_server = mcp
    app.mount(resolved_settings.mcp_v1_prefix, create_mcp_asgi_app(mcp))

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse("src/tg_bot_aggregator/static/index.html")

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
