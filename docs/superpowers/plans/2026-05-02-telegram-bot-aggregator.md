# Telegram Bot Aggregator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved local async FastAPI/Vue/MCP Telegram bot sender and analytics service.

**Architecture:** Implement a small layered Python application under `src/tg_bot_aggregator`: API routers and MCP endpoints call application services, services use repositories and infrastructure clients, and shared validation stays in focused modules. Runtime services are FastAPI app, Taskiq worker/scheduler, Redis, SQLite, and local Telegram Bot API server.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, SQLite/aiosqlite, Alembic, httpx, Telethon, Taskiq, taskiq-redis, Redis, MCP Python SDK, Vue 3 CDN, pytest.

---

## File Structure

- Create `pyproject.toml`: project metadata, runtime dependencies, pytest/ruff config.
- Create `README.md`: local setup, security warning, compose deployment, OMW media mount.
- Create `.env.example`: documented environment variables with safe defaults.
- Create `docker-compose.yml`, `Dockerfile`: app, worker, scheduler, Redis, local Bot API server.
- Create `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial.py`: migrations.
- Create `src/tg_bot_aggregator/config.py`: Pydantic settings.
- Create `src/tg_bot_aggregator/db.py`: async engine/session dependency.
- Create `src/tg_bot_aggregator/models.py`: SQLAlchemy ORM models.
- Create `src/tg_bot_aggregator/schemas.py`: Pydantic request/response models.
- Create `src/tg_bot_aggregator/repositories.py`: async database operations.
- Create `src/tg_bot_aggregator/events.py`: Redis Stream event publisher/reader and SSE formatting.
- Create `src/tg_bot_aggregator/security.py`: token redaction and origin validation helpers.
- Create `src/tg_bot_aggregator/shared_paths.py`: safe shared-media path validation.
- Create `src/tg_bot_aggregator/telegram_bot_api.py`: async Bot API client.
- Create `src/tg_bot_aggregator/send_service.py`: text/template/file send orchestration.
- Create `src/tg_bot_aggregator/mtproto_service.py`: Telethon login/status/analytics boundary.
- Create `src/tg_bot_aggregator/analytics_service.py`: analytics target refresh orchestration.
- Create `src/tg_bot_aggregator/tasks.py`: Taskiq broker and analytics tasks.
- Create `src/tg_bot_aggregator/mcp_server.py`: MCP tools and ASGI apps.
- Create `src/tg_bot_aggregator/api/*.py`: REST routers.
- Create `src/tg_bot_aggregator/main.py`: FastAPI application factory and mounts.
- Create `src/tg_bot_aggregator/static/index.html`: Vue 3 CDN UI.
- Create `tests/*.py`: focused unit and integration tests.

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `.env.example`
- Create: `src/tg_bot_aggregator/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write scaffold files**

Create Python package metadata with dependencies: `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `sqlalchemy[asyncio]`, `aiosqlite`, `alembic`, `httpx`, `redis`, `taskiq`, `taskiq-redis`, `telethon`, `mcp`, `python-multipart`, `pytest`, `pytest-asyncio`, `anyio`.

- [ ] **Step 2: Verify package metadata**

Run: `python -m pip install -e ".[dev]"`

Expected: installation succeeds.

- [ ] **Step 3: Run empty test baseline**

Run: `pytest -q`

Expected: pytest starts and reports no failing tests.

- [ ] **Step 4: Commit**

Run:

```bash
git add pyproject.toml README.md .env.example src tests
git commit -m "chore: scaffold telegram bot aggregator"
```

Expected: commit succeeds.

## Task 2: Settings, Database Models, and Migration

