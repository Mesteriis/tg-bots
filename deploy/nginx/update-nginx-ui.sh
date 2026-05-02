#!/usr/bin/env bash
set -euo pipefail

CT_ID="${1:-103}"
PVE_HOST="${PVE_HOST:-192.168.1.2}"
NGINX_UI_CT_ID="${NGINX_UI_CT_ID:-112}"
SERVER_NAME="${SERVER_NAME:-tg.sh-inc.ru tg.sh-inc.dev}"

if [ -z "${APP_UPSTREAM:-}" ]; then
  APP_IP="$(ssh "root@${PVE_HOST}" "pct exec ${CT_ID} -- hostname -I | awk '{print \$1}'")"
  APP_UPSTREAM="http://${APP_IP}:8000"
fi

tmp_file="$(mktemp)"
trap 'rm -f "${tmp_file}"' EXIT

cat > "${tmp_file}" <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name ${SERVER_NAME};

    client_max_body_size 0;

    location / {
        proxy_pass ${APP_UPSTREAM};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_buffering off;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }

    location ~ /.well-known/acme-challenge {
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$remote_addr:\$remote_port;
        proxy_pass http://127.0.0.1:9180;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name ${SERVER_NAME};

    ssl_certificate /etc/nginx/ssl/tg.sh-inc.ru_tg.sh-inc.dev_self/fullchain.cer;
    ssl_certificate_key /etc/nginx/ssl/tg.sh-inc.ru_tg.sh-inc.dev_self/private.key;
    client_max_body_size 0;

    location / {
        proxy_pass ${APP_UPSTREAM};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_buffering off;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }

    location ~ /.well-known/acme-challenge {
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$remote_addr:\$remote_port;
        proxy_pass http://127.0.0.1:9180;
    }
}
NGINX

scp "${tmp_file}" "root@${PVE_HOST}:/tmp/tg.sh-inc.ru"
ssh "root@${PVE_HOST}" "pct push ${NGINX_UI_CT_ID} /tmp/tg.sh-inc.ru /etc/nginx/sites-available/tg.sh-inc.ru"
ssh "root@${PVE_HOST}" "pct exec ${NGINX_UI_CT_ID} -- sh -lc 'set -e; mkdir -p /etc/nginx/ssl/tg.sh-inc.ru_tg.sh-inc.dev_self; if [ ! -s /etc/nginx/ssl/tg.sh-inc.ru_tg.sh-inc.dev_self/fullchain.cer ]; then openssl req -x509 -nodes -newkey rsa:2048 -days 3650 -subj \"/CN=tg.sh-inc.ru\" -keyout /etc/nginx/ssl/tg.sh-inc.ru_tg.sh-inc.dev_self/private.key -out /etc/nginx/ssl/tg.sh-inc.ru_tg.sh-inc.dev_self/fullchain.cer; fi; ln -sf /etc/nginx/sites-available/tg.sh-inc.ru /etc/nginx/sites-enabled/tg.sh-inc.ru; nginx -t; systemctl reload nginx'"

echo "nginx-ui now proxies ${SERVER_NAME} to ${APP_UPSTREAM}"
