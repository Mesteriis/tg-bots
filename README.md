# Telegram Bot Aggregator

Local async FastAPI service for managing Telegram bot tokens, sending tagged text/media messages, exposing MCP tools, and collecting MTProto analytics.

## OSS Status

This repository is distributed under the MIT License. Contributions are welcome through focused issues and pull requests. Do not include bot tokens, API tokens, `.env` files, SQLite databases, or Telethon session files in public reports or commits.

Public portfolio mirror:

```text
git@github.com:Mesteriis/tg-bots.git
```

Internal deployment repository:

```text
https://git.sh-inc.ru/avm/tg-bots.git
```

## Security Model

This project is intentionally designed for a trusted local network. Localhost and ordinary LAN access remain unauthenticated. Requests whose `Host`, `X-Forwarded-Host`, or `Origin` matches `PROTECTED_API_HOSTS` require a permanent API token for `/api/v1/*`, `/api/v1/events`, and `/mcp/v1/*`. The default protected hosts are `tg.sh-inc.ru` and `tg.sh-inc.dev`.

Create permanent API tokens from the dashboard MCP tab or through MCP tools while connected locally. Tokens are shown once, stored in SQLite only as hashes, and can be revoked from the dashboard. Tokens have explicit scopes:

```text
read
send
mcp_admin
ops_admin
tg_compat
```

Protected `/bot...` facade calls require `tg_compat`; send endpoints require `send`; read endpoints require `read`; MCP/settings/token administration requires `mcp_admin`; non-GET `/api/v1/ops/*` calls require `ops_admin`.

Bot tokens are stored in SQLite as plain text by product decision. Do not expose the app or database outside the trusted network.

