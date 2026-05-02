import hashlib
import secrets

API_TOKEN_PREFIX = "tga_"
API_TOKEN_COOKIE = "tg_api_token"
API_TOKEN_HEADER = "X-API-Token"
API_TOKEN_SCOPES = ("read", "send", "mcp_admin", "tg_compat")


def generate_api_token() -> str:
    return f"{API_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def api_token_prefix(token: str) -> str:
    return token[:12]


def normalize_token_scopes(scopes: list[str] | None) -> list[str]:
    if not scopes:
        return list(API_TOKEN_SCOPES)
    allowed = set(API_TOKEN_SCOPES)
    return [scope for scope in scopes if scope in allowed]
