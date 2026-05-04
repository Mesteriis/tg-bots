# Operator Console UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Recompose the existing Vue 3 CDN admin panel into the approved Operator Console layout without removing existing dashboard functionality.

**Architecture:** Keep the frontend as the existing single `index.html` Vue app. Implement the redesign as static UI composition, Vue state, and small helper methods; no backend API changes are planned. Tests remain static-marker focused because this project currently validates the CDN UI through `tests/test_static_ui.py`.

**Tech Stack:** FastAPI static HTML, Vue 3 CDN, lucide icons, CSS, pytest static UI tests.

---

## File Structure

- Modify: `src/tg_bot_aggregator/static/index.html`
  - CSS primitives for operator headers, modal variants, status bars, stepper, and dense full-width tables.
  - Vue template restructure for Bots, Send, History, MTProto, Analytics, MCP, Operations, and small polish in Diagnostics/Health.
  - Vue state additions for modal visibility and local subtabs.
  - Vue methods for open/close modal flows and confirmation state.
- Modify: `tests/test_static_ui.py`
  - Update brittle assertions from old grid locations to new Operator Console markers.
  - Add tests for new subtabs, modals, history status bars, MTProto wizard, MCP subtabs, Operations subtabs, and no raw health JSON.
- No backend files should change in this UI slice.

## Design System Notes

Use the accepted Operator Console direction from `docs/superpowers/specs/2026-05-03-operator-console-ui-design.md`.

Keep these tokens and conventions:

- OneDark base: `#282c34`, `#61afef`, muted panels, semantic green/yellow/red.
- Panels use radius `8px` or less.
- Tables stay table-driven, not card grids.
- No decorative gradient orbs, no marketing-style hero sections.
- All visible admin copy remains Russian-first.
- Use `prefers-reduced-motion` for nonessential animation.

## Task 1: Add Operator Console Static Tests

**Files:**
- Modify: `tests/test_static_ui.py`

- [x] **Step 1: Add tests for new tab organization markers**

Add these assertions near existing static UI layout tests:

```python
def test_static_ui_uses_operator_console_navigation_patterns() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "operator-toolbar" in html
    assert "operator-actions" in html
    assert "status-strip" in html
    assert "stepper" in html
    assert "modal-panel compact-modal" in html
    assert "modal-panel danger-modal" in html
    assert "prefers-reduced-motion" in html
```

- [x] **Step 2: Add tests for Bots and Analytics modals**

Add:

```python
def test_static_ui_uses_modals_for_bot_and_analytics_creation() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "botModalOpen" in html
    assert "openBotModal" in html
    assert "closeBotModal" in html
    assert "analyticsModalOpen" in html
    assert "openAnalyticsModal" in html
    assert "closeAnalyticsModal" in html
    assert 'aria-labelledby="bot-modal-title"' in html
    assert 'aria-labelledby="analytics-modal-title"' in html
```

- [x] **Step 3: Add tests for Send and History subtabs**

Add:

```python
def test_static_ui_uses_operator_send_and_history_subtabs() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    for marker in [
        'sendWorkTab: "quick"',
        "sendWorkTab === 'quick'",
        "sendWorkTab === 'profiles'",
        "sendWorkTab === 'batch'",
        "sendWorkTab === 'file'",
        "sendWorkTab === 'preview'",
        "Быстрая отправка",
        "Preview / cURL",
    ]:
        assert marker in html

    for marker in [
        'historySubTab: "all"',
        "historySubTab === 'all'",
        "historySubTab === 'queue'",
        "historySubTab === 'dead_letter'",
        "historySubTab === 'attempts'",
        "historyStatusCounts",
        "Очередь",
        "Dead-letter",
        "Попытки",
    ]:
        assert marker in html
```

- [x] **Step 4: Add tests for MCP, Operations, and MTProto**

Add:

```python
def test_static_ui_uses_operator_mcp_operations_and_mtproto_layouts() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    for marker in [
        'mcpSubTab: "profile"',
        "mcpSubTab === 'profile'",
        "mcpSubTab === 'tools'",
        "mcpSubTab === 'tokens'",
        "mcpSubTab === 'connection'",
        "apiTokenModalOpen",
        "revokeTokenModalOpen",
        "confirmRevokeApiToken",
    ]:
        assert marker in html

    for marker in [
        'operationsSubTab: "runtime"',
        "operationsSubTab === 'runtime'",
        "operationsSubTab === 'infra'",
        "operationsSubTab === 'backup'",
        "operationsSubTab === 'restore'",
        "Runtime",
        "Infra и секреты",
        "Backup",
        "Restore",
    ]:
        assert marker in html

    for marker in [
        'mtprotoStep: "phone"',
        "mtprotoStep === 'phone'",
        "mtprotoStep === 'code'",
        "mtprotoStep === 'password'",
        "Шаг 1",
        "Шаг 2",
        "Шаг 3",
    ]:
        assert marker in html
```

