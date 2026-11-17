# Agent Instructions

## Workflow
- Edit files in `~/dev/ContextCut-PRO/` (workspace, git repo)
- After editing, `cp` changed files to `~/contextcut/` (deployed directory)
- Do NOT edit `~/contextcut/` files directly — edit workspace, then copy

## Restart Policy
- After making code changes, ASK the user to restart the proxy.
- Do NOT kill or restart the proxy automatically.
- The user runs `./start.sh` and `./stop.sh` manually.

## Key Files
- `qdrant_proxy_final.py` — main PRO server (dashboard + proxy in one file)
- `agent_handler.py` — LangChain agent tools + checkpoint system
- `capabilities.py` — self-knowledge: capabilities doc loader, always-on blurb, meta-question router
- `CAPABILITIES.md` — user-facing capabilities/usage doc (single source of truth for self-knowledge)
- `cc-free.py` — free edition
- `ingest.py` — Qdrant file watcher + ingester

## Config
- `.env` overrides defaults in `qdrant_proxy_final.py`
- `CONTEXTCUT_MODEL` — chat model (default `qwen3:14b-q8_0`)
- `CONTEXTCUT_CTX_LIMIT` — context window (default 32768, now 16384)
- `CONTEXTCUT_SCAN_MODEL` — separate model for confidence scan (default: unset = disabled).
  Must be different from the agent model to avoid self-evaluation.
  E.g. `qwen3:4b` or `llama3.2:1b-instruct-q4_K_M`

## Context Tuning
- `ContextTuningMiddleware` (`agent_handler.py`) head+tail clamps tool output and shrinks the model call that follows a tool result.
- `CONTEXTCUT_TOOL_OUTPUT_MAX_CHARS` — default tool output clamp (default 4000; 0 disables)
- `CONTEXTCUT_READ_FILE_OUTPUT_MAX_CHARS` — `read_file` clamp (default 12000)
- `CONTEXTCUT_SEARCH_OUTPUT_MAX_CHARS` — `vector_search` clamp (default 6000)
- `CONTEXTCUT_TOOL_TURN_REASONING` — reasoning effort on tool-result turns (default `low`; `off` disables; skipped for Ollama)
- `CONTEXTCUT_TOOL_TURN_MAX_TOKENS` — `max_tokens` cap on tool-result turns (default 8192; 0 disables)


## Self-Knowledge (capabilities)
- Single source of truth: `CAPABILITIES.md`; loaded by `capabilities.py` (`capabilities_text()`, cached).
- Always-on: `CAPABILITIES_BLURB` is appended to the agent system prompt (`get_system_prompt()`)
  and to normal-chat `SYSTEM_BASE` (`qdrant_proxy_final.py`).
- On-demand: agent tool `contextcut_help()` returns the full doc; `is_meta_question()` in
  `capabilities.py` routes meta questions to a trusted capabilities block in `inject_context()`
  (normal chat) and in the `/api/agent` path.
- Deep-dive RAG: `ContextCut_README.md`, `ContextCut_USER_GUIDE.md`, `ContextCut_CUSTOMER_SETUP.md`
  are ingested into the KB under distinct filenames (the KB's own `README.md` is unrelated).

## Fullscreen Behavior
- When shell_exec permission is requested (Allow/Deny), the code auto-exits fullscreen mode and scrolls to show the buttons.
- Fullscreen toggle: `.right` element gets/removes `fullscreen` class.

## Ollama
- Runs on Windows at `http://192.168.137.1:11434`
- Custom model `qwen2.5-coder:14b-16k` with `PARAMETER num_ctx 16384` created via Modelfile

## Checkpoint System

Every agent tool invocation is checkpointed to disk at `~/.contextcut/checkpoints/{task_id}/{step}.json`.

### Resume After Crash
1. The dashboard shows a **Task:** badge with the current task_id after each agent run.
2. Click **↩ Resume** to auto-fill `/resume <task_id>` or type it manually.
3. On resume, the server injects prior step results as a system message so the agent continues where it left off without re-doing work.

### Dashboard Routes
- `GET /api/checkpoints` — list all task_ids with checkpoint data
- `GET /api/checkpoints/{task_id}` — step details, resume token estimate

### Retention
- Stale checkpoints (>24h) are purged on proxy startup.
- The `CheckpointManager.cleanup(max_age_hours=24)` method can be called ad-hoc.

### Tests
- Unit: `tests/test_checkpoints.py` (23 tests, always run)
- Live: `tests/test_integration.py::TestLiveCheckpointIntegration` (4 tests, `--live` flag)
