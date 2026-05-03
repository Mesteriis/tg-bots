# Send Reliability Layer Design

**Date:** 2026-05-03

**Status:** Approved design draft

**Goal:** Add a reliability layer for Telegram sends so queued, scheduled, batch, and manual sends are processed with explicit rate limits, backoff, leases, retry budgets, dead-letter handling, and a live graph dashboard, without removing or hiding any existing dashboard functionality.

## Context

The project already has:

- Async FastAPI REST API under `/api/v1`.
- Vue 3 CDN dashboard.
- SQLite persistence with additive schema creation and Alembic migrations.
- Telegram Bot API send-only flow through `SendService`.
- `send_history` as the source of truth for sends.
- Taskiq and Redis for background send execution.
- Basic queued sends, scheduled sends, retry, cancel, due history, and dead-letter lists.
- Batch sends through the workflow layer.
- Runtime settings editable from the dashboard.
- SSE events for dashboard refresh.
- MCP tools that share the same send services as REST.

This design extends the existing send path. It must not create a second sender, a second history table for canonical state, or a parallel delivery engine.

## Product Boundary

This increment is about reliable Telegram delivery operations.

It must not introduce:

- Marketing campaigns.
- CRM segments.
- Multi-user approvals.
- Tenant isolation.
- SLA contracts.
- External alerting platforms.
- Message polling for ordinary managed sender bots.
- Arbitrary file upload through FastAPI.

It may add operational controls that are directly tied to sending reliability.

## Non-Loss Requirement

The current dashboard functionality must remain available.

The UI may be rearranged, but it must preserve access to:

- Bots.
- Destinations.
- Templates and template validation/versioning.
- Text, template, and file sends.
- Send profiles.
- Send batches.
- History, due rows, dead-letter rows, retry, and cancel.
- MTProto.
- Analytics.
- Diagnostics.
- Discovery.
- MCP settings, MCP tokens, and API tokens.
- Audit.
- Runtime operations, backup, restore, and health.
- Shared media browser.

The new reliability view is a higher-level operational lens. It does not replace the detailed tables. Every graph node must drill down to existing or equivalent table data.

## Architecture

The reliability layer adds three application services around the existing send path:

### `SendPolicyService`

Responsibilities:

- Decide whether a send can execute now.
- Classify failures as retryable, blocked, or terminal.
- Compute retry/backoff decisions.
- Respect runtime settings for retry budget, rate limits, quiet hours, and policy enablement.
- Return structured decisions, not HTTP responses.

Dependencies:

- `Settings`
- `SendHistoryRepository`
- `DestinationRepository`
- `BotRepository`
- `SharedPath` validation where file availability affects sendability

### `SendRateLimiter`

Responsibilities:

- Track fast counters and cooldowns in Redis.
- Enforce global, per-bot, per-chat, and per-destination buckets.
- Store cooldown after Telegram `429` and `retry_after`.
- Provide bucket snapshots for API/UI/MCP.

Redis is the preferred counter backend. If Redis is unavailable, the service falls back to conservative SQLite counts from `send_history` and reports degraded mode through health and the reliability API.

### `SendQueueService`

Responsibilities:

- Select due rows.
- Acquire a lease before a worker sends a row.
- Release or expire stale leases.
- Move retryable failures back to deferred/queued with `next_retry_at`.
- Move exhausted rows to dead-letter.
- Publish reliability SSE events.

The actual Telegram call remains in `SendService`.

Dependency direction:

```text
REST / MCP / Dashboard
  -> Reliability and workflow services
  -> SendService / repositories / rate limiter
  -> Telegram Bot API client / Redis / SQLite
```

Route handlers stay thin. Business rules do not move into the Vue UI or API routers.

## Send State Model

Existing states remain valid:

- `created`
- `queued`
- `sending`
- `succeeded`
- `failed`
- `cancelled`

New states:

- `deferred`: the send is delayed by policy, cooldown, or Telegram backoff and has a future `next_retry_at`.
- `dead_letter`: automatic attempts are exhausted; manual retry is allowed.
- `blocked`: automatic retry will not help until a user changes something, such as bot state, destination access, or file availability.

State transitions:

```text
created -> sending -> succeeded
created -> sending -> failed
created -> queued
queued -> sending
queued -> deferred
queued -> cancelled
deferred -> queued
deferred -> sending
sending -> succeeded
sending -> deferred
sending -> dead_letter
sending -> blocked
sending -> failed
dead_letter -> queued
blocked -> queued
```

`failed` remains supported for backwards compatibility and existing API consumers. New automatic terminal failure should prefer `dead_letter` or `blocked` when the reason is known.

## Database Changes

Extend `send_history` additively:

