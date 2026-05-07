# cc-switch Codex Hot Switch

Keep Codex connected to a stable local `cc-switch` proxy provider while switching the real upstream provider behind that proxy.

This project is designed for Linux servers where `cc-switch-cli` manages multiple Codex-compatible upstream providers. Instead of rewriting Codex directly to each upstream provider, Codex is pinned to a stable local proxy provider and `cc-switch` changes the upstream behind it.

## Core Idea

Codex always sees the same provider:

```toml
model_provider = "cc_switch_proxy"
model = "<model from current cc-switch provider>"

[model_providers.cc_switch_proxy]
name = "cc_switch_proxy"
base_url = "http://127.0.0.1:15721/v1"
wire_api = "responses"
requires_openai_auth = true
```

In proxy mode, Codex auth only contains a placeholder:

```json
{
  "OPENAI_API_KEY": "proxy-placeholder"
}
```

The real upstream `base_url` and API key stay inside the `cc-switch` database. The local proxy forwards Codex requests to the currently selected upstream provider.

## Repository Contents

- `cc-switch-sync-codex.py`: syncs Codex config/auth from the current `cc-switch` Codex provider.
- `cc-switch-check-codex.py`: checks proxy, provider, Codex config, and auth state using only Python standard libraries.
- `quick-check.sh`: shell wrapper around the Python checker, with `CC_SWITCH_DB` / `CODEX_DIR` compatibility.
- `cc-switch-hot.sh`: runs `cc-switch`, then runs the sync script if the command succeeds.
- `systemd/cc-switch-codex-proxy.service`: user-level systemd service template for keeping the Codex proxy running.

## Requirements

- Python 3.10 or newer.
- Installed `cc-switch-cli`.
- A working `cc-switch` database containing at least one Codex provider.
- A running `cc-switch` proxy takeover for `app_type = 'codex'`.
- Codex configured from files under its active home directory.

Default paths:

```text
$HOME/.cc-switch/cc-switch.db
$HOME/.codex/config.toml
$HOME/.codex/auth.json
```

If the Codex process runs as another user, use that user's `$HOME`. For example, running Codex as `root` and running the sync script as a normal user will write different config directories unless explicit paths are passed.

## Bootstrap From Scratch

### 1. Install cc-switch-cli

This repository does not install `cc-switch` or initialize providers. Install `cc-switch-cli` first, for example:

```bash
curl -fsSL https://github.com/SaladDay/cc-switch-cli/releases/latest/download/install.sh | bash
```

Verify:

```bash
cc-switch --help
```

### 2. Create a Codex Provider

The sync script expects the `cc-switch` database to already contain a current Codex provider.

Useful checks:

```bash
cc-switch --app codex provider list
cc-switch --app codex provider current
```

Recommended separation:

- `providers.settings_config.config`: real upstream config only, such as real `model_provider`, `model`, `base_url`, and `wire_api`.
- `providers.settings_config.auth`: real upstream credentials.
- `settings.common_config_codex`: shared Codex top-level settings across providers.

Example shared config:

```toml
model_reasoning_effort = "high"
disable_response_storage = true
```

Do not define the same top-level setting both in provider config and `common_config_codex`.

### 3. Start Codex Proxy Takeover

Important: `proxy enable` and "the proxy is running" are different states.

The sync script only switches Codex to the local proxy when both database fields are `1`:

```text
proxy_enabled = 1
enabled = 1
```

Usually you need to start the proxy process:

```bash
cc-switch proxy serve --takeover codex
```

After a successful foreground test, run it as a user-level systemd service.

### 4. Install Scripts

Recommended layout:

```bash
mkdir -p "$HOME/.local/share/cc-switch-codex-hot-switch" "$HOME/.local/bin"
cp cc-switch-sync-codex.py cc-switch-check-codex.py quick-check.sh cc-switch-hot.sh \
  "$HOME/.local/share/cc-switch-codex-hot-switch/"
chmod +x "$HOME/.local/share/cc-switch-codex-hot-switch/"*.py
chmod +x "$HOME/.local/share/cc-switch-codex-hot-switch/"*.sh
ln -sf "$HOME/.local/share/cc-switch-codex-hot-switch/cc-switch-sync-codex.py" \
  "$HOME/.local/bin/cc-switch-codex-sync"
ln -sf "$HOME/.local/share/cc-switch-codex-hot-switch/cc-switch-check-codex.py" \
  "$HOME/.local/bin/cc-switch-codex-check"
ln -sf "$HOME/.local/share/cc-switch-codex-hot-switch/cc-switch-hot.sh" \
  "$HOME/.local/bin/cc-switch-hot"
```

### 5. Sync Codex Config

Dry run:

```bash
python3 cc-switch-sync-codex.py --dry-run
```

Apply:

```bash
python3 cc-switch-sync-codex.py
```

Use explicit home when Codex does not use the current shell user's `$HOME`:

```bash
python3 cc-switch-sync-codex.py \
  --home /path/to/codex-user-home
```

Or pass paths directly:

```bash
python3 cc-switch-sync-codex.py \
  --db-path /path/to/.cc-switch/cc-switch.db \
  --codex-dir /path/to/.codex
```

### 6. Validate

Run:

```bash
python3 cc-switch-check-codex.py
```

Or:

```bash
./quick-check.sh
```

`quick-check.sh` supports explicit paths through environment variables:

```bash
CC_SWITCH_DB=/path/to/.cc-switch/cc-switch.db \
CODEX_DIR=/path/to/.codex \
./quick-check.sh
```

