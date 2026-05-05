#!/bin/sh
set -eu

STATE_ROOT="${TELEGRAM_EGRESS_STATE_DIR:-/data/telegram-egress}"
PROVIDER="${TELEGRAM_EGRESS_PROVIDER:-wireguard}"

mkdir -p /gluetun/wireguard /gluetun/openvpn

case "$PROVIDER" in
  wireguard)
    export VPN_SERVICE_PROVIDER=custom
    export VPN_TYPE=wireguard
    if [ -f "${STATE_ROOT}/wireguard/profile.conf" ]; then
      cp "${STATE_ROOT}/wireguard/profile.conf" /gluetun/wireguard/wg0.conf
      chmod 600 /gluetun/wireguard/wg0.conf
    fi
    ;;
  openvpn)
    export VPN_SERVICE_PROVIDER=custom
    export VPN_TYPE=openvpn
    export OPENVPN_CUSTOM_CONFIG=/gluetun/custom.conf
    if [ -f "${STATE_ROOT}/openvpn/profile.ovpn" ]; then
      cp "${STATE_ROOT}/openvpn/profile.ovpn" /gluetun/custom.conf
      chmod 600 /gluetun/custom.conf
    fi
    if [ -f "${STATE_ROOT}/openvpn/auth.txt" ]; then
      export OPENVPN_USER="$(sed -n '1p' "${STATE_ROOT}/openvpn/auth.txt")"
      export OPENVPN_PASSWORD="$(sed -n '2p' "${STATE_ROOT}/openvpn/auth.txt")"
    fi
    ;;
  *)
    echo "Unsupported TELEGRAM_EGRESS_PROVIDER: ${PROVIDER}" >&2
    exit 1
    ;;
esac

exec /gluetun-entrypoint
