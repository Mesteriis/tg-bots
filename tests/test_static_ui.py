import re
from pathlib import Path


def _spa_source() -> str:
    return (
        Path("src/tg_bot_aggregator/static/index.html").read_text()
        + Path("src/tg_bot_aggregator/static/app.css").read_text()
        + Path("src/tg_bot_aggregator/static/app.js").read_text()
    )


def test_static_ui_uses_vue_api_and_events() -> None:
    html = _spa_source()

    assert "/static/vendor/vue.global.prod.js" in html
    assert "/static/vendor/lucide.min.js" in html
    assert "v-cloak" in html
    assert Path("src/tg_bot_aggregator/static/vendor/vue.global.prod.js").exists()
    assert Path("src/tg_bot_aggregator/static/vendor/lucide.min.js").exists()
    assert "/api/v1" in html
    assert 'new EventSource("/api/v1/events")' in html
    assert "apiToken" in html


def test_static_ui_exposes_telegram_network_tab() -> None:
    html = _spa_source()

    assert '{ id: "network", label: "Прокси / VPN"' in html
    assert "Telegram-сеть: прокси / VPN" in html
    assert "activeTab === 'network'" in html
    assert "WireGuard" in html
    assert "OpenVPN" in html
    assert "Xray пока остается в roadmap" in html


def test_static_ui_uses_onedark_motion_and_token_first_bot_flow() -> None:
    html = _spa_source()

    assert "#282c34" in html
    assert ":root" in html
    assert "[v-cloak]" in html
    assert "#61afef" in html
    assert "@keyframes panelIn" in html
    assert "prefers-reduced-motion" in html
    assert 'placeholder="@username после проверки"' in html
    assert 'v-model="forms.bot.name"' in html
    assert 'v-model="forms.bot.name" required' not in html
    assert "Получаю данные" in html


def test_static_ui_does_not_self_close_textareas() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "<textarea" in html
    assert not re.search(r"<textarea\b[^>]*?/>", html)


def test_static_ui_shows_api_errors_for_bot_create() -> None:
    html = _spa_source()

    assert "lastError" in html
    assert "error-banner" in html
    assert "this.lastError = detail" in html
    assert "catch (error)" in html


def test_static_ui_exposes_diagnostic_bot_management() -> None:
    html = _spa_source()

    assert '{ id: "diagnostics", label: "ID-бот", icon: "scan-search"' in html
    assert "activeTab === 'diagnostics'" in html
    assert 'v-model.number="diagnosticSettings.bot_id"' in html
    assert 'v-model="diagnosticSettings.is_enabled"' in html
    assert 'saveDiagnosticSettings' in html
    assert 'this.api("/diagnostics/bot"' in html


def test_static_ui_exposes_mcp_and_api_token_management() -> None:
    html = _spa_source()

    assert '{ id: "mcp", label: "MCP и API", icon: "plug-zap"' in html
    assert "activeTab === 'mcp'" in html
    assert 'activeTab === \'mcp\'" class="stack-layout"' in html
    assert "mcpSubTab === 'tools'" in html
    assert "mcpSettings" in html
    assert "createApiToken" in html
    assert "saveMcpSettings" in html
    assert "tg.sh-inc.ru" in html
    assert "tg.sh-inc.dev" in html


def test_static_ui_exposes_ops_automation_controls() -> None:
    html = _spa_source()

    assert '{ id: "discovery", label: "Ops", icon: "radar"' in html
    for label in [
        "Боты",
        "Адресаты",
        "Шаблоны",
        "Отправка",
        "История",
        "MCP",
        "Конфигурация",
    ]:
        assert label in html
    assert "destination_alias" in html
    assert "Проверить" in html
    assert "copyCurl" in html
    assert "discoverySettings" in html
    assert "auditEvents" in html
    assert "send_mode" in html
    assert "tokenScopes" in html
    assert '"ops_admin"' in html
    assert "Telegram Ops" in html


