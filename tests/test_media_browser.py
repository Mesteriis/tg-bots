from pathlib import Path

import pytest

from tg_bot_aggregator.domain.media.browser import MediaBrowser, MediaBrowserError


def test_media_browser_lists_direct_children_without_host_paths(tmp_path: Path) -> None:
    (tmp_path / "clips").mkdir()
    (tmp_path / "clips" / "demo.mp4").write_bytes(b"video")
    (tmp_path / "readme.txt").write_text("notes")
    browser = MediaBrowser(tmp_path)

    listing = browser.list_directory("")

    assert listing.relative_path == ""
    assert [item.name for item in listing.items] == ["clips", "readme.txt"]
    assert listing.items[0].kind == "directory"
    assert listing.items[1].kind == "file"
    assert listing.items[1].media_type == "document"
    assert str(tmp_path) not in listing.items[1].relative_path


def test_media_browser_rejects_absolute_and_traversal_paths(tmp_path: Path) -> None:
    browser = MediaBrowser(tmp_path)

    with pytest.raises(MediaBrowserError, match="relative"):
        browser.list_directory(str(tmp_path))

    with pytest.raises(MediaBrowserError, match="traversal"):
        browser.list_directory("../outside")
