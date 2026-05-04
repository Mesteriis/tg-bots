# Telegram Workflow Layer Design

**Date:** 2026-05-03

**Status:** Approved for implementation

**Goal:** Add a workflow layer on top of the existing local Telegram bot aggregator so repeated sending, file selection, previews, batch sends, retries, and diagnostics-driven setup become convenient without turning the project into a corporate CRM.

## Context

The project already has:

- FastAPI REST API under `/api/v1`.
- Vue 3 CDN dashboard.
- SQLite persistence with Alembic.
- Bot, destination, template, send history, audit, API token, MCP, diagnostics, and discovery domains.
- Send-only Telegram Bot API behavior for normal bots.
- A dedicated polling diagnostics bot.
- Discovery polling for `my_chat_member`.
- Taskiq/Redis queued sending with retry.
- Telegram-compatible `/bot{token}/...` facade.

This increment builds on those existing seams instead of replacing them.

## Product Boundary

The workflow layer is still a local operations tool.

It must not introduce:

- User accounts.
- Roles or teams.
- Tenant isolation.
- Approval workflows.
- CRM segments.
- Marketing campaign analytics.
- Arbitrary file upload through FastAPI.
- File delete/move/rename APIs.
- Message polling for managed sender bots.

It may introduce lightweight workflow objects where they reduce repetitive manual input.

## Main Concepts

### Media Browser

The app exposes a read-only media browser for `SHARED_MEDIA_ROOT`.

REST endpoints:

- `GET /api/v1/media`
- `GET /api/v1/media/tree`

Behavior:

- Accepts an optional relative directory path.
- Rejects absolute paths and traversal.
- Lists direct children only by default.
- Returns directories and regular files with:
  - relative path
  - name
  - kind: `directory` or `file`
  - size for files
  - modified time
  - detected media type hint: `video`, `document`, or `unknown`
- Does not read file contents.
- Does not create copies.
- Does not expose host paths.
- Does not follow symlink escapes outside shared root.

Dashboard behavior:

- Add a file picker panel inside the send workflow.
- Selecting a file fills `forms.file.file_relative_path`.
- The picker is read-only.

### Send Profiles

Send profiles store reusable defaults for common operations.

Table: `send_profiles`

Fields:

- `id`
- `name`
- `bot_id`
- `destination_id`
- `destination_alias`
- `template_tag`
- `parse_mode`
- `disable_web_page_preview`
- `send_mode`
- `default_tag`
- `default_variables_json`
- `default_caption`
- `is_active`
- `created_at`
- `updated_at`

Rules:

- A profile may target either `destination_id`, `destination_alias`, or manual `chat_id` supplied at send time.
- A profile may reference a template by tag.
- Profiles are defaults, not separate permissions.
- Sending still goes through `SendService`.

REST endpoints:

- `GET /api/v1/send-profiles`
- `POST /api/v1/send-profiles`
- `GET /api/v1/send-profiles/{profile_id}`
- `PATCH /api/v1/send-profiles/{profile_id}`
- `DELETE /api/v1/send-profiles/{profile_id}`

MCP tools:

- `list_send_profiles`
- `create_send_profile`

Dashboard behavior:

- Add a `Профили` section.
- A profile can be applied to text, template, file, or batch send forms.

### Message Preview

Preview is a first-class workflow action.

Existing dry-run behavior remains the execution backend.

REST endpoints:

- Keep existing `/send/*/dry-run`.
- Add `POST /api/v1/send/preview` as a unified convenience endpoint.

Preview output includes:

- send kind: `text`, `template`, or `file`
- resolved bot
- resolved destination
- resolved chat ID
- resolved thread ID
- rendered text or caption
- file metadata when present
- Telegram method
- Telegram payload
- warnings

Preview must not create `send_history`.

Dashboard behavior:

- Show a compact preview card before actual send.
- Preview works for single sends and batch sends.

### Batch Sends

Batch sends are lightweight groups of normal send attempts.

