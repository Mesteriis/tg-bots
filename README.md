# Telegram Bot Aggregator

Local async FastAPI service for managing Telegram bot tokens, sending tagged text/media messages, exposing MCP tools, and collecting MTProto analytics.

## Security Model

This project is intentionally designed for a trusted local network and has no authentication in version 1. Anyone who can reach the service can manage bots, send Telegram messages, start MTProto login, and trigger analytics refreshes. Default bind is `127.0.0.1`; LAN exposure requires explicit `APP_HOST=0.0.0.0`.

Bot tokens are stored in SQLite as plain text by product decision. Do not expose the app or database outside the trusted network.

## Development

```bash
python -m pip install -e ".[dev]"
pytest -q
uvicorn tg_bot_aggregator.main:create_app --factory --reload
```

The API is versioned under `/api/v1`. MCP endpoints are under `/mcp/v1`.

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

## Validation

```bash
python -m pytest -q
python -m ruff check .
docker compose config
```
