#!/usr/bin/env bash
set -euo pipefail

CT_ID="${1:?usage: ct-ip.sh <ctid>}"
PVE_HOST="${PVE_HOST:-192.168.1.2}"

ssh "root@${PVE_HOST}" "pct exec ${CT_ID} -- hostname -I | awk '{print \$1}'"
