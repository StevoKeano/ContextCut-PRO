# ContextCut-PRO

**Stop wasting tokens. Inject only what matters.**

ContextCut-PRO is the commercial edition of ContextCut — a transparent semantic RAG proxy for Ollama, OpenClaw, and any OpenAI-compatible local LLM endpoint. Drop it in front of your LLM — zero application changes required.

---

## Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/StevoKeano/ContextCut/main/install.sh -o /tmp/install.sh
chmod +x /tmp/install.sh
bash /tmp/install.sh
```

---

## What's New in PRO

### Dashboard

- **Split-panel layout** — live stats monitor on the left, full chat interface on the right, single page, no tabs
- **Real-time left panel polling** — stats cards, context bar, and request table update every 3 seconds without page reload or losing chat history
- **Integrated chat window** — send messages directly from the dashboard, answers stream in word-by-word
- **Ollama model DDL** — dropdown auto-populates from your Ollama instance on page load, pick any available model or type one manually
- **Per-message stat pills** — each assistant response shows CTX%, prompt tokens, completion tokens, tokens saved, and chunks injected inline

### Proxy

- **MIN_SCORE threshold filtering** — chunks below the configured relevance score are silently skipped, keeping context lean and on-topic
- **Token injection tracking** — before/after token counts recorded per request, total tokens saved tracked across session
- **`/api/tags` passthrough** — dashboard proxies Ollama model list so the DDL works without CORS issues
- **`/log` endpoint** — full request log available as JSON for live polling and external tooling
- **Threaded server** — `ThreadingMixIn` handles concurrent dashboard + proxy requests without blocking
- **Graceful Qdrant errors** — Voyage AI or Qdrant failures are caught per-request; proxy continues serving even if vector search is unavailable

### Ingest

- **`.bak-` file exclusion** — backup files are automatically skipped during ingest and watch mode, keeping the collection clean
- **Voyage AI rate limit handling** — 21-second inter-embed delay respects free tier 3 RPM limit; configurable for paid plans
- **Startup validation** — exits cleanly with actionable error if `VOYAGE_API_KEY` or `KB_DIR` are missing

---

## Why ContextCut

Most RAG implementations stuff your entire knowledge base into every prompt. ContextCut uses vector similarity to inject **only the chunks that are actually relevant** to each query — and skips injection entirely when nothing scores above your threshold.

| Query                      | Without ContextCut       | With ContextCut               |
| -------------------------- | ------------------------ | ----------------------------- |
| "What are the guardrails?" | 3,000+ tokens (all docs) | 806 tokens (1 relevant chunk) |
| "Explain quantum physics"  | 3,000+ tokens (junk)     | ~5 tokens (nothing relevant)  |

**Result: 50–90% token reduction on real workloads.**

![Dashboard](dashboard.png)

> Note: This is the local AI context optimizer for Ollama + Qdrant. There is another unrelated public repo with a similar name — this is the PRO edition.

---

## How it works

```
Your app → ContextCut proxy :18788 → [Qdrant semantic search] → Ollama :11434
                    ↓
           Dashboard :18787 (real-time token usage + chat)
```

1. Request arrives at the proxy
2. User message is embedded with Voyage AI (`voyage-3`)
3. Qdrant returns top-K chunks above `MIN_SCORE` threshold
4. Chunks are prepended to the system prompt
5. Enriched request is forwarded to Ollama (or any OpenAI-compatible endpoint)
6. Response returned to caller unchanged

---

## Requirements

- Python 3.10+
- [Voyage AI API key](https://dash.voyageai.com) (free tier works)
- [Qdrant](https://qdrant.tech) running locally or on your LAN
- Ollama or any OpenAI-compatible LLM endpoint

---

## Manual install

```bash
git clone https://github.com/StevoKeano/ContextCut-PRO
cd ContextCut-PRO
python3 -m venv venv
source venv/bin/activate
pip install voyageai qdrant-client watchdog tiktoken

