from tg_bot_aggregator.config import Settings


def test_settings_defaults_are_local_and_versioned() -> None:
    settings = Settings()

    assert settings.app_host == "127.0.0.1"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.mcp_v1_prefix == "/mcp/v1"
    assert settings.shared_media_root == "/shared/media"
    assert settings.telegram_bot_api_base_url == "http://telegram-bot-api:8081"
    assert settings.max_local_file_bytes == 2_097_152_000
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

