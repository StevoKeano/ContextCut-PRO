# Agent Instructions

## Restart Policy
- After making code changes, ASK the user to restart the proxy.
- Do NOT kill or restart the proxy automatically.
- The user runs `./start.sh` and `./stop.sh` manually.

## Key Files
- `qdrant_proxy_final.py` — main PRO server (dashboard + proxy in one file)
- `agent_handler.py` — LangChain agent tools
- `cc-free.py` — free edition
- `ingest.py` — Qdrant file watcher + ingester

## Config
- `.env` overrides defaults in `qdrant_proxy_final.py`
- `CONTEXTCUT_MODEL` — chat model (default `qwen3:14b-q8_0`)
- `CONTEXTCUT_CTX_LIMIT` — context window (default 32768, now 16384)

## Fullscreen Behavior
- When shell_exec permission is requested (Allow/Deny), the code auto-exits fullscreen mode and scrolls to show the buttons.
- Fullscreen toggle: `.right` element gets/removes `fullscreen` class.

## Ollama
- Runs on Windows at `http://192.168.137.1:11434`
- Custom model `qwen2.5-coder:14b-16k` with `PARAMETER num_ctx 16384` created via Modelfile
