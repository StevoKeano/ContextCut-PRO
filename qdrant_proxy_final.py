#!/usr/bin/env python3
"""
ContextCut-PRO — Qdrant-enriching reverse proxy for any local LLM endpoint.

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
import sys
import uuid
import json
import html
import time
import socket
import random
import threading
import platform
import hashlib
import base64
import urllib.request
import urllib.error
from collections import deque
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

import voyageai
from qdrant_client import QdrantClient

# ── Secure Credential Manager (Machine-bound encryption) ─────────────────────
class CredentialManager:
    """Stores API keys encrypted with a machine-derived key.
    If copied to another machine, the file is useless."""

    _cred_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".contextcut_creds.enc")

    @staticmethod
    def _machine_key():
        raw = ""
        try:
            if platform.system() == "Linux":
                with open("/etc/machine-id") as f: raw = f.read().strip()
            elif platform.system() == "Darwin":
                import subprocess
                raw = subprocess.check_output(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"]).decode().strip()
            else:
                raw = platform.node()
        except Exception:
            raw = "fallback-constant-key"
        return hashlib.sha256(raw.encode()).digest()

    @classmethod
    def _get_fernet(cls):
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(cls._machine_key())
        return Fernet(key)

    @classmethod
    def save(cls, key_name, value):
        creds = cls.load_all()
        creds[key_name] = value
        f = cls._get_fernet()
        encrypted = f.encrypt(json.dumps(creds).encode())
        with open(cls._cred_file, "wb") as fh: fh.write(encrypted)
        os.chmod(cls._cred_file, 0o600)

    @classmethod
    def get(cls, key_name):
        return cls.load_all().get(key_name)

    @classmethod
    def load_all(cls):
        if not os.path.exists(cls._cred_file): return {}
        try:
            f = cls._get_fernet()
            with open(cls._cred_file, "rb") as fh: encrypted = fh.read()
            return json.loads(f.decrypt(encrypted).decode())
        except Exception:
            return {}

# ── Config ────────────────────────────────────────────────────────────────────
UPSTREAM       = os.getenv("CONTEXTCUT_UPSTREAM",        "http://localhost:11434")
QDRANT_HOST    = os.getenv("CONTEXTCUT_QDRANT_HOST",     "localhost")
QDRANT_PORT    = int(os.getenv("CONTEXTCUT_QDRANT_PORT", "6333"))
COLLECTION     = os.getenv("CONTEXTCUT_COLLECTION",      "contextcut")
LISTEN_PORT    = int(os.getenv("CONTEXTCUT_PROXY_PORT",     "18788"))
DASHBOARD_PORT = int(os.getenv("CONTEXTCUT_DASHBOARD_PORT", "18787"))
CTX_LIMIT      = int(os.getenv("CONTEXTCUT_CTX_LIMIT",   "8192"))
TOP_K          = int(os.getenv("CONTEXTCUT_TOP_K",       "5"))
MIN_SCORE      = float(os.getenv("CONTEXTCUT_MIN_SCORE", "0.20"))
DEFAULT_MODEL  = os.getenv("CONTEXTCUT_MODEL",           "")

# ── Dynamic Provider Settings ────────────────────────────────────────────────
PROVIDERS = {
    "Ollama":     {"url": "http://localhost:11434", "key_required": False},
    "OpenAI":     {"url": "https://api.openai.com", "key_required": True},
    "OpenRouter": {"url": "https://openrouter.ai/api", "key_required": True},
    "Anthropic":  {"url": "https://api.anthropic.com", "key_required": True},
    "xAI":        {"url": "https://api.x.ai", "key_required": True},
    "Custom":     {"url": "", "key_required": True},
}
_provider_name = "Ollama"
_custom_base_url = ""
_api_key = ""  # Stored in memory, loaded from encrypted file on startup

def load_saved_credentials():
    global _provider_name, _custom_base_url, _api_key, UPSTREAM
    creds = CredentialManager.load_all()
    _provider_name = creds.get("provider", "Ollama")
    _custom_base_url = creds.get("custom_url", "")
    _api_key = creds.get("api_key", "")
    saved_ollama_url = creds.get("ollama_url", "")
    if _provider_name == "Ollama" and saved_ollama_url:
        UPSTREAM = saved_ollama_url

def get_current_upstream():
    global _provider_name, _custom_base_url
    if _provider_name == "Custom":
        return _custom_base_url
    if _provider_name == "Ollama":
        return UPSTREAM
    base = PROVIDERS.get(_provider_name, {}).get("url", "")
    return base + "/v1"

def get_current_api_key():
    return _api_key if PROVIDERS.get(_provider_name, {}).get("key_required") else None

load_saved_credentials()
DEFAULT_TEMP   = float(os.getenv("CONTEXTCUT_TEMP",      "0.7"))
DEFAULT_MAX_TK = int(os.getenv("CONTEXTCUT_MAX_TOKENS",  "0"))
DEFAULT_TOP_P  = float(os.getenv("CONTEXTCUT_TOP_P",     "1.0"))

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
    "cache_hits":      0,
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

# ── Cache for frequent queries ───────────────────────────────────────────────
CACHE_MAX_SIZE = 100
CACHE_TTL      = 300
_response_cache: dict[str, dict] = {}

def cache_key(query: str, model: str) -> str:
    return f"{model}:{query.strip().lower()}"

def cache_get(query: str, model: str) -> str | None:
    with _lock:
        key = cache_key(query, model)
        entry = _response_cache.get(key)
        if entry and (time.time() - entry["ts"]) < CACHE_TTL:
            _stats["cache_hits"] += 1
            return entry["response"]
        if entry:
            del _response_cache[key]
        return None

def cache_put(query: str, model: str, response: str):
    with _lock:
        if len(_response_cache) >= CACHE_MAX_SIZE:
            oldest = min(_response_cache, key=lambda k: _response_cache[k]["ts"])
            del _response_cache[oldest]
        key = cache_key(query, model)
        _response_cache[key] = {"response": response, "ts": time.time()}

# ── 2b: Session Management ───────────────────────────────────────────────────
MAX_HISTORY_MESSAGES = 50
MAX_HISTORY_TOKENS   = 4096

_sessions: dict[str, dict] = {}

def new_session() -> str:
    sid = str(uuid.uuid4())[:8]
    _sessions[sid] = {"history": [], "created": datetime.now().isoformat(), "msg_count": 0}
    return sid

def get_session(sid: str) -> dict | None:
    if sid and sid in _sessions:
        return _sessions[sid]
    return None

def add_to_history(sid: str, role: str, content: str):
    session = _sessions.get(sid)
    if not session:
        return
    session["history"].append({"role": role, "content": content})
    session["msg_count"] += 1
    _trim_history(session)

def clear_session(sid: str):
    session = _sessions.get(sid)
    if session:
        session["history"] = []
        session["msg_count"] = 0

def _trim_history(session: dict):
    while len(session["history"]) > MAX_HISTORY_MESSAGES:
        session["history"].pop(0)
    total = sum(count_tokens(m["content"]) for m in session["history"])
    while total > MAX_HISTORY_TOKENS and len(session["history"]) > 2:
        removed = session["history"].pop(0)
        total -= count_tokens(removed["content"])

def build_messages_with_history(sid: str, new_user_msg: str) -> list[dict]:
    session = _sessions.get(sid)
    if not session or not session["history"]:
        return [{"role": "user", "content": new_user_msg}]
    return session["history"] + [{"role": "user", "content": new_user_msg}]

def detect_dynamic_action(content: str) -> str | None:
    lower = content.strip().lower()
    if lower in ("stop", "halt", "cease", "that's enough", "thats enough", "that is enough"):
        return "stop"
    if lower in ("continue", "go on", "keep going", "more", "elaborate"):
        return "continue"
    if lower.startswith("revise") or lower.startswith("rewrite") or lower.startswith("rephrase"):
        return "revise"
    return None

def build_revision_prompt(last_user: str, last_assistant: str, revision_request: str) -> list[dict]:
    return [
        {"role": "user", "content": last_user},
        {"role": "assistant", "content": last_assistant},
        {"role": "user", "content": f"{revision_request}. Please revise your previous response accordingly."},
    ]

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".contextcut_sessions.json")

def save_sessions():
    try:
        data = {}
        with _lock:
            for sid, sess in _sessions.items():
                data[sid] = {"history": sess["history"], "created": sess["created"], "msg_count": sess["msg_count"]}
        with open(SESSION_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[contextcut] Session save error: {e}")

def load_sessions():
    if not os.path.exists(SESSION_FILE):
        return
    try:
        with open(SESSION_FILE) as f:
            data = json.load(f)
        with _lock:
            for sid, sess in data.items():
                _sessions[sid] = {"history": sess["history"], "created": sess["created"], "msg_count": sess["msg_count"]}
        print(f"[contextcut] Loaded {len(data)} sessions from {SESSION_FILE}")
    except Exception as e:
        print(f"[contextcut] Session load error: {e}")
def check_license_status() -> dict:
    with _lock:
        return dict(_license_state)

def release_license():
    if not LICENSE_KEY or not _license_state.get("valid"):
        return
    try:
        payload = json.dumps({
            "license_key": LICENSE_KEY,
            "instance_id": _instance_id,
        }).encode()
        req = urllib.request.Request(
            f"{LICENSE_SERVER}/v1/license/release",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "ContextCutPRO/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        print(f"[contextcut] License seat released: {data.get('message','OK')}")
    except Exception as e:
        print(f"[contextcut] License release error (non-fatal): {e}")

def shutdown_hook():
    release_license()
    save_sessions()
import atexit
atexit.register(shutdown_hook)

# ── License Validation ────────────────────────────────────────────────────────
LICENSE_SERVER  = os.getenv("CONTEXTCUT_LICENSE_SERVER", "https://api.contextcut.pro")
LICENSE_KEY     = os.getenv("CONTEXTCUT_LICENSE_KEY", "")
HEARTBEAT_INTERVAL = int(os.getenv("CONTEXTCUT_HEARTBEAT_SEC", "900"))
GRACE_PERIOD    = int(os.getenv("CONTEXTCUT_GRACE_SEC", "3600"))

_license_state = {
    "valid":        False,
    "activated_at": None,
    "last_heartbeat": None,
    "expires_at":   None,
    "license_type": None,
    "seats":        0,
    "message":      "",
    "grace_since":  None,
}

_instance_id = str(uuid.uuid4())

def get_fingerprint() -> dict:
    import platform
    import hashlib
    mac_addr = ""
    try:
        import uuid
        mac_addr = str(uuid.getnode())
    except Exception:
        pass
    return {
        "hostname":    socket.gethostname(),
        "platform":    platform.platform(),
        "node":        mac_addr,
    }

def validate_license() -> bool:
    global _license_state
    if not LICENSE_KEY:
        _license_state["message"] = "No license key provided. Set CONTEXTCUT_LICENSE_KEY."
        return False
    try:
        fp = get_fingerprint()
        payload = json.dumps({
            "license_key": LICENSE_KEY,
            "instance_id": _instance_id,
            "fingerprint": fp,
            "version":     "PRO-1.0",
            "action":      "activate",
        }).encode()
        req = urllib.request.Request(
            f"{LICENSE_SERVER}/v1/license/validate",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "ContextCutPRO/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        if data.get("valid"):
            _license_state.update({
                "valid":        True,
                "activated_at": data.get("activated_at"),
                "license_type": data.get("license_type", "single"),
                "seats":        data.get("seats", 1),
                "expires_at":   data.get("expires_at"),
                "message":      data.get("message", "License validated"),
            })
            return True
        else:
            _license_state["message"] = data.get("error", "License invalid")
            return False
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            err = json.loads(body)
            _license_state["message"] = err.get("error", f"HTTP {e.code}")
        except Exception:
            _license_state["message"] = f"HTTP {e.code}: {body}"
        return False
    except urllib.error.URLError as e:
        _license_state["message"] = f"Network error: {e.reason}"
        return False
    except Exception as e:
        _license_state["message"] = f"Validation error: {e}"
        return False

def send_heartbeat() -> bool:
    if not LICENSE_KEY:
        return False
    try:
        payload = json.dumps({
            "license_key":  LICENSE_KEY,
            "instance_id":  _instance_id,
            "uptime":       time.time(),
            "fingerprint":  get_fingerprint(),
        }).encode()
        req = urllib.request.Request(
            f"{LICENSE_SERVER}/v1/heartbeat",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "ContextCutPRO/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        _license_state["last_heartbeat"] = datetime.now().isoformat()
        if not data.get("valid", True):
            _license_state["valid"] = False
            _license_state["message"] = data.get("error", "Heartbeat rejected")
            return False
        return True
    except Exception:
        if _license_state["valid"] and not _license_state["grace_since"]:
            _license_state["grace_since"] = time.time()
        elif _license_state["grace_since"]:
            elapsed = time.time() - _license_state["grace_since"]
            if elapsed > GRACE_PERIOD:
                _license_state["valid"] = False
                _license_state["message"] = f"License grace period expired ({GRACE_PERIOD}s)"
                return False
        return True

def heartbeat_loop():
    time.sleep(HEARTBEAT_INTERVAL)
    while True:
        send_heartbeat()
        time.sleep(HEARTBEAT_INTERVAL)



import signal
def _handle_signal(signum, frame):
    print("\n[contextcut] Shutting down gracefully...")
    shutdown_hook()
    raise SystemExit(0)

signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

# ── Lazy clients ──────────────────────────────────────────────────────────────
_vc            = None
_qclient       = None
_last_embed_ts = 0.0
_VK            = os.environ.get("VOYAGE_API_KEY", "").strip().strip('"').strip("'")  # strip accidental quotes

def get_clients():
    global _vc, _qclient
    if _vc is None:
        if not _VK:
            print("[contextcut] WARNING: VOYAGE_API_KEY is empty at get_clients()")
        else:
            print(f"[contextcut] Voyage API key loaded: {_VK[:8]}...")
        _vc = voyageai.Client(api_key=_VK)
    if _qclient is None:
        _qclient = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    return _vc, _qclient

# ── Qdrant lookup ─────────────────────────────────────────────────────────────
def _safe_embed(query: str, input_type: str) -> list[float] | None:
    """Embed with retry on rate limit (matches ingest.py safe_embed)."""
    global _last_embed_ts
    max_retries = 3
    for attempt in range(max_retries):
        elapsed = time.time() - _last_embed_ts
        if elapsed < 22.0:
            time.sleep(22.0 - elapsed)
        try:
            vc, _ = get_clients()
            result = vc.embed([query], model="voyage-3", input_type=input_type)
            _last_embed_ts = time.time()
            return result.embeddings[0]
        except Exception as e:
            err_msg = str(e).lower()
            if "rate" in err_msg or "429" in err_msg:
                wait = 60 + random.uniform(5, 15)
                print(f"[contextcut] Voyage rate-limited, backing off {wait:.0f}s (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
            else:
                print(f"[contextcut] Voyage embed error: {e}")
                print(f"[contextcut] API key present: {bool(_VK)}, first 4 chars: {_VK[:4] if _VK else 'NONE'}")
                return None
    print(f"[contextcut] Voyage embed failed after {max_retries} retries")
    return None

def qdrant_context(query: str) -> tuple[str, list[dict]]:
    try:
        emb = _safe_embed(query, input_type="query")
        if emb is None:
            print(f"[contextcut] qdrant_context: embed returned None for query={query[:60]!r}")
            return "", []
        vc, qclient = get_clients()
        response = qclient.query_points(
            collection_name=COLLECTION, query=emb,
            limit=TOP_K, with_payload=True, with_vectors=False,
        )
        chunks, meta = [], []
        for h in response.points:
            score = round(h.score, 3)
            if score < MIN_SCORE:
                print(f"[contextcut] skip score={score} < {MIN_SCORE} for {h.payload.get('filename','?')}")
                continue
            src   = h.payload.get("filename", h.payload.get("source", "?"))
            text  = h.payload.get("text", "")
            chunks.append(f"[{src} | relevance={score}]\n{text}")
            meta.append({"source": src, "score": score, "chars": len(text)})
        if meta:
            print(f"[contextcut] qdrant_context: {len(meta)} hits for query={query[:60]!r}")
        else:
            print(f"[contextcut] qdrant_context: 0 hits for query={query[:60]!r}")
        return "\n\n---\n\n".join(chunks), meta
    except Exception as e:
        print(f"[contextcut] Qdrant error: {e}")
        import traceback; traceback.print_exc()
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

# ── Broken-pipe suppression mixin ────────────────────────────────────────────
class _SuppressBrokenPipe:
    """Silently swallow BrokenPipeError / ConnectionResetError from client disconnects."""
    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass

# ── Proxy ─────────────────────────────────────────────────────────────────────
class ProxyHandler(_SuppressBrokenPipe, BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def _forward(self, method: str, raw_body: bytes, streaming: bool = False, session_id: str = None):
        upstream = get_current_upstream()
        
        # Cloud providers use {base}/v1/chat/completions, Ollama uses {base}/v1/chat/completions too
        upstream_url = upstream + self.path
        
        req = urllib.request.Request(upstream_url, data=raw_body if method == "POST" else None, method=method)
        
        # Inject API key header for cloud providers
        api_key = get_current_api_key()
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")

        for k, v in self.headers.items():
            if k.lower() not in ("host", "content-length"):
                req.add_header(k, v)
        if raw_body:
            req.add_header("Content-Length", str(len(raw_body)))
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding", "content-length"):
                        self.send_header(k, v)
                if streaming:
                    self.send_header("Transfer-Encoding", "chunked")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    full_response = []
                    while True:
                        chunk = resp.read(4096)
                        if not chunk:
                            self.wfile.write(b"0\r\n\r\n")
                            if session_id and full_response:
                                add_to_history(session_id, "assistant", "".join(full_response))
                            break
                        size = f"{len(chunk):X}\r\n".encode()
                        self.wfile.write(size + chunk + b"\r\n")
                        self.wfile.flush()
                        try:
                            text = chunk.decode("utf-8", errors="ignore")
                            for line in text.split("\n"):
                                line = line.strip()
                                if line.startswith("data: ") and line != "data: [DONE]":
                                    try:
                                        chunk_data = json.loads(line[6:])
                                        delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                                        content = delta.get("content", "")
                                        if content:
                                            full_response.append(content)
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                else:
                    resp_body = resp.read()
                    self.send_header("Content-Length", str(len(resp_body)))
                    self.end_headers()
                    self.wfile.write(resp_body)
                    if session_id:
                        try:
                            resp_json = json.loads(resp_body)
                            assistant_msg = resp_json.get("choices", [{}])[0].get("message", {}).get("content", "")
                            if assistant_msg:
                                add_to_history(session_id, "assistant", assistant_msg)
                        except Exception:
                            pass
        except urllib.error.HTTPError as e:
            err_body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(err_body)))
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
            session_id = body.pop("session_id", None)
            use_history = body.pop("use_history", True)

            if use_history:
                if not session_id or session_id not in _sessions:
                    session_id = new_session()
                body["session_id"] = session_id

                new_user_content = body["messages"][-1].get("content", "") if body["messages"] else ""
                action = detect_dynamic_action(new_user_content)

                if action == "revise":
                    session = _sessions.get(session_id)
                    if session and session["history"]:
                        last_user = ""
                        last_assistant = ""
                        for msg in reversed(session["history"]):
                            if msg["role"] == "assistant" and not last_assistant:
                                last_assistant = msg["content"]
                            elif msg["role"] == "user" and not last_user:
                                last_user = msg["content"]
                                break
                        if last_assistant:
                            body["messages"] = build_revision_prompt(last_user, last_assistant, new_user_content)

                elif action == "continue":
                    session = _sessions.get(session_id)
                    if session and session["history"]:
                        body["messages"] = list(session["history"])
                        body["messages"].append({"role": "user", "content": "Please continue your previous response."})

                elif action != "stop":
                    if len(body["messages"]) == 1:
                        body["messages"] = build_messages_with_history(session_id, new_user_content)

                add_to_history(session_id, "user", new_user_content)

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

        is_streaming = isinstance(body, dict) and body.get("stream", False)
        self._forward("POST", raw_body, streaming=is_streaming, session_id=body.get("session_id") if body else None)

    def do_DELETE(self):
        if self.path.startswith("/api/session/"):
            session_id = self.path.split("/api/session/")[-1]
            clear_session(session_id)
            resp = json.dumps({"status": "cleared", "session_id": session_id}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return
        self.send_response(404)
        self.end_headers()

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

    no_rows = '<tr><td colspan="6" class="empty">No requests yet — send a message below</td></tr>'

    return f"""<!DOCTYPE html>
