import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.models import Destination, SendHistory
from tg_bot_aggregator.repositories import (
    BotRepository,
    DestinationRepository,
    NotFoundError,
    SendHistoryRepository,
    TemplateRepository,
)
from tg_bot_aggregator.security import redact_secrets
from tg_bot_aggregator.shared_paths import validate_shared_file
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiClient, TelegramBotApiError
from tg_bot_aggregator.template_renderer import render_template_text


class EventPublisher(Protocol):
    async def publish(self, event_type: str, data: dict[str, Any]) -> str:
        ...


class NullEventPublisher:
    async def publish(self, event_type: str, data: dict[str, Any]) -> str:
        return f"local:{event_type}"


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
    ) -> None:
        self.session = session
        self.bot_api = bot_api
        self.settings = settings
        self.events = events or NullEventPublisher()
        self.bots = BotRepository(session)
        self.destinations = DestinationRepository(session)
        self.templates = TemplateRepository(session)
        self.history = SendHistoryRepository(session)

    async def _bot_token(self, bot_id: int) -> str:
        bot = await self.bots.get(bot_id)
        if bot is None or not bot.is_active:
            raise NotFoundError(f"bot {bot_id} not found")
        return bot.token

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
            request_payload_json=redact_secrets(request_payload),
        )
        await self.session.commit()
        await self.events.publish(
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
        message_id = response.get("result", {}).get("message_id")
        await self._upsert_destination_from_response(
            row.bot_id,
            Target(row.chat_id, row.message_thread_id, row.destination_id),
            response,
        )
        await self.history.mark_succeeded(row, message_id, redact_secrets(response))
        await self.session.commit()
        await self.events.publish("send.succeeded", {"send_history_id": row.id})
        return row

    async def _send_existing_row(self, token: str, row: SendHistory) -> SendHistory:
        try:
            response = await self._execute_row_once(token, row)
        except TelegramBotApiError as exc:
            await self.history.mark_failed(row, str(exc.error_code), exc.description, exc.payload)
            await self.session.commit()
            await self.events.publish("send.failed", {"send_history_id": row.id})
            return row
        return await self._mark_success_from_response(row, response)

    async def process_queued_send(self, send_history_id: int) -> SendHistory:
        row = await self.history.get(send_history_id)
        if row is None:
            raise NotFoundError(f"send history {send_history_id} not found")
        if row.status == "succeeded":
            return row
        token = await self._bot_token(row.bot_id)
        max_attempts = max(1, self.settings.send_retry_max_attempts)
        delay = max(0.0, self.settings.send_retry_delay_seconds)
        last_error: TelegramBotApiError | None = None

        for attempt in range(row.attempt_count + 1, max_attempts + 1):
            await self.history.mark_sending(row, attempt)
            await self.session.commit()
            try:
                response = await self._execute_row_once(token, row)
            except TelegramBotApiError as exc:
                last_error = exc
                if attempt < max_attempts and self._is_retryable(exc):
                    await asyncio.sleep(delay)
                    continue
                await self.history.mark_failed(
                    row,
                    str(exc.error_code),
                    exc.description,
                    exc.payload,
                )
                await self.session.commit()
                await self.events.publish("send.failed", {"send_history_id": row.id})
                return row
            return await self._mark_success_from_response(row, response)

        if last_error is not None:
            await self.history.mark_failed(
                row,
                str(last_error.error_code),
                last_error.description,
                last_error.payload,
            )
            await self.session.commit()
            await self.events.publish("send.failed", {"send_history_id": row.id})
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
    ) -> SendHistory:
        if send_mode not in {"sync", "queued"}:
            raise SendServiceError("send_mode must be sync or queued")
        row, reused = await self._create_or_reuse_history(
            bot_id=bot_id,
            target=target,
            tag=tag,
            text=text,
            media_type=media_type,
            file_relative_path=file_relative_path,
            file_size_bytes=file_size_bytes,
            send_mode=send_mode,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
        )
        if reused or send_mode == "queued":
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
        shared_file = validate_shared_file(
            self.settings.shared_media_root,
            file_relative_path,
            self.settings.max_local_file_bytes,
        )
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
        shared_file = validate_shared_file(
            self.settings.shared_media_root,
            file_relative_path,
            self.settings.max_local_file_bytes,
        )
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
        )
