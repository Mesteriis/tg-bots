# RNet Proxmox Deploy And OSS Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add RNet/Gitea deployment automation, nginx-ui proxy automation, and OSS repository metadata.

**Current status:** Local repository preparation is implemented and verified. External operator actions are intentionally still pending: commit, push, RNet/PVE deploy, nginx-ui update, and post-deploy health check.

**Architecture:** Keep deployment as plain shell scripts plus a Gitea workflow. Keep runtime app unchanged; deployment scripts configure infra and compose services around the existing Docker image.

**Tech Stack:** Gitea Actions, RNet `pve-deploy`, Proxmox LXC, Docker Compose, nginx-ui LXC, pytest, ruff.

---

### Task 1: Repository Tests For Deploy And OSS Shape

**Files:**
- Create: `tests/test_repository_metadata.py`

- [x] Add tests that assert OSS files exist.
- [x] Add tests that assert the Gitea workflow uses `runs-on: python`, `pve-deploy ensure`, `pve-deploy deploy`, and nginx update script.
- [x] Add tests that assert deploy scripts are present and do not contain hardcoded Telegram secrets.

### Task 2: RNet/Gitea Workflow

**Files:**
- Create: `.gitea/workflows/ci-deploy.yml`
- Create: `deploy/docker-compose.lxc.yml`
- Create: `deploy/proxmox/configure-lxc.sh`
- Create: `deploy/proxmox/ct-ip.sh`
- Create: `deploy/nginx/update-nginx-ui.sh`
- Create: `docs/deployment/rnet-proxmox.md`

- [x] Add CI job using `uv sync --extra dev`, ruff, pytest.
- [x] Add deploy job using CTID `103`, CT name `tg-bots`, and RNet `pve-deploy`.
- [x] Add idempotent LXC configuration script for media mount and Docker.
- [x] Add nginx-ui update script for `tg.sh-inc.ru` and `tg.sh-inc.dev`.
- [x] Document required Gitea secrets.

### Task 3: OSS Metadata

**Files:**
- Create: `LICENSE`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `CODE_OF_CONDUCT.md`
- Create: `CHANGELOG.md`
- Create: `.gitea/ISSUE_TEMPLATE/bug_report.md`
- Create: `.gitea/ISSUE_TEMPLATE/feature_request.md`
- Modify: `pyproject.toml`
- Modify: `README.md`

- [x] Add MIT license and concise community docs.
- [x] Add project metadata, license, classifiers, and URLs.
- [x] Update README with OSS and deployment sections.

### Task 4: Verify, Commit, Push, Deploy

- [x] Run `PYTHONPATH=src python3.11 -m pytest`.
- [x] Run `PYTHONPATH=src python3.11 -m ruff check .`.
- [x] Run `bash -n` for deploy scripts.
- [ ] Commit and merge to `main`.
- [ ] Push to `origin main`.
- [ ] Deploy through RNet/pve-deploy or equivalent manual invocation from CI runner.
- [ ] Update nginx-ui and verify health.
