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


class EventPublisher(Protocol):
    async def publish(self, event_type: str, data: dict[str, Any]) -> str:
        ...


class NullEventPublisher:
    async def publish(self, event_type: str, data: dict[str, Any]) -> str:
        return f"local:{event_type}"


class SendServiceError(ValueError):
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
        destination_id: int | None,
        chat_id: str | None,
        message_thread_id: int | None,
    ) -> Target:
        destination: Destination | None = None
        if destination_id is not None:
            destination = await self.destinations.get(destination_id)
            if destination is None or not destination.is_active:
                raise NotFoundError(f"destination {destination_id} not found")
        resolved_chat_id = destination.chat_id if destination else chat_id
        if not resolved_chat_id:
            raise SendServiceError("chat_id or destination_id is required")
        resolved_thread_id = message_thread_id
        if resolved_thread_id is None and destination is not None:
            resolved_thread_id = destination.message_thread_id
        return Target(resolved_chat_id, resolved_thread_id, destination_id)

    async def send_text(
        self,
        bot_id: int,
        text: str,
        destination_id: int | None = None,
        chat_id: str | None = None,
        tag: str | None = None,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
        message_thread_id: int | None = None,
    ) -> SendHistory:
        token = await self._bot_token(bot_id)
        target = await self._target(destination_id, chat_id, message_thread_id)
        request_payload = {
            "chat_id": target.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
            "message_thread_id": target.message_thread_id,
        }
        row = await self.history.create(
            bot_id=bot_id,
            destination_id=target.destination_id,
            chat_id=target.chat_id,
            message_thread_id=target.message_thread_id,
            tag=tag,
            text=text,
            media_type="none",
            status="created",
            request_payload_json=redact_secrets(request_payload),
        )
        await self.session.commit()
        await self.events.publish("send.created", {"send_history_id": row.id})

        try:
            response = await self.bot_api.send_message(
                token=token,
                chat_id=target.chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                message_thread_id=target.message_thread_id,
            )
        except TelegramBotApiError as exc:
            await self.history.mark_failed(row, str(exc.error_code), exc.description, exc.payload)
            await self.session.commit()
            await self.events.publish("send.failed", {"send_history_id": row.id})
            return row

        message_id = response.get("result", {}).get("message_id")
        await self.history.mark_succeeded(row, message_id, redact_secrets(response))
        await self.session.commit()
        await self.events.publish("send.succeeded", {"send_history_id": row.id})
        return row

    async def send_template(
        self,
        bot_id: int,
        tag: str,
        destination_id: int | None = None,
        chat_id: str | None = None,
        message_thread_id: int | None = None,
    ) -> SendHistory:
        template = await self.templates.get_by_tag(tag)
        if template is None:
            raise NotFoundError(f"template {tag} not found")
        return await self.send_text(
            bot_id=bot_id,
            text=template.text,
            destination_id=destination_id,
            chat_id=chat_id,
            tag=tag,
            parse_mode=template.parse_mode,
            disable_web_page_preview=template.disable_web_page_preview,
            message_thread_id=message_thread_id,
        )

    async def send_file(
        self,
        bot_id: int,
        media_type: str,
        file_relative_path: str,
        destination_id: int | None = None,
        chat_id: str | None = None,
        caption: str | None = None,
        tag: str | None = None,
        parse_mode: str | None = None,
        message_thread_id: int | None = None,
    ) -> SendHistory:
        if not self.settings.is_local_bot_api:
            raise SendServiceError("local file sends require local Telegram Bot API base URL")
        if media_type not in {"document", "video"}:
            raise SendServiceError("media_type must be document or video")

        token = await self._bot_token(bot_id)
        target = await self._target(destination_id, chat_id, message_thread_id)
        shared_file = validate_shared_file(
            self.settings.shared_media_root,
            file_relative_path,
            self.settings.max_local_file_bytes,
        )
        request_payload = {
            "chat_id": target.chat_id,
            "caption": caption,
            "parse_mode": parse_mode,
            "message_thread_id": target.message_thread_id,
            "media_type": media_type,
            "file_relative_path": file_relative_path,
        }
        row = await self.history.create(
            bot_id=bot_id,
            destination_id=target.destination_id,
            chat_id=target.chat_id,
            message_thread_id=target.message_thread_id,
            tag=tag,
            text=caption,
            media_type=media_type,
            file_relative_path=file_relative_path,
            file_size_bytes=shared_file.size_bytes,
            status="created",
            request_payload_json=redact_secrets(request_payload),
        )
        await self.session.commit()
        await self.events.publish("send.created", {"send_history_id": row.id})

        try:
            if media_type == "document":
                response = await self.bot_api.send_document(
                    token=token,
                    chat_id=target.chat_id,
                    document=shared_file.file_uri,
                    caption=caption,
                    parse_mode=parse_mode,
                    message_thread_id=target.message_thread_id,
                )
            else:
                response = await self.bot_api.send_video(
                    token=token,
                    chat_id=target.chat_id,
                    video=shared_file.file_uri,
                    caption=caption,
                    parse_mode=parse_mode,
                    message_thread_id=target.message_thread_id,
                )
        except TelegramBotApiError as exc:
            await self.history.mark_failed(row, str(exc.error_code), exc.description, exc.payload)
            await self.session.commit()
            await self.events.publish("send.failed", {"send_history_id": row.id})
            return row

        message_id = response.get("result", {}).get("message_id")
        await self.history.mark_succeeded(row, message_id, redact_secrets(response))
        await self.session.commit()
        await self.events.publish("send.succeeded", {"send_history_id": row.id})
        return row

