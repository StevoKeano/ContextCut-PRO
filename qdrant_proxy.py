#!/usr/bin/env python3
"""
ContextCut — Qdrant-enriching reverse proxy for any local LLM endpoint.

  Proxy port    (CONTEXTCUT_PROXY_PORT)     — receives requests, injects context, forwards to LLM
  Dashboard port (CONTEXTCUT_DASHBOARD_PORT) — real-time token usage and Qdrant hit viewer

Configuration via environment variables (all optional — defaults shown):
  CONTEXTCUT_UPSTREAM        http://localhost:11434   Ollama or any OpenAI-compatible endpoint
  CONTEXTCUT_QDRANT_HOST     localhost                Qdrant host
  CONTEXTCUT_QDRANT_PORT     6333                     Qdrant port
  CONTEXTCUT_COLLECTION      contextcut               Qdrant collection name
  CONTEXTCUT_PROXY_PORT      18788                    Proxy listen port
  CONTEXTCUT_DASHBOARD_PORT  18787                    Dashboard listen port
  CONTEXTCUT_CTX_LIMIT       8192                     Model context window size (for % display)
  CONTEXTCUT_TOP_K           5                        Max Qdrant chunks to retrieve
  CONTEXTCUT_MIN_SCORE       0.30                     Minimum relevance score (0.0-1.0)
  VOYAGE_API_KEY             (required)               Voyage AI API key

Install optional tiktoken for precise token counts:
  pip install tiktoken
Without it, falls back to a word-based estimate (±5%).

Usage:
  python qdrant_proxy.py
"""

import os
import json
import html
import time
import threading
import urllib.request
import urllib.error
from collections import deque
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

import voyageai
from qdrant_client import QdrantClient

# ── Config (all overridable via environment) ──────────────────────────────────
UPSTREAM        = os.getenv("CONTEXTCUT_UPSTREAM",        "http://localhost:11434")
QDRANT_HOST     = os.getenv("CONTEXTCUT_QDRANT_HOST",     "localhost")
QDRANT_PORT     = int(os.getenv("CONTEXTCUT_QDRANT_PORT", "6333"))
COLLECTION      = os.getenv("CONTEXTCUT_COLLECTION",      "contextcut")
LISTEN_PORT     = int(os.getenv("CONTEXTCUT_PROXY_PORT",     "18788"))
DASHBOARD_PORT  = int(os.getenv("CONTEXTCUT_DASHBOARD_PORT", "18787"))
CTX_LIMIT       = int(os.getenv("CONTEXTCUT_CTX_LIMIT",   "8192"))
TOP_K           = int(os.getenv("CONTEXTCUT_TOP_K",       "5"))
MIN_SCORE       = float(os.getenv("CONTEXTCUT_MIN_SCORE", "0.30"))

# Voyage AI rate limiting — free tier allows ~3 RPM
RATE_LIMIT_SECONDS = 21.0

# ── Token estimation ──────────────────────────────────────────────────────────
try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    def count_tokens(text: str) -> int:
        return len(_enc.encode(text))
    TOKEN_METHOD = "tiktoken"
except ImportError:
    def count_tokens(text: str) -> int:
        return int(len(text.split()) * 1.35)
    TOKEN_METHOD = "estimate (pip install tiktoken for exact counts)"

# ── Shared state ──────────────────────────────────────────────────────────────
_lock  = threading.Lock()
_log   = deque(maxlen=50)
_stats = {
    "total_requests":    0,
    "total_tokens_seen": 0,
    "max_tokens_seen":   0,
    "last_seen":         None,
    "start_time":        datetime.now().isoformat(),
    "token_method":      TOKEN_METHOD,
}

def record(entry: dict):
    with _lock:
        _log.appendleft(entry)
        _stats["total_requests"] += 1
        t = entry.get("tokens_after", 0)
        _stats["total_tokens_seen"] += t
        if t > _stats["max_tokens_seen"]:
            _stats["max_tokens_seen"] = t
        _stats["last_seen"] = entry["ts"]

# ── Lazy clients ──────────────────────────────────────────────────────────────
_vc             = None
_qclient        = None
_last_embed_ts  = 0.0

def get_clients():
    global _vc, _qclient
    if _vc is None:
        _vc = voyageai.Client()
    if _qclient is None:
        _qclient = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    return _vc, _qclient

# ── Qdrant lookup ─────────────────────────────────────────────────────────────
def qdrant_context(query: str) -> tuple[str, list[dict]]:
    """Returns (injected_text, hits_metadata). Respects Voyage AI free tier rate limit."""
    global _last_embed_ts
    try:
        vc, qclient = get_clients()

        # Rate limit: stay under 3 RPM on Voyage free tier
        elapsed = time.time() - _last_embed_ts
        if elapsed < RATE_LIMIT_SECONDS:
            time.sleep(RATE_LIMIT_SECONDS - elapsed)

        emb = vc.embed([query], model="voyage-3", input_type="query").embeddings[0]
        _last_embed_ts = time.time()

        response = qclient.query_points(
            collection_name=COLLECTION,
            query=emb,
            limit=TOP_K,
            with_payload=True,
            with_vectors=False,
        )

        chunks, meta = [], []
        for h in response.points:
            if h.score < MIN_SCORE:
                print(f"[contextcut] skip low-score chunk: {round(h.score,3)} < {MIN_SCORE}")
                continue
            src   = h.payload.get("filename", h.payload.get("source", "unknown"))
            text  = h.payload.get("text", "")
            score = round(h.score, 3)
            chunks.append(f"[{src} | relevance={score}]\n{text}")
            meta.append({"source": src, "score": score, "chars": len(text)})

        return "\n\n---\n\n".join(chunks), meta

    except Exception as e:
        print(f"[contextcut] Qdrant/Voyage error: {e}")
        _last_embed_ts = time.time()
        return "", []