- [x] **Step 5: Run new tests and confirm they fail**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_static_ui.py -q
```

Expected: FAIL on the new marker tests because the UI has not yet been recomposed.

## Task 2: Add CSS Primitives

**Files:**
- Modify: `src/tg_bot_aggregator/static/index.html`
- Test: `tests/test_static_ui.py`

- [x] **Step 1: Add shared CSS classes**

Add CSS near existing layout primitives:

```css
.operator-toolbar {
  align-items: flex-start;
  display: flex;
  gap: 16px;
  justify-content: space-between;
  margin-bottom: 16px;
}

.operator-actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.status-strip {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
}

.status-meter {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
}

.status-meter-line {
  background: var(--bg);
  border-radius: 999px;
  height: 5px;
  overflow: hidden;
}

.status-meter-fill {
  background: var(--accent);
  border-radius: inherit;
  display: block;
  height: 100%;
  transition: width 180ms ease;
}

.segmented {
  align-items: center;
  display: inline-flex;
  gap: 4px;
}

.stepper {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}

.step-pill {
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--muted);
  padding: 10px 12px;
}

.step-pill.active {
  border-color: var(--accent);
  color: var(--text);
}

.modal-panel.compact-modal {
  max-width: 560px;
}

.modal-panel.danger-modal {
  max-width: 520px;
}
```

- [x] **Step 2: Extend reduced-motion CSS**

Inside the existing `prefers-reduced-motion` block, ensure these transitions are disabled:

```css
.status-meter-fill,
.reliability-edge,
.panel,
.modal-panel {
  animation: none;
  transition: none;
}
```

- [x] **Step 3: Run static UI tests for CSS markers**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_static_ui.py::test_static_ui_uses_operator_console_navigation_patterns -q
```

Expected: PASS after CSS markers exist.

## Task 3: Add Vue State And Helper Methods

**Files:**
- Modify: `src/tg_bot_aggregator/static/index.html`
- Test: `tests/test_static_ui.py`

- [x] **Step 1: Add state defaults**

In the Vue `data()` return object, add:

```js
botModalOpen: false,
analyticsModalOpen: false,
apiTokenModalOpen: false,
revokeTokenModalOpen: false,
revokeTokenTarget: null,
sendWorkTab: "quick",
historySubTab: "all",
mcpSubTab: "profile",
operationsSubTab: "runtime",
mtprotoStep: "phone",
```

Keep existing `sendSubTab: "text"` because existing send payload helpers depend on it.

- [x] **Step 2: Add computed history status counts**

In `computed`, add:

```js
historyStatusCounts() {
  const counts = { succeeded: 0, failed: 0, queued: 0, dead_letter: this.deadLetter.length };
  this.history.forEach((item) => {
    if (item.status === "succeeded") counts.succeeded += 1;
    if (item.status === "failed") counts.failed += 1;
    if (item.status === "queued" || item.status === "created" || item.status === "deferred") counts.queued += 1;
  });
  return counts;
},
historyStatusTotal() {
  return Math.max(1, this.history.length + this.deadLetter.length);
},
```

- [x] **Step 3: Add open/close methods**

In `methods`, add:

```js
openBotModal() { this.botModalOpen = true; },
closeBotModal() { this.botModalOpen = false; },
openAnalyticsModal() { this.analyticsModalOpen = true; },
closeAnalyticsModal() { this.analyticsModalOpen = false; },
openApiTokenModal() { this.apiTokenModalOpen = true; },
closeApiTokenModal() { this.apiTokenModalOpen = false; this.createdApiToken = null; },
openRevokeTokenModal(token) { this.revokeTokenTarget = token; this.revokeTokenModalOpen = true; },
closeRevokeTokenModal() { this.revokeTokenTarget = null; this.revokeTokenModalOpen = false; },
```

- [x] **Step 4: Update create/revoke methods to close modals**

Change:

