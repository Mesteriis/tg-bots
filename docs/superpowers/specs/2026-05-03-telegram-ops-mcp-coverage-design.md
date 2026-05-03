# Telegram Ops And MCP Coverage Design

**Date:** 2026-05-03

**Status:** Approved design draft

**Goal:** Add a controlled Telegram operations layer that turns discovered bot/chat/topic facts into visible recommendations and safe automation, while ensuring MCP exposes sufficient read, preview, apply, audit, and explain capabilities across the service.

## Scope

This slice extends the existing local Telegram Bot Aggregator. It does not change the product into a generic enterprise automation platform. The focus remains Telegram bot operations, send safety, destination hygiene, and AI/MCP ergonomics.

Included:

- Telegram Ops dashboard built from the existing `Автопоиск` domain.
- Fact collection from bot discovery, diagnostic polling updates, destination checks, and selected Bot API calls.
- Recommendations with explicit reasons and diffs.
- Controlled auto-apply rules for low-risk reversible actions.
- Manual preview/apply flow for all recommendations.
- Audit trail for manual, MCP, scheduler, and auto-apply operations.
- MCP tools for Telegram Ops and a coverage matrix for all major domains.
- Dashboard visibility for rules, actions, recommendations, MCP coverage, scopes, and risks.

Out of scope:

- Automatic message sending.
- Automatic backup restore.
- Automatic secret backup enabling.
- Automatic protected-host or API-token scope changes.
- Deleting chats, destinations, templates, backups, files, or tokens.
- Bot polling/webhooks for ordinary send bots.
- Replacing existing REST/UI flows with MCP-only behavior.

## Existing Context

The repository already contains:

- FastAPI REST API under `/api/v1`.
- Vue 3 CDN dashboard.
- MCP under `/mcp/v1`.
- Bot and destination management.
- Tagged templates and template validation.
- Text/template/file sends.
- Shared media browser.
- Diagnostic polling bot domain.
- Discovery/autopick domain.
- Send history, retries, reliability graph, attempts, and stale lock controls.
- Runtime operations, JSON backup, restore preview/apply, and audit.
- Protected-host API tokens and MCP tool settings.

The new work must use these existing services instead of duplicating logic.

## Architecture

Add a bounded `Telegram Ops` application layer:

```text
Discovery / Diagnostics / Destination Health / Send History / Reliability
  -> OpsFactCollector
  -> OpsAdvisor
  -> OpsActionPreviewer
  -> OpsActionExecutor
  -> Audit
  -> REST / Dashboard / MCP
```

Responsibilities:

- `OpsFactCollector`: normalizes observed Telegram state into facts.
- `OpsAdvisor`: turns facts into recommendations.
- `OpsActionPreviewer`: produces human-readable and machine-readable diffs.
- `OpsActionExecutor`: applies allowed actions through existing repositories/services.
- `OpsAutomationService`: evaluates enabled automation rules and runs eligible actions.
- `McpCoverageService`: returns the REST/UI/MCP/scope/risk matrix.

Dependency direction:

- API routes and MCP tools call application services.
- Application services call repositories and existing Telegram services.
- Domain decision logic stays outside routers and outside static UI code.
- Existing destination/template/send/reliability validation is reused.

## Core Principle

Facts and recommendations are not permissions.

The service may discover information automatically, but changes happen only through one of these channels:

- explicit dashboard apply;
- explicit MCP apply with the required scope;
- enabled automation rule whose category is allowlisted for auto-apply.

Every apply path records an audit event and an action run.

## Data Model

### `ops_facts`

Stores normalized observed state.

Fields:

- `id`
- `fact_type`
- `bot_id`
- `chat_id`
- `message_thread_id`
- `source`
- `title`
- `username`
- `kind`
- `status`
- `confidence`
- `observed_at`
- `expires_at`
- `payload_json`

Allowed `fact_type` examples:

- `chat_seen`
- `bot_admin`
- `bot_not_admin`
- `forum_topic_seen`
- `destination_missing`
- `destination_stale`
- `permission_missing`
- `send_failure_pattern`
- `mcp_gap`

