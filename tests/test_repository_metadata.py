import subprocess
from importlib import import_module
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.core.time import utc_now
from tg_bot_aggregator.domain.operations.repository import RuntimeSettingsRepository

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
        if not path.is_file():
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
        if not path.is_file():
            continue
        try:
            content = path.read_text()
        except UnicodeDecodeError:
            continue

        if any(marker in content for marker in LEGACY_MODULE_IMPORT_MARKERS):
            offenders.append(listed_file)

    assert offenders == []


def test_domain_schema_modules_exist() -> None:
    expectations = [
        ("tg_bot_aggregator.domain.bots.schemas", "BotCreate"),
        ("tg_bot_aggregator.domain.destinations.schemas", "DestinationCreate"),
        ("tg_bot_aggregator.domain.templates.schemas", "TemplateCreate"),
        ("tg_bot_aggregator.domain.sending.schemas", "SendTextRequest"),
        ("tg_bot_aggregator.domain.batches.schemas", "SendBatchCreate"),
        ("tg_bot_aggregator.domain.reliability.schemas", "ReliabilitySummaryRead"),
        ("tg_bot_aggregator.domain.operations.schemas", "RuntimeSettingsRead"),
        ("tg_bot_aggregator.domain.backups.schemas", "BackupRunRead"),
        ("tg_bot_aggregator.domain.diagnostics.schemas", "DiagnosticBotSettingsRead"),
        ("tg_bot_aggregator.domain.discovery.schemas", "BotDiscoverySettingsRead"),
        ("tg_bot_aggregator.domain.analytics.schemas", "AnalyticsTargetRead"),
        ("tg_bot_aggregator.domain.auth.schemas", "ApiTokenRead"),
        ("tg_bot_aggregator.domain.mcp.schemas", "McpSettingsRead"),
        ("tg_bot_aggregator.domain.media.schemas", "MediaListingRead"),
        ("tg_bot_aggregator.domain.ops.schemas", "OpsRecommendationRead"),
    ]

    for module_name, symbol in expectations:
        module = import_module(module_name)
        assert getattr(module, symbol)


def test_api_and_domain_modules_do_not_depend_on_root_schema_aggregator() -> None:
    checked_roots = (
        ROOT / "src/tg_bot_aggregator/api",
        ROOT / "src/tg_bot_aggregator/domain",
        ROOT / "src/tg_bot_aggregator/runtime_settings.py",
    )
    offenders: list[str] = []

    for checked_root in checked_roots:
        paths = [checked_root] if checked_root.is_file() else checked_root.rglob("*.py")
        for path in paths:
            content = path.read_text()
            if "from tg_bot_aggregator.schemas import" in content:
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_domain_model_modules_exist() -> None:
    expectations = [
        ("tg_bot_aggregator.domain.bots.models", "Bot"),
        ("tg_bot_aggregator.domain.destinations.models", "Destination"),
        ("tg_bot_aggregator.domain.templates.models", "MessageTemplate"),
        ("tg_bot_aggregator.domain.sending.models", "SendHistory"),
        ("tg_bot_aggregator.domain.batches.models", "SendBatch"),
        ("tg_bot_aggregator.domain.reliability.models", "SendAttempt"),
        ("tg_bot_aggregator.domain.operations.models", "RuntimeSettings"),
        ("tg_bot_aggregator.domain.backups.models", "BackupRun"),
        ("tg_bot_aggregator.domain.diagnostics.models", "DiagnosticBotSettings"),
        ("tg_bot_aggregator.domain.discovery.models", "BotDiscoverySettings"),
        ("tg_bot_aggregator.domain.analytics.models", "AnalyticsTarget"),
        ("tg_bot_aggregator.domain.auth.models", "ApiToken"),
        ("tg_bot_aggregator.domain.mcp.models", "McpSettings"),
        ("tg_bot_aggregator.domain.ops.models", "OpsRecommendation"),
        ("tg_bot_aggregator.domain.audit.models", "AuditEvent"),
    ]

    for module_name, symbol in expectations:
        module = import_module(module_name)
        assert getattr(module, symbol)


def test_domain_repositories_do_not_depend_on_root_model_aggregator() -> None:
    offenders: list[str] = []

    for path in (ROOT / "src/tg_bot_aggregator/domain").rglob("repository.py"):
        content = path.read_text()
        if "from tg_bot_aggregator.models import" in content:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_core_time_no_longer_depends_on_root_models_module() -> None:
    content = (ROOT / "src/tg_bot_aggregator/core/time.py").read_text()

    assert "from tg_bot_aggregator.models import utc_now" not in content
    assert "def utc_now()" in content


def test_root_compatibility_aggregator_modules_are_removed() -> None:
    assert not (ROOT / "src/tg_bot_aggregator/models.py").exists()
    assert not (ROOT / "src/tg_bot_aggregator/schemas.py").exists()


