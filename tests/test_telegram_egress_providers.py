from pathlib import Path

import httpx

from tg_bot_aggregator.domain.operations.telegram_egress_providers import (
    DirectProvider,
    OpenVpnProvider,
    WireGuardProvider,
)
from tg_bot_aggregator.domain.operations.telegram_egress_store import TelegramEgressStore


async def test_direct_provider_reports_disconnected_without_tunnel() -> None:
    provider = DirectProvider()

    status = await provider.status()

    assert status.mode == "direct"
    assert status.provider is None
    assert status.tunnel_state == "not_applicable"
    assert status.provider_config_present is False
    assert status.egress_ip is None
    assert status.telegram_reachable is None


async def test_wireguard_provider_requires_profile_file(tmp_path: Path) -> None:
    provider = WireGuardProvider(root=tmp_path)

    result = await provider.validate_config()

    assert result.ok is False
    assert "profile.conf" in result.message


async def test_wireguard_provider_rejects_invalid_profile_contents(tmp_path: Path) -> None:
    store = TelegramEgressStore(tmp_path)
    store.write_wireguard_profile("[Peer]\nPublicKey = peer\n")
    provider = WireGuardProvider(store=store)

    result = await provider.validate_config()

    assert result.ok is False
    assert "[Interface]" in result.message


async def test_wireguard_provider_reports_disconnected_when_profile_is_present(
    tmp_path: Path,
) -> None:
    store = TelegramEgressStore(tmp_path)
    store.write_wireguard_profile("[Interface]\nPrivateKey = secret\n")
    provider = WireGuardProvider(store=store)

    status = await provider.status()

    assert status.mode == "wireguard"
    assert status.provider == "wireguard"
    assert status.tunnel_state == "disconnected"
    assert status.provider_config_present is True
    assert status.last_error is None


async def test_wireguard_provider_uses_control_server_for_connected_status(
    tmp_path: Path,
) -> None:
    store = TelegramEgressStore(tmp_path)
    store.write_wireguard_profile("[Interface]\nPrivateKey = secret\n")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and str(request.url) == "http://control/v1/vpn/status":
            return httpx.Response(200, json={"status": "running"})
        if request.method == "GET" and str(request.url) == "http://control/v1/publicip/ip":
            return httpx.Response(200, json={"public_ip": "198.51.100.50"})
        return httpx.Response(200, json={"ok": True})

    provider = WireGuardProvider(
        store=store,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        control_url="http://control",
    )

    status = await provider.status()

    assert status.tunnel_state == "connected"
    assert status.egress_ip == "198.51.100.50"
    assert status.last_error is None


async def test_wireguard_provider_surfaces_control_server_runtime_status(
    tmp_path: Path,
) -> None:
    store = TelegramEgressStore(tmp_path)
    store.write_wireguard_profile("[Interface]\nPrivateKey = secret\n")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and str(request.url) == "http://control/v1/vpn/status":
            return httpx.Response(200, json={"status": "crashed"})
        return httpx.Response(200, json={"ok": True})

    provider = WireGuardProvider(
        store=store,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        control_url="http://control",
    )

    status = await provider.status()

    assert status.tunnel_state == "degraded"
    assert status.last_error == "Telegram egress control server reported status: crashed"


async def test_wireguard_provider_connect_calls_control_server(tmp_path: Path) -> None:
    store = TelegramEgressStore(tmp_path)
    store.write_wireguard_profile("[Interface]\nPrivateKey = secret\n")
    calls: list[tuple[str, str, bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url), request.content))
        return httpx.Response(200, json={"status": "running"})

    provider = WireGuardProvider(
        store=store,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        control_url="http://control",
    )

    await provider.connect()

    assert calls == [
        ("PUT", "http://control/v1/vpn/status", b'{"status":"running"}')
    ]


async def test_openvpn_provider_requires_profile_file(tmp_path: Path) -> None:
    provider = OpenVpnProvider(root=tmp_path)

    result = await provider.validate_config()

    assert result.ok is False
    assert "profile.ovpn" in result.message


async def test_openvpn_provider_reports_disconnected_when_profile_is_present(
    tmp_path: Path,
) -> None:
    store = TelegramEgressStore(tmp_path)
    store.write_openvpn_profile("client\nremote vpn.example.com 1194\n")
    provider = OpenVpnProvider(store=store)

    status = await provider.status()

    assert status.mode == "openvpn"
    assert status.provider == "openvpn"
    assert status.tunnel_state == "disconnected"
    assert status.provider_config_present is False
    assert status.last_error is None


async def test_openvpn_provider_degrades_when_control_server_is_unavailable(
    tmp_path: Path,
) -> None:
    store = TelegramEgressStore(tmp_path)
    store.write_openvpn_profile("client\nremote vpn.example.com 1194\n")

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = OpenVpnProvider(
        store=store,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        control_url="http://control",
    )

    status = await provider.status()

    assert status.tunnel_state == "degraded"
    assert status.last_error == "Telegram egress control server is unavailable"


async def test_openvpn_provider_surfaces_control_server_runtime_status(
    tmp_path: Path,
) -> None:
    store = TelegramEgressStore(tmp_path)
    store.write_openvpn_profile("client\nremote vpn.example.com 1194\n")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and str(request.url) == "http://control/v1/vpn/status":
            return httpx.Response(200, json={"status": "crashed"})
        return httpx.Response(200, json={"ok": True})

    provider = OpenVpnProvider(
        store=store,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        control_url="http://control",
    )

    status = await provider.status()

    assert status.tunnel_state == "degraded"
    assert status.last_error == "Telegram egress control server reported status: crashed"
