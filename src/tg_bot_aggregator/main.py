from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from typing import Awaitable, Callable

from tg_bot_aggregator.api import analytics, bots, destinations, events, health, mtproto, send, templates
from tg_bot_aggregator.config import Settings, get_settings
from tg_bot_aggregator.db import create_engine, create_session_factory
from tg_bot_aggregator.events import MemoryEventBus
from tg_bot_aggregator.models import Base
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient


def create_app(
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    event_bus: MemoryEventBus | None = None,
    bot_api_client: TelegramBotApiClient | None = None,
    enqueue_analytics_refresh: Callable[[int, int], Awaitable[str | None]] | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()

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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    prefix = resolved_settings.api_v1_prefix
    app.include_router(health.router, prefix=prefix)
    app.include_router(bots.router, prefix=prefix)
    app.include_router(destinations.router, prefix=prefix)
    app.include_router(templates.router, prefix=prefix)
    app.include_router(send.router, prefix=prefix)
    app.include_router(mtproto.router, prefix=prefix)
    app.include_router(analytics.router, prefix=prefix)
    app.include_router(events.router, prefix=prefix)

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
