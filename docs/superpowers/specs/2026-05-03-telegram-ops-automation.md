# Telegram Ops Automation Spec

**Date:** 2026-05-03

**Status:** Approved for implementation

**Goal:** Add small operational conveniences around the existing local Telegram bot aggregator without turning the project into a multi-user platform.

## Scope

Version 1 of this increment includes:

- Scoped permanent API tokens.
- Audit events for dashboard/API/MCP actions.
- Idempotent send requests through `Idempotency-Key`.
- Send dry-run endpoints and MCP tool.
- Destination aliases.
- Destination chat check through Bot API.
- Discovery polling runner that auto-registers chats where a managed bot is added or promoted.
- Queued send mode with Taskiq and retry for transient failures.
- Template variables with a small built-in renderer.
- Dashboard affordances for MCP, tokens, aliases, dry-run, discovery, curl copy, and audit.

## Non-Goals

- User accounts, roles, teams, or tenants.
- Complex policy engine.
- Webhooks for discovery.
- Polling message content for discovery.
- File upload through FastAPI.
- Full Telegram Bot API clone beyond the currently supported facade.

## Token Scopes

API tokens store a JSON list of scopes:

- `read`
- `send`
- `mcp_admin`
- `tg_compat`

Protected host requests still require a token for `/api/v1`, `/mcp/v1`, and `/bot...`.
The token is also checked for the operation scope:

- read endpoints require `read`.
- send endpoints require `send`.
- MCP token management and settings require `mcp_admin`.
- Telegram-compatible `/bot...` endpoints require `tg_compat`.

For backward compatibility, tokens created before this migration receive all four scopes.

## Audit

Audit events are stored in `audit_events`.

Tracked fields:

- `id`
- `created_at`
- `source`
- `action`
- `status`
- `api_token_id`
- `host`
- `path`
- `method`
- `entity_type`
- `entity_id`
- `request_id`
- `message`
- `metadata_json`

Secret values are redacted before storage. The dashboard exposes a latest-events list only.

## Idempotency

Send endpoints accept `Idempotency-Key`.

For send endpoints:

- If the same key is seen again, return the original `send_history` row.
- The key is scoped by send operation, bot, chat, destination, thread, media type, text/caption, file reference, and template tag.
- A conflicting reuse of the same key with a different fingerprint returns `409`.

The key is stored on `send_history`.

## Dry-Run

Dry-run endpoints validate and return the computed payload but do not send Telegram requests and do not create `send_history` rows.

Endpoints:

- `POST /api/v1/send/text/dry-run`
- `POST /api/v1/send/template/dry-run`
- `POST /api/v1/send/file/dry-run`

MCP tool:

- `dry_run_send`

## Destination Aliases

Destinations gain optional `alias`.

Rules:

- Alias is optional.
- Alias must be unique per bot when present.
- Alias may be used as `destination_alias` in send and dry-run requests.
- Existing `destination_id` and `chat_id` continue to work.

## Destination Check

Endpoint:

- `POST /api/v1/destinations/{destination_id}/check`

The app calls:

- `getChat`
- `getChatMemberCount` when available

It stores returned title, username, kind, and active state where useful, and returns raw non-secret check metadata.

## Discovery Runner

A separate service discovers chats where managed bots are added or promoted.

Data:

- `bot_discovery_settings`
- `bot_discovery_events`

Behavior:

- Settings are per bot.
- Disabled by default.
- Uses `getUpdates` with `allowed_updates=["my_chat_member"]`.
- Deletes webhook on initialize with `drop_pending_updates=false`.
- Stores `last_update_id`.
- Upserts destinations from `my_chat_member.chat`.
- Does not process message bodies.

Docker Compose adds a `discovery-bot` service.

## Queue And Retry

Send requests accept `send_mode`:

- `sync` default
- `queued`

Queued sends create a `send_history` row with status `queued`, enqueue a Taskiq task, then worker sends it.

Retry rules:

- Retry up to `SEND_RETRY_MAX_ATTEMPTS`, default `3`.
- Retry Telegram `429`, `5xx`, and network errors represented as `error_code=None`.
- Do not retry validation errors or Telegram `4xx` except `429`.

## Template Variables

Template requests accept `variables`.

Supported placeholders:

- `{{name}}` for keys in `variables`
- `{{date}}`
- `{{time}}`
- `{{datetime}}`

Missing variables fail validation. The renderer does not evaluate expressions.

## Dashboard

Dashboard additions stay compact:

- token scopes checkboxes
- destination alias field
- destination check button
- send dry-run button
- send mode segmented control
- discovery toggle/status per bot
- audit list
- copy curl buttons for REST and `/bot...` facade

