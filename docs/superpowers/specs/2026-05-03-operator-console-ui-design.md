# Operator Console UI Design

**Date:** 2026-05-03

**Status:** Approved design direction, pending implementation plan

## Goal

Refresh the existing Vue 3 CDN admin panel into a more polished operator console without removing current functionality. The UI should feel like a serious local operations tool: clear hierarchy, predictable workflows, dense but readable tables, modal-based creation flows, restrained animation, and useful graphs only where they explain operational state.

The selected direction is **Operator Console**:

- Keep the existing left navigation and OneDark-style visual language.
- Add consistent per-page headers with primary actions.
- Use subtabs inside complex domains instead of placing every control on one screen.
- Move create/edit and dangerous actions into modals or wizards.
- Keep saved lists and diagnostic tables full-width when scanning matters.
- Add compact charts/status visuals only for queues, reliability, backup, and MCP coverage.

## Constraints

- Preserve all current dashboard functionality.
- Preserve the Vue 3 CDN single-file frontend approach for this slice.
- Do not introduce a frontend build pipeline.
- Do not add decorative charts that do not support decisions.
- Avoid a corporate-heavy redesign: keep the tool direct, local, and operational.
- Keep text Russian-first.
- Maintain existing API contracts unless an implementation plan explicitly justifies a small addition.
- Respect reduced-motion users where animation is added.

## Current UI Assessment

Already reasonable:

- `Адресаты`: list is full-width and creation is already modal-based.
- `Шаблоны`: saved/create subtabs are already present.
- `Telegram Ops`: internal subtabs already match the domain shape.
- `Надежность`: graph is useful and aligned with the product.
- `Состояние`: runtime data is now readable cards instead of raw JSON.

Needs restructuring:

- `Операции`: too much unrelated runtime, infra, backup, restore, import, and run history on one long screen.
- `MCP`: settings, tool matrix, tokens, transports, and connection helper compete in one grid.
- `История`: main history, due queue, dead-letter, and retry/cancel actions need clearer operational grouping.
- `MTProto`: three forms should behave like a login wizard.
- `Отправка`: profile, batch, text, template, file, preview, and preflight are all valid, but the current order makes the main send task less focused.
- `Боты`, `Аналитика`, `Диагностика`: can be polished with the same header/actions/modal conventions.

## Navigation Model

Top-level sidebar stays unchanged in scope and intent:

- Боты
- Адресаты
- Шаблоны
- Отправка
- История
- Надежность
- MTProto
- Аналитика
- Диагностика
- Telegram Ops
- MCP
- Аудит
- Операции
- Состояние

Each tab receives a consistent local header:

- title
- one-sentence purpose
- secondary refresh/status action where relevant
- one primary action when relevant, such as `Добавить`, `Создать токен`, `Run scan`, or `Backup`

The header replaces ad hoc panel-level primary actions where that improves scanability, but panel actions remain for row-specific or secondary operations.

## Tab Restructure

### Боты

Keep a simple full-width list and move bot creation into a modal.

Main screen:

- saved bots table
- username, Telegram bot ID, status/check timestamp where available
- row action: check bot

Modal:

- token
- optional display name and description
- explanation that `getMe` auto-fills username and ID

### Адресаты

Keep the current full-width list plus creation modal.

Polish:

- row health status as badges
- copy-friendly chat ID/thread ID cells where feasible
- primary header action `Добавить адресата`

### Шаблоны

Keep existing subtabs:

- `Сохраненные`
- `Новый шаблон`

Polish:

- saved templates full-width
- template versions shown as a detail drawer/panel after selecting a template
- validation result remains visible near the create/edit flow

### Отправка

Use subtabs to separate operational intent:

- `Быстрая отправка`
- `Профили`
- `Batch`
- `Файл с шары`
- `Preview / cURL`

`Быстрая отправка` contains a segmented send-kind control for text vs template. File sending remains separate because it has mount and local Bot API constraints.

Profiles and batch stay accessible, but they should not visually sit above every manual send form. The user should first understand whether they are sending now, using a saved profile, or managing a batch.

When shared media is unavailable:

- `Файл с шары` is disabled with a visible reason.
- Text/template/profile flows remain enabled.

### История

Convert to subtabs:

- `Все отправки`
- `Очередь`
- `Dead-letter`
- `Попытки`

Add compact status bars at the top:

- succeeded
- failed
- queued/deferred
- dead-letter

The bars are operational indicators, not analytics charts. They should be derived from already-loaded lists where possible.

### Надежность

Keep the graph as a primary surface.

Polish:

- keep node details and edge table below the graph
- keep latest attempts full-width
- add subtle animated edge pulse only when motion is allowed
- avoid adding unrelated charts

### MTProto

Convert the three forms into a stepper/wizard:

- Step 1: phone and request code
- Step 2: confirm code
- Step 3: 2FA password, only when needed

Keep the instruction panel visible or collapsible. The warning about unauthenticated LAN access remains visible because it is a real product risk.

### Аналитика

Keep simple for now:

- targets table full-width
- `Добавить цель` modal
- manual refresh action per row

