#!/usr/bin/env python3
"""ContextCut-Free — local RAG chat. One file, no Docker, no license."""
VERSION = "1.0.0"
import os, sys, json, time, hashlib, sqlite3, urllib.request, urllib.parse, http.server, mimetypes, threading, re
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────
_ENV_FILE = Path(os.getenv("CC_ENV_FILE", str(Path.home() / ".contextcut-free" / "env"))).expanduser()
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text().splitlines():
        _line = _line.strip()
        if _line and "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "localhost")
OLLAMA_PORT = os.getenv("OLLAMA_PORT", "11434")
OLLAMA_URL  = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
CHAT_MODEL  = os.getenv("CC_CHAT_MODEL", "qwen2.5:7b")
EMBED_MODEL = os.getenv("CC_EMBED_MODEL", "nomic-embed-text")
PROXY_PORT  = int(os.getenv("CC_PORT", "18788"))
DATA_DIR    = Path(os.getenv("CC_DATA_DIR", str(Path.home() / ".contextcut-free"))).expanduser()
KB_DIR      = Path(os.getenv("CC_KB_DIR", str(Path.home() / "contextcut-free" / "knowledge"))).expanduser()
MAX_FILES   = 50
MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_EXT = {".md", ".txt", ".py", ".js", ".ts", ".html", ".css", ".csv", ".json", ".xml", ".yaml", ".yml",
               ".go", ".rs", ".rb", ".java", ".c", ".cpp", ".h", ".sh", ".sql", ".log"}
