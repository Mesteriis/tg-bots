# Application Structure and CI Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the application toward the requested `core/api/domain/infra` layout without breaking the deployed service, and harden the Gitea-to-PVE deploy pipeline including GitHub mirror publishing.

**Architecture:** This is an evolutionary refactor, not a big-bang rewrite. The first pass creates the requested package boundaries with compatibility wrappers and focused import migrations; later passes can physically split the large ORM/schema files once the public import paths are stable. CI/deploy changes are independent and should be shipped first because they reduce release risk.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy async, Alembic, pytest, Ruff, Docker Compose, Gitea Actions, RNet `pve-deploy`, nginx-ui LXC, GitHub Actions mirror CI.

---

## Verified Current State

- Current package is mostly flat under `src/tg_bot_aggregator`.
- Current API routers live in `src/tg_bot_aggregator/api/*.py`, not `api/v1/*.py`.
- `deploy/docker-compose.lxc.yml` already runs `python -m tg_bot_aggregator.migration_repair && alembic upgrade head` before `uvicorn`.
- `.gitea/workflows/ci-deploy.yml` writes `.env` in the checked-out workspace and deploys that workspace.
- `.gitea/workflows/ci-deploy.yml` defines `NGINX_UI_CT_ID=112` but calls `deploy/nginx/update-nginx-ui.sh "$CT_ID"`.
- `deploy/nginx/update-nginx-ui.sh` uses the first positional argument as app CT id only when `APP_UPSTREAM` is not supplied, and pushes config into `${NGINX_UI_CT_ID}`.
- Public protected API hosts are expected to return `401` without a permanent API token. Smoke checks for protected host API endpoints must account for that.

## Target File Structure

Create or populate these packages:

- `src/tg_bot_aggregator/core/`
  - `config.py`: settings and environment parsing.
  - `db.py`: async engine/session factory helpers.
  - `time.py`: `utc_now`.
  - `errors.py`: domain errors, including `NotFoundError`.
  - `logging.py`: logging/bootstrap helpers.
  - `security.py`: token, redaction, protected-host helpers.
- `src/tg_bot_aggregator/api/`
  - `router.py`: root `/api/v1` router aggregator.
  - `deps.py`: FastAPI dependencies.
  - `v1/*.py`: versioned route modules.
- `src/tg_bot_aggregator/domain/*/`
  - `models.py`: domain ORM exports for that slice.
  - `schemas.py`: Pydantic schema exports for that slice.
  - `repository.py`: repositories for that slice.
  - `service.py` and focused helpers where a service already exists.
- `src/tg_bot_aggregator/infra/`
  - `uow.py`: small Unit of Work.
  - `taskiq.py`: broker/task config facade.
  - `telegram_client.py`: Telegram Bot API client.
  - `events.py`: SSE/event bus.
  - `audit.py`: audit writer/repository facade.

Keep these compatibility files during the migration:

- `src/tg_bot_aggregator/config.py`
- `src/tg_bot_aggregator/db.py`
- `src/tg_bot_aggregator/models.py`
- `src/tg_bot_aggregator/repositories.py`
- `src/tg_bot_aggregator/schemas.py`
- `src/tg_bot_aggregator/events.py`
- `src/tg_bot_aggregator/telegram_bot_api.py`

They should re-export from the new packages after imports are migrated. Removing them is a later cleanup after tests and deployed imports prove stable.

## Repository Split Map

- `BotRepository` -> `domain/bots/repository.py`
- `ApiTokenRepository` -> `domain/auth/repository.py`
- `McpSettingsRepository`, `McpCoverageSnapshotRepository` -> `domain/mcp/repository.py`
- `RuntimeSettingsRepository`, `RuntimeAdvancedSettingsRepository` -> `domain/operations/repository.py`
- `BackupRunRepository` -> `domain/backups/repository.py`
- `DestinationRepository`, `DestinationHealthRepository` -> `domain/destinations/repository.py`
- `TemplateRepository`, `TemplateVersionRepository` -> `domain/templates/repository.py`
- `SendProfileRepository`, `SendHistoryRepository`, `SendAttemptRepository` -> `domain/sending/repository.py`
- `SendBatchRepository` -> `domain/batches/repository.py`
- `AuditRepository` -> `infra/audit.py`
- `DiagnosticSettingsRepository`, `DiagnosticUpdateRepository` -> `domain/diagnostics/repository.py`
- `BotDiscoverySettingsRepository`, `BotDiscoveryEventRepository` -> `domain/discovery/repository.py`
- `OpsFactRepository`, `OpsRecommendationRepository`, `OpsAutomationRuleRepository`, `OpsActionRunRepository` -> `domain/ops/repository.py`
- `MtprotoSessionRepository`, `AnalyticsRepository` -> `domain/analytics/repository.py`

## Task 1: Harden Deploy Workflow Before Architecture Moves

**Files:**
- Modify: `.gitea/workflows/ci-deploy.yml`
- Create: `deploy/env/.env.lxc.template`
- Create: `deploy/env/prepare-lxc-bundle.sh`
- Create: `.github/workflows/ci.yml`
- Modify: `tests/test_repository_metadata.py`

