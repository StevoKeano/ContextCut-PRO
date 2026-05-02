curl -fsSL https://raw.githubusercontent.com/StevoKeano/ContextCut/main/install.sh -o /tmp/install.sh
chmod +x /tmp/install.sh
bash /tmp/install.sh

ContextCut installer
Stop wasting tokens. Inject only what matters.
──────────────────────────────────────────────

Voyage AI API key (from dash.voyageai.com): pa-zzzzzzzzzz-zzzzzzzzzz-zzzzzzzzzz-zzzz-zzzzzz
Ollama host [localhost]: 192.168.1.101
Ollama port [11434]:
Qdrant host [localhost]:
Qdrant port [6333]:
Path to your markdown knowledge base [/home/steve/contextcut/knowledge]: /home/steve/md
Proxy port [18788]:
Dashboard port [18787]:
Model context limit [8192]:
Minimum relevance score 0.0-1.0 [0.30]:

Installing to /home/steve/contextcut ...
Checking Qdrant at localhost:6333 ...
Qdrant found.
Creating Python virtual environment...
Installing Python dependencies...
tiktoken installed (exact token counts)
Downloading ContextCut scripts...
Linux: starting services now...
ContextCut started. Dashboard: http://localhost:18787

Running initial knowledge base ingest...
(this may take a while — Voyage AI free tier: 1 file per 21s)

[*] Ingesting 12 files from /home/steve/md ...
[contextcut] Dashboard → http://localhost:18787 (Chat + Monitor tabs)
[contextcut] Proxy → http://127.0.0.1:18788 → http://192.168.1.101:11434
[contextcut] Qdrant → localhost:6333 / contextcut
[contextcut] Min score → 0.3 Top-K → 5 CTX → 8192
[contextcut] Tokens → tiktoken (exact)
[ok] laymans.md
^[[A [ok] karpathy_autoresearch_use_cases.md
[ok] SKILL.md
[ok] IDENTITY.md
[ok] GUARDRAILS.md
[ok] CHANGES.md
[ok] AGENTS.md
[ok] USER.md
[ok] SOUL.md
[ok] TOOLS.md
[ok] BOOTSTRAP.md
[ok] HEARTBEAT.md
[*] Done.

ContextCut installed successfully!

Dashboard: http://localhost:18787
Proxy: http://localhost:18788
KB dir: /home/steve/md
Logs: /home/steve/.contextcut/logs

Test it:
curl -X POST http://localhost:18788/v1/chat/completions \
 -H 'Content-Type: application/json' \
 -d '{"messages":[{"role":"user","content":"hello"}],"model":"your-model-name"}'

Add .md files to /home/steve/md and they will be auto-ingested.
