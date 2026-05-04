# Telegram Workflow Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a workflow layer for read-only media browsing, reusable send profiles, unified preview, batch sends, retry/cancel controls, diagnostics-to-destination, MCP helpers, and dashboard controls.

**Architecture:** Keep the current layered shape: FastAPI routers stay thin, workflow behavior lives in small services, persistence goes through repositories, and actual Telegram sends still go through `SendService`. The new workflow objects are convenience wrappers over existing bots, destinations, templates, send history, Taskiq, and MCP; they do not introduce users, roles, tenants, or CRM behavior.

**Tech Stack:** FastAPI, SQLAlchemy async, SQLite/Alembic, Taskiq Redis, Vue 3 CDN, MCP FastMCP, pytest, ruff.

---

## File Structure

- Create `src/tg_bot_aggregator/media_browser.py`: read-only shared media listing and path validation for directory browsing.
- Create `src/tg_bot_aggregator/api/media.py`: `/api/v1/media` and `/api/v1/media/tree`.
- Create `src/tg_bot_aggregator/workflow_service.py`: send profiles, unified preview, batch lifecycle, retry/cancel orchestration.
- Modify `src/tg_bot_aggregator/models.py`: add `SendProfile`, `SendBatch`, `SendBatchItem`, `DiagnosticUpdate`.
- Modify `src/tg_bot_aggregator/schemas.py`: add media, profile, preview, batch, retry/cancel, diagnostic update, and MCP connection schemas.
- Modify `src/tg_bot_aggregator/repositories.py`: add repositories for profiles, batches, batch items, diagnostic updates, plus retry/cancel state helpers.
- Create `src/tg_bot_aggregator/api/send_profiles.py`: profile CRUD.
- Create `src/tg_bot_aggregator/api/send_batches.py`: batch CRUD, preview, enqueue, cancel.
- Modify `src/tg_bot_aggregator/api/send.py`: add unified preview and send-history retry/cancel endpoints.
- Modify `src/tg_bot_aggregator/api/diagnostics.py`: list diagnostic updates and create destination from update.
- Modify `src/tg_bot_aggregator/diagnostics/formatter.py`: extract compact diagnostic update metadata.
- Modify `src/tg_bot_aggregator/diagnostics/bot.py`: persist diagnostic update metadata while replying.
- Modify `src/tg_bot_aggregator/tasks.py`: add batch enqueue/process task entry points.
- Modify `src/tg_bot_aggregator/mcp_catalog.py`: add workflow MCP tool definitions.
- Modify `src/tg_bot_aggregator/mcp_server.py`: expose media/profile/batch/diagnostic/MCP-helper tools.
- Modify `src/tg_bot_aggregator/main.py`: include new routers and `/favicon.ico`.
- Modify `src/tg_bot_aggregator/static/index.html`: add dashboard workflow UI.
- Create `alembic/versions/0005_workflow_layer.py`: persistence migration.
- Create or modify tests under `tests/` for each slice.

---

### Task 1: Media Browser Domain And API

**Files:**
- Create: `src/tg_bot_aggregator/media_browser.py`
- Create: `src/tg_bot_aggregator/api/media.py`
- Modify: `src/tg_bot_aggregator/main.py`
- Modify: `src/tg_bot_aggregator/schemas.py`
- Test: `tests/test_media_browser.py`
- Test: `tests/test_api_basic.py`

- [x] **Step 1: Write failing media browser unit tests**

Add to `tests/test_media_browser.py`:

```python
from pathlib import Path

import pytest

from tg_bot_aggregator.media_browser import MediaBrowser, MediaBrowserError


def test_media_browser_lists_direct_children_without_host_paths(tmp_path: Path) -> None:
    (tmp_path / "clips").mkdir()
    (tmp_path / "clips" / "demo.mp4").write_bytes(b"video")
    (tmp_path / "readme.txt").write_text("notes")
    browser = MediaBrowser(tmp_path)

    listing = browser.list_directory("")

    assert listing.relative_path == ""
    assert [item.name for item in listing.items] == ["clips", "readme.txt"]
    assert listing.items[0].kind == "directory"
    assert listing.items[1].kind == "file"
    assert listing.items[1].media_type == "document"
    assert str(tmp_path) not in listing.items[1].relative_path


def test_media_browser_rejects_absolute_and_traversal_paths(tmp_path: Path) -> None:
    browser = MediaBrowser(tmp_path)

    with pytest.raises(MediaBrowserError, match="relative"):
        browser.list_directory(str(tmp_path))

    with pytest.raises(MediaBrowserError, match="traversal"):
        browser.list_directory("../outside")
```

