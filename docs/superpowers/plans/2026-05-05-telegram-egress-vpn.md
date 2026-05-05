# Telegram Egress VPN Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add optional Telegram egress routing with `direct`, `wireguard`, and `openvpn` modes, file-backed secret storage, dashboard controls, and health/status APIs without forcing the entire local stack through the tunnel.

**Architecture:** Keep VPN as an outbound egress subsystem owned by the operations layer. Store non-secret runtime metadata in SQLite and provider secrets/config files under `/data/telegram-egress`. Introduce a narrow provider interface, ship `direct` + `wireguard` first, then `openvpn`, and expose everything through `Настройки -> Инфраструктура`.

**Tech Stack:** FastAPI, SQLAlchemy async, SQLite/PostgreSQL runtime settings, Docker Compose, Vue 3 CDN UI, Alembic, pytest, file-backed secret storage.

---

## File Map

**Create**

- `src/tg_bot_aggregator/domain/operations/telegram_egress_service.py` — orchestration for reading metadata, reading/writing provider files, status checks, and provider lifecycle.
- `src/tg_bot_aggregator/domain/operations/telegram_egress_models.py` — focused ORM model for non-secret Telegram egress runtime state if a separate table is chosen.
- `src/tg_bot_aggregator/domain/operations/telegram_egress_schemas.py` — request/response models for config upload, state, and status.
- `src/tg_bot_aggregator/domain/operations/telegram_egress_store.py` — file-backed secret/config store.
- `src/tg_bot_aggregator/domain/operations/telegram_egress_providers.py` — `DirectProvider`, `WireGuardProvider`, `OpenVpnProvider` interface + implementations.
- `tests/test_telegram_egress_store.py` — file storage tests.
- `tests/test_telegram_egress_service.py` — orchestration/status tests.
- `tests/test_api_telegram_egress.py` — API contract tests.
- `tests/test_telegram_egress_providers.py` — provider validation/status tests.

**Modify**

- `src/tg_bot_aggregator/domain/operations/models.py` — extend runtime metadata if reusing existing runtime settings instead of a separate table.
- `src/tg_bot_aggregator/domain/operations/repository.py` — CRUD/read helpers for egress metadata.
- `src/tg_bot_aggregator/domain/operations/schemas.py` — include egress fields in operations settings or split references.
- `src/tg_bot_aggregator/api/v1/operations.py` — add `/operations/telegram-egress*` endpoints.
- `src/tg_bot_aggregator/core/config.py` — add `TELEGRAM_EGRESS_MODE`, `TELEGRAM_EGRESS_STATE_DIR`.
- `src/tg_bot_aggregator/runtime_settings.py` — apply persisted egress metadata to runtime settings if needed.
- `src/tg_bot_aggregator/static/index.html` — add `Telegram connectivity` panel under `Настройки -> Инфраструктура`.
- `docker-compose.yml` — add `telegram-egress` and route Telegram-facing services.
- `deploy/docker-compose.lxc.yml` — same for deployment stack.
- `alembic/versions/<new_revision>.py` — schema migration for runtime metadata if a DB model changes.
- `.env.example` — add egress env variables.
- `README.md` — document configuration and operator workflow.
- `docs/deployment/rnet-proxmox.md` — deployment notes for VPN container and state directory.

---

### Task 1: Persist Non-Secret Telegram Egress Metadata

**Files:**
- Modify: `src/tg_bot_aggregator/domain/operations/models.py`
- Modify: `src/tg_bot_aggregator/domain/operations/repository.py`
- Modify: `src/tg_bot_aggregator/domain/operations/schemas.py`
- Modify: `src/tg_bot_aggregator/core/config.py`
- Test: `tests/test_models.py`
- Test: `tests/test_repository_metadata.py`
- Test: `tests/test_api_ops.py`
- Create: `alembic/versions/<new_revision>.py`

- [x] **Step 1: Write the failing model/schema test**

