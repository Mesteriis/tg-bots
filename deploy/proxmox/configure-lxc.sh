#!/usr/bin/env bash
set -euo pipefail

CT_ID="${1:?usage: configure-lxc.sh <ctid>}"
PVE_HOST="${PVE_HOST:-192.168.1.2}"
MEDIA_EXPORT="${MEDIA_EXPORT:-192.168.1.23:/media}"
MEDIA_MOUNT="${MEDIA_MOUNT:-/mnt/omw-media}"

ssh_pve() {
  ssh "root@${PVE_HOST}" "$@"
}

echo "Configuring CT ${CT_ID} on ${PVE_HOST}"

ssh_pve "pct set ${CT_ID} --features nesting=1,keyctl=1 || pct set ${CT_ID} --features nesting=1"

ssh_pve "mkdir -p ${MEDIA_MOUNT}"
ssh_pve "if ! command -v mount.nfs >/dev/null 2>&1; then apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y nfs-common; fi"
ssh_pve "if ! mountpoint -q ${MEDIA_MOUNT}; then mount -t nfs -o vers=4 ${MEDIA_EXPORT} ${MEDIA_MOUNT}; fi"
ssh_pve "grep -qs '${MEDIA_EXPORT} ${MEDIA_MOUNT}' /etc/fstab || printf '%s %s nfs defaults,vers=4 0 0\n' '${MEDIA_EXPORT}' '${MEDIA_MOUNT}' >> /etc/fstab"

if ! ssh_pve "pct config ${CT_ID} | grep -Eq '^mp[0-9]+: ${MEDIA_MOUNT},mp=${MEDIA_MOUNT}'"; then
  ssh_pve "pct set ${CT_ID} -mp0 ${MEDIA_MOUNT},mp=${MEDIA_MOUNT},ro=1"
  ssh_pve "pct reboot ${CT_ID} || (pct stop ${CT_ID} && pct start ${CT_ID})"
fi

for _ in $(seq 1 60); do
  if APP_IP="$(ssh_pve "pct exec ${CT_ID} -- hostname -I 2>/dev/null | awk '{print \$1}'")" && [ -n "${APP_IP}" ]; then
    break
  fi
  sleep 2
done

APP_IP="${APP_IP:?container IP was not resolved}"
echo "Container IP: ${APP_IP}"

ssh "root@${APP_IP}" "if ! command -v docker >/dev/null 2>&1; then apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl && curl -fsSL https://get.docker.com | sh; fi"
ssh "root@${APP_IP}" "systemctl enable --now docker"
ssh "root@${APP_IP}" "docker compose version"