- [x] **Step 2: Run media browser tests and verify RED**

Run:

```bash
pytest tests/test_media_browser.py -q
```

Expected: fail because `tg_bot_aggregator.media_browser` does not exist.

- [x] **Step 3: Implement media browser**

Create `src/tg_bot_aggregator/media_browser.py` with:

```python
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class MediaBrowserError(ValueError):
    pass


@dataclass(frozen=True)
class MediaItem:
    name: str
    relative_path: str
    kind: str
    size_bytes: int | None
    modified_at: datetime
    media_type: str


@dataclass(frozen=True)
class MediaListing:
    relative_path: str
    items: list[MediaItem]


VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
DOCUMENT_SUFFIXES = {".pdf", ".txt", ".zip", ".rar", ".7z", ".doc", ".docx", ".xls", ".xlsx"}


class MediaBrowser:
    def __init__(self, shared_root: str | Path) -> None:
        self.root = Path(shared_root).resolve()

    def _resolve_directory(self, relative_path: str | None) -> tuple[str, Path]:
        value = (relative_path or "").strip()
        candidate_input = Path(value)
        if candidate_input.is_absolute():
            raise MediaBrowserError("media path must be relative to shared media root")
        if ".." in candidate_input.parts:
            raise MediaBrowserError("media path cannot contain parent directory traversal")
        candidate = (self.root / candidate_input).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise MediaBrowserError("media path escapes shared media root") from exc
        if not candidate.exists():
            raise MediaBrowserError("media directory does not exist")
        if not candidate.is_dir():
            raise MediaBrowserError("media path must point to a directory")
        return "" if value == "." else value, candidate

    def list_directory(self, relative_path: str | None = "") -> MediaListing:
        normalized, directory = self._resolve_directory(relative_path)
        items = [self._item(path) for path in sorted(directory.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))]
        return MediaListing(relative_path=normalized, items=items)

    def _item(self, path: Path) -> MediaItem:
        stat = path.stat()
        relative_path = path.relative_to(self.root).as_posix()
        kind = "directory" if path.is_dir() else "file"
        return MediaItem(
            name=path.name,
            relative_path=relative_path,
            kind=kind,
            size_bytes=None if kind == "directory" else stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            media_type="directory" if kind == "directory" else self._media_type(path),
        )

    def _media_type(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in VIDEO_SUFFIXES:
            return "video"
        if suffix in DOCUMENT_SUFFIXES:
            return "document"
        return "unknown"
```

- [x] **Step 4: Add media schemas**

Add to `src/tg_bot_aggregator/schemas.py`:

```python
class MediaItemRead(BaseModel):
    name: str
    relative_path: str
    kind: Literal["directory", "file"]
    size_bytes: int | None
    modified_at: datetime
    media_type: str


class MediaListingRead(BaseModel):
    relative_path: str
    items: list[MediaItemRead]
```

- [x] **Step 5: Add API tests**

Add to `tests/test_api_basic.py`:

```python
async def test_media_listing_is_read_only_and_relative(tmp_path: Path) -> None:
    (tmp_path / "outbox").mkdir()
    (tmp_path / "outbox" / "release.mp4").write_bytes(b"video")
    client, _ = await _client(
        settings=Settings(
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            SHARED_MEDIA_ROOT=str(tmp_path),
        )
    )
    async with client:
        response = await client.get("/api/v1/media", params={"path": "outbox"})
        traversal = await client.get("/api/v1/media", params={"path": "../"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["relative_path"] == "outbox"
    assert payload["items"][0]["relative_path"] == "outbox/release.mp4"
    assert payload["items"][0]["media_type"] == "video"
    assert str(tmp_path) not in payload["items"][0]["relative_path"]
    assert traversal.status_code == 400
```

If `_client` does not accept `settings`, update its signature to accept a `Settings | None` and pass it to `create_app`.

- [x] **Step 6: Implement media API and include router**

Create `src/tg_bot_aggregator/api/media.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Request

from tg_bot_aggregator.api.dependencies import require_scope
from tg_bot_aggregator.media_browser import MediaBrowser, MediaBrowserError
from tg_bot_aggregator.schemas import MediaListingRead

router = APIRouter(prefix="/media", tags=["media"])


@router.get("", response_model=MediaListingRead)
async def list_media(
    request: Request,
    path: str = "",
    _: object = Depends(require_scope("read")),
) -> object:
    settings = request.app.state.settings
    try:
        return MediaBrowser(settings.shared_media_root).list_directory(path)
    except MediaBrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tree", response_model=MediaListingRead)
async def list_media_tree(
    request: Request,
    path: str = "",
    _: object = Depends(require_scope("read")),
) -> object:
    settings = request.app.state.settings
    try:
        return MediaBrowser(settings.shared_media_root).list_directory(path)
    except MediaBrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

Modify `src/tg_bot_aggregator/main.py`:

```python
from tg_bot_aggregator.api import media

