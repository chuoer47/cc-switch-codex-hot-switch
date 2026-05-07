# cc-switch Codex 热切换

[English README](README.en.md)

## 项目背景

我在 Linux 服务器上使用 [cc-switch-cli](https://github.com/SaladDay/cc-switch-cli) 切换 Codex 上游服务。直接把 Codex 改到不同中转站时，当前会话和历史状态容易变得不稳定。这个仓库提供一个小的同步层：让 Codex 固定连接本地 `cc-switch` 代理，真实 provider 在代理后面切换。

如果你已经能使用 code agent，可以直接把这个仓库链接交给 agent，让它按 README 在服务器上部署。

## 核心思路

Codex 始终看到同一个 provider：

```toml
model_provider = "cc_switch_proxy"
model = "<来自当前 cc-switch provider 的 model>"

[model_providers.cc_switch_proxy]
name = "cc_switch_proxy"
base_url = "http://127.0.0.1:15721/v1"
wire_api = "responses"
requires_openai_auth = true
```

Codex 的 `auth.json` 在代理模式下只保留占位 key：

```json
{
  "OPENAI_API_KEY": "proxy-placeholder"
}
```

真实上游的 `base_url` 和 API key 留在 `cc-switch` 数据库里。本地代理负责把 Codex 请求转发到当前选中的真实 provider。

## 文件说明

- `cc-switch-sync-codex.py`：把 `cc-switch` 当前 Codex provider 同步到 Codex 配置。
- `cc-switch-check-codex.py`：用 Python 标准库检查代理、provider、Codex 配置和 auth 状态。
- `quick-check.sh`：检查脚本的 shell 包装，兼容 `CC_SWITCH_DB` / `CODEX_DIR` 环境变量。
- `cc-switch-hot.sh`：先执行 `cc-switch`，成功后自动运行同步脚本。
- `systemd/cc-switch-codex-proxy.service`：用户级 systemd 服务模板，用于常驻运行 Codex 代理。

## 环境要求

- Python 3.10 或更高版本。
- 已安装 `cc-switch-cli`。
- 已存在可用的 `cc-switch` 数据库，并且其中包含 Codex provider。
- `cc-switch` 已为 `app_type = 'codex'` 启动代理 takeover。
- Codex 使用文件方式读取其配置目录。

默认路径：

```text
$HOME/.cc-switch/cc-switch.db
$HOME/.codex/config.toml
$HOME/.codex/auth.json
```

如果 Codex 进程运行在另一个用户下，必须使用那个用户的 `$HOME`。例如 Codex 以 `root` 运行，而同步脚本以普通用户运行，两者默认会写到不同配置目录。此时应显式传路径。

## 从零接入

### 1. 安装 cc-switch-cli

本仓库不安装 `cc-switch`，也不初始化 provider。先按 `cc-switch-cli` 官方方式安装，例如：

```bash
curl -fsSL https://github.com/SaladDay/cc-switch-cli/releases/latest/download/install.sh | bash
```

确认命令可用：

```bash
cc-switch --help
```

### 2. 创建 Codex provider

同步脚本依赖 `cc-switch` 数据库中已经有当前 Codex provider。先创建并选中至少一个 `app_type = 'codex'` 的 provider。

常用检查命令：

```bash
cc-switch --app codex provider list
cc-switch --app codex provider current
```

建议把 provider 配置职责拆清楚：

- `providers.settings_config.config`：只放真实上游相关配置，例如真实 `model_provider`、`model`、`base_url`、`wire_api`。
- `providers.settings_config.auth`：保存真实上游认证。
- `settings.common_config_codex`：保存跨 provider 通用的 Codex 顶层配置。

通用配置示例：

```toml
model_reasoning_effort = "high"
disable_response_storage = true
```

不要同时在 provider 配置和 `common_config_codex` 中重复放同一个顶层字段，否则容易产生冲突。

### 3. 启动 Codex 代理 takeover

注意：`proxy enable` 和“代理正在运行”不是一回事。

同步脚本只有在以下两个数据库字段都为 `1` 时，才会把 Codex 指到本地代理：

```text
proxy_enabled = 1
enabled = 1
```

通常需要真正启动代理进程：

```bash
cc-switch proxy serve --takeover codex
```

前台验证成功后，建议用用户级 systemd 常驻。

### 4. 安装脚本到用户目录

一种推荐布局：

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

### 5. 同步 Codex 配置

先 dry run：

```bash
python3 cc-switch-sync-codex.py --dry-run
```

正式同步：

```bash
python3 cc-switch-sync-codex.py
```

如果 Codex 使用的 home 不是当前 shell 的 `$HOME`：

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

### 6. 检查验收

运行：

```bash
python3 cc-switch-check-codex.py
```

或：

```bash
./quick-check.sh
```

`quick-check.sh` 支持通过环境变量指定路径：

```bash
CC_SWITCH_DB=/path/to/.cc-switch/cc-switch.db \
CODEX_DIR=/path/to/.codex \
./quick-check.sh
```

验收标准：

- `proxy_config.proxy_enabled = 1`
- `proxy_config.enabled = 1`
- `proxy_runtime_session` 能看到运行时地址和端口
- `~/.codex/config.toml` 指向 `model_provider = "cc_switch_proxy"`
- `~/.codex/config.toml` 包含 `[model_providers.cc_switch_proxy]`
- `~/.codex/auth.json` 是 `proxy-placeholder`
- `cc-switch` 当前 Codex provider 仍保存真实上游认证

## systemd 常驻代理

仓库提供模板：

```text
systemd/cc-switch-codex-proxy.service
```

安装到用户级 systemd：

```bash
mkdir -p "$HOME/.config/systemd/user"
cp systemd/cc-switch-codex-proxy.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now cc-switch-codex-proxy.service
```

查看状态：

```bash
systemctl --user status cc-switch-codex-proxy.service
```

模板默认执行：

```text
%h/.local/bin/cc-switch proxy serve --takeover codex
```

如果你的 `cc-switch` 不在 `$HOME/.local/bin/cc-switch`，需要修改 service 里的 `ExecStart`。

## 切换后自动同步

仓库提供 `cc-switch-hot.sh`。它会先执行原始 `cc-switch` 命令，命令成功后再调用 `cc-switch-sync-codex.py`。

示例：

```bash
cc-switch-hot --app codex provider switch <provider-id>
```

如果已经按推荐布局安装，可以在交互式 shell 中加 alias：

```bash
alias cc-switch='cc-switch-hot'
```

或写入 `~/.bash_aliases`：

```bash
echo "alias cc-switch='cc-switch-hot'" >> "$HOME/.bash_aliases"
```

跳过自动同步：

```bash
CODEX_HOT_SWITCH_SKIP_SYNC=1 cc-switch-hot --help
```

如果 `cc-switch` 命令路径特殊：

```bash
CC_SWITCH_BIN=/custom/path/cc-switch cc-switch-hot --app codex provider current
```

如果同步脚本路径特殊：

```bash
CODEX_SYNC_SCRIPT=/custom/path/cc-switch-sync-codex.py \
  cc-switch-hot --app codex provider switch <provider-id>
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

如果 `settings.proxy_runtime_session` 存在，并且包含 `address` 或 `port`，脚本会优先使用运行时地址和端口，而不是 `proxy_config.listen_address` / `proxy_config.listen_port`。

脚本还会追加共享 Codex 配置：

```sql
SELECT value FROM settings WHERE key = 'common_config_codex';
```

## 配置保留规则

脚本只重写和 provider/auth 切换相关的部分。

会移除已有配置中与托管 provider 状态冲突的顶层字段：

- `model_provider`
- `model`
- `common_config_codex` 中提供的字段

也会移除已有的 `[model_providers.*]` 段，避免旧 provider 残留。

其他 Codex 配置段会保留。例如：

```toml
[projects."/path/to/project"]
trust_level = "trusted"
```

MCP 配置和其他非 provider section 也会保留。

## 安全说明

不要提交真实 API key。

代理模式下，`auth.json` 应只包含：

```json
{
  "OPENAI_API_KEY": "proxy-placeholder"
}
```

真实 API key 保存在本地 `cc-switch` 数据库中。这个数据库应视为敏感文件，不要发布。

`--dry-run` 和检查脚本会在输出认证信息时自动打码。注意：如果代理模式未开启，同步脚本仍会把真实认证信息写入 Codex 的 `auth.json`，因为这种模式下 Codex 是直接访问当前 provider。

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

### 没有当前 Codex provider

先在 `cc-switch` 中创建并选中一个 `app_type = 'codex'` 的 provider。同步脚本不负责创建 provider。

### 执行了 proxy enable 但 Codex 没切到代理

`proxy enable` 只表示持久开关打开，不等于代理进程正在接管。需要运行：

```bash
cc-switch proxy serve --takeover codex
```

并确认检查脚本里 `proxy_enabled` 和 `enabled` 都通过。

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

### 会话历史看起来丢失

先确认 Codex 使用的是预期 home：

```bash
printf '%s\n' "$HOME"
ls -la "$HOME/.codex"
```

会话连续性依赖同一个 Codex 数据目录。切换用户、容器或挂载目录后，即使文件没有被删除，也可能看起来像历史丢失。

## 推荐稳定态

1. Codex 配置指向 `cc_switch_proxy`。
2. Codex auth 使用占位 key。
3. `cc-switch` provider 保存真实上游配置和认证。
4. 本地 `cc-switch` 代理由 systemd 或其他守护方式常驻。
5. provider 切换后自动调用同步脚本。

