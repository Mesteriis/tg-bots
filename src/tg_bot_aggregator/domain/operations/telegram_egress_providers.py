from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urljoin

import httpx

from tg_bot_aggregator.domain.operations.telegram_egress_store import (
    ProviderConfigSummary,
    TelegramEgressStore,
)

TelegramEgressMode = Literal["direct", "wireguard", "openvpn"]
TelegramEgressProviderName = Literal["wireguard", "openvpn"]
TunnelState = Literal["not_applicable", "disconnected", "misconfigured", "connected", "degraded"]


class TelegramEgressProviderError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class ValidationResult:
    ok: bool
    message: str


@dataclass(slots=True, frozen=True)
class TelegramEgressStatus:
    mode: TelegramEgressMode
    provider: TelegramEgressProviderName | None
    tunnel_state: TunnelState
    provider_config_present: bool
    egress_ip: str | None
    telegram_reachable: bool | None
    last_error: str | None


class TelegramEgressProvider(Protocol):
    async def validate_config(self) -> ValidationResult: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def restart(self) -> None: ...

    async def status(self) -> TelegramEgressStatus: ...

    async def egress_ip(self) -> str | None: ...

    async def telegram_reachability_check(self) -> bool | None: ...


class DirectProvider:
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        ip_check_url: str = "https://api.ipify.org?format=json",
        telegram_check_url: str = "https://api.telegram.org",
    ) -> None:
        self._http_client = http_client
        self._ip_check_url = ip_check_url
        self._telegram_check_url = telegram_check_url
        self._control_url = None

    async def validate_config(self) -> ValidationResult:
        return ValidationResult(ok=True, message="direct mode does not require provider config")

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def restart(self) -> None:
        return None

    async def status(self) -> TelegramEgressStatus:
        return TelegramEgressStatus(
            mode="direct",
            provider=None,
            tunnel_state="not_applicable",
            provider_config_present=False,
            egress_ip=await self.egress_ip(),
            telegram_reachable=await self.telegram_reachability_check(),
            last_error=None,
        )

    async def egress_ip(self) -> str | None:
        if self._control_url is not None:
            control_ip = await _fetch_control_public_ip(self._http_client, self._control_url)
            if control_ip is not None:
                return control_ip
        return await _fetch_egress_ip(self._http_client, self._ip_check_url)

    async def telegram_reachability_check(self) -> bool | None:
        return await _check_telegram_reachability(self._http_client, self._telegram_check_url)


