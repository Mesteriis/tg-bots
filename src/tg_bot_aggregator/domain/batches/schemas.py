from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from tg_bot_aggregator.domain.sending.schemas import SendPreviewRead


class SendBatchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    bot_id: int
    send_kind: str
    destination_ids: list[int] = Field(default_factory=list)
    chat_ids: list[str] = Field(default_factory=list)
    template_tag: str | None = None
    text: str | None = None
    media_type: str = "none"
    file_relative_path: str | None = None
    caption: str | None = None
    parse_mode: str | None = None
    disable_web_page_preview: bool | None = None
    variables: dict[str, Any] = Field(default_factory=dict)


class SendBatchItemRead(BaseModel):
    id: int
    batch_id: int
    destination_id: int | None
    chat_id: str
    message_thread_id: int | None
    status: str
    send_history_id: int | None
    error_message: str | None


class SendBatchRead(BaseModel):
    id: int
    name: str
    description: str | None
    bot_id: int
    send_kind: str
    status: str
    template_tag: str | None
    text: str | None
    media_type: str
    file_relative_path: str | None
    caption: str | None
    parse_mode: str | None
    disable_web_page_preview: bool | None
    variables: dict[str, Any]
    progress: dict[str, int]
    items: list[SendBatchItemRead]
    created_at: datetime
    updated_at: datetime
    queued_at: datetime | None
    finished_at: datetime | None


class SendBatchPreviewRead(BaseModel):
    batch_id: int
    previews: list[SendPreviewRead]