## Development

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
uvicorn tg_bot_aggregator.main:create_app --factory --reload
```

The repository keeps `uv.lock` and `.python-version` for reproducible local and CI installs. Runtime Docker images still install from `pyproject.toml` inside Python 3.11.

The API is versioned under `/api/v1`. MCP endpoints are under `/mcp/v1`.

## MCP Settings and Protected Domains

Dashboard path: open the `MCP` tab.

REST endpoints:

```text
GET /api/v1/mcp/settings
PATCH /api/v1/mcp/settings
GET /api/v1/auth/tokens
POST /api/v1/auth/tokens
DELETE /api/v1/auth/tokens/{token_id}
POST /api/v1/auth/session
```

MCP admin tools:

```text
list_api_tokens
create_api_token
revoke_api_token
```

For protected domains, send `X-API-Token: <token>` or `Authorization: Bearer <token>`. Browser SSE uses `/api/v1/auth/session` to set an HttpOnly cookie because native `EventSource` cannot send custom headers.

## Telegram-Compatible Send API

The app exposes a small Telegram Bot API-compatible facade for integrations that already know how to call Telegram actions:

```text
POST /bot{telegram_bot_token}/getMe
POST /bot{telegram_bot_token}/sendMessage
POST /bot{telegram_bot_token}/sendDocument
POST /bot{telegram_bot_token}/sendVideo
```

The token is resolved against bots stored in SQLite. The facade is intentionally allowlisted: it does not expose polling, webhooks, or arbitrary Telegram methods. Successful sends are recorded in send history and the returned Telegram `chat` object is used to create or update a matching destination automatically. Protected domains still require a permanent API token.

## Sending Conveniences

Send endpoints support:

```text
Idempotency-Key: <stable unique key>
```

Repeated requests with the same key return the original send history row instead of sending a duplicate. Reusing the same key for a different payload returns `409`.

Dry-run endpoints validate bot, target, template variables, and shared file path without sending to Telegram or creating history:

```text
POST /api/v1/send/preview
POST /api/v1/send/preflight
POST /api/v1/send/text/dry-run
POST /api/v1/send/template/dry-run
POST /api/v1/send/file/dry-run
```

`/send/preflight` returns structured checks for bot state, send policy, target resolution, template variables, and file path validation. Requests can use `send_mode=queued` to enqueue through Taskiq/Redis, or `send_at` with an ISO datetime to create a scheduled queued row. Transient Telegram errors (`429`, `5xx`, network failures) are retried according to `SEND_RETRY_MAX_ATTEMPTS` and `SEND_RETRY_DELAY_SECONDS`.

Templates support simple placeholders:

```text
{{name}}
{{date}}
{{time}}
{{datetime}}
```

Values come from the request `variables` object plus the built-in date/time values. Missing variables fail validation.

Template changes are versioned. Creation, update and rollback append immutable versions:

```text
GET /api/v1/templates/{template_id}/versions
POST /api/v1/templates/{template_id}/rollback/{version_id}
```

Destinations can have an optional per-bot `alias`, which can be used as `destination_alias` in send and dry-run requests. Destination metadata can be refreshed with:

```text
POST /api/v1/destinations/{destination_id}/check
GET /api/v1/destinations/{destination_id}/health
```

The health endpoint returns the latest check snapshot, including partial warnings such as missing rights for member counts.

Reusable send profiles store a common bot/target/message combination for the dashboard:

```text
GET /api/v1/send-profiles
POST /api/v1/send-profiles
GET /api/v1/send-profiles/{profile_id}
PATCH /api/v1/send-profiles/{profile_id}
DELETE /api/v1/send-profiles/{profile_id}
```

Batch sends store one payload and many targets. Preview expands the payload per destination without creating history. Enqueue creates normal queued send history rows, so retry/cancel behavior stays shared with ordinary sends:

```text
GET /api/v1/send-batches
POST /api/v1/send-batches
GET /api/v1/send-batches/{batch_id}
POST /api/v1/send-batches/{batch_id}/preview
POST /api/v1/send-batches/{batch_id}/enqueue
POST /api/v1/send-batches/{batch_id}/cancel
```

Failed or queued history rows can be controlled directly:

```text
GET /api/v1/send-history/dead-letter
GET /api/v1/send-history/due
POST /api/v1/send-history/{send_history_id}/retry
POST /api/v1/send-history/{send_history_id}/cancel
```

If `CALLBACK_ENABLED=true` and `CALLBACK_URL` is configured, terminal send states emit a small JSON callback with `schema_version`, `event_type`, `send_history_id`, and final `status`. Callback failures do not change the Telegram send result.

## Send Reliability

The dashboard tab `Надежность` shows the live send flow graph:

```text
Batch / Manual -> Queue -> Policy gate -> Worker lease -> Bot bucket -> Chat bucket -> Telegram -> Result
```

Queued sends use worker leases so two workers do not process the same send history row concurrently. Retryable Telegram failures are deferred by setting `next_retry_at`; once the retry budget is exhausted, the row moves to `dead_letter`. Non-retryable operational problems move to `blocked`.

Reliability REST endpoints:

```text
GET /api/v1/reliability/summary
GET /api/v1/reliability/graph
GET /api/v1/reliability/attempts
GET /api/v1/reliability/stale-locks
POST /api/v1/reliability/stale-locks/release
POST /api/v1/reliability/send-history/bulk-retry
POST /api/v1/reliability/send-history/bulk-cancel
```

Runtime settings include `RELIABILITY_ENABLED`, `SEND_DEFAULT_MODE`, global/bot/chat/destination rate limits, retry backoff, worker lease duration, stale lock grace, and the send dedupe window.

MCP exposes the same reliability controls through `get_reliability_summary`, `get_reliability_graph`, `list_send_attempts`, `list_rate_limit_buckets`, `release_stale_send_locks`, `bulk_retry_sends`, and `bulk_cancel_sends`.

## Runtime Operations and JSON Backup

Open the `Операции` dashboard tab to change runtime settings without restarting FastAPI. Values are stored in SQLite and applied immediately to the current process:

```text
GET /api/v1/operations/settings
PATCH /api/v1/operations/settings
```

Editable settings include Bot API URL, Telegram API ID/hash, Telethon session dir, shared media root, file limit, retry policy, simple send policy, callback URL, protected hosts, CORS/MCP origins, DB/Redis URLs, diagnostic/discovery polling timings, and JSON backup settings. DB URL, CORS middleware, and listen host/port are persisted for local configuration and backup, but the active process connection/listener still changes only after restart.

The backup service exports the current configuration to JSON and can optionally commit/push it to a configured git repository:

```text
GET /api/v1/operations/backup/runs
POST /api/v1/operations/backup/run
```

Secrets such as bot tokens, Redis/DB URLs, Telegram API hash, callback URL, git repo URL, and Git API token are excluded by default. Before each backup the service checks repository privacy through GitHub or Gitea:

- GitHub: `GET https://api.github.com/repos/{owner}/{repo}`.
- Gitea: `GET {gitea_api_base_url}/repos/{owner}/{repo}`, defaulting to `https://{git_host}/api/v1`.

