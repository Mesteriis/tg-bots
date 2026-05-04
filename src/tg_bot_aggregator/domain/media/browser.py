from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from tg_bot_aggregator.domain.media.paths import ensure_shared_media_root


class MediaBrowserError(ValueError):
    pass


@dataclass(frozen=True)
class MediaItem:
    name: str
    relative_path: str
    kind: str
    size_bytes: int | None
    modified_at: datetime
    media_type: str


@dataclass(frozen=True)
class MediaListing:
    relative_path: str
    items: list[MediaItem]


VIDEO_SUFFIXES = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
DOCUMENT_SUFFIXES = {
    ".7z",
    ".doc",
    ".docx",
    ".pdf",
    ".rar",
    ".txt",
    ".xls",
    ".xlsx",
    ".zip",
}


class MediaBrowser:
    def __init__(self, shared_root: str | Path, *, require_mount: bool = False) -> None:
        self.root = Path(shared_root).resolve()
        self.require_mount = require_mount

    def list_directory(self, relative_path: str | None = "") -> MediaListing:
        normalized, directory = self._resolve_directory(relative_path)
        items: list[MediaItem] = []
        for path in sorted(
            directory.iterdir(),
            key=lambda item: (item.is_file(), item.name.lower()),
        ):
            try:
                items.append(self._item(path))
            except MediaBrowserError:
                continue
        return MediaListing(relative_path=normalized, items=items)

    def _resolve_directory(self, relative_path: str | None) -> tuple[str, Path]:
        value = (relative_path or "").strip()
        candidate_input = Path(value)
        if candidate_input.is_absolute():
            raise MediaBrowserError("media path must be relative to shared media root")
        if ".." in candidate_input.parts:
            raise MediaBrowserError("media path cannot contain parent directory traversal")

        root = self._ensure_root_available()
        candidate = (root / candidate_input).resolve()
        self._ensure_inside_root(candidate)
        if not candidate.exists():
            raise MediaBrowserError("media directory does not exist")
        if not candidate.is_dir():
            raise MediaBrowserError("media path must point to a directory")
        return "" if value in {"", "."} else value, candidate

    def _ensure_root_available(self) -> Path:
        try:
            return ensure_shared_media_root(self.root, require_mount=self.require_mount)
        except ValueError as exc:
            raise MediaBrowserError(str(exc)) from exc

    def _item(self, path: Path) -> MediaItem:
        resolved = path.resolve()
        self._ensure_inside_root(resolved)
        stat = resolved.stat()
        kind = "directory" if resolved.is_dir() else "file"
        relative_path = resolved.relative_to(self.root).as_posix()
        return MediaItem(
            name=path.name,
            relative_path=relative_path,
            kind=kind,
            size_bytes=None if kind == "directory" else stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            media_type="directory" if kind == "directory" else self._media_type(resolved),
        )

    def _ensure_inside_root(self, path: Path) -> None:
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise MediaBrowserError("media path escapes shared media root") from exc

    def _media_type(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in VIDEO_SUFFIXES:
            return "video"
        if suffix in DOCUMENT_SUFFIXES:
            return "document"
        return "unknown"
