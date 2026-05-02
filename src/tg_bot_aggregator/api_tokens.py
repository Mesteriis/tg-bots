import hashlib
import secrets

API_TOKEN_PREFIX = "tga_"
API_TOKEN_COOKIE = "tg_api_token"
API_TOKEN_HEADER = "X-API-Token"


def generate_api_token() -> str:
    return f"{API_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def api_token_prefix(token: str) -> str:
    return token[:12]