Tables:

- `send_batches`
- `send_batch_items`

`send_batches` fields:

- `id`
- `name`
- `kind`: `text`, `template`, or `file`
- `status`: `draft`, `queued`, `running`, `finished`, `failed`, `cancelled`
- `bot_id`
- `template_tag`
- `text`
- `caption`
- `media_type`
- `file_relative_path`
- `variables_json`
- `send_mode`
- `created_at`
- `updated_at`
- `started_at`
- `finished_at`

`send_batch_items` fields:

- `id`
- `batch_id`
- `destination_id`
- `destination_alias`
- `chat_id`
- `message_thread_id`
- `send_history_id`
- `status`: `pending`, `queued`, `sending`, `succeeded`, `failed`, `cancelled`
- `error_message`
- `created_at`
- `updated_at`

Rules:

- Each batch item becomes a normal `send_history` row.
- Existing send validation, file validation, template rendering, token redaction, events, and retry rules apply.
- Batch sending must be bounded and explicit.
- No hidden recurring schedules in this increment.
- Batch cancellation only cancels items that are not already sending or succeeded.

REST endpoints:

- `GET /api/v1/send-batches`
- `POST /api/v1/send-batches`
- `GET /api/v1/send-batches/{batch_id}`
- `POST /api/v1/send-batches/{batch_id}/preview`
- `POST /api/v1/send-batches/{batch_id}/enqueue`
- `POST /api/v1/send-batches/{batch_id}/cancel`

MCP tools:

- `list_send_batches`
- `create_send_batch`
- `preview_send_batch`
- `enqueue_send_batch`

Dashboard behavior:

- Add a `Массовая` workflow tab.
- User selects multiple saved destinations.
- The result table shows one row per destination with status and error.

### Retry And Cancel Controls

Existing queued send and retry behavior remains the execution primitive.

Additional REST endpoints:

- `POST /api/v1/send-history/{send_history_id}/retry`
- `POST /api/v1/send-history/{send_history_id}/cancel`

Rules:

- Retry is allowed for `failed` rows and reuses the recorded request payload.
- Cancel is allowed for `queued` rows that have not reached active sending.
- Succeeded rows cannot be retried or cancelled.
- Failed retry creates a new attempt count on the same send history row, not a duplicate row.

Dashboard behavior:

- History rows show retry/cancel actions when allowed.
- Batch item rows link back to send history.

### Diagnostics To Destination

The diagnostics bot should become a setup assistant.

Persistence:

- Add `diagnostic_updates`.

Fields:

- `id`
- `update_id`
- `chat_id`
- `message_id`
- `message_thread_id`
- `chat_type`
- `chat_title`
- `chat_username`
- `sender_id`
- `sender_username`
- `summary_text`
- `raw_update_json`
- `created_at`

Behavior:

- Diagnostics polling stores a compact extracted record for supported message updates.
- The bot still replies with the formatted diagnostic report.
- The dashboard can create a destination from a diagnostic update.

REST endpoints:

- `GET /api/v1/diagnostics/updates`
- `POST /api/v1/diagnostics/updates/{update_id}/create-destination`

Rules:

- Creation requires selected `bot_id`.
- Forum `message_thread_id` is preserved.
- Existing destination upsert behavior prevents duplicates.

MCP tools:

- `list_diagnostic_updates`
- `create_destination_from_diagnostic_update`

### MCP Connection Helper

The dashboard should make MCP setup copyable.

REST endpoint:

- `GET /api/v1/mcp/connection-info`

Output:

- streamable HTTP URL
- legacy SSE URL
- legacy messages URL
- protected hosts
- required headers
- enabled tools
- examples for local and `tg.*` hosts

MCP tool:

- `get_mcp_connection_info`

Dashboard behavior:

- MCP tab shows copy buttons for URLs and JSON snippets.

### Favicon And App Metadata

Add a small static favicon endpoint or inline icon asset to remove browser console noise.

