from pathlib import Path


def test_static_ui_uses_vue_api_and_events() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "https://unpkg.com/vue@3" in html
    assert "/api/v1" in html
    assert 'new EventSource("/api/v1/events")' in html
    assert "auth" not in html.lower()


def test_static_ui_uses_onedark_motion_and_token_first_bot_flow() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "#282c34" in html
    assert "#61afef" in html
    assert "@keyframes panelIn" in html
    assert "prefers-reduced-motion" in html
    assert 'placeholder="@username after check"' in html
    assert 'v-model="forms.bot.name"' in html
    assert 'v-model="forms.bot.name" required' not in html
    assert "Fetching metadata" in html


def test_static_ui_shows_api_errors_for_bot_create() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "lastError" in html
    assert "error-banner" in html
    assert "this.lastError = detail" in html
    assert "catch (error)" in html


def test_static_ui_exposes_diagnostic_bot_management() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert '{ id: "diagnostics", label: "Diagnostics", icon: "scan-search" }' in html
    assert "activeTab === 'diagnostics'" in html
    assert 'v-model.number="diagnosticSettings.bot_id"' in html
    assert 'v-model="diagnosticSettings.is_enabled"' in html
    assert 'saveDiagnosticSettings' in html
    assert 'this.api("/diagnostics/bot"' in html
