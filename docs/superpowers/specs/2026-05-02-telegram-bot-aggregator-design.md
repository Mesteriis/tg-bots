# Telegram Bot Aggregator Design

**Date:** 2026-05-02

**Status:** Approved design draft

**Goal:** Build a local async FastAPI service that manages Telegram bot tokens, sends tagged text and media messages to Telegram destinations, exposes REST/UI/MCP interfaces, and collects Telegram analytics through an MTProto user session.

## Scope

The application is send-only for Telegram bots. It does not poll bot updates, register webhooks, or process inbound bot messages.

Version 1 includes:

- Local FastAPI web service with Vue 3 CDN UI.
- SQLite persistence for bots, destinations, message templates, send history, MTProto login state, analytics targets, analytics snapshots, and task runs.
- Plain-text bot token storage in SQLite.
- Async Telegram Bot API client.
- Local Telegram Bot API server in Docker Compose for local-path file sending.
- Shared-media file sending without copying file contents through the FastAPI service.
- Telethon-based MTProto user session for extended analytics.
- Taskiq with Redis for background analytics refresh tasks.
- REST API under `/api/v1`.
- MCP endpoints under `/mcp/v1`.
- Frontend Server-Sent Events under `/api/v1/events`.
- Docker Compose deployment targeting a selected Docker host with access to the existing OMW media share.

Out of scope for version 1:

- Authentication and authorization.
- Bot polling.
- Bot webhooks.
- Inbound message processing.
- Arbitrary file upload through FastAPI.
- Userbot-based message sending.
- Multi-tenant isolation.
- Postgres.
- Celery/RabbitMQ.

## Infrastructure Facts

Repository context:

- Project directory: `/Users/avm/projects/Personal/tg-bots`.
- At design time the directory was empty and was not a git repository.

Discovered infrastructure context:

- PVE host: `192.168.1.2`, `pve-manager/9.1.7`.
- OMW/OMV VM: `111 omw`, IP `192.168.1.23`, hostname `samba`.
- OMW media disk: 500G ext4 disk mounted at `/srv/dev-disk-by-uuid-621250bf-a4b4-4c72-9f16-b376e26fe558`.
- OMV shared folder: `media`.
- NFS export: `192.168.1.23:/export/media` for `192.168.1.0/24`.
- SMB share: `media`, writable, guest allowed.
- No Docker deployment host is fixed by this design.

## Architecture

The system is split into five runtime services:

- `app`: FastAPI ASGI service. Owns REST API, Vue 3 CDN UI, MCP endpoints, frontend SSE, lightweight validation, and task enqueueing.
- `worker`: Taskiq worker. Runs analytics refresh jobs and writes task events.
- `scheduler`: Taskiq scheduler process for periodic analytics refreshes.
- `redis`: Redis broker/result backend and event stream storage.
- `telegram-bot-api`: local Telegram Bot API server running in local mode.

Persistent storage:

- SQLite database in an app data volume.
- Alembic migrations in the repository.
- Telethon session files in an app data volume.
- Local Telegram Bot API server data in a separate volume.
- Shared media mounted read-only into application containers.

Primary dependency direction:

```text
API/UI/MCP
  -> Application services
  -> Domain validation and DTOs
  -> Infrastructure clients and repositories
```

Route handlers should stay thin. They validate request shape, call application services, and return response models. Telegram HTTP calls, Telethon calls, Taskiq enqueueing, path validation, persistence, and event emission should live behind explicit service/repository boundaries.

## Async-First Rule

All runtime I/O must be async:

- FastAPI handlers are `async def`.
- Database access uses SQLAlchemy async with SQLite.
- Telegram Bot API calls use `httpx.AsyncClient`.
- MTProto uses Telethon async client.
- Background jobs are Taskiq async tasks.
- SSE streams use async generators.

No blocking filesystem, network, subprocess, or database operation should run directly in an event loop path unless it is bounded and explicitly pushed to a thread where needed.

## Telegram Bot API

The service sends through Telegram Bot API only. It must not poll updates or configure webhooks.

The default Bot API base URL is the local server:

```text
http://telegram-bot-api:8081
```

The cloud fallback is:

```text
https://api.telegram.org
```

Request construction:

```text
{TELEGRAM_BOT_API_BASE_URL}/bot{token}/{method}
```

Supported send methods in version 1:

- `sendMessage`
- `sendDocument`
- `sendVideo`