- [ ] **Step 1: Write metadata tests for the safer deploy shape**

Update `tests/test_repository_metadata.py` so `test_rnet_deploy_workflow_uses_pve_deploy_and_nginx_update` asserts:

```python
assert "concurrency:" in workflow
assert "uv sync --extra dev --locked" in workflow
assert "deploy/env/prepare-lxc-bundle.sh" in workflow
assert 'pve-deploy deploy "$CT_ID" "$DEPLOY_BUNDLE" deploy/docker-compose.lxc.yml' in workflow
assert 'bash deploy/nginx/update-nginx-ui.sh "$NGINX_UI_CT_ID"' in workflow
assert "Smoke test app and proxy" in workflow
assert "git push github HEAD:main --force" in workflow
```

Add a new test:

```python
def test_github_mirror_ci_exists_for_portfolio_repo() -> None:
    workflow = ROOT / ".github/workflows/ci.yml"
    content = workflow.read_text()

    assert "name: GitHub CI" in content
    assert "uv sync --extra dev --locked" in content
    assert "uv run ruff check ." in content
    assert "uv run pytest -q" in content
    assert "README.md" in content
```

Add a new test:

```python
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
```

- [ ] **Step 2: Run metadata tests and verify they fail**

Run:

```bash
uv run pytest tests/test_repository_metadata.py -q
```

Expected: failing assertions for missing workflow/template/script.

- [ ] **Step 3: Add `deploy/env/.env.lxc.template`**

Create:

```dotenv
APP_HOST=0.0.0.0
APP_PORT=8000
DATABASE_URL=sqlite+aiosqlite:////data/app.db
REDIS_URL=redis://redis:6379/0
TELEGRAM_API_ID={{TELEGRAM_API_ID}}
TELEGRAM_API_HASH={{TELEGRAM_API_HASH}}
TELEGRAM_BOT_API_BASE_URL=http://telegram-bot-api:8081
SHARED_MEDIA_ROOT=/shared/media
MAX_LOCAL_FILE_BYTES=2097152000
CORS_ALLOWED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000,https://tg.sh-inc.ru,https://tg.sh-inc.dev
MCP_ALLOWED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000,https://tg.sh-inc.ru,https://tg.sh-inc.dev
PROTECTED_API_HOSTS=tg.sh-inc.ru,tg.sh-inc.dev
TELETHON_SESSION_DIR=/data/telethon
SCHEDULER_INTERVAL_SECONDS=3600
DIAGNOSTIC_POLL_TIMEOUT_SECONDS=30
DIAGNOSTIC_RETRY_DELAY_SECONDS=5
DISCOVERY_POLL_TIMEOUT_SECONDS=30
DISCOVERY_RETRY_DELAY_SECONDS=5
SEND_RETRY_MAX_ATTEMPTS=3
SEND_RETRY_DELAY_SECONDS=1
```

- [ ] **Step 4: Add deploy bundle preparation script**

Create `deploy/env/prepare-lxc-bundle.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE="${ROOT_DIR}/deploy/env/.env.lxc.template"

if [ -z "${TELEGRAM_API_ID:-}" ]; then
  echo "TELEGRAM_API_ID is required" >&2
  exit 2
fi

if [ -z "${TELEGRAM_API_HASH:-}" ]; then
  echo "TELEGRAM_API_HASH is required" >&2
  exit 2
fi

bundle_dir="$(mktemp -d)"
rsync -a --delete \
  --exclude .git \
  --exclude .venv \
  --exclude .mypy_cache \
  --exclude .pytest_cache \
  --exclude .ruff_cache \
  --exclude __pycache__ \
  "${ROOT_DIR}/" "${bundle_dir}/"

install -m 600 /dev/null "${bundle_dir}/.env"
sed \
  -e "s|{{TELEGRAM_API_ID}}|${TELEGRAM_API_ID}|g" \
  -e "s|{{TELEGRAM_API_HASH}}|${TELEGRAM_API_HASH}|g" \
  "${TEMPLATE}" > "${bundle_dir}/.env"

printf '%s\n' "${bundle_dir}"
```

- [ ] **Step 5: Update Gitea workflow**

Change `.gitea/workflows/ci-deploy.yml` to:

