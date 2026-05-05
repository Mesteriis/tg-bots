from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class MediaItemRead(BaseModel):
    name: str
    relative_path: str
    kind: Literal["directory", "file"]
    size_bytes: int | None
    modified_at: datetime
    media_type: str


class MediaListingRead(BaseModel):
    relative_path: str
    items: list[MediaItemRead]