# ── Context injection ─────────────────────────────────────────────────────────
def inject_context(body: dict, context: str) -> dict:
    if not context:
        return body
    prefix = (
        "## Relevant context from knowledge base (semantic search):\n\n"
        + context
        + "\n\n---\n\n"
    )
    messages = body.get("messages", [])
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = prefix + messages[0]["content"]
    else:
        messages.insert(0, {"role": "system", "content": prefix})
    body["messages"] = messages
    return body

# ── Token counting ────────────────────────────────────────────────────────────
def count_body_tokens(body: dict) -> int:
    total = 0
    for msg in body.get("messages", []):
        content = msg.get("content", "")
        if isinstance(content, str):
            total += count_tokens(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    total += count_tokens(block.get("text", ""))
    return total

# ── Server ────────────────────────────────────────────────────────────────────
class ReusableHTTPServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads      = True

class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence default access log

    def do_POST(self):
        length   = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length)

        try:
            body = json.loads(raw_body)
        except Exception:
            body = None

        query      = ""
        hits_meta  = []
        tok_before = 0
        tok_after  = 0

        if body and "messages" in body:
            for msg in reversed(body["messages"]):
                if msg.get("role") == "user":
                    c     = msg.get("content", "")
                    query = c if isinstance(c, str) else str(c)
                    break

            tok_before = count_body_tokens(body)

            if query:
                ctx, hits_meta = qdrant_context(query)
                body     = inject_context(body, ctx)
                raw_body = json.dumps(body).encode()

            tok_after = count_body_tokens(body)
            pct = round(tok_after / CTX_LIMIT * 100, 1)
            ts  = datetime.now().strftime("%H:%M:%S")
            print(f"[contextcut] {ts} | {tok_before}→{tok_after}/{CTX_LIMIT} ({pct}%) | hits:{len(hits_meta)} | {query[:60]}")
            record({
                "ts": ts, "query": query[:120],
                "tokens_before": tok_before, "tokens_after": tok_after,
                "ctx_limit": CTX_LIMIT, "pct": pct, "hits": hits_meta,
            })

        upstream_url = UPSTREAM + self.path
        req = urllib.request.Request(upstream_url, data=raw_body, method="POST")
        for k, v in self.headers.items():
            if k.lower() not in ("host", "content-length"):
                req.add_header(k, v)
        req.add_header("Content-Length", str(len(raw_body)))

        try:
            with urllib.request.urlopen(req) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding",):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            err_body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(err_body)))
            self.end_headers()
            self.wfile.write(err_body)
        except Exception as e:
            msg = str(e).encode()
            self.send_response(502)
            self.end_headers()
            self.wfile.write(msg)

    def do_GET(self):
        upstream_url = UPSTREAM + self.path
        req = urllib.request.Request(upstream_url, method="GET")
        for k, v in self.headers.items():
            if k.lower() != "host":
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp_body)
        except Exception as e:
            msg = str(e).encode()
            self.send_response(502)
            self.end_headers()
            self.wfile.write(msg)

# ── Dashboard ─────────────────────────────────────────────────────────────────
def pct_color(pct):
    if pct < 60: return "#22c55e"
    if pct < 80: return "#f59e0b"
    return "#ef4444"

def make_dashboard() -> str:
    with _lock:
        rows = list(_log)
        s    = dict(_stats)

    avg  = int(s["total_tokens_seen"] / s["total_requests"]) if s["total_requests"] else 0
    last_pct  = rows[0]["pct"] if rows else 0
    bar_color = pct_color(last_pct)

    rows_html = ""
    for r in rows:
        p   = r["pct"]
        col = pct_color(p)
        hits_str = ", ".join(f"{h['source']}({h['score']})" for h in r.get("hits", []))
        rows_html += f"""<tr>
          <td>{r['ts']}</td>
          <td class="query">{html.escape(r['query'])}</td>
          <td>{r['tokens_before']}</td>
          <td>{r['tokens_after']}</td>
          <td style="color:{col};font-weight:700">{p}%</td>
          <td class="hits">{html.escape(hits_str)}</td>
        </tr>"""

    no_data = '<tr><td colspan="6" style="text-align:center;padding:32px;color:#64748b">No requests yet — send a query through the proxy</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="5">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ContextCut Dashboard</title>