- `priority integer not null default 100`
- `locked_at datetime null`
- `locked_by string null`
- `lock_expires_at datetime null`
- `last_attempt_at datetime null`
- `retry_after_seconds integer null`
- `last_error_kind string null`
- `dedupe_window_key string null`

Keep `next_retry_at`, `attempt_count`, `queued_task_id`, `error_code`, and `error_message`.

Add table `send_attempts`:

- `id`
- `send_history_id`
- `attempt_number`
- `worker_id`
- `started_at`
- `finished_at`
- `status`
- `telegram_error_code`
- `error_kind`
- `error_message`
- `retry_after_seconds`
- `latency_ms`
- `response_payload_json`

Rules:

- `send_history` remains the current canonical state.
- `send_attempts` is append-only diagnostic history.
- Secret redaction applies before storing response payloads.
- Failed attempts must be visible even if a later attempt succeeds.

## Rate Limits And Backoff

Rate limit dimensions:

- Global send rate.
- Per bot.
- Per chat.
- Per destination.
- Per forum topic when `message_thread_id` is present.

Runtime settings:

- `reliability_enabled`
- `send_default_mode`: `sync`, `queued`, or `auto`
- `send_global_rate_per_minute`
- `send_bot_rate_per_minute`
- `send_chat_rate_per_minute`
- `send_destination_rate_per_minute`
- `send_retry_max_attempts`
- `send_retry_base_delay_seconds`
- `send_retry_max_delay_seconds`
- `send_worker_lease_seconds`
- `send_stale_lock_grace_seconds`
- `send_dedupe_window_seconds`

Backoff rules:

- Telegram `429` with `retry_after`: use Telegram value as the minimum delay, set `retry_after_seconds`, and move to `deferred`.
- Telegram `429` without `retry_after`: use configured exponential backoff with jitter.
- Telegram `5xx` and network failures: exponential backoff with jitter while retry budget remains.
- Validation failures, missing files, inactive bots, and destination access problems: move to `blocked`.
- Non-retryable Telegram `4xx`: move to `blocked` or `dead_letter` depending on whether user action can fix it.
- Exhausted retry budget: move to `dead_letter`.

No worker should sleep inside a long retry loop. Retryable failures should update `next_retry_at`, release the lease, and let the scheduler pick the row later.

## Lease Behavior

Before sending, a worker must acquire a lease:

- Row must be due.
- Row must not be terminal.
- Existing lease must be missing or expired.
- Acquiring the lease sets `status=sending`, `locked_at`, `locked_by`, and `lock_expires_at`.

After success:

- Set `succeeded`, clear lease fields, write Telegram message id and response payload.

After retryable failure:

- Write `send_attempts`.
- Set `deferred`, `next_retry_at`, `retry_after_seconds`, `last_error_kind`, and clear lease fields.

After terminal failure:

- Write `send_attempts`.
- Set `dead_letter` or `blocked`, clear lease fields, and preserve the last error.

Stale locks:

- API/UI exposes stale lock count.
- A manual action can release stale locks.
- Releasing a stale lock records an audit event.

## Dashboard Design

Add a `Надежность` view or merge the top of `История` into a reliability console.

Primary UI is the selected visual model: **Live Flow Graph**.

Graph nodes:

- `Batch / Manual`
- `Queue`
- `Policy gate`
- `Worker lease`
- `Bot bucket`
- `Chat bucket`
- `Telegram`
- `Result`

Graph edge colors:

- Blue: normal active flow.
- Yellow: deferred, cooldown, retry, or rate limit.
- Red: blocked, dead-letter, or terminal failure.

Graph animation:

- Driven by real SSE events.
- Edges animate only when there is recent activity.
- The graph must remain readable without animation.
- No existing table data is hidden behind animation-only affordances.

Drill-down:

- Clicking `Queue` shows ready, scheduled, due, and deferred rows.
- Clicking `Policy gate` shows policy decisions and blocked reasons.
- Clicking `Worker lease` shows sending rows and stale locks.
- Clicking `Bot bucket` shows per-bot counters, cooldowns, and recent sends.
- Clicking `Chat bucket` shows per-chat and per-topic counters.
- Clicking `Telegram` shows latest response/error groups.
- Clicking `Result` shows succeeded, dead-letter, blocked, and cancelled rows.
- Clicking a batch shows existing batch progress and items.

Actions:

- Retry selected dead-letter rows.
- Retry selected blocked rows after validation passes.
- Cancel selected queued/deferred rows.
- Release stale locks.
- Open source bot/destination/template/history records.

## REST API

Add endpoints under `/api/v1/reliability`:

