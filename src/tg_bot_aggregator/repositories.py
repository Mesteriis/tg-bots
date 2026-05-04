from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.mcp_catalog import MCP_DEFAULT_ENABLED_TOOL_NAMES
from tg_bot_aggregator.models import (
    AnalyticsRun,
    AnalyticsSnapshot,
    AnalyticsTarget,
    ApiToken,
    AuditEvent,
    BackupRun,
    Bot,
    BotDiscoveryEvent,
    BotDiscoverySettings,
    Destination,
    DestinationHealth,
    DiagnosticBotSettings,
    DiagnosticUpdate,
    McpCoverageSnapshot,
    McpSettings,
    MessageTemplate,
    MessageTemplateVersion,
    MtprotoSession,
    OpsActionRun,
    OpsAutomationRule,
    OpsFact,
    OpsRecommendation,
    RuntimeAdvancedSettings,
    RuntimeSettings,
    SendAttempt,
    SendBatch,
    SendBatchItem,
    SendHistory,
    SendProfile,
    utc_now,
)


class NotFoundError(ValueError):
    pass


async def _get_or_none(session: AsyncSession, model: type[Any], row_id: int) -> Any | None:
    return await session.get(model, row_id)


async def _list(session: AsyncSession, statement: Select[tuple[Any]]) -> list[Any]:
    return list((await session.execute(statement)).scalars().all())


def _optional_equals(column: Any, value: Any) -> Any:
    return column.is_(None) if value is None else column == value


