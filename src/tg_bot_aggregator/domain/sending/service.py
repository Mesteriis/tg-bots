import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil
from time import monotonic
from typing import Any, Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.core.errors import NotFoundError
from tg_bot_aggregator.core.security import redact_secrets, redact_text
from tg_bot_aggregator.core.time import utc_now
from tg_bot_aggregator.domain.bots.repository import BotRepository
from tg_bot_aggregator.domain.destinations.models import Destination
from tg_bot_aggregator.domain.destinations.repository import DestinationRepository
from tg_bot_aggregator.domain.media.paths import SharedFile, SharedPathError, validate_shared_file
from tg_bot_aggregator.domain.reliability.service import (
    SendQueueService,
    SendRateLimiter,
    compute_retry_decision,
    latency_ms_since,
)
from tg_bot_aggregator.domain.sending.models import SendHistory
from tg_bot_aggregator.domain.sending.repository import (
    SendAttemptRepository,
    SendHistoryRepository,
)
from tg_bot_aggregator.domain.templates.renderer import render_template_text
from tg_bot_aggregator.domain.templates.repository import TemplateRepository
from tg_bot_aggregator.infra.telegram_client import TelegramBotApiClient, TelegramBotApiError


class EventPublisher(Protocol):
    async def publish(self, event_type: str, data: dict[str, Any]) -> str:
        ...


class CallbackPublisher(Protocol):
    async def publish(self, url: str, payload: dict[str, Any]) -> None:
        ...


class NullEventPublisher:
    async def publish(self, event_type: str, data: dict[str, Any]) -> str:
        return f"local:{event_type}"


class HttpCallbackPublisher:
    async def publish(self, url: str, payload: dict[str, Any]) -> None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            await client.post(url, json=payload)


class SendServiceError(ValueError):
    pass


class IdempotencyConflictError(SendServiceError):
    pass


@dataclass(frozen=True)
class Target:
    chat_id: str
    message_thread_id: int | None
    destination_id: int | None


