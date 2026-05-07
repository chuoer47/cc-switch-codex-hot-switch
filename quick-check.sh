#!/usr/bin/env bash
set -euo pipefail

db_path="${CC_SWITCH_DB:-${HOME}/.cc-switch/cc-switch.db}"
codex_dir="${CODEX_DIR:-${HOME}/.codex}"
config_path="${codex_dir}/config.toml"
auth_path="${codex_dir}/auth.json"

echo "HOME=${HOME}"
echo "CC_SWITCH_DB=${db_path}"
echo "CODEX_DIR=${codex_dir}"
echo

if [[ ! -f "${db_path}" ]]; then
  echo "Missing cc-switch DB: ${db_path}" >&2
  exit 1
fi

if [[ ! -f "${config_path}" ]]; then
  echo "Missing Codex config: ${config_path}" >&2
  exit 1
fi

if [[ ! -f "${auth_path}" ]]; then
  echo "Missing Codex auth: ${auth_path}" >&2
  exit 1
fi

echo "Codex proxy config:"
sqlite3 "${db_path}" \
  "SELECT app_type, proxy_enabled, enabled, listen_address, listen_port FROM proxy_config WHERE app_type='codex';"
echo

echo "Proxy runtime session:"
sqlite3 "${db_path}" \
  "SELECT value FROM settings WHERE key='proxy_runtime_session';"
echo

echo "Codex config head:"
sed -n '1,80p' "${config_path}"
echo

echo "Codex auth:"
python3 - "${auth_path}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
if isinstance(payload, dict):
    payload = {key: "<redacted>" for key in payload}
print(json.dumps(payload, indent=2, ensure_ascii=False))
PY
