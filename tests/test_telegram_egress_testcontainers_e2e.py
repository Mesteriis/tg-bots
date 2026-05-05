from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from docker.errors import DockerException
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

from tg_bot_aggregator.core.config import Settings
from tg_bot_aggregator.core.orm import Base
from tg_bot_aggregator.infra.telegram_client import TelegramBotApiClient
from tg_bot_aggregator.main import create_app

OPENVPN_PROFILE = """\
client
dev tun
proto udp
remote 198.51.100.20 1194
nobind
persist-key
persist-tun
verb 3
cipher AES-256-GCM
auth SHA256
remote-cert-tls server
<ca>
-----BEGIN CERTIFICATE-----
MIIBszCCAVmgAwIBAgIUQm9ndXNDZXJ0aWZpY2F0ZVRlc3QwCgYIKoZIzj0EAwIw
EjEQMA4GA1UEAwwHVGVzdCBDQTAeFw0yNjA1MDUxNjAwMDBaFw0zNjA1MDIxNjAw
MDBaMBIxEDAOBgNVBAMMB1Rlc3QgQ0EwWTATBgcqhkjOPQIBBggqhkjOPQMBBwNC
AATuQ2k0d3Vj5dD5p2c9v6F0k6+qfH77Q6QnV4x1U2D9gU9nW7P3NQ8Qx8BzZkzB
M2p+vAq6g2T3l6h7Y6w8m5Nfo1MwUTAdBgNVHQ4EFgQU8N2YtP3WQ1cS3V5q0P9j
QX6B7NswHwYDVR0jBBgwFoAU8N2YtP3WQ1cS3V5q0P9jQX6B7NswDwYDVR0TAQH/
BAUwAwEB/zAKBggqhkjOPQQDAgNJADBGAiEA5yN0+9n0pM0vLx6n0u1lX8O4zY1A
3vR7vP7fYyP7sYQCIQDaQ0hA0qF1v5M0n4gH1a0M0b7M5b7yP0V5O3o9s6M+8A==
-----END CERTIFICATE-----
</ca>
"""


async def _wait_for_control_server(base_url: str, *, timeout_seconds: float = 20.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    async with httpx.AsyncClient(timeout=2.0) as client:
        while True:
            try:
                response = await client.get(f"{base_url}/v1/vpn/status")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError(f"Gluetun control server did not become ready at {base_url}")
            await asyncio.sleep(0.5)


async def _wait_for_file(path: Path, *, timeout_seconds: float = 20.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        if await asyncio.to_thread(path.exists):
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"Expected file was not generated in time: {path}")
        await asyncio.sleep(0.5)


async def _wait_for_wireguard_handshake(
    server_container: DockerContainer,
    *,
    timeout_seconds: float = 20.0,
) -> str:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    wrapped = server_container.get_wrapped_container()
    while True:
        result = wrapped.exec_run("wg show")
        output = result.output.decode("utf-8", errors="replace")
        if result.exit_code == 0 and "latest handshake:" in output:
            return output
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"WireGuard peer handshake did not appear in time:\n{output}")
        await asyncio.sleep(0.5)


def _start_gluetun_container(
    *,
    provider: str,
    profile_path: Path,
    auth_path: Path | None = None,
    network: Network | None = None,
) -> tuple[DockerContainer, str]:
    container: DockerContainer = (
        DockerContainer("qmcgaw/gluetun:v3.41.1")
        .with_exposed_ports(8000)
        .with_env("VPN_SERVICE_PROVIDER", "custom")
        .with_env("VPN_TYPE", provider)
        .with_env("HTTP_CONTROL_SERVER_AUTH_DEFAULT_ROLE", '{"auth":"none"}')
        .with_kwargs(cap_add=["NET_ADMIN"], devices=["/dev/net/tun:/dev/net/tun"])
    )
    if network is not None:
        container = container.with_network(network)
    if provider == "wireguard":
        container = container.with_volume_mapping(
            str(profile_path),
            "/gluetun/wireguard/wg0.conf",
            "ro",
        )
    else:
        container = container.with_env("OPENVPN_CUSTOM_CONFIG", "/gluetun/custom.conf")
        container = container.with_volume_mapping(
            str(profile_path),
            "/gluetun/custom.conf",
            "ro",
        )
        if auth_path is not None:
            container = container.with_volume_mapping(
                str(auth_path),
                "/gluetun/auth.txt",
                "ro",
            )
    try:
        container.start()
    except DockerException as exc:
        pytest.skip(f"Docker is unavailable for Gluetun testcontainers: {exc}")
    host = container.get_container_host_ip()
    port = container.get_exposed_port(8000)
    return container, f"http://{host}:{port}"