- `GET /api/v1/reliability/summary`
- `GET /api/v1/reliability/graph`
- `GET /api/v1/reliability/buckets`
- `GET /api/v1/reliability/attempts`
- `GET /api/v1/reliability/stale-locks`
- `POST /api/v1/reliability/stale-locks/release`
- `POST /api/v1/reliability/send-history/{send_history_id}/retry`
- `POST /api/v1/reliability/send-history/bulk-retry`
- `POST /api/v1/reliability/send-history/bulk-cancel`

Existing endpoints remain:

- `/api/v1/send/*`
- `/api/v1/send-history`
- `/api/v1/send-history/dead-letter`
- `/api/v1/send-history/due`
- `/api/v1/send-batches/*`

Existing response models may receive additive fields only.

## SSE Events

Add events:

- `send.deferred`
- `send.dead_letter`
- `send.blocked`
- `send.locked`
- `send.released`
- `send.retry_scheduled`
- `reliability.bucket.updated`
- `reliability.graph.updated`

Payloads include:

- `schema_version`
- `event_type`
- `send_history_id` when applicable
- `bot_id` when applicable
- `destination_id` when applicable
- `bucket_key` when applicable
- `status`
- `next_retry_at` when applicable

Existing clients that ignore unknown events continue to work.

## MCP

Add MCP tools:

- `get_reliability_summary`
- `get_reliability_graph`
- `list_send_attempts`
- `list_rate_limit_buckets`
- `release_stale_send_locks`
- `bulk_retry_sends`
- `bulk_cancel_sends`

Tool availability is controlled through existing MCP settings.

MCP tools must share the same services as REST. They must not bypass rate-limit, lease, redaction, audit, or history rules.

## Error Handling

Every failure must be classified:

- `telegram_rate_limit`
- `telegram_server`
- `telegram_client`
- `network`
- `policy`
- `validation`
- `file`
- `bot`
- `destination`
- `unknown`

Unknown errors are allowed but must be visible in UI, attempts, and logs. They must not be silently swallowed.

Bot tokens and API tokens must never appear in SSE events, dashboard payloads, logs, `send_attempts`, or stored response payloads.

## Testing Strategy

Unit tests:

- Policy decisions for active/inactive bot, file missing, destination missing, quiet hours, and rate limits.
- Backoff calculation for `429`, `5xx`, network errors, and exhausted retry budget.
- Lease acquisition and stale lease release.
- Redis degraded fallback using SQLite counts.
- Error classification.
- Secret redaction in attempts and SSE payloads.

Integration tests:

- Queued send moves `queued -> sending -> succeeded`.
- Telegram `429 retry_after` moves `sending -> deferred` with `next_retry_at`.
- Due deferred send is retried later.
- Exhausted attempts move to `dead_letter`.
- Validation failure moves to `blocked`.
- Two workers cannot process the same row while a lease is active.
- Bulk retry and bulk cancel affect only allowed states.
- Existing send endpoints still return compatible responses.

Static/UI tests:

- `Надежность` view exists.
- Live graph nodes are present.
- Existing dashboard tabs and controls remain present.
- Drill-down tables expose current history/due/dead-letter/batch data.
- File send controls still disable when shared media is unavailable.

Manual validation:

- Start local server.
- Create bot and destination.
- Send sync text.
- Send queued text.
- Trigger a mocked or forced retryable error.
- Confirm graph receives SSE updates.
- Confirm existing History tab still works.
- Confirm MCP `get_reliability_summary` returns expected data.

## Migration And Rollout

Rollout is additive:

1. Add schema fields and `send_attempts`.
2. Add services and tests while preserving current send behavior.
3. Switch queued processing to lease/backoff flow.
4. Add reliability REST/MCP/SSE.
5. Add dashboard graph and drill-down.
6. Keep old history tables visible until the new view proves complete.

`reliability_enabled` defaults to `false` for safest migration if existing local databases may rely on current immediate retry behavior. After validation, the dashboard can offer a one-click enable action.

## Open Decisions

No blocking product decisions remain.

Implementation may choose the exact graph rendering approach:

- CSS/SVG graph inside the Vue CDN app.
- Canvas-based graph if performance becomes an issue.

The first implementation should prefer SVG/CSS because the graph is small, inspectable, and easy to test.

## Design Self-Review

Spec coverage:

- Reliability scope is focused on Telegram send delivery.
- Existing dashboard functionality preservation is explicit.
- Architecture builds on `SendService`, `send_history`, Taskiq, Redis, and SQLite.
- State transitions are defined.
- DB additions are additive.
- REST, SSE, MCP, dashboard, error handling, and tests are covered.

Placeholder scan:

- No required section contains placeholder text.

Consistency check:

- New endpoints are consistently under `/api/v1/reliability`.
- New MCP tools share REST services.
- `send_history` remains the canonical current state.
- `send_attempts` is append-only diagnostics.

Scope check:

- The design does not introduce campaigns, CRM, tenants, or unrelated operational systems.
