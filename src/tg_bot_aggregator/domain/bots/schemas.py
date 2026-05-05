from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BotCreate(BaseModel):
    name: str | None = None
    token: str
    description: str | None = None
    is_active: bool = True


class BotUpdate(BaseModel):
    name: str | None = None
    token: str | None = None
    description: str | None = None
    is_active: bool | None = None


class BotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    username: str | None
    telegram_bot_id: int | None
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None
