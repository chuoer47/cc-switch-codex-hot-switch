# cc-switch Codex 热切换

[English README](README.en.md)

## 项目背景

在Linux服务器，我使用[cc-switch-cli](https://github.com/SaladDay/cc-switch-cli)更好自己切换服务。

但是Codex直接换中转站会导致历史记录不见，虽然可以让agent帮忙恢复，但是还是很麻烦，就vibe coding了一个小的中间层。如果你现在能用code agent，直接把仓库链接丢给ta就能帮完成好了。

让 Codex 始终连接到稳定的本地 `cc-switch` 代理 provider，而真实上游 provider 在代理后面切换。

这个方案适合这样的场景：你用 `cc-switch` 切换多个 Codex 兼容 provider，但不希望 Codex 自己的 `model_provider`、`base_url`、`auth` 每次都被改成真实 provider，从而影响当前会话连续性。

## 功能

同步脚本会读取 `cc-switch` SQLite 数据库里的当前 Codex provider，并写入 Codex 配置文件。

当 `cc-switch` 里 Codex 代理已开启时，Codex 会被配置为：

```toml
model_provider = "cc_switch_proxy"
model = "<来自当前 cc-switch provider 的 model>"

[model_providers.cc_switch_proxy]
name = "cc_switch_proxy"
base_url = "http://127.0.0.1:15721/v1"
wire_api = "responses"
requires_openai_auth = true
```

Codex 的认证文件会写成占位 key：

```json
{
  "OPENAI_API_KEY": "proxy-placeholder"
}
```

真实 provider 的 `base_url` 和 API key 仍然保存在 `cc-switch` 中。Codex 只访问本地代理。

## 为什么有用

Codex 的会话和本地状态通常保存在：

```text
$HOME/.codex/
```

关键点是 provider 身份稳定。如果 Codex 被反复改成 provider A、provider B、provider C，运行中的 Codex 可能会把 provider、认证、base URL 的变化视为后端变更，从而影响当前工作流或会话连续性。

使用本方案后，Codex 看到的始终是：

- `model_provider = "cc_switch_proxy"`
- `base_url = "http://<本地代理地址>:<本地代理端口>/v1"`
- 占位 OpenAI API key

真实上游 provider 只在 `cc-switch` 内部切换。

## 文件说明

- `cc-switch-sync-codex.py`：从 `cc-switch` 同步 Codex 配置和认证。
- `quick-check.sh`：打印代理状态和 Codex 配置状态。

## 环境要求

- Python 3.10 或更高版本。
- `quick-check.sh` 需要 `sqlite3` 命令行工具。
- 已存在可用的 `cc-switch` 数据库，并且其中包含 Codex provider。
- `cc-switch` 已为 `app_type = 'codex'` 配置或启动代理。
- Codex 使用文件方式读取其配置目录。

默认路径：

```text
$HOME/.cc-switch/cc-switch.db
$HOME/.codex/config.toml
$HOME/.codex/auth.json
```

注意：如果 Codex 进程运行在另一个用户下，必须使用那个用户的 `$HOME`。例如 Codex 以 `root` 运行，而同步脚本以普通用户运行，两者默认会写到不同的配置目录。此时应显式传路径。

## 使用方法

先 dry run，确认将要生成的内容：

```bash
python3 cc-switch-sync-codex.py --dry-run
```

正式同步：

```bash
python3 cc-switch-sync-codex.py
```

检查结果：

```bash
./quick-check.sh
```

`quick-check.sh` 支持通过环境变量指定路径：

```bash
CC_SWITCH_DB=/path/to/.cc-switch/cc-switch.db \
CODEX_DIR=/path/to/.codex \
./quick-check.sh
```

如果 Codex 实际使用的 home 不是当前 shell 的 `$HOME`：

```bash
python3 cc-switch-sync-codex.py \
  --home /path/to/codex-user-home
```

也可以直接传数据库和 Codex 配置目录：

```bash
python3 cc-switch-sync-codex.py \
  --db-path /path/to/.cc-switch/cc-switch.db \
  --codex-dir /path/to/.codex
```

## 使用到的 cc-switch 数据库字段

读取当前 Codex provider：

```sql
SELECT settings_config
FROM providers
WHERE app_type = 'codex' AND is_current = 1
ORDER BY rowid DESC
LIMIT 1;
```

检查 Codex 代理是否接管：

```sql
SELECT proxy_enabled, enabled, listen_address, listen_port
FROM proxy_config
WHERE app_type = 'codex'
LIMIT 1;
```

代理模式只有在以下两个值都开启时才生效：

```text
proxy_enabled = 1
enabled = 1
```

如果 `settings.proxy_runtime_session` 存在，并且包含 `address` 或 `port`，脚本会优先使用运行时地址和端口，而不是 `proxy_config.listen_address` / `proxy_config.listen_port`。

脚本还会追加共享 Codex 配置：

```sql
SELECT value FROM settings WHERE key = 'common_config_codex';
```

例如：

```toml
model_reasoning_effort = "high"
disable_response_storage = true
```

## 配置保留规则

脚本只重写和 provider/auth 切换相关的部分。

会移除已有配置中与托管 provider 状态冲突的顶层字段：

- `model_provider`
- `model`
- `common_config_codex` 中提供的字段

也会移除已有的 `[model_providers.*]` 段，避免旧 provider 残留。

其他 Codex 配置段会保留。例如项目 trust 配置：

```toml
[projects."/path/to/project"]
trust_level = "trusted"
```

## 安全说明

不要提交真实 API key。

代理模式下，`auth.json` 应只包含：

```json
{
  "OPENAI_API_KEY": "proxy-placeholder"
}
```

真实 API key 保存在本地 `cc-switch` 数据库中。这个数据库应视为敏感文件，不要发布。

`--dry-run` 和 `quick-check.sh` 会在输出认证信息时自动打码。注意：如果代理模式未开启，同步脚本仍会把真实认证信息写入 Codex 的 `auth.json`，因为这种模式下 Codex 是直接访问当前 provider。

推送到 GitHub 前建议检查：

```bash
git status --short
git diff -- .
```

## 排错

### `cc-switch DB not found`

脚本默认查找：

```text
$HOME/.cc-switch/cc-switch.db
```

解决方式：用拥有该数据库的同一个用户运行脚本，或传入 `--home` / `--db-path`。

### Codex 仍然使用旧 provider

检查 Codex 配置顶部：

```bash
sed -n '1,80p' "$HOME/.codex/config.toml"
```

应以以下内容开头：

```toml
model_provider = "cc_switch_proxy"
```

如果不是，重新运行同步脚本。

### 请求失败并出现认证错误

代理模式下，认证错误通常说明：

- `cc-switch` 代理没有运行；
- `cc-switch` 中当前上游 provider 的 key 无效；
- Codex 没有实际指向本地代理；
- 脚本写入的 `$HOME` 与 Codex 进程实际使用的 `$HOME` 不一致。

### 代理端口不对

检查运行时代理会话：

```bash
sqlite3 "$HOME/.cc-switch/cc-switch.db" \
  "SELECT value FROM settings WHERE key='proxy_runtime_session';"
```

如果其中包含 `address` 或 `port`，同步脚本会优先使用这些值。

### 会话历史看起来丢失

先确认 Codex 使用的是预期 home：

```bash
printf '%s\n' "$HOME"
ls -la "$HOME/.codex"
```

会话连续性依赖同一个 Codex 数据目录。切换用户、容器或挂载目录后，即使文件没有被删除，也可能看起来像历史丢失。

## 推荐运行模型

在 `cc-switch` provider 状态变化后运行此脚本，尤其是代理地址、端口或模型选择可能变化时。

理想稳定状态：

1. Codex 配置指向 `cc_switch_proxy`。
2. Codex auth 使用占位 key。
3. 本地 `cc-switch` 代理把请求转发到当前选择的真实上游 provider。
4. provider 切换发生在 `cc-switch` 内部，而不是把 Codex 直接改写到每个真实 provider。