Acceptance checklist:

- `proxy_config.proxy_enabled = 1`
- `proxy_config.enabled = 1`
- `proxy_runtime_session` shows runtime address and port
- `~/.codex/config.toml` uses `model_provider = "cc_switch_proxy"`
- `~/.codex/config.toml` contains `[model_providers.cc_switch_proxy]`
- `~/.codex/auth.json` uses `proxy-placeholder`
- the current `cc-switch` Codex provider still stores real upstream credentials

## systemd Proxy Service

Template:

```text
systemd/cc-switch-codex-proxy.service
```

Install as a user service:

```bash
mkdir -p "$HOME/.config/systemd/user"
cp systemd/cc-switch-codex-proxy.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now cc-switch-codex-proxy.service
```

Check status:

```bash
systemctl --user status cc-switch-codex-proxy.service
```

The template runs:

```text
%h/.local/bin/cc-switch proxy serve --takeover codex
```

If your `cc-switch` binary is not at `$HOME/.local/bin/cc-switch`, edit `ExecStart`.

## Auto-Sync After Switching

`cc-switch-hot.sh` runs the original `cc-switch` command, then runs `cc-switch-sync-codex.py` if the command succeeds.

Example:

```bash
cc-switch-hot --app codex provider switch <provider-id>
```

If installed with the recommended layout, you can add this alias in interactive shells:

```bash
alias cc-switch='cc-switch-hot'
```

Or append it to `~/.bash_aliases`:

```bash
echo "alias cc-switch='cc-switch-hot'" >> "$HOME/.bash_aliases"
```

Skip auto-sync:

```bash
CODEX_HOT_SWITCH_SKIP_SYNC=1 cc-switch-hot --help
```

Custom `cc-switch` binary:

```bash
CC_SWITCH_BIN=/custom/path/cc-switch cc-switch-hot --app codex provider current
```

Custom sync script:

```bash
CODEX_SYNC_SCRIPT=/custom/path/cc-switch-sync-codex.py \
  cc-switch-hot --app codex provider switch <provider-id>
```

## cc-switch Database Fields Used

Current Codex provider:

```sql
SELECT settings_config
FROM providers
WHERE app_type = 'codex' AND is_current = 1
ORDER BY rowid DESC
LIMIT 1;
```

Proxy takeover:

```sql
SELECT proxy_enabled, enabled, listen_address, listen_port
FROM proxy_config
WHERE app_type = 'codex'
LIMIT 1;
```

If `settings.proxy_runtime_session` contains an `address` or `port`, the sync script prefers those runtime values over `proxy_config.listen_address` and `proxy_config.listen_port`.

Shared Codex config:

```sql
SELECT value FROM settings WHERE key = 'common_config_codex';
```

## Config Preservation Rules

The script rewrites only provider/auth-related state.

It removes top-level keys that conflict with managed provider state:

- `model_provider`
- `model`
- keys supplied by `common_config_codex`

It also removes existing `[model_providers.*]` sections to avoid stale provider definitions.

Other Codex config sections are preserved, for example:

```toml
[projects."/path/to/project"]
trust_level = "trusted"
```

MCP and other non-provider sections are preserved too.

## Security Notes

Do not commit real API keys.

In proxy mode, `auth.json` should contain only:

```json
{
  "OPENAI_API_KEY": "proxy-placeholder"
}
```

Real API keys remain in the local `cc-switch` database. Treat that database as secret material and do not publish it.

Dry-run and check commands redact auth values before printing. If proxy mode is disabled, the sync script still writes the real auth payload to Codex `auth.json`, because Codex is configured to talk directly to the selected provider in that mode.

Before pushing this repository, check:

```bash
git status --short
git diff -- .
```

## Troubleshooting

### `cc-switch DB not found`

The default path is:

```text
$HOME/.cc-switch/cc-switch.db
```

Run the script as the same user that owns the database, or pass `--home` / `--db-path`.

### No Current Codex Provider

Create and select an `app_type = 'codex'` provider in `cc-switch` first. The sync script does not create providers.

### `proxy enable` Was Run but Codex Still Does Not Use the Proxy

`proxy enable` only enables the persistent switch. It does not prove that a proxy process is running. Start takeover:

```bash
cc-switch proxy serve --takeover codex
```

Then verify that both `proxy_enabled` and `enabled` pass in the checker.

### Codex Still Uses the Old Provider

Check the top of Codex config:

```bash
sed -n '1,80p' "$HOME/.codex/config.toml"
```

It should start with:

```toml
model_provider = "cc_switch_proxy"
```

If it does not, rerun the sync script.

### Requests Fail With Auth Errors

In proxy mode, auth failures usually mean one of these:

- the `cc-switch` proxy is not running;
- the active upstream provider key in `cc-switch` is invalid;
- Codex is not actually pointing at the local proxy;
- the script wrote config for a different `$HOME` than the Codex process uses.

### Session History Appears Missing

Confirm Codex is using the expected home directory:

```bash
printf '%s\n' "$HOME"
ls -la "$HOME/.codex"
```

Session continuity depends on using the same Codex data directory. Switching users, containers, or mounted homes can make history appear missing even if no files were deleted.

## Recommended Steady State

1. Codex config points to `cc_switch_proxy`.
2. Codex auth uses the placeholder key.
3. The `cc-switch` provider stores real upstream config and credentials.
4. The local `cc-switch` proxy is kept alive by systemd or another supervisor.
5. Provider switching automatically invokes the sync script.

