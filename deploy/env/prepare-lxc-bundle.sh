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
python3 - "${TEMPLATE}" "${bundle_dir}/.env" <<'PY'
import os
import pathlib
import sys

template_path = pathlib.Path(sys.argv[1])
output_path = pathlib.Path(sys.argv[2])
content = template_path.read_text()
content = content.replace("{{TELEGRAM_API_ID}}", os.environ["TELEGRAM_API_ID"])
content = content.replace("{{TELEGRAM_API_HASH}}", os.environ["TELEGRAM_API_HASH"])
output_path.write_text(content)
PY

printf '%s\n' "${bundle_dir}"