`source` examples:

- `diagnostic_update`
- `bot_discovery`
- `destination_check`
- `send_history`
- `reliability_attempt`
- `mcp_coverage`

### `ops_recommendations`

Stores actionable recommendations derived from facts.

Fields:

- `id`
- `recommendation_type`
- `status`
- `risk`
- `bot_id`
- `destination_id`
- `fact_ids_json`
- `title`
- `reason`
- `diff_json`
- `action_payload_json`
- `created_at`
- `updated_at`
- `applied_at`
- `dismissed_at`

Allowed `status`:

- `open`
- `previewed`
- `applied`
- `dismissed`
- `stale`
- `failed`

Allowed `risk`:

- `low`
- `medium`
- `high`

### `ops_automation_rules`

Stores rule configuration.

Fields:

- `id`
- `rule_key`
- `title`
- `mode`
- `is_enabled`
- `is_paused`
- `risk_limit`
- `config_json`
- `last_run_at`
- `last_result`
- `created_at`
- `updated_at`

Allowed `mode`:

- `suggest_only`
- `auto_apply`

### `ops_action_runs`

Stores every preview/apply/auto-apply attempt.

Fields:

- `id`
- `recommendation_id`
- `rule_id`
- `action_type`
- `source`
- `actor`
- `status`
- `preview_diff_json`
- `request_payload_json`
- `result_json`
- `error_message`
- `rollback_hint`
- `created_at`
- `finished_at`

Allowed `source`:

- `dashboard`
- `mcp`
- `scheduler`
- `auto_apply`

### `mcp_coverage_snapshots`

Optional table for persisted matrix snapshots.

Fields:

- `id`
- `captured_at`
- `matrix_json`
- `missing_required_tools_json`
- `warnings_json`

This can be added only if runtime calculation becomes expensive. Version 1 can compute the matrix from the tool catalog and static domain definitions.

## Recommendation Types

Version 1 supports:

- `create_destination_from_seen_chat`
- `update_destination_metadata`
- `record_forum_topic_thread`
- `mark_destination_unhealthy`
- `recommend_mcp_preset`
- `explain_failed_send`

Future-safe but not required in version 1:

- `suggest_send_profile`
- `suggest_template_variables`
- `suggest_rate_limit_change`

## Auto-Apply Rules

Auto-apply is available only for low-risk reversible actions:

- Create a destination from a chat where a configured bot is observed and the chat ID is known.
- Update destination title, username, or kind from fresh Telegram metadata.
- Record or update a forum topic `message_thread_id`.
- Mark destination health as degraded when the bot loses required rights.

Auto-apply is not allowed for:

- Sending messages.
- Retrying or canceling messages.
- Backup restore.
- Enabling secret backup.
- Creating or expanding API token scopes.
- Editing protected hosts.
- Enabling write MCP tools.
- Deleting any data.

Default mode for every rule is `suggest_only`.

## REST API

All endpoints live under `/api/v1/ops`.

Fact endpoints:

- `GET /api/v1/ops/facts`
- `POST /api/v1/ops/scan`

Recommendation endpoints:

- `GET /api/v1/ops/recommendations`
- `GET /api/v1/ops/recommendations/{recommendation_id}`
- `POST /api/v1/ops/recommendations/{recommendation_id}/preview`
- `POST /api/v1/ops/recommendations/{recommendation_id}/apply`
- `POST /api/v1/ops/recommendations/{recommendation_id}/dismiss`

Rule endpoints:

- `GET /api/v1/ops/rules`
- `PATCH /api/v1/ops/rules/{rule_id}`
- `POST /api/v1/ops/rules/{rule_id}/run`
- `POST /api/v1/ops/rules/{rule_id}/pause`
- `POST /api/v1/ops/rules/{rule_id}/resume`

Action/audit endpoints:

- `GET /api/v1/ops/action-runs`
- `GET /api/v1/ops/mcp-coverage`

## MCP Coverage Model

The matrix has one row per domain and tracks:

