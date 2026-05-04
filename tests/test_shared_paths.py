from pathlib import Path

import pytest

from tg_bot_aggregator.domain.media.paths import SharedPathError, validate_shared_file


def test_validate_shared_file_success(tmp_path: Path) -> None:
    file_path = tmp_path / "outbox" / "video.mp4"
    file_path.parent.mkdir()
    file_path.write_bytes(b"abc")

    result = validate_shared_file(tmp_path, "outbox/video.mp4", max_size_bytes=10)

    assert result.relative_path == "outbox/video.mp4"
    assert result.resolved_path == file_path.resolve()
    assert result.file_uri.startswith("file://")
    assert result.size_bytes == 3


@pytest.mark.parametrize("path", ["/tmp/file.mp4", "../file.mp4", "outbox/../../file.mp4"])
def test_validate_shared_file_rejects_unsafe_paths(tmp_path: Path, path: str) -> None:
    with pytest.raises(SharedPathError):
        validate_shared_file(tmp_path, path, max_size_bytes=10)


def test_validate_shared_file_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SharedPathError, match="does not exist"):
        validate_shared_file(tmp_path, "missing.mp4", max_size_bytes=10)


def test_validate_shared_file_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    link = tmp_path / "link.txt"
    link.symlink_to(outside)

    with pytest.raises(SharedPathError, match="escapes"):
        validate_shared_file(tmp_path, "link.txt", max_size_bytes=10)


def test_validate_shared_file_rejects_large_file(tmp_path: Path) -> None:
    file_path = tmp_path / "large.bin"
    file_path.write_bytes(b"12345")

    with pytest.raises(SharedPathError, match="maximum"):
        validate_shared_file(tmp_path, "large.bin", max_size_bytes=4)

