# scodex-mini — SLA-native Codex mini (workspace mode)

Single-turn agent CLI written in SLA, mirroring the Rust `codex-min` behavior:
prompt -> POST `https://api.openai.com/v1/responses` -> print text ->
execute `shell_exec` tool calls -> loop until done (max 8 turns).

## Layout (workspace mode)

```
sa.mod                        workspace { members [...], default_member "codex-mini-cli" }
packages/
  codex-mini-config/          OPENAI_API_KEY / OPENAI_MODEL / OPENAI_BASE_URL env config
  codex-mini-protocol/        MiniEventKind / MiniToolCall / MiniTurnOutcome
  codex-mini-http/            plugin_abi/sa_http_client.sai + HTTPS POST adapter (TLS via http-client plugin)
  codex-mini-model/           Responses request JSON builder, response parser, turn loop
  codex-mini-tools/           shell_exec via sh -c with captured stdout
  codex-mini-cli/             main: argv -> prompt -> run turn
```

Cross-package imports use workspace package names
(`@import "codex-mini-config/src/config.sla"`), not relative `../../` paths.

## Build & run (pending)

```sh
export PATH="$HOME/.sa/bin:/opt/zig:$PATH"
export SA_STD_DIR="$HOME/.sa/std"
export SA_PLUGIN_DEV=1
cd ~/workspace/scodex-mini
sa sla check
sa sla build-exe --release-fast -o scodex-mini
OPENAI_API_KEY=... ./scodex-mini "what is 2+2"
```

## Status (2026-09-18)

- Workspace scaffolded, all 6 packages + 7 `.sla` sources written.
- Plugin ABI copied verbatim from `sa_plugin_http_client/sa_http_client.sai`.
- Deliberately **non-streaming** first cut: full response JSON via
  `sa_http_client_resp_body_slice`, parsed with `sa_std` JSON macros.
  SSE streaming (`resp_body_reader` + `read_chunk`) is the natural next step.
- `sa` itself currently cannot start on this VM (`libLLVM-14.so.1` missing
  after the system reset), so `sa sla check` / `build-exe` verification is
  blocked until the LLVM 14 runtime is reinstalled (needs user approval).
- The `.sla` sources were written against verified dialect patterns
  (`@import`, `@extern`, imported `[MACRO]`-as-function, `STR_PTR/STR_LEN`,
  `Vec<T>` methods, `while`, tuple destructuring) but have **not** been
  compiler-checked yet.
