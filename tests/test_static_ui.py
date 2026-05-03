from pathlib import Path


def test_static_ui_uses_vue_api_and_events() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "https://unpkg.com/vue@3" in html
    assert "/api/v1" in html
    assert 'new EventSource("/api/v1/events")' in html
    assert "apiToken" in html


def test_static_ui_uses_onedark_motion_and_token_first_bot_flow() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "#282c34" in html
    assert "#61afef" in html
    assert "@keyframes panelIn" in html
    assert "prefers-reduced-motion" in html
    assert 'placeholder="@username после проверки"' in html
    assert 'v-model="forms.bot.name"' in html
    assert 'v-model="forms.bot.name" required' not in html
    assert "Получаю данные" in html


def test_static_ui_shows_api_errors_for_bot_create() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "lastError" in html
    assert "error-banner" in html
    assert "this.lastError = detail" in html
    assert "catch (error)" in html


def test_static_ui_exposes_diagnostic_bot_management() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert '{ id: "diagnostics", label: "Диагностика", icon: "scan-search"' in html
    assert "activeTab === 'diagnostics'" in html
    assert 'v-model.number="diagnosticSettings.bot_id"' in html
    assert 'v-model="diagnosticSettings.is_enabled"' in html
    assert 'saveDiagnosticSettings' in html
    assert 'this.api("/diagnostics/bot"' in html


def test_static_ui_exposes_mcp_and_api_token_management() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert '{ id: "mcp", label: "MCP", icon: "plug-zap"' in html
    assert "activeTab === 'mcp'" in html
    assert 'activeTab === \'mcp\'" class="grid settings-grid"' in html
    assert "mcpSettings" in html
    assert "createApiToken" in html
    assert "saveMcpSettings" in html
    assert "tg.sh-inc.ru" in html
    assert "tg.sh-inc.dev" in html


def test_static_ui_exposes_ops_automation_controls() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "destination_alias" in html
    assert "Проверить" in html
    assert "copyCurl" in html
    assert "discoverySettings" in html
    assert "auditEvents" in html
    assert "send_mode" in html
    assert "tokenScopes" in html


def test_static_ui_contains_tables_and_mcp_scope_controls() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "minmax(0, 1fr)" in html
    assert ".table-wrap" in html
    assert 'class="table-wrap"' in html
    assert 'class="tools-table"' in html
    assert 'class="token-scope-grid"' in html
    assert 'class="btn icon-only"' in html


def test_static_ui_is_russian_first_and_explains_mtproto() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert '<html lang="ru">' in html
    assert "Агрегатор Telegram-ботов" in html
    assert '{ id: "bots", label: "Боты", icon: "bot"' in html
    assert '{ id: "send", label: "Отправка", icon: "send"' in html
    assert "Зачем нужен MTProto" in html
    assert "Запросить код" in html
    assert "любой клиент с доступом к ней сможет пользоваться сохраненной MTProto-сессией" in html


def test_static_ui_describes_tabs_and_cards() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert 'class="section-description"' in html
    assert "currentTab.description" in html
    assert 'class="panel-title"' in html
    assert 'class="panel-description"' in html
    assert "Новый бот" in html
    assert "Список адресатов" in html
    assert "Журнал отправок" in html
    assert "Состояние сервиса" in html


def test_static_ui_uses_destination_modal_and_full_width_list() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

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


def test_static_ui_uses_dropdowns_for_fixed_choices() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "parseModeOptions" in html
    assert 'v-model="forms.template.parse_mode"' in html
    assert 'v-model="forms.send.parse_mode"' in html
    assert 'v-model="forms.file.parse_mode"' in html
    assert 'v-model="forms.templateSend.tag"' in html
    assert 'v-for="item in templates"' in html
    assert 'value: "MarkdownV2"' in html


def test_static_ui_exposes_template_send_flow() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "Отправка по шаблону" in html
    assert "forms.templateSend" in html
    assert "sendTemplate" in html
    assert 'this.api("/send/template"' in html
    assert 'this.api("/send/template/dry-run"' in html
    assert 'template: "/api/v1/send/template"' in html


def test_static_ui_exposes_mcp_connection_helper_and_media_browser() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "connection-info" in html
    assert "Подключение MCP" in html
    assert "mediaItems" in html
    assert "selectMediaFile" in html


def test_static_ui_disables_file_send_when_shared_media_is_unavailable() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "fileSendAvailable" in html
    assert "fileSendUnavailableReason" in html
    assert ':disabled="!fileSendAvailable"' in html
    assert "Отправка файлов отключена" in html


def test_static_ui_uses_template_subtabs_for_saved_and_create() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert 'templateSubTab: "saved"' in html
    assert 'class="subtabs"' in html
    assert 'templateSubTab === \'saved\'' in html
    assert 'templateSubTab === \'create\'' in html
    assert '@click="templateSubTab = \'saved\'"' in html
    assert '@click="templateSubTab = \'create\'"' in html
    assert "Сохраненные шаблоны" in html
    assert "Новый шаблон" in html


def test_static_ui_uses_send_subtabs_for_send_modes() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert 'sendSubTab: "text"' in html
    assert 'aria-label="Отправка"' in html
    assert 'sendSubTab === \'text\'' in html
    assert 'sendSubTab === \'template\'' in html
    assert 'sendSubTab === \'file\'' in html
    assert '@click="sendSubTab = \'text\'"' in html
    assert '@click="sendSubTab = \'template\'"' in html
    assert '@click="fileSendAvailable && (sendSubTab = \'file\')"' in html
    assert "Ручной текст" in html
    assert "По шаблону" in html
    assert "Файл с шары" in html


def test_static_ui_explains_and_validates_templates() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "Как правильно писать шаблоны" in html
    assert "{{name}}" in html
    assert "Проверочные переменные" in html
    assert "Проверить шаблон" in html
    assert "templateValidation" in html
    assert "validateTemplate" in html
    assert "templateValidationError" in html
    assert 'this.api("/templates/validate"' in html


def test_static_ui_exposes_send_profiles_preview_retry_and_cancel() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

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
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

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
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert '{ id: "operations", label: "Операции", icon: "settings-2"' in html
    assert "Runtime-настройки без рестарта" in html
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
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

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

    for tab in [
        "Боты",
        "Адресаты",
        "Шаблоны",
        "Отправка",
        "История",
        "MTProto",
        "Аналитика",
        "Диагностика",
        "Автопоиск",
        "MCP",
        "Аудит",
        "Операции",
        "Состояние",
    ]:
        assert tab in html


def test_static_ui_reliability_calls_new_api_and_keeps_history_actions() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert 'this.api("/reliability/summary"' in html
    assert 'this.api("/reliability/graph"' in html
    assert 'this.api("/reliability/attempts"' in html
    assert 'this.api("/reliability/stale-locks/release"' in html
    assert "edge.from || edge.source" in html
    assert "edge.to || edge.target" in html
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
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

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
    assert "Локальные секреты" in html