```yaml
name: CI and RNet Deploy

on:
  push:
    branches: [main]
  pull_request:

concurrency:
  group: tg-bots-${{ github.ref }}
  cancel-in-progress: true

env:
  CT_ID: 103
  CT_NAME: tg-bots
  CT_MEMORY: 8192
  CT_CORES: 4
  CT_DISK: 64
  PVE_HOST: 192.168.1.2
  NGINX_UI_CT_ID: 112

jobs:
  test:
    runs-on: python
    steps:
      - uses: actions/checkout@v4
      - run: uv sync --extra dev --locked
      - run: uv run ruff check .
      - run: uv run pytest -q

  deploy:
    needs: test
    runs-on: main
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4

      - name: Ensure Proxmox LXC
        run: pve-deploy ensure "$CT_ID" "$CT_NAME" "$CT_MEMORY" "$CT_CORES" "$CT_DISK"

      - name: Configure Proxmox LXC
        run: bash deploy/proxmox/configure-lxc.sh "$CT_ID"

      - name: Prepare deploy bundle
        run: |
          DEPLOY_BUNDLE="$(TELEGRAM_API_ID='${{ secrets.TELEGRAM_API_ID }}' TELEGRAM_API_HASH='${{ secrets.TELEGRAM_API_HASH }}' bash deploy/env/prepare-lxc-bundle.sh)"
          echo "DEPLOY_BUNDLE=${DEPLOY_BUNDLE}" >> "$GITHUB_ENV"

      - name: Deploy Docker Compose stack
        run: |
          pve-deploy deploy "$CT_ID" "$DEPLOY_BUNDLE" deploy/docker-compose.lxc.yml
          APP_IP="$(bash deploy/proxmox/ct-ip.sh "$CT_ID")"
          ssh "root@${APP_IP}" "cd /opt/app && docker compose -f deploy/docker-compose.lxc.yml up -d --build --force-recreate --remove-orphans"

      - name: Update nginx-ui upstream
        run: |
          APP_IP="$(bash deploy/proxmox/ct-ip.sh "$CT_ID")"
          APP_UPSTREAM="http://${APP_IP}:8000" bash deploy/nginx/update-nginx-ui.sh "$NGINX_UI_CT_ID"

      - name: Smoke test app and proxy
        run: |
          APP_IP="$(bash deploy/proxmox/ct-ip.sh "$CT_ID")"
          for attempt in $(seq 1 45); do
            if curl -fsS "http://${APP_IP}:8000/api/v1/health"; then
              break
            fi
            echo "Waiting for app health, attempt ${attempt}/45"
            sleep 2
          done
          curl -fsS "http://${APP_IP}:8000/api/v1/health"
          curl -fsS "http://${APP_IP}:8000/api/v1/mcp/settings"
          curl -fsS "http://${APP_IP}:8000/api/v1/reliability/summary"
          curl -fsSI "http://${APP_IP}:8000/" | grep -q "200"
          curl -fsSI -H "Host: tg.sh-inc.ru" "http://192.168.1.7/" | grep -q "200"
          curl -fsSI -H "Host: tg.sh-inc.dev" "http://192.168.1.7/" | grep -q "200"

      - name: Push verified main to GitHub mirror
        run: |
          git remote remove github 2>/dev/null || true
          git remote add github git@github.com:Mesteriis/tg-bots.git
          git push github HEAD:main --force

      - if: success()
        run: tg-notify "tg-bots deployed to CT ${CT_ID}" --success

      - if: failure()
        run: tg-notify "tg-bots deploy failed" --fail
```

Note: the workflow intentionally verifies nginx through direct host-header checks against `192.168.1.7`; public `tg.sh-inc.dev` currently has an external Cloudflare 404 outside this repository.

- [ ] **Step 6: Add GitHub mirror CI**

Create `.github/workflows/ci.yml`:

```yaml
name: GitHub CI

on:
  push:
    branches: [main]
  pull_request:

concurrency:
  group: github-ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --extra dev --locked
      - run: uv run ruff check .
      - run: uv run pytest -q
      - name: Documentation smoke
        run: |
          test -s README.md
          test -s LICENSE
          test -s SECURITY.md
          test -s CONTRIBUTING.md
```

- [ ] **Step 7: Run validation**

Run:

```bash
chmod +x deploy/env/prepare-lxc-bundle.sh
uv run pytest tests/test_repository_metadata.py -q
uv run ruff check .
uv run pytest -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add .gitea/workflows/ci-deploy.yml .github/workflows/ci.yml deploy/env tests/test_repository_metadata.py
git commit -m "ci: harden rnet deploy and github mirror"
```

## Task 2: Create Core and Infra Package Boundaries

**Files:**
- Create: `src/tg_bot_aggregator/core/__init__.py`
- Create: `src/tg_bot_aggregator/core/config.py`
- Create: `src/tg_bot_aggregator/core/db.py`
- Create: `src/tg_bot_aggregator/core/time.py`
- Create: `src/tg_bot_aggregator/core/errors.py`
- Create: `src/tg_bot_aggregator/core/security.py`
- Create: `src/tg_bot_aggregator/core/logging.py`
- Create: `src/tg_bot_aggregator/infra/__init__.py`
- Create: `src/tg_bot_aggregator/infra/events.py`
- Create: `src/tg_bot_aggregator/infra/telegram_client.py`
- Modify: root compatibility modules.
- Test: `tests/test_import_boundaries.py`

- [ ] **Step 1: Add import-boundary tests**

Create `tests/test_import_boundaries.py`:

```python
def test_core_imports_are_available() -> None:
    from tg_bot_aggregator.core.config import Settings
    from tg_bot_aggregator.core.db import create_engine, create_session_factory
    from tg_bot_aggregator.core.errors import NotFoundError
    from tg_bot_aggregator.core.security import redact_secrets
    from tg_bot_aggregator.core.time import utc_now

    assert Settings
    assert create_engine
    assert create_session_factory
    assert issubclass(NotFoundError, ValueError)
    assert redact_secrets({"token": "secret"})["token"] == "***"
    assert utc_now().tzinfo is not None


def test_infra_imports_are_available() -> None:
    from tg_bot_aggregator.infra.events import MemoryEventBus
    from tg_bot_aggregator.infra.telegram_client import TelegramBotApiClient

    assert MemoryEventBus
    assert TelegramBotApiClient
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
uv run pytest tests/test_import_boundaries.py -q
```