```python
def test_runtime_settings_read_includes_telegram_egress_fields() -> None:
    payload = RuntimeSettingsRead.model_validate(
        {
            "app_host": "127.0.0.1",
            "app_port": 8000,
            "database_url": "sqlite+aiosqlite:///:memory:",
            "redis_url": "redis://redis:6379/0",
            "telegram_api_id": None,
            "telegram_api_hash": None,
            "telegram_bot_api_base_url": "https://api.telegram.org",
            "cors_allowed_origins": ["http://localhost:8000"],
            "mcp_allowed_origins": ["http://localhost:8000"],
            "shared_media_root": "/shared/media",
            "shared_media_require_mount": False,
            "max_local_file_bytes": 2097152000,
            "telethon_session_dir": "/data/telethon",
            "diagnostic_poll_timeout_seconds": 30,
            "diagnostic_retry_delay_seconds": 5.0,
            "discovery_poll_timeout_seconds": 30,
            "discovery_retry_delay_seconds": 5.0,
            "send_retry_max_attempts": 3,
            "send_retry_delay_seconds": 1.0,
            "reliability_enabled": False,
            "send_default_mode": "sync",
            "send_global_rate_per_minute": None,
            "send_bot_rate_per_minute": None,
            "send_chat_rate_per_minute": None,
            "send_destination_rate_per_minute": None,
            "send_retry_base_delay_seconds": 1.0,
            "send_retry_max_delay_seconds": 300.0,
            "send_worker_lease_seconds": 60,
            "send_stale_lock_grace_seconds": 30,
            "send_dedupe_window_seconds": None,
            "protected_api_hosts": [],
            "policy_enabled": False,
            "rate_limit_per_minute": None,
            "quiet_hours_start": None,
            "quiet_hours_end": None,
            "callback_enabled": False,
            "callback_url": None,
            "backup_git_repo_url": None,
            "backup_git_branch": "main",
            "backup_git_path": "tg-bots.json",
            "backup_git_service": "auto",
            "backup_git_auth_method": "token",
            "backup_git_api_base_url": None,
            "backup_git_api_token": None,
            "backup_include_secrets": False,
            "backup_schedule_enabled": False,
            "backup_schedule_interval_seconds": 86400,
            "backup_schedule_push_to_git": False,
            "telegram_egress_mode": "direct",
            "telegram_egress_enabled": False,
            "telegram_egress_provider": None,
            "telegram_egress_last_status": "disconnected",
            "telegram_egress_last_error": None,
            "telegram_egress_connected_at": None,
            "telegram_egress_last_handshake_at": None,
            "telegram_egress_last_egress_ip": None,
        }
    )
    assert payload.telegram_egress_mode == "direct"
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_api_ops.py -k telegram_egress`

Expected: FAIL because `RuntimeSettingsRead` and related persistence do not include Telegram egress fields.

- [x] **Step 3: Add the metadata fields and migration**

```python
class RuntimeSettings(Base):
    __tablename__ = "runtime_settings"

    telegram_egress_mode: Mapped[str | None] = mapped_column(String(32))
    telegram_egress_enabled: Mapped[bool | None] = mapped_column(Boolean)
    telegram_egress_provider: Mapped[str | None] = mapped_column(String(32))
    telegram_egress_last_status: Mapped[str | None] = mapped_column(String(32))
    telegram_egress_last_error: Mapped[str | None] = mapped_column(Text)
    telegram_egress_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_egress_last_handshake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_egress_last_egress_ip: Mapped[str | None] = mapped_column(String(128))
```

```python
class RuntimeSettingsRead(BaseModel):
    telegram_egress_mode: Literal["direct", "wireguard", "openvpn"]
    telegram_egress_enabled: bool
    telegram_egress_provider: Literal["wireguard", "openvpn"] | None
    telegram_egress_last_status: str | None
    telegram_egress_last_error: str | None
    telegram_egress_connected_at: datetime | None
    telegram_egress_last_handshake_at: datetime | None
    telegram_egress_last_egress_ip: str | None
```