def test_service_and_runtime_layers_prefer_domain_model_entrypoints() -> None:
    checked_paths = [
        ROOT / "src/tg_bot_aggregator/tasks.py",
        ROOT / "src/tg_bot_aggregator/api/v1/sending.py",
        ROOT / "src/tg_bot_aggregator/domain/reliability/service.py",
        ROOT / "src/tg_bot_aggregator/domain/ops/service.py",
        ROOT / "src/tg_bot_aggregator/domain/mcp/server.py",
        ROOT / "src/tg_bot_aggregator/domain/backups/service.py",
        ROOT / "src/tg_bot_aggregator/domain/sending/service.py",
    ]
    offenders: list[str] = []

    for path in checked_paths:
        content = path.read_text()
        if "from tg_bot_aggregator.models import" in content:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_api_v1_route_modules_do_not_depend_on_legacy_route_wrappers() -> None:
    offenders: list[str] = []

    for path in (ROOT / "src/tg_bot_aggregator/api/v1").glob("*.py"):
        if path.name == "__init__.py":
            continue
        content = path.read_text()
        if (
            "from tg_bot_aggregator.api." in content
            and "api.dependencies" not in content
            and "api.deps" not in content
        ):
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_api_v1_route_modules_prefer_api_deps_module() -> None:
    offenders: list[str] = []

    for path in (ROOT / "src/tg_bot_aggregator/api/v1").glob("*.py"):
        if path.name in {"__init__.py", "backups.py", "events.py"}:
            continue
        content = path.read_text()
        if "from tg_bot_aggregator.api.dependencies import" in content:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_main_bootstrap_does_not_depend_on_root_model_aggregator() -> None:
    content = (ROOT / "src/tg_bot_aggregator/main.py").read_text()

    assert "from tg_bot_aggregator.models import Base" not in content
    assert "resolve_runtime_database_state" in content


def test_runtime_modules_do_not_depend_on_root_compatibility_aggregators() -> None:
    checked_paths = [
        ROOT / "src/tg_bot_aggregator/domain/diagnostics/bot.py",
        ROOT / "src/tg_bot_aggregator/domain/discovery/bot.py",
        ROOT / "src/tg_bot_aggregator/domain/reliability/models.py",
        ROOT / "src/tg_bot_aggregator/infra/events.py",
    ]
    offenders: list[str] = []

    for path in checked_paths:
        content = path.read_text()
        if (
            "from tg_bot_aggregator.models import" in content
            or "from tg_bot_aggregator.schemas import" in content
        ):
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_api_package_uses_target_route_layout_without_legacy_route_modules() -> None:
    api_root = ROOT / "src/tg_bot_aggregator/api"
    legacy_route_modules = [
        "analytics.py",
        "audit.py",
        "auth.py",
        "bots.py",
        "destinations.py",
        "diagnostics.py",
        "discovery.py",
        "events.py",
        "health.py",
        "mcp_settings.py",
        "media.py",
        "mtproto.py",
        "operations.py",
        "ops.py",
        "reliability.py",
        "send.py",
        "send_batches.py",
        "send_profiles.py",
        "telegram_compat.py",
        "templates.py",
        "dependencies.py",
    ]

    missing_target_files = [
        "deps.py",
        "router.py",
        "v1/backups.py",
        "v1/operations.py",
        "v1/sending.py",
    ]

    for relative_path in legacy_route_modules:
        assert not (api_root / relative_path).exists()

    for relative_path in missing_target_files:
        assert (api_root / relative_path).exists()


def test_selected_runtime_modules_use_unit_of_work() -> None:
    expectations = {
        "src/tg_bot_aggregator/api/deps.py": "get_uow",
        "src/tg_bot_aggregator/api/v1/auth.py": "get_uow",
        "src/tg_bot_aggregator/api/v1/bots.py": "get_uow",
        "src/tg_bot_aggregator/api/v1/destinations.py": "get_uow",
        "src/tg_bot_aggregator/api/v1/templates.py": "get_uow",
        "src/tg_bot_aggregator/api/v1/analytics.py": "get_uow",
        "src/tg_bot_aggregator/api/v1/operations.py": "get_uow",
        "src/tg_bot_aggregator/api/v1/backups.py": "get_uow",
        "src/tg_bot_aggregator/api/v1/send_batches.py": "get_uow",
        "src/tg_bot_aggregator/api/v1/send_profiles.py": "get_uow",
        "src/tg_bot_aggregator/tasks.py": "UnitOfWork",
    }

    for relative_path, marker in expectations.items():
        content = (ROOT / relative_path).read_text()
        assert marker in content


async def test_runtime_settings_repository_persists_telegram_egress_metadata(
    db_session: AsyncSession,
) -> None:
    repository = RuntimeSettingsRepository(db_session)
    connected_at = utc_now()
    handshake_at = utc_now()

    await repository.upsert(
        telegram_egress_mode="wireguard",
        telegram_egress_enabled=True,
        telegram_egress_provider="wireguard",
        telegram_egress_last_status="connected",
        telegram_egress_last_error=None,
        telegram_egress_connected_at=connected_at,
        telegram_egress_last_handshake_at=handshake_at,
        telegram_egress_last_egress_ip="203.0.113.5",
    )
    await db_session.commit()

    loaded = await repository.get()

    assert loaded is not None
    assert loaded.telegram_egress_mode == "wireguard"
    assert loaded.telegram_egress_enabled is True
    assert loaded.telegram_egress_provider == "wireguard"
    assert loaded.telegram_egress_last_status == "connected"
    assert loaded.telegram_egress_last_error is None
    assert loaded.telegram_egress_connected_at is not None
    assert loaded.telegram_egress_last_handshake_at is not None
    assert loaded.telegram_egress_connected_at.replace(tzinfo=connected_at.tzinfo) == connected_at
    assert (
        loaded.telegram_egress_last_handshake_at.replace(tzinfo=handshake_at.tzinfo)
        == handshake_at
    )
    assert loaded.telegram_egress_last_egress_ip == "203.0.113.5"


async def test_runtime_settings_repository_get_does_not_dirty_session(
    db_session: AsyncSession,
) -> None:
    repository = RuntimeSettingsRepository(db_session)

    await repository.upsert(
        telegram_egress_mode="wireguard",
        telegram_egress_enabled=True,
        telegram_egress_provider="wireguard",
        telegram_egress_last_status="connected",
        telegram_egress_connected_at=utc_now(),
        telegram_egress_last_handshake_at=utc_now(),
    )
    await db_session.commit()

    loaded = await repository.get()

    assert loaded is not None
    assert not db_session.dirty


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
