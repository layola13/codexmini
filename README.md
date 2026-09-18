# scodex-mini — SLA-native Codex mini (workspace mode)

Single-turn agent CLI written in SLA, mirroring the Rust `codex-min` behavior:
prompt -> POST `https://api.openai.com/v1/responses` -> print text ->
execute `shell_exec` tool calls -> loop until done (max 8 turns).

Conversations are persisted per session via the `db` plugin (`sa_plugin_db`,
no SQLite): every run creates a session, all turns (user / assistant /
tool calls / tool outputs) are stored, and sessions can be listed and resumed.

## Layout

```
sa.mod                        workspace { members [...], default_member "codex-mini" }
packages/
  codex-mini/src/
    config.sla                OPENAI_API_KEY env config
    protocol.sla              MiniEventKind / MiniToolCall / MiniTurnOutcome
    http.sla                  plugin_abi/sa_http_client.sai + HTTPS POST adapter
    model.sla                 Responses request/response, turn loop, session DB
    tools.sla                 shell_exec via sh -c with captured stdout
    main.sla                  CLI: argv -> prompt / --list / --resume
    sessionx.sa               session DB macros (DB path, row encoding)
    plugin_abi/db.sai         sa_plugin_db FFI signatures
db_api_guide.md               sa_plugin_db calling conventions (probed, verified)
e2e/mock_responses.py         plain-HTTP mock of /v1/responses for local testing
```

## Usage

```sh
export PATH="$HOME/.sa/bin:/opt/zig:$PATH"
export SA_STD_DIR="$HOME/.sa/std"
export SA_PLUGIN_DEV=1

# new session (creates session, saves every turn)
OPENAI_API_KEY=... scodex-mini "what is 2+2"

# list sessions (no API key needed)
scodex-mini --list
#   session id=1 msgs=4 updated_ms=1789744779005
#   what is 2+2

# resume session 1 with a follow-up prompt
OPENAI_API_KEY=... scodex-mini --resume 1 "and what is 3+3"
```

## Session persistence

- Storage: `$HOME/.scodex-mini/db` (created automatically; never committed).
- Tables: `sessions(id, created_ms, updated_ms, msg_count, title_blob)`,
  `messages(session_id, seq, role, body_blob)`.
- Roles: 0=user, 1=assistant, 2=function_call (`{"call_id","name","args"}`),
  3=function_call_output (`{"call_id","output"}`).
- `--resume` replays history in `seq` order (user → assistant →
  function_call → function_call_output); a corrupt tool-call record aborts
  with an explicit error instead of silently dropping history.

## Build & run

```sh
export PATH="$HOME/.sa/bin:/opt/zig:$PATH"
export SA_STD_DIR="$HOME/.sa/std"
export SA_PLUGIN_DEV=1
cd ~/workspace/scodex-mini
sa sla check
sa sla build-exe --release-fast -o scodex-mini
OPENAI_API_KEY=... ./scodex-mini "what is 2+2"
```

## Local E2E test (mock)

`e2e/mock_responses.py` is a plain-HTTP mock of the Responses API
(first request → one `shell_exec` call, then final text). Build a test-only
binary with the URL pointed at the mock (never commit that change):

```sh
python3 e2e/mock_responses.py &  # 127.0.0.1:8080
# in a scratch copy of the repo: point mini_model_build_url at
# http://127.0.0.1:8080/v1/responses and use_tls=0 in http.sla, then build
rm -rf ~/.scodex-mini
OPENAI_API_KEY=fake ./scodex-mini-e2e "hello"   # tool loop, exit 0
./scodex-mini-e2e --list                        # session id=1 msgs=4
OPENAI_API_KEY=fake ./scodex-mini-e2e --resume 1 "again"  # history replayed
```

## Status (2026-09-18)

- Session persistence implemented on `feature/session-persistence`:
  `sa_plugin_db`-backed sessions, `--list` (no key), `--resume <id>`,
  JSON-blob tool history with strict resume parsing.
- Full mock E2E verified: create → tool call → `--list` → `--resume` →
  history replayed in order (`user,function_call,function_call_output,
  assistant,user`), exit 0.
- Deliberately **non-streaming**: full response JSON parsed with
  `sa_std` JSON macros. SSE streaming is the natural next step.
