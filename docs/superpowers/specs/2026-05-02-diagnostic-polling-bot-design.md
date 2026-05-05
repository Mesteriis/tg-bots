# Diagnostic Polling Bot Design

**Date:** 2026-05-02

**Status:** Approved implementation scope

**Goal:** Add a product-owned Telegram diagnostic bot that runs in polling mode and replies with a readable report for every message it receives or is forwarded, including forum topic/thread identifiers.

## Scope

This is a separate product domain named `diagnostics`. It is not part of the existing send-only bot sender workflow and must not change the REST/MCP sending contract.

Version 1 includes:

- Dedicated long-polling process launched separately from FastAPI.
- Dashboard management for selecting exactly one saved product bot as the diagnostic bot.
- SQLite persistence for diagnostic bot settings and polling offset.
- Telegram Bot API `getUpdates`, `deleteWebhook`, and diagnostic reply sending.
- Human-readable message reports, not raw JSON dumps.
- Explicit forum topic/thread detection through `message_thread_id` and `is_topic_message`.
- Inline copy buttons for important identifiers when Telegram clients support `copy_text`.
- No inbound update persistence.

Out of scope:

- Webhooks.
- Storing inbound updates in SQLite.
- User authorization.
- Command routing beyond an optional `/start` diagnostic explanation.
- Sending operational messages through this diagnostic bot.

## Runtime Model

The diagnostic bot is a separate process:

```bash
python -m tg_bot_aggregator.domain.diagnostics.bot
```

Docker Compose runs it as a dedicated `diagnostic-bot` service. It shares the same code image, SQLite data volume, and Bot API base URL configuration as the app.

The process:

1. Reads the dashboard-managed diagnostic settings from SQLite.
2. Resolves the selected active bot and token from the existing `bots` table.
3. Calls `deleteWebhook` once on startup to make polling valid.
4. Runs `getUpdates` with long polling.
5. For each `message`, `edited_message`, `channel_post`, or `edited_channel_post`, formats a report.
6. Sends the report back to the source chat, preserving `message_thread_id` when present.
7. Advances the update offset only after handling the update attempt.

## Dashboard Management

The shared Vue dashboard includes a `Diagnostics` tab.

The tab supports:

- Selecting one existing bot record as the product diagnostic bot.
- Enabling or disabling diagnostic polling.
- Showing selected bot name and username.
- Showing last processed update id.
- Showing the last polling/reply error.

The REST API is versioned under `/api/v1`:

- `GET /api/v1/diagnostics/bot`
- `PATCH /api/v1/diagnostics/bot`

The polling process must not use a standalone token hidden outside the dashboard. It reads the configured bot from SQLite so dashboard state is the source of truth.

## Database

Table: `diagnostic_bot_settings`

Fields:

- `id`, singleton row id `1`
- `bot_id`, nullable FK to `bots.id`
- `is_enabled`
- `last_update_id`
- `last_error`
- `created_at`
- `updated_at`

## Report Content

The report is readable MarkdownV2 or plain text with stable sections:

- Message:
  - update id
  - update kind
  - message id
  - date
  - message type summary
  - text/caption preview where present
- Thread:
  - `message_thread_id`
  - `is_topic_message`
  - forum topic created/closed/reopened/general topic service markers when present
- Chat:
  - chat id
  - type
  - title
  - username
- Sender:
  - user id
  - username
  - first and last name
  - bot flag
- Forward origin:
  - origin type
  - source chat or user id when Telegram exposes it
  - source message id when present
  - signature/sender name when present
- Reply:
  - replied message id
  - replied sender id
  - replied thread id when present
- Media:
  - document/photo/video/animation/audio/voice/sticker/video note/contact/location/poll/dice ids and key metadata where present.

Unknown or unsupported fields are summarized as an `Other fields` list with compact key/value lines. The bot must not send a full raw JSON dump unless a future explicit debug mode is added.

## Copy Controls

The reply includes an inline keyboard with `copy_text` buttons for high-value IDs:

- chat id
- message id
- thread id
- sender id
- forward source id
- file id

Telegram limits `copy_text.text` to 1-256 characters, so only scalar IDs are included. If no scalar identifiers are available, the reply is sent without a keyboard.

## Formatting Constraints

Telegram message length is capped, so reports are split into chunks below 3900 characters before sending. The first chunk carries the copy keyboard; continuation chunks omit it.

Special characters must be escaped when parse mode is used. If MarkdownV2 escaping becomes too risky, version 1 may use plain text with HTML-like section separators and no parse mode. Correct delivery is more important than rich formatting.

## Error Handling

- Network and Bot API errors are logged with token redaction.
- A single failed update must not kill the polling process.
- Polling uses a short retry delay after errors.
- The loop must handle cancellation cleanly.
- Bot tokens must never be printed in logs.

## Testing Strategy

Unit tests:

- Extract identifiers from representative private, group, forwarded, reply, media, and forum topic messages.
- Format reports with forum `message_thread_id`.
- Build copy keyboards with correct `copy_text` shape.
- Split long reports.
- Polling loop calls `deleteWebhook`, `getUpdates`, and replies with preserved thread id.
- Telegram client request errors are converted to domain errors without leaking tokens.

Manual validation:

- Run the diagnostic bot with a test token.
- Send a private message.
- Forward a message.
- Send a message inside a forum topic.
- Confirm the reply includes chat id, message id, sender id, and `message_thread_id`.
- Press copy buttons in Telegram client.

## References

- Telegram Bot API: https://core.telegram.org/bots/api
- `InlineKeyboardButton.copy_text`: https://core.telegram.org/bots/api#inlinekeyboardbutton
- `message_thread_id`: https://core.telegram.org/bots/api#sendmessage
