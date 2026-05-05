from fastapi import APIRouter

from tg_bot_aggregator.api.v1 import (
    analytics,
    audit,
    auth,
    backups,
    bots,
    destinations,
    diagnostics,
    discovery,
    events,
    health,
    mcp,
    media,
    mtproto,
    operations,
    ops,
    reliability,
    send_batches,
    send_profiles,
    sending,
    telegram_compat,
    templates,
)


def create_api_router(api_v1_prefix: str = "/api/v1") -> APIRouter:
    v1_router = APIRouter(prefix=api_v1_prefix)
    v1_router.include_router(health.router)
    v1_router.include_router(audit.router)
    v1_router.include_router(auth.router)
    v1_router.include_router(bots.router)
    v1_router.include_router(destinations.router)
    v1_router.include_router(diagnostics.router)
    v1_router.include_router(discovery.router)
    v1_router.include_router(media.router)
    v1_router.include_router(ops.router)
    v1_router.include_router(operations.router)
    v1_router.include_router(backups.router)
    v1_router.include_router(reliability.router)
    v1_router.include_router(templates.router)
    v1_router.include_router(sending.router)
    v1_router.include_router(send_batches.router)
    v1_router.include_router(send_profiles.router)
    v1_router.include_router(mtproto.router)
    v1_router.include_router(mcp.router)
    v1_router.include_router(analytics.router)
    v1_router.include_router(events.router)

    root_router = APIRouter()
    root_router.include_router(v1_router)
    root_router.include_router(telegram_compat.router)
    return root_router


api_router = create_api_router()

__all__ = ["api_router", "create_api_router"]
