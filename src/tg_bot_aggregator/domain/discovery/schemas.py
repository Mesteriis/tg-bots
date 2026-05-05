from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class BotDiscoverySettingsUpdate(BaseModel):
    is_enabled: bool | None = None


class BotDiscoverySettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bot_id: int
    is_enabled: bool
    last_update_id: int | None
    last_error: str | None
    updated_at: datetime


class BotDiscoveryEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bot_id: int
    update_id: int
    chat_id: str
    kind: str
    old_status: str | None
    new_status: str | None
    raw_update_json: dict[str, Any] | None
    created_at: datetime