Forum topics use `message_thread_id` where provided.

Bot checks use `getMe`.

Destination metadata can be supplemented through Bot API calls such as `getChat` and `getChatMemberCount` when available to the bot. Missing access must be reported as a normal recoverable error, not hidden.

## Local Bot API Server

The Docker Compose stack includes a local Telegram Bot API server in local mode.

Required configuration:

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_BOT_API_BASE_URL=http://telegram-bot-api:8081`

The local server exists mainly to support local-path file uploads and larger file limits than cloud Bot API. It does not remove Telegram-side upload limits.

Known limit:

- Local Bot API mode supports uploads up to 2000 MB.

If `TELEGRAM_BOT_API_BASE_URL` points to the cloud Bot API, file-path sending must be disabled because Telegram cloud cannot read LAN/local paths.

## Shared Media Flow

The application does not accept large file bodies.

Expected flow:

1. An external uploader writes a video/file into the OMW `media` share.
2. The app receives a send request containing a relative path under the shared root.
3. The app validates the path and records the send attempt.
4. The app calls the local Bot API server with a local file URI or local file path visible to the `telegram-bot-api` container.
5. The app records Telegram response data or error details.
6. The frontend receives live status through `/api/v1/events`.

Recommended host/container paths:

```text
NFS source:      192.168.1.23:/export/media
Docker host path: /mnt/omw-media
Container path:  /shared/media
```

The same container path must be mounted into:

- `app`
- `worker`
- `telegram-bot-api`

The request API accepts a relative path, not an absolute host path:

```json
{
  "bot_id": 1,
  "destination_id": 10,
  "tag": "release_video",
  "caption": "Release video",
  "media_type": "video",
  "file_relative_path": "telegram-outbox/release.mp4"
}
```

Canonical path resolution:

```text
/shared/media/telegram-outbox/release.mp4
```

Validation rules:

- Resolve the final path.
- Reject absolute input paths.
- Reject `..` traversal.
- Reject symlinks that escape `/shared/media`.
- Require an existing regular file.
- Require readable file permissions from the container.
- Reject file sizes above configured maximum, defaulting to `2000 MB`.
- Reject local-file sends when the Bot API base URL is not local.

The app must not copy file contents to its own data volume and must not proxy the file as multipart data through FastAPI.

## Database Model

SQLite is the version 1 database.

Migrations are managed with Alembic.

Tables:

### `bots`

Stores Telegram bot records.

Fields:

- `id`
- `name`
- `token`
- `username`
- `telegram_bot_id`
- `description`
- `is_active`
- `created_at`
- `updated_at`
- `last_checked_at`

Token storage is plain text by explicit product decision.

### `destinations`

Stores saved Telegram targets.

Fields:

- `id`
- `bot_id`
- `kind`
- `chat_id`
- `message_thread_id`
- `title`
- `username`
- `is_active`
- `created_at`
- `updated_at`

Allowed `kind` values:

- `private`
- `group`
- `supergroup`
- `channel`
- `forum_topic`

### `message_templates`

Stores reusable tagged messages.

Fields:

- `id`
- `tag`
- `title`
- `text`
- `parse_mode`
- `disable_web_page_preview`
- `created_at`
- `updated_at`

`tag` is unique.

### `send_history`

Stores every send attempt.

Fields:

- `id`
- `bot_id`
- `destination_id`
- `chat_id`
- `message_thread_id`
- `tag`
- `text`
- `media_type`
- `file_relative_path`
- `file_size_bytes`
- `telegram_message_id`
- `status`
- `error_code`
- `error_message`
- `request_payload_json`
- `response_payload_json`
- `created_at`
- `sent_at`
- `failed_at`

Allowed `status` values:

- `created`
- `succeeded`
- `failed`

Allowed `media_type` values:

- `none`
- `document`
- `video`

### `mtproto_sessions`

Stores MTProto login state metadata and session references.

Fields:

- `id`
- `session_name`
- `phone`
- `status`
- `created_at`
- `updated_at`
- `last_connected_at`
- `last_error`

Allowed `status` values:

- `missing`
- `code_requested`
- `password_required`
- `ready`
- `failed`

Telethon session files are stored in the configured app data volume, not inside random globals.

### `analytics_targets`

Stores chats/channels selected for analytics.

Fields:

- `id`
- `peer_ref`
- `title`
- `username`
- `kind`
- `is_active`
- `refresh_interval_seconds`
- `created_at`
- `updated_at`
- `last_snapshot_at`