def test_static_ui_exposes_telegram_ops_control_panel() -> None:
    html = _spa_source()

    for marker in [
        "Факты",
        "Рекомендации",
        "Автоматизация",
        "Журнал действий",
        "MCP покрытие",
        "Preview",
        "Apply",
        "suggest_only",
        "auto_apply",
    ]:
        assert marker in html

    for endpoint in [
        "/ops/facts",
        "/ops/scan",
        "/ops/recommendations",
        "/ops/rules",
        "/ops/action-runs",
        "/ops/mcp-coverage",
    ]:
        assert endpoint in html

    for marker in [
        "updateOpsRule",
        "runOpsRule",
        "pauseOpsRule",
        "resumeOpsRule",
        "ops.rule.updated",
        "ops.rule.ran",
        "ops.rule.paused",
        "ops.rule.resumed",
    ]:
        assert marker in html

    assert ':value="rule.mode"' in html
    assert ':value="rule.risk_limit"' in html
    assert ':checked="rule.is_enabled"' in html
    assert 'v-model="rule.mode"' not in html
    assert 'v-model="rule.risk_limit"' not in html
    assert 'v-model="rule.is_enabled"' not in html


def test_static_ui_contains_tables_and_mcp_scope_controls() -> None:
    html = _spa_source()

    assert "minmax(0, 1fr)" in html
    assert ".table-wrap" in html
    assert 'class="table-wrap"' in html
    assert 'class="tools-table"' in html
    assert 'class="token-scope-grid"' in html
    assert 'class="btn icon-only"' in html


def test_static_ui_uses_operator_console_navigation_patterns() -> None:
    html = _spa_source()

    assert "operator-toolbar" in html
    assert "operator-actions" in html
    assert "status-strip" in html
    assert "stepper" in html
    assert "modal-panel compact-modal" in html
    assert "modal-panel danger-modal" in html
    assert "prefers-reduced-motion" in html


def test_static_ui_prioritizes_sending_platform_navigation() -> None:
    html = _spa_source()

    assert 'activeTab: "send"' in html
    assert "navGroups" in html
    assert "navSections" in html
    assert "workflowStats" in html
    assert 'navAccordionOpenId: "workflow"' in html
    assert "activeNavGroupId" in html
    assert "isNavGroupOpen" in html
    assert "toggleNavGroup" in html
    assert "selectTab" in html
    assert "Платформа отправки" in html
    assert "Рабочий контур" in html
    assert "Контроль" in html
    assert "Интеграции" in html
    assert "Инфраструктура" in html
    assert 'tabIds: ["send", "bots", "destinations", "templates", "history"]' in html
    assert 'class="side-nav"' in html
    assert 'class="nav-product-card"' in html
    assert 'class="nav-product-main"' in html
    assert 'class="nav-session-card"' in html
    assert 'class="nav-section-toggle"' in html
    assert 'v-show="isNavGroupOpen(group)"' in html
    assert '<header>' not in html
    assert "calc(100vh - 56px)" not in html


def test_static_ui_uses_modals_for_bot_and_analytics_creation() -> None:
    html = _spa_source()

    assert "botModalOpen" in html
    assert "openBotModal" in html
    assert "closeBotModal" in html
    assert 'openBotModal() {' in html
    assert 'this.lastError = "";' in html
    assert "analyticsModalOpen" in html
    assert "openAnalyticsModal" in html
    assert "closeAnalyticsModal" in html
    assert 'aria-labelledby="bot-modal-title"' in html
    assert 'aria-labelledby="analytics-modal-title"' in html


def test_static_ui_uses_operator_send_and_history_subtabs() -> None:
    html = _spa_source()

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
        "sendTargetMode",
        "Способ адресации",
        "сохраненный адресат",
        "алиас адресата",
        "ручной chat ID",
        "v-if=\"sendTargetMode.text === 'destination'\"",
        "v-if=\"sendTargetMode.text === 'alias'\"",
        "v-if=\"sendTargetMode.text === 'chat_id'\"",
        "v-if=\"forms.send.send_mode === 'queued'\"",
        "v-if=\"forms.templateSend.send_mode === 'queued'\"",
        "v-if=\"forms.file.send_mode === 'queued'\"",
        "normalizeSendPayload",
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