<style>
  :root{{--bg:#0f172a;--surface:#1e293b;--border:#334155;--text:#e2e8f0;--muted:#94a3b8;--accent:#3b82f6}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:'SF Mono',Monaco,monospace;font-size:13px;padding:24px}}
  h1{{font-size:20px;color:var(--accent);margin-bottom:4px}}
  .sub{{color:var(--muted);font-size:11px;margin-bottom:24px}}
  .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:28px}}
  .card{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px}}
  .card-label{{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}}
  .card-val{{font-size:24px;font-weight:700;color:var(--text)}}
  .card-val.warn{{color:#f59e0b}}.card-val.danger{{color:#ef4444}}
  .bar-wrap{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:28px}}
  .bar-label{{color:var(--muted);font-size:11px;margin-bottom:8px}}
  .bar-track{{background:#0f172a;border-radius:4px;height:20px;overflow:hidden}}
  .bar-fill{{height:100%;border-radius:4px;transition:width .4s;background:{bar_color};width:{min(last_pct,100)}%}}
  .bar-text{{margin-top:6px;font-size:12px;color:{bar_color};font-weight:700}}
  table{{width:100%;border-collapse:collapse;background:var(--surface);border-radius:8px;overflow:hidden}}
  th{{background:#1e3a5f;color:var(--accent);text-align:left;padding:10px 12px;font-size:11px;text-transform:uppercase;letter-spacing:.06em}}
  td{{padding:9px 12px;border-top:1px solid var(--border);vertical-align:top;color:var(--muted)}}
  tr:hover td{{background:#263450}}
  td.query{{color:var(--text);max-width:260px;word-break:break-word}}
  td.hits{{font-size:11px;max-width:240px;word-break:break-word}}
  .method{{font-size:10px;color:var(--muted);margin-top:20px;text-align:right}}
  .dot{{display:inline-block;width:8px;height:8px;border-radius:50%;background:#22c55e;animation:pulse 2s infinite;margin-right:6px}}
  @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
</style>
</head>
<body>
<h1><span class="dot"></span>ContextCut · Proxy Dashboard</h1>
<div class="sub">Auto-refreshes every 5s &nbsp;|&nbsp; Started {s['start_time']} &nbsp;|&nbsp;
  Proxy :{LISTEN_PORT} → {UPSTREAM} &nbsp;|&nbsp; Qdrant {QDRANT_HOST}:{QDRANT_PORT} &nbsp;|&nbsp;
  Min score: {MIN_SCORE}</div>
<div class="cards">
  <div class="card"><div class="card-label">Total Requests</div><div class="card-val">{s['total_requests']}</div></div>
  <div class="card"><div class="card-label">Last Context</div>
    <div class="card-val {'danger' if last_pct>80 else 'warn' if last_pct>60 else ''}">{last_pct}%</div></div>
  <div class="card"><div class="card-label">Avg Tokens</div><div class="card-val">{avg}</div></div>
  <div class="card"><div class="card-label">Peak Tokens</div>
    <div class="card-val {'danger' if s['max_tokens_seen']>CTX_LIMIT*0.8 else ''}">{s['max_tokens_seen']}</div></div>
  <div class="card"><div class="card-label">CTX Limit</div><div class="card-val">{CTX_LIMIT}</div></div>
  <div class="card"><div class="card-label">Last Request</div>
    <div class="card-val" style="font-size:16px">{s['last_seen'] or '—'}</div></div>
</div>
<div class="bar-wrap">
  <div class="bar-label">Most Recent Context Usage</div>
  <div class="bar-track"><div class="bar-fill"></div></div>
  <div class="bar-text">{rows[0]['tokens_after'] if rows else 0} / {CTX_LIMIT} tokens ({last_pct}%)</div>
</div>
<table>
  <thead><tr><th>Time</th><th>Query</th><th>Tokens Before</th><th>Tokens After</th><th>CTX %</th><th>Qdrant Hits</th></tr></thead>
  <tbody>{rows_html if rows_html else no_data}</tbody>
</table>
<div class="method">Token counting: {TOKEN_METHOD}</div>
</body></html>"""

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass
    def do_GET(self):
        page = make_dashboard().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not os.getenv("VOYAGE_API_KEY"):
        print("ERROR: VOYAGE_API_KEY environment variable not set.")
        print("  export VOYAGE_API_KEY=your-key-here")
        raise SystemExit(1)

    dash = ReusableHTTPServer(("0.0.0.0", DASHBOARD_PORT), DashboardHandler)
    threading.Thread(target=dash.serve_forever, daemon=True).start()

    print(f"[contextcut] Dashboard  → http://localhost:{DASHBOARD_PORT}")
    print(f"[contextcut] Proxy      → http://127.0.0.1:{LISTEN_PORT} → {UPSTREAM}")
    print(f"[contextcut] Qdrant     → {QDRANT_HOST}:{QDRANT_PORT} / {COLLECTION}")
    print(f"[contextcut] Min score  → {MIN_SCORE}  Top-K → {TOP_K}")
    print(f"[contextcut] Tokens     → {TOKEN_METHOD}")

    ReusableHTTPServer(("127.0.0.1", LISTEN_PORT), ProxyHandler).serve_forever()
