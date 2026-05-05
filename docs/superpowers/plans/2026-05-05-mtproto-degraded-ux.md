# MTProto Degraded UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MTProto analytics login a guided, non-blocking workflow and ensure missing MTProto credentials never interfere with normal Bot API bot creation.

**Architecture:** Keep Bot API and MTProto concerns separate. Add explicit backend configuration errors for MTProto endpoints, then let the Vue admin read MTProto status and render a guided onboarding state with prerequisites, current status, and clear non-blocking messaging.

**Tech Stack:** FastAPI, SQLAlchemy async, Telethon, Vue 3 CDN, pytest

---

### Task 1: Lock the backend contract

**Files:**
- Modify: `tests/test_api_basic.py`
- Modify: `src/tg_bot_aggregator/api/v1/mtproto.py`
- Modify: `src/tg_bot_aggregator/domain/analytics/mtproto.py`

- [ ] Add a failing API test proving `POST /api/v1/mtproto/login/start` returns a controlled client error when `TELEGRAM_API_ID/HASH` are missing.
- [ ] Run the targeted test and verify it fails for the current uncaught configuration path.
- [ ] Implement minimal MTProto configuration error handling in the route/service layer.
- [ ] Re-run the targeted test and verify it passes.

### Task 2: Lock the UI contract

**Files:**
- Modify: `tests/test_static_ui.py`
- Modify: `src/tg_bot_aggregator/static/index.html`

- [ ] Add a failing static UI test proving the MTProto screen contains prerequisites, explicit “MTProto is not needed for Bot API bot creation” guidance, and a status-driven onboarding model.
- [ ] Run the targeted static UI test and verify it fails on the current step-only screen.
- [ ] Implement minimal MTProto onboarding/status UI and wire it to `/api/v1/mtproto/status`.
- [ ] Re-run the targeted static UI test and verify it passes.

### Task 3: Regression-check bot creation and live UI behavior

**Files:**
- Modify: `tests/test_api_basic.py`
- Modify: `src/tg_bot_aggregator/static/index.html`

- [ ] Add or keep a regression test showing Bot API bot creation still succeeds with missing MTProto credentials.
- [ ] Update MTProto actions so the current step follows the returned status instead of blindly advancing.
- [ ] Run focused API/UI tests plus local app smoke verification.
- [ ] Run the full pytest suite.
