from tg_bot_aggregator.security import REDACTED, is_allowed_origin, redact_secrets, redact_text


def test_redact_text_removes_bot_token_from_url_and_plain_text() -> None:
    value = "http://telegram-bot-api:8081/bot123456:ABCdef_123456789012345/sendMessage"

    assert "123456:ABCdef" not in redact_text(value)
    assert REDACTED in redact_text(value)


def test_redact_secrets_handles_nested_payloads() -> None:
    payload = {
        "token": "123456:ABCdef_123456789012345",
        "nested": [{"url": "/bot123456:ABCdef_123456789012345/sendMessage"}],
    }

    redacted = redact_secrets(payload)

    assert redacted["token"] == REDACTED
    assert REDACTED in redacted["nested"][0]["url"]


def test_origin_validation_allows_missing_origin_and_configured_origins() -> None:
    assert is_allowed_origin(None, ["http://localhost:8000"]) is True
    assert is_allowed_origin("http://localhost:8000", ["http://localhost:8000"]) is True
    assert is_allowed_origin("http://evil.test", ["http://localhost:8000"]) is False