def _create_network() -> tuple[Network, str]:
    network = Network()
    docker_network_name = network.name
    try:
        network.create()
    except DockerException as exc:
        pytest.skip(f"Docker is unavailable for VPN server testcontainers: {exc}")
    return network, docker_network_name


def _start_wireguard_server_container(
    *,
    config_root: Path,
    network: Network,
) -> DockerContainer:
    container = (
        DockerContainer("lscr.io/linuxserver/wireguard:latest")
        .with_network(network)
        .with_network_aliases("wireguard-server")
        .with_env("PUID", "1000")
        .with_env("PGID", "1000")
        .with_env("TZ", "UTC")
        .with_env("SERVERURL", "wireguard-server")
        .with_env("SERVERPORT", "51820")
        .with_env("PEERS", "1")
        .with_env("PEERDNS", "1.1.1.1")
        .with_env("INTERNAL_SUBNET", "10.13.13.0")
        .with_volume_mapping(str(config_root), "/config", "rw")
        .with_kwargs(cap_add=["NET_ADMIN"])
    )
    try:
        container.start()
    except DockerException as exc:
        pytest.skip(f"Docker is unavailable for WireGuard server testcontainers: {exc}")
    return container


def _container_ip(container: DockerContainer, docker_network_name: str) -> str:
    wrapped = container.get_wrapped_container()
    wrapped.reload()
    return wrapped.attrs["NetworkSettings"]["Networks"][docker_network_name]["IPAddress"]


def _rewrite_wireguard_endpoint(profile_text: str, *, endpoint_ip: str) -> str:
    rewritten_lines: list[str] = []
    for line in profile_text.splitlines():
        if line.startswith("Endpoint = "):
            _, port = line.rsplit(":", 1)
            rewritten_lines.append(f"Endpoint = {endpoint_ip}:{port}")
        else:
            rewritten_lines.append(line)
    return "\n".join(rewritten_lines) + "\n"


def _start_openvpn_server_container(
    *,
    config_root: Path,
    network: Network,
) -> DockerContainer:
    container = (
        DockerContainer("kylemanna/openvpn:2.1.3")
        .with_network(network)
        .with_network_aliases("openvpn-server")
        .with_env("PUID", "1000")
        .with_env("PGID", "1000")
        .with_env("TZ", "UTC")
        .with_env("OVPN_DNS", "1.1.1.1")
        .with_volume_mapping(str(config_root), "/etc/openvpn", "rw")
        .with_kwargs(cap_add=["NET_ADMIN"], devices=["/dev/net/tun:/dev/net/tun"])
        .with_command(
            "bash -lc '"
            "ovpn_genconfig -u udp://openvpn-server:1194 >/tmp/openvpn-bootstrap.log 2>&1 && "
            "EASYRSA_BATCH=1 ovpn_initpki nopass >/tmp/openvpn-bootstrap.log 2>&1 && "
            "EASYRSA_BATCH=1 easyrsa build-client-full telegram-client nopass "
            ">/tmp/openvpn-bootstrap.log 2>&1 && "
            "ovpn_getclient telegram-client > /etc/openvpn/telegram-client.ovpn && "
            "exec ovpn_run'"
        )
    )
    try:
        container.start()
    except DockerException as exc:
        pytest.skip(f"Docker is unavailable for OpenVPN server testcontainers: {exc}")
    return container


async def _wait_for_openvpn_client_profile(
    *,
    config_root: Path,
    timeout_seconds: float = 20.0,
) -> str:
    client_profile = config_root / "telegram-client.ovpn"
    await _wait_for_file(client_profile, timeout_seconds=timeout_seconds)
    return client_profile.read_text(encoding="utf-8")


