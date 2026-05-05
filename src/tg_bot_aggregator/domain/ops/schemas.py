from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class OpsFactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fact_type: str
    bot_id: int | None
    chat_id: str | None
    message_thread_id: int | None
    source: str
    title: str | None
    username: str | None
    kind: str | None
    status: str
    confidence: int
    observed_at: datetime
    expires_at: datetime | None
    payload_json: dict[str, Any] | None


class OpsRecommendationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recommendation_type: str
    status: str
    risk: str
    bot_id: int | None
    destination_id: int | None
    fact_ids_json: list[int]
    title: str
    reason: str
    diff_json: dict[str, Any]
    action_payload_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    applied_at: datetime | None
    dismissed_at: datetime | None


class OpsActionPreviewRead(BaseModel):
    recommendation_id: int
    diff: dict[str, Any]
    run_id: int


class OpsActionApplyRead(BaseModel):
    recommendation_id: int
    status: str
    destination_id: int | None = None
    run_id: int | None = None


class OpsRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_key: str
    title: str
    mode: str
    is_enabled: bool
    is_paused: bool
    risk_limit: str
    config_json: dict[str, Any]
    last_run_at: datetime | None
    last_result: str | None
    created_at: datetime
    updated_at: datetime


class OpsRuleUpdate(BaseModel):
    mode: Literal["suggest_only", "auto_apply"] | None = None
    is_enabled: bool | None = None
    is_paused: bool | None = None
    risk_limit: Literal["low", "medium", "high"] | None = None
    config_json: dict[str, Any] | None = None


class OpsActionRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recommendation_id: int | None
    rule_id: int | None
    action_type: str
    source: str
    actor: str | None
    status: str
    preview_diff_json: dict[str, Any] | None
    request_payload_json: dict[str, Any] | None
    result_json: dict[str, Any] | None
    error_message: str | None
    rollback_hint: str | None
    created_at: datetime
    finished_at: datetime | None
