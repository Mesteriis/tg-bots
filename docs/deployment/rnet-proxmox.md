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

The LXC configure script mounts:

```text
192.168.1.23:/export/media -> /mnt/omw-media
```

The compose file mounts it read-only into app containers as:

```text
/mnt/omw-media:/shared/media:ro
```

