# Diagnostic Polling Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dedicated polling diagnostic bot that replies with readable Telegram message metadata and copyable IDs.

**Architecture:** Keep diagnostics as a separate domain under `tg_bot_aggregator.diagnostics`. Reuse the shared Telegram Bot API client, but add the polling/reply methods it needs. The FastAPI sender remains send-only; polling runs only in a separate process and compose service.

**Tech Stack:** Python 3.11, async `httpx`, existing Telegram Bot API client, pytest, Docker Compose.

---

## File Structure

- `src/tg_bot_aggregator/telegram_bot_api.py`: add generic Bot API methods required by polling diagnostics.
- `src/tg_bot_aggregator/diagnostics/__init__.py`: mark the diagnostics package.
- `src/tg_bot_aggregator/diagnostics/formatter.py`: extract IDs, build copy keyboards, and format readable reports.
- `src/tg_bot_aggregator/diagnostics/bot.py`: long-polling runner and CLI entrypoint.
- `src/tg_bot_aggregator/config.py`: add diagnostic bot settings.
- `docker-compose.yml`: add dedicated `diagnostic-bot` service.
- `.env.example`: document diagnostic settings.
- `README.md`: document how to run and validate the diagnostic bot.
- `tests/test_telegram_bot_api.py`: cover new Bot API client methods.
- `tests/test_diagnostics_formatter.py`: cover report formatting, thread detection, copy buttons, and chunking.
- `tests/test_diagnostics_bot.py`: cover polling behavior with a fake client.

### Task 1: Extend Telegram Bot API Client

**Files:**
- Modify: `src/tg_bot_aggregator/telegram_bot_api.py`
- Test: `tests/test_telegram_bot_api.py`

- [ ] **Step 1: Write failing client tests**

Add tests that call `delete_webhook`, `get_updates`, and `send_message` with `reply_markup`.

- [ ] **Step 2: Run client tests to verify failure**

Run: `python -m pytest tests/test_telegram_bot_api.py -q`

Expected: failures because `delete_webhook` and `get_updates` do not exist, and `send_message` does not accept `reply_markup`.

- [ ] **Step 3: Implement client methods**

Add:

- `delete_webhook(token, drop_pending_updates=True)`
- `get_updates(token, offset=None, timeout=30, allowed_updates=None)`
- optional `reply_markup` to `send_message`

- [ ] **Step 4: Run client tests**

Run: `python -m pytest tests/test_telegram_bot_api.py -q`

Expected: all client tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/tg_bot_aggregator/telegram_bot_api.py tests/test_telegram_bot_api.py
git commit -m "feat: add bot api polling methods"
```

### Task 2: Add Diagnostics Formatter

**Files:**
- Create: `src/tg_bot_aggregator/diagnostics/__init__.py`
- Create: `src/tg_bot_aggregator/diagnostics/formatter.py`
- Test: `tests/test_diagnostics_formatter.py`

- [ ] **Step 1: Write failing formatter tests**

Cover:

- forum topic `message_thread_id`
- private chat/user identifiers
- forwarded message origin
- photo/document file identifiers
- copy keyboard shape
- chunk splitting below 3900 characters

- [ ] **Step 2: Run formatter tests to verify failure**

Run: `python -m pytest tests/test_diagnostics_formatter.py -q`

Expected: import failure because diagnostics formatter does not exist.

- [ ] **Step 3: Implement formatter**

Implement:

- `DiagnosticReport`
- `format_update_report(update)`
- `build_copy_keyboard(identifiers)`
- `chunk_report(text, limit=3900)`

Use plain text reports and copy buttons through Telegram Bot API `copy_text`.

- [ ] **Step 4: Run formatter tests**

Run: `python -m pytest tests/test_diagnostics_formatter.py -q`

Expected: all formatter tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/tg_bot_aggregator/diagnostics tests/test_diagnostics_formatter.py
git commit -m "feat: format diagnostic message reports"
```

### Task 3: Add Polling Diagnostic Bot Runner

**Files:**
- Create: `src/tg_bot_aggregator/diagnostics/bot.py`
- Modify: `src/tg_bot_aggregator/config.py`
- Test: `tests/test_diagnostics_bot.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing polling tests**

Cover:

- startup calls `delete_webhook`
- `get_updates` receives the next offset
- replies preserve `message_thread_id`
- non-message updates still advance offset
- loop can run one iteration for tests

- [ ] **Step 2: Run polling tests to verify failure**

Run: `python -m pytest tests/test_diagnostics_bot.py tests/test_config.py -q`

Expected: import/config failures.

- [ ] **Step 3: Implement config and runner**

Add settings:

- `DIAGNOSTIC_BOT_TOKEN`
- `DIAGNOSTIC_POLL_TIMEOUT_SECONDS`
- `DIAGNOSTIC_RETRY_DELAY_SECONDS`

Implement:

- `DiagnosticPollingBot`
- `run_once()`
- `run_forever()`
- module `main()` entrypoint

- [ ] **Step 4: Run polling tests**

Run: `python -m pytest tests/test_diagnostics_bot.py tests/test_config.py -q`

Expected: tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/tg_bot_aggregator/diagnostics/bot.py src/tg_bot_aggregator/config.py tests/test_diagnostics_bot.py tests/test_config.py
git commit -m "feat: add diagnostic polling runner"
```

### Task 4: Wire Compose and Documentation

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Write static tests**

Add tests or extend existing static/config tests to confirm `diagnostic-bot`, `DIAGNOSTIC_BOT_TOKEN`, and the module command are documented.

- [ ] **Step 2: Run static tests to verify failure**

Run: `python -m pytest tests/test_config.py -q`

Expected: failure until compose/env/docs are updated.

- [ ] **Step 3: Update compose and docs**

Add a `diagnostic-bot` service using the same image:

```yaml
diagnostic-bot:
  build: .
  env_file:
    - path: .env
      required: false
  command: ["python", "-m", "tg_bot_aggregator.diagnostics.bot"]
  environment:
    TELEGRAM_BOT_API_BASE_URL: http://telegram-bot-api:8081
  depends_on:
    - telegram-bot-api
```

Document that this service must use a bot dedicated to diagnostics.

- [ ] **Step 4: Run static tests and compose validation**

Run:

```bash
python -m pytest tests/test_config.py -q
docker compose config
```

Expected: tests pass and compose renders successfully.

- [ ] **Step 5: Commit**

Run:

```bash
git add docker-compose.yml .env.example README.md tests/test_config.py
git commit -m "docs: wire diagnostic polling bot"
```

### Task 5: Full Verification and Merge Prep

**Files:**
- All changed files.

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Run lint**

Run: `python -m ruff check .`

Expected: all checks pass.

- [ ] **Step 3: Validate compose**

Run: `docker compose config`

Expected: compose config renders.

- [ ] **Step 4: Manual dry run**

Run:

```bash
python -m tg_bot_aggregator.diagnostics.bot --once
```

Expected without `DIAGNOSTIC_BOT_TOKEN`: exits with a clear missing-token error and no stack trace.

- [ ] **Step 5: Final status**

Report changed files, validation commands, current branch, and merge recommendation.