- domain key;
- REST coverage;
- UI coverage;
- MCP read tools;
- MCP preview tools;
- MCP write/apply tools;
- required scopes;
- risk level;
- enabled tools;
- missing recommended tools;
- notes.

Required domains:

- `health`
- `bots`
- `destinations`
- `templates`
- `send`
- `send_profiles`
- `send_batches`
- `media`
- `history`
- `reliability`
- `diagnostics`
- `discovery`
- `analytics`
- `mtproto`
- `operations_backup`
- `audit`
- `mcp_settings`
- `telegram_ops`

Coverage expectations:

- Every domain needs at least a read path.
- Every write domain needs a preview or dry-run path when the action is non-trivial.
- Every admin or automation action needs an audit path.
- Missing MCP tools are visible in the dashboard.

## MCP Tools

New tools:

- `inspect_bot_access`
- `list_ops_facts`
- `run_ops_scan`
- `list_ops_recommendations`
- `preview_ops_action`
- `apply_ops_action`
- `dismiss_ops_recommendation`
- `list_ops_rules`
- `update_ops_rule`
- `run_ops_rule`
- `pause_ops_rule`
- `resume_ops_rule`
- `explain_failed_send`
- `get_mcp_coverage_matrix`
- `recommend_mcp_preset`

Existing MCP settings still control whether each tool is callable.

Scope requirements:

- Read-only tools require `read`.
- Send explanation can use `read`.
- Recommendation preview requires `read`.
- Recommendation apply requires `ops_admin`.
- Rule update/run/pause/resume requires `ops_admin`.
- MCP preset recommendation requires `read`.
- Applying MCP preset changes requires `mcp_admin` and remains a separate existing MCP settings action.

## Dashboard

Rename or expand `Автопоиск` into `Telegram Ops`.

Views:

- `Факты`: table of observed chats, topics, permissions, and errors.
- `Рекомендации`: cards with reason, risk, diff, preview, apply, dismiss.
- `Автоматизация`: rules with mode, pause/resume, run now, last result.
- `Журнал`: action runs with source, actor, status, result, rollback hint.
- `MCP покрытие`: matrix for REST/UI/MCP/scopes/risk/enabled/missing.

Design constraints:

- Do not hide auto-applied changes.
- Every recommendation card must show why it exists.
- Every apply action must show a preview diff first.
- High-risk actions are visible as unsupported or manual-only, not silently hidden.

## Data Flows

### Scan Flow

1. User, MCP, scheduler, or dashboard starts scan.
2. `OpsFactCollector` reads discovery events, diagnostic updates, destination health, send history, and reliability attempts.
3. It optionally calls Bot API methods for fresh metadata where tokens and permissions allow.
4. Facts are upserted.
5. `OpsAdvisor` creates or refreshes recommendations.
6. SSE emits `ops.scan.completed` and `ops.recommendations.updated`.

### Manual Apply Flow

1. User opens a recommendation.
2. Dashboard calls preview endpoint.
3. Preview returns structured diff and risk.
4. User clicks apply.
5. `OpsActionExecutor` validates the recommendation is still current.
6. Executor calls existing repositories/services.
7. Action run and audit event are written.
8. SSE emits `ops.action.applied` or `ops.action.failed`.

### Auto-Apply Flow

1. Scheduler runs an enabled rule.
2. Rule selects open low-risk recommendations.
3. Executor previews each action internally.
4. Executor applies only allowlisted actions under the configured risk limit.
5. Every action writes `ops_action_runs` and audit events.
6. Rule `last_run_at` and `last_result` are updated.

### MCP Flow

1. MCP client calls read/preview/apply tool.
2. Tool enablement is checked through existing MCP settings.
3. Protected-host API token scope is checked by existing middleware when applicable.
4. Tool calls the same application service as REST.
5. Write tools write audit events.

## Error Handling

Telegram and local failures become facts or failed action runs when possible:

- `bot_not_admin`
- `missing_send_messages`
- `missing_send_media`
- `chat_not_found`
- `forum_topic_unknown`
- `rate_limited`
- `telegram_forbidden`
- `bot_api_unavailable`
- `shared_media_unavailable`
- `mcp_tool_disabled`