# Set required env vars
export VOYAGE_API_KEY=your-key-here
export CONTEXTCUT_UPSTREAM=http://localhost:11434
export CONTEXTCUT_QDRANT_HOST=localhost
export CONTEXTCUT_KB_DIR=/path/to/your/markdown/files

# Ingest your knowledge base
python ingest.py

# Start the proxy + dashboard
python qdrant_proxy.py
```

---

## Configuration

All settings via environment variables:

| Variable                    | Default                  | Description                           |
| --------------------------- | ------------------------ | ------------------------------------- |
| `VOYAGE_API_KEY`            | _(required)_             | Voyage AI API key                     |
| `CONTEXTCUT_UPSTREAM`       | `http://localhost:11434` | Ollama or OpenAI-compatible endpoint  |
| `CONTEXTCUT_QDRANT_HOST`    | `localhost`              | Qdrant host                           |
| `CONTEXTCUT_QDRANT_PORT`    | `6333`                   | Qdrant port                           |
| `CONTEXTCUT_COLLECTION`     | `contextcut`             | Qdrant collection name                |
| `CONTEXTCUT_KB_DIR`         | `~/contextcut/knowledge` | Markdown knowledge base directory     |
| `CONTEXTCUT_PROXY_PORT`     | `18788`                  | Proxy listen port                     |
| `CONTEXTCUT_DASHBOARD_PORT` | `18787`                  | Dashboard port                        |
| `CONTEXTCUT_CTX_LIMIT`      | `8192`                   | Model context window (for % display)  |
| `CONTEXTCUT_TOP_K`          | `5`                      | Max chunks to retrieve from Qdrant    |
| `CONTEXTCUT_MIN_SCORE`      | `0.30`                   | Minimum relevance threshold (0.0–1.0) |
| `CONTEXTCUT_MODEL`          | _(empty)_                | Default model pre-filled in dashboard |

---

## Ingest tool

```bash
python ingest.py                          # one-shot ingest all .md files
python ingest.py --watch                  # ingest then watch for file changes
python ingest.py --query "guardrails"     # test semantic search
python ingest.py --clear                  # wipe collection and start fresh
```

Files matching `EXCLUDE_FILES` or containing `.bak-` in the name are skipped automatically.

> **Note:** Voyage AI free tier allows ~3 RPM. A 21-second delay is added between embeds to stay within limits. Upgrade to a paid plan to remove this delay.

---

## Dashboard

Open `http://localhost:18787` to see:

- **Left panel** — live stats cards, context usage bar, per-request token table with Qdrant hit sources and relevance scores. Updates every 3 seconds without page reload.
- **Right panel** — integrated chat window with model dropdown. Send messages, see streamed responses, and watch the left panel update in real time.

---

## Tuning MIN_SCORE

Run a test query and check the scores in the dashboard:

```bash
python ingest.py --query "your typical query"
```

- Scores above `0.35` — highly relevant, definitely inject
- Scores `0.20–0.35` — tangentially related, inject with caution
- Scores below `0.20` — noise, skip injection

Start at `0.30` and adjust based on your domain. Narrow technical domains score higher; general queries against a specialized KB score lower.

---

## Testing

A test suite is included to validate all proxy features:

```bash
bash test_proxy.sh
```

Tests cover: process health, port binding, Ollama reachability, Qdrant reachability, dashboard load, `/stats`, `/log`, `/api/tags` model list, proxy injection with token validation, streaming, MIN_SCORE threshold filtering, off-topic query suppression, context usage below 25%, and the full dashboard Send button path.

---

## License

ContextCut-PRO is licensed for **commercial use** under the ContextCut Pro License.

Free personal and educational use is available via the public [ContextCut](https://github.com/StevoKeano/ContextCut) repo.

**Pro License – $29.88 one-time per seat**

- Lifetime commercial usage rights
- Priority support
- Advanced context-cutting rules & presets
- Pro dashboard features (split-panel, live polling, model DDL, streaming chat)
- License key activation

[Buy Pro License →](https://5984630877416.gumroad.com/l/ContextCut-Pro)