def _ops_fact_identity_key(values: dict[str, Any]) -> str:
    identity = [
        values["fact_type"],
        values.get("bot_id"),
        values.get("chat_id"),
        values.get("message_thread_id"),
        values["source"],
    ]
    payload = json.dumps(identity, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


class DiagnosticUpdateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> DiagnosticUpdate:
        row = DiagnosticUpdate(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self, limit: int = 100) -> list[DiagnosticUpdate]:
        statement = select(DiagnosticUpdate).order_by(DiagnosticUpdate.id.desc()).limit(limit)
        return await _list(self.session, statement)

    async def get(self, update_id: int) -> DiagnosticUpdate | None:
        return await _get_or_none(self.session, DiagnosticUpdate, update_id)

    async def get_by_update_id(self, update_id: int) -> DiagnosticUpdate | None:
        statement = select(DiagnosticUpdate).where(DiagnosticUpdate.update_id == update_id)
        return (await self.session.execute(statement)).scalar_one_or_none()


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
            row = McpSettings(id=1, enabled_tools_json=list(MCP_DEFAULT_ENABLED_TOOL_NAMES))
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


class RuntimeSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> RuntimeSettings | None:
        return await _get_or_none(self.session, RuntimeSettings, 1)

    async def get_or_create(self) -> RuntimeSettings:
        row = await self.get()
        if row is None:
            row = RuntimeSettings(id=1)
            self.session.add(row)
            await self.session.flush()
        return row

    async def upsert(self, **values: Any) -> RuntimeSettings:
        row = await self.get()
        if row is None:
            row = RuntimeSettings(id=1, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
        await self.session.flush()
        return row


class RuntimeAdvancedSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> RuntimeAdvancedSettings | None:
        return await _get_or_none(self.session, RuntimeAdvancedSettings, 1)

    async def get_or_create(self) -> RuntimeAdvancedSettings:
        row = await self.get()
        if row is None:
            row = RuntimeAdvancedSettings(id=1, settings_json={})
            self.session.add(row)
            await self.session.flush()
        return row

    async def upsert(self, **values: Any) -> RuntimeAdvancedSettings:
        row = await self.get_or_create()
        merged = dict(row.settings_json or {})
        merged.update(values)
        row.settings_json = merged
        row.updated_at = utc_now()
        await self.session.flush()
        return row


class BackupRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> BackupRun:
        row = BackupRun(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self, limit: int = 50) -> list[BackupRun]:
        statement = select(BackupRun).order_by(BackupRun.id.desc()).limit(limit)
        return await _list(self.session, statement)

    async def get(self, run_id: int) -> BackupRun | None:
        return await _get_or_none(self.session, BackupRun, run_id)

    async def latest_successful(self) -> BackupRun | None:
        statement = (
            select(BackupRun)
            .where(BackupRun.status == "succeeded", BackupRun.backup_json.is_not(None))
            .order_by(BackupRun.id.desc())
            .limit(1)
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def mark_finished(
        self,
        row: BackupRun,
        *,
        status: str,
        items_exported: int,
        backup_json: dict[str, Any] | None = None,
        git_commit: str | None = None,
        error_message: str | None = None,
    ) -> BackupRun:
        row.status = status
        row.items_exported = items_exported
        row.backup_json = backup_json
        row.git_commit = git_commit
        row.error_message = error_message
        row.finished_at = utc_now()
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
            nested = await self.session.begin_nested()
            try:
                row = Destination(
                    bot_id=bot_id,
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    **values,
                )
                self.session.add(row)
                await self.session.flush()
            except IntegrityError:
                await nested.rollback()
                row = await self.get_by_chat(bot_id, chat_id, message_thread_id)
                if row is None:
                    raise
                for key, value in values.items():
                    setattr(row, key, value)
                row.updated_at = utc_now()
            else:
                await nested.commit()
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


class DestinationHealthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_destination(self, destination_id: int) -> DestinationHealth | None:
        statement = select(DestinationHealth).where(
            DestinationHealth.destination_id == destination_id
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def upsert_for_destination(
        self,
        destination_id: int,
        **values: Any,
    ) -> DestinationHealth:
        row = await self.get_for_destination(destination_id)
        if row is None:
            row = DestinationHealth(destination_id=destination_id, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.checked_at = utc_now()
        await self.session.flush()
        return row


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


class TemplateVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_version_number(self, template_id: int) -> int:
        statement = select(func.max(MessageTemplateVersion.version_number)).where(
            MessageTemplateVersion.template_id == template_id
        )
        current = (await self.session.execute(statement)).scalar_one()
        return int(current or 0) + 1

    async def create_from_template(self, template: MessageTemplate) -> MessageTemplateVersion:
        row = MessageTemplateVersion(
            template_id=template.id,
            version_number=await self.next_version_number(template.id),
            title=template.title,
            text=template.text,
            parse_mode=template.parse_mode,
            disable_web_page_preview=template.disable_web_page_preview,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_for_template(self, template_id: int) -> list[MessageTemplateVersion]:
        statement = (
            select(MessageTemplateVersion)
            .where(MessageTemplateVersion.template_id == template_id)
            .order_by(MessageTemplateVersion.version_number)
        )
        return await _list(self.session, statement)

    async def get(self, version_id: int) -> MessageTemplateVersion | None:
        return await _get_or_none(self.session, MessageTemplateVersion, version_id)


class SendProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> SendProfile:
        row = SendProfile(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self, active_only: bool = False) -> list[SendProfile]:
        statement = select(SendProfile).order_by(SendProfile.id)
        if active_only:
            statement = statement.where(SendProfile.is_active.is_(True))
        return await _list(self.session, statement)

    async def get(self, profile_id: int) -> SendProfile | None:
        return await _get_or_none(self.session, SendProfile, profile_id)

    async def update(self, profile_id: int, **values: Any) -> SendProfile:
        row = await self.get(profile_id)
        if row is None:
            raise NotFoundError(f"send profile {profile_id} not found")
        for key, value in values.items():
            setattr(row, key, value)
        row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def delete(self, profile_id: int) -> bool:
        row = await self.get(profile_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True


class SendBatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_batch(self, **values: Any) -> SendBatch:
        row = SendBatch(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def add_item(self, batch_id: int, **values: Any) -> SendBatchItem:
        row = SendBatchItem(batch_id=batch_id, **values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_batches(self, limit: int = 100) -> list[SendBatch]:
        statement = select(SendBatch).order_by(SendBatch.id.desc()).limit(limit)
        return await _list(self.session, statement)

    async def get_batch(self, batch_id: int) -> SendBatch | None:
        return await _get_or_none(self.session, SendBatch, batch_id)

    async def list_items(self, batch_id: int) -> list[SendBatchItem]:
        statement = select(SendBatchItem).where(SendBatchItem.batch_id == batch_id).order_by(
            SendBatchItem.id
        )
        return await _list(self.session, statement)

    async def get_item(self, item_id: int) -> SendBatchItem | None:
        return await _get_or_none(self.session, SendBatchItem, item_id)

    async def mark_batch_status(self, batch: SendBatch, status: str) -> SendBatch:
        batch.status = status
        batch.updated_at = utc_now()
        if status == "queued":
            batch.queued_at = utc_now()
        if status in {"finished", "failed", "cancelled"}:
            batch.finished_at = utc_now()
        await self.session.flush()
        return batch

    async def mark_item_status(
        self,
        item: SendBatchItem,
        status: str,
        send_history_id: int | None = None,
        error_message: str | None = None,
    ) -> SendBatchItem:
        item.status = status
        if send_history_id is not None:
            item.send_history_id = send_history_id
        item.error_message = error_message
        item.updated_at = utc_now()
        await self.session.flush()
        return item


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

    async def list_failed(self, limit: int = 100) -> list[SendHistory]:
        statement = (
            select(SendHistory)
            .where(SendHistory.status == "failed")
            .order_by(SendHistory.id.desc())
            .limit(limit)
        )
        return await _list(self.session, statement)

    async def list_due(self, now: datetime, limit: int = 100) -> list[SendHistory]:
        statement = (
            select(SendHistory)
            .where(
                SendHistory.status == "queued",
                SendHistory.next_retry_at.is_not(None),
                SendHistory.next_retry_at <= now,
            )
            .order_by(SendHistory.next_retry_at, SendHistory.id)
            .limit(limit)
        )
        return await _list(self.session, statement)

    async def acquire_due_lease(
        self,
        row_id: int,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> SendHistory | None:
        statement = (
            update(SendHistory)
            .where(
                SendHistory.id == row_id,
                SendHistory.status.in_(("queued", "deferred", "created")),
                or_(SendHistory.next_retry_at.is_(None), SendHistory.next_retry_at <= now),
                or_(SendHistory.lock_expires_at.is_(None), SendHistory.lock_expires_at <= now),
            )
            .values(
                status="sending",
                locked_at=now,
                locked_by=worker_id,
                lock_expires_at=now + timedelta(seconds=lease_seconds),
            )
            .execution_options(synchronize_session=False)
        )
        result = await self.session.execute(statement)
        if result.rowcount != 1:
            return None
        await self.session.flush()
        row = await self.get(row_id)
        if row is not None:
            await self.session.refresh(row)
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

    async def count_for_bot_since(self, bot_id: int, since: datetime) -> int:
        statement = select(func.count()).select_from(SendHistory).where(
            SendHistory.bot_id == bot_id,
            SendHistory.created_at >= since,
            SendHistory.status.in_(("created", "sending", "queued", "succeeded")),
        )
        return int((await self.session.execute(statement)).scalar_one())

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
        row.locked_at = None
        row.locked_by = None
        row.lock_expires_at = None
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
        row.locked_at = None
        row.locked_by = None
        row.lock_expires_at = None
        await self.session.flush()
        return row

    async def mark_cancelled(
        self,
        row: SendHistory,
        error_message: str = "cancelled by user",
    ) -> SendHistory:
        row.status = "cancelled"
        row.error_code = "cancelled"
        row.error_message = error_message
        row.queued_task_id = None
        row.next_retry_at = None
        row.locked_at = None
        row.locked_by = None
        row.lock_expires_at = None
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


class OpsFactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_fact(self, **values: Any) -> OpsFact:
        values["identity_key"] = _ops_fact_identity_key(values)
        statement = select(OpsFact).where(OpsFact.identity_key == values["identity_key"])
        row = (await self.session.execute(statement)).scalar_one_or_none()
        if row is None:
            row = OpsFact(**values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.observed_at = utc_now()
        await self.session.flush()
        return row

    async def list(self, limit: int = 200) -> list[OpsFact]:
        statement = select(OpsFact).order_by(OpsFact.id.desc()).limit(limit)
        return await _list(self.session, statement)

    async def get(self, fact_id: int) -> OpsFact | None:
        return await _get_or_none(self.session, OpsFact, fact_id)


class OpsRecommendationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> OpsRecommendation:
        row = OpsRecommendation(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(
        self,
        status: str | None = None,
        recommendation_type: str | None = None,
        limit: int = 200,
    ) -> list[OpsRecommendation]:
        statement = select(OpsRecommendation).order_by(OpsRecommendation.id.desc()).limit(limit)
        if status is not None:
            statement = statement.where(OpsRecommendation.status == status)
        if recommendation_type is not None:
            statement = statement.where(
                OpsRecommendation.recommendation_type == recommendation_type
            )
        return await _list(self.session, statement)

    async def get(self, recommendation_id: int) -> OpsRecommendation | None:
        return await _get_or_none(self.session, OpsRecommendation, recommendation_id)

    async def claim_for_apply(self, recommendation_id: int) -> OpsRecommendation | None:
        result = await self.session.execute(
            update(OpsRecommendation)
            .where(
                OpsRecommendation.id == recommendation_id,
                OpsRecommendation.status.in_(("open", "previewed")),
            )
            .values(status="applying", updated_at=utc_now())
        )
        if result.rowcount != 1:
            return None
        return await self.get(recommendation_id)

    async def find_open(
        self,
        recommendation_type: str,
        bot_id: int | None,
        chat_id: str | None,
        message_thread_id: int | None,
    ) -> OpsRecommendation | None:
        statement = (
            select(OpsRecommendation)
            .where(
                OpsRecommendation.recommendation_type == recommendation_type,
                OpsRecommendation.status.in_(("open", "previewed")),
            )
            .order_by(OpsRecommendation.id.desc())
        )
        rows = await _list(self.session, statement)
        for row in rows:
            payload = row.action_payload_json or {}
            if (
                payload.get("bot_id") == bot_id
                and payload.get("chat_id") == chat_id
                and payload.get("message_thread_id") == message_thread_id
            ):
                return row
        return None

    async def mark_previewed(self, row: OpsRecommendation) -> OpsRecommendation:
        row.status = "previewed"
        row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def mark_applied(
        self,
        row: OpsRecommendation,
        destination_id: int | None = None,
    ) -> OpsRecommendation:
        row.status = "applied"
        row.destination_id = destination_id if destination_id is not None else row.destination_id
        row.applied_at = utc_now()
        row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def mark_dismissed(self, row: OpsRecommendation) -> OpsRecommendation:
        row.status = "dismissed"
        row.dismissed_at = utc_now()
        row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def mark_stale(self, row: OpsRecommendation) -> OpsRecommendation:
        row.status = "stale"
        row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def mark_failed(self, row: OpsRecommendation, message: str) -> OpsRecommendation:
        row.status = "failed"
        row.reason = f"{row.reason}\nFailure: {message}"
        row.updated_at = utc_now()
        await self.session.flush()
        return row


class OpsAutomationRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_by_key(self, rule_key: str, **values: Any) -> OpsAutomationRule:
        statement = select(OpsAutomationRule).where(OpsAutomationRule.rule_key == rule_key)
        row = (await self.session.execute(statement)).scalar_one_or_none()
        if row is None:
            row = OpsAutomationRule(rule_key=rule_key, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def list(self) -> list[OpsAutomationRule]:
        return await _list(self.session, select(OpsAutomationRule).order_by(OpsAutomationRule.id))

    async def get(self, rule_id: int) -> OpsAutomationRule | None:
        return await _get_or_none(self.session, OpsAutomationRule, rule_id)

    async def update(self, rule_id: int, **values: Any) -> OpsAutomationRule:
        row = await self.get(rule_id)
        if row is None:
            raise NotFoundError(f"ops automation rule {rule_id} not found")
        for key, value in values.items():
            setattr(row, key, value)
        row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def mark_run(self, row: OpsAutomationRule, result: str) -> OpsAutomationRule:
        row.last_run_at = utc_now()
        row.last_result = result
        row.updated_at = utc_now()
        await self.session.flush()
        return row


class OpsActionRunRepository:
    _TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> OpsActionRun:
        row = OpsActionRun(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self, limit: int = 200) -> list[OpsActionRun]:
        statement = select(OpsActionRun).order_by(OpsActionRun.id.desc()).limit(limit)
        return await _list(self.session, statement)

    async def get(self, run_id: int) -> OpsActionRun | None:
        return await _get_or_none(self.session, OpsActionRun, run_id)

    async def update(self, run_id: int, **values: Any) -> OpsActionRun:
        row = await self.get(run_id)
        if row is None:
            raise NotFoundError(f"ops action run {run_id} not found")
        if row.status in self._TERMINAL_STATUSES:
            raise ValueError(f"ops action run {row.id} is already terminal")
        for key, value in values.items():
            setattr(row, key, value)
        await self.session.flush()
        return row

    async def mark_finished(
        self,
        row: OpsActionRun,
        *,
        status: str,
        result_json: dict[str, Any] | None = None,
        error_message: str | None = None,
        rollback_hint: str | None = None,
    ) -> OpsActionRun:
        if row.status in self._TERMINAL_STATUSES:
            raise ValueError(f"ops action run {row.id} is already terminal")
        row.status = status
        row.result_json = result_json
        row.error_message = error_message
        if rollback_hint is not None:
            row.rollback_hint = rollback_hint
        row.finished_at = utc_now()
        await self.session.flush()
        return row

    async def mark_succeeded(
        self,
        row: OpsActionRun,
        *,
        result_json: dict[str, Any] | None = None,
        rollback_hint: str | None = None,
    ) -> OpsActionRun:
        return await self.mark_finished(
            row,
            status="succeeded",
            result_json=result_json,
            rollback_hint=rollback_hint,
        )

    async def mark_failed(
        self,
        row: OpsActionRun,
        *,
        error_message: str,
        result_json: dict[str, Any] | None = None,
        rollback_hint: str | None = None,
    ) -> OpsActionRun:
        return await self.mark_finished(
            row,
            status="failed",
            result_json=result_json,
            error_message=error_message,
            rollback_hint=rollback_hint,
        )


class McpCoverageSnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> McpCoverageSnapshot:
        row = McpCoverageSnapshot(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def latest(self) -> McpCoverageSnapshot | None:
        statement = select(McpCoverageSnapshot).order_by(McpCoverageSnapshot.id.desc()).limit(1)
        return (await self.session.execute(statement)).scalar_one_or_none()


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