Scan failures must be partial. One inaccessible chat must not fail the whole scan.

Apply failures must preserve the recommendation unless the underlying fact is stale.

## Security

The app remains unauthenticated on trusted localhost/LAN by product decision.

Protected hosts still require permanent API tokens.

New scope:

```text
ops_admin
```

`ops_admin` is required for:

- applying recommendations through MCP or protected-host REST;
- updating automation rules;
- running auto-apply rules manually;
- pausing or resuming automation rules.

Dashboard local access can still perform these actions without auth, matching the current local-network model.

Tokens, bot secrets, API tokens, and Telethon session material must not appear in facts, recommendations, MCP responses, SSE events, or audit payloads.

## SSE Events

Add events:

- `ops.scan.started`
- `ops.scan.completed`
- `ops.scan.failed`
- `ops.recommendations.updated`
- `ops.action.previewed`
- `ops.action.applied`
- `ops.action.failed`
- `ops.rule.updated`
- `ops.rule.paused`
- `ops.rule.resumed`
- `mcp.coverage.updated`

Payloads keep the existing event envelope with `schema_version`.

## Testing Strategy

Unit tests:

- Fact normalization from diagnostic/discovery data.
- Recommendation generation.
- Preview diff generation.
- Auto-apply allowlist and risk limits.
- MCP coverage matrix completeness.
- Secret redaction.

Integration tests:

- `/api/v1/ops/facts`.
- `/api/v1/ops/recommendations`.
- Preview/apply/dismiss lifecycle.
- Rule pause/resume/run.
- MCP tools call the same services.
- Protected-host scope enforcement for `ops_admin`.

Static UI tests:

- `Telegram Ops` dashboard is visible.
- Existing dashboard tabs remain visible.
- Recommendations show diff/preview/apply/dismiss controls.
- Rules show `suggest_only` and `auto_apply` modes.
- MCP coverage matrix includes all required domains.

Manual validation:

- Start server.
- Run ops scan.
- Confirm facts appear.
- Preview destination creation.
- Apply destination creation.
- Enable one low-risk auto-apply rule.
- Run rule manually.
- Confirm action run and audit event.
- Call MCP `get_mcp_coverage_matrix`.
- Call MCP `preview_ops_action`.
- Confirm disabled MCP tools are rejected.

## Migration Strategy

All tables are additive.

No existing data is rewritten during migration.

The first scan creates facts and recommendations from current data.

Default automation mode is `suggest_only`, so enabling the feature does not change existing destinations until the user acts.

## Risks

- Telegram Bot API may not expose all permission details for every chat. Missing values must be represented as partial facts with warnings.
- Diagnostic facts depend on the product diagnostic bot receiving messages or forwards.
- Auto-apply can surprise users if too broad. Version 1 keeps the allowlist narrow and makes every action visible.
- MCP coverage can drift as new REST/UI features are added. Static tests should pin required domains and tool names.

## Open Decisions

None blocking for implementation planning.

Non-blocking details can be decided during implementation:

- Exact dashboard layout inside the current `Автопоиск` tab.
- Whether `mcp_coverage_snapshots` is persisted in version 1 or computed live only.
- Exact wording of recommendation cards.

## Design Self-Review

Spec coverage:

- Telegram Ops facts, recommendations, automation, and audit are covered.
- Controlled auto-apply behavior is covered.
- Dashboard visibility requirement is covered.
- MCP sufficiency requirement is covered through an explicit matrix and tool list.
- REST, MCP, SSE, migration, security, and testing are covered.

Placeholder scan:

- No required section contains placeholder text.

Consistency check:

- Auto-apply is consistently restricted to low-risk reversible actions.
- MCP write operations consistently require `ops_admin` or existing admin scopes.
- Existing services remain the source of behavior for destinations, sends, reliability, and audit.

Scope check:

- The slice is focused on Telegram operations and MCP coverage. It does not add unrelated messaging, file management, billing, or tenant features.

Ambiguity check:

- The design explicitly separates facts, recommendations, preview, manual apply, and auto-apply.
- The design states which actions are excluded from auto-apply.