If the API confirms `private=true`, secrets are included automatically. If the repo is public, the API token is missing, the API cannot read the repo, or privacy is unknown, secrets stay excluded unless `backup_include_secrets=true` is explicitly enabled as a local manual override. Configure `backup_git_service` as `auto`, `github`, or `gitea`.

Authentication is intentionally token-based, without OAuth:

- `backup_git_auth_method=token` sends a GitHub PAT as `Authorization: Bearer ...`.
- `backup_git_auth_method=token` sends a Gitea access token as `Authorization: token ...`.
- `backup_git_auth_method=none` disables the Authorization header for public repositories.

The Operations tab has a `Проверить доступ к repo` button that runs the same privacy check before backup.

Additional backup operations:

```text
POST /api/v1/operations/backup/check-repo
POST /api/v1/operations/backup/preflight
POST /api/v1/operations/backup/diff
POST /api/v1/operations/backup/import/preview
POST /api/v1/operations/backup/import/apply
POST /api/v1/operations/backup/runs/{run_id}/restore-preview
POST /api/v1/operations/backup/runs/{run_id}/restore
```

Preflight reports repository access, privacy status, whether secrets will be included, whether git push is configured, and a section-level diff against the latest successful snapshot. Diff responses also include row-level changes with redacted secret values, so the dashboard can show exactly which saved rows will be added, removed, or changed. The dashboard shows a persistent warning when secret backups are manually enabled.

Scheduled backup is configured from the same Operations tab through `backup_schedule_enabled`, `backup_schedule_interval_seconds`, and `backup_schedule_push_to_git`. The scheduler process checks whether a backup is due and then runs the same backup path as a manual run.

Restore is intentionally explicit. The preferred dashboard flow is the restore wizard: choose a stored `backup_run`, select the sections to restore, run preview, inspect the row-level diff, then send `confirm=RESTORE`. Partial restore is supported through the `sections` request field; selecting `templates` also restores `template_versions` to keep template history consistent. The raw JSON import endpoints remain available for external snapshots. Every apply creates a safety backup run of the current state before replacing selected backed-up sections, records an audit event, and rejects snapshots missing required fields such as bot tokens. A backup created with secrets excluded can still be useful for review, but it is not accepted for restore when selected sections require missing secret columns.

## Shared Media

The app does not upload large file bodies. An external uploader writes files to the OMW `media` share. The Docker host must mount:

```text
192.168.1.23:/export/media -> /mnt/omw-media -> /shared/media
```

The app validates relative paths under `/shared/media` and sends files through a local Telegram Bot API server in local mode.
If `SHARED_MEDIA_ROOT` is missing, not readable, or above-limit files exceed `MAX_LOCAL_FILE_BYTES`, file sends fail with a normal API error before any Telegram call. Set `SHARED_MEDIA_REQUIRE_MOUNT=true` when the deployment must reject a plain directory that is not an actual mounted share. The dashboard disables file sending when health reports shared media or local Bot API as unavailable.

The dashboard and MCP expose a read-only media browser:

```text
GET /api/v1/media?path=<relative-directory>
GET /api/v1/media/tree?path=<relative-directory>
MCP tool: list_media
```

