from anyio import to_thread
from fastapi import APIRouter, HTTPException, Request

from tg_bot_aggregator.media_browser import MediaBrowser, MediaBrowserError
from tg_bot_aggregator.schemas import MediaListingRead

router = APIRouter(prefix="/media", tags=["media"])


async def _list_media(request: Request, path: str) -> object:
    settings = request.app.state.settings
    browser = MediaBrowser(
        settings.shared_media_root,
        require_mount=settings.shared_media_require_mount,
    )
    try:
        return await to_thread.run_sync(browser.list_directory, path)
    except MediaBrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=MediaListingRead)
async def list_media(request: Request, path: str = "") -> object:
    return await _list_media(request, path)


@router.get("/tree", response_model=MediaListingRead)
async def list_media_tree(request: Request, path: str = "") -> object:
    return await _list_media(request, path)
