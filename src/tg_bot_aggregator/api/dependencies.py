from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.events import MemoryEventBus
from tg_bot_aggregator.send_service import SendService
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_event_bus(request: Request) -> MemoryEventBus:
    return request.app.state.event_bus


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


def get_bot_api_client(request: Request) -> TelegramBotApiClient:
    return request.app.state.bot_api_client


def create_send_service(
    session: AsyncSession,
    request: Request,
) -> SendService:
    return SendService(
        session=session,
        bot_api=request.app.state.bot_api_client,
        settings=request.app.state.settings,
        events=request.app.state.event_bus,
    )