def test_static_ui_uses_operator_mcp_operations_and_mtproto_layouts() -> None:
    html = _spa_source()

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
        "Поведение",
        "Инфраструктура",
        "Бэкапы",
        "Восстановление",
    ]:
        assert marker in html

    for marker in [
        'mtprotoStep: "phone"',
        "mtprotoStatus: { status: \"missing\"",
        "syncMtprotoStepFromStatus",
        "mtprotoStatusLabel",
        "mtprotoCredentialsConfigured",
        "Открыть my.telegram.org",
        "MTProto не нужен для добавления Bot API токенов",
    ]:
        assert marker in html


def test_static_ui_revoke_token_modal_uses_busy_state_and_finally_cleanup() -> None:
    html = _spa_source()

    assert "tokenRevocationBusy" in html
    assert "this.tokenRevocationBusy = true;" in html
    assert "this.tokenRevocationBusy = false;" in html
    assert ":disabled=\"tokenRevocationBusy\"" in html
    assert "finally" in html


def test_static_ui_is_russian_first_and_explains_mtproto() -> None:
    html = _spa_source()

    assert '<html lang="ru">' in html
    assert "Агрегатор Telegram-ботов" in html
    assert '{ id: "bots", label: "Боты", icon: "bot"' in html
    assert '{ id: "send", label: "Отправка", icon: "send"' in html
    assert "Зачем нужен MTProto" in html
    assert "Запросить код" in html


def test_static_ui_uses_admin_auth_shell_before_dashboard_boot() -> None:
    html = _spa_source()

    for marker in [
        "adminUiReady",
        "adminAuthenticated",
        "loadAdminState",
        "loginAdmin",
        "bootstrapAdmin",
        "logoutAdmin",
        "Вход администратора",
        "Первая настройка",
        "Войти через Touch ID / passkey",
        'v-if="adminUiReady && adminAuthenticated"',
    ]:
        assert marker in html


def test_static_ui_places_admin_passkey_controls_in_infra_settings() -> None:
    html = _spa_source()

    for marker in [
        "adminPasskeys",
        "passkeySupported",
        "passkeyOriginSupported",
        "passkeyOriginHint",
        "beginPasskeyRegistration",
        "loginWithPasskey",
        "deletePasskey",
        "Администратор и Touch ID",
        "Смена логина и пароля обязательна перед активацией Touch ID / passkey.",
        "Для локального Touch ID открой админку через http://localhost:8000",
        "touch ID",
    ]:
        assert marker in html


def test_static_ui_exposes_auth_diagnostics_and_session_controls() -> None:
    html = _spa_source()

    for marker in [
        "adminSessionLabel",
        "Текущая сессия",
        "Auth file",
        "Текущий origin",
        "Текущий RP ID",
        "admin_auth_bootstrap_required",
        "admin_auth_file_exists",
        "admin_auth_file_readable",
        "@click=\"logoutAdmin\"",
        (
            "confirm(\"Удалить этот passkey? Повторный вход через Touch ID придется "
            "подключить заново.\")"
        ),
        (
            "confirm(\"Обновить логин и пароль администратора? Текущая browser-сессия "
            "будет перевыпущена.\")"
        ),
    ]:
        assert marker in html
    assert "любой клиент с доступом к ней сможет пользоваться сохраненной MTProto-сессией" in html
    assert "Сначала укажи Telegram API ID и Telegram API Hash" in html
    assert "MTProto нужен только для аналитики" in html


def test_static_ui_describes_tabs_and_cards() -> None:
    html = _spa_source()

    assert 'class="section-description"' in html
    assert "currentTab.description" in html
    assert 'class="panel-title"' in html
    assert 'class="panel-description"' in html
    assert "Новый бот" in html
    assert "Список адресатов" in html
    assert "Журнал отправок" in html
    assert "Состояние сервиса" in html


