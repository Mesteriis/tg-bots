from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import get_session
from tg_bot_aggregator.domain.mcp.catalog import MCP_TOOL_DEFINITIONS, MCP_TOOL_NAMES
from tg_bot_aggregator.domain.mcp.repository import McpSettingsRepository
from tg_bot_aggregator.models import McpSettings
from tg_bot_aggregator.schemas import (
    McpConnectionInfoRead,
    McpSettingsRead,
    McpSettingsUpdate,
    McpToolRead,
    McpTransportInfo,
)

router = APIRouter(prefix="/mcp", tags=["mcp-settings"])


def _read_model(settings: McpSettings, request: Request) -> McpSettingsRead:
    enabled_names = set(settings.enabled_tools_json or [])
    tools = [
        McpToolRead(
            name=definition.name,
            title=definition.title,
            category=definition.category,
            risk=definition.risk,
            enabled=definition.name in enabled_names,
        )
        for definition in MCP_TOOL_DEFINITIONS
    ]
    transports = [
        {
            "name": "streamable_http",
            "path": request.app.state.settings.mcp_v1_prefix,
            "enabled": True,
        },
        {
            "name": "legacy_sse",
            "path": f"{request.app.state.settings.mcp_v1_prefix}/sse",
            "enabled": settings.allow_legacy_sse,
        },
        {
            "name": "legacy_messages",
            "path": f"{request.app.state.settings.mcp_v1_prefix}/messages",
            "enabled": settings.allow_legacy_sse,
        },
    ]
    return McpSettingsRead(
        is_enabled=settings.is_enabled,
        allow_legacy_sse=settings.allow_legacy_sse,
        protected_hosts=request.app.state.settings.protected_api_hosts,
        transports=transports,
        tools=tools,
        tools_by_name={tool.name: tool for tool in tools},
    )


@router.get("/settings", response_model=McpSettingsRead)
async def get_mcp_settings(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> McpSettingsRead:
    settings = await McpSettingsRepository(session).get_or_create()
    await session.commit()
    return _read_model(settings, request)


@router.get("/connection-info", response_model=McpConnectionInfoRead)
async def get_mcp_connection_info(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> McpConnectionInfoRead:
    settings = request.app.state.settings
    mcp_settings = await McpSettingsRepository(session).get_or_create()
    await session.commit()
    first_protected_host = settings.protected_api_hosts[0] if settings.protected_api_hosts else ""
    return McpConnectionInfoRead(
        streamable_http=McpTransportInfo(
            name="streamable_http",
            path=f"{settings.mcp_v1_prefix}/",
            enabled=mcp_settings.is_enabled,
        ),
        legacy_sse=McpTransportInfo(
            name="legacy_sse",
            path=f"{settings.mcp_v1_prefix}/sse",
            enabled=mcp_settings.is_enabled and mcp_settings.allow_legacy_sse,
        ),
        legacy_messages=McpTransportInfo(
            name="legacy_messages",
            path=f"{settings.mcp_v1_prefix}/messages/",
            enabled=mcp_settings.is_enabled and mcp_settings.allow_legacy_sse,
        ),
        protected_hosts=settings.protected_api_hosts,
        required_headers=["X-API-Token"],
        enabled_tools=list(mcp_settings.enabled_tools_json or []),
        local_examples={
            "streamable_http": f"http://127.0.0.1:{settings.app_port}{settings.mcp_v1_prefix}/",
            "legacy_sse": f"http://127.0.0.1:{settings.app_port}{settings.mcp_v1_prefix}/sse",
        },
        protected_host_examples={
            "streamable_http": f"https://{first_protected_host}{settings.mcp_v1_prefix}/"
            if first_protected_host
            else "",
            "header": "X-API-Token: <token>",
        },
    )


@router.patch("/settings", response_model=McpSettingsRead)
async def update_mcp_settings(
    payload: McpSettingsUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> McpSettingsRead:
    values = payload.model_dump(exclude_unset=True)
    if "enabled_tools" in values:
        unknown = sorted(set(values["enabled_tools"]) - set(MCP_TOOL_NAMES))
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown MCP tools: {', '.join(unknown)}")
        values["enabled_tools_json"] = values.pop("enabled_tools")
    settings = await McpSettingsRepository(session).upsert(**values)
    await session.commit()
    return _read_model(settings, request)
