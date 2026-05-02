from pathlib import Path


def test_static_ui_uses_vue_api_and_events() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()

    assert "https://unpkg.com/vue@3" in html
    assert "/api/v1" in html
    assert 'new EventSource("/api/v1/events")' in html
    assert "auth" not in html.lower()