"""

def make_settings_page():
    current_provider = _provider_name
    current_url = _custom_base_url if current_provider == "Custom" else PROVIDERS.get(current_provider, {}).get("url", "")
    if current_provider == "Ollama":
        current_url = UPSTREAM
    has_key = bool(_api_key)
    masked_key = "••••••••••••••••" if has_key else ""
    provider_opts = "".join(f'<option value="{k}" {"selected" if k==current_provider else ""}>{k}</option>' for k in PROVIDERS.keys())
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ContextCut-PRO — Settings</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
<style>
:root{{--bg:#080c14;--surf:#0d1420;--surf2:#111927;--border:#1e2d42;--text:#c9d8f0;--muted:#4a6080;--accent:#00d4ff;--green:#22c55e;--yellow:#f59e0b;--red:#ef4444;--r:6px}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'JetBrains Mono',monospace;font-size:13px;display:flex;flex-direction:column;height:100vh}}
.header{{background:var(--surf);border-bottom:1px solid var(--border);padding:0 20px;display:flex;align-items:center;gap:14px;height:48px;flex-shrink:0}}
.logo{{font-family:'Syne',sans-serif;font-size:20px;font-weight:800;color:var(--accent);letter-spacing:-.5px}}
.logo span{{color:var(--text)}}
.back-btn{{background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:3px 10px;font-size:11px;cursor:pointer;font-family:'JetBrains Mono',monospace;margin-left:auto;text-decoration:none}}
.back-btn:hover{{color:var(--text);border-color:var(--accent)}}
.container{{flex:1;overflow-y:auto;padding:20px;display:flex;justify-content:center}}
.card{{background:var(--surf);border:1px solid var(--border);border-radius:var(--r);padding:20px;width:100%;max-width:500px}}
.card h2{{font-family:'Syne',sans-serif;font-size:18px;margin-bottom:16px;color:var(--accent)}}
.form-group{{margin-bottom:16px}}
.form-group label{{display:block;font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px}}
.form-group select,.form-group input{{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:var(--r);padding:8px 12px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:13px;outline:none}}
.form-group select:focus,.form-group input:focus{{border-color:var(--accent)}}
.form-group select{{cursor:pointer}}
.form-group select option{{background:var(--surf);color:var(--text)}}
.btn{{background:var(--accent);color:#000;border:none;border-radius:var(--r);padding:8px 16px;font-family:'Syne',sans-serif;font-weight:700;font-size:13px;cursor:pointer}}
.btn:hover{{opacity:.85}}
.btn:disabled{{opacity:.4;cursor:not-allowed}}
.btn-secondary{{background:transparent;border:1px solid var(--border);color:var(--muted)}}
.btn-secondary:hover{{color:var(--text);border-color:var(--accent)}}
.btn-row{{display:flex;gap:8px;margin-top:8px}}
#modelList{{max-height:200px;overflow-y:auto;background:var(--bg);border:1px solid var(--border);border-radius:var(--r);padding:8px;margin-top:8px;display:none}}
#modelList.show{{display:block}}
#modelList div{{padding:6px 8px;cursor:pointer;border-radius:3px;font-size:12px}}
#modelList div:hover{{background:var(--surf2);color:var(--accent)}}
.status{{font-size:11px;margin-top:8px;min-height:16px}}
.status.ok{{color:var(--green)}}
.status.err{{color:var(--red)}}
.hidden{{display:none}}
</style>
</head>
<body>
<div class="header">
  <div class="logo">ContextCut<span>-PRO</span></div>
  <a href="/" class="back-btn">← Back to Dashboard</a>
</div>
<div class="container">
  <div class="card">
    <h2>LLM Provider Settings</h2>
    
    <div class="form-group">
      <label>Provider</label>
      <select id="providerSelect" onchange="onProviderChange()">
        {provider_opts}
      </select>
    </div>

    <div class="form-group hidden" id="ollamaUrlGroup">
      <label>Ollama URL</label>
      <input type="text" id="ollamaUrl" value="{current_url}" placeholder="http://localhost:11434">
    </div>

    <div class="form-group hidden" id="customUrlGroup">
      <label>Base URL</label>
      <input type="text" id="customUrl" placeholder="https://api.example.com/v1">
    </div>

    <div class="form-group">
      <label>API Key</label>
      <input type="password" id="apiKey" value="{masked_key}" placeholder="Enter your API key">
      <div style="font-size:10px;color:var(--muted);margin-top:4px">Stored encrypted on disk. Only your machine can decrypt it.</div>
    </div>

    <div class="form-group">
      <label>Available Models</label>
      <div class="btn-row">
        <button class="btn" id="fetchBtn" onclick="fetchModels()">Fetch Models</button>
        <span class="status" id="fetchStatus"></span>
      </div>
      <div id="modelList"></div>
      <div id="selectedModel" style="font-size:12px;color:var(--accent);margin-top:6px"></div>
    </div>

    <div class="btn-row">
      <button class="btn" id="saveBtn" onclick="saveSettings()">Save & Switch</button>
      <span class="status" id="saveStatus"></span>
    </div>
  </div>
</div>

<script>
let selectedModelName = null;

function onProviderChange() {{
  const p = document.getElementById('providerSelect').value;
  const o = document.getElementById('ollamaUrlGroup');
  const c = document.getElementById('customUrlGroup');
  const k = document.getElementById('apiKey');
  if (p === 'Ollama') {{
    o.classList.remove('hidden');
    c.classList.add('hidden');
    k.value = '';
    k.placeholder = 'Not required for local Ollama';
  }} else {{
    o.classList.add('hidden');
    if (p === 'Custom') c.classList.remove('hidden');
    else c.classList.add('hidden');
    k.placeholder = 'Enter your API key';
  }}
  hideModelList();
}}

function hideModelList() {{
  document.getElementById('modelList').classList.remove('show');
  document.getElementById('modelList').innerHTML = '';
  document.getElementById('fetchStatus').textContent = '';
  document.getElementById('selectedModel').textContent = '';
  selectedModelName = null;
}}

async function fetchModels() {{
  const status = document.getElementById('fetchStatus');
  status.textContent = 'Fetching...';
  status.className = 'status';
  try {{
    const provider = document.getElementById('providerSelect').value;
    const apiKey = document.getElementById('apiKey').value;
    const customUrl = document.getElementById('customUrl').value;
    const ollamaUrl = document.getElementById('ollamaUrl').value;
    const resp = await fetch('/api/settings/models', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{provider, api_key: apiKey, custom_url: customUrl, ollama_url: ollamaUrl}})
    }});
    const data = await resp.json();
    if (data.error) {{
      status.textContent = 'Error: ' + data.error;
      status.className = 'status err';
      return;
    }}
    const list = document.getElementById('modelList');
    if (data.models && data.models.length) {{
      list.innerHTML = data.models.map(m => `<div onclick="selectModel('${{m}}')">${{m}}</div>`).join('');
      list.classList.add('show');
      status.textContent = `${{data.models.length}} models found`;
      status.className = 'status ok';
    }} else {{
      list.innerHTML = '<div style="color:var(--muted)">No models found</div>';
      list.classList.add('show');
    }}
  }} catch(e) {{
    status.textContent = 'Failed: ' + e.message;
    status.className = 'status err';
  }}
}}

function selectModel(name) {{
  selectedModelName = name;
  document.getElementById('modelList').classList.remove('show');
  document.getElementById('selectedModel').textContent = 'Selected: ' + name;
}}

async function saveSettings() {{
  const btn = document.getElementById('saveBtn');
  const status = document.getElementById('saveStatus');
  btn.disabled = true;
  status.textContent = 'Saving...';
  status.className = 'status';
  try {{
    const provider = document.getElementById('providerSelect').value;
    const apiKey = document.getElementById('apiKey').value;
    const customUrl = document.getElementById('customUrl').value;
    const ollamaUrl = document.getElementById('ollamaUrl').value;
    const resp = await fetch('/api/settings/provider', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{provider, api_key: apiKey, custom_url: customUrl, ollama_url: ollamaUrl, model: selectedModelName}})
    }});
    const data = await resp.json();
    if (data.ok) {{
      status.textContent = 'Saved! Provider switched to ' + provider;
      status.className = 'status ok';
      setTimeout(() => {{ window.location.href = '/'; }}, 1000);
    }} else {{
      status.textContent = 'Error saving';
      status.className = 'status err';
    }}
  }} catch(e) {{
    status.textContent = 'Failed: ' + e.message;
    status.className = 'status err';
  }} finally {{
    btn.disabled = false;
  }}
}}

onProviderChange();
</script>
</body>
</html>"""