Routes:

- `GET /favicon.ico`

This is a polish item and does not affect API behavior.

## Architecture

New modules:

- `media_browser.py`
- `workflow_service.py`
- `api/media.py`
- `api/send_profiles.py`
- `api/send_batches.py`

Existing modules extended:

- `send_service.py`
- `repositories.py`
- `models.py`
- `schemas.py`
- `diagnostics/bot.py`
- `diagnostics/formatter.py`
- `mcp_catalog.py`
- `mcp_server.py`
- `static/index.html`

Dependency direction remains:

```text
API / MCP / UI
  -> workflow and send services
  -> repositories
  -> SQLAlchemy models and Telegram Bot API client
```

API handlers must stay thin.

## Events

Add SSE event types:

- `media.browser.error`
- `send.profile.created`
- `send.profile.updated`
- `send.batch.created`
- `send.batch.queued`
- `send.batch.item.updated`
- `send.batch.finished`
- `send.retry.queued`
- `send.cancelled`
- `diagnostics.update.created`
- `destination.created_from_diagnostic`

Payloads keep `schema_version: "v1"`.

## Security And Safety

Required constraints:

- Media browser is read-only.
- Media browser accepts relative paths only.
- No file content streaming through FastAPI.
- No delete/move/rename operations.
- No shell execution from path inputs.
- Batch send uses saved destinations or explicit chat IDs only.
- API tokens and bot tokens are never emitted through events, logs, or preview payloads.
- Protected host token checks continue to apply.

## Testing Strategy

Unit tests:

- Media path listing and traversal rejection.
- Send profile repository and validation.
- Batch creation, preview, enqueue, cancellation, and retry state transitions.
- Diagnostic update extraction and destination creation.
- MCP connection-info generation.

Integration tests:

- REST media listing with temporary shared root.
- REST send profile CRUD.
- REST batch lifecycle with mocked Bot API.
- Retry/cancel endpoints.
- Diagnostics update API.
- MCP tool calls.

Static UI tests:

- Dashboard exposes workflow tabs and copyable MCP helper.
- File picker fills file relative path.
- Batch table and history retry/cancel controls exist.

Manual validation:

- Start local server.
- Open dashboard.
- Pick shared file without copying it.
- Create profile.
- Preview single send.
- Create batch with two destinations.
- Enqueue batch.
- Retry a failed item.
- Create destination from diagnostic update.
- Verify MCP connection snippets.
- Verify no `/favicon.ico` 404.

## Implementation Order

1. Media browser and favicon.
2. Send profiles.
3. Unified preview endpoint and UI preview card.
4. Retry/cancel endpoints for existing `send_history`.
5. Batch persistence and batch API.
6. Batch worker integration.
7. Diagnostics update persistence and create-destination action.
8. MCP connection helper and new MCP tools.
9. Dashboard workflow UI.
10. Documentation and full validation.

## Decomposition

This is a large increment. It should be implemented in slices that can pass tests independently:

- Slice A: media browser, favicon, MCP connection helper.
- Slice B: send profiles and unified preview.
- Slice C: retry/cancel and batch send backend.
- Slice D: diagnostics-to-destination.
- Slice E: dashboard workflow UI and MCP tool coverage.

Each slice must preserve a working server.

## Self-Review

Placeholder scan:

- No placeholders or incomplete requirements remain.

Consistency:

- All sends still flow through `SendService`.
- Batch items map back to normal `send_history` rows.
- Media browser stays read-only and no-copy.
- Diagnostics remains the only polling message bot.

Scope:

- The selected option is intentionally larger than the previous recommended compact pass, so it is decomposed into five slices.
- The design excludes users, roles, approvals, tenant isolation, and campaign analytics to avoid enterprise scope creep.

Ambiguity:

- Retry mutates the same `send_history` row rather than creating duplicates.
- Batch cancel only affects pending/queued items.
- Media browser never exposes absolute host paths.
