import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED_SECRET_SCAN_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "output",
}
LEAKED_TEST_BOT_TOKEN_PREFIX = "8578509043" + ":"
LEGACY_MODULE_IMPORT_MARKERS = [
    "tg_bot_aggregator.repositories",
    "tg_bot_aggregator.config",
    "tg_bot_aggregator.db",
    "tg_bot_aggregator.security",
    "tg_bot_aggregator.events",
    "tg_bot_aggregator.telegram_bot_api",
    "tg_bot_aggregator.api_tokens",
    "tg_bot_aggregator.auth_middleware",
    "tg_bot_aggregator.mcp_catalog",
    "tg_bot_aggregator.mcp_server",
    "tg_bot_aggregator.media_browser",
    "tg_bot_aggregator.shared_paths",
    "tg_bot_aggregator.template_renderer",
    "tg_bot_aggregator.send_service",
    "tg_bot_aggregator.workflow_service",
    "tg_bot_aggregator.reliability",
    "tg_bot_aggregator.operations_service",
    "tg_bot_aggregator.backup_service",
    "tg_bot_aggregator.analytics_service",
    "tg_bot_aggregator.mtproto_service",
    "tg_bot_aggregator.telegram_ops",
]


def test_oss_repository_files_exist() -> None:
    expected = [
        "LICENSE",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        "CHANGELOG.md",
        ".dockerignore",
        ".python-version",
        "MANIFEST.in",
        "uv.lock",
        ".github/workflows/ci.yml",
        ".gitea/ISSUE_TEMPLATE/bug_report.md",
        ".gitea/ISSUE_TEMPLATE/feature_request.md",
    ]

    missing = [path for path in expected if not (ROOT / path).is_file()]

    assert missing == []


def test_rnet_deploy_workflow_uses_pve_deploy_and_nginx_update() -> None:
    workflow = (ROOT / ".gitea/workflows/ci-deploy.yml").read_text()

    assert "concurrency:" in workflow
    assert "runs-on: python" in workflow
    assert "uv sync --extra dev --locked" in workflow
    assert 'pve-deploy ensure "$CT_ID" "$CT_NAME"' in workflow
    assert "deploy/env/prepare-lxc-bundle.sh" in workflow
    assert 'pve-deploy deploy "$CT_ID" "$DEPLOY_BUNDLE" deploy/docker-compose.lxc.yml' in workflow
    assert "up -d --build --force-recreate --remove-orphans" in workflow
    assert 'bash deploy/nginx/update-nginx-ui.sh "$NGINX_UI_CT_ID"' in workflow
    assert "Smoke test app and proxy" in workflow
    assert "curl -fsS \"http://${APP_IP}:8000/api/v1/health\"" in workflow
    assert "Waiting for app health, attempt ${attempt}/45" in workflow
    assert "git push github HEAD:main --force" in workflow


def test_github_mirror_ci_exists_for_portfolio_repo() -> None:
    workflow = ROOT / ".github/workflows/ci.yml"
    content = workflow.read_text()

    assert "name: GitHub CI" in content
    assert "uv sync --extra dev --locked" in content
    assert "uv run ruff check ." in content
    assert "uv run pytest -q" in content
    assert "README.md" in content


def test_lxc_env_template_and_bundle_script_exist_without_secret_values() -> None:
    template = (ROOT / "deploy/env/.env.lxc.template").read_text()
    script = (ROOT / "deploy/env/prepare-lxc-bundle.sh").read_text()

    assert "TELEGRAM_API_ID={{TELEGRAM_API_ID}}" in template
    assert "TELEGRAM_API_HASH={{TELEGRAM_API_HASH}}" in template
    assert "mktemp -d" in script
    assert "install -m 600" in script
    assert "rsync" in script
    assert "b93aadb8" not in template
    assert "b93aadb8" not in script


def test_lxc_configure_script_uses_nfs_v4_media_pseudo_root() -> None:
    script = (ROOT / "deploy/proxmox/configure-lxc.sh").read_text()

    assert 'MEDIA_EXPORT="${MEDIA_EXPORT:-192.168.1.23:/media}"' in script
    assert "mount -t nfs -o vers=4 ${MEDIA_EXPORT}" in script


def test_package_metadata_points_to_public_portfolio_mirror() -> None:
    metadata = (ROOT / "pyproject.toml").read_text()

    assert 'Homepage = "https://github.com/Mesteriis/tg-bots"' in metadata
    assert 'Repository = "https://github.com/Mesteriis/tg-bots"' in metadata
    assert '"Internal Deploy Repository" = "https://git.sh-inc.ru/avm/tg-bots"' in metadata


def test_deploy_scripts_are_present_and_do_not_commit_telegram_secrets() -> None:
    scripts = [
        "deploy/proxmox/configure-lxc.sh",
        "deploy/proxmox/ct-ip.sh",
        "deploy/nginx/update-nginx-ui.sh",
    ]

    for script in scripts:
        content = (ROOT / script).read_text()
        assert content.startswith("#!/usr/bin/env bash")
        assert "TELEGRAM_API_HASH=" not in content
        assert "TELEGRAM_API_ID=" not in content
        assert LEAKED_TEST_BOT_TOKEN_PREFIX not in content


def test_repository_does_not_contain_known_leaked_test_bot_token_prefix() -> None:
    leaked_paths: list[str] = []
    listed_files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    for listed_file in listed_files:
        path = ROOT / listed_file
        if IGNORED_SECRET_SCAN_DIRS.intersection(Path(listed_file).parts):
            continue

        try:
            content = path.read_text()
        except UnicodeDecodeError:
            continue

        if LEAKED_TEST_BOT_TOKEN_PREFIX in content:
            leaked_paths.append(listed_file)

    assert leaked_paths == []


def test_runtime_files_do_not_import_removed_compatibility_modules() -> None:
    checked_roots = ("alembic/", "src/", "tests/", "deploy/", ".gitea/", ".github/")
    offenders: list[str] = []
    listed_files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    for listed_file in listed_files:
        if listed_file == "tests/test_repository_metadata.py":
            continue
        if not listed_file.startswith(checked_roots):
            continue

        path = ROOT / listed_file
        try:
            content = path.read_text()
        except UnicodeDecodeError:
            continue

        if any(marker in content for marker in LEGACY_MODULE_IMPORT_MARKERS):
            offenders.append(listed_file)

    assert offenders == []


def test_deploy_compose_contains_runtime_services() -> None:
    compose = (ROOT / "deploy/docker-compose.lxc.yml").read_text()

    for service in [
        "app:",
        "worker:",
        "scheduler:",
        "diagnostic-bot:",
        "discovery-bot:",
        "redis:",
        "telegram-bot-api:",
    ]:
        assert service in compose
    assert "/mnt/omw-media:/shared/media:ro" in compose


def test_lxc_deploy_compose_paths_resolve_from_deploy_directory() -> None:
    compose = (ROOT / "deploy/docker-compose.lxc.yml").read_text()
    lines = {line.strip() for line in compose.splitlines()}

    assert "build: ." not in lines
    assert "build: .." in lines
    assert "- path: .env" not in lines
    assert "- path: ../.env" in lines