def _rewrite_openvpn_remote(profile_text: str, *, server_ip: str) -> str:
    rewritten_lines: list[str] = []
    replaced = False
    for line in profile_text.splitlines():
        if line.startswith("remote "):
            rewritten_lines.append(f"remote {server_ip} 1194")
            replaced = True
        else:
            rewritten_lines.append(line)
    if not replaced:
        raise AssertionError("Client profile does not contain remote")
    return "\n".join(rewritten_lines) + "\n"


async def _wait_for_openvpn_server_ready(
    server_container: DockerContainer,
    *,
    timeout_seconds: float = 30.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    wrapped = server_container.get_wrapped_container()
    while True:
        wrapped.reload()
        status = wrapped.attrs.get("State", {}).get("Status")
        logs = wrapped.logs().decode("utf-8", errors="replace")
        if "Initialization Sequence Completed" in logs and status == "running":
            return
        if status in {"exited", "dead", "created"}:
            raise AssertionError(
                f"OpenVPN server container failed to start with status '{status}':\n{logs}"
            )
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(
                f"OpenVPN server did not become ready in time. Last status '{status}':\n{logs}"
            )
        await asyncio.sleep(0.5)


def _build_app_client(
    *,
    state_dir: Path,
    control_url: str,
) -> tuple[httpx.AsyncClient, AsyncEngine, httpx.AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    shared_http_client = httpx.AsyncClient(timeout=5.0)
    app = create_app(
        Settings(
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            TELEGRAM_EGRESS_STATE_DIR=str(state_dir),
            TELEGRAM_EGRESS_CONTROL_URL=control_url,
        ),
        session_factory=session_factory,
        bot_api_client=TelegramBotApiClient(
            "https://api.telegram.org",
            shared_http_client,
        ),
    )
    return (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ),
        engine,
        shared_http_client,
    )


async def test_wireguard_gluetun_testcontainer_with_wireguard_server_e2e(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "telegram-egress"
    profile_path = state_dir / "wireguard" / "profile.conf"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    server_config_root = tmp_path / "wireguard-server-config"
    server_config_root.mkdir(parents=True, exist_ok=True)

    network, docker_network_name = _create_network()
    server_container = _start_wireguard_server_container(
        config_root=server_config_root,
        network=network,
    )
    try:
        peer_profile_path = server_config_root / "peer1" / "peer1.conf"
        await _wait_for_file(peer_profile_path)
        peer_profile_text = peer_profile_path.read_text(encoding="utf-8")
        profile_path.write_text(
            _rewrite_wireguard_endpoint(
                peer_profile_text,
                endpoint_ip=_container_ip(server_container, docker_network_name),
            ),
            encoding="utf-8",
        )

        gluetun_container, control_url = _start_gluetun_container(
            provider="wireguard",
            profile_path=profile_path,
            network=network,
        )
        try:
            await _wait_for_control_server(control_url)
            client, engine, shared_http_client = _build_app_client(
                state_dir=state_dir,
                control_url=control_url,
            )
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            try:
                async with client:
                    patched = await client.patch(
                        "/api/v1/operations/telegram-egress",
                        json={"mode": "wireguard", "enabled": True},
                    )
                    assert patched.status_code == 200

                    connected = await client.post("/api/v1/operations/telegram-egress/connect")
                    assert connected.status_code == 200
                    connected_payload = connected.json()
                    assert connected_payload["mode"] == "wireguard"
                    assert connected_payload["provider"] == "wireguard"
                    assert connected_payload["tunnel_state"] == "connected"

                    checked = await client.post("/api/v1/operations/telegram-egress/check")
                    assert checked.status_code == 200
                    checked_payload = checked.json()
                    assert checked_payload["tunnel_state"] == "connected"

                    state = await client.get("/api/v1/operations/telegram-egress")
                    assert state.status_code == 200
                    state_payload = state.json()
                    assert state_payload["last_status"] == "connected"
                    assert state_payload["connected_at"] is not None

                server_wg_show = await _wait_for_wireguard_handshake(server_container)
                assert "latest handshake:" in server_wg_show
                assert "allowed ips: 10.13.13.2/32" in server_wg_show
            finally:
                await shared_http_client.aclose()
                await engine.dispose()
        finally:
            gluetun_container.stop()
    finally:
        server_container.stop()
        network.remove()


async def test_openvpn_gluetun_testcontainer_e2e_reports_runtime_crash(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "telegram-egress"
    profile_path = state_dir / "openvpn" / "profile.ovpn"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(OPENVPN_PROFILE)

    container, control_url = _start_gluetun_container(
        provider="openvpn",
        profile_path=profile_path,
    )
    try:
        await _wait_for_control_server(control_url)
        client, engine, shared_http_client = _build_app_client(
            state_dir=state_dir,
            control_url=control_url,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with client:
                patched = await client.patch(
                    "/api/v1/operations/telegram-egress",
                    json={"mode": "openvpn", "enabled": True},
                )
                assert patched.status_code == 200

                uploaded = await client.post(
                    "/api/v1/operations/telegram-egress/config",
                    json={"provider": "openvpn", "profile_text": OPENVPN_PROFILE},
                )
                assert uploaded.status_code == 200

                await asyncio.sleep(2.0)
                checked = await client.post("/api/v1/operations/telegram-egress/check")
                assert checked.status_code == 200
                checked_payload = checked.json()
                assert checked_payload["mode"] == "openvpn"
                assert checked_payload["provider"] == "openvpn"
                assert checked_payload["tunnel_state"] == "degraded"
                assert checked_payload["last_error"] == (
                    "Telegram egress control server reported status: crashed"
                )

                state = await client.get("/api/v1/operations/telegram-egress")
                assert state.status_code == 200
                state_payload = state.json()
                assert state_payload["last_status"] == "degraded"
                assert state_payload["last_error"] == (
                    "Telegram egress control server reported status: crashed"
                )
        finally:
            await shared_http_client.aclose()
            await engine.dispose()
    finally:
        container.stop()


async def test_openvpn_gluetun_testcontainer_with_openvpn_server_e2e(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "telegram-egress"
    profile_path = state_dir / "openvpn" / "profile.ovpn"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    server_config_root = tmp_path / "openvpn-server-config"
    server_config_root.mkdir(parents=True, exist_ok=True)

    network, docker_network_name = _create_network()
    server_container = _start_openvpn_server_container(
        config_root=server_config_root,
        network=network,
    )
    try:
        await _wait_for_openvpn_server_ready(server_container)
        profile_text = await _wait_for_openvpn_client_profile(config_root=server_config_root)
        rewritten_profile = _rewrite_openvpn_remote(
            profile_text,
            server_ip=_container_ip(server_container, docker_network_name),
        )
        profile_path.write_text(rewritten_profile, encoding="utf-8")

        gluetun_container, control_url = _start_gluetun_container(
            provider="openvpn",
            profile_path=profile_path,
            network=network,
        )
        try:
            await _wait_for_control_server(control_url)
            client, engine, shared_http_client = _build_app_client(
                state_dir=state_dir,
                control_url=control_url,
            )
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            try:
                async with client:
                    patched = await client.patch(
                        "/api/v1/operations/telegram-egress",
                        json={"mode": "openvpn", "enabled": True},
                    )
                    assert patched.status_code == 200

                    uploaded = await client.post(
                        "/api/v1/operations/telegram-egress/config",
                        json={"provider": "openvpn", "profile_text": rewritten_profile},
                    )
                    assert uploaded.status_code == 200

                    connected = await client.post("/api/v1/operations/telegram-egress/connect")
                    assert connected.status_code == 200

                    checked = await client.post("/api/v1/operations/telegram-egress/check")
                    assert checked.status_code == 200
                    checked_payload = checked.json()
                    assert checked_payload["mode"] == "openvpn"
                    assert checked_payload["provider"] == "openvpn"
                    assert checked_payload["tunnel_state"] == "connected"

                    state = await client.get("/api/v1/operations/telegram-egress")
                    assert state.status_code == 200
                    state_payload = state.json()
                    assert state_payload["mode"] == "openvpn"
                    assert state_payload["provider"] == "openvpn"
                    assert state_payload["last_status"] == "connected"
                    assert state_payload["connected_at"] is not None
            finally:
                await shared_http_client.aclose()
                await engine.dispose()
        finally:
            gluetun_container.stop()
    finally:
        server_container.stop()
        network.remove()
