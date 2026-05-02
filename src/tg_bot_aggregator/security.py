import re
from collections.abc import Mapping, Sequence
from typing import Any

SECRET_KEYS = {"token", "authorization", "password", "api_hash", "telegram_api_hash"}
REDACTED = "[REDACTED]"
BOT_URL_RE = re.compile(r"/bot([^/\s]+)/")
TOKEN_RE = re.compile(r"\b\d{5,}:[A-Za-z0-9_-]{16,}\b")


def redact_text(value: str) -> str:
    value = BOT_URL_RE.sub(f"/bot{REDACTED}/", value)
    return TOKEN_RE.sub(REDACTED, value)


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

