from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.models import (
    AnalyticsRun,
    AnalyticsSnapshot,
    AnalyticsTarget,
    Bot,
    Destination,
    MessageTemplate,
    MtprotoSession,
    SendHistory,
    utc_now,
)


class NotFoundError(ValueError):
    pass


async def _get_or_none(session: AsyncSession, model: type[Any], row_id: int) -> Any | None:
    return await session.get(model, row_id)


async def _list(session: AsyncSession, statement: Select[tuple[Any]]) -> list[Any]:
    return list((await session.execute(statement)).scalars().all())


class BotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> Bot:
        bot = Bot(**values)
        self.session.add(bot)
        await self.session.flush()
        return bot

    async def list(self) -> list[Bot]:
        return await _list(self.session, select(Bot).order_by(Bot.id))

    async def get(self, bot_id: int) -> Bot | None:
        return await _get_or_none(self.session, Bot, bot_id)

    async def update(self, bot_id: int, **values: Any) -> Bot:
        bot = await self.get(bot_id)
        if bot is None:
            raise NotFoundError(f"bot {bot_id} not found")
        for key, value in values.items():
            setattr(bot, key, value)
        bot.updated_at = utc_now()
        await self.session.flush()
        return bot

    async def delete(self, bot_id: int) -> bool:
        bot = await self.get(bot_id)
        if bot is None:
            return False
        await self.session.delete(bot)
        await self.session.flush()
        return True


class DestinationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> Destination:
        destination = Destination(**values)
        self.session.add(destination)
        await self.session.flush()
        return destination

    async def list(self) -> list[Destination]:
        return await _list(self.session, select(Destination).order_by(Destination.id))

    async def get(self, destination_id: int) -> Destination | None:
        return await _get_or_none(self.session, Destination, destination_id)

    async def update(self, destination_id: int, **values: Any) -> Destination:
        destination = await self.get(destination_id)
        if destination is None:
            raise NotFoundError(f"destination {destination_id} not found")
        for key, value in values.items():
            setattr(destination, key, value)
        destination.updated_at = utc_now()
        await self.session.flush()
        return destination

    async def delete(self, destination_id: int) -> bool:
        destination = await self.get(destination_id)
        if destination is None:
            return False
        await self.session.delete(destination)
        await self.session.flush()
        return True


class TemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> MessageTemplate:
        template = MessageTemplate(**values)
        self.session.add(template)
        await self.session.flush()
        return template

    async def list(self) -> list[MessageTemplate]:
        return await _list(self.session, select(MessageTemplate).order_by(MessageTemplate.id))

    async def get(self, template_id: int) -> MessageTemplate | None:
        return await _get_or_none(self.session, MessageTemplate, template_id)

    async def get_by_tag(self, tag: str) -> MessageTemplate | None:
        statement = select(MessageTemplate).where(MessageTemplate.tag == tag)
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def update(self, template_id: int, **values: Any) -> MessageTemplate:
        template = await self.get(template_id)
        if template is None:
            raise NotFoundError(f"template {template_id} not found")
        for key, value in values.items():
            setattr(template, key, value)
        template.updated_at = utc_now()
        await self.session.flush()
        return template

    async def delete(self, template_id: int) -> bool:
        template = await self.get(template_id)
        if template is None:
            return False
        await self.session.delete(template)
        await self.session.flush()
        return True


class SendHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> SendHistory:
        row = SendHistory(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self, limit: int = 100) -> list[SendHistory]:
        statement = select(SendHistory).order_by(SendHistory.id.desc()).limit(limit)
        return await _list(self.session, statement)

    async def mark_succeeded(
        self,
        row: SendHistory,
        telegram_message_id: int | None,
        response: dict[str, Any],
    ) -> SendHistory:
        row.status = "succeeded"
        row.telegram_message_id = telegram_message_id
        row.response_payload_json = response
        row.sent_at = utc_now()
        await self.session.flush()
        return row

    async def mark_failed(
        self,
        row: SendHistory,
        error_code: str,
        error_message: str,
        response: dict[str, Any] | None = None,
    ) -> SendHistory:
        row.status = "failed"
        row.error_code = error_code
        row.error_message = error_message
        row.response_payload_json = response
        row.failed_at = utc_now()
        await self.session.flush()
        return row


class MtprotoSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_default(self) -> MtprotoSession | None:
        statement = select(MtprotoSession).where(MtprotoSession.session_name == "default")
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def upsert_default(self, **values: Any) -> MtprotoSession:
        row = await self.get_default()
        if row is None:
            row = MtprotoSession(session_name="default", **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
        await self.session.flush()
        return row


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_target(self, **values: Any) -> AnalyticsTarget:
        target = AnalyticsTarget(**values)
        self.session.add(target)
        await self.session.flush()
        return target

    async def list_targets(self, active_only: bool = False) -> list[AnalyticsTarget]:
        statement = select(AnalyticsTarget).order_by(AnalyticsTarget.id)
        if active_only:
            statement = statement.where(AnalyticsTarget.is_active.is_(True))
        return await _list(self.session, statement)

    async def get_target(self, target_id: int) -> AnalyticsTarget | None:
        return await _get_or_none(self.session, AnalyticsTarget, target_id)

    async def create_run(self, **values: Any) -> AnalyticsRun:
        run = AnalyticsRun(**values)
        self.session.add(run)
        await self.session.flush()
        return run

    async def create_snapshot(self, **values: Any) -> AnalyticsSnapshot:
        snapshot = AnalyticsSnapshot(**values)
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def list_runs(self, limit: int = 100) -> list[AnalyticsRun]:
        statement = select(AnalyticsRun).order_by(AnalyticsRun.id.desc()).limit(limit)
        return await _list(self.session, statement)

    async def list_snapshots(self, target_id: int | None = None, limit: int = 100) -> list[AnalyticsSnapshot]:
        statement = select(AnalyticsSnapshot).order_by(AnalyticsSnapshot.id.desc()).limit(limit)
        if target_id is not None:
            statement = statement.where(AnalyticsSnapshot.target_id == target_id)
        return await _list(self.session, statement)

