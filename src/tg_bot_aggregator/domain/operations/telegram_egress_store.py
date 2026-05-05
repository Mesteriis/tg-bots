from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(slots=True)
class ProviderConfigSummary:
    provider: Literal["wireguard", "openvpn"]
    path: Path
    exists: bool
    readable: bool
    auth_path: Path | None = None
    auth_exists: bool | None = None

    @property
    def present(self) -> bool:
        if self.auth_path is None:
            return self.exists
        return self.exists and bool(self.auth_exists)

    @property
    def files(self) -> tuple[tuple[str, Path, bool], ...]:
        entries: list[tuple[str, Path, bool]] = [("profile", self.path, self.exists)]
        if self.auth_path is not None:
            entries.append(("auth", self.auth_path, bool(self.auth_exists)))
        return tuple(entries)


class TelegramEgressStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def write_wireguard_profile(self, contents: str) -> Path:
        target = self.root / "wireguard" / "profile.conf"
        self._atomic_write_text(target, contents)
        return target

    def write_openvpn_profile(self, contents: str) -> Path:
        target = self.root / "openvpn" / "profile.ovpn"
        self._atomic_write_text(target, contents)
        return target

    def write_openvpn_auth(self, contents: str) -> Path:
        target = self.root / "openvpn" / "auth.txt"
        self._atomic_write_text(target, contents)
        return target

    def config_summary(self, provider: str) -> ProviderConfigSummary:
        if provider == "wireguard":
            path = self.root / "wireguard" / "profile.conf"
            return ProviderConfigSummary(
                provider=provider,
                path=path,
                exists=path.exists(),
                readable=path.is_file(),
            )

        if provider == "openvpn":
            path = self.root / "openvpn" / "profile.ovpn"
            auth_path = self.root / "openvpn" / "auth.txt"
            return ProviderConfigSummary(
                provider=provider,
                path=path,
                exists=path.exists(),
                readable=path.is_file(),
                auth_path=auth_path,
                auth_exists=auth_path.exists(),
            )

        raise ValueError(f"Unsupported telegram egress provider: {provider}")

    def _atomic_write_text(self, target: Path, contents: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            text=True,
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(contents)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, target)
            target.chmod(0o600)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
