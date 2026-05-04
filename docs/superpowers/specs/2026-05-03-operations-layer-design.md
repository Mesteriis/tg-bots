# Telegram Operations Layer Design

**Date:** 2026-05-03

**Goal:** Add operational controls around the existing Telegram send hub without turning it into a CRM, inbox, or marketing platform.

## Scope

Version 1 adds:

- Runtime settings editable from the dashboard and applied to the running FastAPI process without restart.
- Send preflight checks.
- Simple send policies.
- Destination health snapshots.
- Dead-letter view for failed sends.
- Scheduled queued sends.
- Batch progress counters.
- Outbound callbacks for send results.
- Template version history and rollback.
- JSON backup export to a configured git repository.

Out of scope:

- Inbound message inbox.
- Content calendar product.
- Video transcoding.
- Userbot sending.
- Role-based auth.
- Complex campaign analytics.

## Architecture

All additions stay inside the current send/control domain:

- Runtime configuration lives in SQLite and overlays the environment settings at request time.
- Send behavior still flows through `SendService`.
- Preflight reuses dry-run validation and adds non-sending checks.
- Destination health is a separate table, not new columns on `destinations`, to avoid existing SQLite schema drift.
- Template versions are append-only rows linked to templates.
- Backups export current persisted configuration to JSON and optionally commit/push it through git.

## Runtime Settings

`runtime_settings` is a single-row table. Settings editable without restart:

- `telegram_bot_api_base_url`
- `shared_media_root`
- `shared_media_require_mount`
- `max_local_file_bytes`
- `send_retry_max_attempts`
- `send_retry_delay_seconds`
- `policy_enabled`
- `rate_limit_per_minute`
- `quiet_hours_start`
- `quiet_hours_end`
- `callback_enabled`
- `callback_url`
- `backup_git_repo_url`
- `backup_git_branch`
- `backup_git_path`
- `backup_include_secrets`

Applying settings updates both the DB row and `app.state.settings`/`app.state.bot_api_client` for the current process.

## Send Operations

Preflight returns structured checks:

- bot exists and active
- destination/chat target resolved
- template variables render
- file path/local Bot API rules
- destination health warning if known bad
- policy warnings/errors

Policies are deliberately simple:

- optional per-bot max sends per minute
- optional quiet hours
- file size still uses `MAX_LOCAL_FILE_BYTES`

Scheduled sends use queued `send_history` rows with `next_retry_at` as the due timestamp. Due rows can be listed and processed by API/task.

Dead-letter is a read view over failed send history rows.

## Backup

The backup service exports JSON with:

- bots
- destinations
- templates
- send profiles
- MCP settings
- discovery settings
- diagnostic settings
- runtime settings

Secrets are excluded unless `backup_include_secrets=true`. If a git repo URL is configured, the service clones or reuses a local worktree, writes JSON under `backup_git_path`, commits, and pushes. Git is executed with argument lists only, never through shell.

## UI

The dashboard adds one operational section:

- Runtime config form.
- Preflight button in Send.
- Failed sends/dead-letter table in History.
- Destination health in Destinations.
- Template versions in Templates.
- Backup settings and run button in Health/Operations.

## Risks

- Hot settings affect the FastAPI process immediately, but already running worker processes only pick them up when task code loads runtime settings from DB.
- Git backup with secrets is dangerous; it is explicit opt-in.
- Scheduled sends need a scheduler/worker loop in deployment for hands-free execution.