class SendService:
    def __init__(
        self,
        session: AsyncSession,
        bot_api: TelegramBotApiClient,
        settings: Settings,
        events: EventPublisher | None = None,
        callback_publisher: CallbackPublisher | None = None,
        *,
        rate_limiter: SendRateLimiter | None = None,
    ) -> None:
        self.session = session
        self.bot_api = bot_api
        self.settings = settings
        self.events = events or NullEventPublisher()
        self.callback_publisher = callback_publisher or HttpCallbackPublisher()
        self.rate_limiter = rate_limiter
        self.bots = BotRepository(session)
        self.destinations = DestinationRepository(session)
        self.templates = TemplateRepository(session)
        self.history = SendHistoryRepository(session)
        self.attempts = SendAttemptRepository(session)
        self.queue = SendQueueService(self.history, self.attempts)

    def _validate_shared_file(self, file_relative_path: str) -> SharedFile:
        try:
            return validate_shared_file(
                self.settings.shared_media_root,
                file_relative_path,
                self.settings.max_local_file_bytes,
                require_mount=self.settings.shared_media_require_mount,
            )
        except SharedPathError as exc:
            raise SendServiceError(str(exc)) from exc

    async def _bot_token(self, bot_id: int) -> str:
        bot = await self.bots.get(bot_id)
        if bot is None or not bot.is_active:
            raise NotFoundError(f"bot {bot_id} not found")
        return bot.token

    async def check_send_policy(self, bot_id: int) -> list[str]:
        if not self.settings.policy_enabled:
            return []
        errors: list[str] = []
        if self.settings.rate_limit_per_minute is not None:
            since = utc_now() - timedelta(minutes=1)
            count = await self.history.count_for_bot_since(bot_id, since)
            if count >= self.settings.rate_limit_per_minute:
                errors.append("rate limit exceeded for bot")
        return errors

    async def _target(
        self,
        bot_id: int,
        destination_id: int | None,
        destination_alias: str | None,
        chat_id: str | None,
        message_thread_id: int | None,
    ) -> Target:
        destination: Destination | None = None
        if destination_id is not None:
            destination = await self.destinations.get(destination_id)
            if destination is None or not destination.is_active or destination.bot_id != bot_id:
                raise NotFoundError(f"destination {destination_id} not found")
        elif destination_alias:
            destination = await self.destinations.get_by_alias(bot_id, destination_alias)
            if destination is None or not destination.is_active:
                raise NotFoundError(f"destination alias {destination_alias} not found")

        resolved_chat_id = destination.chat_id if destination else chat_id
        if not resolved_chat_id:
            raise SendServiceError("chat_id, destination_id, or destination_alias is required")
        resolved_thread_id = message_thread_id
        if resolved_thread_id is None and destination is not None:
            resolved_thread_id = destination.message_thread_id
        return Target(resolved_chat_id, resolved_thread_id, destination.id if destination else None)

    async def _upsert_destination_from_response(
        self,
        bot_id: int,
        target: Target,
        response: dict[str, Any],
    ) -> None:
        result = response.get("result", {})
        chat = result.get("chat")
        if not isinstance(chat, dict):
            return
        chat_id = str(chat.get("id") or target.chat_id)
        chat_type = str(chat.get("type") or "private")
        kind = "forum_topic" if target.message_thread_id is not None else chat_type
        if kind not in {"private", "group", "supergroup", "channel", "forum_topic"}:
            kind = "group"
        title = chat.get("title") or chat.get("first_name") or chat.get("username") or chat_id
        username = chat.get("username")
        await self.destinations.upsert_by_chat(
            bot_id=bot_id,
            chat_id=chat_id,
            message_thread_id=target.message_thread_id,
            kind=kind,
            title=str(title) if title is not None else None,
            username=str(username) if username is not None else None,
            is_active=True,
        )

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    async def _idempotent_existing(
        self,
        idempotency_key: str | None,
        fingerprint: str,
    ) -> SendHistory | None:
        if not idempotency_key:
            return None
        existing = await self.history.get_by_idempotency_key(idempotency_key)
        if existing is None:
            return None
        if existing.idempotency_fingerprint != fingerprint:
            raise IdempotencyConflictError("idempotency key was already used for another request")
        return existing

    def _clean_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in payload.items() if value is not None}

    def _is_future_send(self, send_at: datetime | None) -> bool:
        if send_at is None:
            return False
        resolved = send_at if send_at.tzinfo is not None else send_at.replace(tzinfo=UTC)
        return resolved > utc_now()

    async def _publish_event(self, event_type: str, data: dict[str, Any]) -> None:
        try:
            await self.events.publish(event_type, data)
        except Exception:
            return

    async def _publish_terminal_callback(self, event_type: str, row: SendHistory) -> None:
        if not self.settings.callback_enabled or not self.settings.callback_url:
            return
        payload = {
            "schema_version": "v1",
            "event_type": event_type,
            "send_history_id": row.id,
            "status": row.status,
        }
        try:
            await self.callback_publisher.publish(self.settings.callback_url, payload)
        except Exception as exc:
            await self._publish_event(
                "send.callback.failed",
                {"send_history_id": row.id, "error": str(exc)},
            )

    async def _create_or_reuse_history(
        self,
        *,
        bot_id: int,
        target: Target,
        tag: str | None,
        text: str | None,
        media_type: str,
        file_relative_path: str | None = None,
        file_size_bytes: int | None = None,
        send_mode: str,
        idempotency_key: str | None,
        request_payload: dict[str, Any],
        next_retry_at: datetime | None = None,
    ) -> tuple[SendHistory, bool]:
        fingerprint = self._fingerprint(request_payload)
        existing = await self._idempotent_existing(idempotency_key, fingerprint)
        if existing is not None:
            return existing, True

        row = await self.history.create(
            bot_id=bot_id,
            destination_id=target.destination_id,
            chat_id=target.chat_id,
            message_thread_id=target.message_thread_id,
            tag=tag,
            text=text,
            media_type=media_type,
            file_relative_path=file_relative_path,
            file_size_bytes=file_size_bytes,
            status="queued" if send_mode == "queued" else "created",
            send_mode=send_mode,
            idempotency_key=idempotency_key,
            idempotency_fingerprint=fingerprint if idempotency_key else None,
            next_retry_at=next_retry_at,
            request_payload_json=redact_secrets(request_payload),
        )
        await self.session.commit()
        await self._publish_event(
            "send.queued" if send_mode == "queued" else "send.created",
            {"send_history_id": row.id},
        )
        return row, False

    async def _execute_row_once(self, token: str, row: SendHistory) -> dict[str, Any]:
        payload = dict(row.request_payload_json or {})
        method = payload.pop("method", None)
        if method == "sendMessage":
            return await self.bot_api.send_message(token=token, **self._clean_payload(payload))
        if method == "sendDocument":
            return await self.bot_api.send_document(token=token, **self._clean_payload(payload))
        if method == "sendVideo":
            return await self.bot_api.send_video(token=token, **self._clean_payload(payload))
        raise SendServiceError("send history row has unsupported method")

    def _is_retryable(self, exc: TelegramBotApiError) -> bool:
        if exc.error_code is None:
            return True
        return exc.error_code == 429 or 500 <= exc.error_code <= 599

    async def _mark_success_from_response(
        self,
        row: SendHistory,
        response: dict[str, Any],
    ) -> SendHistory:
        await self._persist_success_from_response(row, response)
        await self._publish_event("send.succeeded", {"send_history_id": row.id})
        await self._publish_terminal_callback("send.succeeded", row)
        return row

    async def _persist_success_from_response(
        self,
        row: SendHistory,
        response: dict[str, Any],
    ) -> None:
        message_id = response.get("result", {}).get("message_id")
        await self._upsert_destination_from_response(
            row.bot_id,
            Target(row.chat_id, row.message_thread_id, row.destination_id),
            response,
        )
        await self.history.mark_succeeded(row, message_id, redact_secrets(response))
        await self.session.commit()

    async def _send_existing_row(self, token: str, row: SendHistory) -> SendHistory:
        try:
            response = await self._execute_row_once(token, row)
        except TelegramBotApiError as exc:
            await self.history.mark_failed(row, str(exc.error_code), exc.description, exc.payload)
            await self.session.commit()
            await self._publish_event("send.failed", {"send_history_id": row.id})
            await self._publish_terminal_callback("send.failed", row)
            return row
        return await self._mark_success_from_response(row, response)

    def _worker_retry_after_seconds(self) -> int:
        return max(1, ceil(max(0.0, self.settings.send_retry_base_delay_seconds)))

    async def _record_interrupted_attempt(
        self,
        *,
        row: SendHistory,
        worker_id: str,
        started_at: datetime,
        started_timer: float,
    ) -> None:
        await self.queue.record_attempt(
            row=row,
            worker_id=worker_id,
            started_at=started_at,
            finished_at=utc_now(),
            status="interrupted",
            telegram_error_code=None,
            error_kind="worker_cancelled",
            error_message="send worker was cancelled",
            retry_after_seconds=None,
            latency_ms=latency_ms_since(started_timer),
            response_payload=None,
        )
        await self.session.commit()

    async def _record_success_attempt_once(
        self,
        *,
        row: SendHistory,
        worker_id: str,
        started_at: datetime,
        finished_at: datetime,
        started_timer: float,
        response: dict[str, Any],
    ) -> None:
        existing = await self.attempts.list_for_send(row.id)
        if any(
            item.attempt_number == row.attempt_count and item.status == "succeeded"
            for item in existing
        ):
            return
        await self.queue.record_attempt(
            row=row,
            worker_id=worker_id,
            started_at=started_at,
            finished_at=finished_at,
            status="succeeded",
            telegram_error_code=None,
            error_kind=None,
            error_message=None,
            retry_after_seconds=None,
            latency_ms=latency_ms_since(started_timer),
            response_payload=response,
        )

    async def _complete_queued_success(
        self,
        *,
        row: SendHistory,
        worker_id: str,
        started_at: datetime,
        started_timer: float,
        response: dict[str, Any],
    ) -> SendHistory:
        await self._record_success_attempt_once(
            row=row,
            worker_id=worker_id,
            started_at=started_at,
            finished_at=utc_now(),
            started_timer=started_timer,
            response=response,
        )
        await self._persist_success_from_response(row, response)
        await self._publish_event("send.succeeded", {"send_history_id": row.id})
        await self._publish_terminal_callback("send.succeeded", row)
        return row

    async def _complete_queued_success_after_cancellation(
        self,
        *,
        row: SendHistory,
        worker_id: str,
        started_at: datetime,
        started_timer: float,
        response: dict[str, Any],
    ) -> None:
        task = asyncio.current_task()
        pending_cancellations = task.cancelling() if task is not None else 0
        for _ in range(pending_cancellations):
            task.uncancel()
        await self._complete_queued_success(
            row=row,
            worker_id=worker_id,
            started_at=started_at,
            started_timer=started_timer,
            response=response,
        )

    async def _defer_worker_error(
        self,
        *,
        row: SendHistory,
        worker_id: str,
        started_at: datetime,
        started_timer: float,
        exc: Exception,
    ) -> SendHistory:
        finished_at = utc_now()
        retry_after_seconds = self._worker_retry_after_seconds()
        message = redact_text(str(exc)) or exc.__class__.__name__
        response_payload = {"exception_type": exc.__class__.__name__}
        await self.queue.record_attempt(
            row=row,
            worker_id=worker_id,
            started_at=started_at,
            finished_at=finished_at,
            status="deferred",
            telegram_error_code=None,
            error_kind="worker_error",
            error_message=message,
            retry_after_seconds=retry_after_seconds,
            latency_ms=latency_ms_since(started_timer),
            response_payload=response_payload,
        )
        await self.history.mark_deferred(
            row,
            error_code=exc.__class__.__name__,
            error_message=message,
            error_kind="worker_error",
            next_retry_at=finished_at + timedelta(seconds=retry_after_seconds),
            retry_after_seconds=retry_after_seconds,
            response=response_payload,
        )
        await self.session.commit()
        await self._publish_event(
            "send.deferred",
            {
                "send_history_id": row.id,
                "next_retry_at": row.next_retry_at.isoformat()
                if row.next_retry_at is not None
                else None,
            },
        )
        return row

    async def process_queued_send(
        self,
        send_history_id: int,
        worker_id: str = "worker",
    ) -> SendHistory:
        row = await self.history.get(send_history_id)
        if row is None:
            raise NotFoundError(f"send history {send_history_id} not found")
        if row.status in {"succeeded", "cancelled", "dead_letter", "blocked"}:
            return row
        if self._is_future_send(row.next_retry_at):
            return row
        leased = await self.queue.acquire_lease(
            row,
            worker_id=worker_id,
            lease_seconds=self.settings.send_worker_lease_seconds,
        )
        if leased is None:
            return row
        row = leased
        token = await self._bot_token(row.bot_id)
        attempt = row.attempt_count + 1
        started_at = utc_now()
        started_timer = monotonic()
        await self.history.mark_sending(row, attempt)
        row.last_attempt_at = started_at
        await self.session.commit()

        try:
            await self._publish_event(
                "send.locked",
                {"send_history_id": row.id, "worker_id": worker_id},
            )
            if self.settings.reliability_enabled and self.rate_limiter is not None:
                rate_decision = await self.rate_limiter.check_and_increment(
                    bot_id=row.bot_id,
                    chat_id=row.chat_id,
                    destination_id=row.destination_id,
                )
                if not rate_decision.allowed:
                    retry_after_seconds = rate_decision.retry_after_seconds or 60
                    finished_at = utc_now()
                    await self.queue.record_attempt(
                        row=row,
                        worker_id=worker_id,
                        started_at=started_at,
                        finished_at=finished_at,
                        status="deferred",
                        telegram_error_code=None,
                        error_kind="rate_limit",
                        error_message=rate_decision.message or "rate limit exceeded",
                        retry_after_seconds=retry_after_seconds,
                        latency_ms=latency_ms_since(started_timer),
                        response_payload={"bucket_key": rate_decision.bucket_key},
                    )
                    await self.history.mark_deferred(
                        row,
                        error_code="rate_limit",
                        error_message=rate_decision.message or "rate limit exceeded",
                        error_kind="rate_limit",
                        next_retry_at=finished_at + timedelta(seconds=retry_after_seconds),
                        retry_after_seconds=retry_after_seconds,
                        response=None,
                    )
                    await self.session.commit()
                    await self._publish_event(
                        "send.deferred",
                        {
                            "send_history_id": row.id,
                            "next_retry_at": row.next_retry_at.isoformat()
                            if row.next_retry_at is not None
                            else None,
                        },
                    )
                    return row

            response = await self._execute_row_once(token, row)
        except TelegramBotApiError as exc:
            decision = compute_retry_decision(
                settings=self.settings,
                error=exc,
                attempt_number=attempt,
                now=utc_now(),
            )
            finished_at = utc_now()
            await self.queue.record_attempt(
                row=row,
                worker_id=worker_id,
                started_at=started_at,
                finished_at=finished_at,
                status=decision.terminal_status,
                telegram_error_code=str(exc.error_code) if exc.error_code is not None else None,
                error_kind=decision.error_kind,
                error_message=exc.description,
                retry_after_seconds=decision.retry_after_seconds,
                latency_ms=latency_ms_since(started_timer),
                response_payload=exc.payload,
            )
            if decision.retry and decision.next_retry_at is not None:
                await self.history.mark_deferred(
                    row,
                    str(exc.error_code) if exc.error_code is not None else None,
                    exc.description,
                    decision.error_kind,
                    decision.next_retry_at,
                    decision.retry_after_seconds,
                    redact_secrets(exc.payload),
                )
                await self.session.commit()
                await self._publish_event(
                    "send.deferred",
                    {
                        "send_history_id": row.id,
                        "next_retry_at": row.next_retry_at.isoformat()
                        if row.next_retry_at is not None
                        else None,
                    },
                )
                return row
            if decision.terminal_status == "blocked":
                await self.history.mark_blocked(
                    row,
                    str(exc.error_code) if exc.error_code is not None else None,
                    exc.description,
                    decision.error_kind,
                )
                await self.session.commit()
                await self._publish_event("send.blocked", {"send_history_id": row.id})
                await self._publish_terminal_callback("send.blocked", row)
                return row
            await self.history.mark_dead_letter(
                row,
                str(exc.error_code) if exc.error_code is not None else None,
                exc.description,
                decision.error_kind,
                redact_secrets(exc.payload),
            )
            await self.session.commit()
            await self._publish_event("send.dead_letter", {"send_history_id": row.id})
            await self._publish_terminal_callback("send.dead_letter", row)
            return row
        except asyncio.CancelledError:
            await self._record_interrupted_attempt(
                row=row,
                worker_id=worker_id,
                started_at=started_at,
                started_timer=started_timer,
            )
            raise
        except Exception as exc:
            return await self._defer_worker_error(
                row=row,
                worker_id=worker_id,
                started_at=started_at,
                started_timer=started_timer,
                exc=exc,
            )

        try:
            return await self._complete_queued_success(
                row=row,
                worker_id=worker_id,
                started_at=started_at,
                started_timer=started_timer,
                response=response,
            )
        except asyncio.CancelledError:
            await self._complete_queued_success_after_cancellation(
                row=row,
                worker_id=worker_id,
                started_at=started_at,
                started_timer=started_timer,
                response=response,
            )
            raise

    async def retry_history(self, send_history_id: int) -> SendHistory:
        row = await self.history.get(send_history_id)
        if row is None:
            raise NotFoundError(f"send history {send_history_id} not found")
        if row.status not in {"failed", "dead_letter", "blocked"}:
            raise SendServiceError(
                "only failed, dead-letter, or blocked send history rows can be retried"
            )
        row.status = "queued"
        row.error_code = None
        row.error_message = None
        row.last_error_kind = None
        row.failed_at = None
        row.queued_task_id = None
        row.next_retry_at = None
        row.retry_after_seconds = None
        row.locked_at = None
        row.locked_by = None
        row.lock_expires_at = None
        await self.session.commit()
        await self._publish_event("send.retry_scheduled", {"send_history_id": row.id})
        return row

    async def cancel_history(self, send_history_id: int) -> SendHistory:
        row = await self.history.get(send_history_id)
        if row is None:
            raise NotFoundError(f"send history {send_history_id} not found")
        if row.status not in {"created", "queued", "deferred"}:
            raise SendServiceError(
                "only created, queued, or deferred send history rows can be cancelled"
            )
        await self.history.mark_cancelled(row)
        await self.session.commit()
        await self._publish_event("send.cancelled", {"send_history_id": row.id})
        return row

    async def _queue_or_send(
        self,
        *,
        bot_id: int,
        token: str,
        target: Target,
        tag: str | None,
        text: str | None,
        media_type: str,
        send_mode: str,
        idempotency_key: str | None,
        request_payload: dict[str, Any],
        file_relative_path: str | None = None,
        file_size_bytes: int | None = None,
        send_at: datetime | None = None,
    ) -> SendHistory:
        if send_mode not in {"sync", "queued"}:
            raise SendServiceError("send_mode must be sync or queued")
        effective_send_mode = "queued" if self._is_future_send(send_at) else send_mode
        policy_errors = await self.check_send_policy(bot_id)
        if policy_errors:
            raise SendServiceError("; ".join(policy_errors))
        row, reused = await self._create_or_reuse_history(
            bot_id=bot_id,
            target=target,
            tag=tag,
            text=text,
            media_type=media_type,
            file_relative_path=file_relative_path,
            file_size_bytes=file_size_bytes,
            send_mode=effective_send_mode,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            next_retry_at=send_at if effective_send_mode == "queued" else None,
        )
        if reused or effective_send_mode == "queued":
            return row
        return await self._send_existing_row(token, row)

    async def dry_run_text(
        self,
        bot_id: int,
        text: str,
        destination_id: int | None = None,
        destination_alias: str | None = None,
        chat_id: str | None = None,
        tag: str | None = None,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
        message_thread_id: int | None = None,
    ) -> dict[str, Any]:
        await self._bot_token(bot_id)
        target = await self._target(
            bot_id,
            destination_id,
            destination_alias,
            chat_id,
            message_thread_id,
        )
        payload = self._clean_payload(
            {
                "chat_id": target.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": disable_web_page_preview,
                "message_thread_id": target.message_thread_id,
            }
        )
        return {
            "ok": True,
            "method": "sendMessage",
            "bot_id": bot_id,
            "chat_id": target.chat_id,
            "message_thread_id": target.message_thread_id,
            "destination_id": target.destination_id,
            "tag": tag,
            "payload": payload,
        }

    async def dry_run_template(
        self,
        bot_id: int,
        tag: str,
        destination_id: int | None = None,
        destination_alias: str | None = None,
        chat_id: str | None = None,
        message_thread_id: int | None = None,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        template = await self.templates.get_by_tag(tag)
        if template is None:
            raise NotFoundError(f"template {tag} not found")
        text = render_template_text(template.text, variables)
        return await self.dry_run_text(
            bot_id=bot_id,
            text=text,
            destination_id=destination_id,
            destination_alias=destination_alias,
            chat_id=chat_id,
            tag=tag,
            parse_mode=template.parse_mode,
            disable_web_page_preview=template.disable_web_page_preview,
            message_thread_id=message_thread_id,
        )

    async def dry_run_file(
        self,
        bot_id: int,
        media_type: str,
        file_relative_path: str,
        destination_id: int | None = None,
        destination_alias: str | None = None,
        chat_id: str | None = None,
        caption: str | None = None,
        tag: str | None = None,
        parse_mode: str | None = None,
        message_thread_id: int | None = None,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.settings.is_local_bot_api:
            raise SendServiceError("local file sends require local Telegram Bot API base URL")
        if media_type not in {"document", "video"}:
            raise SendServiceError("media_type must be document or video")
        await self._bot_token(bot_id)
        target = await self._target(
            bot_id,
            destination_id,
            destination_alias,
            chat_id,
            message_thread_id,
        )
        rendered_caption = render_template_text(caption, variables) if caption else caption
        shared_file = self._validate_shared_file(file_relative_path)
        field_name = "document" if media_type == "document" else "video"
        method = "sendDocument" if media_type == "document" else "sendVideo"
        payload = self._clean_payload(
            {
                "chat_id": target.chat_id,
                field_name: shared_file.file_uri,
                "caption": rendered_caption,
                "parse_mode": parse_mode,
                "message_thread_id": target.message_thread_id,
            }
        )
        return {
            "ok": True,
            "method": method,
            "bot_id": bot_id,
            "chat_id": target.chat_id,
            "message_thread_id": target.message_thread_id,
            "destination_id": target.destination_id,
            "payload": payload,
        }

    async def send_text(
        self,
        bot_id: int,
        text: str,
        destination_id: int | None = None,
        destination_alias: str | None = None,
        chat_id: str | None = None,
        tag: str | None = None,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
        message_thread_id: int | None = None,
        send_mode: str = "sync",
        send_at: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> SendHistory:
        token = await self._bot_token(bot_id)
        target = await self._target(
            bot_id,
            destination_id,
            destination_alias,
            chat_id,
            message_thread_id,
        )
        request_payload = {
            "method": "sendMessage",
            "chat_id": target.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
            "message_thread_id": target.message_thread_id,
        }
        return await self._queue_or_send(
            bot_id=bot_id,
            token=token,
            target=target,
            tag=tag,
            text=text,
            media_type="none",
            send_mode=send_mode,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            send_at=send_at,
        )

    async def send_template(
        self,
        bot_id: int,
        tag: str,
        destination_id: int | None = None,
        destination_alias: str | None = None,
        chat_id: str | None = None,
        message_thread_id: int | None = None,
        variables: dict[str, Any] | None = None,
        send_mode: str = "sync",
        send_at: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> SendHistory:
        template = await self.templates.get_by_tag(tag)
        if template is None:
            raise NotFoundError(f"template {tag} not found")
        text = render_template_text(template.text, variables)
        return await self.send_text(
            bot_id=bot_id,
            text=text,
            destination_id=destination_id,
            destination_alias=destination_alias,
            chat_id=chat_id,
            tag=tag,
            parse_mode=template.parse_mode,
            disable_web_page_preview=template.disable_web_page_preview,
            message_thread_id=message_thread_id,
            send_mode=send_mode,
            send_at=send_at,
            idempotency_key=idempotency_key,
        )

    async def send_file(
        self,
        bot_id: int,
        media_type: str,
        file_relative_path: str,
        destination_id: int | None = None,
        destination_alias: str | None = None,
        chat_id: str | None = None,
        caption: str | None = None,
        tag: str | None = None,
        parse_mode: str | None = None,
        message_thread_id: int | None = None,
        variables: dict[str, Any] | None = None,
        send_mode: str = "sync",
        send_at: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> SendHistory:
        if not self.settings.is_local_bot_api:
            raise SendServiceError("local file sends require local Telegram Bot API base URL")
        if media_type not in {"document", "video"}:
            raise SendServiceError("media_type must be document or video")

        token = await self._bot_token(bot_id)
        target = await self._target(
            bot_id,
            destination_id,
            destination_alias,
            chat_id,
            message_thread_id,
        )
        rendered_caption = render_template_text(caption, variables) if caption else caption
        shared_file = self._validate_shared_file(file_relative_path)
        field_name = "document" if media_type == "document" else "video"
        method = "sendDocument" if media_type == "document" else "sendVideo"
        request_payload = {
            "method": method,
            "chat_id": target.chat_id,
            field_name: shared_file.file_uri,
            "caption": rendered_caption,
            "parse_mode": parse_mode,
            "message_thread_id": target.message_thread_id,
        }
        return await self._queue_or_send(
            bot_id=bot_id,
            token=token,
            target=target,
            tag=tag,
            text=rendered_caption,
            media_type=media_type,
            file_relative_path=file_relative_path,
            file_size_bytes=shared_file.size_bytes,
            send_mode=send_mode,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            send_at=send_at,
        )

    async def send_media_reference(
        self,
        bot_id: int,
        media_type: str,
        file_reference: str,
        destination_id: int | None = None,
        destination_alias: str | None = None,
        chat_id: str | None = None,
        caption: str | None = None,
        parse_mode: str | None = None,
        message_thread_id: int | None = None,
        send_mode: str = "sync",
        send_at: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> SendHistory:
        if media_type not in {"document", "video"}:
            raise SendServiceError("media_type must be document or video")

        token = await self._bot_token(bot_id)
        target = await self._target(
            bot_id,
            destination_id,
            destination_alias,
            chat_id,
            message_thread_id,
        )
        field_name = "document" if media_type == "document" else "video"
        method = "sendDocument" if media_type == "document" else "sendVideo"
        request_payload = {
            "method": method,
            "chat_id": target.chat_id,
            field_name: file_reference,
            "caption": caption,
            "parse_mode": parse_mode,
            "message_thread_id": target.message_thread_id,
        }
        return await self._queue_or_send(
            bot_id=bot_id,
            token=token,
            target=target,
            tag=None,
            text=caption,
            media_type=media_type,
            send_mode=send_mode,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            send_at=send_at,
        )