CTX_LIMIT   = int(os.getenv("CC_CTX_LIMIT", "32768"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
KB_DIR.mkdir(parents=True, exist_ok=True)

# ── FAISS setup ───────────────────────────────────────────────
try:
    import numpy as np
    import faiss
    HAVE_FAISS = True
except ImportError:
    HAVE_FAISS = False

FAISS_PATH = DATA_DIR / "vectors.idx"
META_PATH  = DATA_DIR / "metadata.json"

_index = None
_metadata: list[dict] = []
_index_lock = threading.Lock()

def _init_index():
    global _index, _metadata
    with _index_lock:
        if FAISS_PATH.exists():
            _index = faiss.read_index(str(FAISS_PATH))
            if META_PATH.exists():
                _metadata = json.loads(META_PATH.read_text())
            else:
                _metadata = []
        else:
            _index = None
            _metadata = []

def _save_index():
    with _index_lock:
        if _index is not None and _index.ntotal > 0:
            faiss.write_index(_index, str(FAISS_PATH))
            META_PATH.write_text(json.dumps(_metadata))
        elif FAISS_PATH.exists():
            FAISS_PATH.unlink()
            META_PATH.unlink(missing_ok=True)

if HAVE_FAISS:
    _init_index()

# ── SQLite sessions ───────────────────────────────────────────
DB_PATH = DATA_DIR / "sessions.db"

_db_lock = threading.Lock()

def _init_db():
    with _db_lock:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            sid TEXT PRIMARY KEY, name TEXT, created REAL, updated REAL, context TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS messages (
            mid INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, role TEXT, content TEXT,
            model TEXT, created REAL, tokens INTEGER,
            FOREIGN KEY(sid) REFERENCES sessions(sid))""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_sid ON messages(sid)")
        conn.commit()
        conn.close()

_init_db()

def _get_db():
    return sqlite3.connect(str(DB_PATH))

# ── Ollama helpers ──────────────────────────────────────────
def _ollama(method, path, data=None, timeout=120):
    url = f"{OLLAMA_URL}{path}"
    req = urllib.request.Request(url, method=method,
        data=json.dumps(data).encode() if data else None,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise RuntimeError(f"Ollama HTTP {e.code}: {err}")
    except Exception as e:
        raise RuntimeError(f"Ollama error: {e}")

def _chat(messages, model=None, stream=False):
    body = {"model": model or CHAT_MODEL, "messages": messages, "stream": stream,
            "options": {"num_ctx": CTX_LIMIT}}
    return _ollama("POST", "/api/chat", body)

def _chat_stream_yield(messages, model=None):
    """Yields parsed JSON chunks from Ollama's streaming /api/chat."""
    model = model or CHAT_MODEL
    body = {"model": model, "messages": messages, "stream": True,
            "options": {"num_ctx": CTX_LIMIT}}
    url = f"{OLLAMA_URL}/api/chat"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, method="POST", data=data,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        for line in r:
            line = line.decode().strip()
            if line:
                yield json.loads(line)

def _embed(texts, model=None):
    body = {"model": model or EMBED_MODEL, "input": texts if isinstance(texts, list) else [texts]}
    r = _ollama("POST", "/api/embed", body)
    return r.get("embeddings", [])

def _list_models():
    r = _ollama("GET", "/api/tags")
    return [m["name"] for m in r.get("models", [])]

# ── DuckDuckGo search ─────────────────────────────────────────
def _web_search(q, max_results=5):
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = []
            for r in ddgs.text(q, max_results=max_results):
                results.append({"title": r.get("title", ""), "url": r.get("href", ""),
                                "snippet": r.get("body", "")})
            return results
    except ImportError:
        # Fallback: plain HTML scrape (no API key needed)
        import html
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(q)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                body = r.read().decode()
            results = []
            for m in re.finditer(r'<a rel="nofollow" href="(.*?)".*?class="result__a".*?>(.*?)</a>.*?class="result__snippet".*?>(.*?)</a>', body, re.DOTALL):
                results.append({"url": html.unescape(m.group(1)), "title": html.unescape(re.sub(r'<.*?>', '', m.group(2))),
                                "snippet": html.unescape(re.sub(r'<.*?>', '', m.group(3)))})
            return results[:max_results]
        except Exception as e:
            return [{"error": str(e)}]

# ── File / knowledge management ─────────────────────────────
def _count_files():
    return sum(1 for f in KB_DIR.iterdir() if f.is_file() and f.suffix.lower() in ALLOWED_EXT)

def _read_file(path):
    fpath = KB_DIR / path
    if not fpath.exists() or not fpath.is_file():
        return None
    try:
        return fpath.read_bytes()
    except:
        return None

def _write_file(name, content):
    fpath = KB_DIR / name
    fpath.write_bytes(content if isinstance(content, bytes) else content.encode())
    print(f"[cc-free] File saved: {fpath.name}")

def _delete_file(name):
    fpath = KB_DIR / name
    if fpath.exists():
        fpath.unlink()
    # Remove vectors
    with _index_lock:
        global _metadata
        _metadata = [m for m in _metadata if m.get("filename") != name]
    _save_index()
    print(f"[cc-free] File deleted: {name}")

def _ingest_file(name):
    fpath = KB_DIR / name
    if not fpath.exists():
        return {"error": "File not found"}
    raw = fpath.read_text(encoding="utf-8", errors="ignore")
    if not raw.strip():
        return {"error": "Empty file"}

    chunks = _chunk_text(raw)
    if not chunks:
        return {"error": "No valid chunks"}

    try:
        vecs = _embed(chunks)
    except Exception as e:
        return {"error": f"Embed failed: {e}"}

    if len(vecs) != len(chunks):
        return {"error": f"Expected {len(chunks)} embeddings, got {len(vecs)}"}

    dim = len(vecs[0])
    with _index_lock:
        global _index, _metadata
        # Remove old vectors for this file
        _metadata = [m for m in _metadata if m.get("filename") != name]
        if _index is None:
            _index = faiss.IndexFlatIP(dim)
        _index.add(np.array(vecs, dtype=np.float32))
        for i, (chunk, vec) in enumerate(zip(chunks, vecs)):
            _metadata.append({"filename": name, "chunk_index": i, "text": chunk[:4000]})
    _save_index()
    print(f"[cc-free] Ingested: {name} ({len(chunks)} chunks)")
    return {"ok": True, "chunks": len(chunks)}

def _query_kb(query, top_k=5):
    if _index is None or _index.ntotal == 0:
        return []
    try:
        qvec = _embed([query])[0]
    except:
        return []
    with _index_lock:
        if _index.ntotal == 0:
            return []
        scores, indices = _index.search(np.array([qvec], dtype=np.float32), min(top_k, _index.ntotal))
    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx >= 0 and idx < len(_metadata):
            m = _metadata[idx]
            results.append({"filename": m["filename"], "text": m["text"], "score": round(float(score), 4)})
    return results

def _chunk_text(text, max_chars=1500, overlap=150):
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            # Try to break at newline
            nl = text.rfind("\n", start, end)
            if nl > start + max_chars // 2:
                end = nl
        chunks.append(text[start:end])
        start = end - (overlap if end < len(text) else 0)
    return chunks

# ── Dashboard HTML ────────────────────────────────────────────
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>ContextCut-Free</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0F172A;--surf:#1E293B;--border:#334155;--text:#E2E8F0;--muted:#64748B;--accent:#0EA5E9;--accent2:#7C3AED;--err:#EF4444;--ok:#4ADE80}
.light{--bg:#F8FAFC;--surf:#FFFFFF;--border:#CBD5E1;--text:#1E293B;--muted:#94A3B8;--accent:#0284C7;--accent2:#7C3AED;--err:#DC2626;--ok:#16A34A}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;font-size:14px;overflow:hidden}
.app{display:flex;height:100vh;overflow:hidden}
.sbar{width:280px;min-width:280px;background:var(--surf);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
.sbar-hdr{padding:16px 16px 12px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}
.sbar-hdr h2{font-size:13px;font-weight:700;color:var(--accent);letter-spacing:.5px}
.sbar-hdr .badge{font-size:9px;background:var(--accent);color:#000;padding:1px 6px;border-radius:3px;font-weight:700;letter-spacing:.5px}
.sbar-acts{display:flex;gap:4px}
.sbar-acts button{background:none;border:none;color:var(--muted);font-size:16px;cursor:pointer;width:28px;height:28px;border-radius:4px;display:flex;align-items:center;justify-content:center;transition:all .15s}
.sbar-acts button:hover{background:var(--border);color:var(--text)}
.slist{flex:1;overflow-y:auto;padding:4px 0}
.sitem{padding:10px 16px;cursor:pointer;border-bottom:1px solid transparent;transition:background .1s;display:flex;justify-content:space-between;align-items:center;gap:8px}
.sitem:hover{background:var(--border)}
.sitem.act{background:var(--border);border-left:3px solid var(--accent)}
.sitem-name{font-size:12px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.sitem-del{background:none;border:none;color:var(--muted);font-size:10px;cursor:pointer;padding:2px 4px;border-radius:2px;opacity:0;transition:all .1s}
.sitem:hover .sitem-del{opacity:1}
.sitem-del:hover{color:var(--err);background:rgba(239,68,68,.15)}
.main{flex:1;display:flex;flex-direction:column;min-width:0}
.top{display:flex;align-items:center;justify-content:space-between;padding:8px 20px;border-bottom:1px solid var(--border);gap:12px;min-height:48px}
.top-l{display:flex;align-items:center;gap:8px;flex:1}
.top-btn{background:none;border:none;color:var(--muted);font-size:13px;cursor:pointer;padding:4px 10px;border-radius:4px;transition:all .15s;font-family:inherit;white-space:nowrap}
.top-btn:hover{background:var(--border);color:var(--text)}
.top-btn.act{color:var(--accent)}
#modelSel{background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-size:12px;padding:4px 8px;font-family:inherit;cursor:pointer;outline:none;max-width:160px}
#modelSel:focus{border-color:var(--accent)}
.cht{flex:1;overflow-y:auto;padding:20px 24px;display:flex;flex-direction:column;gap:16px}
.cht:empty::after{content:'Send a message or upload files to your knowledge base.';color:var(--muted);text-align:center;padding:60px 20px;font-size:13px}
.msg{max-width:80%;padding:12px 16px;border-radius:8px;font-size:13px;line-height:1.7;white-space:pre-wrap;word-break:break-word;animation:fadeIn .2s}
.msg.user{background:var(--accent);color:#000;align-self:flex-end;border-bottom-right-radius:2px}
.msg.ass{background:var(--surf);border:1px solid var(--border);align-self:flex-start;border-bottom-left-radius:2px}
.msg.ass p{margin:0 0 8px}
.msg.ass p:last-child{margin:0}
.msg.ass code{background:var(--bg);padding:1px 4px;border-radius:3px;font-size:12px}
.msg.ass pre{background:var(--bg);padding:12px;border-radius:6px;overflow-x:auto;margin:8px 0;font-size:12px;border:1px solid var(--border)}
.msg.ass pre code{background:none;padding:0}
.msg.ass ul,.msg.ass ol{margin:6px 0;padding-left:20px}
.msg.ass table{border-collapse:collapse;margin:8px 0;width:100%}
.msg.ass th,.msg.ass td{border:1px solid var(--border);padding:6px 10px;text-align:left;font-size:12px}
.msg.ass th{background:var(--bg);color:var(--accent)}
.msg .fname{font-size:10px;color:var(--muted);margin-top:4px}
.src{font-size:10px;color:var(--muted);margin-top:4px}
.src a{color:var(--accent);text-decoration:none}
.src a:hover{text-decoration:underline}
.inp-wrap{display:flex;gap:8px;padding:12px 20px;border-top:1px solid var(--border);align-items:flex-end}
.inp-wrap textarea{flex:1;background:var(--surf);border:1px solid var(--border);border-radius:6px;padding:10px 14px;color:var(--text);font-size:13px;font-family:inherit;resize:none;outline:none;max-height:120px;line-height:1.5}
.inp-wrap textarea:focus{border-color:var(--accent)}
.inp-wrap button{background:var(--accent);color:#000;border:none;border-radius:6px;padding:10px 18px;font-size:13px;font-weight:600;cursor:pointer;transition:background .15s;white-space:nowrap;font-family:inherit}
.inp-wrap button:hover{background:#0284C7}
.inp-wrap button:disabled{opacity:.4;cursor:default}
.inp-wrap .att-btn{background:none;border:none;color:var(--muted);font-size:18px;cursor:pointer;padding:6px;border-radius:4px;transition:all .15s;line-height:1}
.inp-wrap .att-btn:hover{background:var(--border);color:var(--text)}
.inp-wrap .tog-btn{background:none;border:none;color:var(--muted);font-size:13px;cursor:pointer;padding:6px 10px;border-radius:4px;transition:all .15s;font-family:inherit;white-space:nowrap}
.inp-wrap .tog-btn:hover{background:var(--border);color:var(--text)}
.inp-wrap .tog-btn.on{color:var(--accent)}
.kb-panel{display:none;width:320px;min-width:320px;background:var(--surf);border-left:1px solid var(--border);flex-direction:column;overflow:hidden}
.kb-panel.open{display:flex}
.kb-hdr{padding:14px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;font-size:12px;font-weight:600;color:var(--accent)}
.kb-hdr .ct{font-size:10px;color:var(--muted);font-weight:400}
.kb-acts{display:flex;gap:6px}
.kb-acts button{background:none;border:none;color:var(--muted);font-size:15px;cursor:pointer;padding:2px 6px;border-radius:3px;transition:all .1s}
.kb-acts button:hover{background:var(--border);color:var(--text)}
.kb-list{flex:1;overflow-y:auto;padding:4px 0}
.kbf{padding:8px 14px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;font-size:12px;border-bottom:1px solid transparent;transition:background .1s}
.kbf:hover{background:var(--border)}
.kbf-name{color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kbf-size{color:var(--muted);font-size:10px}
.kbf-rm{background:none;border:none;color:var(--muted);font-size:10px;cursor:pointer;padding:2px 4px;border-radius:2px;opacity:0}
.kbf:hover .kbf-rm{opacity:1}
.kbf-rm:hover{color:var(--err);background:rgba(239,68,68,.15)}
.kb-empty{color:var(--muted);text-align:center;padding:30px 16px;font-size:12px}
.kb-ftr{padding:8px 14px;border-top:1px solid var(--border);font-size:10px;color:var(--muted);text-align:center}
.kb-ftr a{color:var(--accent);text-decoration:none}
.ld{display:inline-block;width:14px;height:14px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-left:6px}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes fadeIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
@media(max-width:768px){.sbar{display:none}.kb-panel{display:none!important}.msg{max-width:95%}}
</style>
</head>
<body>
<div class="app">
  <div class="sbar" id="sbar">
    <div class="sbar-hdr">
      <h2>ContextCut<span class="badge">FREE</span></h2>
      <div class="sbar-acts">
        <button onclick="newSession()" title="New session">+</button>
        <button onclick="toggleTheme()" id="togBtn" title="Toggle theme">☽</button>
      </div>
    </div>
    <div class="slist" id="slist"></div>
  </div>
  <div class="main">
    <div class="top">
      <div class="top-l">
        <select id="modelSel" onchange="switchModel(this.value)"></select>
        <button class="top-btn" onclick="toggleKB()" id="kbBtn">📂 Files</button>
        <button class="top-btn" onclick="toggleSearch()" id="wsBtn">🌐 Search</button>
        <button class="top-btn" onclick="clearCtx()">✕ Clear</button>
      </div>
      <span style="font-size:11px;color:var(--muted)" id="stats"></span>
    </div>
    <div class="cht" id="cht"></div>
    <div class="inp-wrap">
      <button class="att-btn" onclick="document.getElementById('fu').click()" title="Upload file">📎</button>
      <input type="file" id="fu" accept=".md,.txt,.py,.js,.ts,.html,.css,.csv,.json,.xml,.yaml,.yml,.go,.rs,.rb,.java,.c,.cpp,.h,.sh,.sql,.log" style="display:none" onchange="uploadFile(this)">
      <textarea id="inp" rows="1" placeholder="Message..." onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send()}"></textarea>
      <button id="sndBtn" onclick="send()">Send</button>
      <button class="tog-btn" id="kbTog" onclick="toggleKB()">📂</button>
    </div>
  </div>
  <div class="kb-panel" id="kbPanel">
    <div class="kb-hdr">
      <span>Knowledge Base <span class="ct" id="kbCount"></span></span>
      <div class="kb-acts">
        <button onclick="document.getElementById('fu').click()" title="Upload file">📎</button>
        <button onclick="toggleKB()" title="Close">✕</button>
      </div>
    </div>
    <div class="kb-list" id="kbList"></div>
    <div class="kb-ftr">Free: 50 files max &middot; <a href="#" onclick="openPro()">Upgrade →</a></div>
  </div>
</div>
<script>
const _ = id=>document.getElementById(id);
let _sid=null, _sending=false, _kbOpen=false, _wsOn=false, _models=[];

function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function escAttr(s){return esc(s).replace(/"/g,'&quot;')}
function md(s){
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/```(\w*)\n([\s\S]*?)```/g,'<pre><code>$2</code></pre>')
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>')
    .replace(/\*([^*]+)\*/g,'<i>$1</i>')
    .replace(/\n/g,'<br>');
}

function addMsg(role,content,extra){
  const d=document.createElement('div');
  d.className='msg '+role;
  d.innerHTML=role==='user'?esc(content):md(content);
  if(extra) d.innerHTML+=extra;
  _('cht').appendChild(d);
  _('cht').scrollTop=_('cht').scrollHeight;
}

async function loadSessions(){
  try{
    const r=await fetch('/api/sessions');
    const d=await r.json();
    const list=_('slist'); list.innerHTML='';
    (d.sessions||[]).forEach(s=>{
      const div=document.createElement('div');
      div.className='sitem'+(s.sid===_sid?' act':'');
      div.onclick=()=>loadSession(s.sid);
      div.innerHTML='<span class="sitem-name">'+esc(s.name||'Session')+'</span>'+
        '<button class="sitem-del" onclick="event.stopPropagation();delSession(\''+s.sid+'\')">&times;</button>';
      list.appendChild(div);
    });
  }catch(e){console.error('sessions',e)}
}

async function newSession(){
  try{
    const r=await fetch('/api/session/new',{method:'POST'});
    const d=await r.json();
    _sid=d.sid;
    _('cht').innerHTML='';
    loadSessions();
  }catch(e){console.error('new session',e)}
}

async function loadSession(sid){
  _sid=sid;
  try{
    const r=await fetch('/api/session/load/'+sid);
    const d=await r.json();
    _('cht').innerHTML='';
    (d.messages||[]).forEach(m=>addMsg(m.role,m.content));
    document.querySelectorAll('.sitem').forEach(el=>el.classList.toggle('act',el.dataset.sid===sid));
    loadSessions();
  }catch(e){console.error('load session',e)}
}

async function delSession(sid){
  if(!confirm('Delete session?'))return;
  try{
    await fetch('/api/session/delete/'+sid,{method:'POST'});
    if(_sid===sid){_sid=null;_('cht').innerHTML=''}
    loadSessions();
  }catch(e){console.error('del session',e)}
}

async function send(){
  const inp=_('inp'); const txt=inp.value.trim();
  if(!txt||_sending)return;
  inp.value=''; inp.style.height='auto';
  addMsg('user',txt);
  _sending=true; _('sndBtn').disabled=true; _('sndBtn').innerHTML='<span class="ld"></span>';
  try{
    let ctx='';
    if(_wsOn){
      const sr=await fetch('/api/search/web?q='+encodeURIComponent(txt));
      const sd=await sr.json();
      if(sd.results&&sd.results.length){
        ctx='\\n\\nWeb search results:\\n'+sd.results.map(r=>'- '+esc(r.title)+': '+esc(r.snippet)+' ('+esc(r.url)+')').join('\\n');
      }
    }
    const kr=await fetch('/api/knowledge/query?q='+encodeURIComponent(txt)+'&top_k=5');
    const kd=await kr.json();
    if(kd.results&&kd.results.length){
      ctx+='\\n\\nKnowledge base results:\\n'+kd.results.map(r=>'['+esc(r.filename)+'] '+esc(r.text)).join('\\n');
    }
    const _model=_('modelSel').value||_models[0]||'';
    const body=JSON.stringify({sid:_sid,message:txt,context:ctx||undefined,model:_model,stream:true});
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body});
    if(!r.ok){const d=await r.json();addMsg('ass','Error: '+esc(d.error||'Unknown'));_sending=false;_('sndBtn').disabled=false;_('sndBtn').textContent='Send';return;}
    const reader=r.body.getReader(); const decoder=new TextDecoder();
    let buf='', msgEl=null, full='', _sources=null;
    while(true){
      const{value,done}=await reader.read();
      if(done)break;
      buf+=decoder.decode(value,{stream:true});
      const lines=buf.split('\n'); buf=lines.pop()||'';
      for(const line of lines){
        if(!line.startsWith('data: '))continue;
        const d=JSON.parse(line.slice(6));
        if(d.done){_sid=d.sid;if(d.sources&&d.sources.length)_sources=d.sources;}
        else if(d.error){addMsg('ass','Error: '+esc(d.error));}
        else if(d.token){
          if(!msgEl){const el=document.createElement('div');el.className='msg ass';_('cht').appendChild(el);msgEl=el;}
          full+=d.token; msgEl.innerHTML=md(full); _('cht').scrollTop=_('cht').scrollHeight;
        }
      }
    }
    // Flush remaining buffer
    if(buf.startsWith('data: ')){
      try{const d=JSON.parse(buf.slice(6));if(d.done){_sid=d.sid;if(d.sources&&d.sources.length)_sources=d.sources;}}catch(e){}
    }
    if(_sources&&_sources.length)addMsg('ass','**Sources:** '+_sources.map(s=>'`'+esc(s.filename)+'`').join(', '),'');
    loadSessions(); loadStats();
  }catch(e){
    addMsg('ass','Error: '+esc(e.message));
  }
  _sending=false; _('sndBtn').disabled=false; _('sndBtn').textContent='Send';
}

async function loadModels(){
  try{
    const r=await fetch('/api/models'); const d=await r.json();
    _models=d.models||[];
    const sel=_('modelSel'); sel.innerHTML='';
    _models.forEach(m=>{
      const o=document.createElement('option');
      o.value=m; o.textContent=m;
      if(m===localStorage.getItem('ccModel')||m===_models[0])o.selected=true;
      sel.appendChild(o);
    });
  }catch(e){console.error('models',e)}
}

function switchModel(m){
  localStorage.setItem('ccModel',m);
}

async function loadStats(){
  try{
    const r=await fetch('/api/stats'); const d=await r.json();
    _('stats').textContent=d.files+' files';
  }catch(e){}
}

async function loadKB(){
  try{
    const r=await fetch('/api/knowledge/files'); const d=await r.json();
    const list=_('kbList'); list.innerHTML='';
    _('kbCount').textContent='('+(d.files||[]).length+'/'+d.max+')';
    (d.files||[]).forEach(f=>{
      const div=document.createElement('div'); div.className='kbf';
      div.innerHTML='<span class="kbf-name">'+esc(f.name)+'</span><span class="kbf-size">'+fmtSize(f.size)+'</span>';
      const rm=document.createElement('button'); rm.className='kbf-rm'; rm.textContent='✕';
      rm.onclick=async e=>{e.stopPropagation();if(confirm('Delete '+f.name+'?')){await fetch('/api/knowledge/delete/'+encodeURIComponent(f.name),{method:'POST'});loadKB();loadStats();}};
      div.appendChild(rm);
      list.appendChild(div);
    });
    if(!(d.files||[]).length)list.innerHTML='<div class="kb-empty">Drop files or click 📎 to add knowledge.</div>';
  }catch(e){console.error('kb',e)}
}

function fmtSize(s){if(!s)return'0B';if(s<1024)return s+'B';if(s<1048576)return(s/1024).toFixed(1)+'KB';return(s/1048576).toFixed(1)+'MB'}

function toggleKB(){
  _kbOpen=!_kbOpen;
  _('kbPanel').classList.toggle('open',_kbOpen);
  _('kbBtn').classList.toggle('act',_kbOpen);
  if(_kbOpen)loadKB();
}

function toggleSearch(){
  _wsOn=!_wsOn;
  _('wsBtn').classList.toggle('act',_wsOn);
}

function clearCtx(){
  if(!_sid)return;
  fetch('/api/context/clear/'+_sid,{method:'POST'});
  _('cht').innerHTML='';
}

async function uploadFile(input){
  const file=input.files[0]; if(!file)return;
  if(file.size>10485760){alert('Max 10MB');input.value='';return}
  const fd=new FormData(); fd.append('file',file);
  try{
    const r=await fetch('/api/knowledge/upload',{method:'POST',body:fd});
    const d=await r.json();
    if(d.ok)loadKB();
    else alert(d.error||'Upload failed');
  }catch(e){alert('Upload error');}
  input.value='';
}

function toggleTheme(){
  document.body.classList.toggle('light');
  _('togBtn').textContent=document.body.classList.contains('light')?'☀':'☽';
  localStorage.setItem('ccTheme',document.body.classList.contains('light')?'light':'dark');
}

function openPro(){window.open('https://api.contextcut-pro.com','_blank')}

// Init
(function(){
  const t=localStorage.getItem('ccTheme');
  if(t==='light'){document.body.classList.add('light');_('togBtn').textContent='☀'}
  loadModels(); loadSessions(); loadStats(); newSession();
})();
</script>
</body></html>"""

# ── HTTP handlers ─────────────────────────────────────────────
def _json(data, status=200):
    body = json.dumps(data).encode()
    return status, {"Content-Type": "application/json", "Content-Length": str(len(body))}, body

def _html(body, status=200):
    b = body.encode() if isinstance(body, str) else body
    ct = "text/html;charset=UTF-8"
    return status, {"Content-Type": ct, "Content-Length": str(len(b))}, b

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def _send(self, status, headers, body):
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _parse_qs(self):
        from urllib.parse import urlparse, parse_qs
        return parse_qs(urlparse(self.path).query)

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path == "/":
                return self._send(*_html(DASHBOARD_HTML))
            if path == "/api/models":
                models = _list_models()
                return self._send(*_json({"models": models}))
            if path == "/api/sessions":
                with _db_lock:
                    db = _get_db()
                    rows = db.execute("SELECT sid, name, updated FROM sessions ORDER BY updated DESC").fetchall()
                    db.close()
                sessions = [{"sid": r[0], "name": r[1], "updated": r[2]} for r in rows]
                return self._send(*_json({"sessions": sessions}))
            if path.startswith("/api/session/load/"):
                sid = path.split("/api/session/load/")[-1]
                with _db_lock:
                    db = _get_db()
                    rows = db.execute("SELECT role, content FROM messages WHERE sid=? ORDER BY mid", (sid,)).fetchall()
                    db.close()
                messages = [{"role": r[0], "content": r[1]} for r in rows]
                return self._send(*_json({"messages": messages}))
            if path == "/api/knowledge/files":
                files = []
                for f in KB_DIR.iterdir():
                    if f.is_file() and f.suffix.lower() in ALLOWED_EXT:
                        files.append({"name": f.name, "size": f.stat().st_size, "path": str(f)})
                return self._send(*_json({"files": files, "max": MAX_FILES}))
            if path.startswith("/api/knowledge/delete/"):
                name = urllib.parse.unquote(path.split("/api/knowledge/delete/")[-1])
                _delete_file(name)
                return self._send(*_json({"ok": True}))
            if path == "/api/knowledge/query":
                qs = self._parse_qs()
                q = qs.get("q", [""])[0]
                top_k = int(qs.get("top_k", ["5"])[0])
                results = _query_kb(q, top_k) if q else []
                return self._send(*_json({"results": results}))
            if path == "/api/search/web":
                qs = self._parse_qs()
                q = qs.get("q", [""])[0]
                results = _web_search(q) if q else []
                return self._send(*_json({"results": results}))
            if path == "/api/stats":
                count = _count_files()
                return self._send(*_json({"files": count}))
            if path == "/favicon.ico":
                svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#10b981"/><text x="16" y="22" text-anchor="middle" font-family="Arial,sans-serif" font-size="18" font-weight="800" fill="#000">CC</text></svg>'
                b = svg.encode()
                return self._send(200, {"Content-Type": "image/svg+xml", "Content-Length": str(len(b)), "Cache-Control": "public, max-age=86400"}, b)
            return self._send(*_json({"error": "Not found"}, 404))
        except Exception as e:
            return self._send(*_json({"error": str(e)}, 500))

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            if path == "/api/session/new":
                sid = hashlib.md5(os.urandom(16)).hexdigest()[:16]
                now = time.time()
                with _db_lock:
                    db = _get_db()
                    db.execute("INSERT INTO sessions (sid, name, created, updated, context) VALUES (?,?,?,?,?)",
                               (sid, "New session", now, now, ""))
                    db.commit()
                    db.close()
                return self._send(*_json({"sid": sid}))
            if path == "/api/chat":
                body = json.loads(self._read_body())
                stream = body.get("stream", False)
                sid = body.get("sid")
                msg = body.get("message", "")
                ctx = body.get("context", "")
                model = body.get("model") or CHAT_MODEL
                now = time.time()

                messages = []
                if ctx:
                    messages.append({"role": "system", "content": f"You are a helpful assistant. Use the following context if relevant:\n\n{ctx}"})
                messages.append({"role": "user", "content": msg})

                # Session + user message (shared by both paths)
                if not sid:
                    sid = hashlib.md5(os.urandom(16)).hexdigest()[:16]
                    with _db_lock:
                        db = _get_db()
                        db.execute("INSERT INTO sessions (sid, name, created, updated, context) VALUES (?,?,?,?,?)",
                                   (sid, msg[:50], now, now, ""))
                        db.commit()
                        db.close()
                else:
                    with _db_lock:
                        db = _get_db()
                        db.execute("UPDATE sessions SET updated=? WHERE sid=?", (now, sid))
                        db.commit()
                        db.close()

                with _db_lock:
                    db = _get_db()
                    db.execute("INSERT INTO messages (sid, role, content, model, created) VALUES (?,?,?,?,?)",
                               (sid, "user", msg, model, now))
                    db.commit()
                    db.close()

                if stream:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    full_reply = ""
                    try:
                        for chunk in _chat_stream_yield(messages, model=model):
                            delta = chunk.get("message", {}).get("content", "")
                            if delta:
                                full_reply += delta
                                event = json.dumps({"token": delta, "done": False})
                                self.wfile.write(f"data: {event}\n\n".encode())
                                self.wfile.flush()
                    except Exception as e:
                        self.wfile.write(f"data: {json.dumps({'error': str(e)})}\n\n".encode())
                        self.wfile.flush()
                    # Save assistant message
                    with _db_lock:
                        db = _get_db()
                        db.execute("INSERT INTO messages (sid, role, content, model, created) VALUES (?,?,?,?,?)",
                                   (sid, "assistant", full_reply, model, now))
                        db.commit()
                        db.close()
                    # Knowledge sources
                    kresults = _query_kb(msg, 3)
                    sources = [{"filename": r["filename"], "score": r["score"]} for r in kresults] if kresults else []
                    final = json.dumps({"done": True, "sid": sid, "sources": sources})
                    self.wfile.write(f"data: {final}\n\n".encode())
                    self.wfile.flush()
                    return

                # Non-streaming path
                try:
                    resp = _chat(messages, model=model)
                    reply = resp.get("message", {}).get("content", "")
                    if not reply:
                        reply = resp.get("response", "")
                except Exception as e:
                    return self._send(*_json({"error": str(e)}, 500))

                with _db_lock:
                    db = _get_db()
                    db.execute("INSERT INTO messages (sid, role, content, model, created) VALUES (?,?,?,?,?)",
                               (sid, "assistant", reply, model, now))
                    db.commit()
                    db.close()

                kresults = _query_kb(msg, 3)
                sources = [{"filename": r["filename"], "score": r["score"]} for r in kresults] if kresults else []

                return self._send(*_json({"ok": True, "sid": sid, "reply": reply, "sources": sources}))

            if path.startswith("/api/session/delete/"):
                sid = path.split("/api/session/delete/")[-1]
                with _db_lock:
                    db = _get_db()
                    db.execute("DELETE FROM messages WHERE sid=?", (sid,))
                    db.execute("DELETE FROM sessions WHERE sid=?", (sid,))
                    db.commit()
                    db.close()
                return self._send(*_json({"ok": True}))

            if path.startswith("/api/context/clear/"):
                sid = path.split("/api/context/clear/")[-1]
                with _db_lock:
                    db = _get_db()
                    db.execute("DELETE FROM messages WHERE sid=?", (sid,))
                    db.commit()
                    db.close()
                return self._send(*_json({"ok": True}))

            if path == "/api/knowledge/upload":
                ct = self.headers.get("Content-Type", "")
                if "multipart/form-data" in ct:
                    import cgi
                    form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"})
                    fitem = form["file"]
                    name = fitem.filename
                    raw = fitem.file.read()
                else:
                    body = json.loads(self._read_body())
                    name = body.get("name", "")
                    raw = body.get("content", "").encode() if isinstance(body.get("content", ""), str) else b""

                if not name:
                    return self._send(*_json({"error": "No filename"}, 400))
                ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext not in ALLOWED_EXT:
                    return self._send(*_json({"error": "File type not supported"}, 400))
                if len(raw) > MAX_FILE_SIZE:
                    return self._send(*_json({"error": "File too large (max 10MB)"}, 400))
                current = _count_files()
                if current >= MAX_FILES and not (KB_DIR / name).exists():
                    return self._send(*_json({"error": f"File limit ({MAX_FILES}) reached. Upgrade to PRO for unlimited."}, 400))

                _write_file(name, raw)
                if HAVE_FAISS:
                    ing = _ingest_file(name)
                else:
                    ing = {"ok": True, "chunks": 0}
                return self._send(*_json({"ok": True, "ingest": ing}))
        except Exception as e:
            return self._send(*_json({"error": str(e)}, 500))

# ── Main ──────────────────────────────────────────────────────
def main():
    if not HAVE_FAISS:
        print("[cc-free] FAISS not installed — pip install faiss-cpu numpy")
    print(f"[cc-free] v{VERSION}")
    print(f"[cc-free] Dashboard: http://localhost:{PROXY_PORT}")
    print(f"[cc-free] Ollama:    {OLLAMA_URL}")
    print(f"[cc-free] KB dir:    {KB_DIR}")
    print(f"[cc-free] Data dir:  {DATA_DIR}")
    print(f"[cc-free] Files:     {_count_files()}/{MAX_FILES}")
    srv = http.server.HTTPServer(("127.0.0.1", PROXY_PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[cc-free] Shutting down.")
        srv.server_close()

if __name__ == "__main__":
    main()