class WireGuardProvider:
    def __init__(
        self,
        store: TelegramEgressStore | None = None,
        *,
        root: Path | str | None = None,
        http_client: httpx.AsyncClient | None = None,
        ip_check_url: str = "https://api.ipify.org?format=json",
        telegram_check_url: str = "https://api.telegram.org",
        control_url: str | None = None,
    ) -> None:
        if store is None:
            if root is None:
                raise ValueError("WireGuardProvider requires either a store or root path")
            store = TelegramEgressStore(root)
        self._store = store
        self._http_client = http_client
        self._ip_check_url = ip_check_url
        self._telegram_check_url = telegram_check_url
        self._control_url = control_url.rstrip("/") if control_url else None

    async def validate_config(self) -> ValidationResult:
        summary = self._summary()
        if not summary.exists:
            return ValidationResult(
                ok=False,
                message=f"WireGuard profile is missing: {summary.path}",
            )
        if not summary.readable:
            return ValidationResult(
                ok=False,
                message=f"WireGuard profile is not readable: {summary.path}",
            )
        try:
            contents = summary.path.read_text(encoding="utf-8")
        except OSError as exc:
            return ValidationResult(
                ok=False,
                message=f"WireGuard profile could not be read: {summary.path} ({exc})",
            )
        if "[Interface]" not in contents:
            return ValidationResult(
                ok=False,
                message=f"WireGuard profile must contain [Interface]: {summary.path}",
            )
        return ValidationResult(ok=True, message="WireGuard profile is present")

    async def connect(self) -> None:
        validation = await self.validate_config()
        if not validation.ok:
            raise TelegramEgressProviderError(validation.message)
        await _set_tunnel_status(
            self._http_client,
            self._control_url,
            "running",
        )

    async def disconnect(self) -> None:
        await _set_tunnel_status(
            self._http_client,
            self._control_url,
            "stopped",
        )

    async def restart(self) -> None:
        validation = await self.validate_config()
        if not validation.ok:
            raise TelegramEgressProviderError(validation.message)
        await _set_tunnel_status(
            self._http_client,
            self._control_url,
            "stopped",
        )
        await _set_tunnel_status(
            self._http_client,
            self._control_url,
            "running",
        )

    async def status(self) -> TelegramEgressStatus:
        summary = self._summary()
        validation = await self.validate_config()
        if not validation.ok:
            return TelegramEgressStatus(
                mode="wireguard",
                provider="wireguard",
                tunnel_state="misconfigured",
                provider_config_present=summary.present,
                egress_ip=None,
                telegram_reachable=None,
                last_error=validation.message,
            )
        control_status = await _read_tunnel_status(self._http_client, self._control_url)
        if control_status == "running":
            tunnel_state: TunnelState = "connected"
            last_error = None
        elif control_status == "stopped":
            tunnel_state = "disconnected"
            last_error = None
        else:
            tunnel_state = "degraded" if self._control_url else "disconnected"
            last_error = (
                f"Telegram egress control server reported status: {control_status}"
                if control_status is not None
                else (
                    "Telegram egress control server is unavailable"
                    if self._control_url
                    else None
                )
            )
        return TelegramEgressStatus(
            mode="wireguard",
            provider="wireguard",
            tunnel_state=tunnel_state,
            provider_config_present=summary.present,
            egress_ip=await self.egress_ip(),
            telegram_reachable=await self.telegram_reachability_check(),
            last_error=last_error,
        )

    async def egress_ip(self) -> str | None:
        if self._control_url is not None:
            control_ip = await _fetch_control_public_ip(self._http_client, self._control_url)
            if control_ip is not None:
                return control_ip
        return await _fetch_egress_ip(self._http_client, self._ip_check_url)

    async def telegram_reachability_check(self) -> bool | None:
        return await _check_telegram_reachability(self._http_client, self._telegram_check_url)

    def _summary(self) -> ProviderConfigSummary:
        return self._store.config_summary("wireguard")


