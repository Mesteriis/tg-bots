# RNet Proxmox Deployment

This repository deploys through the local RNet/Gitea Actions runner documented at:

```text
http://192.168.1.13/#python
```

## Target

- Gitea repository: `https://git.sh-inc.ru/avm/tg-bots.git`
- Runner labels: `python` for tests, `main` for deployment
- PVE host: `192.168.1.2`
- LXC CTID: `103`
- LXC hostname: `tg-bots`
- nginx-ui CTID: `112`
- Public hosts: `tg.sh-inc.ru`, `tg.sh-inc.dev`

## Required Gitea Secrets

```text
TELEGRAM_API_ID
TELEGRAM_API_HASH
```

The workflow writes a runtime `.env` during deployment. The file is not committed.

## Manual Deploy From CI Runner

```bash
cd /path/to/tg-bots
pve-deploy ensure 103 tg-bots 8192 4 64
bash deploy/proxmox/configure-lxc.sh 103
pve-deploy deploy 103 . deploy/docker-compose.lxc.yml
APP_IP="$(bash deploy/proxmox/ct-ip.sh 103)"
APP_UPSTREAM="http://${APP_IP}:8000" bash deploy/nginx/update-nginx-ui.sh 103
curl -fsS "http://${APP_IP}:8000/api/v1/health"
```

## Media Mount

The LXC configure script mounts the OMV media share through NFSv4:

```text
192.168.1.23:/media -> /mnt/omw-media
```

OMV `showmount -e` exposes the NFSv3 path as `/export/media`, but `/export` is the
NFSv4 pseudo-root (`fsid=0`), so NFSv4 clients must mount `/media`.

The compose file mounts it read-only into app containers as:

```text
/mnt/omw-media:/shared/media:ro
```

## Telegram Egress State

Telegram egress provider configs are file-backed and should live under:

```text
/data/telegram-egress
```

Relevant runtime env values:

```text
TELEGRAM_EGRESS_MODE=direct
TELEGRAM_EGRESS_ENABLED=false
TELEGRAM_EGRESS_PROVIDER=
TELEGRAM_EGRESS_STATE_DIR=/data/telegram-egress
TELEGRAM_EGRESS_CONTROL_URL=
```

Current deployment note:

- runtime config upload and validation are already available from the dashboard
- the default LXC compose stack keeps normal direct networking by default
- the VPN-enabled LXC stack is the separate file `deploy/docker-compose.lxc.telegram-egress.yml`
- that stack runs `telegram-egress` on Gluetun and moves the app to internal port `8001`
- in that stack the Telegram-facing containers use `http://127.0.0.1:8081` for the local Bot API and `http://127.0.0.1:8000` for the Gluetun control server

Example deploy command for the VPN-enabled stack:

```bash
pve-deploy deploy 103 . deploy/docker-compose.lxc.telegram-egress.yml
APP_IP="$(bash deploy/proxmox/ct-ip.sh 103)"
ssh "root@${APP_IP}" \
  "cd /opt/app && docker compose -f deploy/docker-compose.lxc.telegram-egress.yml up -d --build --force-recreate --remove-orphans"
curl -fsS "http://${APP_IP}:8000/api/v1/health"
```
