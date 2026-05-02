# RNet Proxmox Deploy And OSS Release Spec

**Date:** 2026-05-03

**Status:** Approved by direct user request

**Goal:** Prepare the repository for Gitea/RNet CI deployment to Proxmox LXC, update nginx-ui reverse proxy automation, and make the repository OSS-ready.

## Infrastructure Facts

- Git remote: `https://git.sh-inc.ru/avm/tg-bots.git`.
- RNet/Gitea Actions docs: `http://192.168.1.13/#python`.
- CI runner: CT `127`, host/IP `ci-runner` / `192.168.1.13`.
- RNet runner labels include `python` and `main`.
- RNet deploy command: `pve-deploy ensure <ctid> <name> [mem] [cores] [disk]` and `pve-deploy deploy <ctid> <path> [compose]`.
- PVE host: `192.168.1.2`.
- nginx-ui CT: `112`, IP `192.168.1.7`.
- Existing public hosts: `tg.sh-inc.ru`, `tg.sh-inc.dev`.
- Current nginx upstream was local desktop `192.168.1.108:8000`.
- Free next CTID at design time: `103`.

## Deployment Shape

The deployment target is one Docker-enabled LXC:

- CTID: `103`
- Hostname: `tg-bots`
- Memory: `8192 MB`
- Cores: `4`
- Disk: `64 GB`

CI flow:

1. Run Python checks on the `python` runner label.
2. On `main`, create/start/update LXC through `pve-deploy ensure`.
3. Configure the LXC for Docker and OMW media mount.
4. Generate `.env` from Gitea secrets and defaults.
5. Deploy `deploy/docker-compose.lxc.yml` through `pve-deploy deploy`.
6. Resolve the LXC IP.
7. Update nginx-ui site `tg.sh-inc.ru` / `tg.sh-inc.dev` to proxy to the LXC app.
8. Run health check on `http://<ct-ip>:8000/api/v1/health`.

## LXC Configuration

The configure script must be idempotent:

- Ensure PVE host has `/mnt/omw-media` mounted from `192.168.1.23:/export/media`.
- Bind `/mnt/omw-media` into the LXC at the same path.
- Ensure Docker is installed and running in the target LXC.
- Leave existing LXC data alone.

## nginx-ui

The nginx script must:

- Resolve CT IP from PVE unless `APP_UPSTREAM` is supplied.
- Back up existing `/etc/nginx/sites-available/tg.sh-inc.ru`.
- Write both HTTP and HTTPS server blocks.
- Preserve the existing self-signed certificate path used by the current config.
- Enable the site.
- Run `nginx -t`.
- Reload nginx.

## OSS Repository Shape

Add:

- MIT `LICENSE`.
- `CONTRIBUTING.md`.
- `SECURITY.md`.
- `CODE_OF_CONDUCT.md`.
- `CHANGELOG.md`.
- Gitea issue templates.
- PyPI-style project metadata in `pyproject.toml`.
- README section for OSS status and deployment.

Secrets remain out of git.

