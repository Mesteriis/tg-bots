import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
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


def generate_secret_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return f"scrypt$16384$8$1${base64url_encode(salt)}${base64url_encode(derived)}"


def verify_password_hash(password: str, encoded: str) -> bool:
    try:
        algorithm, n_value, r_value, p_value, salt_b64, digest_b64 = encoded.split("$", 5)
    except ValueError:
        return False
    if algorithm != "scrypt":
        return False
    try:
        salt = base64url_decode(salt_b64)
        expected = base64url_decode(digest_b64)
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_value),
            r=int(r_value),
            p=int(p_value),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, expected)


def sign_json_value(payload: Mapping[str, Any], secret: str) -> str:
    body = base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{base64url_encode(signature)}"


def verify_signed_json_value(token: str, secret: str) -> dict[str, Any] | None:
    try:
        body, signature = token.split(".", 1)
    except ValueError:
        return None
    expected = base64url_encode(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        return json.loads(base64url_decode(body).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


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