`peer_ref` is the Telethon-resolvable chat reference, such as username, invite-resolved ID, or numeric peer ID.

### `analytics_snapshots`

Stores point-in-time metrics.

Fields:

- `id`
- `target_id`
- `captured_at`
- `participants_count`
- `recent_messages_count`
- `recent_views_total`
- `recent_forwards_total`
- `recent_replies_total`
- `raw_metrics_json`

Missing metrics must be represented as `NULL`, not `0`, when Telegram does not expose them.

### `analytics_runs`

Tracks Taskiq jobs.

Fields:

- `id`
- `task_id`
- `target_id`
- `status`
- `started_at`
- `finished_at`
- `error_message`
- `snapshots_created`

Allowed `status` values:

- `queued`
- `started`
- `finished`
- `failed`

## REST API Version 1

All REST endpoints are under:

```text
/api/v1
```

Bot endpoints:

- `GET /api/v1/bots`
- `POST /api/v1/bots`
- `GET /api/v1/bots/{bot_id}`
- `PATCH /api/v1/bots/{bot_id}`
- `DELETE /api/v1/bots/{bot_id}`
- `POST /api/v1/bots/{bot_id}/check`

Destination endpoints:

- `GET /api/v1/destinations`
- `POST /api/v1/destinations`
- `GET /api/v1/destinations/{destination_id}`
- `PATCH /api/v1/destinations/{destination_id}`
- `DELETE /api/v1/destinations/{destination_id}`

Template endpoints:

- `GET /api/v1/templates`
- `POST /api/v1/templates`
- `GET /api/v1/templates/{template_id}`
- `PATCH /api/v1/templates/{template_id}`
- `DELETE /api/v1/templates/{template_id}`

Send endpoints:

- `POST /api/v1/send/text`
- `POST /api/v1/send/template`
- `POST /api/v1/send/file`
- `GET /api/v1/send-history`

MTProto endpoints:

- `POST /api/v1/mtproto/login/start`
- `POST /api/v1/mtproto/login/confirm-code`
- `POST /api/v1/mtproto/login/confirm-password`
- `GET /api/v1/mtproto/status`

Analytics endpoints:

- `GET /api/v1/analytics/targets`
- `POST /api/v1/analytics/targets`
- `GET /api/v1/analytics/targets/{target_id}`
- `PATCH /api/v1/analytics/targets/{target_id}`
- `DELETE /api/v1/analytics/targets/{target_id}`
- `POST /api/v1/analytics/refresh`
- `GET /api/v1/analytics/runs`
- `GET /api/v1/analytics/snapshots`

Operational endpoints:

- `GET /api/v1/health`
- `GET /api/v1/events`

## Send Behavior

Text sends support:

- Direct text with optional `tag`.
- Template-based text by `tag`.
- Optional `parse_mode`.
- Optional `disable_web_page_preview`.
- Optional `message_thread_id`.

File sends support:

- `document`
- `video`
- optional caption
- optional template caption by tag
- optional `message_thread_id`
- local shared-path file reference

The app records history before calling Telegram, updates status after the call, and emits SSE events for created/succeeded/failed states.

Telegram errors are persisted with response body context after secret redaction. Bot tokens must never be written into logs, SSE events, or API responses.

## MTProto Login

The user explicitly selected web-based MTProto login.

Flow:

1. `POST /api/v1/mtproto/login/start` accepts phone number and requests code through Telethon.
2. `POST /api/v1/mtproto/login/confirm-code` confirms Telegram login code.
3. If Telegram requires 2FA, status becomes `password_required`.
4. `POST /api/v1/mtproto/login/confirm-password` completes login.
5. `GET /api/v1/mtproto/status` reports current state.

Risk:

- Without auth, any LAN client that reaches the app can initiate or complete MTProto login and later use the saved user session. This is accepted for version 1 and must be documented in README and visible in UI.

## Analytics

The analytics layer uses Telethon through the saved MTProto user session.

Version 1 supports:

- Register analytics targets.
- Refresh one target manually.
- Refresh all active targets manually.
- Refresh active targets periodically through Taskiq scheduler.
- Store point-in-time snapshots.
- Show current summary and historical trend in UI.
- Expose analytics refresh and summary through MCP.

Snapshot content:

- chat/channel title
- username where available
- participant/subscriber count where available
- recent message count for configured lookback
- aggregate views where available
- aggregate forwards where available
- aggregate replies where available
- raw metrics JSON for debugging and future migration

Missing Telegram permissions or unavailable metrics must produce partial snapshots with `NULL` values and visible warnings, not failed global refreshes unless the target cannot be resolved at all.

## Taskiq and Redis

Taskiq handles background work.

Tasks:

- `refresh_analytics_target(target_id: int)`
- `refresh_all_analytics_targets()`

Redis responsibilities:

- Taskiq broker.
- Taskiq result backend.
- Frontend SSE event stream.
- Cross-process event fanout from worker to web clients.

Task lifecycle:

1. API creates `analytics_runs` row with `queued`.
2. API enqueues Taskiq task.
3. Worker marks run `started`.
4. Worker collects Telethon metrics.
5. Worker writes `analytics_snapshots`.
6. Worker marks run `finished` or `failed`.
7. Worker emits Redis Stream events for frontend SSE.

Long-running Telethon operations must not run in FastAPI request handlers.

## Frontend UI

The UI is a Vue 3 CDN single-page interface served by FastAPI.

The first screen is the working application, not a landing page.

Views:

- Bots: create/edit/check bots.
- Destinations: manage chats/channels/forum topics.
- Templates: manage tagged message templates.
- Send: send text/template/file from shared path.
- History: inspect send attempts and errors.
- MTProto: login/status.
- Analytics: manage targets, refresh, inspect snapshots/trends.
- Settings/Health: show configured Bot API base URL, shared media root, Redis status, DB status, and local mode warnings.

The UI uses REST for commands and `/api/v1/events` for live updates.

## Frontend SSE

Endpoint:

```text
GET /api/v1/events
```

The endpoint returns `text/event-stream`.

Events include:

- `send.created`
- `send.succeeded`
- `send.failed`
- `analytics.run.queued`
- `analytics.run.started`
- `analytics.run.finished`
- `analytics.run.failed`
- `analytics.snapshot.created`
- `mtproto.login.status_changed`
- `bot.checked`

Each event payload contains:

```json
{
  "schema_version": "v1",
  "event_type": "send.succeeded",
  "data": {}
}
```

`Last-Event-ID` must be supported for reconnect where Redis Stream history still contains the event.

The UI startup sequence:

1. Load current state through REST.
2. Open `EventSource("/api/v1/events")`.
3. Apply events to refresh affected views or invalidate cached lists.

## MCP

MCP is versioned separately from REST.

Modern endpoint:

```text
/mcp/v1
```

Compatibility endpoints:

```text
/mcp/v1/sse
/mcp/v1/messages
```

The modern endpoint uses MCP Streamable HTTP. The compatibility endpoints support older HTTP+SSE clients.

MCP tools:

- `list_bots`
- `list_destinations`
- `list_message_templates`
- `send_text`
- `send_template`
- `send_file_from_shared_path`
- `refresh_analytics`
- `get_analytics_summary`
- `get_send_history`

MCP tools must share the same application services as REST. They must not bypass path validation, token redaction, or history recording.

## Versioning

REST:

- Versioned by URL prefix: `/api/v1`.
- Breaking changes require `/api/v2`.

MCP:

- Versioned by URL prefix: `/mcp/v1`.
- Breaking tool schema changes require `/mcp/v2`.

Frontend SSE:

- Endpoint starts at `/api/v1/events`.
- Payloads include `schema_version`.
- Additive fields are allowed in `v1`.
- Field rename, removal, or type change requires a new schema version.

Database:

- All schema changes go through Alembic migrations.

## Docker Compose Deployment

Compose services:

- `app`
- `worker`
- `scheduler`
- `redis`
- `telegram-bot-api`

Expected environment variables:

