# cc-switch Codex Hot Switch

Keep Codex connected to a stable local `cc-switch` proxy provider while switching the real upstream provider behind that proxy.

This is useful when you use `cc-switch` to rotate or switch Codex-compatible providers and want Codex to keep using the same local provider identity instead of rewriting Codex to every real provider directly.

## What This Does

The sync script reads the current Codex provider from the `cc-switch` SQLite database and writes Codex config files.

When the Codex proxy is enabled in `cc-switch`, Codex is configured like this:

```toml
model_provider = "cc_switch_proxy"
model = "<model from current cc-switch provider>"

[model_providers.cc_switch_proxy]
name = "cc_switch_proxy"
base_url = "http://127.0.0.1:15721/v1"
wire_api = "responses"
requires_openai_auth = true
```

And Codex auth is written as a placeholder:

```json
{
  "OPENAI_API_KEY": "proxy-placeholder"
}
```

The real provider `base_url` and API key stay inside `cc-switch`. Codex only talks to the local proxy.

## Why This Helps

Codex stores sessions and local state under its Codex data directory, usually:

```text
$HOME/.codex/
```

The important part is provider stability. If Codex is repeatedly rewritten from provider A to provider B to provider C, the active runtime may treat the provider/auth/base URL change as a materially different backend. This can interrupt the current workflow or make session continuity harder to reason about.

With this approach, Codex sees a stable provider:

- `model_provider = "cc_switch_proxy"`
- `base_url = "http://<local-proxy-host>:<local-proxy-port>/v1"`
- placeholder OpenAI API key

Only `cc-switch` changes the real upstream provider.

## Repository Contents

- `cc-switch-sync-codex.py`: syncs Codex config/auth from `cc-switch`.
- `quick-check.sh`: prints relevant proxy and Codex config state.

## Requirements

- Python 3.10 or newer.
- `sqlite3` command-line tool for `quick-check.sh`.
- A working `cc-switch` database containing Codex providers.
- A running or configured `cc-switch` proxy for `app_type = 'codex'`.
- Codex configured from files under its active home directory.

The default paths are:

```text
$HOME/.cc-switch/cc-switch.db
$HOME/.codex/config.toml
$HOME/.codex/auth.json
```

If your Codex process runs as a different user, use that user's `$HOME`. For example, running Codex as `root` and running the sync script as a normal user will write different config directories unless you pass explicit paths.

## Usage

Run a dry run first:

```bash
python3 cc-switch-sync-codex.py --dry-run
```

Apply the sync:

```bash
python3 cc-switch-sync-codex.py
```

Check the result:

```bash
./quick-check.sh
```

`quick-check.sh` supports explicit paths through environment variables:

```bash
CC_SWITCH_DB=/path/to/.cc-switch/cc-switch.db \
CODEX_DIR=/path/to/.codex \
./quick-check.sh
```

Use explicit paths when the active Codex home is not the shell user's `$HOME`:

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

## cc-switch Database Fields Used

The script reads the current Codex provider from:

```sql
SELECT settings_config
FROM providers
WHERE app_type = 'codex' AND is_current = 1
ORDER BY rowid DESC
LIMIT 1;
```

It checks whether Codex proxy takeover is enabled through:

```sql
SELECT proxy_enabled, enabled, listen_address, listen_port
FROM proxy_config
WHERE app_type = 'codex'
LIMIT 1;
```

Proxy mode is active only when both values are enabled:

```text
proxy_enabled = 1
enabled = 1
```

If `settings.proxy_runtime_session` exists and contains an `address` or `port`, those runtime values take precedence over `proxy_config.listen_address` and `proxy_config.listen_port`.

The script also appends shared Codex config from:

```sql
SELECT value FROM settings WHERE key = 'common_config_codex';
```

This is useful for settings such as:

```toml
model_reasoning_effort = "high"
disable_response_storage = true
```

## Config Preservation Rules

The script rewrites only the provider/auth portion needed for Codex provider switching.

It removes existing top-level keys that conflict with managed provider state:

- `model_provider`
- `model`
- keys supplied by `common_config_codex`

It also removes existing `[model_providers.*]` sections so stale providers do not remain in Codex config.

Other Codex config sections are preserved. For example project trust entries are kept:

```toml
[projects."/path/to/project"]
trust_level = "trusted"
```

## Security Notes

Do not commit real API keys.

In proxy mode, `auth.json` should contain only:

```json
{
  "OPENAI_API_KEY": "proxy-placeholder"
}
```

The real API keys remain in the local `cc-switch` database. Treat that database as secret material and do not publish it.

The dry-run and quick-check commands redact auth values before printing. The sync script still writes the real auth payload when proxy mode is disabled, because in that mode Codex is being configured to talk directly to the selected provider.

Before pushing this repository, check:

```bash
git status --short
git diff -- .
```

## Troubleshooting

### `cc-switch DB not found`

The script looked for:

```text
$HOME/.cc-switch/cc-switch.db
```

Fix by running under the same user that owns the `cc-switch` database, or pass `--home` / `--db-path`.

### Codex still uses the old provider

Check the top of Codex config:

```bash
sed -n '1,80p' "$HOME/.codex/config.toml"
```

It should start with:

```toml
model_provider = "cc_switch_proxy"
```

If it does not, rerun the sync script.

### Requests fail with auth errors

In proxy mode, auth failures usually mean one of these:

- the `cc-switch` proxy is not running;
- the active upstream provider key in `cc-switch` is invalid;
- Codex is not actually pointing at the local proxy;
- the script wrote config for a different `$HOME` than the Codex process uses.

### Proxy port is wrong

Inspect the runtime proxy session:

```bash
sqlite3 "$HOME/.cc-switch/cc-switch.db" \
  "SELECT value FROM settings WHERE key='proxy_runtime_session';"
```

If it contains `address` or `port`, the sync script will use those values first.

### Session history appears missing

Confirm Codex is using the expected home directory:

```bash
printf '%s\n' "$HOME"
ls -la "$HOME/.codex"
```

Session continuity depends on using the same Codex data directory. Switching between users, containers, or mounted homes can make history appear missing even if no files were deleted.

## Operational Model

Use this script after changing provider state in `cc-switch`, especially when proxy address or model selection may have changed.

The intended steady state is:

1. Codex config points to `cc_switch_proxy`.
2. Codex auth uses the placeholder key.
3. The local `cc-switch` proxy forwards requests to the currently selected upstream provider.
4. Provider switching happens inside `cc-switch`, not by directly rewriting Codex to each upstream provider.

