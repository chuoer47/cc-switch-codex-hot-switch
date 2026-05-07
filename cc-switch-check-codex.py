#!/usr/bin/env python3

import json
import os
import re
import sqlite3
import sys
from argparse import ArgumentParser
from pathlib import Path


ASSIGNMENT_RE = re.compile(r"^([A-Za-z0-9_]+)\s*=\s*(.+?)\s*$")
SECTION_RE = re.compile(r"^\[(.+)]$")


def parse_args() -> object:
    parser = ArgumentParser(
        description="Check cc-switch Codex proxy state and Codex local config."
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=Path(os.environ.get("HOME", str(Path.home()))),
        help="Home directory containing .cc-switch and .codex. Defaults to $HOME.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        help="Path to cc-switch.db. Defaults to <home>/.cc-switch/cc-switch.db.",
    )
    parser.add_argument(
        "--codex-dir",
        type=Path,
        help="Path to Codex config directory. Defaults to <home>/.codex.",
    )
    return parser.parse_args()


def parse_simple_toml(path: Path) -> tuple[dict[str, str], set[str]]:
    top_level: dict[str, str] = {}
    sections: set[str] = set()
    current_section: str | None = None

    if not path.exists():
        return top_level, sections

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        section = SECTION_RE.match(line)
        if section:
            current_section = section.group(1).strip()
            sections.add(current_section)
            continue
        if current_section is not None:
            continue
        assignment = ASSIGNMENT_RE.match(line)
        if assignment:
            value = assignment.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
            top_level[assignment.group(1)] = value

    return top_level, sections


def load_json_file(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def status_line(level: str, message: str) -> None:
    print(f"[{level}] {message}")


def provider_auth_keys(settings_config: str) -> list[str]:
    try:
        payload = json.loads(settings_config)
    except json.JSONDecodeError:
        return []
    auth = payload.get("auth")
    if not isinstance(auth, dict):
        return []
    return sorted(str(key) for key, value in auth.items() if value)


def main() -> int:
    args = parse_args()
    home = args.home.expanduser()
    db_path = (args.db_path or home / ".cc-switch" / "cc-switch.db").expanduser()
    codex_dir = (args.codex_dir or home / ".codex").expanduser()
    config_path = codex_dir / "config.toml"
    auth_path = codex_dir / "auth.json"

    print(f"home: {home}")
    print(f"cc-switch DB: {db_path}")
    print(f"Codex dir: {codex_dir}")
    print()

    failures = 0

    if not db_path.exists():
        status_line("FAIL", f"missing cc-switch DB: {db_path}")
        return 1
    if not config_path.exists():
        status_line("FAIL", f"missing Codex config: {config_path}")
        failures += 1
    if not auth_path.exists():
        status_line("FAIL", f"missing Codex auth: {auth_path}")
        failures += 1

    conn = sqlite3.connect(db_path)
    try:
        proxy_row = conn.execute(
            """
            SELECT proxy_enabled, enabled, listen_address, listen_port
            FROM proxy_config
            WHERE app_type = 'codex'
            LIMIT 1
            """
        ).fetchone()
        provider_row = conn.execute(
            """
            SELECT id, name, settings_config
            FROM providers
            WHERE app_type = 'codex' AND is_current = 1
            ORDER BY rowid DESC
            LIMIT 1
            """
        ).fetchone()
        runtime_row = conn.execute(
            "SELECT value FROM settings WHERE key = 'proxy_runtime_session'"
        ).fetchone()
        common_row = conn.execute(
            "SELECT value FROM settings WHERE key = 'common_config_codex'"
        ).fetchone()
    finally:
        conn.close()

    if proxy_row is None:
        status_line("FAIL", "no proxy_config row for app_type='codex'")
        failures += 1
        proxy_enabled = takeover_enabled = 0
        listen_address = listen_port = None
    else:
        proxy_enabled, takeover_enabled, listen_address, listen_port = proxy_row
        if proxy_enabled:
            status_line("OK", "Codex proxy persistent switch is enabled")
        else:
            status_line("FAIL", "Codex proxy persistent switch is disabled")
            failures += 1
        if takeover_enabled:
            status_line("OK", "Codex proxy takeover is currently active")
        else:
            status_line(
                "FAIL",
                "Codex proxy takeover is not active; start the proxy process with takeover",
            )
            failures += 1
        status_line("INFO", f"configured proxy address: {listen_address}:{listen_port}")

    runtime_payload = None
    if runtime_row and runtime_row[0]:
        try:
            runtime_payload = json.loads(runtime_row[0])
        except json.JSONDecodeError:
            runtime_payload = None
    if isinstance(runtime_payload, dict):
        address = runtime_payload.get("address", listen_address)
        port = runtime_payload.get("port", listen_port)
        status_line("OK", f"proxy runtime session: {address}:{port}")
    else:
        status_line("WARN", "proxy_runtime_session is missing or invalid")

    if provider_row is None:
        status_line("FAIL", "no current Codex provider in cc-switch")
        failures += 1
    else:
        provider_id, provider_name, settings_config = provider_row
        auth_keys = provider_auth_keys(settings_config)
        status_line("OK", f"current cc-switch Codex provider: {provider_name} ({provider_id})")
        if auth_keys:
            status_line("OK", f"provider auth keys present: {', '.join(auth_keys)}")
        else:
            status_line("WARN", "current provider has no non-empty auth keys")

    if common_row and common_row[0]:
        common_lines = len(str(common_row[0]).splitlines())
        status_line("OK", f"common_config_codex is present ({common_lines} lines)")
    else:
        status_line("INFO", "common_config_codex is empty")

    top_level, sections = parse_simple_toml(config_path)
    model_provider = top_level.get("model_provider")
    if model_provider == "cc_switch_proxy":
        status_line("OK", "Codex config uses model_provider = cc_switch_proxy")
    else:
        status_line(
            "FAIL",
            f"Codex config model_provider is {model_provider!r}, expected 'cc_switch_proxy'",
        )
        failures += 1

    if "model_providers.cc_switch_proxy" in sections:
        status_line("OK", "Codex config contains [model_providers.cc_switch_proxy]")
    else:
        status_line("FAIL", "Codex config is missing [model_providers.cc_switch_proxy]")
        failures += 1

    auth_payload = load_json_file(auth_path)
    if isinstance(auth_payload, dict) and auth_payload.get("OPENAI_API_KEY") == "proxy-placeholder":
        status_line("OK", "Codex auth uses proxy-placeholder")
    elif proxy_enabled and takeover_enabled:
        status_line("FAIL", "Codex auth is not proxy-placeholder while proxy mode is active")
        failures += 1
    else:
        keys = sorted(auth_payload) if isinstance(auth_payload, dict) else []
        status_line("INFO", f"Codex auth is direct-provider style; keys: {', '.join(keys)}")

    print()
    if failures:
        status_line("FAIL", f"{failures} check(s) failed")
        return 1
    status_line("OK", "Codex hot-switch state looks usable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

