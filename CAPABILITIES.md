# ContextCut PRO — Capabilities

ContextCut PRO is a local, transparent **semantic RAG proxy** that sits in front of any
OpenAI-compatible LLM (Ollama, OpenAI, OpenRouter, custom). It intercepts each request,
retrieves the most relevant chunks from a Qdrant knowledge base, and injects only the
chunks that score above a threshold — cutting token usage 50–90% with zero client changes.
It also ships an **Agent mode** (tool use), a dashboard, a headless coding worker, and a
two-agent coding orchestrator.

- Proxy: `http://localhost:18788/v1/chat/completions`
- Dashboard: `http://localhost:18787`

## Two ways to use it

1. **Normal chat (Agent OFF)** — plain LLM conversation with automatic RAG injection.
   No tools. Best for Q&A over your knowledge base.
2. **Agent mode (Agent ON)** — LangChain tool-use agent. Can run shell commands, read/write
   files, search the KB, run Python, plan, and remember. Tools run locally, no per-call cost.

`Scan`, `DEEP`, `TypeSafe`, `Unattended`, and `OpenCode` are independent toggles on top of
either mode.

## Dashboard controls

| Control | Effect |
|---|---|
| **Scan ON/OFF** | A secondary LLM grades factual claims (correct/uncertain/incorrect) and highlights suspects. In Agent mode, enables one self-correction retry on LOW confidence. |
| **DEEP** | Replaces the simple scan with a sub-agent verifier that checks claims against the Qdrant KB (evidence-backed). Requires `deepagents`. |
| **🛡 TypeSafe** | Routes scanning to the TypeSafe.ai cloud verifier (requires `TYPESAFE_API_KEY`). |
| **Agent ON/OFF** | Enables tool-use mode. |
| **Unattended** | Auto-approves shell commands, skipping Allow/Deny. |
| **Model** | Model name used for chat/agent (e.g. `qwen3:14b-q8_0`). |
| **Workspace** | Directory that relative agent file paths and `run_python`/`shell_exec` use as `cwd`. |
| **⌨ OpenCode** | Routes agent turns through `opencode run --agent build` in the workspace. |

## Knowledge base (RAG)

- Files live in `CONTEXTCUT_KB_DIR` (default `~/contextcut/knowledge`).
- The watcher (`ingest.py --watch`) auto-ingests changed files. Supported: `.md`, `.txt`,
  `.py`, `.js`, `.ts`, `.html`, `.css`, and more (see `ALLOWED_EXT` in `ingest.py`).
- Upload via the dashboard File Browser, or drop files into the KB directory.
- Retrieval: `CONTEXTCUT_TOP_K` (default 5) chunks with score ≥ `CONTEXTCUT_MIN_SCORE`
  (default 0.50). Below threshold → nothing injected.
- Tune retrieval with `python ingest.py --query "your typical query"`.
- Embeddings: Voyage AI (`VOYAGE_API_KEY`) or local Ollama embeddings.

## Agent tools

Local, zero per-call cost. High-impact tools pause for Allow/Deny approval.

| Tool | Purpose |
|---|---|
| `shell_exec` | Run allowlisted shell commands (argv, `shell=False`). |
| `read_file` / `write_file` / `append_file` / `diff_files` / `list_dir` | File operations jailed to the workspace. |
| `vector_search` | Search the Qdrant KB directly. |
| `web_search` / `fetch_url` | DuckDuckGo search and SSRF-guarded URL fetch. |
| `run_python` / `run_sql` | Execute Python and SQL. |
| `ingest_file` / `list_knowledge` / `delete_knowledge` | Manage KB contents. |
| `system_info` / `get_context_logs` / `get_session_stats` | System and session introspection. |
| `plan` | Structured multi-step planning. |
| `remember` / `recall` / `forget` | Persistent memory. |
| `compose_tool` | Define a new compound tool at runtime, callable on later turns. |

Tools are extendable at runtime: `run_python`, `shell_exec`, and `compose_tool` let the
agent generate code and new tools on the fly.

## Coding with ContextCut

Three ways to code with it:

1. **Dashboard Agent mode** — turn Agent ON, set the **Workspace**, then ask for changes.
   Use `plan` for multi-step work. Optionally enable **⌨ OpenCode** to route turns through
   `opencode run`.
