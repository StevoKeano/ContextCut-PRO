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

## Local Diffusion (separate GPU worker)
- `diffusion/worker.py` runs on the Windows RTX 4090 host in native Windows Python (`Z:\contextcut\diffusion-venv`), not on Ubuntu; stdlib `http.server` binds `DIFFUSION_HOST:DIFFUSION_PORT` (default `0.0.0.0:8189`).
- Ubuntu proxy setting `DIFFUSION_WORKER_URL` must be `http://192.168.137.1:8189`; `DIFFUSION_ENABLED` (default true) is editable under Settings → LLM Provider.
- Remote workers return absolute image URLs (`http://192.168.137.1:8189/outputs/images/<name>`); override with `DIFFUSION_IMAGE_BASE_URL`. The worker serves those files from its own `DIFFUSION_OUTPUT_DIR` (default `.\outputs\images`).
- Worker-side `DIFFUSION_PUBLIC_HOST` controls the host in generated URLs (default `127.0.0.1`; Windows start script sets `192.168.137.1`).
- `DIFFUSION_IDLE_TIMEOUT` (default 300s) unloads the single active pipeline when idle and no generation lock is held.
- Before image requests the proxy evicts all loaded Ollama models; before any LLM chat/completion request (including agent turns) it calls `POST /internal/unload`. Both now act on the same Windows 4090.
- Settings → LLM Provider has a Test Worker button (`GET /api/diffusion/test?url=...`) that probes `/health` from the proxy host; dashboard chat renders `/outputs/images/*.png` inline when the URL origin is the proxy or configured image base.
- Image tool calls show an indeterminate progress card in dashboard chat (model, prompt, elapsed timer); worker-driven real step progress is deferred.
- Worker `/health` samples `nvidia-smi` every 5s (`DIFFUSION_GPU_SAMPLE_INTERVAL`) for GPU util/memory/temp/power; dashboard polls `/api/diffusion/status` every 5s during image generation.
- Scripts: PowerShell `install-diffusion.ps1` (admin; one combined `pip install` with matched `torch`/`torchvision` cu126 pair plus unpinned diffusers stack, CUDA assert + import smoke test, `pip freeze > requirements-diffusion.lock.txt`, inbound firewall rule for TCP 8189 from `192.168.137.0/24`), `start-diffusion.ps1`, `stop-diffusion.ps1`. Stop falls back to a command-line/port scan when the PID file is stale; start checks port 8189 before launching, waits for a Python worker process to own that port instead of probing HTTP (the first `nvidia-smi` sample can be slow), and rewrites the PID file to the actual owner. Python 3.13.5 is supported. Linux bash scripts remain for local/WSL use.
- Stage 1 model keys: `z-image-turbo`, `flux2-klein`, `flux1-dev`, `flux1-kontext`, `auto`; FP8 single-file, GGUF, and other quantized variants are intentionally out of scope.
- `flux1-dev` is a hidden manual override: excluded from worker `/health` and `/v1/models` lists and from agent tool guidance, but still accepted when explicitly passed as `model="flux1-dev"`. It loads with `enable_sequential_cpu_offload()` because full bfloat16 weights do not fit in 24GB VRAM.
- Worker `DIFFUSION_MODEL_ROOT` (default `Z:\contextcut\models\official`, set by `start-diffusion.ps1`) points to self-contained diffusers directories; a missing directory falls back to the HF repo ID.
- Worker `DIFFUSION_AUTO_TEXT_MODEL`, `DIFFUSION_AUTO_EDIT_MODEL`, `DIFFUSION_AUTO_INPAINT_MODEL`, and `DIFFUSION_AUTO_MULTIREF_MODEL` override `auto`; defaults are text/inpaint `z-image-turbo`, edits/multi-reference `flux2-klein`.
- Proxy `diffusion_client.model_ids()` caches worker `/v1/models` for 30s so dashboard and `/v1/models` lists follow the worker without code edits; fallback list is used if the worker is offline.

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

## Approval (HITL)
- The approval list is defined in exactly one place: `HumanInTheLoopMiddleware(interrupt_on=...)`
  in `build_agent()` (`agent_handler.py`). There is no `.env` var or second definition.
- Tools that pause for Allow/Deny: `shell_exec`, `content_write`, `publish_content`,
  `delete_knowledge` (all `allowed_decisions: ["approve", "reject"]`).
- `run_python`, `write_file`, and `append_file` do NOT prompt.
- `_shell_is_safe()` (`agent_handler.py`) + `agent_policy.py` are an extra safety gate that
  applies only to `shell_exec`, independent of the approval list.
- The dashboard **Unattended** toggle sets `shell_confirm_mode="always"`, which auto-approves
  ALL HITL actions (not just shell). Default is `ask`.
- `content_write`/`publish_content` come from `aeo/tools.py` (added via `build_agent(extra_tools=...)`).

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