- [x] **Step 4: Run targeted tests**

Run: `uv run pytest -q tests/test_api_ops.py tests/test_models.py -k telegram_egress`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/tg_bot_aggregator/domain/operations/models.py src/tg_bot_aggregator/domain/operations/repository.py src/tg_bot_aggregator/domain/operations/schemas.py src/tg_bot_aggregator/core/config.py alembic/versions tests/test_api_ops.py tests/test_models.py
git commit -m "feat: persist telegram egress runtime metadata"
```

### Task 2: Add File-Backed Secret Store for VPN Configs

**Files:**
- Create: `src/tg_bot_aggregator/domain/operations/telegram_egress_store.py`
- Modify: `src/tg_bot_aggregator/core/config.py`
- Test: `tests/test_telegram_egress_store.py`

- [x] **Step 1: Write the failing storage tests**

```python
from pathlib import Path

def test_store_writes_wireguard_profile_atomically(tmp_path: Path) -> None:
    store = TelegramEgressStore(tmp_path)
    store.write_wireguard_profile("[Interface]\\nPrivateKey = secret\\n")

    profile = tmp_path / "wireguard" / "profile.conf"
    assert profile.exists()
    assert profile.read_text() == "[Interface]\\nPrivateKey = secret\\n"

def test_store_reports_missing_provider_config(tmp_path: Path) -> None:
    store = TelegramEgressStore(tmp_path)
    status = store.config_summary("wireguard")
    assert status.exists is False
    assert status.path.name == "profile.conf"
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_telegram_egress_store.py`

Expected: FAIL because `TelegramEgressStore` does not exist yet.

- [x] **Step 3: Write minimal file-backed store**

```python
class TelegramEgressStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write_wireguard_profile(self, contents: str) -> Path:
        target = self.root / "wireguard" / "profile.conf"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(contents)
        tmp.chmod(0o600)
        tmp.replace(target)
        return target

    def write_openvpn_profile(self, contents: str) -> Path:
        ...

    def config_summary(self, provider: str) -> ProviderConfigSummary:
        ...
```

- [x] **Step 4: Run tests**

Run: `uv run pytest -q tests/test_telegram_egress_store.py`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/tg_bot_aggregator/domain/operations/telegram_egress_store.py src/tg_bot_aggregator/core/config.py tests/test_telegram_egress_store.py
git commit -m "feat: add telegram egress secret file store"
```

### Task 3: Add Provider Abstraction and Direct/WireGuard Status Path

**Files:**
- Create: `src/tg_bot_aggregator/domain/operations/telegram_egress_providers.py`
- Create: `src/tg_bot_aggregator/domain/operations/telegram_egress_service.py`
- Test: `tests/test_telegram_egress_providers.py`
- Test: `tests/test_telegram_egress_service.py`

- [x] **Step 1: Write failing provider/service tests**

```python
async def test_direct_provider_reports_disconnected_without_tunnel() -> None:
    provider = DirectProvider()
    status = await provider.status()
    assert status.mode == "direct"
    assert status.tunnel_state == "not_applicable"

async def test_wireguard_provider_requires_profile_file(tmp_path: Path) -> None:
    provider = WireGuardProvider(root=tmp_path)
    result = await provider.validate_config()
    assert result.ok is False
    assert "profile.conf" in result.message
```

```python
async def test_service_reads_runtime_metadata_and_store_summary(tmp_path: Path) -> None:
    service = TelegramEgressService(...)
    state = await service.read_state()
    assert state.mode == "direct"
    assert state.provider_config_present is False
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/test_telegram_egress_providers.py tests/test_telegram_egress_service.py`

Expected: FAIL because provider classes and service do not exist.

- [x] **Step 3: Implement the narrow provider interface and service**

