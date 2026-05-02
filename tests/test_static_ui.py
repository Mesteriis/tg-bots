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
    assert "Runtime health" in html


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
