# Telegram Bot Aggregator

Local async FastAPI service for managing Telegram bot tokens, sending tagged text/media messages, exposing MCP tools, and collecting MTProto analytics.

## OSS Status

This repository is distributed under the MIT License. Contributions are welcome through focused issues and pull requests. Do not include bot tokens, API tokens, `.env` files, SQLite databases, or Telethon session files in public reports or commits.

## Security Model

This project is intentionally designed for a trusted local network. Localhost and ordinary LAN access remain unauthenticated. Requests whose `Host`, `X-Forwarded-Host`, or `Origin` matches `PROTECTED_API_HOSTS` require a permanent API token for `/api/v1/*`, `/api/v1/events`, and `/mcp/v1/*`. The default protected hosts are `tg.sh-inc.ru` and `tg.sh-inc.dev`.

Create permanent API tokens from the dashboard MCP tab or through MCP tools while connected locally. Tokens are shown once, stored in SQLite only as hashes, and can be revoked from the dashboard. Tokens have explicit scopes:

```text
read
send
mcp_admin
tg_compat
```

Protected `/bot...` facade calls require `tg_compat`; send endpoints require `send`; read endpoints require `read`; MCP/settings/token administration requires `mcp_admin`.

Bot tokens are stored in SQLite as plain text by product decision. Do not expose the app or database outside the trusted network.

## Development

```bash
python -m pip install -e ".[dev]"
pytest -q
uvicorn tg_bot_aggregator.main:create_app --factory --reload
```

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
POST /api/v1/send/text/dry-run
POST /api/v1/send/template/dry-run
POST /api/v1/send/file/dry-run
```

Requests can use `send_mode=queued` to enqueue through Taskiq/Redis. Transient Telegram errors (`429`, `5xx`, network failures) are retried according to `SEND_RETRY_MAX_ATTEMPTS` and `SEND_RETRY_DELAY_SECONDS`.

Templates support simple placeholders:

```text
{{name}}
{{date}}
{{time}}
{{datetime}}
```

Values come from the request `variables` object plus the built-in date/time values. Missing variables fail validation.

Destinations can have an optional per-bot `alias`, which can be used as `destination_alias` in send and dry-run requests. Destination metadata can be refreshed with:

```text
POST /api/v1/destinations/{destination_id}/check
```

## Shared Media

The app does not upload large file bodies. An external uploader writes files to the OMW `media` share. The Docker host must mount:

```text
192.168.1.23:/export/media -> /mnt/omw-media -> /shared/media
```

The app validates relative paths under `/shared/media` and sends files through a local Telegram Bot API server in local mode.

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

## Validation

```bash
python -m pytest -q
python -m ruff check .
docker compose config
```