class OpenVpnProvider:
    def __init__(
        self,
        store: TelegramEgressStore | None = None,
        *,
        root: Path | str | None = None,
        http_client: httpx.AsyncClient | None = None,
        ip_check_url: str = "https://api.ipify.org?format=json",
        telegram_check_url: str = "https://api.telegram.org",
        control_url: str | None = None,
    ) -> None:
        if store is None:
            if root is None:
                raise ValueError("OpenVpnProvider requires either a store or root path")
            store = TelegramEgressStore(root)
        self._store = store
        self._http_client = http_client
        self._ip_check_url = ip_check_url
        self._telegram_check_url = telegram_check_url
        self._control_url = control_url.rstrip("/") if control_url else None

    async def validate_config(self) -> ValidationResult:
        summary = self._summary()
        if not summary.exists:
            return ValidationResult(
                ok=False,
                message=f"OpenVPN profile is missing: {summary.path}",
            )
        if not summary.readable:
            return ValidationResult(
                ok=False,
                message=f"OpenVPN profile is not readable: {summary.path}",
            )
        try:
            contents = summary.path.read_text(encoding="utf-8")
        except OSError as exc:
            return ValidationResult(
                ok=False,
                message=f"OpenVPN profile could not be read: {summary.path} ({exc})",
            )
        if "client" not in contents:
            return ValidationResult(
                ok=False,
                message=f"OpenVPN profile must contain client directive: {summary.path}",
            )
        return ValidationResult(ok=True, message="OpenVPN profile is present")

    async def connect(self) -> None:
        validation = await self.validate_config()
        if not validation.ok:
            raise TelegramEgressProviderError(validation.message)
        await _set_tunnel_status(
            self._http_client,
            self._control_url,
            "running",
        )

    async def disconnect(self) -> None:
        await _set_tunnel_status(
            self._http_client,
            self._control_url,
            "stopped",
        )

    async def restart(self) -> None:
        validation = await self.validate_config()
        if not validation.ok:
            raise TelegramEgressProviderError(validation.message)
        await _set_tunnel_status(
            self._http_client,
            self._control_url,
            "stopped",
        )
        await _set_tunnel_status(
            self._http_client,
            self._control_url,
            "running",
        )

    async def status(self) -> TelegramEgressStatus:
        summary = self._summary()
        validation = await self.validate_config()
        if not validation.ok:
            return TelegramEgressStatus(
                mode="openvpn",
                provider="openvpn",
                tunnel_state="misconfigured",
                provider_config_present=summary.present,
                egress_ip=None,
                telegram_reachable=None,
                last_error=validation.message,
            )
        control_status = await _read_tunnel_status(self._http_client, self._control_url)
        if control_status == "running":
            tunnel_state: TunnelState = "connected"
            last_error = None
        elif control_status == "stopped":
            tunnel_state = "disconnected"
            last_error = None
        else:
            tunnel_state = "degraded" if self._control_url else "disconnected"
            last_error = (
                f"Telegram egress control server reported status: {control_status}"
                if control_status is not None
                else (
                    "Telegram egress control server is unavailable"
                    if self._control_url
                    else None
                )
            )
        return TelegramEgressStatus(
            mode="openvpn",
            provider="openvpn",
            tunnel_state=tunnel_state,
            provider_config_present=summary.present,
            egress_ip=await self.egress_ip(),
            telegram_reachable=await self.telegram_reachability_check(),
            last_error=last_error,
        )

    async def egress_ip(self) -> str | None:
        if self._control_url is not None:
            control_ip = await _fetch_control_public_ip(self._http_client, self._control_url)
            if control_ip is not None:
                return control_ip
        return await _fetch_egress_ip(self._http_client, self._ip_check_url)

    async def telegram_reachability_check(self) -> bool | None:
        return await _check_telegram_reachability(self._http_client, self._telegram_check_url)

    def _summary(self) -> ProviderConfigSummary:
        return self._store.config_summary("openvpn")


async def _fetch_egress_ip(
    client: httpx.AsyncClient | None,
    url: str,
) -> str | None:
    if client is None:
        return None
    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    payload = _json_payload(response.text)
    value = payload.get("ip")
    if isinstance(value, str) and value.strip():
        return value.strip()
    text = response.text.strip()
    return text or None


async def _check_telegram_reachability(
    client: httpx.AsyncClient | None,
    url: str,
) -> bool | None:
    if client is None:
        return None
    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPError:
        return False
    return True


async def _fetch_control_public_ip(
    client: httpx.AsyncClient | None,
    control_url: str | None,
) -> str | None:
    if client is None or control_url is None:
        return None
    try:
        response = await client.get(urljoin(f"{control_url}/", "v1/publicip/ip"))
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    payload = _json_payload(response.text)
    value = payload.get("public_ip")
    return value.strip() if isinstance(value, str) and value.strip() else None


async def _read_tunnel_status(
    client: httpx.AsyncClient | None,
    control_url: str | None,
) -> str | None:
    if client is None or control_url is None:
        return None
    try:
        response = await client.get(urljoin(f"{control_url}/", "v1/vpn/status"))
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    payload = _json_payload(response.text)
    value = payload.get("status")
    return value if isinstance(value, str) and value else None


async def _set_tunnel_status(
    client: httpx.AsyncClient | None,
    control_url: str | None,
    status: Literal["running", "stopped"],
) -> None:
    if client is None or control_url is None:
        raise TelegramEgressProviderError(
            "Telegram egress control server is not configured"
        )
    try:
        response = await client.put(
            urljoin(f"{control_url}/", "v1/vpn/status"),
            json={"status": status},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise TelegramEgressProviderError(
            f"Telegram egress control request failed: {exc}"
        ) from exc


def _json_payload(value: str) -> dict[str, object]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


__all__ = [
    "DirectProvider",
    "OpenVpnProvider",
    "TelegramEgressMode",
    "TelegramEgressProvider",
    "TelegramEgressProviderError",
    "TelegramEgressProviderName",
    "TelegramEgressStatus",
    "TunnelState",
    "ValidationResult",
    "WireGuardProvider",
]