The browser never deletes, moves, uploads, copies, or proxies files. It only lists direct children under `SHARED_MEDIA_ROOT` and lets the send form reuse a relative path.

## Docker Compose

Copy `.env.example` to `.env`, set `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`, mount the OMW media share on the Docker host, then run:

```bash
docker compose up --build
```

The compose stack includes FastAPI app, Taskiq worker, Taskiq scheduler, Redis, and local Telegram Bot API server.

`telegram-bot-api` uses the documented community image `aiogram/telegram-bot-api:latest` for the official `tdlib/telegram-bot-api` server. Set `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` before starting the stack.

## RNet / Proxmox Deployment

The repository includes a Gitea Actions workflow for the local RNet runner:

```text
.gitea/workflows/ci-deploy.yml
```

It runs tests on the `python` runner label, then deploys `main` to Proxmox LXC `103` named `tg-bots` through `pve-deploy`. The deploy job also updates nginx-ui CT `112` so `tg.sh-inc.ru` and `tg.sh-inc.dev` proxy to the deployed app.

Deployment details and manual commands are documented in:

```text
docs/deployment/rnet-proxmox.md
```

## Diagnostic Polling Bot

The product includes one dashboard-managed diagnostic bot. Add its token on the Bots tab, then open the Diagnostics tab and select that bot. The setting is stored in SQLite and exposed through:

```text
GET /api/v1/diagnostics/bot
PATCH /api/v1/diagnostics/bot
```

The dedicated `diagnostic-bot` compose service runs `python -m tg_bot_aggregator.diagnostics.bot`, reads the selected bot from the database, calls `getUpdates`, and replies to every received or forwarded message with a readable report. Forum topics are detected through `message_thread_id` and replies are sent back to the same topic. Important IDs are exposed as Telegram copy buttons where the client supports `copy_text`.

Each diagnostic update is also stored as compact metadata and can be converted into a saved destination from the dashboard:

```text
GET /api/v1/diagnostics/updates
POST /api/v1/diagnostics/updates/{update_id}/destination
```

Run one local polling iteration without starting the infinite loop:

```bash
python -m tg_bot_aggregator.diagnostics.bot --once
```

## Discovery Polling Bot

Discovery is a separate opt-in polling domain. It exists only to register chats where managed bots are added or promoted. It listens to:

```text
allowed_updates=["my_chat_member"]
```

It does not process message bodies. Enable it per bot from the Discovery tab or through:

```text
GET /api/v1/discovery/bots
PATCH /api/v1/discovery/bots/{bot_id}
GET /api/v1/discovery/events
```

The dedicated `discovery-bot` compose service runs `python -m tg_bot_aggregator.discovery.bot`.

## Audit

Recent operational events are visible in the Audit tab and through:

```text
GET /api/v1/audit
```

Audit metadata is secret-redacted before storage.

## MCP Workflow Tools

The MCP server exposes the same workflow layer used by REST/UI:

```text
list_media
list_send_profiles
create_send_profile
list_send_batches
create_send_batch
preview_send_batch
enqueue_send_batch
cancel_send_batch
list_diagnostic_updates
create_destination_from_diagnostic_update
get_mcp_connection_info
```

MCP tools share the same path validation, token redaction, send history recording, and protected-host API token policy as REST.

## Telegram Ops

The Telegram Ops dashboard turns discovery and diagnostic facts into operational recommendations. Facts, recommendations, preview, apply, and auto-apply are separate steps so the system can explain what it knows before changing anything.

Auto-apply is limited to low-risk reversible actions. It never sends messages, restores backups, enables secret backups, changes protected hosts, expands API-token scopes, enables write MCP tools, or deletes data.

REST endpoints live under `/api/v1/ops`. MCP tools include:

```text
list_ops_facts
list_ops_recommendations
preview_ops_action
apply_ops_action
list_ops_rules
run_ops_scan
explain_failed_send
get_mcp_coverage_matrix
```

## Validation

```bash
python -m pytest -q
python -m ruff check .
docker compose config
```
