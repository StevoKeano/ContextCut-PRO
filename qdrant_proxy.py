#!/usr/bin/env python3
"""
ContextCut — Qdrant-enriching reverse proxy for any local LLM endpoint.

  Proxy port    (CONTEXTCUT_PROXY_PORT)      — receives requests, injects context, forwards to LLM
  Dashboard port (CONTEXTCUT_DASHBOARD_PORT)  — Chat interface + real-time monitor

Configuration via environment variables (all optional — defaults shown):
  CONTEXTCUT_UPSTREAM        http://localhost:11434   Ollama or OpenAI-compatible endpoint
  CONTEXTCUT_QDRANT_HOST     localhost                Qdrant host
  CONTEXTCUT_QDRANT_PORT     6333                     Qdrant port
  CONTEXTCUT_COLLECTION      contextcut               Qdrant collection name
  CONTEXTCUT_PROXY_PORT      18788                    Proxy listen port
  CONTEXTCUT_DASHBOARD_PORT  18787                    Dashboard listen port
  CONTEXTCUT_CTX_LIMIT       8192                     Model context window size
  CONTEXTCUT_TOP_K           5                        Max Qdrant chunks to retrieve
  CONTEXTCUT_MIN_SCORE       0.30                     Minimum relevance score (0.0-1.0)
  CONTEXTCUT_MODEL                                    Default model name for chat tab
  VOYAGE_API_KEY             (required)               Voyage AI API key
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

# ── Config ────────────────────────────────────────────────────────────────────
UPSTREAM       = os.getenv("CONTEXTCUT_UPSTREAM",        "http://localhost:11434")
QDRANT_HOST    = os.getenv("CONTEXTCUT_QDRANT_HOST",     "localhost")
QDRANT_PORT    = int(os.getenv("CONTEXTCUT_QDRANT_PORT", "6333"))
COLLECTION     = os.getenv("CONTEXTCUT_COLLECTION",      "contextcut")
LISTEN_PORT    = int(os.getenv("CONTEXTCUT_PROXY_PORT",     "18788"))
DASHBOARD_PORT = int(os.getenv("CONTEXTCUT_DASHBOARD_PORT", "18787"))
CTX_LIMIT      = int(os.getenv("CONTEXTCUT_CTX_LIMIT",   "8192"))
TOP_K          = int(os.getenv("CONTEXTCUT_TOP_K",       "5"))
MIN_SCORE      = float(os.getenv("CONTEXTCUT_MIN_SCORE", "0.30"))
DEFAULT_MODEL  = os.getenv("CONTEXTCUT_MODEL",           "")

# ── Token estimation ──────────────────────────────────────────────────────────
try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    def count_tokens(text: str) -> int:
        return len(_enc.encode(text))
    TOKEN_METHOD = "tiktoken (exact)"
except ImportError:
    def count_tokens(text: str) -> int:
        return int(len(text.split()) * 1.35)
    TOKEN_METHOD = "estimate ±5%"

# ── Shared state ──────────────────────────────────────────────────────────────
_lock  = threading.Lock()
_log   = deque(maxlen=100)
_stats = {
    "total_requests":  0,
    "total_saved":     0,
    "max_tokens_seen": 0,
    "last_seen":       None,
    "start_time":      datetime.now().isoformat(),
}

def record(entry: dict):
    with _lock:
        _log.appendleft(entry)
        _stats["total_requests"] += 1
        t = entry.get("tokens_after", 0)
        b = entry.get("tokens_before", 0)
        _stats["total_saved"] += max(0, b - t) if b > 5 else 0
        if t > _stats["max_tokens_seen"]:
            _stats["max_tokens_seen"] = t
        _stats["last_seen"] = entry["ts"]

# ── Lazy clients ──────────────────────────────────────────────────────────────
_vc            = None
_qclient       = None
_last_embed_ts = 0.0

def get_clients():
    global _vc, _qclient
    if _vc is None:
        _vc = voyageai.Client()
    if _qclient is None:
        _qclient = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    return _vc, _qclient

# ── Qdrant lookup ─────────────────────────────────────────────────────────────
def qdrant_context(query: str) -> tuple[str, list[dict]]:
    global _last_embed_ts
    try:
        vc, qclient = get_clients()
        elapsed = time.time() - _last_embed_ts
        if elapsed < 21.0:
            time.sleep(21.0 - elapsed)
        emb = vc.embed([query], model="voyage-3", input_type="query").embeddings[0]
        _last_embed_ts = time.time()
        response = qclient.query_points(
            collection_name=COLLECTION, query=emb,
            limit=TOP_K, with_payload=True, with_vectors=False,
        )
        chunks, meta = [], []
        for h in response.points:
            if h.score < MIN_SCORE:
                print(f"[contextcut] skip {round(h.score,3)} < {MIN_SCORE}")
                continue
            src   = h.payload.get("filename", h.payload.get("source", "?"))
            text  = h.payload.get("text", "")
            score = round(h.score, 3)
            chunks.append(f"[{src} | relevance={score}]\n{text}")
            meta.append({"source": src, "score": score, "chars": len(text)})
        return "\n\n---\n\n".join(chunks), meta
    except Exception as e:
        print(f"[contextcut] Qdrant error: {e}")
        _last_embed_ts = time.time()
        return "", []

# ── Context injection ─────────────────────────────────────────────────────────
def inject_context(body: dict, context: str) -> dict:
    if not context:
        return body
    prefix = "## Relevant context (semantic search):\n\n" + context + "\n\n---\n\n"
    messages = body.get("messages", [])
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = prefix + messages[0]["content"]
    else:
        messages.insert(0, {"role": "system", "content": prefix})
    body["messages"] = messages
    return body

def count_body_tokens(body: dict) -> int:
    total = 0
    for msg in body.get("messages", []):
        c = msg.get("content", "")
        total += count_tokens(c if isinstance(c, str) else str(c))
    return total

# ── Server base ───────────────────────────────────────────────────────────────
class ReusableHTTPServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads      = True

# ── Proxy ─────────────────────────────────────────────────────────────────────
class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def _forward(self, method: str, raw_body: bytes):
        upstream_url = UPSTREAM + self.path
        req = urllib.request.Request(upstream_url, data=raw_body if method == "POST" else None, method=method)
        for k, v in self.headers.items():
            if k.lower() not in ("host", "content-length"):
                req.add_header(k, v)
        if raw_body:
            req.add_header("Content-Length", str(len(raw_body)))
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
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
            self.end_headers()
            self.wfile.write(err_body)
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def do_GET(self):
        self._forward("GET", b"")

    def do_POST(self):
        length   = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length)
        try:
            body = json.loads(raw_body)
        except Exception:
            body = None

        query = ""
        hits_meta = []
        tok_before = tok_after = 0

        if body and "messages" in body:
            for msg in reversed(body["messages"]):
                if msg.get("role") == "user":
                    c = msg.get("content", "")
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
            record({"ts": ts, "query": query[:120], "tokens_before": tok_before,
                    "tokens_after": tok_after, "ctx_limit": CTX_LIMIT, "pct": pct, "hits": hits_meta})

        self._forward("POST", raw_body)

# ── Dashboard ─────────────────────────────────────────────────────────────────
def pct_color(p):
    return "#22c55e" if p < 60 else "#f59e0b" if p < 80 else "#ef4444"

def make_stats_json() -> dict:
    with _lock:
        rows = list(_log)
        s    = dict(_stats)
    r = rows[0] if rows else {}
    return {
        "pct":           r.get("pct", 0),
        "tokens_before": r.get("tokens_before", 0),
        "tokens_after":  r.get("tokens_after", 0),
        "hits":          r.get("hits", []),
        "total_saved":   s["total_saved"],
        "total_requests":s["total_requests"],
    }

def make_dashboard() -> str:
    with _lock:
        rows = list(_log)
        s    = dict(_stats)

    last_pct = rows[0]["pct"] if rows else 0
    last_tok = rows[0]["tokens_after"] if rows else 0
    bc       = pct_color(last_pct)

    rows_html = ""
    for r in rows:
        p   = r["pct"]
        col = pct_color(p)
        hits_str = " ".join(
            f'<span class="hit">{html.escape(h["source"].replace(".md",""))} <em>{h["score"]}</em></span>'
            for h in r.get("hits", [])
        ) or '<span style="color:#4b5563">—</span>'
        bar = f'<div class="mini-bar"><div class="mini-fill" style="width:{min(p,100)}%;background:{col}"></div></div>'
        rows_html += f"""<tr>
          <td class="ts">{r['ts']}</td>
          <td class="qcell">{html.escape(r['query'])}</td>
          <td class="num">{r['tokens_before']}</td>
          <td class="num">{r['tokens_after']}</td>
          <td class="num" style="color:{col}">{p}%{bar}</td>
          <td class="hitcell">{hits_str}</td>
        </tr>"""

    no_rows = '<tr><td colspan="6" class="empty">No requests yet — use the Chat tab or send a query through the proxy</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ContextCut</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
<style>
:root{{--bg:#080c14;--surf:#0d1420;--surf2:#111927;--border:#1e2d42;--text:#c9d8f0;--muted:#4a6080;--accent:#00d4ff;--green:#22c55e;--yellow:#f59e0b;--red:#ef4444;--r:6px}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'JetBrains Mono',monospace;font-size:13px;min-height:100vh}}
.header{{background:var(--surf);border-bottom:1px solid var(--border);padding:0 24px;display:flex;align-items:center;gap:16px;height:52px}}
.logo{{font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:var(--accent);letter-spacing:-.5px}}
.logo span{{color:var(--text)}}
.hinfo{{color:var(--muted);font-size:11px;flex:1}}
.live{{display:flex;align-items:center;gap:6px;color:var(--muted);font-size:11px}}
.dot{{width:7px;height:7px;border-radius:50%;background:var(--green);animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.3}}}}
.tabs{{display:flex;border-bottom:1px solid var(--border);background:var(--surf);padding:0 24px}}
.tab{{padding:12px 20px;cursor:pointer;border-bottom:2px solid transparent;color:var(--muted);font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;transition:.2s}}
.tab:hover{{color:var(--text)}}.tab.active{{color:var(--accent);border-bottom-color:var(--accent)}}
.panel{{display:none;padding:20px}}.panel.active{{display:block}}
/* cards */
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:20px}}
.card{{background:var(--surf);border:1px solid var(--border);border-radius:var(--r);padding:14px}}
.card-label{{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px}}
.card-val{{font-size:24px;font-weight:600;font-family:'Syne',sans-serif}}
.green{{color:var(--green)}}.yellow{{color:var(--yellow)}}.red{{color:var(--red)}}
/* ctx bar */
.ctx-wrap{{background:var(--surf);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:20px}}
.ctx-label{{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px}}
.ctx-track{{background:var(--bg);border-radius:3px;height:16px;overflow:hidden}}
.ctx-fill{{height:100%;border-radius:3px;transition:width .5s;background:{bc};width:{min(last_pct,100)}%}}
.ctx-info{{display:flex;justify-content:space-between;margin-top:5px;font-size:11px;color:var(--muted)}}
/* table */
table{{width:100%;border-collapse:collapse;background:var(--surf);border-radius:var(--r);overflow:hidden;border:1px solid var(--border)}}
th{{background:#0a1628;color:var(--muted);text-align:left;padding:9px 12px;font-size:10px;text-transform:uppercase;letter-spacing:.1em;border-bottom:1px solid var(--border)}}
td{{padding:8px 12px;border-top:1px solid var(--border);vertical-align:middle}}
tr:hover td{{background:var(--surf2)}}
.ts{{color:var(--muted);white-space:nowrap;font-size:11px}}.qcell{{max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.num{{text-align:right;white-space:nowrap}}.hitcell{{max-width:280px}}
.hit{{display:inline-block;background:#0a1a2e;border:1px solid var(--border);border-radius:3px;padding:1px 5px;margin:1px;font-size:10px;color:var(--muted)}}.hit em{{color:var(--accent);font-style:normal}}
.mini-bar{{height:3px;background:var(--border);border-radius:2px;margin-top:3px;overflow:hidden}}.mini-fill{{height:100%;border-radius:2px}}
.empty{{text-align:center;padding:36px;color:var(--muted)}}
/* chat */
.chat-layout{{display:grid;grid-template-columns:1fr 270px;gap:14px;height:calc(100vh - 128px)}}
.chat-main{{display:flex;flex-direction:column;background:var(--surf);border:1px solid var(--border);border-radius:var(--r);overflow:hidden}}
.chat-messages{{flex:1;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:12px}}
.chat-messages::-webkit-scrollbar{{width:4px}}.chat-messages::-webkit-scrollbar-thumb{{background:var(--border);border-radius:2px}}
.msg{{max-width:85%}}.msg.user{{align-self:flex-end}}.msg.assistant{{align-self:flex-start}}
.bubble{{padding:10px 14px;border-radius:var(--r);line-height:1.6;white-space:pre-wrap;word-break:break-word}}
.msg.user .bubble{{background:var(--accent);color:#000;font-weight:500}}
.msg.assistant .bubble{{background:var(--surf2);border:1px solid var(--border)}}
.msg-meta{{font-size:10px;color:var(--muted);margin-top:3px}}.msg.user .msg-meta{{text-align:right}}
.typing{{display:flex;gap:4px;padding:10px 14px;background:var(--surf2);border:1px solid var(--border);border-radius:var(--r);width:fit-content}}
.typing span{{width:6px;height:6px;border-radius:50%;background:var(--muted);animation:blink 1.2s infinite}}
.typing span:nth-child(2){{animation-delay:.2s}}.typing span:nth-child(3){{animation-delay:.4s}}
@keyframes blink{{0%,100%{{opacity:.2}}50%{{opacity:1}}}}
.chat-input-row{{display:flex;gap:8px;padding:10px;border-top:1px solid var(--border)}}
.chat-input{{flex:1;background:var(--bg);border:1px solid var(--border);border-radius:var(--r);padding:9px 12px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:13px;resize:none;outline:none;line-height:1.5}}
.chat-input:focus{{border-color:var(--accent)}}
.send-btn{{background:var(--accent);color:#000;border:none;border-radius:var(--r);padding:9px 16px;font-family:'Syne',sans-serif;font-weight:700;font-size:13px;cursor:pointer;white-space:nowrap;transition:.15s}}
.send-btn:hover{{opacity:.85}}.send-btn:disabled{{opacity:.4;cursor:not-allowed}}
.chat-side{{display:flex;flex-direction:column;gap:10px;overflow-y:auto}}
.side-card{{background:var(--surf);border:1px solid var(--border);border-radius:var(--r);padding:12px;flex-shrink:0}}
.side-title{{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-bottom:8px}}
.gauge-val{{font-family:'Syne',sans-serif;font-size:32px;font-weight:800;color:var(--accent);text-align:center}}
.gauge-sub{{font-size:10px;color:var(--muted);text-align:center;margin-top:2px}}
.model-input{{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:var(--r);padding:7px 10px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:12px;outline:none}}
.model-input:focus{{border-color:var(--accent)}}
.hit-row{{background:var(--bg);border:1px solid var(--border);border-radius:3px;padding:5px 8px;margin-bottom:3px}}
.hit-name{{color:var(--text);font-size:11px}}.hit-score{{color:var(--accent);font-size:10px;margin-top:1px}}
.saved-val{{font-family:'Syne',sans-serif;font-size:28px;font-weight:800;color:var(--green)}}
</style>
</head>
<body>
<div class="header">
  <div class="logo">Context<span>Cut</span></div>
  <div class="hinfo">{UPSTREAM} &nbsp;·&nbsp; Qdrant {QDRANT_HOST}:{QDRANT_PORT} &nbsp;·&nbsp; min_score={MIN_SCORE} &nbsp;·&nbsp; top_k={TOP_K}</div>
  <div class="live"><span class="dot"></span>live</div>
</div>
<div class="tabs">
  <div class="tab active" onclick="switchTab('chat',this)">💬 Chat</div>
  <div class="tab" onclick="switchTab('monitor',this)">📊 Monitor</div>
</div>

<!-- ── CHAT ── -->
<div class="panel active" id="tab-chat" style="padding:14px">
  <div class="chat-layout">
    <div class="chat-main">
      <div class="chat-messages" id="messages">
        <div class="msg assistant">
          <div class="bubble">👋 Welcome to ContextCut. Ask anything — relevant context from your knowledge base will be injected automatically before the query reaches the LLM.</div>
        </div>
      </div>
      <div class="chat-input-row">
        <textarea class="chat-input" id="chatInput" rows="2" placeholder="Type a message… (Enter to send, Shift+Enter for newline)" onkeydown="handleKey(event)"></textarea>
        <button class="send-btn" id="sendBtn" onclick="sendMessage()">Send ↑</button>
      </div>
    </div>
    <div class="chat-side">
      <div class="side-card">
        <div class="side-title">Model</div>
        <input class="model-input" id="modelInput" type="text" value="{DEFAULT_MODEL}" placeholder="e.g. qwen2.5-coder:32b-8k">
      </div>
      <div class="side-card">
        <div class="side-title">Context Usage</div>
        <div class="gauge-val" id="gaugePct">—</div>
        <div class="gauge-sub" id="gaugeSub">of {CTX_LIMIT:,} tokens</div>
        <div class="ctx-track" style="margin-top:10px"><div class="ctx-fill" id="gaugeBar" style="width:0%;background:var(--green)"></div></div>
        <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--muted);margin-top:4px">
          <span id="tokBefore">before: —</span><span id="tokAfter">after: —</span>
        </div>
      </div>
      <div class="side-card">
        <div class="side-title">Qdrant Hits</div>
        <div id="hitsList"><div style="color:var(--muted);font-size:11px">No query yet</div></div>
      </div>
      <div class="side-card">
        <div class="side-title">Session Tokens Saved</div>
        <div class="saved-val" id="sessionSaved">0</div>
        <div style="font-size:10px;color:var(--muted);margin-top:2px">not sent to LLM</div>
      </div>
    </div>
  </div>
</div>

<!-- ── MONITOR ── -->
<div class="panel" id="tab-monitor">
  <div class="cards">
    <div class="card"><div class="card-label">Total Requests</div><div class="card-val">{s['total_requests']}</div></div>
    <div class="card"><div class="card-label">Last Context</div><div class="card-val {'green' if last_pct<60 else 'yellow' if last_pct<80 else 'red'}">{last_pct}%</div></div>
    <div class="card"><div class="card-label">Tokens Saved</div><div class="card-val green">{s['total_saved']:,}</div></div>
    <div class="card"><div class="card-label">Peak Tokens</div><div class="card-val {'red' if s['max_tokens_seen']>CTX_LIMIT*0.8 else ''}">{s['max_tokens_seen']:,}</div></div>
    <div class="card"><div class="card-label">CTX Limit</div><div class="card-val">{CTX_LIMIT:,}</div></div>
    <div class="card"><div class="card-label">Last Request</div><div class="card-val" style="font-size:15px">{s['last_seen'] or '—'}</div></div>
  </div>
  <div class="ctx-wrap">
    <div class="ctx-label">Most Recent Context Usage</div>
    <div class="ctx-track"><div class="ctx-fill"></div></div>
    <div class="ctx-info"><span>{last_tok:,} / {CTX_LIMIT:,} tokens</span><strong style="color:{bc}">{last_pct}%</strong></div>
  </div>
  <table>
    <thead><tr><th>Time</th><th>Query</th><th>Before</th><th>After</th><th>CTX %</th><th>Qdrant Hits</th></tr></thead>
    <tbody>{rows_html if rows_html else no_rows}</tbody>
  </table>
  <div style="margin-top:8px;font-size:10px;color:var(--muted);text-align:right">Token counting: {TOKEN_METHOD}</div>
</div>

<script>
let sessionSaved = 0;

function switchTab(name, el) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
  if (name === 'monitor') setTimeout(() => location.reload(), 50);
}}

function handleKey(e) {{
  if (e.key === 'Enter' && !e.shiftKey) {{ e.preventDefault(); sendMessage(); }}
}}

function esc(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

function appendMsg(role, text, meta) {{
  const box = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.innerHTML = `<div class="bubble">${{esc(text)}}</div>` +
    (meta ? `<div class="msg-meta">${{esc(meta)}}</div>` : '');
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}}

function showTyping() {{
  const box = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'msg assistant'; div.id = 'typing';
  div.innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';
  box.appendChild(div); box.scrollTop = box.scrollHeight;
}}

function removeTyping() {{ const el=document.getElementById('typing'); if(el) el.remove(); }}

function updateSidebar(d) {{
  const pct = d.pct || 0;
  const col = pct < 60 ? '#22c55e' : pct < 80 ? '#f59e0b' : '#ef4444';
  document.getElementById('gaugePct').textContent = pct + '%';
  document.getElementById('gaugePct').style.color = col;
  document.getElementById('gaugeBar').style.cssText = `width:${{Math.min(pct,100)}}%;background:${{col}}`;
  document.getElementById('tokBefore').textContent = 'before: ' + (d.tokens_before||0);
  document.getElementById('tokAfter').textContent  = 'after: '  + (d.tokens_after||0);
  const saved = Math.max(0,(d.tokens_before||0)-(d.tokens_after||0));
  if (saved > 0) {{
    sessionSaved += saved;
    document.getElementById('sessionSaved').textContent = sessionSaved.toLocaleString();
  }}
  const hl = document.getElementById('hitsList');
  if (d.hits && d.hits.length) {{
    hl.innerHTML = d.hits.map(h =>
      `<div class="hit-row"><div class="hit-name">${{esc(h.source)}}</div><div class="hit-score">score: ${{h.score}}</div></div>`
    ).join('');
  }} else {{
    hl.innerHTML = '<div style="color:var(--muted);font-size:11px">No chunks above threshold ({MIN_SCORE})</div>';
  }}
}}

async function sendMessage() {{
  const input   = document.getElementById('chatInput');
  const sendBtn = document.getElementById('sendBtn');
  const model   = document.getElementById('modelInput').value.trim();
  const text    = input.value.trim();
  if (!text) return;
  if (!model) {{ alert('Enter a model name in the sidebar first.'); return; }}
  input.value = '';
  sendBtn.disabled = true;
  appendMsg('user', text);
  showTyping();
  try {{
    const resp = await fetch('/v1/chat/completions', {{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{model, messages:[{{role:'user',content:text}}], stream:false}})
    }});
    removeTyping();
    if (!resp.ok) {{ appendMsg('assistant','❌ Error '+resp.status+': '+await resp.text()); return; }}
    const data    = await resp.json();
    const content = data.choices?.[0]?.message?.content || '(no response)';
    const usage   = data.usage || {{}};
    appendMsg('assistant', content,
      `prompt: ${{usage.prompt_tokens||'?'}} tokens · completion: ${{usage.completion_tokens||'?'}} tokens`);
    try {{
      const sr = await fetch('/stats');
      if (sr.ok) updateSidebar(await sr.json());
    }} catch(e) {{}}
  }} catch(e) {{
    removeTyping();
    appendMsg('assistant','❌ Network error: '+e.message);
  }} finally {{
    sendBtn.disabled = false;
    input.focus();
  }}
}}
</script>
</body></html>"""