**Files:**
- Create: `src/tg_bot_aggregator/config.py`
- Create: `src/tg_bot_aggregator/db.py`
- Create: `src/tg_bot_aggregator/models.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/0001_initial.py`
- Test: `tests/test_config.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing settings tests**

Test safe defaults: localhost bind, `/api/v1`, `/mcp/v1`, `/shared/media`, local Bot API base URL, and 2 GB max file bytes.

- [ ] **Step 2: Implement settings**

Use `pydantic_settings.BaseSettings` with explicit env names and typed fields.

- [ ] **Step 3: Write failing model tests**

Use temporary SQLite async engine, create metadata, insert one bot, destination, template, and send history row.

- [ ] **Step 4: Implement ORM models and DB helpers**

Define all tables from the approved spec with SQLAlchemy async-compatible models and UTC timestamp defaults.

- [ ] **Step 5: Add Alembic initial migration**

Create matching SQL migration with constraints and indexes for unique template tags and common foreign keys.

- [ ] **Step 6: Verify**

Run: `pytest tests/test_config.py tests/test_models.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/tg_bot_aggregator/config.py src/tg_bot_aggregator/db.py src/tg_bot_aggregator/models.py alembic.ini alembic tests/test_config.py tests/test_models.py
git commit -m "feat: add settings and database schema"
```

Expected: commit succeeds.

## Task 3: Repositories and Shared Validation

**Files:**
- Create: `src/tg_bot_aggregator/repositories.py`
- Create: `src/tg_bot_aggregator/shared_paths.py`
- Create: `src/tg_bot_aggregator/security.py`
- Test: `tests/test_shared_paths.py`
- Test: `tests/test_repositories.py`
- Test: `tests/test_security.py`

- [ ] **Step 1: Write failing path validation tests**

Cover relative path success, absolute path rejection, `..` traversal rejection, missing file rejection, symlink escape rejection, and size limit rejection.

- [ ] **Step 2: Implement path validation**

Return a typed `SharedFile` object with relative path, resolved path, URI, and size bytes.

- [ ] **Step 3: Write failing security tests**

Verify token redaction from strings and nested dict/list payloads.

- [ ] **Step 4: Implement security helpers**

Implement deterministic redaction and allowed-origin checking.

- [ ] **Step 5: Write failing repository tests**

Cover CRUD for bots, destinations, templates, send history, analytics targets/runs/snapshots.

- [ ] **Step 6: Implement repositories**

Use `AsyncSession` and explicit methods. Do not hide missing records; return `None` or raise a narrow domain exception consistently.

- [ ] **Step 7: Verify**

Run: `pytest tests/test_shared_paths.py tests/test_security.py tests/test_repositories.py -q`

Expected: all tests pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add src/tg_bot_aggregator/repositories.py src/tg_bot_aggregator/shared_paths.py src/tg_bot_aggregator/security.py tests/test_shared_paths.py tests/test_repositories.py tests/test_security.py
git commit -m "feat: add repositories and shared validation"
```

Expected: commit succeeds.

## Task 4: Telegram Send Services

**Files:**
- Create: `src/tg_bot_aggregator/telegram_bot_api.py`
- Create: `src/tg_bot_aggregator/send_service.py`
- Test: `tests/test_telegram_bot_api.py`
- Test: `tests/test_send_service.py`

- [ ] **Step 1: Write failing Bot API client tests**

Use `httpx.MockTransport` to verify `getMe`, `sendMessage`, `sendDocument`, and `sendVideo` call the configured base URL and never log/return token-bearing URLs.

- [ ] **Step 2: Implement Bot API client**

Use one `httpx.AsyncClient`, timeouts, explicit Telegram error handling, and support local file URI/path sends.

- [ ] **Step 3: Write failing send service tests**

Cover direct text send, template send, forum `message_thread_id`, successful file send, cloud Bot API file-path rejection, and failed Telegram response persisted in history.

- [ ] **Step 4: Implement send service**

Create send history before Telegram call, update status after call, persist redacted response context, and publish events through an injected publisher.

- [ ] **Step 5: Verify**

