# scodex-mini config.toml 设计（2026-09-20）

学 codex 的 `config.toml`，路径用我们自己的。

## Codex 的做法（research 结论）

分层（后者覆盖前者，per-key merge）：
1. package：随包默认配置
2. admin：MDM 托管（macOS）
3. system：`/etc/codex/config.toml`
4. cloud：企业云下发
5. user：`$CODEX_HOME/config.toml`（默认 `~/.codex/`）
6. profile：`$CODEX_HOME/<name>.config.toml`（`--profile` 选中时）
7. cwd：`$PWD/config.toml`（untrusted 目录则禁用）
8. tree：父目录向上找 `./.codex/config.toml`（untrusted 禁用）
9. repo：git root 的 `./.codex/config.toml`（untrusted 禁用）
10. runtime：`--config` flag 等

Profiles：`[profiles.<name>]` 内联表 + 独立 `<name>.config.toml` 文件两种。

## 我们的路径（用户要求：路径是我们自己的）

| 层 | 路径 |
|---|---|
| system | `/etc/scodex-mini/config.toml` |
| user | `$SCODEX_HOME/config.toml`，默认 `~/.scodex-mini/config.toml` |
| profile | `$SCODEX_HOME/profiles/<name>.toml`，或 user config 里的 `[profiles.<name>]` |
| project(cwd) | `./.scodex-mini/config.toml` |
| project(tree) | 父目录向上找 `.scodex-mini/config.toml`（到 `/` 或 git root） |
| project(repo) | `git rev-parse --show-toplevel` 的 `.scodex-mini/config.toml` |
| runtime | `SCODEX_*` 环境变量（最高优先级，保持现有行为） |

**不做的**：package 层（我们没发包默认配置）、admin/MDM、cloud（P2 再说）。
**信任模型**：v1 不做 untrusted 禁用（scodex-mini 是个人工具，不是多租户）；
project 层默认启用，`--no-project-config` 可关。

## TOML schema（v1，只收我们用得上的键）

```toml
# ~/.scodex-mini/config.toml
model = "gpt-5"
api_mode = "responses"          # responses | chat
base_url = "https://api.openai.com/v1"
max_turns = 8

[sandbox]
enabled = true
# 未来：profile 可切沙箱策略

[compaction]
budget = 32000
disabled = false

[mcp_servers.my-server]
command = "npx"
args = ["-y", "my-mcp"]
env = { FOO = "bar" }

[profiles.fast]
model = "gpt-5-mini"
api_mode = "chat"

[profiles.coding]
model = "gpt-5"
sandbox.enabled = true
```

**Merge 语义**：per-key，后层覆盖前层。`[mcp_servers.*]` 按 server name 合并
（同名覆盖，不同名并存）。`[profiles.*]` 不跨层合并（profile 必须完整定义
在同一层，或用 profile 文件）。

## TOML 子集（纯 SLA 解析器要支持的）

- `[table]`、`[table.sub]`（不支持 `[[array-of-tables]]`，v1 不需要）
- `key = "basic string"`（支持 `\"` `\\` `\n` `\t` 转义）
- `key = 'literal string'`（无转义）
- `key = 123` / `key = 12.5` / `key = true` / `key = false`
- `key = ["a", "b"]`（字符串数组，v1 只需字符串元素）
- `key = { a = "b" }`（inline table，v1 只需一层，用于 `env = {...}`）
- `#` 注释
- 不支持：datetime、multiline strings、hex/oct/bin 整数、花哨空白

## 文件清单

- `src/toml.sla`：TOML 子集解析器 → 输出 flat key-value（dotted key → value）
- `src/config_layers.sla`：层发现（路径）+ per-key merge + profile 应用
- `src/config.sla`：`mini_config_load()` 改走分层（env 保持最高优先级）
- 向后兼容：`~/.scodex-mini/config.json` 仍读（deprecated 警告），`SCODEX_*` env 不变

## 验收

- `~/.scodex-mini/config.toml` 生效
- `./.scodex-mini/config.toml` 覆盖 user 层
- `--profile fast` 切换 model（或 `SCODEX_PROFILE` env）
- `sa sla check` 通过（LLVM 恢复后补测 build）