Expected: import errors for missing packages.

- [ ] **Step 3: Move implementations with compatibility wrappers**

Use `git mv` where the file responsibility maps directly:

```bash
mkdir -p src/tg_bot_aggregator/core src/tg_bot_aggregator/infra
git mv src/tg_bot_aggregator/config.py src/tg_bot_aggregator/core/config.py
git mv src/tg_bot_aggregator/db.py src/tg_bot_aggregator/core/db.py
git mv src/tg_bot_aggregator/security.py src/tg_bot_aggregator/core/security.py
git mv src/tg_bot_aggregator/events.py src/tg_bot_aggregator/infra/events.py
git mv src/tg_bot_aggregator/telegram_bot_api.py src/tg_bot_aggregator/infra/telegram_client.py
```

Create wrappers:

```python
# src/tg_bot_aggregator/config.py
from tg_bot_aggregator.core.config import *  # noqa: F403
```

```python
# src/tg_bot_aggregator/db.py
from tg_bot_aggregator.core.db import *  # noqa: F403
```

```python
# src/tg_bot_aggregator/security.py
from tg_bot_aggregator.core.security import *  # noqa: F403
```

```python
# src/tg_bot_aggregator/events.py
from tg_bot_aggregator.infra.events import *  # noqa: F403
```

```python
# src/tg_bot_aggregator/telegram_bot_api.py
from tg_bot_aggregator.infra.telegram_client import *  # noqa: F403
```

Create `src/tg_bot_aggregator/core/time.py`:

```python
from tg_bot_aggregator.models import utc_now

__all__ = ["utc_now"]
```

Create `src/tg_bot_aggregator/core/errors.py`:

```python
from tg_bot_aggregator.repositories import NotFoundError

__all__ = ["NotFoundError"]
```

Create empty `__init__.py` files in `core` and `infra`.

- [ ] **Step 4: Update moved-file internal imports**

In `src/tg_bot_aggregator/core/db.py`, change:

```python
from tg_bot_aggregator.core.config import Settings, get_settings
```

to:

```python
from tg_bot_aggregator.core.config import Settings, get_settings
```

In `src/tg_bot_aggregator/infra/telegram_client.py`, change:

```python
from tg_bot_aggregator.core.security import redact_secrets, redact_text
```

to:

```python
from tg_bot_aggregator.core.security import redact_secrets, redact_text
```

If `src/tg_bot_aggregator/infra/events.py` imports schemas, leave it unchanged for this task.

- [ ] **Step 5: Run validation**

Run:

```bash
uv run pytest tests/test_import_boundaries.py -q
uv run pytest -q
uv run ruff check .
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/tg_bot_aggregator tests/test_import_boundaries.py
git commit -m "refactor: introduce core and infra package boundaries"
```

## Task 3: Create Domain Repository Modules

**Files:**
- Create: `src/tg_bot_aggregator/domain/*/__init__.py`
- Create: `src/tg_bot_aggregator/domain/*/repository.py`
- Create: `src/tg_bot_aggregator/domain/*/models.py`
- Create: `src/tg_bot_aggregator/domain/*/schemas.py`
- Modify: `tests/test_import_boundaries.py`

- [ ] **Step 1: Add domain import tests**

Append to `tests/test_import_boundaries.py`:

```python
def test_domain_repository_imports_are_available() -> None:
    from tg_bot_aggregator.domain.auth.repository import ApiTokenRepository
    from tg_bot_aggregator.domain.backups.repository import BackupRunRepository
    from tg_bot_aggregator.domain.batches.repository import SendBatchRepository
    from tg_bot_aggregator.domain.bots.repository import BotRepository
    from tg_bot_aggregator.domain.destinations.repository import DestinationRepository
    from tg_bot_aggregator.domain.mcp.repository import McpSettingsRepository
    from tg_bot_aggregator.domain.operations.repository import RuntimeSettingsRepository
    from tg_bot_aggregator.domain.sending.repository import SendHistoryRepository
    from tg_bot_aggregator.domain.templates.repository import TemplateRepository

    assert ApiTokenRepository
    assert BackupRunRepository
    assert SendBatchRepository
    assert BotRepository
    assert DestinationRepository
    assert McpSettingsRepository
    assert RuntimeSettingsRepository
    assert SendHistoryRepository
    assert TemplateRepository
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
uv run pytest tests/test_import_boundaries.py::test_domain_repository_imports_are_available -q
```

Expected: missing package/module import errors.

- [ ] **Step 3: Create repository modules as compatibility exports**

Create exact modules:

```python
# src/tg_bot_aggregator/domain/bots/repository.py
from tg_bot_aggregator.repositories import BotRepository

__all__ = ["BotRepository"]
```