def make_dashboard():
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

    no_rows = '<tr><td colspan="6" class="empty">No requests yet — send a message below</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ContextCut-PRO</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
<style>
:root{{--bg:#080c14;--surf:#0d1420;--surf2:#111927;--border:#1e2d42;--text:#c9d8f0;--muted:#4a6080;--accent:#00d4ff;--green:#22c55e;--yellow:#f59e0b;--red:#ef4444;--r:6px}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'JetBrains Mono',monospace;font-size:13px;display:flex;flex-direction:column;height:100vh;overflow:hidden}}
/* ── header ── */
.header{{background:var(--surf);border-bottom:1px solid var(--border);padding:0 20px;display:flex;align-items:center;gap:14px;height:48px;flex-shrink:0}}
.logo{{font-family:'Syne',sans-serif;font-size:20px;font-weight:800;color:var(--accent);letter-spacing:-.5px}}
.logo span{{color:var(--text)}}
.hinfo{{color:var(--muted);font-size:11px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.live{{display:flex;align-items:center;gap:5px;color:var(--muted);font-size:11px;flex-shrink:0}}
.dot{{width:7px;height:7px;border-radius:50%;background:var(--green);animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.3}}}}
/* ── main two-column layout ── */
.main{{display:flex;flex:1;overflow:hidden;gap:0}}
/* ── LEFT: stats + table (scrollable) ── */
.left{{width:55%;border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}}
.left-scroll{{flex:1;overflow-y:auto;padding:14px}}
.left-scroll::-webkit-scrollbar{{width:4px}}.left-scroll::-webkit-scrollbar-thumb{{background:var(--border);border-radius:2px}}
/* ── RIGHT: chat ── */
.right{{flex:1;display:flex;flex-direction:column;overflow:hidden}}
/* cards */
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}}
.card{{background:var(--surf);border:1px solid var(--border);border-radius:var(--r);padding:11px}}
.card-label{{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.1em;margin-bottom:5px}}
.card-val{{font-size:20px;font-weight:600;font-family:'Syne',sans-serif}}
.green{{color:var(--green)}}.yellow{{color:var(--yellow)}}.red{{color:var(--red)}}
/* ctx bar */
.ctx-wrap{{background:var(--surf);border:1px solid var(--border);border-radius:var(--r);padding:11px;margin-bottom:12px}}
.ctx-label{{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.1em;margin-bottom:7px}}
.ctx-track{{background:var(--bg);border-radius:3px;height:14px;overflow:hidden}}
.ctx-fill{{height:100%;border-radius:3px;transition:width .5s;background:{bc};width:{min(last_pct,100)}%}}
.ctx-info{{display:flex;justify-content:space-between;margin-top:4px;font-size:10px;color:var(--muted)}}
/* table */
.tbl-wrap{{background:var(--surf);border:1px solid var(--border);border-radius:var(--r);overflow:hidden}}
table{{width:100%;border-collapse:collapse}}
th{{background:#0a1628;color:var(--muted);text-align:left;padding:8px 10px;font-size:9px;text-transform:uppercase;letter-spacing:.1em;border-bottom:1px solid var(--border)}}
td{{padding:7px 10px;border-top:1px solid var(--border);vertical-align:middle;font-size:12px}}
tr:hover td{{background:var(--surf2)}}
.ts{{color:var(--muted);white-space:nowrap;font-size:10px}}
.qcell{{max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.num{{text-align:right;white-space:nowrap}}
.hitcell{{max-width:180px}}
.hit{{display:inline-block;background:#0a1a2e;border:1px solid var(--border);border-radius:3px;padding:1px 4px;margin:1px;font-size:10px;color:var(--muted)}}
.hit em{{color:var(--accent);font-style:normal}}
.mini-bar{{height:3px;background:var(--border);border-radius:2px;margin-top:3px;overflow:hidden}}
.mini-fill{{height:100%;border-radius:2px}}
.empty{{text-align:center;padding:28px;color:var(--muted);font-size:12px}}
.tbl-footer{{font-size:10px;color:var(--muted);text-align:right;padding:6px 10px;border-top:1px solid var(--border)}}
/* ── CHAT ── */
.chat-header{{display:flex;align-items:center;justify-content:space-between;padding:8px 14px;border-bottom:1px solid var(--border);background:var(--surf);flex-shrink:0}}
.session-badge{{font-size:11px;color:var(--muted);background:var(--surf2);border:1px solid var(--border);border-radius:3px;padding:3px 8px;font-family:'JetBrains Mono',monospace}}
.clear-btn{{background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:3px 10px;font-size:11px;cursor:pointer;font-family:'JetBrains Mono',monospace}}
.clear-btn:hover{{color:var(--text);border-color:var(--accent)}}
.chat-messages{{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}}
.chat-messages::-webkit-scrollbar{{width:4px}}.chat-messages::-webkit-scrollbar-thumb{{background:var(--border);border-radius:2px}}
.msg{{max-width:88%}}
.msg.user{{align-self:flex-end}}.msg.assistant{{align-self:flex-start}}
.bubble{{padding:9px 13px;border-radius:var(--r);line-height:1.6;white-space:pre-wrap;word-break:break-word;font-size:13px}}
.msg.user .bubble{{background:var(--accent);color:#000;font-weight:500}}
.msg.assistant .bubble{{background:var(--surf2);border:1px solid var(--border)}}
.msg-meta{{font-size:10px;color:var(--muted);margin-top:3px;padding:0 4px}}
.msg.user .msg-meta{{text-align:right}}
.msg-stat{{display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap}}
.stat-pill{{background:var(--surf);border:1px solid var(--border);border-radius:3px;padding:1px 6px;font-size:10px}}
.stat-pill.ctx{{color:var(--accent)}}.stat-pill.save{{color:var(--green)}}.stat-pill.hit{{color:var(--muted)}}
/* typing */
.typing{{display:flex;gap:4px;padding:9px 13px;background:var(--surf2);border:1px solid var(--border);border-radius:var(--r);width:fit-content}}
.typing span{{width:6px;height:6px;border-radius:50%;background:var(--muted);animation:blink 1.2s infinite}}
.typing span:nth-child(2){{animation-delay:.2s}}.typing span:nth-child(3){{animation-delay:.4s}}
@keyframes blink{{0%,100%{{opacity:.2}}50%{{opacity:1}}}}
/* input bar */
.chat-input-bar{{border-top:1px solid var(--border);padding:10px;display:flex;flex-direction:column;gap:8px;flex-shrink:0;background:var(--surf)}}
.model-row{{display:flex;align-items:center;gap:8px}}
.model-label{{font-size:10px;color:var(--muted);white-space:nowrap}}
.model-combo{{flex:1;display:flex;gap:4px}}
.model-input{{flex:1;background:var(--bg);border:1px solid var(--border);border-radius:var(--r);padding:5px 9px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:12px;outline:none;min-width:0}}
.model-input:focus{{border-color:var(--accent)}}
.model-select{{background:var(--bg);border:1px solid var(--border);border-radius:var(--r);padding:4px 6px;color:var(--muted);font-size:11px;cursor:pointer;outline:none;font-family:'JetBrains Mono',monospace}}
.model-select:focus{{border-color:var(--accent)}}
.model-select option{{background:var(--surf);color:var(--text)}}
.input-row{{display:flex;gap:8px;align-items:flex-end}}
.chat-input{{flex:1;background:var(--bg);border:1px solid var(--border);border-radius:var(--r);padding:8px 12px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:13px;resize:none;outline:none;line-height:1.5;max-height:120px}}
.chat-input:focus{{border-color:var(--accent)}}
.send-btn{{background:var(--accent);color:#000;border:none;border-radius:var(--r);padding:8px 16px;font-family:'Syne',sans-serif;font-weight:700;font-size:13px;cursor:pointer;white-space:nowrap;height:38px}}
.send-btn:hover{{opacity:.85}}.send-btn:disabled{{opacity:.4;cursor:not-allowed}}
/* ── Settings panel ── */
.settings-row{{display:flex;align-items:center;gap:6px;flex-wrap:wrap}}
.param-group{{display:flex;align-items:center;gap:4px}}
.param-label{{font-size:10px;color:var(--muted);white-space:nowrap}}
.param-slider{{width:60px;height:4px;-webkit-appearance:none;background:var(--border);border-radius:2px;outline:none;cursor:pointer}}
.param-slider::-webkit-slider-thumb{{-webkit-appearance:none;width:12px;height:12px;border-radius:50%;background:var(--accent);cursor:pointer}}
.param-val{{font-size:10px;color:var(--accent);min-width:28px;text-align:center;font-family:'JetBrains Mono',monospace}}
.settings-toggle{{background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:3px 8px;font-size:10px;cursor:pointer;font-family:'JetBrains Mono',monospace}}
.settings-toggle:hover{{color:var(--text);border-color:var(--accent)}}
.settings-panel{{display:none;background:var(--surf);border-top:1px solid var(--border);padding:8px 10px}}
.settings-panel.open{{display:block}}
</style>
</head>
<body>

<div class="header">
  <div class="logo">ContextCut<span>-PRO</span></div>
  <div class="hinfo">{UPSTREAM} · Qdrant {QDRANT_HOST}:{QDRANT_PORT} · min_score={MIN_SCORE} · top_k={TOP_K}</div>
  <a href="/settings" style="background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:3px 10px;font-size:11px;cursor:pointer;font-family:'JetBrains Mono',monospace;text-decoration:none">Settings ⚙</a>
  <div class="live"><span class="dot"></span>live</div>
</div>

<div class="main">

  <!-- ── LEFT: Stats + Table ── -->
  <div class="left">
    <div class="left-scroll">
      <div class="cards">
        <div class="card"><div class="card-label">License</div><div class="card-val" id="cardLicense" style="font-size:13px">—</div></div>
        <div class="card"><div class="card-label">Requests</div><div class="card-val" id="cardReq">{s['total_requests']}</div></div>
        <div class="card"><div class="card-label">Last CTX</div><div class="card-val {'green' if last_pct<60 else 'yellow' if last_pct<80 else 'red'}" id="cardCtx">{last_pct}%</div></div>
        <div class="card"><div class="card-label">Tokens Saved</div><div class="card-val green" id="cardSave">{s.get('total_saved',0):,}</div></div>
        <div class="card"><div class="card-label">Peak Tokens</div><div class="card-val {'red' if s['max_tokens_seen']>CTX_LIMIT*0.8 else ''}">{s['max_tokens_seen']:,}</div></div>
        <div class="card"><div class="card-label">CTX Limit</div><div class="card-val">{CTX_LIMIT:,}</div></div>
        <div class="card"><div class="card-label">Cache Hits</div><div class="card-val" style="font-size:13px" id="cardCache">{s.get('cache_hits',0)}</div></div>
      </div>
      <div class="ctx-wrap">
        <div class="ctx-label">Most Recent Context Usage</div>
        <div class="ctx-track"><div class="ctx-fill" id="ctxBar"></div></div>
        <div class="ctx-info"><span id="ctxTok">{last_tok:,} / {CTX_LIMIT:,} tokens</span><strong style="color:{bc}" id="ctxPct">{last_pct}%</strong></div>
      </div>
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>Time</th><th>Query</th><th>Before</th><th>After</th><th>CTX%</th><th>Hits</th></tr></thead>
          <tbody id="tblBody">{rows_html if rows_html else no_rows}</tbody>
        </table>
        <div class="tbl-footer">Token counting: {TOKEN_METHOD} · auto-refreshes on each request</div>
      </div>
    </div>
  </div>

  <!-- ── RIGHT: Chat ── -->
  <div class="right">
    <div class="chat-header" id="chatHeader">
      <span class="session-badge" id="sessionBadge">Session: new</span>
      <button class="clear-btn" id="clearBtn" onclick="clearConversation()" title="Clear conversation (/clear)">Clear</button>
    </div>
    <div class="chat-messages" id="messages" role="log" aria-live="polite" aria-label="Chat messages">
      <div class="msg assistant">
        <div class="bubble">👋 <strong>ContextCut-PRO</strong> — Ask anything. Relevant context from your knowledge base is injected automatically. Conversation history is maintained automatically. Watch the left panel update after each message.</div>
      </div>
    </div>
    <div class="chat-input-bar">
      <div class="model-row">
        <span class="model-label">Model:</span>
        <div class="model-combo">
          <input class="model-input" id="modelInput" type="text" value="{DEFAULT_MODEL}" placeholder="e.g. qwen3:14b-q8_0">
          <select class="model-select" id="modelSelect" title="Available models" onchange="if(this.value){{document.getElementById('modelInput').value=this.value;this.value=\'\';}}">
            <option value="">▾</option>
          </select>
        </div>
        <button class="settings-toggle" id="settingsToggle" onclick="toggleSettings()">Settings ⚙</button>
      </div>
      <div class="settings-panel" id="settingsPanel">
        <div class="settings-row">
          <div class="param-group">
            <span class="param-label">Temp:</span>
            <input type="range" class="param-slider" id="tempSlider" min="0" max="2" step="0.05" value="{DEFAULT_TEMP}" oninput="updateParamVal('tempSlider','tempVal')">
            <span class="param-val" id="tempVal">{DEFAULT_TEMP}</span>
          </div>
          <div class="param-group">
            <span class="param-label">Top-p:</span>
            <input type="range" class="param-slider" id="toppSlider" min="0" max="1" step="0.05" value="{DEFAULT_TOP_P}" oninput="updateParamVal('toppSlider','toppVal')">
            <span class="param-val" id="toppVal">{DEFAULT_TOP_P}</span>
          </div>
          <div class="param-group">
            <span class="param-label">Max tokens:</span>
            <input type="number" class="param-slider" id="maxTokInput" min="0" max="32768" step="64" value="{DEFAULT_MAX_TK}" style="width:70px;background:var(--bg);border:1px solid var(--border);border-radius:2px;padding:2px 4px;color:var(--accent);font-size:10px;font-family:'JetBrains Mono',monospace">
            <span class="param-val" id="maxTokVal">{DEFAULT_MAX_TK}</span>
          </div>
          <div class="param-group">
            <span class="param-label">Min score:</span>
            <input type="range" class="param-slider" id="minscoreSlider" min="0.0" max="0.6" step="0.05" value="{MIN_SCORE}" oninput="updateMinScore()">
            <span class="param-val" id="minscoreVal">{MIN_SCORE}</span>
          </div>
        </div>
      </div>
      <div class="input-row">
        <textarea class="chat-input" id="chatInput" rows="2" role="textbox" aria-label="Message input"
          placeholder="Type a message… (Enter to send, Shift+Enter for newline). Try: /clear, /help"
          onkeydown="handleKey(event)"></textarea>
        <button class="send-btn" id="sendBtn" onclick="sendMessage()" aria-label="Send message">Send ↑</button>
      </div>
    </div>
  </div>

</div>

<script>
let sessionId = null;
let conversationHistory = [];
let inputHistory = [];
let inputHistoryIdx = -1;

function esc(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\\n/g,'<br>');
}}

function handleKey(e) {{
  const input = document.getElementById('chatInput');
  if (e.key === 'ArrowUp' && input.selectionStart === 0 && input.value === '') {{
    e.preventDefault();
    if (inputHistory.length > 0 && inputHistoryIdx < inputHistory.length - 1) {{
      inputHistoryIdx++;
      input.value = inputHistory[inputHistoryIdx];
    }}
    return;
  }}
  if (e.key === 'ArrowDown' && input.selectionStart === 0) {{
    e.preventDefault();
    if (inputHistoryIdx > 0) {{
      inputHistoryIdx--;
      input.value = inputHistory[inputHistoryIdx];
    }} else {{
      inputHistoryIdx = -1;
      input.value = '';
    }}
    return;
  }}
  if (e.key === 'Enter' && !e.shiftKey) {{ e.preventDefault(); sendMessage(); }}
}}

function updateSessionBadge() {{
  const badge = document.getElementById('sessionBadge');
  if (badge) {{
    badge.textContent = sessionId ? 'Session: ' + sessionId : 'Session: new';
  }}
}}

async function initSession() {{
  try {{
    const r = await fetch('/api/session/new');
    if (r.ok) {{
      const d = await r.json();
      sessionId = d.session_id;
      updateSessionBadge();
    }}
  }} catch(e) {{}}
}}

function toggleSettings() {{
  const panel = document.getElementById('settingsPanel');
  panel.classList.toggle('open');
}}

function updateParamVal(sliderId, valId) {{
  const slider = document.getElementById(sliderId);
  const val = document.getElementById(valId);
  if (slider && val) {{
    val.textContent = slider.value;
  }}
}}

function updateMinScore() {{
  const slider = document.getElementById('minscoreSlider');
  const val = document.getElementById('minscoreVal');
  if (slider && val) {{
    val.textContent = parseFloat(slider.value).toFixed(2);
    fetch('/api/settings', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{min_score: parseFloat(slider.value)}})
    }}).catch(e => console.warn('min_score sync failed', e));
  }}
}}

function getGenerationParams() {{
  const temp = parseFloat(document.getElementById('tempSlider').value);
  const topP = parseFloat(document.getElementById('toppSlider').value);
  const maxTok = parseInt(document.getElementById('maxTokInput').value);
  document.getElementById('maxTokVal').textContent = maxTok || '0';
  const params = {{temperature: temp, top_p: topP}};
  if (maxTok > 0) params.max_tokens = maxTok;
  return params;
}}

async function clearConversation() {{
  if (!sessionId) return;
  try {{
    await fetch('/api/session/' + sessionId, {{method: 'DELETE'}});
    conversationHistory = [];
    const msgs = document.getElementById('messages');
    msgs.innerHTML = '<div class="msg assistant"><div class="bubble">Conversation cleared. Starting fresh.</div></div>';
    const r = await fetch('/api/session/new');
    if (r.ok) {{
      const d = await r.json();
      sessionId = d.session_id;
      updateSessionBadge();
    }}
  }} catch(e) {{}}
}}

function handleCommand(text) {{
  if (text === '/clear') {{
    clearConversation();
    return true;
  }}
  if (text === '/help') {{
    appendMsg('assistant',
      'Commands:\\n' +
      '/clear — Clear conversation history\\n' +
      '/help — Show this help\\n\\n' +
      'Natural commands:\\n' +
      '"stop" / "that\\'s enough" — Stop current response\\n' +
      '"continue" / "go on" — Continue previous response\\n' +
      '"revise..." / "rewrite..." — Ask for revision',
      '');
    return true;
  }}
  return false;
}}

function appendMsg(role, text, statHtml) {{
  const box = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.innerHTML =
    `<div class="bubble">${{esc(text)}}</div>` +
    (statHtml ? `<div class="msg-meta"><div class="msg-stat">${{statHtml}}</div></div>` : '');
  box.appendChild(div);
  div.scrollIntoView({{behavior:'smooth', block:'start'}});
}}

function showTyping() {{
  const box = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'msg assistant'; div.id = 'typing-indicator';
  div.innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';
  box.appendChild(div);
  div.scrollIntoView({{behavior:'smooth', block:'start'}});
}}

function removeTyping() {{
  const el = document.getElementById('typing-indicator');
  if (el) el.remove();
}}

function updateStats(d) {{
  if (!d) return;
  const pct = d.pct || 0;
  const col = pct < 60 ? 'var(--green)' : pct < 80 ? 'var(--yellow)' : 'var(--red)';
  const bar = document.getElementById('ctxBar');
  if (bar) {{ bar.style.width = Math.min(pct,100)+'%'; bar.style.background = col; }}
  const cp = document.getElementById('ctxPct');
  if (cp) {{ cp.textContent = pct+'%'; cp.style.color = col; }}
  const ct = document.getElementById('ctxTok');
  if (ct) ct.textContent = (d.tokens_after||0).toLocaleString() + ' / {CTX_LIMIT:,} tokens';
  const tb = document.getElementById('tblBody');
  if (tb && d.ts) {{
    const hits = (d.hits||[]).map(h=>`<span class="hit">${{esc(h.source.replace('.md',''))}} <em>${{h.score}}</em></span>`).join(' ') || '<span style="color:#4b5563">—</span>';
    const newRow = `<tr>
      <td class="ts">${{d.ts}}</td>
      <td class="qcell">${{esc((d.query||'').substring(0,60))}}</td>
      <td class="num">${{d.tokens_before||0}}</td>
      <td class="num">${{d.tokens_after||0}}</td>
      <td class="num" style="color:${{col}}">${{pct}}%<div class="mini-bar"><div class="mini-fill" style="width:${{Math.min(pct,100)}}%;background:${{col}}"></div></div></td>
      <td class="hitcell">${{hits}}</td>
    </tr>`;
    if (tb.querySelector('.empty')) tb.innerHTML = newRow;
    else tb.insertAdjacentHTML('afterbegin', newRow);
  }}
}}

async function fetchModels() {{
  try {{
    const r = await fetch('/api/tags');
    if (!r.ok) return;
    const d = await r.json();
    const models = (d.models||[]).map(m=>m.name).sort();
    if (!models.length) return;
    const sel = document.getElementById('modelSelect');
    if (!sel) return;
    sel.innerHTML = '<option value="">▾</option>' +
      models.map(m=>`<option value="${{m}}">${{m}}</option>`).join('');
    const inp = document.getElementById('modelInput');
    if (inp && !inp.value && models.length) inp.value = models[0];
  }} catch(e) {{}}
}}

let _lastTs = null;

async function pollStats() {{
  const g = (id) => document.getElementById(id);
  try {{
    const sr = await fetch('/stats');
    if (sr.ok) {{
      const d = await sr.json();
      if(g('cardReq'))  g('cardReq').textContent  = d.total_requests||0;
      if(g('cardSave')) g('cardSave').textContent = (d.total_saved||0).toLocaleString();
      if(g('cardPeak')) g('cardPeak').textContent = (d.max_tokens_seen||0).toLocaleString();
      const pct = d.pct||0;
      const col = pct<60?'var(--green)':pct<80?'var(--yellow)':'var(--red)';
      if(g('cardCtx')){{ g('cardCtx').textContent=pct+'%'; g('cardCtx').style.color=col; }}
      if(g('ctxBar')){{ g('ctxBar').style.width=Math.min(pct,100)+'%'; g('ctxBar').style.background=col; }}
      if(g('ctxTok')) g('ctxTok').textContent=(d.tokens_after||0).toLocaleString()+' / {CTX_LIMIT} tokens';
      if(g('ctxPct')){{ g('ctxPct').textContent=pct+'%'; g('ctxPct').style.color=col; }}
    }}
  }} catch(e) {{}}
  try {{
    const lr = await fetch('/log');
    if (!lr.ok) return;
    const rows = await lr.json();
    if (!rows.length) return;
    const sig = rows[0].ts + '|' + rows[0].tokens_after;
    if (sig === _lastTs) return;
    _lastTs = sig;
    const tb = g('tblBody');
    if (!tb) return;
    tb.innerHTML = rows.map(r => {{
      const p = r.pct||0;
      const c = p<60?'var(--green)':p<80?'var(--yellow)':'var(--red)';
      const hits = (r.hits||[]).map(h=>
        `<span class="hit">${{esc((h.source||'?').replace('.md',''))}} <em>${{h.score}}</em></span>`
      ).join(' ') || '<span style="color:#4b5563">\u2014</span>';
      return `<tr>
        <td class="ts">${{r.ts||''}}</td>
        <td class="qcell">${{esc((r.query||'').substring(0,60))}}</td>
        <td class="num">${{r.tokens_before||0}}</td>
        <td class="num">${{r.tokens_after||0}}</td>
        <td class="num" style="color:${{c}}">${{p}}%<div class="mini-bar"><div class="mini-fill" style="width:${{Math.min(p,100)}}%;background:${{c}}"></div></div></td>
        <td class="hitcell">${{hits}}</td>
      </tr>`;
    }}).join('');
  }} catch(e) {{ console.error('poll/log error:', e); }}
}}

async function pollLicense() {{
  try {{
    const r = await fetch('/api/license');
    if (!r.ok) return;
    const d = await r.json();
    const el = document.getElementById('cardLicense');
    if (!el) return;
    if (d.valid) {{
      el.textContent = d.license_type || 'valid';
      el.className = 'card-val green';
      el.title = (d.message || '') + (d.last_heartbeat ? '\\nLast heartbeat: ' + d.last_heartbeat : '');
    }} else if (d.license_type) {{
      el.textContent = 'expired';
      el.className = 'card-val red';
    }} else {{
      el.textContent = 'no key';
      el.className = 'card-val yellow';
    }}
  }} catch(e) {{}}
}}

setInterval(pollStats, 3000);
setInterval(pollLicense, 5000);
pollStats();
pollLicense();
fetchModels();
initSession();

async function sendMessage() {{
  const input   = document.getElementById('chatInput');
  const sendBtn = document.getElementById('sendBtn');
  const model   = document.getElementById('modelInput').value.trim();
  const text    = input.value.trim();
  if (!text) return;
  if (!model) {{ alert('Enter a model name first.'); return; }}
  if (handleCommand(text)) {{ input.value = ''; return; }}
  inputHistory.unshift(text);
  if (inputHistory.length > 50) inputHistory.pop();
  inputHistoryIdx = -1;
  input.value = '';
  sendBtn.disabled = true;
  appendMsg('user', text, '');
  conversationHistory.push({{role:'user', content:text}});
  showTyping();

  let assistantDiv = null;
  let bubble = null;
  let fullText = '';
  let usage = {{}};

  function ensureBubble() {{
    if (assistantDiv) return;
    removeTyping();
    const box = document.getElementById('messages');
    assistantDiv = document.createElement('div');
    assistantDiv.className = 'msg assistant';
    assistantDiv.innerHTML = '<div class="bubble"></div>';
    box.appendChild(assistantDiv);
    bubble = assistantDiv.querySelector('.bubble');
    assistantDiv.scrollIntoView({{behavior:'smooth', block:'start'}});
  }}

  try {{
    const genParams = getGenerationParams();
    const resp = await fetch('/v1/chat/completions', {{
      method: 'POST',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{model, messages: conversationHistory, stream:true, session_id: sessionId, ...genParams}})
    }});

    if (!resp.ok) {{
      removeTyping();
      appendMsg('assistant', '\u274c Error ' + resp.status + ': ' + await resp.text(), '');
      return;
    }}

    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {{
      const {{done, value}} = await reader.read();
      if (done) break;
      buf += decoder.decode(value, {{stream: true}});
      const lines = buf.split('\\n');
      buf = lines.pop();
      for (const line of lines) {{
        const trimmed = line.trim();
        if (!trimmed || trimmed === 'data: [DONE]') continue;
        if (!trimmed.startsWith('data: ')) continue;
        try {{
          const chunk = JSON.parse(trimmed.slice(6));
          if (chunk.usage) usage = chunk.usage;
          const delta = chunk.choices && chunk.choices[0] && chunk.choices[0].delta;
          if (!delta) continue;
          const token = delta.content || '';
          if (!token) continue;
          fullText += token;
          ensureBubble();
          bubble.innerHTML = esc(fullText);
          assistantDiv.scrollIntoView({{behavior:'instant', block:'end'}});
        }} catch(e) {{}}
      }}
    }}

    ensureBubble();
    if (!fullText) bubble.innerHTML = '<em>(no response)</em>';
    conversationHistory.push({{role:'assistant', content:fullText}});

    try {{
      const sr = await fetch('/stats');
      if (sr.ok) {{
        const d = await sr.json();
        updateStats(d);
        const saved = Math.max(0,(d.tokens_before||0)-(d.tokens_after||0));
        const pct   = d.pct||0;
        const col   = pct<60?'var(--green)':pct<80?'var(--yellow)':'var(--red)';
        const hits  = (d.hits||[]).length;
        const statHtml =
          '<span class="stat-pill ctx" style="color:'+col+'">'+pct+'% CTX</span>' +
          '<span class="stat-pill">\u2191'+(usage.prompt_tokens||'?')+' prompt</span>' +
          '<span class="stat-pill">\u2193'+(usage.completion_tokens||'?')+' completion</span>' +
          (saved>0 ? '<span class="stat-pill save">-'+saved+' saved</span>' : '') +
          (hits>0  ? '<span class="stat-pill hit">'+hits+' chunk'+(hits>1?'s':'')+' injected</span>' : '<span class="stat-pill">no injection</span>');
        assistantDiv.insertAdjacentHTML('beforeend',
          '<div class="msg-meta"><div class="msg-stat">'+statHtml+'</div></div>');
      }}
    }} catch(e) {{}}

  }} catch(e) {{
    removeTyping();
    appendMsg('assistant', '\u274c Network error: ' + e.message, '');
  }} finally {{
    sendBtn.disabled = false;
    input.focus();
  }}
}}
</script>
</body></html>"""

# ── Dashboard handler ─────────────────────────────────────────────────────────
class DashboardHandler(_SuppressBrokenPipe, BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def do_GET(self):
        if self.path == "/log":
            with _lock:
                rows = list(_log)
            body = json.dumps(rows).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/tags":
            try:
                upstream = get_current_upstream()
                api_key = get_current_api_key()
                
                if _provider_name == "Ollama":
                    req = urllib.request.Request(f"{upstream}/api/tags", method="GET")
                    with urllib.request.urlopen(req, timeout=5) as r:
                        data = json.loads(r.read().decode("utf-8"))
                        models = [{"name": m["name"]} for m in data.get("models", [])]
                        body = json.dumps({"models": models}, ensure_ascii=True).encode("utf-8")
                else:
                    url = f"{upstream}/v1/models"
                    req = urllib.request.Request(url, method="GET")
                    if api_key:
                        req.add_header("Authorization", f"Bearer {api_key}")
                    req.add_header("Accept", "application/json")
                    with urllib.request.urlopen(req, timeout=10) as r:
                        raw = r.read()
                        if r.headers.get("Content-Encoding") == "gzip":
                            import gzip
                            raw = gzip.decompress(raw)
                        data = json.loads(raw.decode("utf-8"))
                        models = [{"name": m.get("id", str(m))} for m in data.get("data", [])]
                        models.sort(key=lambda x: x["name"])
                        body = json.dumps({"models": models}, ensure_ascii=True).encode("utf-8")
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                safe_msg = str(e)[:100].encode("ascii", errors="replace").decode("ascii")
                err_body = json.dumps({"models": [], "error": safe_msg}, ensure_ascii=True).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_body)))
                self.end_headers()
                self.wfile.write(err_body)
            return

        if self.path == "/api/settings/models":
            # POST only — handled below in do_POST
            self.send_response(405)
            self.end_headers()
            self.wfile.write(b"Method Not Allowed")
            return
        if self.path == "/api/session/new":
            sid = new_session()
            body = json.dumps({"session_id": sid}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/session/history":
            with _lock:
                sessions = {sid: {"msg_count": s["msg_count"], "created": s["created"]} for sid, s in _sessions.items()}
            body = json.dumps({"sessions": sessions}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/license":
            body = json.dumps(check_license_status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/stats":
            body = json.dumps(make_stats_json()).encode()
            self.send_response(200)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/settings":
            page = make_settings_page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        else:
            page = make_dashboard().encode()
            self.send_response(200)
            self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length",str(len(page)))
            self.end_headers()
            self.wfile.write(page)

    def do_POST(self):
        length   = int(self.headers.get("Content-Length",0))
        raw_body = self.rfile.read(length)

        # ── Settings endpoints ──
        if self.path == "/api/settings/provider":
            try:
                body = json.loads(raw_body)
                global _provider_name, _custom_base_url, _api_key, UPSTREAM
                _provider_name = body.get("provider", "Ollama")
                _custom_base_url = body.get("custom_url", "").strip()
                _api_key = body.get("api_key", "").strip()
                ollama_url = body.get("ollama_url", "").strip()
                
                if _provider_name == "Ollama" and ollama_url:
                    UPSTREAM = ollama_url
                
                UPSTREAM = get_current_upstream()

                # Save securely to disk
                CredentialManager.save("provider", _provider_name)
                CredentialManager.save("custom_url", _custom_base_url)
                CredentialManager.save("ollama_url", ollama_url)
                if _api_key: CredentialManager.save("api_key", _api_key)

                print(f"[contextcut] Provider switched to {_provider_name} | upstream: {UPSTREAM}")
                resp = json.dumps({"ok": True, "upstream": UPSTREAM, "has_key": bool(_api_key)}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return
            except Exception as e:
                err = json.dumps({"error": str(e).encode("ascii", errors="replace").decode("ascii")}).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
                return

        if self.path == "/api/settings/models":
            try:
                body = json.loads(raw_body)
                provider = body.get("provider", "Ollama")
                api_key = body.get("api_key", "").strip()
                custom_url = body.get("custom_url", "").strip()
                ollama_url = body.get("ollama_url", "").strip()
                
                if provider == "Ollama":
                    # Ollama uses /api/tags, NOT /v1/models
                    base = ollama_url if ollama_url else (UPSTREAM or "http://localhost:11434")
                    req = urllib.request.Request(f"{base}/api/tags", method="GET")
                    with urllib.request.urlopen(req, timeout=5) as r:
                        data = json.loads(r.read().decode("utf-8"))
                        models = sorted([m["name"] for m in data.get("models", [])])
                elif provider == "Custom" and custom_url:
                    base = custom_url.rstrip("/")
                    req = urllib.request.Request(f"{base}/v1/models", method="GET")
                    if api_key: req.add_header("Authorization", f"Bearer {api_key}")
                    req.add_header("Accept", "application/json")
                    with urllib.request.urlopen(req, timeout=15) as r:
                        raw = r.read()
                        if r.headers.get("Content-Encoding") == "gzip":
                            import gzip
                            raw = gzip.decompress(raw)
                        data = json.loads(raw.decode("utf-8"))
                        models = sorted([m.get("id", str(m)) for m in data.get("data", [])])
                else:
                    base = PROVIDERS.get(provider, {}).get("url", "")
                    url = f"{base}/v1/models"
                    req = urllib.request.Request(url, method="GET")
                    if api_key: req.add_header("Authorization", f"Bearer {api_key}")
                    req.add_header("Accept", "application/json")
                    with urllib.request.urlopen(req, timeout=15) as r:
                        raw = r.read()
                        if r.headers.get("Content-Encoding") == "gzip":
                            import gzip
                            raw = gzip.decompress(raw)
                        data = json.loads(raw.decode("utf-8"))
                        models = sorted([m.get("id", str(m)) for m in data.get("data", [])])
                
                # Ensure ASCII-safe response
                resp = json.dumps({"models": models}, ensure_ascii=True).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return
            except (ConnectionRefusedError, OSError) as e:
                err_msg = "Connection refused - is the service running?"
                resp = json.dumps({"models": [], "error": err_msg}, ensure_ascii=True).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return
            except urllib.error.HTTPError as e:
                raw_err = e.read()
                err_text = raw_err.decode("utf-8", errors="replace")[:200]
                err_text = err_text.encode("ascii", errors="replace").decode("ascii")
                err_msg = "HTTP %d: %s" % (e.code, err_text)
                resp = json.dumps({"models": [], "error": err_msg}, ensure_ascii=True).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return
            except Exception as e:
                err_msg = str(e)[:200].encode("ascii", errors="replace").decode("ascii")
                resp = json.dumps({"models": [], "error": err_msg}, ensure_ascii=True).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return

        # ── Settings endpoint: update global MIN_SCORE live ──
        if self.path == "/api/settings":
            try:
                body = json.loads(raw_body)
                if "min_score" in body:
                    global MIN_SCORE
                    with _lock:
                        MIN_SCORE = float(body["min_score"])
                    print(f"[contextcut] Min score updated live: {MIN_SCORE}")
                    resp = json.dumps({"ok": True, "min_score": MIN_SCORE}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return
            except Exception as e:
                err = json.dumps({"error": str(e)}).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
                return

        try:
            parsed_body = json.loads(raw_body)
        except Exception:
            parsed_body = None
        is_streaming = isinstance(parsed_body, dict) and parsed_body.get("stream", False)
        req = urllib.request.Request(
            f"http://127.0.0.1:{LISTEN_PORT}{self.path}",
            data=raw_body, method="POST"
        )
        for k,v in self.headers.items():
            if k.lower() not in ("host",):
                req.add_header(k,v)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                self.send_response(resp.status)
                for k,v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding", "content-length"):
                        self.send_header(k,v)
                if is_streaming:
                    self.send_header("Transfer-Encoding", "chunked")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    while True:
                        chunk = resp.read(4096)
                        if not chunk:
                            self.wfile.write(b"0\r\n\r\n")
                            break
                        size = f"{len(chunk):X}\r\n".encode()
                        self.wfile.write(size + chunk + b"\r\n")
                        self.wfile.flush()
                else:
                    rb = resp.read()
                    self.send_header("Content-Length", str(len(rb)))
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

    load_sessions()

    if LICENSE_KEY:
        print("[contextcut] Validating license key...")
        if not validate_license():
            msg = _license_state['message']
            print(f"ERROR: {msg}")
            if "limit reached" in msg.lower() or "seats" in msg.lower():
                try:
                    if sys.stdin.isatty():
                        answer = input("\n  Release all license seats and retry? [y/N]: ").strip().lower()
                        should_release = answer in ("y", "yes")
                    else:
                        print("[contextcut] Non-interactive mode — auto-releasing stale seats...")
                        should_release = True
                    if should_release:
                        payload = json.dumps({"license_key": LICENSE_KEY}).encode()
                        req = urllib.request.Request(
                            f"{LICENSE_SERVER}/v1/license/reset",
                            data=payload,
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            result = json.loads(resp.read().decode())
                        print(f"[contextcut] {result.get('message', 'Seats reset')}")
                        print("[contextcut] Retrying license validation...")
                        time.sleep(1)
                        if validate_license():
                            print(f"[contextcut] License: {_license_state.get('license_type','?')} | {_license_state['message']}")
                            threading.Thread(target=heartbeat_loop, daemon=True).start()
                            print(f"[contextcut] Heartbeat: every {HEARTBEAT_INTERVAL}s | grace: {GRACE_PERIOD}s")
                        else:
                            print(f"ERROR: {_license_state['message']}")
                            raise SystemExit(1)
                    else:
                        print("Exiting. Release seats manually or wait 30 minutes.")
                        raise SystemExit(1)
                except Exception as e:
                    print(f"ERROR: Failed to release seats: {e}")
                    raise SystemExit(1)
            else:
                raise SystemExit(1)
        else:
            print(f"[contextcut] License: {_license_state.get('license_type','?')} | {_license_state['message']}")
            threading.Thread(target=heartbeat_loop, daemon=True).start()
            print(f"[contextcut] Heartbeat: every {HEARTBEAT_INTERVAL}s | grace: {GRACE_PERIOD}s")
    else:
        print("[contextcut] WARNING: No license key set. Set CONTEXTCUT_LICENSE_KEY.")

    dash = ReusableHTTPServer(("0.0.0.0", DASHBOARD_PORT), DashboardHandler)
    threading.Thread(target=dash.serve_forever, daemon=True).start()

    print(f"[contextcut] Dashboard  → http://localhost:{DASHBOARD_PORT}  (Chat + Monitor tabs)")
    print(f"[contextcut] Proxy      → http://127.0.0.1:{LISTEN_PORT} → {UPSTREAM}")
    print(f"[contextcut] Qdrant     → {QDRANT_HOST}:{QDRANT_PORT} / {COLLECTION}")
    print(f"[contextcut] Min score  → {MIN_SCORE}  Top-K → {TOP_K}  CTX → {CTX_LIMIT}")
    print(f"[contextcut] Tokens     → {TOKEN_METHOD}")
    print(f"[contextcut] Params     → temp={DEFAULT_TEMP} top_p={DEFAULT_TOP_P} max_tokens={DEFAULT_MAX_TK}")
    if DEFAULT_MODEL:
        print(f"[contextcut] Model      → {DEFAULT_MODEL}")

    ReusableHTTPServer(("127.0.0.1", LISTEN_PORT), ProxyHandler).serve_forever()