def test_static_ui_uses_destination_modal_and_full_width_list() -> None:
    html = _spa_source()

    assert 'activeTab === \'destinations\'" class="stack-layout"' in html
    assert 'class="panel full-span"' in html
    assert '@click="openDestinationModal"' in html
    assert 'v-if="destinationModalOpen"' in html
    assert 'class="modal-overlay"' in html
    assert 'class="modal-panel"' in html
    assert '@click.self="closeDestinationModal"' in html
    assert '@click="closeDestinationModal"' in html
    assert "openDestinationModal" in html
    assert "closeDestinationModal" in html
    assert "deleteDestination" in html
    assert "Удалить адресата" in html
    assert 'method: "DELETE"' in html


def test_static_ui_uses_dropdowns_for_fixed_choices() -> None:
    html = _spa_source()

    assert "parseModeOptions" in html
    assert 'v-model="forms.template.parse_mode"' in html
    assert 'v-model="forms.send.parse_mode"' in html
    assert 'v-model="forms.file.parse_mode"' in html
    assert 'v-model="forms.templateSend.tag"' in html
    assert 'v-for="item in templates"' in html
    assert 'value: "MarkdownV2"' in html


def test_static_ui_exposes_template_send_flow() -> None:
    html = _spa_source()

    assert "Отправка по шаблону" in html
    assert "forms.templateSend" in html
    assert "sendTemplate" in html
    assert 'this.api("/send/template"' in html
    assert 'this.api("/send/template/dry-run"' in html
    assert 'template: "/api/v1/send/template"' in html


def test_static_ui_exposes_mcp_connection_helper_and_media_browser() -> None:
    html = _spa_source()

    assert "connection-info" in html
    assert "Подключение MCP" in html
    assert "mediaItems" in html
    assert "selectMediaFile" in html


def test_static_ui_disables_file_send_when_shared_media_is_unavailable() -> None:
    html = _spa_source()

    assert "fileSendAvailable" in html
    assert "fileSendUnavailableReason" in html
    assert ':disabled="!fileSendAvailable"' in html
    assert "Отправка файлов отключена" in html


def test_static_ui_uses_template_subtabs_for_saved_and_create() -> None:
    html = _spa_source()

    assert 'templateSubTab: "saved"' in html
    assert 'class="subtabs"' in html
    assert 'templateSubTab === \'saved\'' in html
    assert 'templateSubTab === \'create\'' in html
    assert '@click="templateSubTab = \'saved\'"' in html
    assert '@click="templateSubTab = \'create\'"' in html
    assert "Сохраненные шаблоны" in html
    assert "Новый шаблон" in html


def test_static_ui_uses_send_subtabs_for_send_modes() -> None:
    html = _spa_source()

    assert 'sendSubTab: "text"' in html
    assert 'aria-label="Отправка"' in html
    assert 'sendSubTab === \'text\'' in html
    assert 'sendSubTab === \'template\'' in html
    assert 'sendSubTab === \'file\'' in html
    assert '@click="sendSubTab = \'text\'"' in html
    assert '@click="sendSubTab = \'template\'"' in html
    assert '@click="fileSendAvailable && (sendWorkTab = \'file\', sendSubTab = \'file\')"' in html
    assert "Ручной текст" in html
    assert "По шаблону" in html
    assert "Файл с шары" in html


def test_static_ui_explains_and_validates_templates() -> None:
    html = _spa_source()

    assert "Как правильно писать шаблоны" in html
    assert "{{name}}" in html
    assert "Проверочные переменные" in html
    assert "Проверить шаблон" in html
    assert "templateValidation" in html
    assert "validateTemplate" in html
    assert "templateValidationError" in html
    assert 'this.api("/templates/validate"' in html


def test_static_ui_exposes_send_profiles_preview_retry_and_cancel() -> None:
    html = _spa_source()

    assert "Профили отправки" in html
    assert "sendProfiles" in html
    assert "applySendProfile" in html
    assert "createSendProfile" in html
    assert 'this.api("/send/preview"' in html
    assert "previewCurrentSend" in html
    assert "retrySendHistory" in html
    assert "cancelSendHistory" in html
    assert "/retry" in html
    assert "/cancel" in html


def test_static_ui_exposes_batches_and_diagnostic_update_destination_flow() -> None:
    html = _spa_source()

    assert "Batch-отправка" in html
    assert "sendBatches" in html
    assert "createSendBatch" in html
    assert "previewSendBatch" in html
    assert "enqueueSendBatch" in html
    assert "cancelSendBatch" in html
    assert "diagnosticUpdates" in html
    assert "createDestinationFromDiagnosticUpdate" in html
    assert 'this.api("/diagnostics/updates"' in html
    assert "/destination" in html