```python
# src/tg_bot_aggregator/domain/auth/repository.py
from tg_bot_aggregator.repositories import ApiTokenRepository

__all__ = ["ApiTokenRepository"]
```

```python
# src/tg_bot_aggregator/domain/mcp/repository.py
from tg_bot_aggregator.repositories import McpCoverageSnapshotRepository, McpSettingsRepository

__all__ = ["McpCoverageSnapshotRepository", "McpSettingsRepository"]
```

```python
# src/tg_bot_aggregator/domain/operations/repository.py
from tg_bot_aggregator.repositories import RuntimeAdvancedSettingsRepository, RuntimeSettingsRepository

__all__ = ["RuntimeAdvancedSettingsRepository", "RuntimeSettingsRepository"]
```

```python
# src/tg_bot_aggregator/domain/backups/repository.py
from tg_bot_aggregator.repositories import BackupRunRepository

__all__ = ["BackupRunRepository"]
```

```python
# src/tg_bot_aggregator/domain/destinations/repository.py
from tg_bot_aggregator.repositories import DestinationHealthRepository, DestinationRepository

__all__ = ["DestinationHealthRepository", "DestinationRepository"]
```

```python
# src/tg_bot_aggregator/domain/templates/repository.py
from tg_bot_aggregator.repositories import TemplateRepository, TemplateVersionRepository

__all__ = ["TemplateRepository", "TemplateVersionRepository"]
```

```python
# src/tg_bot_aggregator/domain/sending/repository.py
from tg_bot_aggregator.repositories import (
    SendAttemptRepository,
    SendHistoryRepository,
    SendProfileRepository,
)

__all__ = ["SendAttemptRepository", "SendHistoryRepository", "SendProfileRepository"]
```

```python
# src/tg_bot_aggregator/domain/batches/repository.py
from tg_bot_aggregator.repositories import SendBatchRepository

__all__ = ["SendBatchRepository"]
```

```python
# src/tg_bot_aggregator/domain/diagnostics/repository.py
from tg_bot_aggregator.repositories import DiagnosticSettingsRepository, DiagnosticUpdateRepository

__all__ = ["DiagnosticSettingsRepository", "DiagnosticUpdateRepository"]
```

```python
# src/tg_bot_aggregator/domain/discovery/repository.py
from tg_bot_aggregator.repositories import BotDiscoveryEventRepository, BotDiscoverySettingsRepository

__all__ = ["BotDiscoveryEventRepository", "BotDiscoverySettingsRepository"]
```

```python
# src/tg_bot_aggregator/domain/ops/repository.py
from tg_bot_aggregator.repositories import (
    OpsActionRunRepository,
    OpsAutomationRuleRepository,
    OpsFactRepository,
    OpsRecommendationRepository,
)

__all__ = [
    "OpsActionRunRepository",
    "OpsAutomationRuleRepository",
    "OpsFactRepository",
    "OpsRecommendationRepository",
]
```

```python
# src/tg_bot_aggregator/domain/analytics/repository.py
from tg_bot_aggregator.repositories import AnalyticsRepository, MtprotoSessionRepository

__all__ = ["AnalyticsRepository", "MtprotoSessionRepository"]
```

- [ ] **Step 4: Create models/schema export modules**

For each domain package, add `models.py` and `schemas.py` exporting the matching classes from root `models.py` and `schemas.py`. Example:

```python
# src/tg_bot_aggregator/domain/bots/models.py
from tg_bot_aggregator.models import Bot

__all__ = ["Bot"]
```

```python
# src/tg_bot_aggregator/domain/bots/schemas.py
from tg_bot_aggregator.schemas import BotCreate, BotRead, BotUpdate

__all__ = ["BotCreate", "BotRead", "BotUpdate"]
```

Do the same for each domain using the class lists from `rg '^class ' src/tg_bot_aggregator/models.py` and `rg '^class ' src/tg_bot_aggregator/schemas.py`.

- [ ] **Step 5: Run validation**

Run:

```bash
uv run pytest tests/test_import_boundaries.py -q
uv run pytest -q
uv run ruff check .
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/tg_bot_aggregator/domain tests/test_import_boundaries.py
git commit -m "refactor: add domain package repository exports"
```

## Task 4: Add Small Unit of Work

**Files:**
- Create: `src/tg_bot_aggregator/infra/uow.py`
- Create: `tests/test_unit_of_work.py`

- [ ] **Step 1: Add UnitOfWork tests**

Create `tests/test_unit_of_work.py`:

```python
import pytest

from tg_bot_aggregator.infra.uow import UnitOfWork


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_unit_of_work_commits_and_closes_on_success() -> None:
    session = FakeSession()

    async with UnitOfWork(lambda: session) as uow:
        assert uow.session is session
        assert uow.bots
        assert uow.tokens
        assert uow.destinations
        assert uow.templates
        assert uow.sending
        assert uow.attempts
        assert uow.batches
        assert uow.backups
        assert uow.ops
        assert uow.audit

    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True


@pytest.mark.asyncio
async def test_unit_of_work_rolls_back_and_closes_on_error() -> None:
    session = FakeSession()

    with pytest.raises(RuntimeError):
        async with UnitOfWork(lambda: session):
            raise RuntimeError("boom")

    assert session.committed is False
    assert session.rolled_back is True
    assert session.closed is True
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
uv run pytest tests/test_unit_of_work.py -q
```

