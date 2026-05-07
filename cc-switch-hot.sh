#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cc_switch_bin="${CC_SWITCH_BIN:-cc-switch}"
sync_script="${CODEX_SYNC_SCRIPT:-${script_dir}/cc-switch-sync-codex.py}"

"${cc_switch_bin}" "$@"

if [[ "${CODEX_HOT_SWITCH_SKIP_SYNC:-0}" == "1" ]]; then
  exit 0
fi

python3 "${sync_script}"

