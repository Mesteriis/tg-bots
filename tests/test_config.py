from pathlib import Path

from tg_bot_aggregator.core.config import Settings


def test_settings_defaults_are_local_and_versioned() -> None:
    settings = Settings()

    assert settings.app_host == "127.0.0.1"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.mcp_v1_prefix == "/mcp/v1"
    assert settings.shared_media_root == "/shared/media"
    assert settings.telegram_bot_api_base_url == "http://telegram-bot-api:8081"
    assert settings.max_local_file_bytes == 2_097_152_000
    assert settings.diagnostic_poll_timeout_seconds == 30
    assert settings.diagnostic_retry_delay_seconds == 5.0
    assert settings.protected_api_hosts == ["tg.sh-inc.ru", "tg.sh-inc.dev"]
    assert settings.is_local_bot_api is True


def test_settings_parse_csv_origins() -> None:
    settings = Settings(
        CORS_ALLOWED_ORIGINS="http://localhost:8000,http://127.0.0.1:8000",
        MCP_ALLOWED_ORIGINS="http://localhost:8000",
    )

    assert settings.cors_allowed_origins == [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    assert settings.mcp_allowed_origins == ["http://localhost:8000"]


def test_settings_parse_csv_origins_from_environment(monkeypatch) -> None:
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000",
    )
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "http://localhost:8000")
    monkeypatch.setenv("PROTECTED_API_HOSTS", "tg.sh-inc.ru,tg.sh-inc.dev")

    settings = Settings()

    assert settings.cors_allowed_origins == [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    assert settings.mcp_allowed_origins == ["http://localhost:8000"]
    assert settings.protected_api_hosts == ["tg.sh-inc.ru", "tg.sh-inc.dev"]


def test_settings_parse_protected_api_hosts() -> None:
    settings = Settings(PROTECTED_API_HOSTS="tg.sh-inc.ru,tg.sh-inc.dev")

    assert settings.protected_api_hosts == ["tg.sh-inc.ru", "tg.sh-inc.dev"]


def test_diagnostic_bot_is_wired_in_compose_env_and_docs() -> None:
    compose = Path("docker-compose.yml").read_text()
    env_example = Path(".env.example").read_text()
    readme = Path("README.md").read_text()

    assert "diagnostic-bot:" in compose
    assert 'python", "-m", "tg_bot_aggregator.domain.diagnostics.bot' in compose
    assert "DIAGNOSTIC_POLL_TIMEOUT_SECONDS" in env_example
    assert "DIAGNOSTIC_RETRY_DELAY_SECONDS" in env_example
    assert "Diagnostic Polling Bot" in readme
    assert "/api/v1/diagnostics/bot" in readme
