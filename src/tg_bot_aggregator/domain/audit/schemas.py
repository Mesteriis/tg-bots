from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    source: str
    action: str
    status: str
    api_token_id: int | None
    host: str | None
    path: str | None
    method: str | None
    entity_type: str | None
    entity_id: str | None
    message: str | None
    metadata_json: dict[str, Any] | None
