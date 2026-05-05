from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.core.security import (
    generate_secret_token,
    hash_password,
    sign_json_value,
    verify_password_hash,
    verify_signed_json_value,
)

ADMIN_DEFAULT_USERNAME = "admin"
ADMIN_DEFAULT_PASSWORD = "12345678"
ADMIN_SESSION_COOKIE = "tg_admin_session"


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class AdminPasskeyCredential:
    credential_id: str
    public_key: str
    sign_count: int
    rp_id: str
    transports: list[str] = field(default_factory=list)
    label: str | None = None
    created_at: str | None = None
    last_used_at: str | None = None


@dataclass(slots=True)
class AdminAuthRecord:
    username: str
    password_hash: str
    must_rotate: bool
    session_secret: str
    session_version: int
    user_handle: str
    passkeys: list[AdminPasskeyCredential] = field(default_factory=list)
    updated_at: str | None = None


@dataclass(slots=True)
class AdminState:
    authenticated: bool
    username: str
    bootstrap_required: bool
    passkey_configured: bool
    auth_mode: str


@dataclass(slots=True)
class AdminAuthDiagnostics:
    auth_file_path: str
    auth_file_exists: bool
    auth_file_readable: bool
    bootstrap_required: bool
    username: str
    passkey_configured: bool


class AdminAuthError(Exception):
    pass


class InvalidCredentialsError(AdminAuthError):
    pass


class BootstrapRequiredError(AdminAuthError):
    pass


class AdminAuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = Path(settings.effective_admin_auth_file)

    def state_from_session_token(self, token: str | None) -> AdminState:
        record = self._load_record()
        bootstrap_required = record is None or record.must_rotate
        if token is None or record is None:
            return AdminState(
                authenticated=False,
                username=ADMIN_DEFAULT_USERNAME if record is None else record.username,
                bootstrap_required=bootstrap_required,
                passkey_configured=bool(record and record.passkeys),
                auth_mode="bootstrap" if bootstrap_required else "password",
            )
        payload = verify_signed_json_value(token, record.session_secret)
        if not payload:
            return AdminState(
                authenticated=False,
                username=record.username,
                bootstrap_required=bootstrap_required,
                passkey_configured=bool(record.passkeys),
                auth_mode="bootstrap" if bootstrap_required else "password",
            )
        expires_at = payload.get("exp")
        if not isinstance(expires_at, int) or expires_at < int(utc_now().timestamp()):
            return AdminState(
                authenticated=False,
                username=record.username,
                bootstrap_required=bootstrap_required,
                passkey_configured=bool(record.passkeys),
                auth_mode="bootstrap" if bootstrap_required else "password",
            )
        if (
            payload.get("sub") != record.username
            or payload.get("ver") != record.session_version
            or bootstrap_required
        ):
            return AdminState(
                authenticated=False,
                username=record.username,
                bootstrap_required=bootstrap_required,
                passkey_configured=bool(record.passkeys),
                auth_mode="bootstrap" if bootstrap_required else "password",
            )
        return AdminState(
            authenticated=True,
            username=record.username,
            bootstrap_required=False,
            passkey_configured=bool(record.passkeys),
            auth_mode="password",
        )

    def diagnostics(self) -> AdminAuthDiagnostics:
        auth_file_exists = self.path.exists()
        auth_file_readable = False
        record = None
        if auth_file_exists:
            try:
                self.path.read_text(encoding="utf-8")
                auth_file_readable = True
            except OSError:
                auth_file_readable = False
            record = self._load_record()
        bootstrap_required = record is None or record.must_rotate
        return AdminAuthDiagnostics(
            auth_file_path=str(self.path),
            auth_file_exists=auth_file_exists,
            auth_file_readable=auth_file_readable,
            bootstrap_required=bootstrap_required,
            username=record.username if record else ADMIN_DEFAULT_USERNAME,
            passkey_configured=bool(record and record.passkeys),
        )

    def verify_login(self, username: str, password: str) -> tuple[AdminState, str | None]:
        record = self._load_record()
        if record is None or record.must_rotate:
            if username != ADMIN_DEFAULT_USERNAME or password != ADMIN_DEFAULT_PASSWORD:
                raise InvalidCredentialsError("invalid username or password")
            return (
                AdminState(
                    authenticated=False,
                    username=ADMIN_DEFAULT_USERNAME,
                    bootstrap_required=True,
                    passkey_configured=False,
                    auth_mode="bootstrap",
                ),
                None,
            )
        if username != record.username or not verify_password_hash(password, record.password_hash):
            raise InvalidCredentialsError("invalid username or password")
        token = self.create_session_token(record)
        return self.state_from_session_token(token), token

    def bootstrap_rotate(
        self,
        current_username: str,
        current_password: str,
        new_username: str,
        new_password: str,
    ) -> tuple[AdminState, str]:
        if current_username != ADMIN_DEFAULT_USERNAME or current_password != ADMIN_DEFAULT_PASSWORD:
            raise InvalidCredentialsError("invalid bootstrap credentials")
        record = AdminAuthRecord(
            username=new_username,
            password_hash=hash_password(new_password),
            must_rotate=False,
            session_secret=generate_secret_token(),
            session_version=1,
            user_handle=generate_secret_token(16),
            passkeys=[],
            updated_at=utc_now().isoformat(),
        )
        self._write_record(record)
        token = self.create_session_token(record)
        return self.state_from_session_token(token), token

    def create_session_token(self, record: AdminAuthRecord) -> str:
        expires_at = utc_now() + timedelta(seconds=self.settings.admin_session_ttl_seconds)
        return sign_json_value(
            {
                "sub": record.username,
                "ver": record.session_version,
                "exp": int(expires_at.timestamp()),
            },
            record.session_secret,
        )

    def require_authenticated(self, token: str | None) -> AdminState:
        state = self.state_from_session_token(token)
        if not state.authenticated:
            raise InvalidCredentialsError("admin session required")
        return state

    def require_configured_record(self) -> AdminAuthRecord:
        record = self._load_record()
        if record is None or record.must_rotate:
            raise BootstrapRequiredError("bootstrap rotation required")
        return record

    def change_credentials(
        self,
        current_password: str,
        new_username: str,
        new_password: str,
    ) -> tuple[AdminState, str]:
        record = self._load_record()
        if record is None or record.must_rotate:
            raise BootstrapRequiredError("bootstrap rotation required")
        if not verify_password_hash(current_password, record.password_hash):
            raise InvalidCredentialsError("invalid current password")
        record.username = new_username
        record.password_hash = hash_password(new_password)
        record.session_version += 1
        record.updated_at = utc_now().isoformat()
        self._write_record(record)
        token = self.create_session_token(record)
        return self.state_from_session_token(token), token

    def list_passkeys(self) -> list[AdminPasskeyCredential]:
        record = self._load_record()
        if record is None:
            return []
        return list(record.passkeys)

    def list_passkeys_for_rp(self, rp_id: str) -> list[AdminPasskeyCredential]:
        return [item for item in self.list_passkeys() if item.rp_id == rp_id]

    def get_passkey(self, credential_id: str, rp_id: str) -> AdminPasskeyCredential | None:
        for item in self.list_passkeys_for_rp(rp_id):
            if item.credential_id == credential_id:
                return item
        return None

    def add_passkey(
        self,
        *,
        credential_id: str,
        public_key: str,
        sign_count: int,
        rp_id: str,
        transports: list[str] | None = None,
        label: str | None = None,
    ) -> AdminPasskeyCredential:
        record = self._load_record()
        if record is None or record.must_rotate:
            raise BootstrapRequiredError("bootstrap rotation required")
        record.passkeys = [
            item
            for item in record.passkeys
            if not (item.credential_id == credential_id and item.rp_id == rp_id)
        ]
        created = AdminPasskeyCredential(
            credential_id=credential_id,
            public_key=public_key,
            sign_count=sign_count,
            rp_id=rp_id,
            transports=transports or [],
            label=label,
            created_at=utc_now().isoformat(),
            last_used_at=None,
        )
        record.passkeys.append(created)
        record.updated_at = utc_now().isoformat()
        self._write_record(record)
        return created

    def update_passkey_sign_count(self, credential_id: str, rp_id: str, sign_count: int) -> None:
        record = self._load_record()
        if record is None:
            raise InvalidCredentialsError("admin auth file is missing")
        for item in record.passkeys:
            if item.credential_id == credential_id and item.rp_id == rp_id:
                item.sign_count = sign_count
                item.last_used_at = utc_now().isoformat()
                record.updated_at = utc_now().isoformat()
                self._write_record(record)
                return
        raise InvalidCredentialsError("passkey not found")

    def delete_passkey(self, credential_id: str, rp_id: str) -> bool:
        record = self._load_record()
        if record is None:
            return False
        before = len(record.passkeys)
        record.passkeys = [
            item
            for item in record.passkeys
            if not (item.credential_id == credential_id and item.rp_id == rp_id)
        ]
        if len(record.passkeys) == before:
            return False
        record.updated_at = utc_now().isoformat()
        self._write_record(record)
        return True

    def _load_record(self) -> AdminAuthRecord | None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        try:
            return AdminAuthRecord(
                username=str(payload["username"]),
                password_hash=str(payload["password_hash"]),
                must_rotate=bool(payload.get("must_rotate", False)),
                session_secret=str(payload["session_secret"]),
                session_version=int(payload.get("session_version", 1)),
                user_handle=str(payload.get("user_handle", generate_secret_token(16))),
                passkeys=[
                    AdminPasskeyCredential(**item) for item in payload.get("passkeys", [])
                ],
                updated_at=payload.get("updated_at"),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _write_record(self, record: AdminAuthRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        payload: dict[str, Any] = asdict(record)
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        tmp_path.replace(self.path)
