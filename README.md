## Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/StevoKeano/ContextCut/main/install.sh -o /tmp/install.sh
chmod +x /tmp/install.sh
bash /tmp/install.sh
```

# ContextCut

**Stop wasting tokens. Inject only what matters.**

ContextCut is a transparent semantic RAG proxy for Ollama, OpenClaw, and any OpenAI-compatible local LLM endpoint. Drop it in front of your LLM — zero application changes required.

---

## Why ContextCut

Most RAG implementations stuff your entire knowledge base into every prompt. ContextCut uses vector similarity to inject **only the chunks that are actually relevant** to each query — and skips injection entirely when nothing scores above your threshold.

| Query                      | Without ContextCut       | With ContextCut               |
| -------------------------- | ------------------------ | ----------------------------- |
| "What are the guardrails?" | 3,000+ tokens (all docs) | 806 tokens (1 relevant chunk) |
| "Explain quantum physics"  | 3,000+ tokens (junk)     | ~5 tokens (nothing relevant)  |

**Result: 50–90% token reduction on real workloads.**

---

## How it works

```
Your app → ContextCut proxy :18788 → [Qdrant semantic search] → Ollama :11434
                    ↓
           Dashboard :18787 (real-time token usage)
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

## Install (macOS / Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/StevoKeano/ContextCut/main/install.sh | bash
```

The installer will ask for:

- Voyage AI API key
- Ollama host/port
- Qdrant host/port
- Path to your markdown knowledge base
- Proxy and dashboard ports

On macOS, services are registered as launchd agents and start automatically on login.  
On Linux, a `start.sh` script is generated.

---

## Manual install

```bash
git clone https://github.com/StevoKeano/ContextCut
cd ContextCut
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

---

## Ingest tool

```bash
python ingest.py                         # one-shot ingest all .md files
python ingest.py --watch                 # ingest then watch for file changes
python ingest.py --query "guardrails"    # test semantic search
python ingest.py --clear                 # wipe collection and start fresh
```

Files matching `EXCLUDE_FILES` or containing `.bak-` in the name are skipped automatically.

> **Note:** Voyage AI free tier allows ~3 RPM. A 21-second delay is added between embeds to stay within limits. Upgrade to a paid plan to remove this delay.

---

## Dashboard

Open `http://localhost:18787` to see:

- Real-time context usage bar (green → yellow → red)
- Per-request token counts (before and after injection)
- Qdrant hit sources and relevance scores
- Peak and average token usage

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

## License

MIT — Built for homelab power users.
