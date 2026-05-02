# Telegram Ops Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add scoped tokens, audit, idempotency, dry-run, destination aliases/checks, discovery polling, queued send retry, template variables, and dashboard controls.

**Architecture:** Keep API handlers thin. Put behavior in services/repositories, reuse the existing Bot API client, Taskiq broker, SendService, and dashboard single HTML file.

**Tech Stack:** FastAPI, SQLAlchemy async, SQLite, Alembic, Taskiq Redis, Vue 3 CDN, pytest, ruff.

---

### Task 1: Persistence And Schemas

**Files:**
- Modify: `src/tg_bot_aggregator/models.py`
- Modify: `src/tg_bot_aggregator/schemas.py`
- Modify: `src/tg_bot_aggregator/repositories.py`
- Create: `alembic/versions/0004_ops_automation.py`
- Test: `tests/test_models.py`
- Test: `tests/test_repositories.py`

- [x] Add `scopes_json` to `ApiToken`, `alias` to `Destination`, idempotency/queue columns to `SendHistory`, and new `AuditEvent`, `BotDiscoverySettings`, `BotDiscoveryEvent` models.
- [x] Add Pydantic models for token scopes, audit reads, destination check, discovery settings, dry-run, and send mode/variables.
- [x] Add repository methods for scoped tokens, alias lookup, idempotency lookup, queued send state transitions, audit events, and discovery settings/events.
- [x] Add Alembic migration with backward-compatible defaults.
- [x] Add model/repository tests and verify they fail before implementation, then pass after implementation.

### Task 2: Token Scope Enforcement And Audit

**Files:**
- Modify: `src/tg_bot_aggregator/auth_middleware.py`
- Modify: `src/tg_bot_aggregator/api/auth.py`
- Create: `src/tg_bot_aggregator/audit.py`
- Test: `tests/test_api_auth.py`

- [x] Add scope constants and operation-to-scope resolution.
- [x] Enforce scopes for protected host requests.
- [x] Support scope selection when creating tokens.
- [x] Write audit events for token create/revoke/session and rejected protected requests.
- [x] Add tests for missing scope, accepted scope, backward-compatible all-scope tokens, and audit rows.

### Task 3: Send Dry-Run, Idempotency, Variables, Queue

**Files:**
- Modify: `src/tg_bot_aggregator/send_service.py`
- Create: `src/tg_bot_aggregator/template_renderer.py`
- Modify: `src/tg_bot_aggregator/api/send.py`
- Modify: `src/tg_bot_aggregator/tasks.py`
- Test: `tests/test_send_service.py`
- Test: `tests/test_api_basic.py`
- Test: `tests/test_tasks.py`

- [x] Add template variable renderer with tests for replacement and missing variables.
- [x] Add dry-run methods that validate target/file/template and return payload without Telegram calls.
- [x] Add idempotency handling to text/template/file/reference sends.
- [x] Add queued send creation and Taskiq worker execution with retry classification.
- [x] Add REST endpoints for dry-run and queued mode.
- [x] Add tests for no duplicate send, conflicting idempotency key, dry-run no history, queued send, and retryable errors.

### Task 4: Destination Aliases And Chat Check

**Files:**
- Modify: `src/tg_bot_aggregator/telegram_bot_api.py`
- Modify: `src/tg_bot_aggregator/api/destinations.py`
- Modify: `src/tg_bot_aggregator/send_service.py`
- Test: `tests/test_telegram_bot_api.py`
- Test: `tests/test_api_basic.py`

- [x] Add Bot API `getChat` and `getChatMemberCount`.
- [x] Add alias to create/update/list responses.
- [x] Resolve `destination_alias` in send/dry-run requests.
- [x] Add destination check endpoint and persist returned metadata.
- [x] Add tests for alias resolution and chat check partial failure handling.

### Task 5: Discovery Polling Domain

**Files:**
- Create: `src/tg_bot_aggregator/discovery/bot.py`
- Create: `src/tg_bot_aggregator/discovery/__init__.py`
- Create: `src/tg_bot_aggregator/api/discovery.py`
- Modify: `src/tg_bot_aggregator/main.py`
- Modify: `docker-compose.yml`
- Test: `tests/test_discovery_bot.py`
- Test: `tests/test_api_basic.py`

- [x] Add per-bot discovery settings API.
- [x] Implement polling runner with `allowed_updates=["my_chat_member"]`.
- [x] Upsert destinations from membership updates only.
- [x] Store last update and discovery events.
- [x] Add compose service `discovery-bot`.
- [x] Add tests for disabled state, webhook initialization, destination upsert, progress storage, and API settings.

### Task 6: MCP And Dashboard

**Files:**
- Modify: `src/tg_bot_aggregator/mcp_catalog.py`
- Modify: `src/tg_bot_aggregator/mcp_server.py`
- Modify: `src/tg_bot_aggregator/static/index.html`
- Test: `tests/test_mcp_server.py`
- Test: `tests/test_static_ui.py`

- [x] Add MCP tools for dry-run, audit list, discovery settings, and destination check.
- [x] Add compact Vue controls for scopes, aliases, dry-run, send mode, discovery, audit, and curl copy.
- [x] Keep OneDark theme and existing layout.
- [x] Add static smoke tests for new labels/functions.

### Task 7: Docs, Lint, Full Validation, Merge

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [x] Document scopes, discovery polling exception, queue settings, aliases, dry-run, and audit.
- [x] Run `PYTHONPATH=src python3.11 -m pytest`.
- [x] Run `PYTHONPATH=src python3.11 -m ruff check .`.
- [x] Merge `feature/tg-ops-automation` back to `main`.
- [x] Restart local server from main and smoke-check `/api/v1/health`.