Expected: `ModuleNotFoundError` for `tg_bot_aggregator.infra.uow`.

- [ ] **Step 3: Implement `UnitOfWork`**

Create `src/tg_bot_aggregator/infra/uow.py`:

```python
from collections.abc import Callable
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.domain.auth.repository import ApiTokenRepository
from tg_bot_aggregator.domain.backups.repository import BackupRunRepository
from tg_bot_aggregator.domain.batches.repository import SendBatchRepository
from tg_bot_aggregator.domain.bots.repository import BotRepository
from tg_bot_aggregator.domain.destinations.repository import DestinationRepository
from tg_bot_aggregator.domain.ops.repository import OpsRecommendationRepository
from tg_bot_aggregator.domain.sending.repository import SendAttemptRepository, SendHistoryRepository
from tg_bot_aggregator.domain.templates.repository import TemplateRepository
from tg_bot_aggregator.infra.audit import AuditRepository


class UnitOfWork:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self.session_factory = session_factory

    async def __aenter__(self) -> "UnitOfWork":
        self.session = self.session_factory()
        self.bots = BotRepository(self.session)
        self.tokens = ApiTokenRepository(self.session)
        self.destinations = DestinationRepository(self.session)
        self.templates = TemplateRepository(self.session)
        self.sending = SendHistoryRepository(self.session)
        self.attempts = SendAttemptRepository(self.session)
        self.batches = SendBatchRepository(self.session)
        self.backups = BackupRunRepository(self.session)
        self.ops = OpsRecommendationRepository(self.session)
        self.audit = AuditRepository(self.session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            await self.session.commit()
        else:
            await self.session.rollback()
        await self.session.close()
```

Create `src/tg_bot_aggregator/infra/audit.py` as a compatibility export if it does not already exist:

```python
from tg_bot_aggregator.repositories import AuditRepository

__all__ = ["AuditRepository"]
```

- [ ] **Step 4: Run validation**

Run:

```bash
uv run pytest tests/test_unit_of_work.py -q
uv run pytest -q
uv run ruff check .
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/tg_bot_aggregator/infra tests/test_unit_of_work.py
git commit -m "refactor: add repository unit of work"
```

## Task 5: Version API Router Without Moving Behavior

**Files:**
- Create: `src/tg_bot_aggregator/api/router.py`
- Create: `src/tg_bot_aggregator/api/deps.py`
- Create: `src/tg_bot_aggregator/api/v1/__init__.py`
- Create: `src/tg_bot_aggregator/api/v1/*.py`
- Modify: `src/tg_bot_aggregator/main.py`
- Test: `tests/test_api_router_layout.py`

- [ ] **Step 1: Add route layout test**

Create `tests/test_api_router_layout.py`:

```python
from fastapi import APIRouter

from tg_bot_aggregator.api.router import api_router


def test_api_router_is_fastapi_router() -> None:
    assert isinstance(api_router, APIRouter)


def test_api_router_contains_v1_paths() -> None:
    paths = {route.path for route in api_router.routes}

    assert "/api/v1/health" in paths
    assert "/api/v1/bots" in paths
    assert "/api/v1/destinations" in paths
    assert "/api/v1/send/text" in paths
    assert "/api/v1/mcp/settings" in paths
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
uv run pytest tests/test_api_router_layout.py -q
```

Expected: import error for `tg_bot_aggregator.api.router`.

- [ ] **Step 3: Add `api/deps.py` compatibility module**

Create:

```python
from tg_bot_aggregator.api.dependencies import *  # noqa: F403
```

- [ ] **Step 4: Create `api/v1` route modules**

Use compatibility exports first. Example:

```python
# src/tg_bot_aggregator/api/v1/bots.py
from tg_bot_aggregator.api.bots import router

__all__ = ["router"]
```

Repeat for:

- `analytics.py`
- `audit.py`
- `auth.py`
- `backups.py` exporting `router` from `api.operations` until backups are split out.
- `bots.py`
- `destinations.py`
- `diagnostics.py`
- `discovery.py`
- `health.py`
- `mcp.py` exporting `router` from `api.mcp_settings`.
- `media.py`
- `mtproto.py`
- `operations.py`
- `ops.py`
- `reliability.py`
- `send_batches.py`
- `sending.py` exporting `router` from `api.send`.
- `send_profiles.py`
- `templates.py`
- `telegram_compat.py`

- [ ] **Step 5: Create `api/router.py`**

Move the router include logic from `main.py` into `api/router.py`:

```python
from fastapi import APIRouter

from tg_bot_aggregator.api.v1 import (
    analytics,
    audit,
    auth,
    bots,
    destinations,
    diagnostics,
    discovery,
    health,
    mcp,
    media,
    mtproto,
    operations,
    ops,
    reliability,
    send_batches,
    send_profiles,
    sending,
    telegram_compat,
    templates,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(bots.router)
api_router.include_router(destinations.router)
api_router.include_router(templates.router)
api_router.include_router(send_profiles.router)
api_router.include_router(sending.router)
api_router.include_router(send_batches.router)
api_router.include_router(reliability.router)
api_router.include_router(telegram_compat.router)
api_router.include_router(media.router)
api_router.include_router(diagnostics.router)
api_router.include_router(discovery.router)
api_router.include_router(operations.router)
api_router.include_router(ops.router)
api_router.include_router(audit.router)
api_router.include_router(mcp.router)
api_router.include_router(mtproto.router)
api_router.include_router(analytics.router)
```

- [ ] **Step 6: Update `main.py`**

Replace individual API router imports and include calls with:

```python
from tg_bot_aggregator.api.router import api_router
```

and:

```python
app.include_router(api_router)
```

- [ ] **Step 7: Run validation**

Run:

```bash
uv run pytest tests/test_api_router_layout.py -q
uv run pytest -q
uv run ruff check .
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/tg_bot_aggregator/api tests/test_api_router_layout.py
git commit -m "refactor: add versioned api router"
```

## Task 6: Move Service Facades by Domain

**Files:**
- Create/modify domain service modules:
  - `domain/bots/service.py`
  - `domain/auth/service.py`
  - `domain/auth/middleware.py`
  - `domain/destinations/service.py`
  - `domain/templates/renderer.py`
  - `domain/templates/service.py`
  - `domain/sending/service.py`
  - `domain/sending/policy.py`
  - `domain/sending/idempotency.py`
  - `domain/sending/telegram_facade.py`
  - `domain/batches/service.py`
  - `domain/reliability/service.py`
  - `domain/reliability/leases.py`
  - `domain/reliability/buckets.py`
  - `domain/operations/service.py`
  - `domain/backups/service.py`
  - `domain/backups/diff.py`
  - `domain/backups/git_provider.py`
  - `domain/backups/redaction.py`
  - `domain/analytics/service.py`
  - `domain/analytics/mtproto.py`
  - `domain/media/browser.py`
  - `domain/media/paths.py`
  - `domain/mcp/server.py`
  - `domain/mcp/catalog.py`
  - `domain/mcp/tools.py`
  - `domain/ops/service.py`
- Modify root compatibility modules as wrappers.
- Test: extend `tests/test_import_boundaries.py`.

- [ ] **Step 1: Add service import tests**

Append:

```python
def test_domain_service_imports_are_available() -> None:
    from tg_bot_aggregator.domain.analytics.service import AnalyticsService
    from tg_bot_aggregator.domain.analytics.mtproto import MtprotoService
    from tg_bot_aggregator.domain.backups.service import BackupService
    from tg_bot_aggregator.domain.batches.service import WorkflowService
    from tg_bot_aggregator.domain.media.browser import MediaBrowser
    from tg_bot_aggregator.domain.media.paths import validate_shared_file
    from tg_bot_aggregator.domain.mcp.catalog import MCP_TOOL_DEFINITIONS
    from tg_bot_aggregator.domain.mcp.server import create_mcp_server
    from tg_bot_aggregator.domain.operations.service import OperationsService
    from tg_bot_aggregator.domain.sending.service import SendService
    from tg_bot_aggregator.domain.templates.renderer import validate_template_text

    assert AnalyticsService
    assert MtprotoService
    assert BackupService
    assert WorkflowService
    assert MediaBrowser
    assert validate_shared_file
    assert MCP_TOOL_DEFINITIONS
    assert create_mcp_server
    assert OperationsService
    assert SendService
    assert validate_template_text
```

- [ ] **Step 2: Move modules one domain at a time**

Use `git mv` for direct ownership moves and keep root wrappers:

```bash
git mv src/tg_bot_aggregator/send_service.py src/tg_bot_aggregator/domain/sending/service.py
git mv src/tg_bot_aggregator/workflow_service.py src/tg_bot_aggregator/domain/batches/service.py
git mv src/tg_bot_aggregator/reliability.py src/tg_bot_aggregator/domain/reliability/service.py
git mv src/tg_bot_aggregator/template_renderer.py src/tg_bot_aggregator/domain/templates/renderer.py
git mv src/tg_bot_aggregator/operations_service.py src/tg_bot_aggregator/domain/operations/service.py
git mv src/tg_bot_aggregator/backup_service.py src/tg_bot_aggregator/domain/backups/service.py
git mv src/tg_bot_aggregator/analytics_service.py src/tg_bot_aggregator/domain/analytics/service.py
git mv src/tg_bot_aggregator/mtproto_service.py src/tg_bot_aggregator/domain/analytics/mtproto.py
git mv src/tg_bot_aggregator/media_browser.py src/tg_bot_aggregator/domain/media/browser.py
git mv src/tg_bot_aggregator/shared_paths.py src/tg_bot_aggregator/domain/media/paths.py
git mv src/tg_bot_aggregator/mcp_catalog.py src/tg_bot_aggregator/domain/mcp/catalog.py
git mv src/tg_bot_aggregator/mcp_server.py src/tg_bot_aggregator/domain/mcp/server.py
git mv src/tg_bot_aggregator/telegram_ops.py src/tg_bot_aggregator/domain/ops/service.py
git mv src/tg_bot_aggregator/api_tokens.py src/tg_bot_aggregator/domain/auth/service.py
git mv src/tg_bot_aggregator/auth_middleware.py src/tg_bot_aggregator/domain/auth/middleware.py
```

