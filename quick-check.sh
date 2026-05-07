#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
args=()

if [[ -n "${CC_SWITCH_DB:-}" ]]; then
  args+=(--db-path "${CC_SWITCH_DB}")
fi

if [[ -n "${CODEX_DIR:-}" ]]; then
  args+=(--codex-dir "${CODEX_DIR}")
fi

python3 "${script_dir}/cc-switch-check-codex.py" "${args[@]}" "$@"
