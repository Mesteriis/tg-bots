from dataclasses import asdict
from pathlib import Path

import pytest

from tg_bot_aggregator.domain.operations.telegram_egress_store import TelegramEgressStore


def test_store_replaces_wireguard_profile_atomically_with_strict_permissions(
    tmp_path: Path,
) -> None:
    store = TelegramEgressStore(tmp_path)

    first_path = store.write_wireguard_profile("[Interface]\nPrivateKey = secret-one\n")
    second_path = store.write_wireguard_profile("[Interface]\nPrivateKey = secret-two\n")

    assert first_path == tmp_path / "wireguard" / "profile.conf"
    assert second_path == first_path
    assert second_path.read_text(encoding="utf-8") == "[Interface]\nPrivateKey = secret-two\n"
    assert second_path.stat().st_mode & 0o777 == 0o600
    assert list(second_path.parent.glob("*.tmp")) == []


def test_store_writes_openvpn_profile_and_auth_with_strict_permissions(tmp_path: Path) -> None:
    store = TelegramEgressStore(tmp_path)

    profile_path = store.write_openvpn_profile("client\nremote vpn.example.com 1194\n")
    auth_path = store.write_openvpn_auth("user\nsuper-secret-password\n")

    assert profile_path == tmp_path / "openvpn" / "profile.ovpn"
    assert auth_path == tmp_path / "openvpn" / "auth.txt"
    assert profile_path.read_text(encoding="utf-8") == "client\nremote vpn.example.com 1194\n"
    assert auth_path.read_text(encoding="utf-8") == "user\nsuper-secret-password\n"
    assert profile_path.stat().st_mode & 0o777 == 0o600
    assert auth_path.stat().st_mode & 0o777 == 0o600


def test_store_reports_missing_wireguard_config_without_creating_directories(
    tmp_path: Path,
) -> None:
    store = TelegramEgressStore(tmp_path)

    summary = store.config_summary("wireguard")

    assert summary.provider == "wireguard"
    assert summary.present is False
    assert summary.files == (("profile", tmp_path / "wireguard" / "profile.conf", False),)
    assert (tmp_path / "wireguard").exists() is False


def test_store_reports_openvpn_summary_without_leaking_secret_values(tmp_path: Path) -> None:
    store = TelegramEgressStore(tmp_path)
    store.write_openvpn_profile("client\nauth-user-pass auth.txt\n")
    store.write_openvpn_auth("demo-user\ndemo-secret-password\n")

    summary = store.config_summary("openvpn")
    payload = repr(asdict(summary))

    assert summary.provider == "openvpn"
    assert summary.present is True
    assert summary.files == (
        ("profile", tmp_path / "openvpn" / "profile.ovpn", True),
        ("auth", tmp_path / "openvpn" / "auth.txt", True),
    )
    assert "demo-secret-password" not in payload
    assert "demo-user" not in payload


def test_store_rejects_unknown_provider_in_summary(tmp_path: Path) -> None:
    store = TelegramEgressStore(tmp_path)

    with pytest.raises(ValueError, match="Unsupported telegram egress provider"):
        store.config_summary("socks5")
