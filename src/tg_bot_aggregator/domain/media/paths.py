import os
from dataclasses import dataclass
from pathlib import Path


class SharedPathError(ValueError):
    pass


@dataclass(frozen=True)
class SharedFile:
    relative_path: str
    resolved_path: Path
    file_uri: str
    size_bytes: int


@dataclass(frozen=True)
class SharedMediaStatus:
    root: Path
    available: bool
    error: str | None = None
    mounted: bool = False
    mount_required: bool = False


def check_shared_media_root(
    shared_root: str | Path,
    *,
    require_mount: bool = False,
) -> SharedMediaStatus:
    root = Path(shared_root).resolve()
    mounted = root.is_mount()
    if not root.exists():
        return SharedMediaStatus(
            root=root,
            available=False,
            error="shared media root is not available",
            mounted=False,
            mount_required=require_mount,
        )
    if not root.is_dir():
        return SharedMediaStatus(
            root=root,
            available=False,
            error="shared media root is not a directory",
            mounted=mounted,
            mount_required=require_mount,
        )
    if not os.access(root, os.R_OK):
        return SharedMediaStatus(
            root=root,
            available=False,
            error="shared media root is not readable",
            mounted=mounted,
            mount_required=require_mount,
        )
    if require_mount and not mounted:
        return SharedMediaStatus(
            root=root,
            available=False,
            error="shared media root is not mounted",
            mounted=False,
            mount_required=True,
        )
    return SharedMediaStatus(
        root=root,
        available=True,
        mounted=mounted,
        mount_required=require_mount,
    )


def ensure_shared_media_root(shared_root: str | Path, *, require_mount: bool = False) -> Path:
    status = check_shared_media_root(shared_root, require_mount=require_mount)
    if not status.available:
        raise SharedPathError(status.error or "shared media root is not available")
    return status.root


def validate_shared_file(
    shared_root: str | Path,
    relative_path: str,
    max_size_bytes: int,
    require_mount: bool = False,
) -> SharedFile:
    root = ensure_shared_media_root(shared_root, require_mount=require_mount)
    candidate_input = Path(relative_path)

    if candidate_input.is_absolute():
        raise SharedPathError("file path must be relative to shared media root")
    if ".." in candidate_input.parts:
        raise SharedPathError("file path cannot contain parent directory traversal")

    candidate = (root / candidate_input).resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SharedPathError("file path escapes shared media root") from exc

    if not candidate.exists():
        raise SharedPathError("file does not exist")
    if not candidate.is_file():
        raise SharedPathError("file path must point to a regular file")

    size = candidate.stat().st_size
    if size > max_size_bytes:
        raise SharedPathError("file exceeds configured maximum size")

    return SharedFile(
        relative_path=relative_path,
        resolved_path=candidate,
        file_uri=candidate.as_uri(),
        size_bytes=size,
    )
