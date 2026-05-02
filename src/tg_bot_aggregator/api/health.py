from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "api_version": "v1",
        "bot_api_base_url": settings.telegram_bot_api_base_url,
        "shared_media_root": settings.shared_media_root,
        "local_bot_api": settings.is_local_bot_api,
    }

