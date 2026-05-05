from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator

TelegramEgressMode = Literal["direct", "wireguard", "openvpn"]
TelegramEgressProviderName = Literal["wireguard", "openvpn"]
TelegramEgressTunnelState = Literal[
    "not_applicable",
    "disconnected",
    "misconfigured",
    "connected",
    "degraded",
]


class TelegramEgressStateRead(BaseModel):
    mode: TelegramEgressMode
    enabled: bool
    provider: TelegramEgressProviderName | None
    provider_config_present: bool
    last_status: str | None
    last_error: str | None
    connected_at: datetime | None
    last_handshake_at: datetime | None
    last_egress_ip: str | None


class TelegramEgressUpdate(BaseModel):
    mode: TelegramEgressMode | None = None
    enabled: bool | None = None
    provider: TelegramEgressProviderName | None = None

    @model_validator(mode="after")
    def validate_mode_provider(self) -> TelegramEgressUpdate:
        if self.mode == "direct" and self.provider is not None:
            raise ValueError("provider must be null when mode is direct")
        if self.mode == "wireguard" and self.provider not in {None, "wireguard"}:
            raise ValueError("provider must match wireguard mode")
        if self.mode == "openvpn" and self.provider not in {None, "openvpn"}:
            raise ValueError("provider must match openvpn mode")
        return self


class TelegramEgressStatusRead(BaseModel):
    mode: TelegramEgressMode
    provider: TelegramEgressProviderName | None
    tunnel_state: TelegramEgressTunnelState
    provider_config_present: bool
    egress_ip: str | None
    telegram_reachable: bool | None
    last_error: str | None


class TelegramEgressConfigUpload(BaseModel):
    provider: TelegramEgressProviderName
    profile_text: str
    auth_text: str | None = None
