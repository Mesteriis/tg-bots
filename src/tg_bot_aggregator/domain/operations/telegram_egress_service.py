from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.core.time import utc_now
from tg_bot_aggregator.domain.operations.repository import (
    RuntimeAdvancedSettingsRepository,
    RuntimeSettingsRepository,
)
from tg_bot_aggregator.domain.operations.telegram_egress_providers import (
    DirectProvider,
    OpenVpnProvider,
    TelegramEgressProvider,
    TelegramEgressProviderError,
    TelegramEgressProviderName,
    TelegramEgressStatus,
    WireGuardProvider,
)
from tg_bot_aggregator.domain.operations.telegram_egress_store import TelegramEgressStore
from tg_bot_aggregator.runtime_settings import runtime_settings_read


@dataclass(slots=True, frozen=True)
class TelegramEgressState:
    mode: str
    enabled: bool
    provider: TelegramEgressProviderName | None
    provider_config_present: bool
    last_status: str | None
    last_error: str | None
    connected_at: datetime | None
    last_handshake_at: datetime | None
    last_egress_ip: str | None


class TelegramEgressService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        store: TelegramEgressStore | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._store = store or TelegramEgressStore(settings.telegram_egress_state_dir)
        self._http_client = http_client

    async def read_state(self) -> TelegramEgressState:
        settings_read = await self._runtime_settings_read()
        provider_name = _resolve_provider_name(
            settings_read.telegram_egress_mode,
            settings_read.telegram_egress_provider,
        )
        provider_config_present = False
        if provider_name is not None:
            provider_config_present = self._store.config_summary(provider_name).present
        return TelegramEgressState(
            mode=settings_read.telegram_egress_mode,
            enabled=settings_read.telegram_egress_enabled,
            provider=provider_name,
            provider_config_present=provider_config_present,
            last_status=settings_read.telegram_egress_last_status,
            last_error=settings_read.telegram_egress_last_error,
            connected_at=settings_read.telegram_egress_connected_at,
            last_handshake_at=settings_read.telegram_egress_last_handshake_at,
            last_egress_ip=settings_read.telegram_egress_last_egress_ip,
        )

    async def status(self) -> TelegramEgressStatus:
        settings_read = await self._runtime_settings_read()
        provider = self._provider_for(
            settings_read.telegram_egress_mode,
            settings_read.telegram_egress_provider,
        )
        status = await provider.status()
        await self._persist_observation(status)
        return status

    async def configure(
        self,
        *,
        provider: TelegramEgressProviderName,
        profile_text: str,
        auth_text: str | None = None,
    ) -> TelegramEgressState:
        if provider == "wireguard":
            self._store.write_wireguard_profile(profile_text)
        elif provider == "openvpn":
            self._store.write_openvpn_profile(profile_text)
            if auth_text is not None:
                self._store.write_openvpn_auth(auth_text)
        else:
            raise NotImplementedError(
                f"Telegram egress provider {provider!r} is not implemented yet"
            )
        return await self.read_state()

    async def connect(self) -> TelegramEgressStatus:
        provider = await self._active_provider()
        try:
            await provider.connect()
        except TelegramEgressProviderError:
            raise
        status = await provider.status()
        await self._persist_observation(status)
        return status

    async def disconnect(self) -> TelegramEgressStatus:
        provider = await self._active_provider()
        await provider.disconnect()
        status = await provider.status()
        await self._persist_observation(status)
        return status

    async def restart(self) -> TelegramEgressStatus:
        provider = await self._active_provider()
        await provider.restart()
        status = await provider.status()
        await self._persist_observation(status)
        return status

    async def _runtime_settings_read(self):
        settings_row = await RuntimeSettingsRepository(self._session).get()
        advanced_row = await RuntimeAdvancedSettingsRepository(self._session).get()
        return runtime_settings_read(self._settings, settings_row, advanced_row)

    async def _active_provider(self) -> TelegramEgressProvider:
        settings_read = await self._runtime_settings_read()
        return self._provider_for(
            settings_read.telegram_egress_mode,
            settings_read.telegram_egress_provider,
        )

    def _provider_for(
        self,
        mode: str,
        provider: TelegramEgressProviderName | None,
    ) -> TelegramEgressProvider:
        if mode == "direct":
            return DirectProvider(http_client=self._http_client)
        resolved_provider = _resolve_provider_name(mode, provider)
        if resolved_provider == "wireguard":
            return WireGuardProvider(
                store=self._store,
                http_client=self._http_client,
                control_url=self._settings.telegram_egress_control_url,
            )
        if resolved_provider == "openvpn":
            return OpenVpnProvider(
                store=self._store,
                http_client=self._http_client,
                control_url=self._settings.telegram_egress_control_url,
            )
        raise NotImplementedError(
            f"Telegram egress provider {resolved_provider or mode!r} is not implemented yet"
        )

    async def _persist_observation(self, status: TelegramEgressStatus) -> None:
        connected_at: datetime | None = None
        current = await RuntimeSettingsRepository(self._session).get()
        if current is not None:
            connected_at = current.telegram_egress_connected_at
        if status.tunnel_state == "connected" and connected_at is None:
            connected_at = utc_now()
        if status.tunnel_state != "connected":
            connected_at = None
        await RuntimeSettingsRepository(self._session).upsert(
            telegram_egress_last_status=status.tunnel_state,
            telegram_egress_last_error=status.last_error,
            telegram_egress_last_egress_ip=status.egress_ip,
            telegram_egress_connected_at=connected_at,
            telegram_egress_last_handshake_at=utc_now()
            if status.tunnel_state == "connected"
            else None,
        )
        await self._session.commit()


def _resolve_provider_name(
    mode: str,
    provider: TelegramEgressProviderName | None,
) -> TelegramEgressProviderName | None:
    if provider is not None:
        return provider
    if mode == "wireguard":
        return "wireguard"
    if mode == "openvpn":
        return "openvpn"
    return None


__all__ = ["TelegramEgressService", "TelegramEgressState"]
