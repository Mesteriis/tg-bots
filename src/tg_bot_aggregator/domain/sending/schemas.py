from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SendProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    bot_id: int
    send_kind: Literal["text", "template", "file"]
    destination_id: int | None = None
    destination_alias: str | None = None
    chat_id: str | None = None
    message_thread_id: int | None = None
    template_tag: str | None = None
    text: str | None = None
    media_type: Literal["none", "document", "video"] = "none"
    file_relative_path: str | None = None
    caption: str | None = None
    parse_mode: str | None = None
    disable_web_page_preview: bool | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class SendProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    bot_id: int | None = None
    send_kind: Literal["text", "template", "file"] | None = None
    destination_id: int | None = None
    destination_alias: str | None = None
    chat_id: str | None = None
    message_thread_id: int | None = None
    template_tag: str | None = None
    text: str | None = None
    media_type: Literal["none", "document", "video"] | None = None
    file_relative_path: str | None = None
    caption: str | None = None
    parse_mode: str | None = None
    disable_web_page_preview: bool | None = None
    variables: dict[str, Any] | None = None
    is_active: bool | None = None


class SendProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    bot_id: int
    send_kind: str
    destination_id: int | None
    destination_alias: str | None
    chat_id: str | None
    message_thread_id: int | None
    template_tag: str | None
    text: str | None
    media_type: str
    file_relative_path: str | None
    caption: str | None
    parse_mode: str | None
    disable_web_page_preview: bool | None
    variables: dict[str, Any] = Field(default_factory=dict, validation_alias="variables_json")
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SendTextRequest(BaseModel):
    bot_id: int
    text: str
    destination_id: int | None = None
    destination_alias: str | None = None
    chat_id: str | None = None
    tag: str | None = None
    parse_mode: str | None = None
    disable_web_page_preview: bool | None = None
    message_thread_id: int | None = None
    send_mode: Literal["sync", "queued"] = "sync"
    send_at: datetime | None = None


class SendTemplateRequest(BaseModel):
    bot_id: int
    tag: str
    destination_id: int | None = None
    destination_alias: str | None = None
    chat_id: str | None = None
    message_thread_id: int | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    send_mode: Literal["sync", "queued"] = "sync"
    send_at: datetime | None = None


class SendFileRequest(BaseModel):
    bot_id: int
    media_type: Literal["document", "video"]
    file_relative_path: str
    destination_id: int | None = None
    destination_alias: str | None = None
    chat_id: str | None = None
    caption: str | None = None
    tag: str | None = None
    parse_mode: str | None = None
    message_thread_id: int | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    send_mode: Literal["sync", "queued"] = "sync"
    send_at: datetime | None = None


class SendPreviewRequest(BaseModel):
    kind: Literal["text", "template", "file"]
    bot_id: int
    text: str | None = None
    tag: str | None = None
    destination_id: int | None = None
    destination_alias: str | None = None
    chat_id: str | None = None
    message_thread_id: int | None = None
    parse_mode: str | None = None
    disable_web_page_preview: bool | None = None
    media_type: Literal["document", "video"] | None = None
    file_relative_path: str | None = None
    caption: str | None = None
    variables: dict[str, Any] = Field(default_factory=dict)


class SendPreviewRead(BaseModel):
    ok: bool = True
    kind: str
    method: str
    bot_id: int
    chat_id: str
    message_thread_id: int | None = None
    destination_id: int | None = None
    tag: str | None = None
    payload: dict[str, Any]


class SendPreflightCheckRead(BaseModel):
    name: str
    status: Literal["ok", "warning", "error"]
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class SendPreflightRead(BaseModel):
    ok: bool
    checks: list[SendPreflightCheckRead]
    preview: SendPreviewRead | None = None


class SendHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bot_id: int | None
    destination_id: int | None
    chat_id: str
    message_thread_id: int | None
    tag: str | None
    text: str | None
    media_type: str
    file_relative_path: str | None
    file_size_bytes: int | None
    telegram_message_id: int | None
    status: str
    send_mode: str
    idempotency_key: str | None
    attempt_count: int
    queued_task_id: str | None
    next_retry_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    sent_at: datetime | None
    failed_at: datetime | None


class SendDryRunRead(BaseModel):
    ok: bool = True
    method: str
    bot_id: int
    chat_id: str
    message_thread_id: int | None = None
    destination_id: int | None = None
    payload: dict[str, Any]
