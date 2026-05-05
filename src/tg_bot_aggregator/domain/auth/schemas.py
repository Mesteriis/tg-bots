from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ApiScope = Literal["read", "send", "mcp_admin", "tg_compat", "ops_admin"]


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scopes: list[ApiScope] = Field(
        default_factory=lambda: ["read", "send", "mcp_admin", "tg_compat", "ops_admin"]
    )


class ApiTokenSessionRequest(BaseModel):
    token: str = Field(min_length=1)


class ApiTokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    token_prefix: str
    scopes_json: list[str] = Field(serialization_alias="scopes")
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiTokenCreated(ApiTokenRead):
    token: str


class AdminAuthStateRead(BaseModel):
    authenticated: bool
    username: str
    bootstrap_required: bool
    passkey_configured: bool
    auth_mode: str


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


class AdminBootstrapRotateRequest(BaseModel):
    current_username: str = Field(min_length=1, max_length=200)
    current_password: str = Field(min_length=1, max_length=500)
    new_username: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=500)


class AdminChangeCredentialsRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=500)
    new_username: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=500)


class AdminPasskeyRead(BaseModel):
    credential_id: str
    rp_id: str
    transports: list[str] = Field(default_factory=list)
    label: str | None = None
    created_at: datetime | None = None
    last_used_at: datetime | None = None


class AdminPasskeyRegisterOptionsRequest(BaseModel):
    label: str | None = Field(default=None, max_length=200)


class AdminPasskeyRegisterOptionsRead(BaseModel):
    challenge_id: str
    options_json: str
    rp_id: str
    origin: str


class AdminPasskeyVerifyRequest(BaseModel):
    challenge_id: str = Field(min_length=1)
    credential: dict


class AdminPasskeyAuthOptionsRead(BaseModel):
    challenge_id: str
    options_json: str
    rp_id: str
    origin: str
