from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TemplateCreate(BaseModel):
    tag: str
    title: str
    text: str
    parse_mode: str | None = None
    disable_web_page_preview: bool = False


class TemplateUpdate(BaseModel):
    title: str | None = None
    text: str | None = None
    parse_mode: str | None = None
    disable_web_page_preview: bool | None = None


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tag: str
    title: str
    text: str
    parse_mode: str | None
    disable_web_page_preview: bool


class TemplateVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template_id: int
    version_number: int
    title: str
    text: str
    parse_mode: str | None
    disable_web_page_preview: bool
    created_at: datetime


class TemplateValidateRequest(BaseModel):
    text: str
    variables: dict[str, Any] = Field(default_factory=dict)


class TemplateValidateRead(BaseModel):
    ok: bool
    variables: list[str]
    missing_variables: list[str]
    rendered_text: str | None = None
    error_message: str | None = None
