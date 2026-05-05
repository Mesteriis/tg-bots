from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.domain.operations.repository import RuntimeSettingsRepository
from tg_bot_aggregator.domain.operations.telegram_egress_service import TelegramEgressService
from tg_bot_aggregator.domain.operations.telegram_egress_store import TelegramEgressStore


async def test_service_reads_runtime_metadata_and_store_summary(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    service = TelegramEgressService(
        db_session,
        Settings(TELEGRAM_EGRESS_STATE_DIR=str(tmp_path)),
    )

    state = await service.read_state()

    assert state.mode == "direct"
    assert state.enabled is False
    assert state.provider is None
    assert state.provider_config_present is False
    assert state.last_status == "disconnected"


async def test_service_reports_wireguard_config_presence_from_store(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    await RuntimeSettingsRepository(db_session).upsert(
        telegram_egress_mode="wireguard",
        telegram_egress_enabled=True,
        telegram_egress_provider="wireguard",
    )
    await db_session.commit()
    TelegramEgressStore(tmp_path).write_wireguard_profile("[Interface]\nPrivateKey = secret\n")

    service = TelegramEgressService(
        db_session,
        Settings(TELEGRAM_EGRESS_STATE_DIR=str(tmp_path)),
    )

    state = await service.read_state()

    assert state.mode == "wireguard"
    assert state.enabled is True
    assert state.provider == "wireguard"
    assert state.provider_config_present is True


async def test_service_status_uses_active_provider_validation(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    await RuntimeSettingsRepository(db_session).upsert(
        telegram_egress_mode="wireguard",
        telegram_egress_enabled=True,
        telegram_egress_provider="wireguard",
    )
    await db_session.commit()

    service = TelegramEgressService(
        db_session,
        Settings(TELEGRAM_EGRESS_STATE_DIR=str(tmp_path)),
    )

    status = await service.status()

    assert status.mode == "wireguard"
    assert status.provider == "wireguard"
    assert status.tunnel_state == "misconfigured"
    assert "profile.conf" in (status.last_error or "")


async def test_service_supports_openvpn_state_and_status(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    await RuntimeSettingsRepository(db_session).upsert(
        telegram_egress_mode="openvpn",
        telegram_egress_enabled=True,
        telegram_egress_provider="openvpn",
    )
    await db_session.commit()
    TelegramEgressStore(tmp_path).write_openvpn_profile("client\nremote vpn.example.com 1194\n")

    service = TelegramEgressService(
        db_session,
        Settings(TELEGRAM_EGRESS_STATE_DIR=str(tmp_path)),
    )

    state = await service.read_state()
    status = await service.status()

    assert state.mode == "openvpn"
    assert state.provider == "openvpn"
    assert state.provider_config_present is False
    assert status.mode == "openvpn"
    assert status.provider == "openvpn"
    assert status.tunnel_state == "disconnected"


async def test_service_persists_connected_observation(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    await RuntimeSettingsRepository(db_session).upsert(
        telegram_egress_mode="wireguard",
        telegram_egress_enabled=True,
        telegram_egress_provider="wireguard",
    )
    await db_session.commit()
    TelegramEgressStore(tmp_path).write_wireguard_profile("[Interface]\nPrivateKey = secret\n")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return httpx.Response(200, json={"status": "running"})
        if request.method == "GET" and str(request.url) == "http://control/v1/vpn/status":
            return httpx.Response(200, json={"status": "running"})
        if request.method == "GET" and str(request.url) == "http://control/v1/publicip/ip":
            return httpx.Response(200, json={"public_ip": "198.51.100.10"})
        return httpx.Response(200, json={"ok": True})

    service = TelegramEgressService(
        db_session,
        Settings(
            TELEGRAM_EGRESS_STATE_DIR=str(tmp_path),
            TELEGRAM_EGRESS_CONTROL_URL="http://control",
        ),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    status = await service.connect()
    state = await service.read_state()

    assert status.tunnel_state == "connected"
    assert state.last_status == "connected"
    assert state.connected_at is not None
    assert state.last_handshake_at is not None