```js
async createBot() {
  this.botSaving = true;
  try {
    await this.api("/bots", { method: "POST", body: JSON.stringify(this.forms.bot) });
    this.forms.bot = { name: "", token: "", description: "" };
    this.closeBotModal();
    await this.refreshAll();
  } finally {
    this.botSaving = false;
  }
},
```

Change `createApiToken` so it keeps the newly created token visible inside the modal and refreshes token list:

```js
async createApiToken() {
  const response = await this.api("/api-tokens", { method: "POST", body: JSON.stringify(this.forms.apiToken) });
  this.createdApiToken = response.token;
  await this.refreshAll();
},
```

Add a wrapper for destructive revoke:

```js
async confirmRevokeApiToken() {
  if (!this.revokeTokenTarget) return;
  await this.revokeApiToken(this.revokeTokenTarget.id);
  this.closeRevokeTokenModal();
},
```

- [x] **Step 5: Run state marker tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_static_ui.py::test_static_ui_uses_modals_for_bot_and_analytics_creation tests/test_static_ui.py::test_static_ui_uses_operator_send_and_history_subtabs tests/test_static_ui.py::test_static_ui_uses_operator_mcp_operations_and_mtproto_layouts -q
```

Expected: still FAIL until the template markers are added, but state/method marker failures should be reduced.

## Task 4: Recompose Bots And Analytics

**Files:**
- Modify: `src/tg_bot_aggregator/static/index.html`
- Test: `tests/test_static_ui.py`

- [x] **Step 1: Move bot creation form into modal**

Replace the current `activeTab === 'bots'` two-column grid with a `stack-layout`:

```html
<div v-if="activeTab === 'bots'" class="stack-layout">
  <div class="operator-toolbar">
    <div>
      <h2>Боты</h2>
      <p class="section-description">Управление Bot API токенами, проверка getMe и базовые сведения о каждом боте.</p>
    </div>
    <div class="operator-actions">
      <button class="btn" type="button" @click="refreshAll"><i data-lucide="refresh-cw"></i>Обновить</button>
      <button class="btn primary" type="button" @click="openBotModal"><i data-lucide="plus"></i>Добавить бота</button>
    </div>
  </div>
  <div class="panel full-span">
    <!-- existing saved bots table -->
  </div>
</div>
```

Add a `botModalOpen` modal with the existing create bot form and `aria-labelledby="bot-modal-title"`.

- [x] **Step 2: Move analytics target creation into modal**

Change `activeTab === 'analytics'` to a full-width targets table plus header action `Добавить цель`. Add an `analyticsModalOpen` modal containing the existing target form and `aria-labelledby="analytics-modal-title"`.

- [x] **Step 3: Run modal tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_static_ui.py::test_static_ui_uses_modals_for_bot_and_analytics_creation tests/test_static_ui.py::test_static_ui_describes_tabs_and_cards -q
```

Expected: PASS.

## Task 5: Recompose Send

**Files:**
- Modify: `src/tg_bot_aggregator/static/index.html`
- Test: `tests/test_static_ui.py`

- [x] **Step 1: Replace send subtabs with work tabs**

Use `sendWorkTab` for top-level send workflow:

```html
<div class="subtabs" role="tablist" aria-label="Отправка">
  <button class="subtab" :class="{ active: sendWorkTab === 'quick' }" type="button" @click="sendWorkTab = 'quick'">Быстрая отправка</button>
  <button class="subtab" :class="{ active: sendWorkTab === 'profiles' }" type="button" @click="sendWorkTab = 'profiles'">Профили</button>
  <button class="subtab" :class="{ active: sendWorkTab === 'batch' }" type="button" @click="sendWorkTab = 'batch'">Batch</button>
  <button class="subtab" :class="{ active: sendWorkTab === 'file' }" type="button" :disabled="!fileSendAvailable" @click="fileSendAvailable && (sendWorkTab = 'file', sendSubTab = 'file')">Файл с шары</button>
  <button class="subtab" :class="{ active: sendWorkTab === 'preview' }" type="button" @click="sendWorkTab = 'preview'">Preview / cURL</button>
</div>
```

- [x] **Step 2: Move profile panel under `sendWorkTab === 'profiles'`**

Keep all existing profile controls and methods unchanged. Disable profile actions only when the active payload is file and file sending is unavailable.

- [x] **Step 3: Move batch panel under `sendWorkTab === 'batch'`**

Keep existing batch controls, destination checkboxes, and batch table.

- [x] **Step 4: Group text/template under quick send**

Inside `sendWorkTab === 'quick'`, add a segmented control:

```html
<div class="segmented" aria-label="Тип быстрой отправки">
  <button class="btn" type="button" :class="{ primary: sendSubTab === 'text' }" @click="sendSubTab = 'text'">Текст</button>
  <button class="btn" type="button" :class="{ primary: sendSubTab === 'template' }" @click="sendSubTab = 'template'">Шаблон</button>
</div>
```

Keep the existing text and template forms with their current methods.

- [x] **Step 5: Move file form under `sendWorkTab === 'file'`**

Keep the existing file form and media browser. Preserve unavailable shared-media warning and disabled fieldset.

- [x] **Step 6: Move dry-run/result panel under `sendWorkTab === 'preview'`**

Keep `sendDryRun` rendering. Add quick buttons for `copyCurl('text')`, `copyCurl('template')`, and `copyCurl('file')` so cURL remains reachable.

- [x] **Step 7: Run send tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_static_ui.py::test_static_ui_uses_operator_send_and_history_subtabs tests/test_static_ui.py::test_static_ui_exposes_send_profiles_preview_retry_and_cancel tests/test_static_ui.py::test_static_ui_exposes_batches_and_diagnostic_update_destination_flow tests/test_static_ui.py::test_static_ui_disables_file_send_when_shared_media_is_unavailable -q
```

Expected: PASS.

## Task 6: Recompose History And MTProto

**Files:**
- Modify: `src/tg_bot_aggregator/static/index.html`
- Test: `tests/test_static_ui.py`

- [x] **Step 1: Add history status strip**

At the top of History, add four `status-meter` cards using `historyStatusCounts`.

Use widths like:

```html
<span class="status-meter-fill" :style="{ width: `${Math.round((historyStatusCounts.succeeded / historyStatusTotal) * 100)}%` }"></span>
```

- [x] **Step 2: Split history into subtabs**

Use:

- `historySubTab === 'all'` for the current history table
- `historySubTab === 'queue'` for due queue
- `historySubTab === 'dead_letter'` for dead-letter
- `historySubTab === 'attempts'` for reliability attempts

Keep retry/cancel buttons in `all`.

- [x] **Step 3: Convert MTProto to stepper**

Add:

```html
<div class="stepper" aria-label="MTProto login steps">
  <button class="step-pill" :class="{ active: mtprotoStep === 'phone' }" type="button" @click="mtprotoStep = 'phone'">Шаг 1 · Телефон</button>
  <button class="step-pill" :class="{ active: mtprotoStep === 'code' }" type="button" @click="mtprotoStep = 'code'">Шаг 2 · Код</button>
  <button class="step-pill" :class="{ active: mtprotoStep === 'password' }" type="button" @click="mtprotoStep = 'password'">Шаг 3 · 2FA</button>
</div>
```

Render the existing phone/code/password forms behind `mtprotoStep`.

- [x] **Step 4: Run history and MTProto tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_static_ui.py::test_static_ui_uses_operator_send_and_history_subtabs tests/test_static_ui.py::test_static_ui_is_russian_first_and_explains_mtproto tests/test_static_ui.py::test_static_ui_uses_operator_mcp_operations_and_mtproto_layouts -q
```

Expected: PASS.

## Task 7: Recompose MCP And Operations

**Files:**
- Modify: `src/tg_bot_aggregator/static/index.html`
- Test: `tests/test_static_ui.py`

- [x] **Step 1: Add MCP subtabs**

Replace the large `activeTab === 'mcp'` grid with `stack-layout` plus subtabs:

- `mcpSubTab === 'profile'`
- `mcpSubTab === 'tools'`
- `mcpSubTab === 'tokens'`
- `mcpSubTab === 'connection'`

Move existing panels into matching subtabs. The tool matrix should be full-width in `tools`.

- [x] **Step 2: Move API token creation into modal**

Place button `Создать токен` in the Tokens header and render a `apiTokenModalOpen` modal containing the existing token creation form.

- [x] **Step 3: Add revoke confirmation modal**

Change token row revoke button from direct `revokeApiToken(token.id)` to:

```html
@click="openRevokeTokenModal(token)"
```

Add a `danger-modal` with:

```html
<button class="btn danger-btn" type="button" @click="confirmRevokeApiToken">Отозвать токен</button>
```

- [x] **Step 4: Add Operations subtabs**

Replace the large `activeTab === 'operations'` grid with subtabs:

- `operationsSubTab === 'runtime'`: runtime settings form
- `operationsSubTab === 'infra'`: local secrets and infra panel
- `operationsSubTab === 'backup'`: repository settings, preflight/diff/run, backup runs
- `operationsSubTab === 'restore'`: restore wizard and manual JSON import

Keep all existing controls, `v-model` bindings, and methods.

- [x] **Step 5: Run MCP and Operations tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_static_ui.py::test_static_ui_exposes_mcp_and_api_token_management tests/test_static_ui.py::test_static_ui_uses_operator_mcp_operations_and_mtproto_layouts tests/test_static_ui.py::test_static_ui_exposes_operations_backup_preflight_and_versions tests/test_static_ui.py::test_static_ui_reliability_calls_new_api_and_keeps_history_actions -q
```

Expected: PASS.

## Task 8: Polish Diagnostics, Health, And Motion

**Files:**
- Modify: `src/tg_bot_aggregator/static/index.html`
- Test: `tests/test_static_ui.py`

- [x] **Step 1: Keep Diagnostics as settings/state/list**

Use `stack-layout` and keep:

- diagnostic settings panel
- current state panel
- full-width diagnostic updates table

Do not remove `createDestinationFromDiagnosticUpdate`.

- [x] **Step 2: Add compact status strip to Health**

Above health cards, add a `status-strip` summarizing:

- API status
- Bot API mode
- file send availability
- backup state

Keep exact value meta table.

- [x] **Step 3: Ensure motion is restrained**

Confirm these CSS features exist:

- `@keyframes panelIn`
- `@keyframes edgeFlow`
- `prefers-reduced-motion`
- `status-meter-fill` transition disabled under reduced motion

- [x] **Step 4: Run polish tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_static_ui.py::test_static_ui_exposes_diagnostic_bot_management tests/test_static_ui.py::test_static_ui_renders_health_as_cards_and_exposes_local_secrets tests/test_static_ui.py::test_static_ui_uses_operator_console_navigation_patterns -q
```

Expected: PASS.

## Task 9: Full Validation And Browser Smoke

**Files:**
- Modify: none expected unless validation finds a defect.

- [x] **Step 1: Run static UI tests**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest tests/test_static_ui.py -q
```

Expected: PASS.

- [x] **Step 2: Run full test suite**

Run:

```bash
PYTHONPATH=src python3.11 -m pytest -q
```

Expected: PASS.

- [x] **Step 3: Run ruff**

Run:

```bash
PYTHONPATH=src python3.11 -m ruff check .
```

Expected: PASS.

- [x] **Step 4: Browser smoke**

Use the in-app browser first. If screenshot capture still times out, use DOM snapshots and browser navigation as the primary smoke check, then record the fallback reason.

Check these screens:

- Боты: open and close create bot modal.
- Отправка: switch quick/profile/batch/file/preview tabs.
- История: switch all/queue/dead-letter/attempts tabs.
- MTProto: switch phone/code/password steps.
- MCP: switch profile/tools/tokens/connection tabs, open token modal, open/close revoke modal.
- Операции: switch runtime/infra/backup/restore tabs.
- Состояние: confirm no raw JSON and cards/status strip render.

- [x] **Step 5: Commit UI slice**

Commit only UI/test/plan changes:

```bash
git add src/tg_bot_aggregator/static/index.html tests/test_static_ui.py docs/superpowers/plans/2026-05-03-operator-console-ui.md
git commit -m "ui: recompose admin as operator console"
```

Expected: commit succeeds without unrelated files staged.

## Self-Review

Spec coverage:

- Modals: covered by Tasks 3, 4, and 7.
- Subtabs: covered by Tasks 5, 6, and 7.
- MTProto wizard: covered by Task 6.
- History status bars: covered by Task 6.
- Operations split: covered by Task 7.
- MCP split and token confirmation: covered by Task 7.
- Health readability and no raw JSON: covered by Task 8.
- Motion and reduced-motion: covered by Tasks 2 and 8.

Deferred-work scan:

- The plan contains no deferred implementation steps.

Assumptions:

- The UI slice can be completed without backend API changes because all requested changes are layout/state composition over existing data and methods.
- Static tests remain the project’s primary automated UI validation because this repo currently has no frontend build/test runner.

Risks:

- `index.html` is large; implementation must keep changes focused and avoid unrelated rewrites.
- Some existing static tests assert old layout fragments and must be updated to new stable markers.
- In-app browser screenshot capture timed out during design review; browser smoke may need DOM snapshots or local Playwright fallback.