# ── Dashboard handler ─────────────────────────────────────────────────────────
class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def do_GET(self):
        if self.path == "/stats":
            body = json.dumps(make_stats_json()).encode()
            self.send_response(200)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            page = make_dashboard().encode()
            self.send_response(200)
            self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length",str(len(page)))
            self.end_headers()
            self.wfile.write(page)

    def do_POST(self):
        # Forward from dashboard chat to proxy
        length   = int(self.headers.get("Content-Length",0))
        raw_body = self.rfile.read(length)
        req = urllib.request.Request(
            f"http://127.0.0.1:{LISTEN_PORT}{self.path}",
            data=raw_body, method="POST"
        )
        for k,v in self.headers.items():
            if k.lower() not in ("host",):
                req.add_header(k,v)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                rb = resp.read()
                self.send_response(resp.status)
                for k,v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding",):
                        self.send_header(k,v)
                self.end_headers()
                self.wfile.write(rb)
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(e).encode())

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not os.getenv("VOYAGE_API_KEY"):
        print("ERROR: VOYAGE_API_KEY not set. Export it and retry.")
        raise SystemExit(1)

    dash = ReusableHTTPServer(("0.0.0.0", DASHBOARD_PORT), DashboardHandler)
    threading.Thread(target=dash.serve_forever, daemon=True).start()

    print(f"[contextcut] Dashboard  → http://localhost:{DASHBOARD_PORT}  (Chat + Monitor tabs)")
    print(f"[contextcut] Proxy      → http://127.0.0.1:{LISTEN_PORT} → {UPSTREAM}")
    print(f"[contextcut] Qdrant     → {QDRANT_HOST}:{QDRANT_PORT} / {COLLECTION}")
    print(f"[contextcut] Min score  → {MIN_SCORE}  Top-K → {TOP_K}  CTX → {CTX_LIMIT}")
    print(f"[contextcut] Tokens     → {TOKEN_METHOD}")
    if DEFAULT_MODEL:
        print(f"[contextcut] Model      → {DEFAULT_MODEL}")

    ReusableHTTPServer(("127.0.0.1", LISTEN_PORT), ProxyHandler).serve_forever()
