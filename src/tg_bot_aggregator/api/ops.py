from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import get_session
from tg_bot_aggregator.audit import record_audit_event
from tg_bot_aggregator.core.errors import NotFoundError
from tg_bot_aggregator.domain.mcp.catalog import MCP_BOOTSTRAP_ENABLED_TOOL_NAMES
from tg_bot_aggregator.domain.mcp.repository import McpSettingsRepository
from tg_bot_aggregator.domain.ops.repository import (
    OpsActionRunRepository,
    OpsAutomationRuleRepository,
    OpsFactRepository,
    OpsRecommendationRepository,
)
from tg_bot_aggregator.domain.ops.service import (
    McpCoverageService,
    TelegramOpsError,
    TelegramOpsService,
)
from tg_bot_aggregator.schemas import (
    McpCoverageRead,
    OpsActionApplyRead,
    OpsActionPreviewRead,
    OpsActionRunRead,
    OpsFactRead,
    OpsRecommendationRead,
    OpsRuleRead,
    OpsRuleUpdate,
)

router = APIRouter(prefix="/ops", tags=["ops"])


def _service(request: Request, session: AsyncSession) -> TelegramOpsService:
    return TelegramOpsService(
        session,
        action_log_session_factory=request.app.state.session_factory,
    )


def _actor(request: Request) -> str:
    api_token_id = getattr(request.state, "api_token_id", None)
    if api_token_id is not None:
        return f"api_token:{api_token_id}"
    return "local"


async def _publish(request: Request, event_type: str, payload: dict[str, Any]) -> None:
    event_bus = getattr(request.app.state, "event_bus", None)
    if event_bus is not None:
        await event_bus.publish(event_type, payload)


