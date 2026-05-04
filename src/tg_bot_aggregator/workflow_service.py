from typing import Any

from tg_bot_aggregator.domain.sending.service import SendService, SendServiceError
from tg_bot_aggregator.repositories import NotFoundError, SendBatchRepository


class WorkflowService:
    def __init__(self, send_service: SendService) -> None:
        self.send_service = send_service
        self.batches = SendBatchRepository(send_service.session)

    async def preview_send(self, kind: str, **values: Any) -> dict[str, Any]:
        if kind == "text":
            text = values.get("text")
            if not isinstance(text, str) or not text:
                raise SendServiceError("text is required for text preview")
            preview = await self.send_service.dry_run_text(
                bot_id=values["bot_id"],
                text=text,
                destination_id=values.get("destination_id"),
                destination_alias=values.get("destination_alias"),
                chat_id=values.get("chat_id"),
                tag=values.get("tag"),
                parse_mode=values.get("parse_mode"),
                disable_web_page_preview=values.get("disable_web_page_preview"),
                message_thread_id=values.get("message_thread_id"),
            )
        elif kind == "template":
            tag = values.get("tag")
            if not isinstance(tag, str) or not tag:
                raise SendServiceError("tag is required for template preview")
            preview = await self.send_service.dry_run_template(
                bot_id=values["bot_id"],
                tag=tag,
                destination_id=values.get("destination_id"),
                destination_alias=values.get("destination_alias"),
                chat_id=values.get("chat_id"),
                message_thread_id=values.get("message_thread_id"),
                variables=values.get("variables"),
            )
        elif kind == "file":
            media_type = values.get("media_type")
            file_relative_path = values.get("file_relative_path")
            if media_type not in {"document", "video"}:
                raise SendServiceError("media_type is required for file preview")
            if not isinstance(file_relative_path, str) or not file_relative_path:
                raise SendServiceError("file_relative_path is required for file preview")
            preview = await self.send_service.dry_run_file(
                bot_id=values["bot_id"],
                media_type=media_type,
                file_relative_path=file_relative_path,
                destination_id=values.get("destination_id"),
                destination_alias=values.get("destination_alias"),
                chat_id=values.get("chat_id"),
                caption=values.get("caption"),
                tag=values.get("tag"),
                parse_mode=values.get("parse_mode"),
                message_thread_id=values.get("message_thread_id"),
                variables=values.get("variables"),
            )
        else:
            raise SendServiceError("kind must be text, template, or file")
        return {"kind": kind, **preview}

    def _batch_payload(self, batch: object, item: object) -> dict[str, Any]:
        return {
            "bot_id": batch.bot_id,
            "text": batch.text,
            "tag": batch.template_tag,
            "destination_id": item.destination_id,
            "chat_id": None if item.destination_id is not None else item.chat_id,
            "message_thread_id": item.message_thread_id,
            "parse_mode": batch.parse_mode,
            "disable_web_page_preview": batch.disable_web_page_preview,
            "media_type": batch.media_type if batch.media_type != "none" else None,
            "file_relative_path": batch.file_relative_path,
            "caption": batch.caption,
            "variables": batch.variables_json or {},
        }

    async def preview_batch(self, batch_id: int) -> dict[str, Any]:
        batch = await self.batches.get_batch(batch_id)
        if batch is None:
            raise NotFoundError(f"send batch {batch_id} not found")
        items = await self.batches.list_items(batch_id)
        previews = [
            await self.preview_send(kind=batch.send_kind, **self._batch_payload(batch, item))
            for item in items
            if item.status in {"pending", "queued"}
        ]
        return {"batch_id": batch.id, "previews": previews}

    async def enqueue_batch(self, batch_id: int) -> object:
        batch = await self.batches.get_batch(batch_id)
        if batch is None:
            raise NotFoundError(f"send batch {batch_id} not found")
        items = await self.batches.list_items(batch_id)
        for item in items:
            if item.status not in {"pending", "queued"}:
                continue
            payload = self._batch_payload(batch, item)
            if batch.send_kind == "text":
                row = await self.send_service.send_text(
                    bot_id=batch.bot_id,
                    text=payload["text"] or "",
                    destination_id=payload["destination_id"],
                    chat_id=payload["chat_id"],
                    tag=payload["tag"],
                    parse_mode=payload["parse_mode"],
                    disable_web_page_preview=payload["disable_web_page_preview"],
                    message_thread_id=payload["message_thread_id"],
                    send_mode="queued",
                )
            elif batch.send_kind == "template":
                row = await self.send_service.send_template(
                    bot_id=batch.bot_id,
                    tag=payload["tag"] or "",
                    destination_id=payload["destination_id"],
                    chat_id=payload["chat_id"],
                    message_thread_id=payload["message_thread_id"],
                    variables=payload["variables"],
                    send_mode="queued",
                )
            elif batch.send_kind == "file":
                row = await self.send_service.send_file(
                    bot_id=batch.bot_id,
                    media_type=payload["media_type"] or "document",
                    file_relative_path=payload["file_relative_path"] or "",
                    destination_id=payload["destination_id"],
                    chat_id=payload["chat_id"],
                    caption=payload["caption"],
                    tag=payload["tag"],
                    parse_mode=payload["parse_mode"],
                    message_thread_id=payload["message_thread_id"],
                    variables=payload["variables"],
                    send_mode="queued",
                )
            else:
                raise SendServiceError("batch send_kind must be text, template, or file")
            await self.batches.mark_item_status(item, "queued", send_history_id=row.id)
        await self.batches.mark_batch_status(batch, "queued")
        await self.send_service.session.commit()
        return batch

    async def cancel_batch(self, batch_id: int) -> object:
        batch = await self.batches.get_batch(batch_id)
        if batch is None:
            raise NotFoundError(f"send batch {batch_id} not found")
        items = await self.batches.list_items(batch_id)
        for item in items:
            if item.status not in {"pending", "queued"}:
                continue
            if item.send_history_id is not None:
                try:
                    await self.send_service.cancel_history(item.send_history_id)
                except SendServiceError:
                    pass
            await self.batches.mark_item_status(item, "cancelled")
        await self.batches.mark_batch_status(batch, "cancelled")
        await self.send_service.session.commit()
        return batch