def test_static_ui_exposes_operations_backup_preflight_and_versions() -> None:
    html = _spa_source()

    assert '{ id: "operations", label: "Конфигурация", icon: "settings-2"' in html
    assert "Поведение отправки без рестарта" in html
    assert "JSON backup в git" in html
    assert 'v-model="operationsSettings.backup_git_repo_url"' in html
    assert 'v-model="operationsSettings.backup_git_service"' in html
    assert 'v-model="operationsSettings.backup_git_auth_method"' in html
    assert 'v-model="operationsSettings.backup_git_api_base_url"' in html
    assert 'v-model="operationsSettings.backup_git_api_token"' in html
    assert "GitHub" in html
    assert "Gitea" in html
    assert "API token / PAT" in html
    assert "OAuth не нужен" in html
    assert "checkBackupRepository" in html
    assert 'this.api("/operations/backup/check-repo"' in html
    assert "runBackupPreflight" in html
    assert "backupPreflight" in html
    assert "backupDiff" in html
    assert "backupImport" in html
    assert "restoreWizard" in html
    assert "sectionOptions" in html
    assert "previewBackupImport" in html
    assert "applyBackupImport" in html
    assert "previewBackupRunRestore" in html


def test_static_ui_exposes_reliability_graph_and_preserves_existing_tabs() -> None:
    html = _spa_source()

    assert '{ id: "reliability", label: "Надежность", icon: "activity"' in html
    assert "reliabilityGraph" in html
    assert "reliabilitySummary" in html
    assert "reliabilityNode" in html
    assert "Batch / Manual" in html
    assert "Policy gate" in html
    assert "Worker lease" in html
    assert "Bot bucket" in html
    assert "Chat bucket" in html
    assert "Telegram" in html
    assert "Result" in html
    assert "@keyframes edgeFlow" in html
    assert "repeat(7, 140px)" not in html
    assert '{ id: "source", label: "Batch / Manual"' in html
    assert '{ id: "queue", label: "Queue"' in html

    for tab in [
        "Боты",
        "Адресаты",
        "Шаблоны",
        "Отправка",
        "Журнал",
        "MTProto",
        "Аналитика",
        "ID-бот",
        "Ops",
        "MCP",
        "Аудит",
        "Конфигурация",
        "Состояние",
    ]:
        assert tab in html


def test_static_ui_uses_snake_layout_for_reliability_graph() -> None:
    html = _spa_source()

    assert "reliability-graph-snake" in html
    assert "reliability-graph-row" in html
    assert "reliability-node-slot" in html
    assert "reliability-graph-turn-row" in html
    assert "reliability-inspector-grid" in html
    assert "reliabilityGraphRows()" in html
    assert "reliabilityRowEdge" in html
    assert "reliabilityRowTurn" in html
    assert "grid-auto-flow: column" not in html
    assert "reliability-legend" not in html