Run: `pytest tests/test_telegram_bot_api.py tests/test_send_service.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/tg_bot_aggregator/telegram_bot_api.py src/tg_bot_aggregator/send_service.py tests/test_telegram_bot_api.py tests/test_send_service.py
git commit -m "feat: add telegram send services"
```

Expected: commit succeeds.

## Task 5: Events, REST API, and SSE

**Files:**
- Create: `src/tg_bot_aggregator/events.py`
- Create: `src/tg_bot_aggregator/api/dependencies.py`
- Create: `src/tg_bot_aggregator/api/bots.py`
- Create: `src/tg_bot_aggregator/api/destinations.py`
- Create: `src/tg_bot_aggregator/api/templates.py`
- Create: `src/tg_bot_aggregator/api/send.py`
- Create: `src/tg_bot_aggregator/api/events.py`
- Create: `src/tg_bot_aggregator/api/health.py`
- Create: `src/tg_bot_aggregator/main.py`
- Test: `tests/test_events.py`
- Test: `tests/test_api_basic.py`

- [ ] **Step 1: Write failing event tests**

Verify event payload includes `schema_version`, `event_type`, stable ID handling, and SSE frame formatting.

- [ ] **Step 2: Implement events**

Use Redis Streams in production and a memory fallback for tests/dev when Redis is unavailable.

- [ ] **Step 3: Write failing API tests**

Use `httpx.AsyncClient` with ASGI transport. Cover health, bot CRUD, destination/template CRUD, text send through mocked service, and `/api/v1/events` frame shape.

- [ ] **Step 4: Implement API routers and app factory**

Mount REST routes under `/api/v1`, serve `/`, add CORS with explicit origins, and wire lifespan resources.

- [ ] **Step 5: Verify**

Run: `pytest tests/test_events.py tests/test_api_basic.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/tg_bot_aggregator/events.py src/tg_bot_aggregator/api src/tg_bot_aggregator/main.py tests/test_events.py tests/test_api_basic.py
git commit -m "feat: add REST API and frontend events"
```

Expected: commit succeeds.

## Task 6: MTProto, Analytics, and Taskiq

**Files:**
- Create: `src/tg_bot_aggregator/mtproto_service.py`
- Create: `src/tg_bot_aggregator/analytics_service.py`
- Create: `src/tg_bot_aggregator/tasks.py`
- Create: `src/tg_bot_aggregator/api/mtproto.py`
- Create: `src/tg_bot_aggregator/api/analytics.py`
- Test: `tests/test_analytics_service.py`
- Test: `tests/test_tasks.py`
- Test: `tests/test_api_analytics.py`

- [ ] **Step 1: Write failing MTProto/analytics tests**

Mock Telethon at the boundary. Cover login state transitions, partial metrics with `None`, target refresh success, and target resolution failure.

- [ ] **Step 2: Implement MTProto service**

Keep Telethon session files in `TELETHON_SESSION_DIR`, expose start/code/password/status methods, and keep Telethon exceptions at the boundary.

- [ ] **Step 3: Implement analytics service**

Refresh one target, write snapshots/runs, and emit Redis events.

- [ ] **Step 4: Write failing Taskiq tests**

Verify broker object exists, task functions call analytics service, and failures mark runs failed.

- [ ] **Step 5: Implement Taskiq tasks and analytics APIs**

Expose manual refresh endpoints and CRUD for targets. Do not perform long Telethon refresh in request handlers.

- [ ] **Step 6: Verify**

Run: `pytest tests/test_analytics_service.py tests/test_tasks.py tests/test_api_analytics.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/tg_bot_aggregator/mtproto_service.py src/tg_bot_aggregator/analytics_service.py src/tg_bot_aggregator/tasks.py src/tg_bot_aggregator/api/mtproto.py src/tg_bot_aggregator/api/analytics.py tests/test_analytics_service.py tests/test_tasks.py tests/test_api_analytics.py
git commit -m "feat: add mtproto analytics tasks"
```

Expected: commit succeeds.

## Task 7: MCP Endpoints