- `APP_HOST`
- `APP_PORT`
- `DATABASE_URL`
- `REDIS_URL`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_BOT_API_BASE_URL`
- `SHARED_MEDIA_ROOT`
- `MAX_LOCAL_FILE_BYTES`
- `CORS_ALLOWED_ORIGINS`
- `MCP_ALLOWED_ORIGINS`
- `TELETHON_SESSION_DIR`

Recommended values:

```text
APP_HOST=127.0.0.1
APP_PORT=8000
DATABASE_URL=sqlite+aiosqlite:////data/app.db
REDIS_URL=redis://redis:6379/0
TELEGRAM_BOT_API_BASE_URL=http://telegram-bot-api:8081
SHARED_MEDIA_ROOT=/shared/media
MAX_LOCAL_FILE_BYTES=2097152000
TELETHON_SESSION_DIR=/data/telethon
```

LAN exposure requires explicit override:

```text
APP_HOST=0.0.0.0
```

NFS prep target:

```text
192.168.1.23:/export/media -> /mnt/omw-media -> /shared/media
```

The `/mnt/omw-media` mount must exist on whichever Docker host runs this Compose stack.

## Security Constraints

The product is intentionally unauthenticated for local network use.

Accepted risks:

- LAN clients can read and modify bot records.
- LAN clients can access plain-text bot tokens through app behavior or DB access.
- LAN clients can send messages through configured bots.
- LAN clients can trigger MTProto login and use saved MTProto session behavior exposed by the app.
- LAN clients can trigger analytics refreshes.

Mitigations still required:

- Default bind to `127.0.0.1`.
- Explicit env opt-in for `0.0.0.0`.
- Explicit CORS origins.
- MCP `Origin` validation.
- Token redaction in logs, events, API responses unless an endpoint intentionally returns token for editing.
- Shared-path traversal and symlink escape checks.
- No shell execution from user-provided paths.
- No file deletion API in version 1.
- No recursive directory sending in version 1.

## Testing Strategy

Unit tests:

- Bot API URL and payload construction.
- Token redaction.
- Destination validation.
- Template lookup and direct text send selection.
- Shared path validation.
- Local Bot API requirement for file-path sends.
- SSE event encoding.
- Redis Stream cursor handling.
- Analytics snapshot aggregation with missing metrics.

Integration tests:

- FastAPI REST endpoints with temporary SQLite DB.
- Send services with mocked Bot API HTTP responses.
- Taskiq task execution with test Redis when available.
- MCP tool calls against ASGI app.
- MTProto service behavior with Telethon mocked at the boundary.

Manual validation:

- Start Compose stack.
- Verify `GET /api/v1/health`.
- Create bot.
- Run bot `getMe` check.
- Create destination.
- Send direct text.
- Send template.
- Mount OMW media share.
- Send local file from `/shared/media`.
- Start MTProto login.
- Complete MTProto login.
- Register analytics target.
- Run analytics refresh.
- Verify `/api/v1/events` receives task and send events.
- Call MCP `send_text`.
- Call MCP `refresh_analytics`.

## External References

- Telegram Bot API: https://core.telegram.org/bots/api
- Local Telegram Bot API server: https://tdlib.github.io/telegram-bot-api/
- Telethon documentation: https://docs.telethon.dev/
- Taskiq documentation: https://taskiq-python.github.io/guide/
- Taskiq Redis package: https://github.com/taskiq-python/taskiq-redis
- MCP transport specification: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports

## Open Decisions

There are no blocking open decisions for version 1 implementation planning.

Non-blocking decisions can be made during implementation:

- Exact frontend component layout.
- Exact chart library, if any, for analytics trends.
- Whether `telegram-bot-api` image is built from official source or pinned to a third-party Docker image.
- Which Docker host runs the stack.
- Whether the NFS mount is configured on that Docker host directly or provided by host-level orchestration.

## Design Self-Review

Spec coverage:

- FastAPI and Vue 3 CDN UI are included.
- SQLite token storage is included and explicitly plain text.
- Send-only Bot API behavior is included.
- Groups, channels, private chats, and forum topics are represented through destinations and `message_thread_id`.
- MCP is included with modern and SSE compatibility endpoints.
- Frontend SSE is included.
- API versioning is included.
- Async-first implementation is required.
- MTProto analytics and web login are included.
- Taskiq and Redis are included.
- Local Telegram Bot API server and shared-media no-copy file flow are included.
- PVE/OMW discovered infrastructure is included.

Placeholder scan:

- No required implementation section contains placeholder text.

Type and naming consistency:

- Endpoint prefixes are consistently `/api/v1` and `/mcp/v1`.
- Shared media path is consistently `/shared/media`.
- Deployment media mount is consistently `/mnt/omw-media`.
- Analytics run and snapshot terminology is consistent across database, tasks, REST, SSE, and MCP.

Scope check:

- The project is larger than a trivial sender dashboard, but still one coherent local service because all subsystems serve the same core workflow: manage bots, send messages/files, expose AI tools, and inspect analytics.
