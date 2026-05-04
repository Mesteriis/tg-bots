import logging
import re
from collections.abc import Mapping, Sequence
from logging import Filter, LogRecord
from typing import Any
from urllib.parse import urlparse

SECRET_KEYS = {"token", "authorization", "password", "api_hash", "telegram_api_hash"}
REDACTED = "[REDACTED]"
BOT_URL_RE = re.compile(r"/bot([^/\s]+)/")
TOKEN_RE = re.compile(r"\b\d{5,}:[A-Za-z0-9_-]{16,}\b")


def redact_text(value: str) -> str:
    value = BOT_URL_RE.sub(f"/bot{REDACTED}/", value)
    return TOKEN_RE.sub(REDACTED, value)


class RedactBotTokenAccessLogFilter(Filter):
    def filter(self, record: LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_text(item) if isinstance(item, str) else item for item in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: redact_text(item) if isinstance(item, str) else item
                for key, item in record.args.items()
            }
        return True


def install_secret_log_filters() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, RedactBotTokenAccessLogFilter) for item in access_logger.filters):
        access_logger.addFilter(RedactBotTokenAccessLogFilter())


def redact_secrets(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SECRET_KEYS:
                redacted[key] = REDACTED
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list | tuple):
        return [redact_secrets(item) for item in value]
    return value


def is_allowed_origin(origin: str | None, allowed_origins: Sequence[str]) -> bool:
    if origin is None:
        return True
    return origin in allowed_origins


def normalize_host(value: str | None) -> str | None:
    if value is None:
        return None
    first = value.split(",", 1)[0].strip()
    if not first:
        return None
    parsed = urlparse(first if "://" in first else f"//{first}")
    return parsed.hostname.lower() if parsed.hostname else None


def host_matches(host: str | None, protected_hosts: Sequence[str]) -> bool:
    normalized = normalize_host(host)
    if normalized is None:
        return False
    for protected in protected_hosts:
        candidate = protected.strip().lower()
        if not candidate:
            continue
        if candidate == normalized:
            return True
        if candidate.startswith("*.") and normalized.endswith(candidate[1:]):
            return True
        if candidate.endswith(".*") and normalized.startswith(candidate[:-1]):
            return True
    return False


def is_protected_host_request(
    host: str | None,
    origin: str | None,
    protected_hosts: Sequence[str],
) -> bool:
    return host_matches(host, protected_hosts) or host_matches(origin, protected_hosts)
