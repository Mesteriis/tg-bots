from fastapi import APIRouter

from tg_bot_aggregator.api.router import api_router


def test_api_router_is_fastapi_router() -> None:
    assert isinstance(api_router, APIRouter)


def test_api_router_contains_v1_paths() -> None:
    paths = {route.path for route in api_router.routes}

    assert "/api/v1/health" in paths
    assert "/api/v1/bots" in paths
    assert "/api/v1/destinations" in paths
    assert "/api/v1/send/text" in paths
    assert "/api/v1/mcp/settings" in paths
    assert "/bot{token}/sendMessage" in paths