**Files:**
- Create: `src/tg_bot_aggregator/mcp_server.py`
- Modify: `src/tg_bot_aggregator/main.py`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write failing MCP tests**

Verify MCP app exposes tools: `list_bots`, `list_destinations`, `list_message_templates`, `send_text`, `send_template`, `send_file_from_shared_path`, `refresh_analytics`, `get_analytics_summary`, `get_send_history`.

- [ ] **Step 2: Implement MCP server**

Use official MCP Python SDK `FastMCP`. Mount Streamable HTTP at `/mcp/v1` and SSE compatibility endpoints at `/mcp/v1/sse` and `/mcp/v1/messages` where supported by the SDK.

- [ ] **Step 3: Verify**

Run: `pytest tests/test_mcp_server.py -q`

Expected: all tests pass or skips only when the installed SDK lacks legacy SSE mounting.

- [ ] **Step 4: Commit**

Run:

```bash
git add src/tg_bot_aggregator/mcp_server.py src/tg_bot_aggregator/main.py tests/test_mcp_server.py
git commit -m "feat: add mcp tools"
```

Expected: commit succeeds.

## Task 8: Vue UI and Deployment

**Files:**
- Create: `src/tg_bot_aggregator/static/index.html`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `README.md`
- Test: `tests/test_static_ui.py`

- [ ] **Step 1: Write failing static UI test**

Verify root page includes Vue CDN, uses `/api/v1`, opens `/api/v1/events`, and includes no auth copy that contradicts the spec.

- [ ] **Step 2: Implement UI**

Build a dense local operations UI with tabs for bots, destinations, templates, send, history, MTProto, analytics, and health. Use REST and EventSource.

- [ ] **Step 3: Implement Docker deployment files**

Compose services: `app`, `worker`, `scheduler`, `redis`, `telegram-bot-api`. Use `aiogram/telegram-bot-api:latest` with `TELEGRAM_LOCAL=1` because it is a documented community image for the official `tdlib/telegram-bot-api` server.

- [ ] **Step 4: Update README**

Document setup, NFS mount, `.env`, local Bot API, no-auth warning, commands, and validation steps.

- [ ] **Step 5: Verify**

Run: `pytest tests/test_static_ui.py -q`

Expected: all tests pass.

Run: `docker compose config`

Expected: compose config renders successfully, allowing warnings only for unset secrets in local shell.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/tg_bot_aggregator/static/index.html Dockerfile docker-compose.yml .env.example README.md tests/test_static_ui.py
git commit -m "feat: add vue ui and deployment"
```

Expected: commit succeeds.

## Task 9: Final Verification

**Files:**
- Modify as needed: all implementation files.

- [ ] **Step 1: Run full tests**

Run: `pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Run lint**

Run: `ruff check .`

Expected: no lint errors.

- [ ] **Step 3: Run Alembic smoke check**

Run: `alembic upgrade head`

Expected: migration applies to configured local SQLite DB.

- [ ] **Step 4: Run app import smoke check**

Run: `python -c "from tg_bot_aggregator.main import create_app; app = create_app(); print(app.title)"`

Expected: prints `Telegram Bot Aggregator`.

- [ ] **Step 5: Check git status**

Run: `git status --short`

Expected: clean working tree.

## Self-Review

Spec coverage:

- Covers async FastAPI, Vue 3 CDN UI, SQLite tokens, send-only Bot API, groups/channels/private/forum destinations, MCP Streamable HTTP and SSE compatibility, frontend SSE, Taskiq/Redis, Telethon analytics, local Bot API, shared OMW media, versioning, Docker Compose, and tests.

Placeholder scan:

- No task depends on undefined future behavior.

Type consistency:

- REST prefix is consistently `/api/v1`.
- MCP prefix is consistently `/mcp/v1`.
- Shared media container path is consistently `/shared/media`.
- Runtime package is consistently `tg_bot_aggregator`.
