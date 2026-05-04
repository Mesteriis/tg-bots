from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tg_bot_aggregator.core.errors import NotFoundError
from tg_bot_aggregator.core.security import redact_secrets
from tg_bot_aggregator.domain.bots.repository import BotRepository
from tg_bot_aggregator.domain.destinations.repository import DestinationRepository
from tg_bot_aggregator.domain.diagnostics.repository import DiagnosticUpdateRepository
from tg_bot_aggregator.domain.discovery.repository import BotDiscoveryEventRepository
from tg_bot_aggregator.domain.mcp.catalog import MCP_TOOL_NAMES
from tg_bot_aggregator.domain.ops.repository import (
    OpsActionRunRepository,
    OpsAutomationRuleRepository,
    OpsFactRepository,
    OpsRecommendationRepository,
)
from tg_bot_aggregator.models import (
    Bot,
    Destination,
    OpsAutomationRule,
    OpsFact,
    OpsRecommendation,
    utc_now,
)

OpsRisk = Literal["low", "medium", "high"]

AUTO_APPLY_ACTIONS: frozenset[str] = frozenset(
    {
        "create_destination_from_seen_chat",
        "update_destination_metadata",
        "record_forum_topic_thread",
    }
)

RISK_RANK: dict[str, int] = {"low": 1, "medium": 2, "high": 3}
ACTIVE_DISCOVERY_STATUSES: frozenset[str] = frozenset({"administrator", "creator", "member"})

DEFAULT_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_key": "create_destination_from_seen_chat",
        "title": "Create destinations from observed chats",
        "mode": "suggest_only",
        "is_enabled": True,
        "is_paused": False,
        "risk_limit": "low",
        "config_json": {},
    },
    {
        "rule_key": "update_destination_metadata",
        "title": "Update destination metadata from observed chats",
        "mode": "suggest_only",
        "is_enabled": True,
        "is_paused": False,
        "risk_limit": "low",
        "config_json": {},
    },
)


class TelegramOpsError(ValueError):
    pass


def normalize_destination_kind(chat_type: str | None, message_thread_id: int | None) -> str:
    if message_thread_id is not None:
        return "forum_topic"
    if chat_type in {"private", "group", "supergroup", "channel"}:
        return chat_type
    return "group"


def build_destination_diff(
    before: Destination | dict[str, Any] | None,
    after: dict[str, Any],
) -> dict[str, Any]:
    before_data = None
    if isinstance(before, Destination):
        before_data = {
            "bot_id": before.bot_id,
            "chat_id": before.chat_id,
            "message_thread_id": before.message_thread_id,
            "kind": before.kind,
            "title": before.title,
            "username": before.username,
            "is_active": before.is_active,
        }
    elif before is not None:
        before_data = dict(before)

    changed = {
        key: {"before": None if before_data is None else before_data.get(key), "after": value}
        for key, value in after.items()
        if before_data is None or before_data.get(key) != value
    }
    return {
        "operation": "create" if before_data is None else "update",
        "before": before_data,
        "after": dict(after),
        "changed": changed,
    }


