# Agent Instructions

## Restart Policy
- After making code changes, ASK the user to restart the proxy.
- Do NOT kill or restart the proxy automatically.
- The user runs `./start.sh` and `./stop.sh` manually.

## Key Files
- `qdrant_proxy_final.py` — main PRO server (dashboard + proxy in one file)
- `agent_handler.py` — LangChain agent tools + checkpoint system
- `cc-free.py` — free edition
- `ingest.py` — Qdrant file watcher + ingester

## Config
- `.env` overrides defaults in `qdrant_proxy_final.py`
- `CONTEXTCUT_MODEL` — chat model (default `qwen3:14b-q8_0`)
- `CONTEXTCUT_CTX_LIMIT` — context window (default 32768, now 16384)
- `CONTEXTCUT_SCAN_MODEL` — separate model for confidence scan (default: unset = disabled).
  Must be different from the agent model to avoid self-evaluation.
  E.g. `qwen3:4b` or `llama3.2:1b-instruct-q4_K_M`

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