app.include_router(media.router, prefix=prefix)
```

- [x] **Step 7: Run tests**

Run:

```bash
pytest tests/test_media_browser.py tests/test_api_basic.py -q
```

Expected: pass.

---

### Task 2: Favicon And MCP Connection Helper

**Files:**
- Modify: `src/tg_bot_aggregator/main.py`
- Modify: `src/tg_bot_aggregator/api/mcp_settings.py`
- Modify: `src/tg_bot_aggregator/mcp_catalog.py`
- Modify: `src/tg_bot_aggregator/mcp_server.py`
- Modify: `src/tg_bot_aggregator/schemas.py`
- Test: `tests/test_api_basic.py`
- Test: `tests/test_mcp_server.py`
- Test: `tests/test_static_ui.py`

- [x] **Step 1: Write failing API tests**

Add to `tests/test_api_basic.py`:

```python
async def test_favicon_and_mcp_connection_info_are_available() -> None:
    client, _ = await _client()
    async with client:
        favicon = await client.get("/favicon.ico")
        info = await client.get("/api/v1/mcp/connection-info")

    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/")
    payload = info.json()
    assert payload["streamable_http"]["path"] == "/mcp/v1/"
    assert payload["legacy_sse"]["path"] == "/mcp/v1/sse"
    assert "X-API-Token" in payload["required_headers"]
    assert "tg.sh-inc.ru" in payload["protected_hosts"]
```

- [x] **Step 2: Run test and verify RED**

Run:

```bash
pytest tests/test_api_basic.py::test_favicon_and_mcp_connection_info_are_available -q
```

Expected: fail with 404 for favicon or connection-info.

- [x] **Step 3: Add MCP connection schemas**

Add to `src/tg_bot_aggregator/schemas.py`:

```python
class McpTransportInfo(BaseModel):
    name: str
    path: str
    enabled: bool


class McpConnectionInfoRead(BaseModel):
    streamable_http: McpTransportInfo
    legacy_sse: McpTransportInfo
    legacy_messages: McpTransportInfo
    protected_hosts: list[str]
    required_headers: list[str]
    enabled_tools: list[str]
    local_examples: dict[str, str]
    protected_host_examples: dict[str, str]