Create root wrappers with `from new.module import *  # noqa: F403`.

- [ ] **Step 3: Fix moved-module imports**

Use `rg 'tg_bot_aggregator\\.(send_service|workflow_service|reliability|template_renderer|operations_service|backup_service|analytics_service|mtproto_service|media_browser|shared_paths|mcp_catalog|mcp_server|telegram_ops|api_tokens|auth_middleware)' src tests` to update imports gradually to domain paths in runtime code. Leave tests on root wrappers until the full test suite passes, then migrate test imports opportunistically.

- [ ] **Step 4: Run validation after each moved domain**

After each `git mv` group:

```bash
uv run pytest -q
uv run ruff check .
```

Expected: all pass before moving the next group.

- [ ] **Step 5: Commit**

```bash
git add src/tg_bot_aggregator tests/test_import_boundaries.py
git commit -m "refactor: move service facades into domain packages"
```

## Task 7: Update Runtime Entrypoints to New Boundaries

**Files:**
- Modify: `src/tg_bot_aggregator/main.py`
- Modify: `src/tg_bot_aggregator/tasks.py`
- Modify: `src/tg_bot_aggregator/scheduler.py`
- Modify: `src/tg_bot_aggregator/diagnostics/bot.py`
- Modify: `src/tg_bot_aggregator/discovery/bot.py`
- Modify: `alembic/env.py`

- [ ] **Step 1: Update imports in runtime entrypoints**

Change runtime code to import from:

- `core.config`
- `core.db`
- `core.security`
- `infra.events`
- `infra.telegram_client`
- `domain.*.service`
- `domain.*.repository`

Keep Alembic importing `tg_bot_aggregator.models.Base` until ORM models are physically split.

- [ ] **Step 2: Run import and app factory tests**

Run:

```bash
uv run pytest tests/test_api_basic.py tests/test_tasks.py tests/test_diagnostics_bot.py tests/test_discovery_bot.py -q
uv run ruff check .
```

Expected: all pass.

- [ ] **Step 3: Run full validation**

Run:

```bash
uv run pytest -q
uv run ruff check .
git diff --check
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add src/tg_bot_aggregator alembic tests
git commit -m "refactor: use new package boundaries in runtime code"
```

## Task 8: Final Deploy Verification and Mirror Push

**Files:**
- No source changes unless CI reveals a defect.

- [ ] **Step 1: Push to Gitea main**

```bash
git push origin main
```

- [ ] **Step 2: Watch Gitea CI**

Use the Gitea API to verify the latest run for branch `main` succeeds.

Expected:

- test job succeeds.
- deploy job succeeds.
- app health succeeds.
- nginx direct host-header checks succeed.
- GitHub mirror push step succeeds.

- [ ] **Step 3: Verify GitHub mirror**

Run:

```bash
git ls-remote github refs/heads/main
```

Expected: GitHub `main` points to the same commit as local `HEAD`.

- [ ] **Step 4: Verify deployed app**

Run:

```bash
curl -fsS http://192.168.1.169:8000/api/v1/health
curl -fsS http://192.168.1.169:8000/api/v1/mcp/settings
curl -fsS http://192.168.1.169:8000/api/v1/reliability/summary
curl -fsSI -H "Host: tg.sh-inc.ru" http://192.168.1.7/ | grep -q "200"
curl -fsSI -H "Host: tg.sh-inc.dev" http://192.168.1.7/ | grep -q "200"
```

Expected: direct app endpoints succeed, nginx host-header UI checks return 200.

## Deferred Cleanup

Do not do these in the first implementation unless all previous tasks are green:

- Physically split ORM class definitions out of root `models.py`.
- Physically split every Pydantic schema out of root `schemas.py`.
- Delete root compatibility wrappers.
- Replace all test imports with domain imports.
- Remove `Base.metadata.create_all` from app lifespan. That needs a separate migration/testing decision because tests currently rely on `Base.metadata.create_all`.

## Self-Review

- Spec coverage: requested package layout, repository mapping, small UnitOfWork, CI deploy cleanup, nginx-ui CT id handling, migrations awareness, smoke tests, GitHub mirror push, and GitHub CI are covered.
- Placeholder scan: no task depends on `TODO`, `TBD`, or undefined future behavior. Deferred cleanup is explicitly out of the first safe implementation slice.
- Type consistency: `UnitOfWork` exposes only repositories and transaction lifecycle. It does not contain Telegram calls, retry logic, or business orchestration.
- Risk note: GitHub mirror push from Gitea CI depends on the runner having SSH credentials accepted by `git@github.com:Mesteriis/tg-bots.git`. If that key is not present, the deploy can succeed and the final mirror step can fail; the failure is visible in CI.
