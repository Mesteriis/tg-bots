# Operations Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add runtime configuration, preflight, policy, health, scheduling, callbacks, template versions, and JSON git backups around the existing Telegram send service.

**Current status:** Implemented locally. The checklist below was reconciled on 2026-05-03 against the repository, `ruff check .`, and `pytest -q`.

**Architecture:** Keep all send execution in `SendService`; add small operation services for settings, preflight, backups, and callbacks. Store new state in additive SQLite tables so existing local databases can create missing tables without altering old tables.

**Tech Stack:** FastAPI, SQLAlchemy async, SQLite, httpx, Taskiq, Vue 3 CDN, pytest, ruff.

---

### Task 1: Runtime Settings And Backup Core

**Files:**
- Modify: `src/tg_bot_aggregator/models.py`
- Modify: `src/tg_bot_aggregator/repositories.py`
- Modify: `src/tg_bot_aggregator/schemas.py`
- Create: `src/tg_bot_aggregator/runtime_settings.py`
- Create: `src/tg_bot_aggregator/backup_service.py`
- Create: `src/tg_bot_aggregator/api/operations.py`
- Modify: `src/tg_bot_aggregator/main.py`
- Test: `tests/test_api_basic.py`
- Test: `tests/test_repositories.py`

- [x] Add failing API test for `GET/PATCH /api/v1/operations/settings` applying `max_local_file_bytes` without restart.
- [x] Add failing backup test for `POST /api/v1/operations/backup/run` returning JSON export metadata.
- [x] Add additive models: `RuntimeSettings`, `BackupRun`.
- [x] Add repositories and schemas.
- [x] Add runtime overlay and app-state apply helper.
- [x] Add JSON backup export service with optional git push.
- [x] Add operations router and include it.
- [x] Run targeted tests.

### Task 2: Preflight, Policy, Destination Health

**Files:**
- Modify: `src/tg_bot_aggregator/models.py`
- Modify: `src/tg_bot_aggregator/repositories.py`
- Modify: `src/tg_bot_aggregator/schemas.py`
- Create: `src/tg_bot_aggregator/operations_service.py`
- Modify: `src/tg_bot_aggregator/send_service.py`
- Modify: `src/tg_bot_aggregator/api/send.py`
- Modify: `src/tg_bot_aggregator/api/destinations.py`
- Test: `tests/test_send_service.py`
- Test: `tests/test_api_basic.py`

- [x] Add failing preflight test for non-sending check output.
- [x] Add failing policy test for rate limit rejection.
- [x] Add failing destination check test for persisted destination health.
- [x] Add `DestinationHealth` table and repository.
- [x] Add `OperationsService.preflight_send`.
- [x] Enforce simple send policy in `SendService`.
- [x] Persist health from destination checks.
- [x] Run targeted tests.

### Task 3: Dead Letter, Scheduling, Batch Progress, Callbacks

**Files:**
- Modify: `src/tg_bot_aggregator/repositories.py`
- Modify: `src/tg_bot_aggregator/schemas.py`
- Modify: `src/tg_bot_aggregator/send_service.py`
- Modify: `src/tg_bot_aggregator/workflow_service.py`
- Modify: `src/tg_bot_aggregator/api/send.py`
- Modify: `src/tg_bot_aggregator/api/send_batches.py`
- Modify: `src/tg_bot_aggregator/tasks.py`
- Test: `tests/test_send_service.py`
- Test: `tests/test_api_basic.py`

- [x] Add failing tests for dead-letter list, scheduled queued row, and batch progress.
- [x] Add callback delivery test using mocked HTTP.
- [x] Reuse `send_history.next_retry_at` as `send_at`.
- [x] Add due-row repository methods.
- [x] Add callback emission on send terminal states.
- [x] Add progress counters to batch read responses.
- [x] Run targeted tests.

### Task 4: Template Versions

**Files:**
- Modify: `src/tg_bot_aggregator/models.py`
- Modify: `src/tg_bot_aggregator/repositories.py`
- Modify: `src/tg_bot_aggregator/schemas.py`
- Modify: `src/tg_bot_aggregator/api/templates.py`
- Test: `tests/test_api_basic.py`
- Test: `tests/test_repositories.py`

- [x] Add failing tests for version creation and rollback.
- [x] Add `MessageTemplateVersion`.
- [x] Store version on create/update.
- [x] Add list versions and rollback endpoints.
- [x] Run targeted tests.

### Task 5: Dashboard And Docs

**Files:**
- Modify: `src/tg_bot_aggregator/static/index.html`
- Modify: `README.md`
- Modify: `.env.example`
- Test: `tests/test_static_ui.py`

- [x] Add failing static UI tests for operations settings, backup, preflight, destination health, template versions, dead-letter, scheduling, and batch progress.
- [x] Add Operations tab.
- [x] Add Send preflight and schedule controls.
- [x] Add destination health and template version UI.
- [x] Add backup controls.
- [x] Update docs.
- [x] Run full validation.

## Self-Review

Spec coverage:

- Runtime settings: Task 1.
- JSON git backup: Task 1.
- Preflight and policy: Task 2.
- Destination health: Task 2.
- Dead-letter and schedule: Task 3.
- Batch progress and callbacks: Task 3.
- Template versions: Task 4.
- Frontend and docs: Task 5.

Placeholder scan:

- No TBD/TODO placeholders.

Type consistency:

- Runtime config uses `RuntimeSettings`.
- Backup records use `BackupRun`.
- Destination checks use separate `DestinationHealth`.
- Template history uses `MessageTemplateVersion`.