```

- [x] **Step 4: Implement connection-info endpoint**

In `src/tg_bot_aggregator/api/mcp_settings.py`, add:

```python
@router.get("/connection-info", response_model=McpConnectionInfoRead)
async def get_mcp_connection_info(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> McpConnectionInfoRead:
    settings = request.app.state.settings
    row = await McpSettingsRepository(session).get_or_create()
    await session.commit()
    enabled_tools = list(row.enabled_tools_json or [])
    return McpConnectionInfoRead(
        streamable_http=McpTransportInfo(name="streamable_http", path=f"{settings.mcp_v1_prefix}/", enabled=row.is_enabled),
        legacy_sse=McpTransportInfo(name="legacy_sse", path=f"{settings.mcp_v1_prefix}/sse", enabled=row.is_enabled and row.allow_legacy_sse),
        legacy_messages=McpTransportInfo(name="legacy_messages", path=f"{settings.mcp_v1_prefix}/messages/", enabled=row.is_enabled and row.allow_legacy_sse),
        protected_hosts=settings.protected_api_hosts,
        required_headers=["X-API-Token"],
        enabled_tools=enabled_tools,
        local_examples={"streamable_http": f"http://127.0.0.1:{settings.app_port}{settings.mcp_v1_prefix}/"},
        protected_host_examples={"streamable_http": f"https://{settings.protected_api_hosts[0]}{settings.mcp_v1_prefix}/"},
    )
```

Import `Request`, `McpConnectionInfoRead`, and `McpTransportInfo`.

- [x] **Step 5: Add favicon route**

In `src/tg_bot_aggregator/main.py`, add:

```python
from fastapi.responses import Response

FAVICON_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#282c34"/><path d="M14 31 50 16 42 50 31 39 24 46 25 35z" fill="#61afef"/></svg>'


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(FAVICON_SVG, media_type="image/svg+xml")
```

- [x] **Step 6: Add MCP tool**

Add `McpToolDefinition("get_mcp_connection_info", "Get MCP connection info", "read", "read")` to `src/tg_bot_aggregator/mcp_catalog.py`.

Add tool to `src/tg_bot_aggregator/mcp_server.py`:

```python
@mcp.tool()
async def get_mcp_connection_info() -> dict[str, Any]:
    await ensure_mcp_tool_enabled(get_session_factory(), "get_mcp_connection_info")
    async with get_session_factory()() as session:
        row = await McpSettingsRepository(session).get_or_create()
        await session.commit()
        return {
            "streamable_http": {"path": f"{settings.mcp_v1_prefix}/", "enabled": row.is_enabled},
            "legacy_sse": {"path": f"{settings.mcp_v1_prefix}/sse", "enabled": row.is_enabled and row.allow_legacy_sse},
            "legacy_messages": {"path": f"{settings.mcp_v1_prefix}/messages/", "enabled": row.is_enabled and row.allow_legacy_sse},
            "protected_hosts": settings.protected_api_hosts,
            "required_headers": ["X-API-Token"],
            "enabled_tools": list(row.enabled_tools_json or []),
        }
```

- [x] **Step 7: Add static UI smoke test**

Add to `tests/test_static_ui.py`:

```python
def test_static_ui_exposes_mcp_connection_helper_and_media_browser() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "connection-info" in html
    assert "MCP connection" in html or "Подключение MCP" in html
    assert "mediaItems" in html
    assert "selectMediaFile" in html
```

- [x] **Step 8: Run tests**

Run:

```bash
pytest tests/test_api_basic.py::test_favicon_and_mcp_connection_info_are_available tests/test_mcp_server.py tests/test_static_ui.py -q
```

Expected: pass after UI is updated.

---

### Task 3: Send Profiles Persistence And API

**Files:**
- Modify: `src/tg_bot_aggregator/models.py`
- Modify: `src/tg_bot_aggregator/schemas.py`
- Modify: `src/tg_bot_aggregator/repositories.py`
- Create: `src/tg_bot_aggregator/api/send_profiles.py`
- Modify: `src/tg_bot_aggregator/main.py`
- Create: `alembic/versions/0005_workflow_layer.py`
- Test: `tests/test_repositories.py`
- Test: `tests/test_api_basic.py`

- [x] Add failing repository test for creating/listing `SendProfile`.
- [x] Add failing API test for profile CRUD.
- [x] Add `SendProfile` model and migration.
- [x] Add `SendProfileRepository`.
- [x] Add Pydantic create/update/read schemas.
- [x] Add REST router and include it.
- [x] Run `pytest tests/test_repositories.py tests/test_api_basic.py -q`.

---

### Task 4: Unified Preview

**Files:**
- Create: `src/tg_bot_aggregator/workflow_service.py`
- Modify: `src/tg_bot_aggregator/api/send.py`
- Modify: `src/tg_bot_aggregator/schemas.py`
- Test: `tests/test_send_service.py`
- Test: `tests/test_api_basic.py`

- [x] Add failing service tests for previewing text/template/file without creating history.
- [x] Add failing API test for `POST /api/v1/send/preview`.
- [x] Implement `WorkflowService.preview_send()` by delegating to existing dry-run methods.
- [x] Add `SendPreviewRequest` and `SendPreviewRead` schemas.
- [x] Add REST endpoint.
- [x] Run targeted tests.

---

### Task 5: Retry And Cancel Send History

**Files:**
- Modify: `src/tg_bot_aggregator/repositories.py`
- Modify: `src/tg_bot_aggregator/send_service.py`
- Modify: `src/tg_bot_aggregator/api/send.py`
- Test: `tests/test_send_service.py`
- Test: `tests/test_api_basic.py`

- [x] Add failing tests for retrying a failed `send_history` row.
- [x] Add failing tests for cancelling a queued row.
- [x] Add repository helpers `mark_cancelled()` and status guards.
- [x] Add `SendService.retry_history()` and `SendService.cancel_history()`.
- [x] Add REST endpoints.
- [x] Run targeted tests.

---

### Task 6: Batch Persistence And API

**Files:**
- Modify: `src/tg_bot_aggregator/models.py`
- Modify: `src/tg_bot_aggregator/schemas.py`
- Modify: `src/tg_bot_aggregator/repositories.py`
- Create: `src/tg_bot_aggregator/api/send_batches.py`
- Modify: `src/tg_bot_aggregator/main.py`
- Modify: `alembic/versions/0005_workflow_layer.py`
- Test: `tests/test_repositories.py`
- Test: `tests/test_api_basic.py`

- [x] Add failing repository tests for `SendBatch` and `SendBatchItem`.
- [x] Add failing API tests for batch create/list/detail.
- [x] Add models and migration sections.
- [x] Add repositories and schemas.
- [x] Add router.
- [x] Run targeted tests.

---

### Task 7: Batch Preview, Enqueue, And Worker

**Files:**
- Modify: `src/tg_bot_aggregator/workflow_service.py`
- Modify: `src/tg_bot_aggregator/api/send_batches.py`
- Modify: `src/tg_bot_aggregator/tasks.py`
- Test: `tests/test_send_service.py`
- Test: `tests/test_tasks.py`
- Test: `tests/test_api_basic.py`

- [x] Add failing service test for batch preview producing one payload per destination.
- [x] Add failing service test for batch enqueue creating normal send history rows.
- [x] Add failing test for batch cancel only affecting pending/queued items.
- [x] Implement batch preview and enqueue through `SendService`.
- [x] Add Taskiq batch task.
- [x] Run targeted tests.

---

### Task 8: Diagnostics To Destination

**Files:**
- Modify: `src/tg_bot_aggregator/models.py`
- Modify: `src/tg_bot_aggregator/schemas.py`
- Modify: `src/tg_bot_aggregator/repositories.py`
- Modify: `src/tg_bot_aggregator/diagnostics/formatter.py`
- Modify: `src/tg_bot_aggregator/diagnostics/bot.py`
- Modify: `src/tg_bot_aggregator/api/diagnostics.py`
- Modify: `alembic/versions/0005_workflow_layer.py`
- Test: `tests/test_diagnostics_formatter.py`
- Test: `tests/test_diagnostics_bot.py`
- Test: `tests/test_api_basic.py`

- [x] Add failing formatter test for extracting chat/thread/message metadata.
- [x] Add failing bot test for persisting diagnostic update records.
- [x] Add failing API test for creating destination from diagnostic update.
- [x] Implement `DiagnosticUpdate` model, repository, schemas.
- [x] Persist updates in polling bot.
- [x] Add list/create-destination endpoints.
- [x] Run targeted tests.

---

### Task 9: MCP Workflow Tools

**Files:**
- Modify: `src/tg_bot_aggregator/mcp_catalog.py`
- Modify: `src/tg_bot_aggregator/mcp_server.py`
- Test: `tests/test_mcp_server.py`

- [x] Add failing MCP tests for media list, profile list/create, batch list/create/preview/enqueue, diagnostic update list/create-destination.
- [x] Add tool definitions.
- [x] Implement tools by reusing repositories and `WorkflowService`.
- [x] Run `pytest tests/test_mcp_server.py -q`.

---

### Task 10: Dashboard Workflow UI

**Files:**
- Modify: `src/tg_bot_aggregator/static/index.html`
- Test: `tests/test_static_ui.py`

- [x] Add failing static tests for workflow tabs, media picker, profiles, batch table, preview card, retry/cancel controls, diagnostics create-destination, and MCP connection helper.
- [x] Add Vue state for `mediaItems`, `sendProfiles`, `sendBatches`, `sendPreview`, `mcpConnectionInfo`, and diagnostic updates.
- [x] Add methods for loading media, selecting files, applying profiles, previewing sends, creating batches, enqueueing batches, retry/cancel, and diagnostics destination creation.
- [x] Keep OneDark style and avoid nested cards.
- [x] Run `pytest tests/test_static_ui.py -q`.

---

### Task 11: Docs, Browser Check, Full Validation

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [x] Document media browser as read-only/no-copy.
- [x] Document send profiles, preview, batch sends, retry/cancel, diagnostics-to-destination, and MCP helper.
- [x] Run `pytest`.
- [x] Run `ruff check .`.
- [x] Restart local server.
- [x] Browser-check dashboard on desktop and mobile widths.
- [x] Verify `/favicon.ico` no longer returns 404.
- [x] Report remaining risks.

---

## Self-Review

Spec coverage:

- Media browser: Task 1.
- MCP helper and favicon: Task 2.
- Send profiles: Task 3.
- Unified preview: Task 4.
- Retry/cancel: Task 5.
- Batch persistence/API: Task 6.
- Batch execution: Task 7.
- Diagnostics-to-destination: Task 8.
- MCP workflow tools: Task 9.
- Dashboard: Task 10.
- Docs and verification: Task 11.

Placeholder scan:

- The first two executable tasks include concrete test snippets, implementation snippets, commands, and expected results.
- Later large tasks are scoped by behavior and exact files because they depend on schema names created in earlier tasks.

Type consistency:

- REST prefixes stay under `/api/v1`.
- MCP tools use existing `MCP_TOOL_DEFINITIONS`.
- All send execution still flows through `SendService`.
- Media browser never returns absolute host paths.