class TelegramOpsService:
    def __init__(
        self,
        session: AsyncSession,
        action_log_session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session = session
        self.action_log_session_factory = action_log_session_factory
        self.facts = OpsFactRepository(session)
        self.recommendations = OpsRecommendationRepository(session)
        self.rules = OpsAutomationRuleRepository(session)
        self.runs = OpsActionRunRepository(session)
        self.destinations = DestinationRepository(session)
        self.bots = BotRepository(session)

    async def scan(self, source: str = "dashboard") -> dict[str, int]:
        del source
        created_facts = 0
        created_recommendations = 0
        updates = await DiagnosticUpdateRepository(self.session).list(limit=500)
        discovery_events = await BotDiscoveryEventRepository(self.session).list(limit=500)
        await self._ensure_default_rules()

        for update in reversed(updates):
            if update.chat_id is None:
                continue

            fact = await self.facts.upsert_fact(
                fact_type="chat_seen",
                bot_id=None,
                chat_id=update.chat_id,
                message_thread_id=update.message_thread_id,
                source="diagnostic_update",
                title=update.chat_title,
                username=update.chat_username,
                kind=normalize_destination_kind(update.chat_type, update.message_thread_id),
                status="active",
                confidence=90,
                payload_json=redact_secrets(update.raw_update_json or {}),
            )
            created_facts += 1
            recommendation = await self._recommend_destination_from_fact(fact)
            if recommendation is not None:
                created_recommendations += 1

        for event in reversed(discovery_events):
            title, username = self._discovery_chat_metadata(event.raw_update_json, event.chat_id)
            fact = await self.facts.upsert_fact(
                fact_type="chat_seen",
                bot_id=event.bot_id,
                chat_id=event.chat_id,
                message_thread_id=None,
                source="discovery_event",
                title=title,
                username=username,
                kind=event.kind,
                status=(
                    "active"
                    if event.new_status in ACTIVE_DISCOVERY_STATUSES
                    else "inactive"
                ),
                confidence=100,
                payload_json=redact_secrets(event.raw_update_json or {}),
            )
            created_facts += 1
            recommendation = await self._recommend_destination_from_fact(fact)
            if recommendation is not None:
                created_recommendations += 1

        return {
            "facts_created": created_facts,
            "recommendations_created": created_recommendations,
        }

    async def preview_action(
        self,
        recommendation_id: int,
        *,
        source: str,
        actor: str,
    ) -> dict[str, Any]:
        recommendation = await self._get_actionable_recommendation(recommendation_id)
        run = await self.runs.create(
            recommendation_id=recommendation.id,
            rule_id=None,
            action_type="preview",
            source=source,
            actor=actor,
            status="succeeded",
            preview_diff_json=recommendation.diff_json,
            request_payload_json={"recommendation_id": recommendation.id},
            result_json={"status": "previewed"},
            rollback_hint="No data was changed.",
            finished_at=utc_now(),
        )
        await self.recommendations.mark_previewed(recommendation)
        return {
            "recommendation_id": recommendation.id,
            "diff": recommendation.diff_json,
            "run_id": run.id,
        }

    async def apply_action(
        self,
        recommendation_id: int,
        *,
        source: str,
        actor: str,
        auto_apply: bool = False,
        rule_id: int | None = None,
    ) -> dict[str, Any]:
        recommendation = await self._get_actionable_recommendation(recommendation_id)
        if auto_apply:
            if recommendation.recommendation_type not in AUTO_APPLY_ACTIONS:
                raise TelegramOpsError(
                    f"recommendation type {recommendation.recommendation_type!r} is not allowlisted"
                )
            if recommendation.risk != "low":
                raise TelegramOpsError("auto_apply is restricted to low-risk recommendations")
        claimed = await self.recommendations.claim_for_apply(recommendation_id)
        if claimed is None:
            recommendation = await self.recommendations.get(recommendation_id)
            if recommendation is None:
                raise NotFoundError(f"ops recommendation {recommendation_id} not found")
            raise TelegramOpsError(
                f"recommendation {recommendation.id} cannot be applied from {recommendation.status}"
            )
        recommendation = claimed

        recommendation_id = recommendation.id
        preview_diff_json = dict(recommendation.diff_json or {})
        try:
            async with self.session.begin_nested():
                destination = await self._apply_destination_action(recommendation)
        except Exception as exc:
            # SQLite keeps the file write lock until the outer transaction ends; abort this
            # request transaction before durable failure logging in a separate session.
            await self.session.rollback()
            await self._record_failed_apply_run(
                recommendation_id=recommendation_id,
                preview_diff_json=preview_diff_json,
                source=source,
                actor=actor,
                auto_apply=auto_apply,
                rule_id=rule_id,
                error_message=str(exc),
            )
            raise

        run = await self.runs.create(
            recommendation_id=recommendation.id,
            rule_id=rule_id,
            action_type="apply",
            source=source,
            actor=actor,
            status="succeeded",
            preview_diff_json=recommendation.diff_json,
            request_payload_json={
                "recommendation_id": recommendation.id,
                "auto_apply": auto_apply,
            },
            result_json={"destination_id": destination.id, "status": "applied"},
            rollback_hint=f"Review or remove destination {destination.id}.",
            finished_at=utc_now(),
        )
        await self.recommendations.mark_applied(recommendation, destination_id=destination.id)

        return {
            "recommendation_id": recommendation.id,
            "status": "applied",
            "destination_id": destination.id,
            "run_id": run.id,
        }

    async def _record_failed_apply_run(
        self,
        *,
        recommendation_id: int,
        preview_diff_json: dict[str, Any],
        source: str,
        actor: str,
        auto_apply: bool,
        rule_id: int | None,
        error_message: str,
    ) -> None:
        session_factory = self._independent_session_factory()

        async with session_factory() as action_log_session:
            runs = OpsActionRunRepository(action_log_session)
            await runs.create(
                recommendation_id=recommendation_id,
                rule_id=rule_id,
                action_type="apply",
                source=source,
                actor=actor,
                status="failed",
                preview_diff_json=preview_diff_json,
                request_payload_json={
                    "recommendation_id": recommendation_id,
                    "auto_apply": auto_apply,
                },
                result_json={"status": "failed"},
                error_message=error_message,
                rollback_hint="Destination changes were rolled back.",
                finished_at=utc_now(),
            )
            await action_log_session.commit()

    def _discovery_chat_metadata(
        self,
        raw_update: dict[str, Any] | None,
        fallback_chat_id: str,
    ) -> tuple[str | None, str | None]:
        membership = (raw_update or {}).get("my_chat_member")
        if not isinstance(membership, dict):
            return fallback_chat_id, None
        chat = membership.get("chat")
        if not isinstance(chat, dict):
            return fallback_chat_id, None
        title = (
            chat.get("title")
            or chat.get("first_name")
            or chat.get("username")
            or fallback_chat_id
        )
        username = chat.get("username")
        return (
            str(title) if title is not None else None,
            str(username) if username is not None else None,
        )

    def _independent_session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self.action_log_session_factory is not None:
            return self.action_log_session_factory
        bind = self.session.bind
        if bind is None:
            raise TelegramOpsError("cannot create independent action session without a bind")
        return async_sessionmaker(bind, expire_on_commit=False)

    async def dismiss_recommendation(
        self,
        recommendation_id: int,
        *,
        source: str = "dashboard",
        actor: str | None = None,
    ) -> dict[str, Any]:
        recommendation = await self.recommendations.get(recommendation_id)
        if recommendation is None:
            raise NotFoundError(f"ops recommendation {recommendation_id} not found")
        if recommendation.status not in {"open", "previewed"}:
            raise TelegramOpsError(
                "recommendation "
                f"{recommendation.id} cannot be dismissed from {recommendation.status}"
            )
        await self.recommendations.mark_dismissed(recommendation)
        await self.runs.create(
            recommendation_id=recommendation.id,
            rule_id=None,
            action_type="dismiss",
            source=source,
            actor=actor,
            status="succeeded",
            request_payload_json={"recommendation_id": recommendation.id},
            result_json={"recommendation_id": recommendation.id, "status": "dismissed"},
            rollback_hint="Create a new recommendation from a future scan if needed.",
            finished_at=utc_now(),
        )
        return {"recommendation_id": recommendation.id, "status": "dismissed"}

    async def list_rules(self) -> list[OpsAutomationRule]:
        await self._ensure_default_rules()
        return await self.rules.list()

    async def update_rule(
        self,
        rule_id: int,
        *,
        mode: str | None = None,
        is_enabled: bool | None = None,
        is_paused: bool | None = None,
        risk_limit: OpsRisk | None = None,
        config_json: dict[str, Any] | None = None,
        source: str = "dashboard",
        actor: str | None = None,
    ) -> OpsAutomationRule:
        current = await self.rules.get(rule_id)
        if current is None:
            raise NotFoundError(f"ops automation rule {rule_id} not found")
        values: dict[str, Any] = {}
        if mode is not None:
            if mode not in {"suggest_only", "auto_apply"}:
                raise TelegramOpsError(f"invalid ops rule mode {mode!r}")
            values["mode"] = mode
        if risk_limit is not None:
            if risk_limit not in RISK_RANK:
                raise TelegramOpsError(f"invalid ops rule risk limit {risk_limit!r}")
            values["risk_limit"] = risk_limit
        if is_enabled is not None:
            values["is_enabled"] = is_enabled
        if is_paused is not None:
            values["is_paused"] = is_paused
        if config_json is not None:
            values["config_json"] = config_json
        next_mode = values.get("mode", current.mode)
        next_risk_limit = values.get("risk_limit", current.risk_limit)
        if next_mode == "auto_apply" and next_risk_limit != "low":
            raise TelegramOpsError("auto_apply rules require low risk_limit")
        row = await self.rules.update(rule_id, **values)
        await self.runs.create(
            recommendation_id=None,
            rule_id=row.id,
            action_type="update_rule",
            source=source,
            actor=actor,
            status="succeeded",
            request_payload_json={"rule_id": row.id, "updates": values},
            result_json=self._rule_result(row),
            rollback_hint="Restore the previous rule values manually if needed.",
            finished_at=utc_now(),
        )
        return row

    async def pause_rule(
        self,
        rule_id: int,
        *,
        source: str = "dashboard",
        actor: str | None = None,
    ) -> OpsAutomationRule:
        row = await self.rules.update(rule_id, is_paused=True)
        await self.runs.create(
            recommendation_id=None,
            rule_id=row.id,
            action_type="pause_rule",
            source=source,
            actor=actor,
            status="succeeded",
            request_payload_json={"rule_id": row.id},
            result_json=self._rule_result(row),
            rollback_hint="Resume the rule.",
            finished_at=utc_now(),
        )
        return row

    async def resume_rule(
        self,
        rule_id: int,
        *,
        source: str = "dashboard",
        actor: str | None = None,
    ) -> OpsAutomationRule:
        row = await self.rules.update(rule_id, is_paused=False)
        await self.runs.create(
            recommendation_id=None,
            rule_id=row.id,
            action_type="resume_rule",
            source=source,
            actor=actor,
            status="succeeded",
            request_payload_json={"rule_id": row.id},
            result_json=self._rule_result(row),
            rollback_hint="Pause the rule.",
            finished_at=utc_now(),
        )
        return row

    async def run_rule(self, rule_id: int, *, source: str, actor: str) -> dict[str, Any]:
        rule = await self.rules.get(rule_id)
        if rule is None:
            raise NotFoundError(f"ops automation rule {rule_id} not found")
        rule_id_value = rule.id
        rule_mode = rule.mode
        rule_is_enabled = rule.is_enabled
        rule_is_paused = rule.is_paused
        rule_risk_limit = rule.risk_limit
        rule_key = rule.rule_key
        if not rule_is_enabled or rule_is_paused:
            result = {"rule_id": rule_id_value, "applied": 0, "skipped": 1, "failed": 0}
            await self.rules.mark_run(rule, "skipped disabled or paused rule")
            await self._record_rule_run(rule, source=source, actor=actor, result=result)
            return result
        if rule_mode != "auto_apply":
            result = {"rule_id": rule_id_value, "applied": 0, "skipped": 1, "failed": 0}
            await self.rules.mark_run(rule, "skipped suggest_only rule")
            await self._record_rule_run(rule, source=source, actor=actor, result=result)
            return result

        applied = 0
        skipped = 0
        failed = 0
        candidates = await self.recommendations.list(
            status="open",
            recommendation_type=rule_key,
        )
        previewed = await self.recommendations.list(
            status="previewed",
            recommendation_type=rule_key,
        )
        candidate_ids_and_risks = [
            (recommendation.id, recommendation.risk)
            for recommendation in [*candidates, *previewed]
        ]
        for recommendation_id, recommendation_risk in candidate_ids_and_risks:
            if not self._risk_allowed(recommendation_risk, rule_risk_limit):
                skipped += 1
                continue
            if await self._apply_rule_recommendation(
                recommendation_id,
                rule_id=rule_id_value,
                source=source,
                actor=actor,
            ):
                applied += 1
            else:
                failed += 1

        result = {
            "rule_id": rule_id_value,
            "applied": applied,
            "skipped": skipped,
            "failed": failed,
        }
        await self.rules.mark_run(rule, f"applied={applied} skipped={skipped} failed={failed}")
        await self._record_rule_run(rule, source=source, actor=actor, result=result)
        return result

    async def _apply_rule_recommendation(
        self,
        recommendation_id: int,
        *,
        rule_id: int,
        source: str,
        actor: str,
    ) -> bool:
        session_factory = self._independent_session_factory()
        async with session_factory() as apply_session:
            try:
                await TelegramOpsService(
                    apply_session,
                    action_log_session_factory=session_factory,
                ).apply_action(
                    recommendation_id,
                    source=source,
                    actor=actor,
                    auto_apply=True,
                    rule_id=rule_id,
                )
                await apply_session.commit()
            except Exception:
                await apply_session.rollback()
                return False
        return True

    def _rule_result(self, rule: OpsAutomationRule) -> dict[str, Any]:
        return {
            "rule_id": rule.id,
            "rule_key": rule.rule_key,
            "mode": rule.mode,
            "is_enabled": rule.is_enabled,
            "is_paused": rule.is_paused,
            "risk_limit": rule.risk_limit,
        }

    async def _record_rule_run(
        self,
        rule: OpsAutomationRule,
        *,
        source: str,
        actor: str,
        result: dict[str, int],
    ) -> None:
        await self.runs.create(
            recommendation_id=None,
            rule_id=rule.id,
            action_type="run_rule",
            source=source,
            actor=actor,
            status="failed" if result["failed"] else "succeeded",
            request_payload_json={"rule_id": rule.id},
            result_json=result,
            rollback_hint="Review individual apply action runs for per-recommendation details.",
            finished_at=utc_now(),
        )

    async def _recommend_destination_from_fact(
        self,
        fact: OpsFact,
    ) -> OpsRecommendation | None:
        bot_id = fact.bot_id
        if bot_id is None:
            bot = await self._first_active_bot()
            if bot is None:
                return None
            bot_id = bot.id

        after = {
            "bot_id": bot_id,
            "chat_id": fact.chat_id,
            "message_thread_id": fact.message_thread_id,
            "kind": fact.kind,
            "title": fact.title,
            "username": fact.username,
            "is_active": True,
        }
        destination = await self._find_destination(
            bot_id=bot_id,
            chat_id=fact.chat_id,
            message_thread_id=fact.message_thread_id,
        )
        if destination is None:
            return await self._create_recommendation_once(
                recommendation_type="create_destination_from_seen_chat",
                risk="low",
                bot_id=bot_id,
                destination_id=None,
                fact_ids=[fact.id],
                title=f"Create destination {fact.title or fact.chat_id}",
                reason="Chat was observed but no destination exists.",
                diff_json=build_destination_diff(None, after),
                action_payload_json=after,
            )

        diff = build_destination_diff(destination, after)
        changed_metadata = {
            key: value
            for key, value in diff["changed"].items()
            if key in {"title", "username", "kind", "message_thread_id"}
        }
        if not changed_metadata:
            return None

        action_payload = dict(after)
        action_payload["destination_id"] = destination.id
        return await self._create_recommendation_once(
            recommendation_type="update_destination_metadata",
            risk="low",
            bot_id=bot_id,
            destination_id=destination.id,
            fact_ids=[fact.id],
            title=f"Update destination {destination.title or destination.chat_id}",
            reason="Observed chat metadata differs from the configured destination.",
            diff_json={**diff, "changed": changed_metadata},
            action_payload_json=action_payload,
        )

    async def _create_recommendation_once(
        self,
        *,
        recommendation_type: str,
        risk: OpsRisk,
        bot_id: int,
        destination_id: int | None,
        fact_ids: list[int],
        title: str,
        reason: str,
        diff_json: dict[str, Any],
        action_payload_json: dict[str, Any],
    ) -> OpsRecommendation | None:
        existing = await self._find_open_or_previewed_recommendation(
            recommendation_type,
            bot_id=action_payload_json.get("bot_id"),
            chat_id=action_payload_json.get("chat_id"),
            message_thread_id=action_payload_json.get("message_thread_id"),
        )
        if existing is not None:
            existing.risk = risk
            existing.bot_id = bot_id
            existing.destination_id = destination_id
            existing.fact_ids_json = fact_ids
            existing.title = title
            existing.reason = reason
            existing.diff_json = diff_json
            existing.action_payload_json = action_payload_json
            existing.updated_at = utc_now()
            await self.session.flush()
            return None
        return await self.recommendations.create(
            recommendation_type=recommendation_type,
            status="open",
            risk=risk,
            bot_id=bot_id,
            destination_id=destination_id,
            fact_ids_json=fact_ids,
            title=title,
            reason=reason,
            diff_json=diff_json,
            action_payload_json=action_payload_json,
        )

    async def _find_open_or_previewed_recommendation(
        self,
        recommendation_type: str,
        *,
        bot_id: int | None,
        chat_id: str | None,
        message_thread_id: int | None,
    ) -> OpsRecommendation | None:
        return await self.recommendations.find_open(
            recommendation_type,
            bot_id=bot_id,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
        )

    async def _first_active_bot(self) -> Bot | None:
        bots = await self.bots.list()
        return next((bot for bot in bots if bot.is_active), None)

    async def _find_destination(
        self,
        *,
        bot_id: int,
        chat_id: str | None,
        message_thread_id: int | None,
    ) -> Destination | None:
        if chat_id is None:
            return None
        return await self.destinations.get_by_chat(bot_id, chat_id, message_thread_id)

    async def _ensure_default_rules(self) -> None:
        existing_rule_keys = {rule.rule_key for rule in await self.rules.list()}
        for values in DEFAULT_RULES:
            rule_key = values["rule_key"]
            if rule_key in existing_rule_keys:
                continue
            rule_values = {key: value for key, value in values.items() if key != "rule_key"}
            await self.rules.upsert_by_key(rule_key, **rule_values)

    async def _get_actionable_recommendation(self, recommendation_id: int) -> OpsRecommendation:
        recommendation = await self.recommendations.get(recommendation_id)
        if recommendation is None:
            raise NotFoundError(f"ops recommendation {recommendation_id} not found")
        if recommendation.status not in {"open", "previewed"}:
            raise TelegramOpsError(
                f"recommendation {recommendation.id} cannot be applied from {recommendation.status}"
            )
        return recommendation

    async def _apply_destination_action(self, recommendation: OpsRecommendation) -> Destination:
        if recommendation.recommendation_type not in {
            "create_destination_from_seen_chat",
            "update_destination_metadata",
            "record_forum_topic_thread",
        }:
            raise TelegramOpsError(
                f"recommendation type {recommendation.recommendation_type!r} is not supported"
            )

        payload = recommendation.action_payload_json or {}
        bot_id = self._required_int(payload, "bot_id")
        chat_id = self._required_str(payload, "chat_id")
        message_thread_id = payload.get("message_thread_id")
        values = {
            "kind": self._required_str(payload, "kind"),
            "title": payload.get("title"),
            "username": payload.get("username"),
            "is_active": bool(payload.get("is_active", True)),
        }
        destination_id = payload.get("destination_id")
        if destination_id is not None:
            return await self.destinations.update(
                int(destination_id),
                bot_id=bot_id,
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                **values,
            )
        return await self.destinations.upsert_by_chat(
            bot_id,
            chat_id,
            message_thread_id,
            **values,
        )

    def _risk_allowed(self, risk: str, risk_limit: str) -> bool:
        return RISK_RANK.get(risk, 99) <= RISK_RANK.get(risk_limit, 0)

    def _required_int(self, payload: dict[str, Any], key: str) -> int:
        value = payload.get(key)
        if value is None:
            raise TelegramOpsError(f"action payload missing {key}")
        return int(value)

    def _required_str(self, payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise TelegramOpsError(f"action payload missing {key}")
        return value


@dataclass(frozen=True)
class McpDomainCoverage:
    domain: str
    rest: bool
    ui: bool
    mcp_read_tools: tuple[str, ...]
    mcp_preview_tools: tuple[str, ...]
    mcp_apply_tools: tuple[str, ...]
    required_scopes: tuple[str, ...]
    risk: str


REQUIRED_MCP_COVERAGE: tuple[McpDomainCoverage, ...] = (
    McpDomainCoverage("health", True, True, ("get_health",), (), (), ("read",), "low"),
    McpDomainCoverage("bots", True, True, ("list_bots",), (), (), ("read",), "low"),
    McpDomainCoverage(
        "destinations",
        True,
        True,
        ("list_destinations",),
        (),
        ("create_destination_from_diagnostic_update", "check_destination"),
        ("read", "send"),
        "medium",
    ),
    McpDomainCoverage(
        "templates",
        True,
        True,
        ("list_message_templates",),
        (),
        ("send_template",),
        ("read", "send"),
        "medium",
    ),
    McpDomainCoverage(
        "send",
        True,
        True,
        (),
        ("dry_run_send",),
        ("send_text", "send_template", "send_file_from_shared_path"),
        ("read", "send"),
        "high",
    ),
    McpDomainCoverage(
        "send_profiles",
        True,
        True,
        ("list_send_profiles",),
        (),
        ("create_send_profile",),
        ("read", "send"),
        "medium",
    ),
    McpDomainCoverage(
        "send_batches",
        True,
        True,
        ("list_send_batches",),
        ("preview_send_batch",),
        ("create_send_batch", "enqueue_send_batch", "cancel_send_batch"),
        ("read", "send"),
        "high",
    ),
    McpDomainCoverage(
        "media",
        True,
        True,
        ("list_media",),
        (),
        (),
        ("read",),
        "low",
    ),
    McpDomainCoverage(
        "history",
        True,
        True,
        ("get_send_history",),
        (),
        (),
        ("read",),
        "low",
    ),
    McpDomainCoverage(
        "reliability",
        True,
        True,
        (
            "get_reliability_summary",
            "get_reliability_graph",
            "list_send_attempts",
            "list_rate_limit_buckets",
        ),
        (),
        ("release_stale_send_locks", "bulk_retry_sends", "bulk_cancel_sends"),
        ("read", "send"),
        "high",
    ),
    McpDomainCoverage(
        "diagnostics",
        True,
        True,
        ("list_diagnostic_updates",),
        (),
        (),
        ("read",),
        "low",
    ),
    McpDomainCoverage(
        "discovery",
        True,
        True,
        ("get_discovery_settings",),
        (),
        ("update_discovery_settings",),
        ("read",),
        "medium",
    ),
    McpDomainCoverage(
        "analytics",
        True,
        True,
        ("get_analytics_summary",),
        (),
        ("refresh_analytics",),
        ("read",),
        "low",
    ),
    McpDomainCoverage(
        "mtproto",
        True,
        True,
        ("list_mtproto_sessions",),
        (),
        ("update_mtproto_session",),
        ("read", "ops_admin"),
        "medium",
    ),
    McpDomainCoverage(
        "operations_backup",
        True,
        True,
        ("list_backup_runs",),
        ("preview_backup",),
        ("run_backup", "restore_backup"),
        ("read", "ops_admin"),
        "high",
    ),
    McpDomainCoverage(
        "audit",
        True,
        True,
        ("list_audit_events",),
        (),
        (),
        ("read",),
        "low",
    ),
    McpDomainCoverage(
        "mcp_settings",
        True,
        True,
        ("get_mcp_connection_info",),
        (),
        ("update_mcp_settings",),
        ("read", "mcp_admin"),
        "high",
    ),
    McpDomainCoverage(
        "telegram_ops",
        True,
        True,
        ("list_ops_facts", "list_ops_recommendations", "list_ops_rules"),
        ("preview_ops_action",),
        (
            "run_ops_scan",
            "apply_ops_action",
            "dismiss_ops_recommendation",
            "update_ops_rule",
            "run_ops_rule",
            "pause_ops_rule",
            "resume_ops_rule",
        ),
        ("read", "ops_admin"),
        "high",
    ),
)


class McpCoverageService:
    def __init__(self, enabled_tools: set[str]) -> None:
        self.enabled_tools = enabled_tools

    def matrix(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        missing_enabled_tools: list[str] = []
        missing_catalog_tools: list[str] = []
        catalog_tools = set(MCP_TOOL_NAMES)
        for coverage in REQUIRED_MCP_COVERAGE:
            tools = (
                list(coverage.mcp_read_tools)
                + list(coverage.mcp_preview_tools)
                + list(coverage.mcp_apply_tools)
            )
            missing_enabled = [
                tool for tool in tools if tool in catalog_tools and tool not in self.enabled_tools
            ]
            missing_catalog = [tool for tool in tools if tool not in catalog_tools]
            missing_enabled_tools.extend(missing_enabled)
            missing_catalog_tools.extend(missing_catalog)
            rows.append(
                {
                    "domain": coverage.domain,
                    "rest": coverage.rest,
                    "ui": coverage.ui,
                    "mcp_read_tools": list(coverage.mcp_read_tools),
                    "mcp_preview_tools": list(coverage.mcp_preview_tools),
                    "mcp_apply_tools": list(coverage.mcp_apply_tools),
                    "required_scopes": list(coverage.required_scopes),
                    "risk": coverage.risk,
                    "enabled": [
                        tool
                        for tool in tools
                        if tool in catalog_tools and tool in self.enabled_tools
                    ],
                    "missing_enabled_tools": missing_enabled,
                    "missing_catalog_tools": missing_catalog,
                }
            )
        return {
            "rows": rows,
            "missing_enabled_tools": sorted(set(missing_enabled_tools)),
            "missing_catalog_tools": sorted(set(missing_catalog_tools)),
        }
