from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DestinationCreate(BaseModel):
    bot_id: int
    kind: Literal["private", "group", "supergroup", "channel", "forum_topic"]
    chat_id: str
    message_thread_id: int | None = None
    alias: str | None = None
    title: str | None = None
    username: str | None = None
    is_active: bool = True


class DestinationUpdate(BaseModel):
    kind: Literal["private", "group", "supergroup", "channel", "forum_topic"] | None = None
    chat_id: str | None = None
    message_thread_id: int | None = None
    alias: str | None = None
    title: str | None = None
    username: str | None = None
    is_active: bool | None = None


class DestinationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bot_id: int
    kind: str
    chat_id: str
    message_thread_id: int | None
    alias: str | None
    title: str | None
    username: str | None
    is_active: bool


class DestinationCheckRead(BaseModel):
    destination_id: int
    ok: bool
    chat: dict[str, Any] | None = None
    member_count: int | None = None
    warnings: list[str] = Field(default_factory=list)


class DestinationHealthRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    destination_id: int
    status: str
    last_error: str | None
    last_member_count: int | None
    checked_at: datetime
    raw_chat_json: dict[str, Any] | None
