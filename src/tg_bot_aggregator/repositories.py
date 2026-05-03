from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.mcp_catalog import MCP_TOOL_NAMES
from tg_bot_aggregator.models import (
    AnalyticsRun,
    AnalyticsSnapshot,
    AnalyticsTarget,
    ApiToken,
    AuditEvent,
    Bot,
    BotDiscoveryEvent,
    BotDiscoverySettings,
    Destination,
    DiagnosticBotSettings,
    McpSettings,
    MessageTemplate,
    MtprotoSession,
    SendAttempt,
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

    async def get_by_token(self, token: str) -> Bot | None:
        statement = select(Bot).where(Bot.token == token)
        return (await self.session.execute(statement)).scalar_one_or_none()

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


class DiagnosticSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> DiagnosticBotSettings | None:
        return await _get_or_none(self.session, DiagnosticBotSettings, 1)

    async def upsert(self, **values: Any) -> DiagnosticBotSettings:
        row = await self.get()
        if row is None:
            row = DiagnosticBotSettings(id=1, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
        await self.session.flush()
        return row


class ApiTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> ApiToken:
        row = ApiToken(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self, active_only: bool = False) -> list[ApiToken]:
        statement = select(ApiToken).order_by(ApiToken.id.desc())
        if active_only:
            statement = statement.where(ApiToken.is_active.is_(True))
        return await _list(self.session, statement)

    async def get(self, token_id: int) -> ApiToken | None:
        return await _get_or_none(self.session, ApiToken, token_id)

    async def get_by_hash(self, token_hash: str) -> ApiToken | None:
        statement = select(ApiToken).where(ApiToken.token_hash == token_hash)
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def mark_used(self, row: ApiToken) -> ApiToken:
        row.last_used_at = utc_now()
        row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def revoke(self, token_id: int) -> bool:
        row = await self.get(token_id)
        if row is None:
            return False
        row.is_active = False
        row.revoked_at = utc_now()
        row.updated_at = utc_now()
        await self.session.flush()
        return True


class McpSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> McpSettings | None:
        return await _get_or_none(self.session, McpSettings, 1)

    async def get_or_create(self) -> McpSettings:
        row = await self.get()
        if row is None:
            row = McpSettings(id=1, enabled_tools_json=list(MCP_TOOL_NAMES))
            self.session.add(row)
            await self.session.flush()
        return row

    async def upsert(self, **values: Any) -> McpSettings:
        row = await self.get()
        if row is None:
            row = McpSettings(id=1, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
        await self.session.flush()
        return row


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

    async def get_by_chat(
        self,
        bot_id: int,
        chat_id: str,
        message_thread_id: int | None = None,
    ) -> Destination | None:
        statement = select(Destination).where(
            Destination.bot_id == bot_id,
            Destination.chat_id == chat_id,
            Destination.message_thread_id.is_(message_thread_id)
            if message_thread_id is None
            else Destination.message_thread_id == message_thread_id,
        )
        return (await self.session.execute(statement)).scalars().first()

    async def get_by_alias(self, bot_id: int, alias: str) -> Destination | None:
        statement = select(Destination).where(
            Destination.bot_id == bot_id,
            Destination.alias == alias,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def upsert_by_chat(
        self,
        bot_id: int,
        chat_id: str,
        message_thread_id: int | None = None,
        **values: Any,
    ) -> Destination:
        row = await self.get_by_chat(bot_id, chat_id, message_thread_id)
        if row is None:
            row = Destination(
                bot_id=bot_id,
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                **values,
            )
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
        await self.session.flush()
        return row

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

    async def get(self, row_id: int) -> SendHistory | None:
        return await _get_or_none(self.session, SendHistory, row_id)

    async def get_by_idempotency_key(self, idempotency_key: str) -> SendHistory | None:
        statement = select(SendHistory).where(SendHistory.idempotency_key == idempotency_key)
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list(self, limit: int = 100) -> list[SendHistory]:
        statement = select(SendHistory).order_by(SendHistory.id.desc()).limit(limit)
        return await _list(self.session, statement)

    async def acquire_due_lease(
        self,
        row_id: int,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> SendHistory | None:
        row = await self.get(row_id)
        if row is None:
            return None
        if row.status not in {"queued", "deferred", "created"}:
            return None
        if row.next_retry_at is not None and row.next_retry_at > now:
            return None
        if row.lock_expires_at is not None and row.lock_expires_at > now:
            return None
        row.status = "sending"
        row.locked_at = now
        row.locked_by = worker_id
        row.lock_expires_at = now + timedelta(seconds=lease_seconds)
        await self.session.flush()
        return row

    async def list_ready_for_lease(self, now: datetime, limit: int = 100) -> list[SendHistory]:
        statement = (
            select(SendHistory)
            .where(
                SendHistory.status.in_(("queued", "deferred")),
                or_(SendHistory.next_retry_at.is_(None), SendHistory.next_retry_at <= now),
                or_(SendHistory.lock_expires_at.is_(None), SendHistory.lock_expires_at <= now),
            )
            .order_by(SendHistory.priority, SendHistory.next_retry_at, SendHistory.id)
            .limit(limit)
        )
        return await _list(self.session, statement)

    async def list_stale_locks(self, now: datetime, limit: int = 100) -> list[SendHistory]:
        statement = (
            select(SendHistory)
            .where(SendHistory.status == "sending", SendHistory.lock_expires_at <= now)
            .order_by(SendHistory.lock_expires_at, SendHistory.id)
            .limit(limit)
        )
        return await _list(self.session, statement)

    async def mark_succeeded(
        self,
        row: SendHistory,
        telegram_message_id: int | None,
        response: dict[str, Any],
    ) -> SendHistory:
        row.status = "succeeded"
        row.error_code = None
        row.error_message = None
        row.telegram_message_id = telegram_message_id
        row.response_payload_json = response
        row.sent_at = utc_now()
        await self.session.flush()
        return row

    async def mark_queued(self, row: SendHistory, task_id: str | None = None) -> SendHistory:
        row.status = "queued"
        row.queued_task_id = task_id
        await self.session.flush()
        return row

    async def mark_sending(self, row: SendHistory, attempt_count: int) -> SendHistory:
        row.status = "sending"
        row.attempt_count = attempt_count
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

    async def mark_deferred(
        self,
        row: SendHistory,
        error_code: str | None,
        error_message: str,
        error_kind: str,
        next_retry_at: datetime,
        retry_after_seconds: int | None,
        response: dict[str, Any] | None = None,
    ) -> SendHistory:
        row.status = "deferred"
        row.error_code = error_code
        row.error_message = error_message
        row.last_error_kind = error_kind
        row.next_retry_at = next_retry_at
        row.retry_after_seconds = retry_after_seconds
        row.response_payload_json = response
        row.locked_at = None
        row.locked_by = None
        row.lock_expires_at = None
        await self.session.flush()
        return row

    async def mark_dead_letter(
        self,
        row: SendHistory,
        error_code: str | None,
        error_message: str,
        error_kind: str,
        response: dict[str, Any] | None = None,
    ) -> SendHistory:
        row.status = "dead_letter"
        row.error_code = error_code
        row.error_message = error_message
        row.last_error_kind = error_kind
        row.response_payload_json = response
        row.failed_at = utc_now()
        row.locked_at = None
        row.locked_by = None
        row.lock_expires_at = None
        await self.session.flush()
        return row

    async def mark_blocked(
        self,
        row: SendHistory,
        error_code: str | None,
        error_message: str,
        error_kind: str,
    ) -> SendHistory:
        row.status = "blocked"
        row.error_code = error_code
        row.error_message = error_message
        row.last_error_kind = error_kind
        row.failed_at = utc_now()
        row.locked_at = None
        row.locked_by = None
        row.lock_expires_at = None
        await self.session.flush()
        return row

    async def release_stale_locks(self, now: datetime) -> int:
        rows = await self.list_stale_locks(now, limit=1000)
        for row in rows:
            row.status = "queued"
            row.locked_at = None
            row.locked_by = None
            row.lock_expires_at = None
        await self.session.flush()
        return len(rows)


class SendAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> SendAttempt:
        row = SendAttempt(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_for_send(self, send_history_id: int) -> list[SendAttempt]:
        statement = (
            select(SendAttempt)
            .where(SendAttempt.send_history_id == send_history_id)
            .order_by(SendAttempt.attempt_number, SendAttempt.id)
        )
        return await _list(self.session, statement)

    async def list(self, limit: int = 100) -> list[SendAttempt]:
        statement = select(SendAttempt).order_by(SendAttempt.id.desc()).limit(limit)
        return await _list(self.session, statement)


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> AuditEvent:
        row = AuditEvent(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self, limit: int = 100) -> list[AuditEvent]:
        statement = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
        return await _list(self.session, statement)


class BotDiscoverySettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> list[BotDiscoverySettings]:
        statement = select(BotDiscoverySettings).order_by(BotDiscoverySettings.id)
        return await _list(self.session, statement)

    async def get(self, settings_id: int) -> BotDiscoverySettings | None:
        return await _get_or_none(self.session, BotDiscoverySettings, settings_id)

    async def get_for_bot(self, bot_id: int) -> BotDiscoverySettings | None:
        statement = select(BotDiscoverySettings).where(BotDiscoverySettings.bot_id == bot_id)
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def upsert_for_bot(self, bot_id: int, **values: Any) -> BotDiscoverySettings:
        row = await self.get_for_bot(bot_id)
        if row is None:
            row = BotDiscoverySettings(bot_id=bot_id, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def list_enabled(self) -> list[BotDiscoverySettings]:
        statement = select(BotDiscoverySettings).where(BotDiscoverySettings.is_enabled.is_(True))
        return await _list(self.session, statement.order_by(BotDiscoverySettings.id))


class BotDiscoveryEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> BotDiscoveryEvent:
        row = BotDiscoveryEvent(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self, limit: int = 100) -> list[BotDiscoveryEvent]:
        statement = select(BotDiscoveryEvent).order_by(BotDiscoveryEvent.id.desc()).limit(limit)
        return await _list(self.session, statement)


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

    async def update_target(self, target_id: int, **values: Any) -> AnalyticsTarget:
        target = await self.get_target(target_id)
        if target is None:
            raise NotFoundError(f"analytics target {target_id} not found")
        for key, value in values.items():
            setattr(target, key, value)
        target.updated_at = utc_now()
        await self.session.flush()
        return target

    async def delete_target(self, target_id: int) -> bool:
        target = await self.get_target(target_id)
        if target is None:
            return False
        await self.session.delete(target)
        await self.session.flush()
        return True

    async def create_run(self, **values: Any) -> AnalyticsRun:
        run = AnalyticsRun(**values)
        self.session.add(run)
        await self.session.flush()
        return run

    async def get_run(self, run_id: int) -> AnalyticsRun | None:
        return await _get_or_none(self.session, AnalyticsRun, run_id)

    async def mark_run_started(self, run: AnalyticsRun) -> AnalyticsRun:
        run.status = "started"
        run.started_at = utc_now()
        await self.session.flush()
        return run

    async def mark_run_finished(self, run: AnalyticsRun, snapshots_created: int) -> AnalyticsRun:
        run.status = "finished"
        run.finished_at = utc_now()
        run.snapshots_created = snapshots_created
        await self.session.flush()
        return run

    async def mark_run_failed(self, run: AnalyticsRun, error_message: str) -> AnalyticsRun:
        run.status = "failed"
        run.finished_at = utc_now()
        run.error_message = error_message
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

    async def list_snapshots(
        self, target_id: int | None = None, limit: int = 100
    ) -> list[AnalyticsSnapshot]:
        statement = select(AnalyticsSnapshot).order_by(AnalyticsSnapshot.id.desc()).limit(limit)
        if target_id is not None:
            statement = statement.where(AnalyticsSnapshot.target_id == target_id)
        return await _list(self.session, statement)