async def _audit(
    session: AsyncSession,
    *,
    request: Request,
    action: str,
    entity_type: str,
    entity_id: int | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await record_audit_event(
        session,
        source="ops",
        action=action,
        status="succeeded",
        request=request,
        api_token_id=getattr(request.state, "api_token_id", None),
        entity_type=entity_type,
        entity_id=entity_id,
        metadata=metadata,
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, TelegramOpsError | ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.post("/scan")
async def scan_ops(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    try:
        result = await _service(request, session).scan(source="rest")
        await _audit(
            session,
            request=request,
            action="ops.scan",
            entity_type="ops_scan",
            metadata=result,
        )
        await session.commit()
    except Exception as exc:
        raise _http_error(exc) from exc
    await _publish(request, "ops.scan.completed", result)
    return result


@router.get("/facts", response_model=list[OpsFactRead])
async def list_facts(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await OpsFactRepository(session).list()


@router.get("/recommendations", response_model=list[OpsRecommendationRead])
async def list_recommendations(
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[object]:
    return await OpsRecommendationRepository(session).list(status=status)


@router.post(
    "/recommendations/{recommendation_id}/preview",
    response_model=OpsActionPreviewRead,
)
async def preview_recommendation(
    recommendation_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        result = await _service(request, session).preview_action(
            recommendation_id,
            source="rest",
            actor=_actor(request),
        )
        await _audit(
            session,
            request=request,
            action="ops.action.previewed",
            entity_type="ops_recommendation",
            entity_id=recommendation_id,
            metadata=result,
        )
        await session.commit()
    except Exception as exc:
        raise _http_error(exc) from exc
    await _publish(request, "ops.action.previewed", result)
    return result


@router.post(
    "/recommendations/{recommendation_id}/apply",
    response_model=OpsActionApplyRead,
)
async def apply_recommendation(
    recommendation_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        result = await _service(request, session).apply_action(
            recommendation_id,
            source="rest",
            actor=_actor(request),
        )
        await _audit(
            session,
            request=request,
            action="ops.action.applied",
            entity_type="ops_recommendation",
            entity_id=recommendation_id,
            metadata=result,
        )
        await session.commit()
    except (NotFoundError, TelegramOpsError, ValueError) as exc:
        raise _http_error(exc) from exc
    await _publish(request, "ops.action.applied", result)
    return result


@router.post("/recommendations/{recommendation_id}/dismiss")
async def dismiss_recommendation(
    recommendation_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        result = await _service(request, session).dismiss_recommendation(
            recommendation_id,
            source="rest",
            actor=_actor(request),
        )
        await _audit(
            session,
            request=request,
            action="ops.recommendation.dismissed",
            entity_type="ops_recommendation",
            entity_id=recommendation_id,
            metadata=result,
        )
        await session.commit()
    except Exception as exc:
        raise _http_error(exc) from exc
    await _publish(request, "ops.recommendation.dismissed", result)
    return result


@router.get("/rules", response_model=list[OpsRuleRead])
async def list_rules(
    session: AsyncSession = Depends(get_session),
) -> list[object]:
    return await OpsAutomationRuleRepository(session).list()


@router.patch("/rules/{rule_id}", response_model=OpsRuleRead)
async def update_rule(
    rule_id: int,
    payload: OpsRuleUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    try:
        rule = await _service(request, session).update_rule(
            rule_id,
            source="rest",
            actor=_actor(request),
            **payload.model_dump(exclude_unset=True),
        )
        await _audit(
            session,
            request=request,
            action="ops.rule.updated",
            entity_type="ops_rule",
            entity_id=rule.id,
            metadata={"rule_id": rule.id},
        )
        await session.commit()
    except Exception as exc:
        raise _http_error(exc) from exc
    await _publish(request, "ops.rule.updated", {"rule_id": rule.id})
    return rule


@router.post("/rules/{rule_id}/run")
async def run_rule(
    rule_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        result = await _service(request, session).run_rule(
            rule_id,
            source="rest",
            actor=_actor(request),
        )
        await _audit(
            session,
            request=request,
            action="ops.rule.ran",
            entity_type="ops_rule",
            entity_id=rule_id,
            metadata=result,
        )
        await session.commit()
    except Exception as exc:
        raise _http_error(exc) from exc
    await _publish(request, "ops.rule.ran", result)
    return result


@router.post("/rules/{rule_id}/pause", response_model=OpsRuleRead)
async def pause_rule(
    rule_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    try:
        rule = await _service(request, session).pause_rule(
            rule_id,
            source="rest",
            actor=_actor(request),
        )
        await _audit(
            session,
            request=request,
            action="ops.rule.paused",
            entity_type="ops_rule",
            entity_id=rule.id,
            metadata={"rule_id": rule.id},
        )
        await session.commit()
    except Exception as exc:
        raise _http_error(exc) from exc
    await _publish(request, "ops.rule.paused", {"rule_id": rule.id})
    return rule


@router.post("/rules/{rule_id}/resume", response_model=OpsRuleRead)
async def resume_rule(
    rule_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> object:
    try:
        rule = await _service(request, session).resume_rule(
            rule_id,
            source="rest",
            actor=_actor(request),
        )
        await _audit(
            session,
            request=request,
            action="ops.rule.resumed",
            entity_type="ops_rule",
            entity_id=rule.id,
            metadata={"rule_id": rule.id},
        )
        await session.commit()
    except Exception as exc:
        raise _http_error(exc) from exc
    await _publish(request, "ops.rule.resumed", {"rule_id": rule.id})
    return rule


@router.get("/action-runs", response_model=list[OpsActionRunRead])
async def list_action_runs(session: AsyncSession = Depends(get_session)) -> list[object]:
    return await OpsActionRunRepository(session).list()


@router.get("/mcp-coverage", response_model=McpCoverageRead)
async def mcp_coverage(session: AsyncSession = Depends(get_session)) -> McpCoverageRead:
    settings = await McpSettingsRepository(session).get()
    enabled_tools = (
        set(settings.enabled_tools_json or [])
        if settings is not None
        else set(MCP_BOOTSTRAP_ENABLED_TOOL_NAMES)
    )
    return McpCoverageRead.model_validate(
        McpCoverageService(enabled_tools).matrix()
    )