2. **Headless coding worker** — `coding_agent.py` runs a bounded tool loop against any
   OpenAI-compatible endpoint, independent of the dashboard:
   ```bash
   ~/contextcut/venv/bin/python coding_agent.py --workspace ~/dev/sandbox \
     "add a test for the parse_date helper and run it"
   ```
   Flags: `--model`, `--reasoning {auto,none,low,medium,high,default}`, `--json`,
   `--resume <run_id>`, `--dry-run`. Runs are logged to `~/.contextcut/coding_runs/<run_id>/`.
3. **Two-agent orchestrator** — `orchestrator.py` runs an implementer plus a verifier with
   deterministic gates and a git baseline:
   ```bash
   ~/contextcut/venv/bin/python ~/contextcut/orchestrator.py \
     --workspace /tmp/project --prompt-file /tmp/prompt.txt \
     --implementer-model qwen3-coder:30b --verifier-model qwen3:14b-q8_0 \
     --check-command "python3 verify.py index.html" --json
   ```
   `--mode verify` re-audits without re-running the implementer. `--use-opencode` routes
   agent turns through OpenCode (`--agent build` / `--agent plan`).

The worker/orchestrator jail file tools to `--workspace` and run commands via an
executable allowlist. Point `--workspace` at a throwaway directory when using an untrusted model.

## Reliability features

- **Checkpoints** — every agent tool call is saved to `~/.contextcut/checkpoints/{task_id}/{step}.json`.
  The dashboard shows a Task badge; click **↩ Resume** or type `/resume <task_id>` to continue
  without redoing work. Stale checkpoints (>24h) are purged on startup.
- **Memory** — `remember` / `recall` / `forget` persist facts across sessions.
- **Untrusted-content hygiene** — tool output, retrieved chunks, web pages, and diffs are
  wrapped in `<<<UNTRUSTED_BEGIN ...>>>` boundaries and secret-looking values redacted.
- **Security alerts** — suspicious untrusted content is logged to
  `~/.contextcut/security_alerts.jsonl` and surfaced in the dashboard.

## MCP knowledge server

Expose the KB over the Model Context Protocol (Claude Desktop, Cursor, VS Code):

```bash
cd ~/contextcut && set -a; . ./.env; set +a
venv/bin/python mcp_knowledge_server.py --transport http --port 8910
```

Tools: `knowledge_search`, `knowledge_search_structured`, `knowledge_list_files`,
`knowledge_stats`, `ingest_file`, `ingest_all`, `ingest_status`.

## Key configuration

| Variable | Default | Purpose |
|---|---|---|
| `CONTEXTCUT_UPSTREAM` | `http://localhost:11434` | LLM endpoint |
| `CONTEXTCUT_MODEL` | `qwen3:14b-q8_0` | Default chat/agent model |
| `CONTEXTCUT_CTX_LIMIT` | `32768` | Context window (match the model's `num_ctx`) |
| `CONTEXTCUT_TOP_K` | `5` | Chunks retrieved |
| `CONTEXTCUT_MIN_SCORE` | `0.50` | Relevance threshold |
| `CONTEXTCUT_KB_DIR` | `~/contextcut/knowledge` | Knowledge base directory |
| `CONTEXTCUT_SCAN_MODEL` | _(unset)_ | Separate model for confidence scan (must differ from agent model) |
| `CONTEXTCUT_AGENT_WORKSPACE` | proxy dir | Agent working directory |
| `CONTEXTCUT_TOOL_OUTPUT_MAX_CHARS` | `4000` | Tool-output clamp |
| `CONTEXTCUT_READ_FILE_OUTPUT_MAX_CHARS` | `12000` | `read_file` clamp |
| `CONTEXTCUT_TOOL_TURN_REASONING` | `low` | Reasoning effort on tool-result turns |
| `CONTEXTCUT_TOOL_TURN_MAX_TOKENS` | `8192` | Max tokens on tool-result turns |
| `CONTEXTCUT_USE_OPENCODE` | `0` | Route agent turns through OpenCode |

## Adding knowledge

- Drop supported files into `~/contextcut/knowledge/` (the watcher ingests changes), or
- Upload through the dashboard **File Browser**, or
- In Agent mode, call `ingest_file("<filename>")`.

## Run / restart

```bash
cd ~/contextcut
./start.sh                 # start proxy + watcher
./stop.sh && ./start.sh    # restart after .env or code changes
```

For more detail, see `README.md` (full docs), `USER_GUIDE.md`, and `CUSTOMER_SETUP.md`.