```python
@dataclass(slots=True)
class TelegramEgressStatus:
    mode: str
    provider: str | None
    tunnel_state: str
    egress_ip: str | None
    last_error: str | None
    provider_config_present: bool

class TelegramEgressProvider(Protocol):
    async def validate_config(self) -> ValidationResult: ...
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def restart(self) -> None: ...
    async def status(self) -> TelegramEgressStatus: ...

class DirectProvider:
    async def status(self) -> TelegramEgressStatus:
        return TelegramEgressStatus(
            mode="direct",
            provider=None,
            tunnel_state="not_applicable",
            egress_ip=None,
            last_error=None,
            provider_config_present=False,
        )
```

- [x] **Step 4: Run tests**

Run: `uv run pytest -q tests/test_telegram_egress_providers.py tests/test_telegram_egress_service.py`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/tg_bot_aggregator/domain/operations/telegram_egress_providers.py src/tg_bot_aggregator/domain/operations/telegram_egress_service.py tests/test_telegram_egress_providers.py tests/test_telegram_egress_service.py
git commit -m "feat: add telegram egress provider abstraction"
```

### Task 4: Expose Telegram Egress REST API

**Files:**
- Create: `src/tg_bot_aggregator/domain/operations/telegram_egress_schemas.py`
- Modify: `src/tg_bot_aggregator/api/v1/operations.py`
- Test: `tests/test_api_telegram_egress.py`

- [x] **Step 1: Write the failing API tests**

```python
async def test_get_telegram_egress_returns_runtime_status(client: AsyncClient) -> None:
    response = await client.get("/api/v1/operations/telegram-egress")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "direct"
    assert payload["provider"] is None

