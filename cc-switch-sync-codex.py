#!/usr/bin/env python3

import json
import os
import re
import sqlite3
import sys
from argparse import ArgumentParser
from pathlib import Path


ASSIGNMENT_RE = re.compile(r"^([A-Za-z0-9_]+)\s*=")
PROXY_PLACEHOLDER_TOKEN = "proxy-placeholder"


def top_level_keys(snippet: str) -> set[str]:
    keys: set[str] = set()
    for raw_line in snippet.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        match = ASSIGNMENT_RE.match(line)
        if match:
            keys.add(match.group(1))
    return keys


def top_level_assignment(snippet: str, key: str) -> str | None:
    in_section = False
    for raw_line in snippet.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_section = True
            continue
        if in_section:
            continue
        match = ASSIGNMENT_RE.match(line)
        if match and match.group(1) == key:
            return line.split("=", 1)[1].strip()
    return None


def preserve_existing_config(existing: str, common_keys: set[str]) -> str:
    preserved: list[str] = []
    section_name: str | None = None
    skip_section = False
    blocked_keys = {"model_provider", "model", *common_keys}

    for raw_line in existing.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section_name = stripped[1:-1].strip()
            skip_section = section_name.startswith("model_providers.")
            if skip_section:
                continue
            preserved.append(raw_line)
            continue

        if skip_section:
            continue

        if section_name is None:
            match = ASSIGNMENT_RE.match(stripped)
            if match and match.group(1) in blocked_keys:
                continue

        preserved.append(raw_line)

    return "\n".join(preserved).strip()


def write_text_if_changed(path: Path, content: str) -> bool:
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def redacted_auth_payload(auth_payload: object) -> object:
    if not isinstance(auth_payload, dict):
        return auth_payload
    return {key: "<redacted>" for key in auth_payload}


def load_proxy_runtime_session(conn: sqlite3.Connection) -> dict[str, object] | None:
    row = conn.execute(
        "SELECT value FROM settings WHERE key = 'proxy_runtime_session'"
    ).fetchone()
    if row is None or not row[0]:
        return None
    try:
        payload = json.loads(row[0])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def codex_proxy_base_url(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        """
        SELECT proxy_enabled, enabled, listen_address, listen_port
        FROM proxy_config
        WHERE app_type = 'codex'
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None

    proxy_enabled, takeover_enabled, listen_address, listen_port = row
    if not proxy_enabled or not takeover_enabled:
        return None

    runtime_session = load_proxy_runtime_session(conn)
    if runtime_session is not None:
        listen_address = runtime_session.get("address") or listen_address
        listen_port = runtime_session.get("port") or listen_port

    if not isinstance(listen_address, str) or not listen_address.strip():
        return None
    try:
        port = int(listen_port)
    except (TypeError, ValueError):
        return None

    return f"http://{listen_address.strip()}:{port}/v1"


def build_proxy_provider_config(provider_config: str, base_url: str) -> str:
    model_value = top_level_assignment(provider_config, "model")
    lines = ['model_provider = "cc_switch_proxy"']
    if model_value:
        lines.append(f"model = {model_value}")
    lines.extend(
        [
            "",
            "[model_providers.cc_switch_proxy]",
            'name = "cc_switch_proxy"',
            f'base_url = "{base_url}"',
            'wire_api = "responses"',
            "requires_openai_auth = true",
        ]
    )
    return "\n".join(lines)


def parse_args() -> object:
    parser = ArgumentParser(
        description=(
            "Synchronize Codex config from cc-switch. When the cc-switch Codex "
            "proxy is enabled, Codex is pinned to a stable local proxy provider."
        )
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the target paths and generated config without writing files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    home = args.home.expanduser()
    db_path = (args.db_path or home / ".cc-switch" / "cc-switch.db").expanduser()
    codex_dir = (args.codex_dir or home / ".codex").expanduser()
    config_path = codex_dir / "config.toml"
    auth_path = codex_dir / "auth.json"

    if not db_path.exists():
        print(f"cc-switch DB not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT settings_config
            FROM providers
            WHERE app_type = 'codex' AND is_current = 1
            ORDER BY rowid DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            print("No current codex provider found in cc-switch DB", file=sys.stderr)
            return 1

        settings_config = json.loads(row[0])
        provider_config = settings_config.get("config", "").strip()
        auth_payload = settings_config.get("auth", {})

        common_row = conn.execute(
            "SELECT value FROM settings WHERE key = 'common_config_codex'"
        ).fetchone()
        common_config = common_row[0].strip() if common_row and common_row[0] else ""
        proxy_base_url = codex_proxy_base_url(conn)
    finally:
        conn.close()

    if not provider_config:
        print("Current codex provider has no config payload", file=sys.stderr)
        return 1

    if proxy_base_url:
        provider_config = build_proxy_provider_config(provider_config, proxy_base_url)
        auth_payload = {"OPENAI_API_KEY": PROXY_PLACEHOLDER_TOKEN}

    common_keys = top_level_keys(common_config)
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    preserved = preserve_existing_config(existing, common_keys)

    parts = [provider_config]
    if common_config:
        parts.append(common_config)
    if preserved:
        parts.append(preserved)
    config_content = "\n\n".join(parts).rstrip() + "\n"

    auth_content = json.dumps(auth_payload, ensure_ascii=False, indent=2) + "\n"

    if args.dry_run:
        dry_run_auth_content = (
            json.dumps(redacted_auth_payload(auth_payload), ensure_ascii=False, indent=2)
            + "\n"
        )
        print(f"cc-switch DB: {db_path}")
        print(f"Codex config: {config_path}")
        print(f"Codex auth: {auth_path}")
        print("\n--- config.toml ---")
        print(config_content, end="")
        print("\n--- auth.json (redacted) ---")
        print(dry_run_auth_content, end="")
        return 0

    config_changed = write_text_if_changed(config_path, config_content)
    auth_changed = write_text_if_changed(auth_path, auth_content)

    if config_changed or auth_changed:
        source = (
            f"cc-switch proxy ({proxy_base_url})"
            if proxy_base_url
            else "the current provider"
        )
        print(
            f"Synchronized Codex config from {source} to {config_path}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