Do not add large analytics charts until snapshots and trend data are surfaced in a stronger product flow.

### Диагностика

Split into clearer blocks:

- settings card for polling diagnostic bot
- current state card
- full-width updates table

Creation from update stays a row action. If it needs more fields, open the existing address modal prefilled from the update instead of adding another inline form.

### Telegram Ops

Keep existing subtabs:

- Обзор
- Факты
- Рекомендации
- Автоматизация
- Журнал действий
- MCP покрытие

Polish:

- make overview more dashboard-like with compact metrics and status chips
- keep recommendation preview/apply actions explicit
- keep MCP coverage as a matrix, not a chart-heavy surface

### MCP

Convert one large grid into subtabs:

- `Профиль`
- `Инструменты`
- `Токены`
- `Подключение`

Details:

- `Профиль`: enable flags and presets
- `Инструменты`: full-width tool matrix with category/risk/enabled
- `Токены`: token list plus `Создать токен` modal
- `Подключение`: transport paths, protected hosts, required header, copy helper

Token creation remains local-admin explicit. Revoking a token should use a confirmation modal because it is destructive.

### Аудит

Keep as a full-width table.

Polish:

- add simple chips/filters for action or status if existing data supports it without API changes
- keep raw event details out of the main table unless a row detail panel is selected

### Операции

Convert into subtabs:

- `Runtime`
- `Infra и секреты`
- `Backup`
- `Restore`

Details:

- `Runtime`: Telegram Bot API URL, media root, file limit, retry policy, send policy, callback.
- `Infra и секреты`: host/port, DB/Redis URLs, CORS, MCP origins, protected hosts, diagnostic/discovery polling timing.
- `Backup`: repository settings, API auth, include secrets warning, preflight/diff/run actions, backup run table.
- `Restore`: restore wizard, partial sections, row-level diff, manual JSON import as secondary/collapsible advanced path.

Backup and restore should remain visually separate because restore is higher risk.

### Состояние

Keep readable cards.

Polish:

- add small status strip for file send, Bot API mode, backup state
- keep meta table for exact values
- do not reintroduce raw JSON

## Modals And Wizards

Use modals for:

- create bot
- create destination
- create analytics target
- create API token
- confirm token revoke
- backup restore apply confirmation
- optional template create/edit if the saved/create subtab becomes too dense

Use wizard/stepper for:

- MTProto login

Modal rules:

- max width appropriate to task, no nested cards inside modals
- clear title, one-sentence purpose, primary action, cancel action
- close on explicit cancel or overlay only for non-dangerous forms
- destructive actions require explicit confirmation text or clear confirmation button

## Visual System

Keep OneDark as the base:

- dark background
- muted panel surfaces
- blue primary action
- green success
- yellow warning
- red danger

Polish directions:

- consistent 8px or smaller radius
- tighter table density with better row hover
- badges for status/risk instead of plain text
- fixed-size icon buttons with tooltips/titles
- no gradient-orb or decorative background effects
- avoid text overflow in buttons and chips

## Motion

Add restrained motion:

- panel enter: short fade/translate
- modal enter: fade plus slight scale
- active subtab underline/indicator
- reliability edge pulse
- status bar fill transition

Rules:

- no motion required to understand the UI
- use `prefers-reduced-motion` to disable nonessential animation
- do not animate table layout changes in a way that causes jitter

## Graphs And Status Visuals

Allowed in this slice:

- reliability graph stays primary
- history status bars
- backup run timeline/status strip
- MCP coverage compact bars or matrix emphasis
- Telegram Ops overview counters

Not included:

- large analytics trend chart
- decorative overview graph unrelated to operations
- heavy charting dependency

Implementation should use CSS/HTML first. A charting library is not justified for this slice.

## Testing And Verification

Static tests should assert:

- key tabs and subtabs remain present
- create flows moved to modals keep expected labels and actions
- file send remains disabled when shared media is unavailable
- MCP subtabs expose profile/tools/tokens/connection
- operations subtabs expose runtime/infra/backup/restore
- history subtabs expose all/queue/dead-letter/attempts
- MTProto stepper instructions remain Russian-first
- health screen does not render raw JSON

Manual browser checks:

- desktop viewport: no cards overlap, long tables scroll inside wrappers
- mobile/narrow viewport: sidebar/content and modals remain usable
- each tab opens without console errors
- modal open/close flows work
- reduced motion does not depend on animations

## Risks

- `index.html` is already large, so UI changes can make it harder to maintain. The implementation plan should keep edits organized and avoid unrelated rewrites.
- Moving forms into modals can break tests that assert exact static fragments. Tests should be updated to verify behavior markers, not brittle layout order.
- If too many subtabs are added at once, the UI can become fragmented. The implementation should only split screens where current density hurts usability.
- Browser screenshot capture currently timed out in the in-app browser session, so visual verification may need DOM snapshots plus local Playwright if screenshot capture remains unavailable.

## Out Of Scope

- Replacing Vue CDN with a bundler.
- Adding authentication.
- Changing backend API behavior.
- Adding a new BI-style dashboard.
- Adding a charting dependency.
- Rewriting the whole frontend into components in this slice.
