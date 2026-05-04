from tg_bot_aggregator.core.security import (
    REDACTED,
    RedactBotTokenAccessLogFilter,
    host_matches,
    is_allowed_origin,
    is_protected_host_request,
    redact_secrets,
    redact_text,
)


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


def test_protected_host_detection_uses_host_or_origin() -> None:
    protected = ["tg.sh-inc.ru", "tg.sh-inc.dev"]

    assert host_matches("tg.sh-inc.ru:443", protected) is True
    assert host_matches("127.0.0.1:8000", protected) is False
    assert (
        is_protected_host_request(
            host="127.0.0.1:8000",
            origin="https://tg.sh-inc.dev",
            protected_hosts=protected,
        )
        is True
    )


def test_access_log_filter_redacts_telegram_compatible_bot_token() -> None:
    import logging

    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "127.0.0.1:1",
            "POST",
            "/bot123456:ABCdef_123456789012345/sendMessage",
            "1.1",
            200,
        ),
        exc_info=None,
    )

    RedactBotTokenAccessLogFilter().filter(record)

    assert "123456:ABCdef" not in record.args[2]
    assert REDACTED in record.args[2]


def test_origin_validation_allows_missing_origin_and_configured_origins() -> None:
    assert is_allowed_origin(None, ["http://localhost:8000"]) is True
    assert is_allowed_origin("http://localhost:8000", ["http://localhost:8000"]) is True
    assert is_allowed_origin("http://evil.test", ["http://localhost:8000"]) is False
