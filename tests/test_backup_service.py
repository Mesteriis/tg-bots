import subprocess
from pathlib import Path

import pytest

from tg_bot_aggregator.domain.backups import service as backup_service
from tg_bot_aggregator.schemas import RuntimeSettingsRead


def test_run_git_reports_missing_git_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_missing_binary(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git")

    monkeypatch.setattr(backup_service.subprocess, "run", raise_missing_binary)

    with pytest.raises(backup_service.BackupServiceError) as exc:
        backup_service._run_git(["git", "status"])

    assert str(exc.value) == "git executable is not installed in the application container"


def test_authenticated_git_repo_url_uses_gitea_token_for_https_clone() -> None:
    settings = RuntimeSettingsRead(
        app_host="0.0.0.0",
        app_port=8000,
        database_url="sqlite+aiosqlite:////data/app.db",
        redis_url="redis://redis:6379/0",
        telegram_api_id=None,
        telegram_api_hash=None,
        telegram_bot_api_base_url="http://telegram-bot-api:8081",
        cors_allowed_origins=["http://localhost:8000"],
        mcp_allowed_origins=["http://localhost:8000"],
        shared_media_root="/shared/media",
        shared_media_require_mount=True,
        max_local_file_bytes=2_097_152_000,
        telethon_session_dir="/data/telethon",
        diagnostic_poll_timeout_seconds=30,
        diagnostic_retry_delay_seconds=5.0,
        discovery_poll_timeout_seconds=30,
        discovery_retry_delay_seconds=5.0,
        send_retry_max_attempts=3,
        send_retry_delay_seconds=1.0,
        reliability_enabled=False,
        send_default_mode="sync",
        send_global_rate_per_minute=None,
        send_bot_rate_per_minute=None,
        send_chat_rate_per_minute=None,
        send_destination_rate_per_minute=None,
        send_retry_base_delay_seconds=1.0,
        send_retry_max_delay_seconds=300.0,
        send_worker_lease_seconds=60,
        send_stale_lock_grace_seconds=30,
        send_dedupe_window_seconds=None,
        protected_api_hosts=["tg.sh-inc.ru"],
        policy_enabled=False,
        rate_limit_per_minute=None,
        quiet_hours_start=None,
        quiet_hours_end=None,
        callback_enabled=False,
        callback_url=None,
        backup_git_repo_url="https://git.sh-inc.ru/avm/tg-bots-backup.git",
        backup_git_branch="main",
        backup_git_path="tg-bots.json",
        backup_git_service="gitea",
        backup_git_auth_method="token",
        backup_git_api_base_url="https://git.sh-inc.ru/api/v1",
        backup_git_api_token="secret-token",
        backup_include_secrets=False,
        backup_schedule_enabled=False,
        backup_schedule_interval_seconds=86400,
        backup_schedule_push_to_git=False,
    )

    auth_url = backup_service._authenticated_git_repo_url(
        settings,
        "https://git.sh-inc.ru/avm/tg-bots-backup.git",
        "gitea",
    )

    assert auth_url == "https://oauth2:secret-token@git.sh-inc.ru/avm/tg-bots-backup.git"


def test_push_snapshot_bootstraps_empty_repo_without_remote_branch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = RuntimeSettingsRead(
        app_host="0.0.0.0",
        app_port=8000,
        database_url="sqlite+aiosqlite:////data/app.db",
        redis_url="redis://redis:6379/0",
        telegram_api_id=None,
        telegram_api_hash=None,
        telegram_bot_api_base_url="http://telegram-bot-api:8081",
        cors_allowed_origins=["http://localhost:8000"],
        mcp_allowed_origins=["http://localhost:8000"],
        shared_media_root="/shared/media",
        shared_media_require_mount=True,
        max_local_file_bytes=2_097_152_000,
        telethon_session_dir="/data/telethon",
        diagnostic_poll_timeout_seconds=30,
        diagnostic_retry_delay_seconds=5.0,
        discovery_poll_timeout_seconds=30,
        discovery_retry_delay_seconds=5.0,
        send_retry_max_attempts=3,
        send_retry_delay_seconds=1.0,
        reliability_enabled=False,
        send_default_mode="sync",
        send_global_rate_per_minute=None,
        send_bot_rate_per_minute=None,
        send_chat_rate_per_minute=None,
        send_destination_rate_per_minute=None,
        send_retry_base_delay_seconds=1.0,
        send_retry_max_delay_seconds=300.0,
        send_worker_lease_seconds=60,
        send_stale_lock_grace_seconds=30,
        send_dedupe_window_seconds=None,
        protected_api_hosts=["tg.sh-inc.ru"],
        policy_enabled=False,
        rate_limit_per_minute=None,
        quiet_hours_start=None,
        quiet_hours_end=None,
        callback_enabled=False,
        callback_url=None,
        backup_git_repo_url="https://git.sh-inc.ru/avm/tg-bots-backup.git",
        backup_git_branch="main",
        backup_git_path="tg-bots.json",
        backup_git_service="gitea",
        backup_git_auth_method="token",
        backup_git_api_base_url="https://git.sh-inc.ru/api/v1",
        backup_git_api_token="secret-token",
        backup_include_secrets=False,
        backup_schedule_enabled=False,
        backup_schedule_interval_seconds=86400,
        backup_schedule_push_to_git=False,
    )
    service = backup_service.BackupService(
        session=None,
        settings=settings,
        workdir=tmp_path / "backup-repo",
    )
    commands: list[tuple[list[str], Path | None]] = []

    def fake_run_git(args: list[str], cwd: Path | None = None) -> str:
        commands.append((args, cwd))
        if args[:4] == ["git", "clone", "--branch", "main"]:
            raise backup_service.BackupServiceError(
                "fatal: Remote branch main not found in upstream origin"
            )
        if args[:4] == ["git", "rev-parse", "--verify", "origin/main"] and cwd is not None:
            raise backup_service.BackupServiceError("fatal: Needed a single revision")
        if args[:3] == ["git", "status", "--porcelain"]:
            return "M tg-bots.json"
        if args[:3] == ["git", "rev-parse", "HEAD"]:
            return "abc123"
        if args[:2] == ["git", "clone"]:
            (tmp_path / "backup-repo" / ".git").mkdir(parents=True, exist_ok=True)
        return ""

    monkeypatch.setattr(backup_service, "_run_git", fake_run_git)

    commit = service._push_snapshot_sync({"bots": []})

    assert commit == "abc123"
    assert commands[0][0][:4] == ["git", "clone", "--branch", "main"]
    assert commands[1][0][:2] == ["git", "clone"]
    assert any(args[:4] == ["git", "checkout", "-B", "main"] for args, _ in commands)
    assert any(args[:3] == ["git", "push", "origin"] for args, _ in commands)