def test_static_ui_reliability_calls_new_api_and_keeps_history_actions() -> None:
    html = _spa_source()

    assert 'this.api("/reliability/summary"' in html
    assert 'this.api("/reliability/graph"' in html
    assert 'this.api("/reliability/attempts"' in html
    assert 'this.api("/reliability/stale-locks/release"' in html
    assert "edge.from || edge.source" in html
    assert "edge.to || edge.target" in html
    assert "reliabilityAttemptMatchesNode" in html
    assert '["source", "queue", "worker", "result"].includes(nodeId)' in html
    assert "matched.length ? matched : this.reliabilityAttempts" in html
    assert "retrySendHistory" in html
    assert "cancelSendHistory" in html
    assert "deadLetter" in html
    assert "dueHistory" in html
    assert "applyBackupRunRestore" in html
    assert 'this.api("/operations/backup/import/preview"' in html
    assert 'this.api("/operations/backup/import/apply"' in html
    assert "restore-preview" in html
    assert "rowDiffRows" in html
    assert "Импорт backup JSON" in html
    assert "Restore wizard" in html
    assert "Частичный restore" in html
    assert "Адресаты требуют существующих ботов" in html
    assert "restoreWizard.preview.warnings" in html
    assert "Визуальный diff" in html
    assert "Safety backup" in html
    assert "RESTORE" in html
    assert 'v-model="operationsSettings.backup_schedule_enabled"' in html
    assert 'v-model.number="operationsSettings.backup_schedule_interval_seconds"' in html
    assert 'v-model="operationsSettings.backup_schedule_push_to_git"' in html
    assert "Плановый backup" in html
    assert 'this.api("/operations/backup/preflight"' in html
    assert 'this.api("/operations/backup/diff"' in html
    assert "Секреты уходят в git" in html
    assert "Backup status" in html
    assert "private repo" in html
    assert "секреты автоматически" in html
    assert 'this.api("/operations/settings"' in html
    assert 'this.api("/operations/backup/run"' in html
    assert 'this.api("/send/preflight"' in html
    assert "deadLetter" in html
    assert "dueHistory" in html
    assert "destinationHealth" in html
    assert "templateVersions" in html
    assert "rollbackTemplate" in html
    assert "batchProgressLabel" in html
    assert 'v-model="forms.send.send_at"' in html


def test_static_ui_renders_health_as_cards_and_exposes_local_secrets() -> None:
    html = _spa_source()

    assert 'class="health-grid"' in html
    assert "Статус API" in html
    assert "Shared media" in html
    assert "Telegram Bot API" in html
    assert "JSON.stringify(health, null, 2)" not in html
    assert 'v-model="operationsSettings.database_url"' in html
    assert 'v-model="operationsSettings.redis_url"' in html
    assert 'v-model="operationsSettings.telegram_api_id"' in html
    assert 'v-model="operationsSettings.telegram_api_hash"' in html
    assert 'type="password"' in html
    assert "Инфраструктура и секреты" in html


def test_static_ui_operations_uses_settings_ux_with_dependent_fields() -> None:
    html = _spa_source()

    assert '{ id: "operations", label: "Конфигурация", icon: "settings-2"' in html
    assert "Поведение" in html
    assert "Инфраструктура" in html
    assert "Бэкапы" in html
    assert "Восстановление" in html
    assert "operations-layout" in html
    assert "operations-card-grid" in html
    assert "Telegram transport" in html
    assert "Shared media" in html
    assert "Retry и delivery" in html
    assert "Policy и quiet hours" in html
    assert "Callback" in html
    assert "formatQuietHoursInput" in html
    assert "applyBackupServiceDefaults" in html
    assert "applyMaxLocalFilePreset" in html
    assert 'v-if="operationsSettings.policy_enabled"' in html
    assert 'v-if="operationsSettings.callback_enabled"' in html
    assert 'v-if="operationsSettings.backup_schedule_enabled"' in html
    assert 'v-if="operationsSettings.backup_git_auth_method !== \'none\'"' in html
    assert 'v-model="operationsSettings.send_default_mode"' in html
    assert 'inputmode="numeric"' in html
    assert 'maxlength="5"' in html


def test_static_ui_exposes_telegram_connectivity_controls() -> None:
    html = _spa_source()

    for marker in [
        "Telegram connectivity",
        "telegramEgressState",
        "telegramEgressDraft",
        "telegramEgressConfig",
        "/operations/telegram-egress",
        "/operations/telegram-egress/config",
        "/operations/telegram-egress/check",
        "/operations/telegram-egress/connect",
        "/operations/telegram-egress/disconnect",
        "/operations/telegram-egress/restart",
        "saveTelegramEgressSettings",
        "uploadTelegramEgressConfig",
        "checkTelegramEgress",
        "connectTelegramEgress",
        "disconnectTelegramEgress",
        "restartTelegramEgress",
        "normalizeTelegramEgressDraft",
        "OpenVPN lifecycle сейчас валидирует профиль, хранит конфиг и отдает статус.",
    ]:
        assert marker in html

    assert "полноценный lifecycle будет включен следующим срезом" not in html