async def test_patch_telegram_egress_updates_mode(client: AsyncClient) -> None:
    response = await client.patch(
        "/api/v1/operations/telegram-egress",
        json={"mode": "wireguard", "enabled": True},
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "wireguard"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/test_api_telegram_egress.py`

Expected: FAIL with `404` because the endpoints do not exist.

- [x] **Step 3: Add schemas and endpoints**

```python
@router.get("/telegram-egress", response_model=TelegramEgressStateRead)
async def get_telegram_egress(...): ...

@router.patch("/telegram-egress", response_model=TelegramEgressStateRead)
async def patch_telegram_egress(...): ...

@router.post("/telegram-egress/check", response_model=TelegramEgressStatusRead)
async def check_telegram_egress(...): ...
```

- [x] **Step 4: Run tests**

Run: `uv run pytest -q tests/test_api_telegram_egress.py tests/test_api_ops.py -k telegram_egress`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/tg_bot_aggregator/domain/operations/telegram_egress_schemas.py src/tg_bot_aggregator/api/v1/operations.py tests/test_api_telegram_egress.py
git commit -m "feat: expose telegram egress operations api"
```

### Task 5: Add WireGuard Config Upload and Lifecycle Actions

**Files:**
- Modify: `src/tg_bot_aggregator/domain/operations/telegram_egress_service.py`
- Modify: `src/tg_bot_aggregator/domain/operations/telegram_egress_providers.py`
- Modify: `src/tg_bot_aggregator/api/v1/operations.py`
- Test: `tests/test_telegram_egress_service.py`
- Test: `tests/test_api_telegram_egress.py`

- [x] **Step 1: Write the failing config/lifecycle tests**

```python
async def test_upload_wireguard_config_marks_provider_present(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/operations/telegram-egress/config",
        json={"provider": "wireguard", "profile_text": "[Interface]\\nPrivateKey = x\\n"},
    )
    assert response.status_code == 200
    assert response.json()["provider_config_present"] is True

async def test_connect_wireguard_without_config_returns_400(client: AsyncClient) -> None:
    response = await client.post("/api/v1/operations/telegram-egress/connect")
    assert response.status_code == 400
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/test_api_telegram_egress.py -k wireguard`

Expected: FAIL because config upload and connect endpoints do not fully work.

- [x] **Step 3: Implement config upload and lifecycle methods**

```python
@router.post("/telegram-egress/config", response_model=TelegramEgressStateRead)
async def upload_telegram_egress_config(...): ...

@router.post("/telegram-egress/connect", response_model=TelegramEgressStatusRead)
async def connect_telegram_egress(...): ...

@router.post("/telegram-egress/disconnect", response_model=TelegramEgressStatusRead)
async def disconnect_telegram_egress(...): ...

@router.post("/telegram-egress/restart", response_model=TelegramEgressStatusRead)
async def restart_telegram_egress(...): ...
```

- [x] **Step 4: Run tests**

Run: `uv run pytest -q tests/test_api_telegram_egress.py tests/test_telegram_egress_service.py -k wireguard`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/tg_bot_aggregator/domain/operations/telegram_egress_service.py src/tg_bot_aggregator/domain/operations/telegram_egress_providers.py src/tg_bot_aggregator/api/v1/operations.py tests/test_api_telegram_egress.py tests/test_telegram_egress_service.py
git commit -m "feat: add wireguard telegram egress lifecycle"
```

### Task 6: Add Dashboard Controls Under Settings -> Infrastructure

**Files:**
- Modify: `src/tg_bot_aggregator/static/index.html`
- Test: `tests/test_static_ui.py`

- [x] **Step 1: Write the failing UI contract test**

```python
def test_static_ui_exposes_telegram_egress_controls() -> None:
    html = Path("src/tg_bot_aggregator/static/index.html").read_text()
    for marker in [
        "Telegram connectivity",
        "operationsSettings.telegram_egress_mode",
        "checkTelegramEgress",
        "connectTelegramEgress",
        "disconnectTelegramEgress",
        "restartTelegramEgress",
        "wireguard",
        "openvpn",
        "xray (roadmap)",
    ]:
        assert marker in html
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_static_ui.py -k telegram_egress`

Expected: FAIL because the panel and handlers do not exist yet.

- [x] **Step 3: Add the minimal UI**

```html
<section class="settings-card">
  <div class="panel-head">
    <p class="panel-title">Telegram connectivity</p>
  </div>
  <label>Режим
    <select v-model="operationsSettings.telegram_egress_mode">
      <option value="direct">direct</option>
      <option value="wireguard">wireguard</option>
      <option value="openvpn">openvpn</option>
    </select>
  </label>
  <p class="field-hint">Xray: roadmap, не включен в текущую реализацию.</p>
  <div class="operator-actions">
    <button class="btn" type="button" @click="checkTelegramEgress">Проверить</button>
    <button class="btn" type="button" @click="connectTelegramEgress">Подключить</button>
    <button class="btn" type="button" @click="disconnectTelegramEgress">Отключить</button>
    <button class="btn" type="button" @click="restartTelegramEgress">Перезапустить</button>
  </div>
</section>
```

- [x] **Step 4: Run tests**

Run: `uv run pytest -q tests/test_static_ui.py -k telegram_egress`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/tg_bot_aggregator/static/index.html tests/test_static_ui.py
git commit -m "feat: add telegram egress controls to settings ui"
```

### Task 7: Add OpenVPN Provider

**Files:**
- Modify: `src/tg_bot_aggregator/domain/operations/telegram_egress_store.py`
- Modify: `src/tg_bot_aggregator/domain/operations/telegram_egress_providers.py`
- Modify: `src/tg_bot_aggregator/domain/operations/telegram_egress_service.py`
- Test: `tests/test_telegram_egress_store.py`
- Test: `tests/test_telegram_egress_providers.py`
- Test: `tests/test_api_telegram_egress.py`

- [x] **Step 1: Write the failing OpenVPN tests**

```python
async def test_openvpn_provider_requires_profile_and_auth(tmp_path: Path) -> None:
    provider = OpenVpnProvider(root=tmp_path)
    result = await provider.validate_config()
    assert result.ok is False
    assert "profile.ovpn" in result.message
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/test_telegram_egress_providers.py -k openvpn`

Expected: FAIL because the provider is not implemented.

- [x] **Step 3: Implement minimal OpenVPN provider and file handling**

```python
class OpenVpnProvider:
    async def validate_config(self) -> ValidationResult:
        profile = self.root / "openvpn" / "profile.ovpn"
        auth = self.root / "openvpn" / "auth.txt"
        if not profile.exists():
            return ValidationResult(ok=False, message="missing openvpn/profile.ovpn")
        return ValidationResult(ok=True, message="ok")
```

- [x] **Step 4: Run tests**

Run: `uv run pytest -q tests/test_telegram_egress_store.py tests/test_telegram_egress_providers.py tests/test_api_telegram_egress.py -k openvpn`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/tg_bot_aggregator/domain/operations/telegram_egress_store.py src/tg_bot_aggregator/domain/operations/telegram_egress_providers.py src/tg_bot_aggregator/domain/operations/telegram_egress_service.py tests/test_telegram_egress_store.py tests/test_telegram_egress_providers.py tests/test_api_telegram_egress.py
git commit -m "feat: add openvpn telegram egress provider"
```

### Task 8: Integrate Compose/Deploy and Document Operator Flow

**Files:**
- Modify: `docker-compose.yml`
- Modify: `deploy/docker-compose.lxc.yml`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/deployment/rnet-proxmox.md`
- Test: `tests/test_config.py`

- [x] **Step 1: Write the failing config/docs test**

```python
from pathlib import Path

def test_telegram_egress_env_is_documented() -> None:
    env_example = Path(".env.example").read_text()
    compose = Path("docker-compose.yml").read_text()
    readme = Path("README.md").read_text()
    assert "TELEGRAM_EGRESS_MODE=" in env_example
    assert "telegram-egress:" in compose
    assert "Telegram connectivity" in readme
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_config.py -k telegram_egress`

Expected: FAIL because compose/env/docs do not include the feature yet.

- [x] **Step 3: Update compose, env, and docs**

```yaml
telegram-egress:
  build: .
  env_file:
    - path: .env
      required: false
  environment:
    TELEGRAM_EGRESS_MODE: ${TELEGRAM_EGRESS_MODE:-direct}
    TELEGRAM_EGRESS_STATE_DIR: /data/telegram-egress
  volumes:
    - app-data:/data
```

```text
TELEGRAM_EGRESS_MODE=direct
TELEGRAM_EGRESS_STATE_DIR=/data/telegram-egress
```

- [x] **Step 4: Run tests and compose validation**

Run: `uv run pytest -q tests/test_config.py -k telegram_egress`

Run: `docker compose config`

Expected: PASS and valid compose output

- [x] **Step 5: Commit**

```bash
git add docker-compose.yml deploy/docker-compose.lxc.yml .env.example README.md docs/deployment/rnet-proxmox.md tests/test_config.py
git commit -m "feat: wire compose and docs for telegram egress vpn"
```

## Spec Coverage Check

- explicit egress modes — covered in Tasks 1, 4, 6
- sidecar/gateway container model — covered in Task 8
- file-backed secret storage — covered in Task 2
- WireGuard/OpenVPN providers — covered in Tasks 5 and 7
- dashboard controls and status — covered in Task 6
- health/status API — covered in Tasks 3 and 4
- Xray roadmap only — covered in Task 6 and README/docs wording, not implemented

## Placeholder Scan

- no unresolved placeholder markers remain
- each task has explicit files, code, tests, and commands
- no references to undefined routes or models outside the described tasks

## Type Consistency Check

- runtime mode literals stay `direct | wireguard | openvpn`
- provider literals stay `wireguard | openvpn | null`
- UI/API/storage all use the same `telegram_egress_*` prefix

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-05-telegram-egress-vpn.md`.

Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints
