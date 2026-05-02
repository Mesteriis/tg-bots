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


def validate_shared_file(
    shared_root: str | Path,
    relative_path: str,
    max_size_bytes: int,
) -> SharedFile:
    root = Path(shared_root).resolve()
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

