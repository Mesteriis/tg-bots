from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DiagnosticBotSettingsUpdate(BaseModel):
    bot_id: int | None = None
    is_enabled: bool | None = None


class DiagnosticBotSettingsRead(BaseModel):
    bot_id: int | None
    bot_name: str | None
    bot_username: str | None
    is_enabled: bool
    last_update_id: int | None
    last_error: str | None
    updated_at: datetime | None


class DiagnosticUpdateCreate(BaseModel):
    update_id: int
    update_kind: str = "message"
    chat_id: str | None = None
    chat_type: str | None = None
    chat_title: str | None = None
    chat_username: str | None = None
    message_id: int | None = None
    message_thread_id: int | None = None
    is_topic_message: bool | None = None
    sender_id: int | None = None
    sender_username: str | None = None
    text_preview: str | None = None
    raw_update: dict[str, Any] | None = None


class DiagnosticDestinationCreate(BaseModel):
    bot_id: int
    alias: str | None = None


class DiagnosticUpdateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    update_id: int
    update_kind: str
    chat_id: str | None
    chat_type: str | None
    chat_title: str | None
    chat_username: str | None
    message_id: int | None
    message_thread_id: int | None
    is_topic_message: bool | None
    sender_id: int | None
    sender_username: str | None
    text_preview: str | None
    raw_update_json: dict[str, Any] | None
    created_at: datetime
