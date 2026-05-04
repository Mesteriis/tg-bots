import subprocess

import pytest

from tg_bot_aggregator.domain.backups import service as backup_service


def test_run_git_reports_missing_git_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_missing_binary(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git")

    monkeypatch.setattr(backup_service.subprocess, "run", raise_missing_binary)

    with pytest.raises(backup_service.BackupServiceError) as exc:
        backup_service._run_git(["git", "status"])

    assert str(exc.value) == "git executable is not installed in the application container"
