from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.core.errors import NotFoundError
from tg_bot_aggregator.models import (
    OpsActionRun,
    OpsAutomationRule,
    OpsFact,
    OpsRecommendation,
    utc_now,
)


async def _get_or_none(session: AsyncSession, model: type[Any], row_id: int) -> Any | None:
    return await session.get(model, row_id)


async def _list(session: AsyncSession, statement: Select[tuple[Any]]) -> list[Any]:
    return list((await session.execute(statement)).scalars().all())


def _optional_equals(column: Any, value: Any) -> Any:
    return column.is_(None) if value is None else column == value


def _ops_fact_identity_key(values: dict[str, Any]) -> str:
    identity = [
        values["fact_type"],
        values.get("bot_id"),
        values.get("chat_id"),
        values.get("message_thread_id"),
        values["source"],
    ]
    payload = json.dumps(identity, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class OpsFactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_fact(self, **values: Any) -> OpsFact:
        values["identity_key"] = _ops_fact_identity_key(values)
        statement = select(OpsFact).where(OpsFact.identity_key == values["identity_key"])
        row = (await self.session.execute(statement)).scalar_one_or_none()
        if row is None:
            row = OpsFact(**values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.observed_at = utc_now()
        await self.session.flush()
        return row

    async def list(self, limit: int = 200) -> list[OpsFact]:
        statement = select(OpsFact).order_by(OpsFact.id.desc()).limit(limit)
        return await _list(self.session, statement)

    async def get(self, fact_id: int) -> OpsFact | None:
        return await _get_or_none(self.session, OpsFact, fact_id)

class OpsRecommendationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> OpsRecommendation:
        row = OpsRecommendation(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(
        self,
        status: str | None = None,
        recommendation_type: str | None = None,
        limit: int = 200,
    ) -> list[OpsRecommendation]:
        statement = select(OpsRecommendation).order_by(OpsRecommendation.id.desc()).limit(limit)
        if status is not None:
            statement = statement.where(OpsRecommendation.status == status)
        if recommendation_type is not None:
            statement = statement.where(
                OpsRecommendation.recommendation_type == recommendation_type
            )
        return await _list(self.session, statement)

    async def get(self, recommendation_id: int) -> OpsRecommendation | None:
        return await _get_or_none(self.session, OpsRecommendation, recommendation_id)

    async def claim_for_apply(self, recommendation_id: int) -> OpsRecommendation | None:
        result = await self.session.execute(
            update(OpsRecommendation)
            .where(
                OpsRecommendation.id == recommendation_id,
                OpsRecommendation.status.in_(("open", "previewed")),
            )
            .values(status="applying", updated_at=utc_now())
        )
        if result.rowcount != 1:
            return None
        return await self.get(recommendation_id)

    async def find_open(
        self,
        recommendation_type: str,
        bot_id: int | None,
        chat_id: str | None,
        message_thread_id: int | None,
    ) -> OpsRecommendation | None:
        statement = (
            select(OpsRecommendation)
            .where(
                OpsRecommendation.recommendation_type == recommendation_type,
                OpsRecommendation.status.in_(("open", "previewed")),
            )
            .order_by(OpsRecommendation.id.desc())
        )
        rows = await _list(self.session, statement)
        for row in rows:
            payload = row.action_payload_json or {}
            if (
                payload.get("bot_id") == bot_id
                and payload.get("chat_id") == chat_id
                and payload.get("message_thread_id") == message_thread_id
            ):
                return row
        return None

    async def mark_previewed(self, row: OpsRecommendation) -> OpsRecommendation:
        row.status = "previewed"
        row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def mark_applied(
        self,
        row: OpsRecommendation,
        destination_id: int | None = None,
    ) -> OpsRecommendation:
        row.status = "applied"
        row.destination_id = destination_id if destination_id is not None else row.destination_id
        row.applied_at = utc_now()
        row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def mark_dismissed(self, row: OpsRecommendation) -> OpsRecommendation:
        row.status = "dismissed"
        row.dismissed_at = utc_now()
        row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def mark_stale(self, row: OpsRecommendation) -> OpsRecommendation:
        row.status = "stale"
        row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def mark_failed(self, row: OpsRecommendation, message: str) -> OpsRecommendation:
        row.status = "failed"
        row.reason = f"{row.reason}\nFailure: {message}"
        row.updated_at = utc_now()
        await self.session.flush()
        return row

class OpsAutomationRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_by_key(self, rule_key: str, **values: Any) -> OpsAutomationRule:
        statement = select(OpsAutomationRule).where(OpsAutomationRule.rule_key == rule_key)
        row = (await self.session.execute(statement)).scalar_one_or_none()
        if row is None:
            row = OpsAutomationRule(rule_key=rule_key, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def list(self) -> list[OpsAutomationRule]:
        return await _list(self.session, select(OpsAutomationRule).order_by(OpsAutomationRule.id))

    async def get(self, rule_id: int) -> OpsAutomationRule | None:
        return await _get_or_none(self.session, OpsAutomationRule, rule_id)

    async def update(self, rule_id: int, **values: Any) -> OpsAutomationRule:
        row = await self.get(rule_id)
        if row is None:
            raise NotFoundError(f"ops automation rule {rule_id} not found")
        for key, value in values.items():
            setattr(row, key, value)
        row.updated_at = utc_now()
        await self.session.flush()
        return row

    async def mark_run(self, row: OpsAutomationRule, result: str) -> OpsAutomationRule:
        row.last_run_at = utc_now()
        row.last_result = result
        row.updated_at = utc_now()
        await self.session.flush()
        return row

class OpsActionRunRepository:
    _TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: Any) -> OpsActionRun:
        row = OpsActionRun(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def list(self, limit: int = 200) -> list[OpsActionRun]:
        statement = select(OpsActionRun).order_by(OpsActionRun.id.desc()).limit(limit)
        return await _list(self.session, statement)

    async def get(self, run_id: int) -> OpsActionRun | None:
        return await _get_or_none(self.session, OpsActionRun, run_id)

    async def update(self, run_id: int, **values: Any) -> OpsActionRun:
        row = await self.get(run_id)
        if row is None:
            raise NotFoundError(f"ops action run {run_id} not found")
        if row.status in self._TERMINAL_STATUSES:
            raise ValueError(f"ops action run {row.id} is already terminal")
        for key, value in values.items():
            setattr(row, key, value)
        await self.session.flush()
        return row

    async def mark_finished(
        self,
        row: OpsActionRun,
        *,
        status: str,
        result_json: dict[str, Any] | None = None,
        error_message: str | None = None,
        rollback_hint: str | None = None,
    ) -> OpsActionRun:
        if row.status in self._TERMINAL_STATUSES:
            raise ValueError(f"ops action run {row.id} is already terminal")
        row.status = status
        row.result_json = result_json
        row.error_message = error_message
        if rollback_hint is not None:
            row.rollback_hint = rollback_hint
        row.finished_at = utc_now()
        await self.session.flush()
        return row

    async def mark_succeeded(
        self,
        row: OpsActionRun,
        *,
        result_json: dict[str, Any] | None = None,
        rollback_hint: str | None = None,
    ) -> OpsActionRun:
        return await self.mark_finished(
            row,
            status="succeeded",
            result_json=result_json,
            rollback_hint=rollback_hint,
        )

    async def mark_failed(
        self,
        row: OpsActionRun,
        *,
        error_message: str,
        result_json: dict[str, Any] | None = None,
        rollback_hint: str | None = None,
    ) -> OpsActionRun:
        return await self.mark_finished(
            row,
            status="failed",
            result_json=result_json,
            error_message=error_message,
            rollback_hint=rollback_hint,
        )

__all__ = [
    "OpsFactRepository",
    "OpsRecommendationRepository",
    "OpsAutomationRuleRepository",
    "OpsActionRunRepository",
]
