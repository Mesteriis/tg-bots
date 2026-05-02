from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from tg_bot_aggregator.analytics_service import AnalyticsService
from tg_bot_aggregator.config import Settings, get_settings
from tg_bot_aggregator.db import create_engine, create_session_factory
from tg_bot_aggregator.events import RedisEventBus
from tg_bot_aggregator.mtproto_service import MtprotoService
from tg_bot_aggregator.repositories import MtprotoSessionRepository


def create_broker(settings: Settings | None = None) -> RedisStreamBroker:
    resolved = settings or get_settings()
    backend = RedisAsyncResultBackend(resolved.redis_url)
    return RedisStreamBroker(resolved.redis_url).with_result_backend(backend)


broker = create_broker()


async def run_refresh_analytics_target(target_id: int, run_id: int | None = None) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            mtproto = MtprotoService(settings, MtprotoSessionRepository(session))
            events = RedisEventBus(settings.redis_url)
            service = AnalyticsService(session, mtproto, events)
            return await service.refresh_target(target_id, run_id)
    finally:
        await engine.dispose()


@broker.task
async def refresh_analytics_target(target_id: int, run_id: int | None = None) -> int:
    return await run_refresh_analytics_target(target_id, run_id)


@broker.task
async def refresh_all_analytics_targets() -> list[int]:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            mtproto = MtprotoService(settings, MtprotoSessionRepository(session))
            events = RedisEventBus(settings.redis_url)
            service = AnalyticsService(session, mtproto, events)
            return await service.refresh_all()
    finally:
        await engine.dispose()

