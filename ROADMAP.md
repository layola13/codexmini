# scodex-mini Roadmap：对比 codex 补齐清单

> 2026-09-20 立项。比较对象：完整版 Codex CLI（codex-min 拆解版主动砍掉的部分不算差距）。
> 定位约束：scodex-mini 是"证明 SLA 能写大型项目"的载体，不是 codex 克隆。

## P0（必答题）

### 1. 沙箱
- **现状**：裸跑 shell，无任何隔离。跑不受信任任务 = 裸奔。
- **目标**：Linux landlock / seccomp 基础沙箱：默认禁止出 workspace 写、禁止 raw socket，显式 allowlist 放行。
- **验收**：`--dangerously-skip-sandbox` 显式关闭才裸跑；默认沙箱下恶意 prompt 要求写 `~/.ssh` 被拒绝并记录。
- **工作量**：中（sa_std 或插件层加 landlock 封装，SLA 侧策略 DSL）。

### 2. 上下文管理（compaction）
- **现状**：`--resume` 全量重放历史，token 随会话线性增长，长会话必炸窗口。
- **目标**：token 预算 + 自动摘要压缩：超阈值时对旧 turn 做摘要，保留工具调用结果摘要，prompt 显式标注"以下是压缩摘要"。
- **验收**：200 turn 会话 resume 后 prompt token < 32k 且关键决策不丢失（抽查 3 个长会话）。
- **工作量**：中（摘要策略 + DB 里存 turn 摘要字段）。

### 3. 工具生态：apply_patch
- **现状**：工具调用是通用本地执行，无代码专用的 patch 语义。
- **目标**：`apply_patch` 语义：fuzz 匹配、diff 预览、失败时报错行号、多 hunk 原子应用。
- **验收**：scodex-mini 自身源码级改动走 apply_patch 全绿；与 `sa sla check` 联动做 patch 后语法校验。
- **工作量**：中大（纯 SLA 实现，正好是 sla-fmt 之后第二个"纯 SLA 证明件"）。

### 4. MCP client 与 AGENTS.md（agent 层插件系统）
- **现状**：agent 层扩展接口全无。SA 插件系统解决的是 runtime 能力扩展，这一层解决的是 agent 行为扩展，两层正交。
- **目标**：先 MCP client（stdio）：tool list/call 走现有工具调用链路；再 AGENTS.md 自动读取注入 system prompt；skills（prompt 包）按目录约定加载。
- **验收**：接一个真实 MCP server（如 filesystem）跑通 list/call；仓库根有 AGENTS.md 时行为可观察变化。
- **工作量**：中。

## P1（加分项）

### 5. 配置体系
- **现状**：基础 config（JSON 单文件 + env），无分层。
- **目标**：学 codex 的 `config.toml`，路径用自己的：system（`/etc/scodex-mini/config.toml`）→ user（`$SCODEX_HOME/config.toml`，默认 `~/.scodex-mini/`）→ project（`./.scodex-mini/config.toml` + 父目录向上）→ profile（`--profile` / `SCODEX_PROFILE`，`[profiles.<name>]` + `$SCODEX_HOME/profiles/<name>.toml`）→ runtime（`SCODEX_*` env 最高优先级，向后兼容）。
- **实现**（2026-09-20）：`src/toml.sla`（纯 SLA TOML 子集解析器）+ `src/config_layers.sla`（分层发现/per-key merge/profile 应用）+ `config.sla` 接入 + `main.sla` 加 `--profile` 参数。
- **验收**：`~/.scodex-mini/config.toml` 生效、项目级覆盖、`--profile` 切换 model 可验证、`sa sla check` 通过。
- **工作量**：小中。

### 6. 分发打包：LLVM 依赖解耦
- **现状**：`sa` 二进制动态链接 `libLLVM-14.so.1`（sci 的 `--release-fast` 后端经 LLVM-C 实时做优化/生成 object，`src/emit_llvm_llvmc.zig`）；目标机器没装 LLVM 14 则 `sa` 直接起不来。VM 重启丢 apt 包已坏过两次。
- **目标**：三选一（需实测定）：随包带 libLLVM 动态库 / 把 LLVM 静态链进 `sa` / dlopen 按需加载＋无 LLVM 时降级。另：Windows 默认关 LLVM 也能用，说明存在非 LLVM 路径，先搞清它的 build-exe 覆盖度与性能代价。
- **验收**：干净机器（docker）从零 install 到 `sa sla build-exe --release-fast` 跑通，全程无 apt。
- **工作量**：中。
- **备注**：这是工具链税，不是产品二进制税——scodex-mini 产品二进制仍 ~1.5MB；rustup 也一样，工具链和产品是两本账。

### 7. TUI 应用框架（基于已有 sa_plugin_tui）
- **现状**：终端底层插件已存在（`sa_plugin_tui` v0.1.0：tui.terminal/tui.input/tui.ansi）；SLA 有闭包（Sala 文档有说明）。缺的是 SLA 侧的 Elm 式应用框架层。
- **目标**：bubbletea 式的通用 TUI 应用框架（纯 SLA，基于 sa_plugin_tui）：Model-Update-View 循环、差分渲染、键盘/鼠标事件；scodex-mini 自身保持 headless，只做框架的第一个用户。
- **前置 spike**：盘点插件现有能力与缺口；在插件之上用 SLA（含闭包）原型验证框架层写起来顺不顺手——啰嗦到不可接受就停。
- **验收**：spike 通过后，框架跑起一个可交互 demo（含文本输入框/列表选择）。
- **工作量**：spike 小；完整框架中（插件缺口回填另计）。

## P2（长期功课）

### 8. HTTP 链路：curl 子进程 → 原生
- **现状**：每请求 fork curl，稳定但重，高频调用有延迟税。
- **目标**：http-client 插件内原生连接池 + keep-alive（复用 sa_plugin_http_server 的线程池经验）。
- **验收**：同等 SSE 场景 p50 延迟下降，`--resume` 高频小请求场景可量化对比。
- **工作量**：大（插件层重构）。

### 9. 底座可信度
- **现状**：SLA 工具链仍在还技术债（`\xHH` 长度、FFI 传参约定等坑）。
- **目标**：scodex-mini 自身作为 SLA 最大的 dogfood 项目：每次 SLA 工具链升级先跑 scodex-mini 全量 E2E。
- **验收**：E2E 套件进 CI（或定时任务），工具链回归先报警。
- **工作量**：持续。

## 非目标
- TUI / 审批流：mini 定位主动不要，不做。
- 逐 API 对齐 codex：不追，选稳定子集。
