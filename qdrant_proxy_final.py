#!/usr/bin/env python3
# Version: fbe5ec4 — grep for this to verify you're on the latest commit
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
  CONTEXTCUT_CTX_LIMIT       32768                    Model context window size
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
import sqlite3
import random
import threading
import platform
import hashlib
import base64
import urllib.request
import urllib.error
import urllib.parse
import re
from collections import deque
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

_VOYAGE_AVAILABLE = False
_voyage_mod = None
try:
    import voyageai

    _voyage_mod = voyageai
    _VOYAGE_AVAILABLE = True
except ImportError:
    pass

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointIdsList,
    Filter,
    FieldCondition,
    MatchValue,
)

EMBED_DIM_MAP = {
    "nomic-embed-text": 768,
    "nomic-embed-text-v1.5": 768,
    "nomic-embed-text-v2-moe": 768,
    "mxbai-embed-large": 1024,
    "bge-m3": 1024,
    "qwen3-embedding:0.6b": 4096,
    "qwen3-embedding:4b": 4096,
    "qwen3-embedding:8b": 4096,
    "snowflake-arctic-embed-l": 1024,
    "all-minilm": 384,
}


def _get_embed_dim(model: str) -> int:
    if not model:
        return 1024
    base = model.split(":")[0]
    return EMBED_DIM_MAP.get(model, EMBED_DIM_MAP.get(base, 1024))


def _file_id(path: Path) -> str:
    return hashlib.md5(str(path).encode()).hexdigest()


def _remove_qdrant_point(path: Path):
    try:
        qc = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        qc.delete(
            collection_name=COLLECTION,
            points_selector=Filter(
                must=[FieldCondition(key="filename", match=MatchValue(value=path.name))]
            ),
        )
        return True
    except Exception as e:
        print(f"[contextcut] Qdrant delete error for {path.name}: {e}")
        return False


# ── Secure Credential Manager (Machine-bound encryption) ─────────────────────
class CredentialManager:
    """Stores API keys encrypted with a machine-derived key.
    If copied to another machine, the file is useless."""

    _cred_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".contextcut_creds.enc"
    )

    @staticmethod
    def _machine_key():
        raw = ""
        try:
            if platform.system() == "Linux":
                with open("/etc/machine-id") as f:
                    raw = f.read().strip()
            elif platform.system() == "Darwin":
                import subprocess

                raw = subprocess.check_output(
                    ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                    encoding="utf-8",
                ).strip()
                import re

                match = re.search(r'"IOPlatformSerialNumber"\s*=\s*"([^"]+)"', raw)
                if match:
                    raw = match.group(1)
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
        with open(cls._cred_file, "wb") as fh:
            fh.write(encrypted)
        os.chmod(cls._cred_file, 0o600)

    @classmethod
    def get(cls, key_name):
        return cls.load_all().get(key_name)

    @classmethod
    def load_all(cls):
        if not os.path.exists(cls._cred_file):
            return {}
        try:
            f = cls._get_fernet()
            with open(cls._cred_file, "rb") as fh:
                encrypted = fh.read()
            return json.loads(f.decrypt(encrypted).decode())
        except Exception:
            return {}


# ── Config ────────────────────────────────────────────────────────────────────
UPSTREAM = os.getenv("CONTEXTCUT_UPSTREAM", "http://localhost:11434")
QDRANT_HOST = os.getenv("CONTEXTCUT_QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("CONTEXTCUT_QDRANT_PORT", "6333"))
COLLECTION = os.getenv("CONTEXTCUT_COLLECTION", "contextcut")
KB_DIR = Path(
    os.getenv("CONTEXTCUT_KB_DIR", str(Path.home() / "contextcut" / "knowledge"))
).expanduser()

ALLOWED_EXT = {
    ".md",
    ".txt",
    ".py",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".csv",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".go",
    ".rs",
    ".rb",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".sh",
    ".sql",
    ".log",
    ".pdf",
    ".docx",
    ".xlsx",
}
LISTEN_PORT = int(os.getenv("CONTEXTCUT_PROXY_PORT", "18788"))
DASHBOARD_PORT = int(os.getenv("CONTEXTCUT_DASHBOARD_PORT", "18787"))
CTX_LIMIT = int(os.getenv("CONTEXTCUT_CTX_LIMIT", "32768"))
TOP_K = int(os.getenv("CONTEXTCUT_TOP_K", "5"))
MIN_SCORE = float(os.getenv("CONTEXTCUT_MIN_SCORE", "0.50"))
MAX_CTX_CHARS = int(os.getenv("CONTEXTCUT_MAX_CTX_CHARS", str(CTX_LIMIT * 3)))
DEFAULT_MODEL = os.getenv("CONTEXTCUT_MODEL", "qwen3:14b-q8_0")

# ── Dynamic Provider Settings ────────────────────────────────────────────────
PROVIDERS = {
    "Ollama": {"url": "http://localhost:11434", "key_required": False},
    "OpenAI": {"url": "https://api.openai.com", "key_required": True},
    "OpenRouter": {"url": "https://openrouter.ai/api", "key_required": True},
    "Anthropic": {"url": "https://api.anthropic.com", "key_required": True},
    "xAI": {"url": "https://api.x.ai", "key_required": True},
    "Custom": {"url": "", "key_required": True},
}
_provider_name = "Ollama"
_custom_base_url = ""
_ollama_url = ""
_api_key = ""
_free_only = False
_local_only = True


def load_saved_credentials():
    global \
        _provider_name, \
        _custom_base_url, \
        _ollama_url, \
        _api_key, \
        _free_only, \
        _local_only
    global _EMBED_MODE, _VK, _LOCAL_EMBED
    creds = CredentialManager.load_all()
    _provider_name = creds.get("provider", "Ollama")
    _custom_base_url = creds.get("custom_url", "")
    _ollama_url = creds.get("ollama_url", "")
    _api_key = creds.get("api_key", "")
    _free_only = creds.get("free_only", False)
    _local_only = creds.get("local_only", True)

    saved_embed_mode = creds.get("embed_mode", "")
    if saved_embed_mode:
        _EMBED_MODE = saved_embed_mode
    saved_voyage = creds.get("voyage_key", "")
    if saved_voyage:
        _VK = saved_voyage
    saved_model = creds.get("embed_model", "")
    if saved_model:
        _LOCAL_EMBED = saved_model


def get_current_upstream():
    global _provider_name, _custom_base_url, _ollama_url
    if _provider_name == "Custom":
        return _custom_base_url
    if _provider_name == "Ollama":
        return _ollama_url if _ollama_url else UPSTREAM
    return PROVIDERS.get(_provider_name, {}).get("url", "")


def get_current_api_key():
    return _api_key if PROVIDERS.get(_provider_name, {}).get("key_required") else None


load_saved_credentials()
DEFAULT_TEMP = float(os.getenv("CONTEXTCUT_TEMP", "0.7"))
DEFAULT_MAX_TK = int(os.getenv("CONTEXTCUT_MAX_TOKENS", "0"))
DEFAULT_TOP_P = float(os.getenv("CONTEXTCUT_TOP_P", "1.0"))

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
_lock = threading.Lock()
_log = deque(maxlen=100)
_stats = {
    "total_requests": 0,
    "total_saved": 0,
    "max_tokens_seen": 0,
    "last_seen": None,
    "start_time": datetime.now().isoformat(),
    "cache_hits": 0,
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
CACHE_TTL = 300
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
MAX_HISTORY_TOKENS = 4096

_sessions: dict[str, dict] = {}
_current_sid: str | None = None

# ── SQLite persistence ──────────────────────────────────────────────────────────

SESSION_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".contextcut_sessions.db"
)
_JSON_LEGACY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".contextcut_sessions.json"
)


def _get_db() -> sqlite3.Connection:
    return sqlite3.connect(SESSION_FILE, check_same_thread=False)


def _init_db():
    db = _get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id               TEXT PRIMARY KEY,
            title            TEXT DEFAULT '',
            created          TEXT NOT NULL,
            msg_count        INTEGER DEFAULT 0,
            total_tokens     INTEGER DEFAULT 0,
            ctx_limit_reached INTEGER DEFAULT 0,
            preview          TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            tokens      INTEGER DEFAULT 0,
            position    INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_created  ON sessions(created DESC);
        CREATE TABLE IF NOT EXISTS agent_memory (
            key     TEXT PRIMARY KEY,
            value   TEXT NOT NULL,
            updated TEXT NOT NULL
        );""")
    db.commit()
    db.close()


def _migrate_json_to_sqlite():
    if not os.path.exists(_JSON_LEGACY):
        return
    try:
        with open(_JSON_LEGACY) as f:
            data = json.load(f)
    except Exception:
        return
    db = _get_db()
    try:
        for sid, sess in data.get("active", {}).items():
            db.execute(
                "INSERT OR IGNORE INTO sessions (id, title, created, msg_count, total_tokens, ctx_limit_reached, preview) VALUES (?,?,?,?,?,?,?)",
                (sid, "", sess.get("created", ""), sess.get("msg_count", 0), 0, 0, ""),
            )
            history = sess.get("history", [])
            for i, m in enumerate(history):
                db.execute(
                    "INSERT INTO messages (session_id, role, content, tokens, position) VALUES (?,?,?,?,?)",
                    (sid, m["role"], m["content"], 0, i),
                )
            if history:
                preview = history[0]["content"][:80]
                title = ""
                for m in history:
                    if m["role"] == "user":
                        title = m["content"][:60]
                        break
                total_tok = sum(count_tokens(m["content"]) for m in history)
                db.execute(
                    "UPDATE sessions SET title=?, preview=?, msg_count=?, total_tokens=? WHERE id=?",
                    (title, preview, len(history), total_tok, sid),
                )
        for _, s in data.get("archive", {}).items():
            sid = s["id"]
            db.execute(
                "INSERT OR IGNORE INTO sessions (id, title, created, msg_count, total_tokens, ctx_limit_reached, preview) VALUES (?,?,?,?,?,?,?)",
                (
                    sid,
                    s.get("title", ""),
                    s.get("created", ""),
                    s.get("msg_count", 0),
                    s.get("total_tokens", 0),
                    1 if s.get("ctx_limit_reached") else 0,
                    s.get("preview", ""),
                ),
            )
            history = s.get("history", [])
            for i, m in enumerate(history):
                db.execute(
                    "INSERT INTO messages (session_id, role, content, tokens, position) VALUES (?,?,?,?,?)",
                    (sid, m["role"], m["content"], 0, i),
                )
        db.commit()
        os.rename(_JSON_LEGACY, _JSON_LEGACY + ".migrated")
        print(f"[contextcut] Migrated {_JSON_LEGACY} → {SESSION_FILE}")
    except Exception as e:
        db.rollback()
        print(f"[contextcut] Migration error: {e}")
    finally:
        db.close()


def new_session() -> str:
    global _current_sid
    if _current_sid:
        _update_session_on_disk(_current_sid)
    sid = str(uuid.uuid4())[:8]
    _sessions[sid] = {
        "history": [],
        "created": datetime.now().isoformat(),
        "msg_count": 0,
        "ctx_limit_reached": False,
        "shell_confirm_mode": "ask",
        "_db_inserted": False,
    }
    _current_sid = sid
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
    try:
        db = _get_db()
        if not session.get("_db_inserted"):
            db.execute(
                "INSERT OR IGNORE INTO sessions (id, created) VALUES (?,?)",
                (sid, session["created"]),
            )
            session["_db_inserted"] = True
        pos = session["msg_count"] - 1
        tok = count_tokens(content)
        db.execute(
            "INSERT INTO messages (session_id, role, content, tokens, position) VALUES (?,?,?,?,?)",
            (sid, role, content, tok, pos),
        )
        db.commit()
        db.close()
    except Exception as e:
        print(f"[contextcut] DB insert message error: {e}")


def _update_session_on_disk(sid: str):
    session = _sessions.get(sid)
    if not session or not session.get("history"):
        return
    history = session["history"]
    total_tok = sum(count_tokens(m["content"]) for m in history)
    ctx_hit = session.get("ctx_limit_reached", False) or total_tok > CTX_LIMIT * 0.8
    title = ""
    for m in history:
        if m["role"] == "user":
            title = m["content"][:60]
            break
    preview = history[0]["content"][:80] if history else ""
    try:
        db = _get_db()
        db.execute(
            "UPDATE sessions SET title=?, preview=?, msg_count=?, total_tokens=?, ctx_limit_reached=? WHERE id=?",
            (title, preview, len(history), total_tok, 1 if ctx_hit else 0, sid),
        )
        db.commit()
        db.close()
    except Exception as e:
        print(f"[contextcut] DB update session error: {e}")


def clear_session(sid: str):
    _update_session_on_disk(sid)
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
    if lower in (
        "stop",
        "halt",
        "cease",
        "that's enough",
        "thats enough",
        "that is enough",
    ):
        return "stop"
    if lower in ("continue", "go on", "keep going", "more", "elaborate"):
        return "continue"
    if (
        lower.startswith("revise")
        or lower.startswith("rewrite")
        or lower.startswith("rephrase")
    ):
        return "revise"
    return None


def build_revision_prompt(
    last_user: str, last_assistant: str, revision_request: str
) -> list[dict]:
    return [
        {"role": "user", "content": last_user},
        {"role": "assistant", "content": last_assistant},
        {
            "role": "user",
            "content": f"{revision_request}. Please revise your previous response accordingly.",
        },
    ]


def load_sessions():
    if not os.path.exists(SESSION_FILE):
        return
    try:
        db = _get_db()
        cur = db.execute(
            "SELECT id, created, msg_count, ctx_limit_reached FROM sessions ORDER BY created"
        )
        rows = cur.fetchall()
        with _lock:
            for sid, created, msg_count, ctx_hit in rows:
                mcur = db.execute(
                    "SELECT role, content, tokens FROM messages WHERE session_id=? ORDER BY position",
                    (sid,),
                )
                history = [{"role": r, "content": c} for r, c, _ in mcur.fetchall()]
                if not history and not msg_count:
                    continue
                _sessions[sid] = {
                    "history": history,
                    "created": created,
                    "msg_count": msg_count or len(history),
                    "ctx_limit_reached": bool(ctx_hit),
                    "shell_confirm_mode": "ask",
                    "_db_inserted": True,
                }
        db.close()
        print(f"[contextcut] Loaded {len(_sessions)} sessions from {SESSION_FILE}")
    except Exception as e:
        print(f"[contextcut] Session load error: {e}")


def check_license_status() -> dict:
    with _lock:
        return dict(_license_state)


def release_license():
    if not LICENSE_KEY or not _license_state.get("valid"):
        return
    try:
        secret = _license_state.get("instance_secret")
        if not secret:
            secret_path = os.path.join(
                os.path.expanduser("~"), ".contextcut", "instance_secret"
            )
            if os.path.exists(secret_path):
                with open(secret_path) as f:
                    secret = f.read().strip()
        payload = json.dumps(
            {
                "license_key": LICENSE_KEY,
                "instance_id": _instance_id,
                "instance_secret": secret or "",
            }
        ).encode()
        req = urllib.request.Request(
            f"{LICENSE_SERVER}/v1/license/release",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "ContextCutPRO/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
        print(f"[contextcut] License seat released: {data.get('message', 'OK')}")
    except Exception as e:
        print(f"[contextcut] License release error (non-fatal): {e}")


_shutdown_done = False


def shutdown_hook():
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True
    release_license()
    if _current_sid:
        _update_session_on_disk(_current_sid)


import atexit

atexit.register(shutdown_hook)

# ── License Validation ────────────────────────────────────────────────────────
LICENSE_SERVER = os.getenv(
    "CONTEXTCUT_LICENSE_SERVER", "https://api.contextcut-pro.com"
).rstrip("/")
LICENSE_KEY = os.getenv("CONTEXTCUT_LICENSE_KEY", "")
HEARTBEAT_INTERVAL = int(os.getenv("CONTEXTCUT_HEARTBEAT_SEC", "900"))
GRACE_PERIOD = int(os.getenv("CONTEXTCUT_GRACE_SEC", "3600"))

_instance_id = os.getenv("CONTEXTCUT_INSTANCE_ID") or str(uuid.uuid4())

_license_state = {
    "valid": False,
    "instance_id": _instance_id,
    "instance_secret": None,
    "last_heartbeat": None,
    "license_type": None,
    "message": "Not yet validated",
    "seats": 0,
}


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
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "node": mac_addr,
    }


def validate_license() -> bool:
    global _license_state
    if not LICENSE_KEY:
        _license_state["message"] = (
            "No license key provided. Set CONTEXTCUT_LICENSE_KEY."
        )
        return False
    try:
        fp = get_fingerprint()
        payload = json.dumps(
            {
                "license_key": LICENSE_KEY,
                "instance_id": _instance_id,
                "fingerprint": fp,
                "version": "PRO-1.0",
                "action": "activate",
            }
        ).encode()
        req = urllib.request.Request(
            f"{LICENSE_SERVER}/v1/license/validate",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "ContextCutPRO/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        if data.get("valid"):
            secret = data.get("instance_secret")
            _license_state.update(
                {
                    "valid": True,
                    "activated_at": data.get("activated_at"),
                    "license_type": data.get("license_type", "single"),
                    "seats": data.get("seats", 1),
                    "expires_at": data.get("expires_at"),
                    "message": data.get("message", "License validated"),
                    "instance_secret": secret,
                }
            )
            if secret:
                secret_path = os.path.join(
                    os.path.expanduser("~"), ".contextcut", "instance_secret"
                )
                os.makedirs(os.path.dirname(secret_path), exist_ok=True)
                with open(secret_path, "w") as f:
                    f.write(secret)
                os.chmod(secret_path, 0o600)
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
        payload = json.dumps(
            {
                "license_key": LICENSE_KEY,
                "instance_id": _instance_id,
                "uptime": time.time(),
                "fingerprint": get_fingerprint(),
            }
        ).encode()
        req = urllib.request.Request(
            f"{LICENSE_SERVER}/v1/heartbeat",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "ContextCutPRO/1.0",
            },
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
        return True  # network blip — don't deactivate, keep running


def heartbeat_loop():
    time.sleep(HEARTBEAT_INTERVAL)
    while True:
        send_heartbeat()
        time.sleep(HEARTBEAT_INTERVAL)


import signal


def _handle_signal(signum, frame):
    print("\n[contextcut] Shutting down gracefully...")
    shutdown_hook()
    os._exit(0)


# ── Load .env into os.environ early so module-level defaults reflect .env ──
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
            if _k and _k not in os.environ:
                os.environ[_k] = _v

# ── Lazy clients ──────────────────────────────────────────────────────────────
_vc = None
_qclient = None
_last_embed_ts = 0.0
_VK = (
    os.environ.get("VOYAGE_API_KEY", "").strip().strip('"').strip("'")
)  # strip accidental quotes
_LOCAL_EMBED = (
    os.environ.get("CONTEXTCUT_EMBED_MODEL", "").strip().strip('"').strip("'")
)
_EMBED_MODE = (
    os.environ.get("CONTEXTCUT_EMBED_MODE", "voyage").strip().strip('"').strip("'")
)


def get_clients():
    global _vc, _qclient
    if _vc is None and _VK and _VOYAGE_AVAILABLE:
        print(f"[contextcut] Voyage API key loaded: {_VK[:8]}...")
        _vc = _voyage_mod.Client(api_key=_VK)
    if _qclient is None:
        _qclient = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    return _vc, _qclient


def _ollama_embed(text: str, model: str) -> list[float] | None:
    """Embed using Ollama's /api/embed endpoint."""
    try:
        payload = json.dumps({"model": model, "input": text}).encode()
        req = urllib.request.Request(
            f"{UPSTREAM}/api/embed", data=payload, method="POST"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        embeddings = data.get("embeddings", [])
        if embeddings:
            return embeddings[0]
        return None
    except Exception as e:
        print(f"[contextcut] Ollama embed error: {e}")
        return None


# ── Qdrant lookup ─────────────────────────────────────────────────────────────
def _safe_embed(query: str, input_type: str) -> list[float] | None:
    """Embed with retry. Uses configured backend: voyage or ollama."""
    global _last_embed_ts

    if _EMBED_MODE == "voyage" and _VK and _VOYAGE_AVAILABLE:
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
                    print(
                        f"[contextcut] Voyage rate-limited, backing off {wait:.0f}s (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait)
                else:
                    print(f"[contextcut] Voyage embed error: {e}")
                    if _LOCAL_EMBED:
                        print(
                            f"[contextcut] Falling back to Ollama embed: {_LOCAL_EMBED}"
                        )
                        return _ollama_embed(query, _LOCAL_EMBED)
                    return None
        print(f"[contextcut] Voyage embed failed after {max_retries} retries")
        if _LOCAL_EMBED:
            return _ollama_embed(query, _LOCAL_EMBED)
        return None

    # Ollama local embed
    if _LOCAL_EMBED:
        return _ollama_embed(query, _LOCAL_EMBED)

    print("[contextcut] WARNING: No embedding backend configured")
    return None


def _sync_env_on_startup():
    """Sync embed settings between .env and runtime variables.
    On fresh install, .env (set by install.sh) is authoritative for ingest.py.
    Runtime creds (from dashboard settings) take precedence when set."""
    try:
        env_path = Path(__file__).parent / ".env"
        env_lines = {}
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env_lines[k.strip()] = v.strip()

        # If runtime embed mode is empty, pull from .env (fresh install path)
        global _EMBED_MODE, _LOCAL_EMBED, _VK
        if not _EMBED_MODE:
            _EMBED_MODE = env_lines.get("CONTEXTCUT_EMBED_MODE", "")
        if not _LOCAL_EMBED:
            _LOCAL_EMBED = env_lines.get("CONTEXTCUT_EMBED_MODEL", "")
        # Default local embed model if mode is ollama but no model specified
        if _EMBED_MODE == "ollama" and not _LOCAL_EMBED:
            _LOCAL_EMBED = "nomic-embed-text"
        if not _VK:
            _VK = env_lines.get("VOYAGE_API_KEY", "")

        # Now sync runtime -> .env so ingest.py subprocess picks them up
        env_lines["CONTEXTCUT_EMBED_MODE"] = _EMBED_MODE
        if _EMBED_MODE == "ollama":
            env_lines["CONTEXTCUT_EMBED_MODEL"] = _LOCAL_EMBED
        elif "CONTEXTCUT_EMBED_MODEL" in env_lines:
            del env_lines["CONTEXTCUT_EMBED_MODEL"]
        if _VK:
            env_lines["VOYAGE_API_KEY"] = _VK

        with open(env_path, "w") as f:
            for k, v in env_lines.items():
                f.write(f"{k}={v}\n")
        if _EMBED_MODE == "voyage":
            print(f"[contextcut] .env synced: mode=voyage (voyage-3)")
        else:
            print(f"[contextcut] .env synced: mode=ollama model={_LOCAL_EMBED}")
    except Exception as e:
        print(f"[contextcut] .env sync warning: {e}")


def ensure_collection_dim():
    """Check Qdrant collection dimension matches current embed model; recreate if needed."""
    try:
        expected_dim = _get_embed_dim(_LOCAL_EMBED if _EMBED_MODE == "ollama" else "")
        qclient = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        try:
            info = qclient.get_collection(COLLECTION)
            actual_dim = info.config.params.vectors.size
            if actual_dim != expected_dim:
                print(
                    f"[contextcut] Dimension mismatch: collection={actual_dim}, model={expected_dim}. Recreating..."
                )
                qclient.delete_collection(COLLECTION)
                time.sleep(2)
                qclient.create_collection(
                    collection_name=COLLECTION,
                    vectors_config=VectorParams(
                        size=expected_dim, distance=Distance.COSINE
                    ),
                )
                print(f"[contextcut] Collection recreated with dim={expected_dim}")
            else:
                print(f"[contextcut] Qdrant collection dim={actual_dim} OK")
        except Exception:
            # Collection doesn't exist yet, create it
            print(f"[contextcut] Creating Qdrant collection with dim={expected_dim}")
            qclient.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(
                    size=expected_dim, distance=Distance.COSINE
                ),
            )
    except Exception as e:
        print(f"[contextcut] Collection dimension check warning: {e}")


def qdrant_context(query: str) -> tuple[str, list[dict]]:
    try:
        emb = _safe_embed(query, input_type="query")
        if emb is None:
            print(
                f"[contextcut] qdrant_context: embed returned None for query={query[:60]!r}"
            )
            return "", []
        vc, qclient = get_clients()
        response = qclient.query_points(
            collection_name=COLLECTION,
            query=emb,
            limit=TOP_K * 2,
            with_payload=True,
            with_vectors=False,
        )
        chunks, meta, seen_ids = [], [], set()
        for h in response.points:
            score = round(h.score, 3)
            if score < MIN_SCORE:
                print(
                    f"[contextcut] skip score={score} < {MIN_SCORE} for {h.payload.get('filename', '?')}"
                )
                continue
            seen_ids.add(h.id)
            src = h.payload.get("filename", h.payload.get("source", "?"))
            text = h.payload.get("text", "")
            chunks.append(f"[{src} | relevance={score}]\n{text}")
            meta.append({"source": src, "score": score, "chars": len(text)})

        # keyword fallback: proper nouns from query → substring match in Python
        query_words = query.split()
        proper_nouns = [w for w in query_words if len(w) > 2 and w[0].isupper()]
        if proper_nouns:
            try:
                all_points = qclient.scroll(COLLECTION, limit=500, with_payload=True)[0]
                for kw in proper_nouns:
                    kw_lower = kw.lower()
                    matched = 0
                    for h in all_points:
                        if matched >= 3:
                            break
                        if h.id in seen_ids:
                            continue
                        txt = (h.payload.get("text", "") or "").lower()
                        fn = (h.payload.get("filename", "") or "").lower()
                        if kw_lower in txt or kw_lower in fn:
                            seen_ids.add(h.id)
                            src = h.payload.get("filename", "?")
                            text = h.payload.get("text", "")
                            chunks.append(f"[{src} | keyword:{kw}]\n{text}")
                            meta.append({"source": src, "score": 0.0, "chars": len(text), "keyword": kw})
                            matched += 1
            except Exception:
                pass

        if meta:
            print(
                f"[contextcut] qdrant_context: {len(meta)} hits for query={query[:60]!r}"
            )
        else:
            print(f"[contextcut] qdrant_context: 0 hits for query={query[:60]!r}")
        ctx_str = "\n\n---\n\n".join(chunks)
        if len(ctx_str) > MAX_CTX_CHARS:
            print(f"[contextcut] truncating context {len(ctx_str)} → {MAX_CTX_CHARS} chars")
            ctx_str = ctx_str[:MAX_CTX_CHARS] + "\n\n[...truncated...]"
        return ctx_str, meta
    except Exception as e:
        print(f"[contextcut] Qdrant error: {e}")
        import traceback

        traceback.print_exc()
        return "", []


# ── Context injection ─────────────────────────────────────────────────────────
SYSTEM_BASE = (
    "You are a helpful AI assistant. "
    "Use the provided context to answer the user's question. "
    "Cite the source filename in brackets (e.g., [filename.md]) for each "
    "claim you make from the context. "
    "If the context does not contain relevant information, say so clearly "
    "rather than fabricating details."
)


def inject_context(body: dict, context: str) -> dict:
    messages = body.get("messages", [])
    has_system = bool(messages and messages[0].get("role") == "system")
    ctx_block = ""
    if context:
        ctx_block = "## Relevant context (semantic search):\n\n" + context + "\n\n---"
    if has_system:
        existing = messages[0]["content"]
        parts = [existing, SYSTEM_BASE]
        if ctx_block:
            parts.append(ctx_block)
        messages[0]["content"] = "\n\n".join(parts)
    else:
        parts = [SYSTEM_BASE]
        if ctx_block:
            parts.append(ctx_block)
        messages.insert(0, {"role": "system", "content": "\n\n".join(parts)})
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
    daemon_threads = True


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
    def log_message(self, fmt, *args):
        pass

    def _forward(
        self,
        method: str,
        raw_body: bytes,
        streaming: bool = False,
        session_id: str = None,
    ):
        upstream = get_current_upstream()

        # Cloud providers use {base}/v1/chat/completions, Ollama uses {base}/v1/chat/completions too
        upstream_url = upstream + self.path

        req = urllib.request.Request(
            upstream_url, data=raw_body if method == "POST" else None, method=method
        )

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
                                add_to_history(
                                    session_id, "assistant", "".join(full_response)
                                )
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
                                        delta = chunk_data.get("choices", [{}])[0].get(
                                            "delta", {}
                                        )
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
                            assistant_msg = (
                                resp_json.get("choices", [{}])[0]
                                .get("message", {})
                                .get("content", "")
                            )
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
        length = int(self.headers.get("Content-Length", 0))
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

                new_user_content = (
                    body["messages"][-1].get("content", "") if body["messages"] else ""
                )
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
                            body["messages"] = build_revision_prompt(
                                last_user, last_assistant, new_user_content
                            )

                elif action == "continue":
                    session = _sessions.get(session_id)
                    if session and session["history"]:
                        body["messages"] = list(session["history"])
                        body["messages"].append(
                            {
                                "role": "user",
                                "content": "Please continue your previous response.",
                            }
                        )

                elif action != "stop":
                    if len(body["messages"]) == 1:
                        body["messages"] = build_messages_with_history(
                            session_id, new_user_content
                        )

                add_to_history(session_id, "user", new_user_content)

            for msg in reversed(body["messages"]):
                if msg.get("role") == "user":
                    c = msg.get("content", "")
                    query = c if isinstance(c, str) else str(c)
                    break
            tok_before = count_body_tokens(body)
            if query:
                ctx, hits_meta = qdrant_context(query)
                body = inject_context(body, ctx)
                tok_after = count_body_tokens(body)
                if tok_after > CTX_LIMIT:
                    pruned = 0
                    for msg in body.get("messages", []):
                        if msg.get("role") == "system" and msg["content"].startswith(
                            "## Relevant context"
                        ):
                            parts = msg["content"].split("\n\n---\n\n")
                            while (
                                len(parts) > 2 and count_body_tokens(body) > CTX_LIMIT
                            ):
                                removed = parts.pop(-2)
                                msg["content"] = "\n\n---\n\n".join(parts)
                                pruned += 1
                                tok_after = count_body_tokens(body)
                            if pruned:
                                print(
                                    f"[contextcut] context truncated: removed {pruned} chunk(s) to fit {CTX_LIMIT}"
                                )
                                if session_id and session_id in _sessions:
                                    _sessions[session_id]["ctx_limit_reached"] = True
                            break
                raw_body = json.dumps(body).encode()
            tok_after = count_body_tokens(body)
            pct = round(tok_after / CTX_LIMIT * 100, 1)
            ts = datetime.now().strftime("%H:%M:%S")
            model_name = body.get("model", "?")
            print(
                f"[contextcut] {ts} | model={model_name} | {tok_before}→{tok_after}/{CTX_LIMIT} ({pct}%) | hits:{len(hits_meta)} | {query[:60]}"
            )
            record(
                {
                    "ts": ts,
                    "query": query[:120],
                    "tokens_before": tok_before,
                    "tokens_after": tok_after,
                    "ctx_limit": CTX_LIMIT,
                    "pct": pct,
                    "hits": hits_meta,
                }
            )

        is_streaming = isinstance(body, dict) and body.get("stream", False)
        if self.path in (
            "/api/pull",
            "/api/push",
            "/api/delete",
            "/api/copy",
            "/api/create",
        ):
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Blocked by proxy"}).encode())
            return
        self._forward(
            "POST",
            raw_body,
            streaming=is_streaming,
            session_id=body.get("session_id") if body else None,
        )

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
        s = dict(_stats)
    r = rows[0] if rows else {}
    return {
        "pct": r.get("pct", 0),
        "tokens_before": r.get("tokens_before", 0),
        "tokens_after": r.get("tokens_after", 0),
        "hits": r.get("hits", []),
        "total_saved": s["total_saved"],
        "total_requests": s["total_requests"],
        "max_tokens_seen": s["max_tokens_seen"],
        "cache_hits": s["cache_hits"],
        "start_time": s["start_time"],
    }


def make_dashboard() -> str:
    with _lock:
        rows = list(_log)
        s = dict(_stats)

    last_pct = rows[0]["pct"] if rows else 0
    last_tok = rows[0]["tokens_after"] if rows else 0
    bc = pct_color(last_pct)

    rows_html = ""
    for r in rows:
        p = r["pct"]
        col = pct_color(p)
        hits_str = (
            " ".join(
                f'<span class="hit">{html.escape(h["source"].replace(".md", ""))} <em>{h["score"]}</em></span>'
                for h in r.get("hits", [])
            )
            or '<span class="nh">—</span>'
        )
        bar = f'<div class="mini-bar"><div class="mini-fill" style="width:{min(p, 100)}%;background:{col}"></div></div>'
        rows_html += f"""<tr>
          <td class="ts">{r["ts"]}</td>
          <td class="qcell">{html.escape(r["query"])}</td>
          <td class="num">{r["tokens_before"]}</td>
          <td class="num">{r["tokens_after"]}</td>
          <td class="num" style="color:{col}">{p}%{bar}</td>
          <td class="hitcell">{hits_str}</td>
        </tr>"""

    no_rows = '<tr><td colspan="6" class="empty">No requests yet — send a message below</td></tr>'

    return f"""<!DOCTYPE html>
"""


def make_settings_page():
    current_provider = _provider_name
    current_url = (
        _custom_base_url
        if current_provider == "Custom"
        else PROVIDERS.get(current_provider, {}).get("url", "")
    )
    ollama_input_url = _ollama_url if _ollama_url else UPSTREAM
    has_key = bool(_api_key)
    masked_key = "••••••••••••••••" if has_key else ""
    provider_opts = "".join(
        f'<option value="{k}" {"selected" if k == current_provider else ""}>{k}</option>'
        for k in PROVIDERS.keys()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ContextCut-PRO — Settings</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
<style>
:root{{--bg:#0d111e;--surf:#131a2b;--surf2:#182233;--border:#1e2d42;--text:#d1dce8;--muted:#5a7a9a;--accent:#00d4ff;--green:#22c55e;--yellow:#f59e0b;--red:#ef4444;--th-bg:#0a1628;--hit-bg:#0a1a2e;--hover-bg:#1e293b;--active-bg:#0f172a;--r:6px}}
.light{{--bg:#f4f7fb;--surf:#fff;--surf2:#edf2f7;--border:#cbd5e1;--text:#0f172a;--muted:#475569;--accent:#0284c7;--th-bg:#e2e8f0;--hit-bg:#f1f5f9;--hover-bg:#f1f5f9;--active-bg:#e2e8f0}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'JetBrains Mono',monospace;font-size:13px;display:flex;flex-direction:column;height:100vh;transition:background .3s,color .3s}}
.header{{background:var(--surf);border-bottom:1px solid var(--border);padding:0 20px;display:flex;align-items:center;gap:14px;height:48px;flex-shrink:0}}
.logo{{font-family:'Syne',sans-serif;font-size:20px;font-weight:800;color:var(--accent);letter-spacing:-.5px}}
.logo span{{color:var(--text)}}
.back-btn{{background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:3px 10px;font-size:11px;cursor:pointer;font-family:'JetBrains Mono',monospace;margin-left:auto;text-decoration:none}}
.back-btn:hover{{color:var(--text);border-color:var(--accent)}}
.tog{{background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:3px 8px;font-size:13px;cursor:pointer;line-height:1;flex-shrink:0}}
.tog:hover{{color:var(--text);border-color:var(--accent)}}
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
  <button class="tog" id="togBtn" title="Toggle day/night">☀</button>
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

    <div id="cloudWarning" style="display:none;background:#2a0a0a;border:1px solid #dc2626;border-radius:6px;padding:12px;margin-bottom:16px">
      <div style="color:#ef4444;font-weight:700;font-size:13px;margin-bottom:4px">&#9888; DATA LEAVES YOUR MACHINE</div>
      <div style="color:#fca5a5;font-size:11px;line-height:1.5">This provider runs on remote servers. Your queries, context from your knowledge base, and conversation history will be sent to a third party. Review their privacy policy and terms of service before use. Only local Ollama models keep 100% of your data on your machine.</div>
    </div>

    <div class="form-group hidden" id="ollamaUrlGroup">
      <label>Ollama URL</label>
      <input type="text" id="ollamaUrl" value="{ollama_input_url}" placeholder="http://localhost:11434">
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

    <div class="form-group hidden" id="ollamaLocalGroup">
      <label style="cursor:pointer;display:flex;align-items:center;gap:8px">
        <input type="checkbox" id="ollamaLocalOnly" style="width:auto;accent-color:var(--accent)"{" checked" if _local_only else ""}>
        Local models only (exclude cloud)
      </label>
    </div>

    <div class="form-group hidden" id="freeOnlyGroup">
      <label style="cursor:pointer;display:flex;align-items:center;gap:8px">
        <input type="checkbox" id="freeOnly" style="width:auto;accent-color:var(--accent)"{" checked" if _free_only else ""}>
        Only free models (OpenRouter)
      </label>
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
  const l = document.getElementById('ollamaLocalGroup');
  const c = document.getElementById('customUrlGroup');
  const f = document.getElementById('freeOnlyGroup');
  const k = document.getElementById('apiKey');
  const w = document.getElementById('cloudWarning');
  if (p === 'Ollama') {{
    o.classList.remove('hidden');
    l.classList.remove('hidden');
    c.classList.add('hidden');
    f.classList.add('hidden');
    k.placeholder = 'Not required for local Ollama';
    w.style.display = 'none';
  }} else {{
    o.classList.add('hidden');
    l.classList.add('hidden');
    if (p === 'Custom') c.classList.remove('hidden');
    else c.classList.add('hidden');
    if (p === 'OpenRouter') f.classList.remove('hidden');
    else f.classList.add('hidden');
    k.placeholder = 'Enter your API key';
    w.style.display = 'block';
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
    const freeOnly = document.getElementById('freeOnly').checked;
    const localOnly = document.getElementById('ollamaLocalOnly').checked;
    const resp = await fetch('/api/settings/models', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{provider, api_key: apiKey, custom_url: customUrl, ollama_url: ollamaUrl, free_only: freeOnly, local_only: localOnly}})
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
    const freeOnly = document.getElementById('freeOnly').checked;
    const localOnly = document.getElementById('ollamaLocalOnly').checked;
    const resp = await fetch('/api/settings/provider', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{provider, api_key: apiKey, custom_url: customUrl, ollama_url: ollamaUrl, free_only: freeOnly, local_only: localOnly, model: selectedModelName}})
    }});
    const data = await resp.json();
    if (data.ok) {{
      if (selectedModelName) localStorage.setItem('contextcut_model', selectedModelName);
      if (typeof sessionId !== 'undefined' && sessionId) localStorage.setItem('contextcut_session', sessionId);
      const msgs = document.getElementById('messages');
      if (msgs) localStorage.setItem('contextcut_msgs', msgs.innerHTML);
      status.textContent = 'Saved! Switching to dashboard...';
      status.className = 'status ok';
      setTimeout(() => {{ window.location.href = '/'; }}, 500);
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

(function(){{
  var t=localStorage.getItem('ccTheme');
  if(!t)t=window.matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light';
  if(t==='light')document.body.classList.add('light');
  var b=document.getElementById('togBtn');
  if(b)b.textContent=t==='light'?'☽':'☀';
}})();
function togTheme(){{
  document.body.classList.toggle('light');
  var l=document.body.classList.contains('light');
  localStorage.setItem('ccTheme',l?'light':'dark');
  document.getElementById('togBtn').textContent=l?'☽':'☀';
}}
onProviderChange();
document.getElementById('togBtn').addEventListener('click',togTheme);
</script>
</body>
</html>"""


def make_dashboard():
    with _lock:
        rows = list(_log)
        s = dict(_stats)

    last_pct = (
        rows[0]["pct"] if rows and rows[0].get("type") != "provider_switch" else 0
    )
    last_tok = (
        rows[0]["tokens_after"]
        if rows and rows[0].get("type") != "provider_switch"
        else 0
    )
    bc = pct_color(last_pct)

    is_cloud = _provider_name != "Ollama" or not _local_only

    cloud_banner = ""
    if is_cloud:
        cloud_banner = f"""<div class="cloud-banner">
  <span style="font-size:18px;margin-right:10px">&#9888;</span>
  <div style="flex:1">
    <strong>DATA LEAVES YOUR MACHINE</strong> &mdash; Using <b>{html.escape(_provider_name)}</b>
    <div style="font-size:12px;opacity:.9;margin-top:2px">Your queries and context from your knowledge base are sent to a third-party server. Switch back to <b>Ollama</b> with <b>Local models only</b> checked for 100% local processing.</div>
  </div>
  <a href="/settings" style="background:#dc2626;color:#fff;border:none;border-radius:4px;padding:6px 14px;font-size:12px;font-weight:600;text-decoration:none;white-space:nowrap">Settings &rarr;</a>
</div>"""

    rows_html = ""
    for r in rows:
        if r.get("type") == "provider_switch":
            cloud_cls = "cloud-on" if r.get("is_cloud") else "cloud-off"
            rows_html += f"""<tr class="{cloud_cls}">
              <td class="ts">{r["ts"]}</td>
              <td class="qcell" colspan="5" style="font-weight:600">{html.escape(r["query"])}</td>
            </tr>"""
            continue
        p = r["pct"]
        col = pct_color(p)
        hits_str = (
            " ".join(
                f'<span class="hit">{html.escape(h["source"].replace(".md", ""))} <em>{h["score"]}</em></span>'
                for h in r.get("hits", [])
            )
            or '<span class="nh">—</span>'
        )
        bar = f'<div class="mini-bar"><div class="mini-fill" style="width:{min(p, 100)}%;background:{col}"></div></div>'
        rows_html += f"""<tr>
          <td class="ts">{r["ts"]}</td>
          <td class="qcell">{html.escape(r["query"])}</td>
          <td class="num">{r["tokens_before"]}</td>
          <td class="num">{r["tokens_after"]}</td>
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
:root{{--bg:#0d111e;--surf:#131a2b;--surf2:#182233;--border:#1e2d42;--text:#d1dce8;--muted:#5a7a9a;--accent:#00d4ff;--green:#22c55e;--yellow:#f59e0b;--red:#ef4444;--th-bg:#0a1628;--hit-bg:#0a1a2e;--hover:#1e293b;--active:#0f172a;--r:6px}}
.light{{--bg:#f4f7fb;--surf:#fff;--surf2:#edf2f7;--border:#cbd5e1;--text:#0f172a;--muted:#475569;--accent:#0284c7;--th-bg:#e2e8f0;--hit-bg:#f1f5f9;--hover:#f1f5f9;--active:#e2e8f0}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'JetBrains Mono',monospace;font-size:13px;display:flex;flex-direction:column;height:100vh;overflow:hidden;transition:background .3s,color .3s}}
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
.ctx-fill{{height:100%;border-radius:3px;transition:width .5s;background:{bc};width:{min(last_pct, 100)}%}}
.ctx-info{{display:flex;justify-content:space-between;margin-top:4px;font-size:10px;color:var(--muted)}}
/* table */
.tbl-wrap{{background:var(--surf);border:1px solid var(--border);border-radius:var(--r);overflow:hidden}}
table{{width:100%;border-collapse:collapse}}
th{{background:var(--th-bg);color:var(--muted);text-align:left;padding:8px 10px;font-size:9px;text-transform:uppercase;letter-spacing:.1em;border-bottom:1px solid var(--border)}}
td{{padding:7px 10px;border-top:1px solid var(--border);vertical-align:middle;font-size:12px}}
tr:hover td{{background:var(--surf2)}}
.ts{{color:var(--muted);white-space:nowrap;font-size:10px}}
.qcell{{max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.num{{text-align:right;white-space:nowrap}}
.hitcell{{max-width:180px}}
.hit{{display:inline-block;background:var(--hit-bg);border:1px solid var(--border);border-radius:3px;padding:1px 4px;margin:1px;font-size:10px;color:var(--muted)}}
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
.tog{{background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:3px 8px;font-size:13px;cursor:pointer;line-height:1;flex-shrink:0}}
.tog:hover{{color:var(--text);border-color:var(--accent)}}
.badge{{font-size:11px;padding:3px 8px;border-radius:4px;color:var(--muted);background:var(--hit-bg)}}
.nh{{color:var(--muted)}}
.fb-file:hover{{background:var(--hover,#f1f5f9)}}
.fb-file:active{{background:var(--active,#e2e8f0)}}
.fb-file.selected{{background:var(--active,#1e293b)}}
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
.model-combo{{flex:1;display:flex;gap:4px;min-width:0;overflow:hidden}}
.model-input{{flex:1;background:var(--bg);border:1px solid var(--border);border-radius:var(--r);padding:5px 9px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:12px;outline:none;min-width:0;width:60px}}
.model-input:focus{{border-color:var(--accent)}}
.model-select{{background:var(--bg);border:1px solid var(--border);border-radius:var(--r);padding:4px 6px;color:var(--muted);font-size:11px;cursor:pointer;outline:none;font-family:'JetBrains Mono',monospace;max-width:100%;overflow:hidden}}
.model-select:focus{{border-color:var(--accent)}}
.model-select option{{background:var(--surf);color:var(--text)}}
.input-row{{display:flex;gap:8px;align-items:flex-end}}
.chat-input{{flex:1;background:var(--bg);border:1px solid var(--border);border-radius:var(--r);padding:8px 12px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:13px;resize:none;outline:none;line-height:1.5;max-height:120px}}
.chat-input:focus{{border-color:var(--accent)}}
.send-btn{{background:var(--accent);color:#000;border:none;border-radius:var(--r);padding:8px 16px;font-family:'Syne',sans-serif;font-weight:700;font-size:13px;cursor:pointer;white-space:nowrap;height:38px}}
.send-btn:hover{{opacity:.85}}.send-btn:disabled{{opacity:.4;cursor:not-allowed}}
.att-btn{{background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:var(--r);padding:8px 10px;font-size:14px;cursor:pointer;line-height:1;flex-shrink:0}}
.agent-toggle.agent-on{{background:var(--accent);color:#000;border-color:var(--accent);font-weight:600}}
.scan-toggle{{background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:8px 10px;font-size:11px;cursor:pointer;line-height:1;flex-shrink:0;font-family:'JetBrains Mono',monospace}}
.scan-toggle.scan-on{{background:#f59e0b;color:#000;border-color:#f59e0b;font-weight:600}}
.suspect{{background:rgba(245,158,11,0.2);border-left:3px solid #f59e0b;padding:2px 6px;border-radius:2px}}
.tool-call{{background:var(--surf2);border:1px solid var(--border);border-radius:var(--r);padding:8px 12px;margin:6px 0;font-size:12px}}
.tool-call summary{{cursor:pointer;color:var(--accent);font-weight:600}}
.tool-call .tool-name{{color:var(--yellow)}}
.tool-call .tool-input{{color:var(--muted);white-space:pre-wrap;word-break:break-word;font-size:11px;margin-top:4px}}
.tool-call .tool-result{{color:var(--text);white-space:pre-wrap;word-break:break-word;font-size:11px;margin-top:4px;max-height:200px;overflow-y:auto;background:var(--bg);padding:6px;border-radius:3px}}
.shell-btns{{display:flex;gap:4px;margin-top:6px}}
.shell-btns button{{background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:2px 8px;font-size:10px;cursor:pointer;font-family:'JetBrains Mono',monospace}}
.shell-btns button:hover{{border-color:var(--accent);color:var(--accent)}}
.shell-btns button.allow{{color:var(--green);border-color:var(--green)}}
.shell-btns button.allow:hover{{background:var(--green);color:#000}}
.shell-btns button.deny{{color:var(--red);border-color:var(--red)}}
.shell-btns button.deny:hover{{background:var(--red);color:#000}}
/* ── Settings panel ── */
.settings-row{{display:flex;align-items:center;gap:6px;flex-wrap:wrap}}
.param-group{{display:flex;align-items:center;gap:4px}}
.param-label{{font-size:10px;color:var(--muted);white-space:nowrap}}
.param-slider{{width:60px;height:4px;-webkit-appearance:none;background:var(--border);border-radius:2px;outline:none;cursor:pointer}}
.param-slider::-webkit-slider-thumb{{-webkit-appearance:none;width:12px;height:12px;border-radius:50%;background:var(--accent);cursor:pointer}}
.param-val{{font-size:10px;color:var(--accent);min-width:28px;text-align:center;font-family:'JetBrains Mono',monospace}}
.settings-toggle{{background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:3px 8px;font-size:10px;cursor:pointer;font-family:'JetBrains Mono',monospace;flex-shrink:0;white-space:nowrap}}
.settings-toggle:hover{{color:var(--text);border-color:var(--accent)}}
.settings-panel{{display:none;background:var(--surf);border-top:1px solid var(--border);padding:8px 10px}}
.settings-panel.open{{display:block}}
.right.fullscreen{{position:fixed;top:48px;left:0;right:0;bottom:0;z-index:100;background:var(--bg);border-top:1px solid var(--border)}}
.right.fullscreen .chat-messages{{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}}
.right.fullscreen .chat-input-bar{{flex-shrink:0}}
#tourOv{{position:fixed;top:0;left:0;right:0;bottom:0;z-index:9998;display:none}}
#tourOv.on{{display:block}}
#tourSpot{{position:fixed;z-index:9999;pointer-events:none;border-radius:8px;box-shadow:0 0 0 9999px rgba(0,0,0,.55);transition:all .35s ease}}
#tourTip{{position:fixed;z-index:10000;background:var(--surf);border:1px solid var(--accent);border-radius:10px;padding:18px 22px;max-width:380px;box-shadow:0 8px 32px rgba(0,0,0,.5);display:none}}
#tourTip.on{{display:block}}
#tourTip h3{{color:var(--accent);font-size:14px;font-weight:700;margin-bottom:6px;font-family:'Syne',sans-serif}}
#tourTip p{{color:var(--text);font-size:12px;line-height:1.7;margin-bottom:14px}}
#tourTip .tc{{display:flex;align-items:center;justify-content:space-between}}
#tourTip .tc .step{{color:var(--muted);font-size:11px}}
#tourTip .tc .btns{{display:flex;gap:6px}}
#tourTip .tc button{{background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:5px;padding:6px 14px;font-size:11px;cursor:pointer;font-family:'JetBrains Mono',monospace}}
#tourTip .tc button:hover{{border-color:var(--accent);color:var(--accent)}}
#tourTip .tc button.prim{{background:var(--accent);border-color:var(--accent);color:#000;font-weight:700}}
.cloud-banner{{display:flex;align-items:center;gap:12px;background:#2a0a0a;border-bottom:2px solid #dc2626;padding:10px 20px;color:#fca5a5;font-size:13px;flex-shrink:0}}
.cloud-banner strong{{color:#ef4444}}
tr.cloud-on td{{background:#2a0a0a!important;color:#fca5a5!important;border-top-color:#dc2626!important}}
tr.cloud-off td{{background:#0a1a2e!important;color:#22c55e!important;border-top-color:#22c55e!important}}
</style>
</head>
<body>

<div class="header">
  <div class="logo">ContextCut<span>-PRO</span></div>
  <div class="hinfo">{UPSTREAM} · Qdrant {QDRANT_HOST}:{QDRANT_PORT} · min_score={MIN_SCORE} · top_k={TOP_K}</div>
  <button class="tog" id="togBtn" title="Toggle day/night">☀</button>
  <a href="/settings" style="background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:3px 10px;font-size:11px;cursor:pointer;font-family:'JetBrains Mono',monospace;text-decoration:none">LLM-Provider ⚙</a>
  <button onclick="openFileBrowser()" style="background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:3px 10px;font-size:11px;cursor:pointer;font-family:'JetBrains Mono',monospace">Browse Files 📂</button>
  <a href="/api/logs/export" style="background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:3px 8px;font-size:11px;cursor:pointer;font-family:'JetBrains Mono',monospace;text-decoration:none" title="Download audit log CSV">Export Log</a>
  <button onclick="seedDemo()" style="background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:3px 8px;font-size:11px;cursor:pointer;font-family:'JetBrains Mono',monospace" title="Load sample data for demo">Demo Data</button>
  <button onclick="openHistory()" style="background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:3px 8px;font-size:11px;cursor:pointer;font-family:'JetBrains Mono',monospace" title="Browse past chat sessions" id="histBtn">History</button>
  <button onclick="startTour()" style="background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:3px 8px;font-size:11px;cursor:pointer;font-family:'JetBrains Mono',monospace" title="Guided tour">Tour</button>
  <div class="live"><span class="dot"></span>live</div>
</div>

{cloud_banner}

<div class="main">

  <!-- ── LEFT: Stats + Table ── -->
  <div class="left">
    <div class="left-scroll">
      <div class="cards">
        <div class="card"><div class="card-label">License</div><div class="card-val" id="cardLicense" style="font-size:13px">—</div></div>
        <div class="card"><div class="card-label">Requests</div><div class="card-val" id="cardReq">{s["total_requests"]}</div></div>
        <div class="card"><div class="card-label">Last CTX</div><div class="card-val {"green" if last_pct < 60 else "yellow" if last_pct < 80 else "red"}" id="cardCtx">{last_pct}%</div></div>
        <div class="card"><div class="card-label">Tokens Saved</div><div class="card-val green" id="cardSave">{s.get("total_saved", 0):,}</div></div>
        <div class="card"><div class="card-label">Peak Tokens</div><div class="card-val {"red" if s["max_tokens_seen"] > CTX_LIMIT * 0.8 else ""}" id="cardPeak">{s["max_tokens_seen"]:,}</div></div>
        <div class="card"><div class="card-label">CTX Limit</div><div class="card-val">{CTX_LIMIT:,}</div></div>
        <div class="card"><div class="card-label">GPU</div><div class="card-val" id="cardGpu" style="font-size:12px">—</div></div>
        <div class="card"><div class="card-label">Cache Hits</div><div class="card-val" style="font-size:13px" id="cardCache">{s.get("cache_hits", 0)}</div></div>
        </div>
      <div class="ctx-wrap">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:7px">
          <div class="ctx-label" style="margin-bottom:0">Most Recent Context Usage</div>
          <div style="display:flex;gap:6px;align-items:center">
            <span id="embedBadge" class="badge" title="Current embedding backend">—</span>
            <button class="clear-btn" onclick="openEmbedSettings()" title="Configure embedding model">⚙ Embed</button>
            <button class="clear-btn" onclick="clearContext()" title="Clears response cache and resets session context">Clear Context</button>
          </div>
        </div>
        <div class="ctx-track"><div class="ctx-fill" id="ctxBar"></div></div>
        <div class="ctx-info"><span id="ctxTok">{last_tok:,} / {CTX_LIMIT:,} tokens</span><strong style="color:{bc}" id="ctxPct">{last_pct}%</strong></div>
      </div>
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>Time</th><th>Query</th><th>Before</th><th>After</th><th>CTX%</th><th>Hits</th></tr></thead>
          <tbody id="tblBody">{rows_html if rows_html else no_rows}</tbody>
        </table>
        <div class="tbl-footer">Token counting: {TOKEN_METHOD} · auto-refreshes on each request</div>
        <div class="tbl-footer" style="border-top:none;padding-top:0">Chats saved to <code>.contextcut_sessions.db</code> &middot; Explore with <a href="https://github.com/simonw/datasette" target="_blank" style="color:var(--accent)">Datasette</a></div>
      </div>
    </div>
  </div>

  <!-- ── RIGHT: Chat ── -->
  <div class="right">
    <div class="chat-header" id="chatHeader">
      <span class="session-badge" id="sessionBadge">Session: new</span>
      <button class="clear-btn" id="fsBtn" onclick="toggleFullscreen()" title="Toggle fullscreen (F11)" style="font-size:15px;padding:2px 8px;line-height:1">⛶</button>
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
        <button class="settings-toggle" id="settingsToggle" onclick="toggleSettings()">Params ⚙</button>
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
            <input type="range" class="param-slider" id="minscoreSlider" min="0.0" max="1.0" step="0.05" value="{MIN_SCORE}" oninput="updateMinScore()">
            <span class="param-val" id="minscoreVal">{MIN_SCORE}</span>
          </div>
          <div class="param-group">
            <span class="param-label">Top-K:</span>
            <input type="range" class="param-slider" id="topkSlider" min="1" max="15" step="1" value="{TOP_K}" oninput="updateTopK()" style="width:50px">
            <span class="param-val" id="topkVal">{TOP_K}</span>
          </div>
          <div style="font-size:9px;color:var(--muted);margin-top:6px;border-top:1px solid var(--border);padding-top:6px">
            ⚡ 128K context = 5GB VRAM for KV cache. If responses take &gt;5s, your GPU is swapping models — set <code>OLLAMA_CONTEXT_LENGTH=32768</code> on the Ollama host to fit both embed &amp; chat models in VRAM.
          </div>
        </div>
      </div>
      <div class="input-row">
        <button class="att-btn" id="attachBtn" onclick="document.getElementById('fileInput').click()" title="Attach file to knowledge base">📎</button>
        <input type="file" id="fileInput" accept=".md,.txt,.py,.js,.ts,.html,.css,.csv,.json,.xml,.yaml,.yml,.go,.rs,.rb,.java,.c,.cpp,.h,.sh,.sql,.log,.pdf,.docx,.xlsx" style="display:none" onchange="attachFile(this)" />
        <textarea class="chat-input" id="chatInput" rows="2" role="textbox" aria-label="Message input"
          placeholder="Type a message… (Enter to send, Shift+Enter for newline). Try: /clear, /help"
          onkeydown="handleKey(event)"></textarea>
        <button class="scan-toggle" id="scanToggle" onclick="toggleScanMode()" title="Scan responses for potential hallucinations">🧪 Scan OFF</button>
        <button class="agent-toggle" id="agentToggle" onclick="toggleAgentMode()" title="Toggle Agent mode (tool-use)" style="background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:3px;padding:8px 10px;font-size:11px;cursor:pointer;line-height:1;flex-shrink:0;font-family:'JetBrains Mono',monospace">🤖 Agent OFF</button>
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
let agentMode = false;
let scanMode = false;
let scanPending = false;
let abortController = null;
let lastEsc = 0;

function toggleAgentMode() {{
  agentMode = !agentMode;
  const btn = document.getElementById('agentToggle');
  if (btn) {{
    btn.textContent = agentMode ? '🤖 Agent ON' : '🤖 Agent OFF';
    btn.classList.toggle('agent-on', agentMode);
  }}
  const input = document.getElementById('chatInput');
  if (input) {{
    input.placeholder = agentMode
      ? 'Agent: use tools, run code, search the web…'
      : 'Type a message… (Enter to send, Shift+Enter for newline). Try: /clear, /help';
  }}
}}

function toggleScanMode() {{
  scanMode = !scanMode;
  const btn = document.getElementById('scanToggle');
  if (btn) {{
    btn.textContent = scanMode ? '🧪 Scan ON' : '🧪 Scan OFF';
    btn.classList.toggle('scan-on', scanMode);
  }}
}}

function esc(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\\n/g,'<br>');
}}

async function shellConfirm(btn, allow) {{
  const btns = btn.parentElement;
  const cmd = btns.dataset.cmd || '';
  btns.innerHTML = allow ? '🟢 Allowed' : '🔴 Denied';
  // Send the decision back via a tool_result or similar mechanism
  // For now we just visually show the decision; in a full impl we'd
  // notify the server to continue/reject the pending tool.
}}

async function shellAlways() {{
  try {{
    await fetch('/api/agent/shell-mode', {{
      method: 'POST',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{session_id: sessionId, mode: 'always'}})
    }});
    document.querySelectorAll('.shell-btns').forEach(el => el.innerHTML = '🟢 Always Allow');
  }} catch(e) {{}}
}}

async function shellReject() {{
  try {{
    await fetch('/api/agent/shell-mode', {{
      method: 'POST',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{session_id: sessionId, mode: 'reject'}})
    }});
    document.querySelectorAll('.shell-btns').forEach(el => el.innerHTML = '🔴 Always Reject');
  }} catch(e) {{}}
}}

function handleKey(e) {{
  if (e.key === 'Escape') {{
    const now = Date.now();
    if (now - lastEsc < 500) {{
      lastEsc = 0;
      if (abortController) abortGeneration();
      return;
    }}
    lastEsc = now;
    return;
  }}
  lastEsc = 0;
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
  const saved = localStorage.getItem('contextcut_session');
  if (saved) {{
    sessionId = saved;
    localStorage.removeItem('contextcut_session');
    updateSessionBadge();
    restoreMessages();
    return;
  }}
  try {{
    const r = await fetch('/api/session/new');
    if (r.ok) {{
      const d = await r.json();
      sessionId = d.session_id;
      updateSessionBadge();
    }}
  }} catch(e) {{}}
}}

function restoreMessages() {{
  const saved = localStorage.getItem('contextcut_msgs');
  if (!saved) return;
  localStorage.removeItem('contextcut_msgs');
  const msgs = document.getElementById('messages');
  if (msgs) {{
    msgs.innerHTML = saved;
    msgs.querySelector('.bubble:last-of-type')?.scrollIntoView({{behavior:'instant', block:'end'}});
  }}
}}

function toggleFullscreen() {{
  document.querySelector('.right').classList.toggle('fullscreen');
}}

async function seedDemo() {{
  try {{
    const r = await fetch('/api/demo/seed');
    const d = await r.json();
    if (d.ok) {{
      const lr = await fetch('/log');
      if (lr.ok) {{
        const rows = await lr.json();
        const tb = document.getElementById('tblBody');
        if (tb) tb.innerHTML = rows.map(r => `<tr><td class="ts">${{r.ts}}</td><td class="qcell">${{esc(r.query.substring(0,60))}}</td><td class="num">${{r.tokens_before}}</td><td class="num">${{r.tokens_after}}</td><td class="num" style="color:var(--accent)">${{r.pct}}%</td><td class="hitcell">${{(r.hits||[]).map(h=>'<span class="hit">'+esc(h.source.replace(".md",""))+' <em>'+h.score+'</em></span>').join(' ')}}</td></tr>`).join('') + '<tr><td colspan="6" class="tbl-footer">Demo data loaded — ${{d.count}} requests</td></tr>';
      }}
      setTimeout(pollStats, 100);
    }}
  }} catch(e) {{}}
}}

const tourSteps = [
  {{sel:'.logo',title:'Dashboard Header',text:'ContextCut PRO dashboard with live status indicator. Green dot means the proxy is running and accepting requests.',pos:'bottom'}},
  {{sel:'button[onclick*="seedDemo"]',title:'Demo Data',text:'Click this to seed the audit log with sample queries from various professions (law, accounting, real estate, etc.). Demonstrates how real-world queries appear with before/after token counts and matched knowledge base hits.',pos:'bottom'}},
  {{sel:'button[onclick*="clearContext"]',title:'Clear Context',text:'Clears the response cache and resets session context without removing chat history.',pos:'bottom'}},
  {{sel:'.hinfo',title:'Connection Info',text:'Shows your LLM provider, Qdrant host, minimum relevance score, and Top-K setting. All configurable via the Settings page.',pos:'bottom'}},
  {{sel:'.cards',title:'Statistics Cards',text:'Real-time metrics: license status, total requests, context compression %, tokens saved, peak token usage, context limit, and cache hits.',pos:'bottom'}},
  {{sel:'.ctx-wrap',title:'Context Usage Meter',text:'Visual bar showing how much of your token limit the most recent request consumed. Green = efficient. Red = nearing the limit.',pos:'bottom'}},
  {{sel:'.tbl-wrap',title:'Audit Log',text:'Every query is logged with timestamp, before/after tokens, compression percentage, and which knowledge base files matched. Exportable as CSV.',pos:'top'}},
  {{sel:'.chat-messages',title:'Chat Area',text:'Conversation with your AI. Context from your knowledge base is injected automatically into every message — no manual work needed.',pos:'left'}},
  {{sel:'.chat-input-bar',title:'Message Input',text:'Type your question here. Press Enter to send. Session history is maintained automatically.',pos:'top'}},
  {{sel:'#modelSelect',title:'Model Selector',text:'Quick-select from available models including Ollama local models and cloud providers like minimax-m2, gemini-3-flash, and glm-4.7. Auto-populated on startup.',pos:'bottom'}},
  {{sel:'#fsBtn',title:'Fullscreen Mode',text:'Expand the chat panel to full screen for focused work. Toggle on/off with this button or press F11. The tour will show and then restore it.',pos:'bottom'}},
  {{sel:'#settingsPanel',title:'Settings Panel',text:'Fine-tune generation parameters: temperature (creativity), top-p (diversity), max tokens, and minimum relevance score for RAG retrieval. Expand by clicking the Params ⚙ button.',pos:'top'}},
  {{sel:'button[onclick*="openFileBrowser"]',title:'File Browser',text:'Upload and manage .md files in your knowledge base. Files are auto-ingested into Qdrant vectors within seconds of being added.',pos:'bottom'}},
];
let tourIdx = -1;
function startTour(){{
  if(document.getElementById('tourOv')) return;
  const ov = document.createElement('div'); ov.id = 'tourOv'; ov.className = 'on';
  const sp = document.createElement('div'); sp.id = 'tourSpot';
  const tip = document.createElement('div'); tip.id = 'tourTip';
  tip.innerHTML = '<h3 id="tourTitle"></h3><p id="tourText"></p><div class="tc"><span class="step" id="tourStep"></span><div class="btns"><button onclick="tourPrev()" id="tourPrevBtn">Back</button><button class="prim" onclick="tourNext()" id="tourNextBtn">Next</button><button onclick="endTour()" id="tourEndBtn" style="display:none" class="prim">Done</button></div></div>';
  document.body.appendChild(ov); document.body.appendChild(sp); document.body.appendChild(tip);
  tourIdx = -1; tourNext();
}}
function endTour(){{
  const ov = document.getElementById('tourOv'); const sp = document.getElementById('tourSpot'); const tip = document.getElementById('tourTip');
  if(ov)ov.remove(); if(sp)sp.remove(); if(tip)tip.remove();
  const sp2 = document.getElementById('settingsPanel'); if(sp2&&sp2.classList.contains('open')) toggleSettings();
  const rg = document.querySelector('.right'); if(rg&&rg.classList.contains('fullscreen')) toggleFullscreen();
  tourIdx = -1;
}}
function tourGo(i){{
  const s = tourSteps[i]; if(!s) return endTour();
  const sp = document.getElementById('settingsPanel');
  if(s.sel==='#settingsPanel'){{ if(sp&&!sp.classList.contains('open')) toggleSettings(); }}
  else if(sp&&sp.classList.contains('open')) toggleSettings();
  const rg = document.querySelector('.right');
  if(s.sel==='#fsBtn'){{ if(rg&&!rg.classList.contains('fullscreen')) toggleFullscreen(); }}
  else if(rg&&rg.classList.contains('fullscreen')) toggleFullscreen();
  const el = document.querySelector(s.sel); if(!el) return tourNext();
  const r = el.getBoundingClientRect();
  const spot = document.getElementById('tourSpot');
  if(spot){{ spot.style.left = (r.left-6)+'px'; spot.style.top = (r.top-6)+'px'; spot.style.width = (r.width+12)+'px'; spot.style.height = (r.height+12)+'px'; }}
  const tip = document.getElementById('tourTip');
  if(tip){{
    document.getElementById('tourTitle').textContent = s.title;
    document.getElementById('tourText').textContent = s.text;
    document.getElementById('tourStep').textContent = (i+1)+' / '+tourSteps.length;
    document.getElementById('tourPrevBtn').style.display = i===0?'none':'';
    document.getElementById('tourNextBtn').style.display = i===tourSteps.length-1?'none':'';
    document.getElementById('tourEndBtn').style.display = i===tourSteps.length-1?'':'none';
    var tx, ty;
    if(s.pos==='bottom'){{ tx = r.left; ty = r.bottom + 16; }}
    else if(s.pos==='top'){{ tx = r.left; ty = r.top - 16 - tip.offsetHeight; }}
    else if(s.pos==='left'){{ tx = r.left - 16 - tip.offsetWidth; ty = r.top; }}
    else{{ tx = r.right + 16; ty = r.top; }}
    if(ty < 10) ty = 10; if(tx < 10) tx = 10;
    if(ty + tip.offsetHeight > window.innerHeight - 10) ty = window.innerHeight - 10 - tip.offsetHeight;
    if(tx + tip.offsetWidth > window.innerWidth - 10) tx = window.innerWidth - 10 - tip.offsetWidth;
    tip.style.left = tx+'px'; tip.style.top = ty+'px'; tip.className = 'on';
    el.scrollIntoView({{behavior:'smooth',block:'center'}});
  }}
}}
function tourNext(){{
  const cur = tourSteps[tourIdx];
  if(cur){{ if(cur.sel==='button[onclick*="seedDemo"]') seedDemo(); else if(cur.sel==='button[onclick*="clearContext"]') clearContext(); }}
  tourIdx++; tourGo(tourIdx);
}}
function tourPrev(){{ tourIdx--; tourGo(tourIdx); }}

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

function updateTopK() {{
  const slider = document.getElementById('topkSlider');
  const val = document.getElementById('topkVal');
  if (slider && val) {{
    val.textContent = parseInt(slider.value);
    fetch('/api/settings', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{top_k: parseInt(slider.value)}})
    }}).catch(e => console.warn('top_k sync failed', e));
  }}
}}

function getGenerationParams() {{
  const temp = parseFloat(document.getElementById('tempSlider').value);
  const topP = parseFloat(document.getElementById('toppSlider').value);
  const maxTok = parseInt(document.getElementById('maxTokInput').value);
  document.getElementById('maxTokVal').textContent = maxTok || '0';
  const params = {{temperature: temp, top_p: topP, num_ctx: {CTX_LIMIT}}};
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

async function clearContext() {{
  if (sessionId) {{
    try {{ await fetch('/api/session/' + sessionId, {{method: 'DELETE'}}); }} catch(e) {{}}
    conversationHistory = [];
    const msgs = document.getElementById('messages');
    msgs.innerHTML = '<div class="msg assistant"><div class="bubble">Context cleared. Starting fresh.</div></div>';
    try {{
      const r = await fetch('/api/session/new');
      if (r.ok) {{ const d = await r.json(); sessionId = d.session_id; updateSessionBadge(); }}
    }} catch(e) {{}}
  }}
  try {{
    const r = await fetch('/api/context/clear');
    if (r.ok) {{
      const tb = document.getElementById('tblBody');
      if (tb) tb.innerHTML = '<tr><td colspan="6" class="empty">Cache cleared — send a message to see new results</td></tr>';
      if (document.getElementById('cardCache')) document.getElementById('cardCache').textContent = '0';
    }}
  }} catch(e) {{}}
}}

async function attachFile(input) {{
  const file = input.files[0];
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) {{ alert('File too large (max 10MB): '+file.name); input.value = ''; return; }}
  const ext = '.' + file.name.split('.').pop().toLowerCase();
  const allowed = {{'.md':1,'.txt':1,'.py':1,'.js':1,'.ts':1,'.html':1,'.css':1,'.csv':1,'.json':1,'.xml':1,'.yaml':1,'.yml':1,'.go':1,'.rs':1,'.rb':1,'.java':1,'.c':1,'.cpp':1,'.h':1,'.sh':1,'.sql':1,'.log':1,'.pdf':1,'.docx':1,'.xlsx':1}};
  if (!allowed[ext]) {{ alert('File type not supported: '+ext); input.value = ''; return; }}
  const content_b64 = await new Promise((resolve, reject) => {{
    const r = new FileReader();
    r.onload = () => resolve(r.result.split(',')[1]);
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  }});
  appendMsg('assistant', '\\uD83D\\uDCC4 Adding **'+esc(file.name)+'** to knowledge base and ingesting...', '');
  try {{
    const r = await fetch('/api/knowledge/upload', {{
      method: 'POST',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{name: file.name, content_b64: content_b64}})
    }});
    const d = await r.json();
    if (!d.ok) throw new Error(d.error||'upload failed');
    const rr = await fetch('/api/embed/reingest', {{method: 'POST'}});
    const dd = await rr.json();
    if (!dd.ok) throw new Error(dd.error||'re-ingest failed');
    appendMsg('assistant', '\\u2705 **'+esc(file.name)+'** added to knowledge base and ingested. Ask a question about it!', '');
  }} catch(e) {{
    appendMsg('assistant', '\\u274c Failed to add file: '+esc(e.message), '');
  }}
  input.value = '';
}}

function handleCommand(text) {{
  if (text === '/clear') {{
    clearConversation();
    return true;
  }}
  const lower = text.toLowerCase().trim();
  if ((lower === 'stop' || lower === "that's enough" || lower === 'stop.') && abortController) {{
    abortGeneration();
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

function abortGeneration() {{
  if (abortController) {{
    abortController.abort();
    abortController = null;
  }}
  const sendBtn = document.getElementById('sendBtn');
  if (sendBtn) {{
    sendBtn.textContent = 'Send \\u2191';
    sendBtn.onclick = function() {{ sendMessage(); }};
    sendBtn.disabled = false;
  }}
  removeTyping();
  const input = document.getElementById('chatInput');
  if (input) input.focus();
}}

function setSendStop() {{
  const sendBtn = document.getElementById('sendBtn');
  if (sendBtn) {{
    sendBtn.textContent = '\\u25a0 Stop';
    sendBtn.onclick = function() {{ abortGeneration(); }};
    sendBtn.disabled = false;
  }}
}}

function linkCitations(text) {{
  return text
    .replace(/(\\b)([\\w\\-.]+\\.(?:md|pdf|docx|xlsx|txt))(\\b)/g,
      '<a href="/knowledge/$2" target="_blank" style="color:var(--accent);text-decoration:underline">$2</a>')
    .replace(/\\[([\\w\\-.]+\\.(?:md|pdf|docx|xlsx|txt))\\]/g,
      '<a href="/knowledge/$1" target="_blank" style="color:var(--accent);text-decoration:underline">$1</a>');
}}

function appendMsg(role, text, statHtml) {{
  const box = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  const display = role === 'assistant' ? linkCitations(esc(text)) : esc(text);
  div.innerHTML =
    `<div class="bubble">${{display}}</div>` +
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
    const hits = (d.hits||[]).map(h=>`<span class="hit">${{esc(h.source.replace('.md',''))}} <em>${{h.score}}</em></span>`).join(' ') || '<span class="nh">—</span>';
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
    if (!inp) return;
    const savedModel = localStorage.getItem('contextcut_model');
    if (savedModel) {{
      if (models.includes(savedModel)) inp.value = savedModel;
      else inp.value = models[0];
      localStorage.removeItem('contextcut_model');
    }}
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
      if (r.type === 'provider_switch') {{
        var cls = r.is_cloud ? 'cloud-on' : 'cloud-off';
        return `<tr class="${{cls}}"><td class="ts">${{r.ts||''}}</td><td class="qcell" colspan="5" style="font-weight:600">${{esc(r.query||'')}}</td></tr>`;
      }}
      const p = r.pct||0;
      const c = p<60?'var(--green)':p<80?'var(--yellow)':'var(--red)';
      const hits = (r.hits||[]).map(h=>
        `<span class="hit">${{esc((h.source||'?').replace('.md',''))}} <em>${{h.score}}</em></span>`
      ).join(' ') || '<span class="nh">\u2014</span>';
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

async function pollGpu() {{
  try {{
    const r = await fetch('/api/ollama-ps');
    const d = await r.json();
    const el = document.getElementById('cardGpu');
    if (d.error || !d.models || d.models.length === 0) {{
      el.textContent = '—'; el.style.color = '';
      return;
    }}
    let lines = [];
    let totalVram = 0;
    let totalShared = 0;
    for (const m of d.models) {{
      const v = m.size_vram || 0;
      totalVram += v;
      const s = Math.max(0, (m.size || 0) - v);
      totalShared += s;
      const gb = (v / 1073741824).toFixed(1);
      lines.push(m.name + ' ' + gb + 'GB' + (s > 0 ? ' (' + (s / 1073741824).toFixed(1) + 'GB shared)' : ''));
    }}
    const vramGb = (totalVram / 1073741824).toFixed(1);
    const sharedGb = (totalShared / 1073741824).toFixed(1);
    const isOverflow = totalShared / 1073741824 > 0.7;
    if (totalShared > 0) {{
      el.textContent = vramGb + ' GB + ' + sharedGb + ' GB shared';
      if (isOverflow) {{
        el.title = '⚠ GPU VRAM exceeded — ' + sharedGb + ' GB spilling into shared/system memory.\\nModel(s) too large for available GPU memory — expect significantly slower inference.';
      }} else {{
        el.title = lines.join('\\n') + '\\n' + sharedGb + ' GB in shared memory.';
      }}
    }} else {{
      el.textContent = vramGb + ' GB';
      el.title = lines.join('\\n');
    }}
    el.style.color = isOverflow ? '#f87171' : '#22c55e';
  }} catch(_) {{}}
}}

setInterval(pollStats, 3000);
setInterval(pollLicense, 5000);
setInterval(pollGpu, 5000);
pollStats();
pollLicense();
pollGpu();
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
  abortController = new AbortController();
  let assistantDiv = null;
  let bubble = null;
  let fullText = '';
  let usage = {{}};
  let agentTimeout = setTimeout(() => {{
    abortController.abort();
  }}, 310000);
  setSendStop();
  appendMsg('user', text, '');
  conversationHistory.push({{role:'user', content:text}});
  showTyping();

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

  // ── Agent mode ──
  if (agentMode) {{
    try {{
      const resp = await fetch('/api/agent', {{
        method: 'POST',
        headers: {{'Content-Type':'application/json'}},
        signal: abortController.signal,
        body: JSON.stringify({{message: text, session_id: sessionId, model, stream: true}})
      }});
      if (!resp.ok) {{
        removeTyping();
        let errText = await resp.text();
        try {{
          const errJson = JSON.parse(errText);
          if (errJson.error && typeof errJson.error === 'object' && errJson.error.message) {{
            errText = errJson.error.message;
          }} else if (typeof errJson.error === 'string') {{
            errText = errJson.error;
          }}
        }} catch(e) {{}}
        let msg = '\u274c Agent Error: ' + errText;
        if (errText.includes('does not support tools')) {{
          msg = '\u274c Model <strong>' + model + '</strong> does not support tool calling. Agent mode requires a model with tool-use capability (e.g. qwen3, llama3, deepseek-v3). Switch to a compatible model or disable Agent ON.';
        }}
        appendMsg('assistant', msg, '');
        return;
      }}
      const reader  = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      let toolDetails = null;
      function getToolDiv() {{
        if (!toolDetails) {{
          ensureBubble();
          toolDetails = document.createElement('details');
          toolDetails.className = 'tool-call';
          toolDetails.innerHTML = '<summary>Tool Calls</summary>';
          assistantDiv.insertBefore(toolDetails, assistantDiv.querySelector('.msg-meta'));
        }}
        return toolDetails;
      }}
      while (true) {{
        const {{done, value}} = await reader.read();
        if (done) break;
        buf += decoder.decode(value, {{stream: true}});
        const lines = buf.split('\\n');
        buf = lines.pop();
        for (const line of lines) {{
          const trimmed = line.trim();
          if (!trimmed) continue;
          if (trimmed.startsWith('event: ')) {{
            const eventType = trimmed.slice(7).trim();
            continue;
          }}
          if (trimmed.startsWith('data: ')) {{
            try {{
              const data = JSON.parse(trimmed.slice(6));
              if (data.token) {{
                fullText += data.token;
                ensureBubble();
                bubble.innerHTML = linkCitations(esc(fullText));
              }} else if (data.name && data.input && !data.result) {{
                const td = getToolDiv();
                const div = document.createElement('div');
                div.className = 'tool-call-entry';
                div.innerHTML = '<span style="color:var(--yellow)">\u2699 ' + esc(data.name) + '</span>' +
                  '<div class="tool-input">' + esc(typeof data.input === 'string' ? data.input : JSON.stringify(data.input, null, 2)) + '</div>';
                if (data.name === 'shell_exec' && data.shell_mode === 'ask') {{
                  td.open = true;
                  const rightEl = document.querySelector('.right.fullscreen');
                  if (rightEl) {{
                    rightEl.classList.remove('fullscreen');
                  }}
                  div.innerHTML += '<div class="shell-btns" data-cmd="' + esc(data.input) + '">' +
                    '<button class="allow" onclick="shellConfirm(this, true)">Allow</button>' +
                    '<button class="deny" onclick="shellConfirm(this, false)">Deny</button>' +
                    '<button class="allow" onclick="shellAlways()">Always Allow</button>' +
                    '<button class="deny" onclick="shellReject()">Always Reject</button>' +
                    '</div>';
                  setTimeout(() => {{
                    const mb = document.getElementById('messages');
                    if (mb) mb.scrollTop = mb.scrollHeight;
                  }}, 50);
                }}
                td.appendChild(div);
              }} else if (data.name && data.result) {{
                const existing = assistantDiv ? assistantDiv.querySelector('.tool-call-entry:last-child') : null;
                if (existing && !existing.querySelector('.tool-result')) {{
                  const rdiv = document.createElement('div');
                  rdiv.className = 'tool-result';
                  rdiv.textContent = typeof data.result === 'string' ? data.result.substring(0,2000) : JSON.stringify(data.result).substring(0,2000);
                  existing.appendChild(rdiv);
                }}
              }} else if (data.response) {{
                fullText = data.response;
                ensureBubble();
                bubble.innerHTML = linkCitations(esc(fullText));
              }} else if (data.error) {{
                ensureBubble();
                bubble.innerHTML = '\u274c Agent error: ' + esc(data.error);
              }}
            }} catch(e) {{}}
          }}
        }}
      }}
    }} catch(e) {{
      if (e.name !== 'AbortError') {{
        removeTyping();
        appendMsg('assistant', '\u274c Agent network error: ' + e.message, '');
        input.focus();
      }}
    }} finally {{
      clearTimeout(agentTimeout);
      // Always reset the send button, regardless of how the try/catch exits
      if (fullText) {{
        conversationHistory.push({{role:'assistant', content:fullText}});
        if (scanMode && assistantDiv) {{
          try {{
            const sr = await fetch('/api/agent/confidence-scan', {{
              method: 'POST',
              headers: {{'Content-Type':'application/json'}},
              body: JSON.stringify({{text: fullText}})
            }});
            if (sr.ok) {{
              const sd = await sr.json();
              if (sd.passages && sd.passages.length > 0) {{
                let highlighted = fullText;
                for (const p of sd.passages) {{
                  if ((p.confidence === 'LOW' || p.confidence === 'MEDIUM') && p.text && p.text.length > 5) {{
                    const escaped = p.text.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&');
                    const icon = p.confidence === 'LOW' ? '\\u26a0\\ufe0f ' : '\\u26a1 ';
                    const title = esc(p.confidence + ': ' + (p.reason || ''));
                    try {{
                      const re = new RegExp(escaped.replace(/\\n/g, '\\\\n'), 'gi');
                      highlighted = highlighted.replace(re, (match) =>
                        '<span class=\\"suspect\\" title=\\"' + title + '\\">' + icon + esc(match) + '</span>'
                      );
                    }} catch(e) {{}}
                  }}
                }}
                if (bubble) bubble.innerHTML = highlighted;
              }}
            }}
          }} catch(e) {{ console.warn('Confidence scan failed:', e); }}
        }}
      }}
      sendBtn.disabled = false;
      abortController = null;
      sendBtn.textContent = 'Send \\u2191';
      sendBtn.onclick = function() {{ sendMessage(); }};
      input.focus();
    }}
    return;
  }}

  try {{
    const genParams = getGenerationParams();
    const resp = await fetch('/v1/chat/completions', {{
      method: 'POST',
      headers: {{'Content-Type':'application/json'}},
      signal: abortController.signal,
      body: JSON.stringify({{model, messages: conversationHistory, stream:true, stream_options: {{include_usage: true}}, session_id: sessionId, ...genParams}})
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
          bubble.innerHTML = linkCitations(esc(fullText));
        }} catch(e) {{}}
      }}
    }}

    const box = document.getElementById('messages');
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 100;
    if (atBottom) {{
      box.scrollTop = box.scrollHeight;
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
    if (e.name === 'AbortError') return;
    removeTyping();
    appendMsg('assistant', '\u274c Network error: ' + e.message, '');
  }} finally {{
    sendBtn.disabled = false;
    abortController = null;
    sendBtn.textContent = 'Send \\u2191';
    sendBtn.onclick = function() {{ sendMessage(); }};
    input.focus();
  }}
}}

// ── Embed Settings Modal ─────────────────────────────────────────────────────
let embedModalOpen = false;

function openEmbedSettings() {{
  if (embedModalOpen) return;
  embedModalOpen = true;
  fetch('/api/embed/config')
    .then(r => r.json())
    .then(cfg => {{
      const overlay = document.createElement('div');
      overlay.id = 'embedOverlay';
      overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.55);z-index:9999;display:flex;align-items:center;justify-content:center';
      overlay.onclick = (e) => {{ if (e.target === overlay) closeEmbedOverlay(overlay); }};

      const isVoyage = cfg.mode === 'voyage';
      const kbDir = cfg.kb_dir || '/knowledge';

      const html = '<div style="background:var(--surf);border:1px solid var(--border);border-radius:8px;padding:24px;width:420px;max-width:90vw;font-family:JetBrains Mono,monospace;font-size:12px;color:var(--text)">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">' +
          '<strong style="font-size:14px">\\u2699 Embed Model Settings</strong>' +
          '<button id="emCloseBtn" style="background:none;border:none;color:var(--muted);font-size:18px;cursor:pointer">&times;</button>' +
        '</div>' +
        '<div style="background:var(--bg);border:1px solid #dc2626;border-radius:6px;padding:12px;margin-bottom:16px">' +
          '<div style="color:#ef4444;font-weight:700;font-size:13px;margin-bottom:4px">\\u26a0 DANGER ZONE</div>' +
          '<div style="color:#fca5a5;font-size:11px;line-height:1.5">Switching embedding models will <b>delete all existing vectors</b> in Qdrant. Your knowledge base will be wiped and you must re-ingest all files. This action cannot be undone.</div>' +
        '</div>' +
        '<label style="display:block;margin-bottom:4px;color:var(--muted);font-size:11px">Backend</label>' +
        '<select id="emMode" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:7px 10px;font-family:inherit;font-size:12px;margin-bottom:4px">' +
          '<option value="voyage" '+(isVoyage?'selected':'')+'>Voyage AI (voyage-3)</option>' +
          '<option value="ollama" '+(!isVoyage?'selected':'')+'>Ollama Local</option>' +
        '</select>' +
        '<div id="emModeDesc" style="color:var(--muted);font-size:10px;margin-bottom:14px">'+(isVoyage?'Cloud \\u2014 highest quality, requires API key':'100% local \\u2014 nomic-embed-text, mxbai-embed-large, bge-m3, qwen3-embedding')+'</div>' +
        '<div id="emVoyageFields" style="display:'+(isVoyage?'block':'none')+'">' +
          '<label style="display:block;margin-bottom:4px;color:var(--muted);font-size:11px">Voyage API Key</label>' +
           '<input id="emVoyageKey" type="password" value="'+(cfg.voyage_key||'')+'" placeholder="Paste your voyage-ai key" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:7px 10px;font-family:inherit;font-size:12px;margin-bottom:14px" />' +
        '</div>' +
        '<div id="emOllamaFields" style="display:'+(isVoyage?'none':'block')+'">' +
          '<label style="display:block;margin-bottom:4px;color:var(--muted);font-size:11px">Ollama Embedding Model</label>' +
           '<select id="emModel" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:7px 10px;font-family:inherit;font-size:12px;margin-bottom:14px">' +
            '<option value="nomic-embed-text"'+(cfg.ollama_model==='nomic-embed-text'?' selected':'')+'>nomic-embed-text (274MB, 8K ctx)</option>' +
            '<option value="mxbai-embed-large"'+(cfg.ollama_model==='mxbai-embed-large'?' selected':'')+'>mxbai-embed-large (670MB, 512 ctx)</option>' +
            '<option value="bge-m3"'+(cfg.ollama_model==='bge-m3'?' selected':'')+'>bge-m3 (1.2GB, 8K ctx, multilingual)</option>' +
            '<option value="qwen3-embedding:8b"'+(cfg.ollama_model==='qwen3-embedding:8b'?' selected':'')+'>qwen3-embedding:8b (4.9GB, best quality)</option>' +
          '</select>' +
          '<div style="color:var(--muted);font-size:10px;margin-bottom:14px">Ollama URL: '+(cfg.ollama_url||'http://localhost:11434')+'</div>' +
        '</div>' +
        '<div style="display:flex;gap:8px;justify-content:flex-end">' +
          '<button id="emCancelBtn" style="background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:4px;padding:6px 16px;font-size:11px;cursor:pointer;font-family:inherit">Cancel</button>' +
          '<button id="emSaveBtn" onclick="saveEmbedConfig()" style="background:var(--accent);color:#000;border:none;border-radius:4px;padding:6px 16px;font-size:11px;cursor:pointer;font-family:inherit;font-weight:600">Save</button>' +
        '</div>' +
        '<div id="emMsg" style="margin-top:10px;font-size:11px;min-height:16px"></div>' +
        '<label style="display:flex;align-items:flex-start;gap:8px;margin-top:12px;cursor:pointer">' +
          '<input type="checkbox" id="emDangerCheck" style="margin-top:2px;accent-color:#ef4444;width:16px;height:16px" />' +
          '<span style="color:#f87171;font-size:10px;line-height:1.4">I understand this will delete all existing embeddings and I will need to re-ingest my knowledge base.</span>' +
        '</label>' +

      '</div>';

      overlay.innerHTML = html;
      document.body.appendChild(overlay);

      document.getElementById('emCloseBtn').onclick = function() {{ closeEmbedOverlay(overlay); }};
      document.getElementById('emCancelBtn').onclick = function() {{ closeEmbedOverlay(overlay); }};

      document.getElementById('emMode').onchange = function() {{
        const v = this.value;
        document.getElementById('emVoyageFields').style.display = v==='voyage'?'block':'none';
        document.getElementById('emOllamaFields').style.display = v==='ollama'?'block':'none';
        if (v === 'voyage')
          document.getElementById('emModeDesc').textContent = 'Cloud \\u2014 highest quality, requires API key';
        else
          document.getElementById('emModeDesc').textContent = '100% local \\u2014 nomic-embed-text, mxbai-embed-large, bge-m3, qwen3-embedding';
      }};
    }})
    .catch(e => {{
      embedModalOpen = false;
      alert('Failed to load embed config: ' + e.message);
    }});
}}

function closeEmbedOverlay(el) {{
  if (el) el.remove();
  embedModalOpen = false;
}}

function saveEmbedConfig() {{
  const chk = document.getElementById('emDangerCheck');
  if (!chk || !chk.checked) {{
    const msg = document.getElementById('emMsg');
    msg.style.color = '#ef4444';
    msg.textContent = '\\u26a0 You must check the confirmation box below first.';
    return;
  }}

  const mode = document.getElementById('emMode').value;
  const data = {{ mode }};
  if (mode === 'voyage') {{
    data.voyage_key = document.getElementById('emVoyageKey').value;
  }} else {{
    data.ollama_model = document.getElementById('emModel').value;
  }}

  const btn = document.getElementById('emSaveBtn');
  const msg = document.getElementById('emMsg');
  btn.disabled = true;
  btn.textContent = 'Deleting & recreating...';
  msg.textContent = '';

  fetch('/api/embed/config', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(data)
  }})
  .then(r => r.json())
  .then(resp => {{
    if (resp.ok) {{
      msg.style.color = 'var(--green)';
      msg.textContent = '\\u2713 Embedding model changed. Knowledge base re-ingested with ' + resp.mode + '.';
      loadEmbedBadge();
      document.getElementById('emDangerCheck').checked = false;
    }} else {{
      msg.style.color = 'var(--red)';
      msg.textContent = 'Error: ' + (resp.error || 'Unknown');
    }}
  }})
  .catch(e => {{
    msg.style.color = 'var(--red)';
    msg.textContent = 'Network error: ' + e.message;
  }})
  .finally(() => {{
    btn.disabled = false;
    btn.textContent = 'Save';
  }});
}}

function reIngestKnowledgeBase() {{
  const btn = document.getElementById('emReingestBtn');
  const msg = document.getElementById('emReingestMsg');
  btn.disabled = true;
  btn.textContent = 'Ingesting...';
  msg.textContent = '';

  fetch('/api/embed/reingest', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{}})
  }})
  .then(r => r.json())
  .then(resp => {{
    if (resp.ok) {{
      btn.style.background = '#16a34a';
      btn.textContent = '\\u2713 Done!';
      msg.innerHTML = '<span style="color:var(--green)">Knowledge base re-ingested successfully.</span>';
      setTimeout(() => {{
        closeEmbedOverlay(document.getElementById('embedOverlay'));
      }}, 1500);
    }} else {{
      msg.innerHTML = '<span style="color:var(--red)">Error: ' + (resp.error || 'Unknown') + '</span>';
      btn.disabled = false;
      btn.textContent = 'Re-ingest';
    }}
  }})
  .catch(e => {{
    msg.innerHTML = '<span style="color:var(--red)">Network error: ' + e.message + '</span>';
    btn.disabled = false;
    btn.textContent = 'Re-ingest';
  }});
}}

async function openHistory() {{
  try {{
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);z-index:1000;display:flex;align-items:center;justify-content:center;font-family:JetBrains Mono,monospace;font-size:12px';
    overlay.onclick = (e) => {{ if (e.target === overlay) overlay.remove(); }};
    const panel = document.createElement('div');
    panel.style.cssText = 'background:#1E293B;border:1px solid #334155;border-radius:8px;width:560px;max-width:90vw;max-height:80vh;display:flex;flex-direction:column';
    const hdr = document.createElement('div');
    hdr.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-bottom:1px solid #334155';
    hdr.innerHTML = '<span style="font-weight:600;color:var(--text)">Session History</span><span style="color:var(--muted);font-size:10px" id="histCount"></span>';
    const closeBtn = document.createElement('button');
    closeBtn.textContent = '\\u2715';
    closeBtn.style.cssText = 'background:none;border:none;color:var(--muted);cursor:pointer;font-size:14px';
    closeBtn.onclick = () => overlay.remove();
    hdr.appendChild(closeBtn);
    panel.appendChild(hdr);
    const searchBox = document.createElement('input');
    searchBox.type = 'text';
    searchBox.placeholder = 'Search sessions...';
    searchBox.style.cssText = 'margin:8px 20px;padding:6px 10px;background:#0F172A;border:1px solid #334155;border-radius:4px;color:var(--text);font-family:inherit;font-size:11px;outline:none';
    let debounceTimer;
    searchBox.oninput = function() {{
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => loadHistory(this.value), 250);
    }};
    panel.appendChild(searchBox);
    const list = document.createElement('div');
    list.id = 'histList';
    list.style.cssText = 'overflow-y:auto;padding:8px 0;flex:1';
    panel.appendChild(list);
    overlay.appendChild(panel);
    document.body.appendChild(overlay);
    loadHistory('');
    setTimeout(() => searchBox.focus(), 100);
  }} catch(e) {{ console.error('history error:', e); }}
}}

async function loadHistory(q) {{
  const list = document.getElementById('histList');
  if (!list) return;
  try {{
    const url = q ? '/api/sessions/archive?q=' + encodeURIComponent(q) : '/api/sessions/archive';
    const r = await fetch(url);
    if (!r.ok) return;
    const sessions = await r.json();
    const countEl = document.getElementById('histCount');
    if (countEl) countEl.textContent = sessions.length + ' session(s)';
    if (!sessions.length) {{
      list.innerHTML = '<div style="padding:24px;text-align:center;color:var(--muted)">' + (q ? 'No sessions match "' + esc(q) + '".' : 'No past sessions yet.') + '</div>';
      return;
    }}
    list.innerHTML = '';
    for (const s of sessions) {{
      const item = document.createElement('div');
      const warn = s.ctx_limit_reached ? ' <span style="color:#f87171">\\u26a0</span>' : '';
      const title = esc(s.title || s.preview || '(empty session)');
      const detail = s.created + ' \\u2022 ' + s.msg_count + ' msg(s) \\u2022 ' + s.total_tokens + ' tokens';
      item.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:10px 20px;cursor:pointer;border-bottom:1px solid rgba(51,65,85,0.5)';
      item.onmouseenter = () => item.style.background = '#1a2536';
      item.onmouseleave = () => item.style.background = 'transparent';
      item.onclick = () => recallSession(s.id);
      item.innerHTML = '<div style="flex:1;min-width:0;padding-right:12px"><div style="color:var(--text);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + title + ' ' + warn + '</div><div style="color:var(--muted);font-size:10px;margin-top:3px">' + detail + '</div></div>';
      item.innerHTML += '<span style="color:var(--accent);font-size:11px;flex-shrink:0">Load \\u2192</span>';
      list.appendChild(item);
    }}
  }} catch(e) {{ console.error('loadHistory error:', e); }}
}}

async function recallSession(sid) {{
  try {{
    const r = await fetch('/api/session/recall/' + sid);
    if (!r.ok) return;
    const data = await r.json();
    if (!data.ok) return;
    const s = data.session;
    if (!s.history || !s.history.length) return;
    if (s.ctx_limit_reached && !confirm('This session reached the context limit (' + s.total_tokens + ' tokens). Continuing may produce degraded responses.\\n\\nLoad anyway?')) return;
    await fetch('/api/session/' + sessionId, {{method: 'DELETE'}});
    await fetch('/api/session/recall/' + s.id);
    sessionId = s.id;
    updateSessionBadge();
    conversationHistory = s.history.map(m => ({{role: m.role, content: m.content}}));
    const msgs = document.getElementById('messages');
    if (msgs) {{
      msgs.innerHTML = s.history.map(m => '<div class="msg ' + m.role + '"><div class="bubble">' + (m.role === 'assistant' ? linkCitations(esc(m.content)) : esc(m.content)) + '</div></div>').join('');
      msgs.querySelector('.bubble:last-of-type')?.scrollIntoView({{behavior:'instant', block:'end'}});
    }}
    document.querySelectorAll('[style*="z-index:1000"]').forEach(el => el.remove());
  }} catch(e) {{ console.error('recall error:', e); }}
}}

function loadEmbedBadge() {{
  fetch('/api/embed/config')
    .then(r => r.json())
    .then(cfg => {{
      const badge = document.getElementById('embedBadge');
      if (cfg.mode === 'voyage') {{
        badge.textContent = '\u26a1 VoyageAI';
        badge.title = 'Embedding: Voyage AI (voyage-3)';
      }} else if (cfg.mode === 'ollama') {{
        badge.textContent = 'Local ' + (cfg.ollama_model || 'ollama');
        badge.title = 'Embedding: Ollama local — ' + (cfg.ollama_model || 'not set');
      }} else {{
        badge.textContent = cfg.mode || '\u2014';
      }}
    }})
    .catch(() => {{}});
}}
loadEmbedBadge();

// ── File Browser Modal ─────────────────────────────────────────────────────────
let fbOpen = false;
function openFileBrowser() {{
  if (fbOpen) return;
  fbOpen = true;
  fetch('/api/knowledge/files')
    .then(r => r.json())
    .then(data => {{
      const overlay = document.createElement('div');
      overlay.id = 'fbOverlay';
      overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.55);z-index:9999;display:flex;align-items:center;justify-content:center';
      overlay.onclick = (e) => {{ if (e.target === overlay) closeFB(overlay); }};

      let listHtml = data.files.map(f =>
        '<div class="fb-file" data-path="'+escAttr(f.path)+'" onclick="fbOpenFile(this)" style="padding:6px 10px;cursor:pointer;border-radius:4px;display:flex;justify-content:space-between">' +
          '<span>'+esc(f.name)+'</span>' +
          '<span style="color:var(--muted);font-size:10px">'+(f.size||0)+'B</span>' +
        '</div>'
      ).join('') || '<div style="color:var(--muted);padding:20px;text-align:center">No .md files found</div>';

      const kbd = data.kb_dir || '~/contextcut/knowledge';
      overlay.innerHTML =
        '<div style="background:var(--surf);border:1px solid var(--border);border-radius:8px;width:700px;max-width:95vw;max-height:85vh;display:flex;flex-direction:column;font-family:JetBrains Mono,monospace;font-size:12px;color:var(--text)">' +
          '<div style="display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-bottom:1px solid var(--border)">' +
            '<div><strong style="font-size:14px">📂 Knowledge Files</strong><div style="font-size:10px;color:var(--muted);margin-top:2px">'+esc(kbd)+'</div></div>' +
            '<div style="display:flex;gap:8px;align-items:center">' +
              '<button onclick="document.getElementById(\\'fbFileInput\\').click()" style="background:none;border:none;font-size:15px;cursor:pointer;line-height:1" title="Attach file to knowledge base">📎</button>' +
              '<input type="file" id="fbFileInput" accept=".md,.txt,.py,.js,.ts,.html,.css,.csv,.json,.xml,.yaml,.yml,.go,.rs,.rb,.java,.c,.cpp,.h,.sh,.sql,.log,.pdf,.docx,.xlsx" style="display:none" onchange="fbAttachFile(this)" />' +
              '<button onclick="fbUploadFile()" style="background:var(--accent);color:#000;border:none;border-radius:4px;padding:4px 12px;font-size:11px;cursor:pointer;font-family:inherit;font-weight:600">+ New</button>' +
              '<button id="fbCloseBtn" style="background:none;border:none;color:var(--muted);font-size:18px;cursor:pointer">&times;</button>' +
            '</div>' +
          '</div>' +
          '<div style="display:flex;flex:1;min-height:0">' +
            '<div id="fbFileList" style="width:220px;min-width:180px;overflow-y:auto;border-right:1px solid var(--border);padding:6px 0">'+listHtml+'</div>' +
            '<div id="fbEditor" style="flex:1;display:flex;flex-direction:column;min-width:0">' +
              '<div id="fbEditorPlaceholder" style="flex:1;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:12px">Select a file to edit</div>' +
              '<div id="fbEditorContent" style="display:none;flex:1;flex-direction:column;min-height:0">' +
                '<div id="fbFileName" style="padding:8px 14px;font-size:11px;color:var(--accent);border-bottom:1px solid var(--border)"></div>' +
                '<textarea id="fbTextArea" style="flex:1;background:var(--bg);color:var(--text);border:none;padding:12px 14px;font-family:JetBrains Mono,monospace;font-size:12px;resize:none;outline:none" spellcheck="false"></textarea>' +
                '<div style="display:flex;gap:8px;justify-content:flex-end;padding:8px 14px;border-top:1px solid var(--border)">' +
                  '<button id="fbDeleteBtn" onclick="fbDeleteFile()" style="background:#7f1d1d;color:#fca5a5;border:1px solid #dc2626;border-radius:4px;padding:5px 14px;font-size:11px;cursor:pointer;font-family:inherit">Delete</button>' +
                  '<button id="fbSaveBtn" onclick="fbSaveFile()" style="background:var(--accent);color:#000;border:none;border-radius:4px;padding:5px 14px;font-size:11px;cursor:pointer;font-family:inherit;font-weight:600">Save</button>' +
                '</div>' +
              '</div>' +
            '</div>' +
          '</div>' +
          '<div id="fbMsg" style="padding:6px 20px;font-size:10px;min-height:16px;color:var(--muted);border-top:1px solid var(--border)"></div>' +
        '</div>';

      document.body.appendChild(overlay);
      document.getElementById('fbCloseBtn').onclick = () => closeFB(overlay);
    }});
}}

function closeFB(overlay) {{
  fbOpen = false;
  overlay.remove();
}}

function escAttr(s) {{ return (s||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}

let _fbCurrentPath = '';

function fbOpenFile(el) {{
  document.querySelectorAll('.fb-file').forEach(e => e.classList.remove('selected'));
  el.classList.add('selected');
  _fbCurrentPath = el.dataset.path;
  const name = el.querySelector('span').textContent;
  document.getElementById('fbFileName').textContent = name;
  document.getElementById('fbEditorPlaceholder').style.display = 'none';
  document.getElementById('fbEditorContent').style.display = 'flex';
  document.getElementById('fbTextArea').value = 'Loading...';
  document.getElementById('fbTextArea').disabled = true;
  document.getElementById('fbMsg').textContent = '';
  fetch('/api/knowledge/read?path='+encodeURIComponent(_fbCurrentPath))
    .then(r => r.json())
    .then(d => {{
      if (d.error) {{ document.getElementById('fbTextArea').value = 'Error: '+d.error; return; }}
      if (d.binary) {{
        document.getElementById('fbTextArea').value = '[Binary file - preview not available]';
        document.getElementById('fbTextArea').disabled = true;
        document.getElementById('fbSaveBtn').style.display = 'none';
        return;
      }}
      document.getElementById('fbTextArea').value = d.content;
      document.getElementById('fbTextArea').disabled = false;
      document.getElementById('fbTextArea').focus();
    }})
    .catch(() => {{ document.getElementById('fbTextArea').value = 'Network error'; }});
}}

function fbSaveFile() {{
  const content = document.getElementById('fbTextArea').value;
  const btn = document.getElementById('fbSaveBtn');
  btn.disabled = true;
  btn.textContent = 'Saving...';
  fetch('/api/knowledge/save', {{
    method: 'POST',
    headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify({{path: _fbCurrentPath, content: content}})
  }})
  .then(r => r.json())
  .then(d => {{
    const msg = document.getElementById('fbMsg');
    if (d.ok) {{ msg.innerHTML = '<span style="color:#4ade80">Saved</span>'; }}
    else {{ msg.innerHTML = '<span style="color:#f87171">Error: '+(d.error||'')+'</span>'; }}
    btn.disabled = false;
    btn.textContent = 'Save';
  }})
  .catch(e => {{
    document.getElementById('fbMsg').innerHTML = '<span style="color:#f87171">Network error</span>';
    btn.disabled = false;
    btn.textContent = 'Save';
  }});
}}

function fbDeleteFile() {{
  if (!confirm('Delete this file? The Qdrant vector will also be removed.')) return;
  const btn = document.getElementById('fbDeleteBtn');
  btn.disabled = true;
  btn.textContent = 'Deleting...';
  fetch('/api/knowledge/delete', {{
    method: 'POST',
    headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify({{path: _fbCurrentPath}})
  }})
  .then(r => r.json())
  .then(d => {{
    if (d.ok) {{
      closeFB(document.getElementById('fbOverlay'));
      openFileBrowser();
    }} else {{
      document.getElementById('fbMsg').innerHTML = '<span style="color:#f87171">Error: '+(d.error||'')+'</span>';
      btn.disabled = false;
      btn.textContent = 'Delete';
    }}
  }})
  .catch(e => {{
    document.getElementById('fbMsg').innerHTML = '<span style="color:#f87171">Network error</span>';
    btn.disabled = false;
    btn.textContent = 'Delete';
  }});
}}

function fbAttachFile(input) {{
  const file = input.files[0];
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) {{ alert('File too large (max 10MB): '+file.name); input.value = ''; return; }}
  const ext = '.' + file.name.split('.').pop().toLowerCase();
  const allowed = {{'.md':1,'.txt':1,'.py':1,'.js':1,'.ts':1,'.html':1,'.css':1,'.csv':1,'.json':1,'.xml':1,'.yaml':1,'.yml':1,'.go':1,'.rs':1,'.rb':1,'.java':1,'.c':1,'.cpp':1,'.h':1,'.sh':1,'.sql':1,'.log':1,'.pdf':1,'.docx':1,'.xlsx':1}};
  if (!allowed[ext]) {{ alert('File type not supported: '+ext); input.value = ''; return; }}
  document.getElementById('fbMsg').textContent = 'Uploading '+file.name+'...';
  const reader = new FileReader();
  reader.onload = function(e) {{
    const content_b64 = e.target.result.split(',')[1];
    fetch('/api/knowledge/upload', {{
      method: 'POST',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{name: file.name, content_b64: content_b64}})
    }})
    .then(r => r.json())
    .then(d => {{
      if (!d.ok) throw new Error(d.error||'upload failed');
      return fetch('/api/embed/reingest', {{method: 'POST'}});
    }})
    .then(r => r.json())
    .then(dd => {{
      if (!dd.ok) throw new Error(dd.error||'re-ingest failed');
      document.getElementById('fbMsg').innerHTML = '<span style="color:#4ade80">'+esc(file.name)+' added and ingested</span>';
      fbRefreshList();
    }})
    .catch(err => {{
      document.getElementById('fbMsg').innerHTML = '<span style="color:#f87171">Error: '+esc(err.message)+'</span>';
    }});
  }};
  reader.readAsDataURL(file);
  input.value = '';
}}

function fbRefreshList() {{
  fetch('/api/knowledge/files')
    .then(r => r.json())
    .then(data => {{
      const container = document.getElementById('fbFileList');
      if (!container) return;
      container.innerHTML = data.files.map(f =>
        '<div class="fb-file" data-path="'+escAttr(f.path)+'" onclick="fbOpenFile(this)" style="padding:6px 10px;cursor:pointer;border-radius:4px;display:flex;justify-content:space-between">' +
          '<span>'+esc(f.name)+'</span>' +
          '<span style="color:var(--muted);font-size:10px">'+(f.size||0)+'B</span>' +
        '</div>'
      ).join('') || '<div style="color:var(--muted);padding:20px;text-align:center">No .md files found</div>';
    }});
}}

function fbUploadFile() {{
  const name = prompt('New filename (e.g. notes.md, data.csv):', '');
  if (!name) return;
  const ext = '.' + name.split('.').pop().toLowerCase();
  const allowed = {{'.md':1,'.txt':1,'.py':1,'.js':1,'.ts':1,'.html':1,'.css':1,'.csv':1,'.json':1,'.xml':1,'.yaml':1,'.yml':1,'.go':1,'.rs':1,'.rb':1,'.java':1,'.c':1,'.cpp':1,'.h':1,'.sh':1,'.sql':1,'.log':1,'.pdf':1,'.docx':1,'.xlsx':1}};
  if (!allowed[ext]) {{ alert('File type not supported.'); return; }}
  if (name.includes('/') || name.includes('\\\\')) {{ alert('Invalid filename.'); return; }}
  fetch('/api/knowledge/upload', {{
    method: 'POST',
    headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify({{name: name, content: ''}})
  }})
  .then(r => r.json())
  .then(d => {{
    if (d.ok) {{
      fbRefreshList();
      const items = document.querySelectorAll('.fb-file');
      for (let i = 0; i < items.length; i++) {{
        if (items[i].dataset.path === d.path) {{
          fbOpenFile(items[i]);
          break;
        }}
      }}
    }} else {{
      alert('Upload failed: '+(d.error||''));
    }}
  }})
  .catch(e => {{ alert('Network error: '+e.message); }});
}}
(function(){{
  var t=localStorage.getItem('ccTheme');
  if(!t)t=window.matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light';
  if(t==='light')document.body.classList.add('light');
  var b=document.getElementById('togBtn');
  if(b)b.textContent=t==='light'?'☽':'☀';
}})();
function togTheme(){{
  document.body.classList.toggle('light');
  var l=document.body.classList.contains('light');
  localStorage.setItem('ccTheme',l?'light':'dark');
  document.getElementById('togBtn').textContent=l?'☽':'☀';
}}
document.getElementById('togBtn').addEventListener('click',togTheme);
</script>
</body></html>"""


# ── Dashboard handler ─────────────────────────────────────────────────────────
class DashboardHandler(_SuppressBrokenPipe, BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

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
        if self.path.startswith("/api/session/recall/"):
            sid = self.path.split("/api/session/recall/")[-1]
            data = {"ok": False, "error": "Session not found"}
            with _lock:
                if sid in _sessions:
                    s = _sessions[sid]
                    total_tok = sum(count_tokens(m["content"]) for m in s["history"])
                    data = {
                        "ok": True,
                        "session": {
                            "id": sid,
                            "history": s["history"],
                            "msg_count": s["msg_count"],
                            "created": s["created"],
                            "total_tokens": total_tok,
                            "ctx_limit_reached": s.get("ctx_limit_reached", False),
                        },
                    }
                else:
                    try:
                        db = _get_db()
                        cur = db.execute(
                            "SELECT id, title, created, msg_count, total_tokens, ctx_limit_reached, preview FROM sessions WHERE id=?",
                            (sid,),
                        )
                        row = cur.fetchone()
                        if row:
                            mcur = db.execute(
                                "SELECT role, content FROM messages WHERE session_id=? ORDER BY position",
                                (sid,),
                            )
                            history = [
                                {"role": r, "content": c} for r, c in mcur.fetchall()
                            ]
                            global _current_sid
                            _current_sid = sid
                            _sessions[sid] = {
                                "history": list(history),
                                "msg_count": row[3] or len(history),
                                "created": row[2],
                                "ctx_limit_reached": bool(row[5]),
                            }
                            data = {
                                "ok": True,
                                "session": {
                                    "id": row[0],
                                    "title": row[1],
                                    "created": row[2],
                                    "msg_count": row[3] or len(history),
                                    "total_tokens": row[4],
                                    "ctx_limit_reached": bool(row[5]),
                                    "preview": row[6],
                                    "history": history,
                                },
                            }
                        db.close()
                    except Exception as e:
                        print(f"[contextcut] Recall DB error: {e}")
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/logs/export":
            with _lock:
                rows = list(_log)
            lines = ["ts,query,tokens_before,tokens_after,pct,hits"]
            for r in rows:
                if r.get("type") == "provider_switch":
                    continue
                hits = "; ".join(
                    f"{h['source'].replace('.md', '')} ({h['score']})"
                    for h in r.get("hits", [])
                )
                q = r["query"].replace('"', '""')
                lines.append(
                    f'{r["ts"]},"{q}",{r["tokens_before"]},{r["tokens_after"]},{r["pct"]},"{hits}"'
                )
            body = "\n".join(lines).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="contextcut-audit-{datetime.now().strftime("%Y%m%d")}.csv"',
            )
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
                        if _local_only:
                            models = [
                                {"name": m["name"]}
                                for m in data.get("models", [])
                                if "cloud" not in m["name"].lower()
                            ]
                        else:
                            models = [
                                {"name": m["name"]} for m in data.get("models", [])
                            ]
                        body = json.dumps({"models": models}, ensure_ascii=True).encode(
                            "utf-8"
                        )
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
                        raw_models = data.get("data", [])
                        if _free_only:

                            def _is_free(m):
                                p = m.get("pricing", {})
                                return (
                                    p.get("prompt", "0") == "0"
                                    and p.get("completion", "0") == "0"
                                )

                            models = [
                                {"name": m.get("id", str(m))}
                                for m in raw_models
                                if _is_free(m)
                            ]
                        else:
                            models = [{"name": m.get("id", str(m))} for m in raw_models]
                        models.sort(key=lambda x: x["name"])
                        body = json.dumps({"models": models}, ensure_ascii=True).encode(
                            "utf-8"
                        )

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                safe_msg = (
                    str(e)[:100].encode("ascii", errors="replace").decode("ascii")
                )
                err_body = json.dumps(
                    {"models": [], "error": safe_msg}, ensure_ascii=True
                ).encode("utf-8")
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
                sessions = {
                    sid: {"msg_count": s["msg_count"], "created": s["created"]}
                    for sid, s in _sessions.items()
                }
            body = json.dumps({"sessions": sessions}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/sessions/archive" or self.path.startswith(
            "/api/sessions/archive?"
        ):
            from urllib.parse import urlparse, parse_qs

            q = (
                (parse_qs(urlparse(self.path).query).get("q") or [""])[0]
                .strip()
                .lower()
            )
            archive = []
            try:
                db = _get_db()
                if q:
                    cur = db.execute(
                        "SELECT id, title, created, msg_count, total_tokens, ctx_limit_reached, preview FROM sessions WHERE LOWER(title) LIKE ? OR LOWER(preview) LIKE ? OR id IN (SELECT DISTINCT session_id FROM messages WHERE LOWER(content) LIKE ?) ORDER BY created DESC LIMIT 50",
                        (f"%{q}%", f"%{q}%", f"%{q}%"),
                    )
                else:
                    cur = db.execute(
                        "SELECT id, title, created, msg_count, total_tokens, ctx_limit_reached, preview FROM sessions ORDER BY created DESC LIMIT 50"
                    )
                for row in cur.fetchall():
                    archive.append(
                        {
                            "id": row[0],
                            "title": row[1] or "",
                            "created": row[2],
                            "msg_count": row[3],
                            "total_tokens": row[4],
                            "ctx_limit_reached": bool(row[5]),
                            "preview": row[6] or "",
                        }
                    )
                db.close()
            except Exception as e:
                print(f"[contextcut] Archive query error: {e}")
            body = json.dumps(archive).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/context/clear":
            global _response_cache, _stats
            with _lock:
                _response_cache.clear()
                _stats = {
                    "total_requests": 0,
                    "total_saved": 0,
                    "max_tokens_seen": 0,
                    "last_seen": None,
                    "start_time": datetime.now().isoformat(),
                    "cache_hits": 0,
                }
                _log.clear()
                _sessions.clear()
            print("[contextcut] Context cache, sessions, and monitor history cleared")
            resp = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return
        if self.path == "/api/embed/config":
            cfg = {
                "mode": _EMBED_MODE,
                "voyage_key": _VK[:8] + "..."
                if _VK and _EMBED_MODE == "voyage"
                else "",
                "ollama_model": _LOCAL_EMBED if _EMBED_MODE == "ollama" else "",
                "ollama_url": UPSTREAM,
                "kb_dir": str(KB_DIR),
            }
            body = json.dumps(cfg).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/knowledge/files":
            import glob as _glob

            all_files = sorted(
                f
                for f in KB_DIR.iterdir()
                if f.is_file() and f.suffix.lower() in ALLOWED_EXT
            )
            files = []
            for f in all_files:
                files.append(
                    {
                        "name": f.name,
                        "path": str(f),
                        "size": f.stat().st_size,
                        "modified": datetime.fromtimestamp(
                            f.stat().st_mtime
                        ).isoformat(),
                    }
                )
            body = json.dumps({"files": files, "kb_dir": str(KB_DIR)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/api/knowledge/read"):
            from urllib.parse import urlparse, parse_qs

            qs = parse_qs(urlparse(self.path).query)
            fp = qs.get("path", [None])[0]
            if not fp:
                body = json.dumps({"error": "path required"}).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            fpath = Path(fp)
            if (
                not fpath.suffix.lower() in ALLOWED_EXT
                or not fpath.resolve()
                .absolute()
                .as_posix()
                .startswith(KB_DIR.resolve().absolute().as_posix())
            ):
                body = json.dumps({"error": "Forbidden"}).encode()
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if not fpath.exists():
                body = json.dumps({"error": "Not found"}).encode()
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            BINARY_EXTS = {".pdf", ".docx", ".xlsx"}
            if fpath.suffix.lower() in BINARY_EXTS:
                body = json.dumps(
                    {"name": fpath.name, "content": None, "binary": True}
                ).encode()
            else:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                body = json.dumps({"name": fpath.name, "content": content}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
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
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/demo/seed":
            demo_queries = [
                (
                    "What are the key terms in this non-compete clause?",
                    142,
                    2870,
                    [
                        {"source": "lawyer-smb-CONTRACT.md", "score": 0.81},
                        {"source": "lawyer-smb-EMPLOYMENT.md", "score": 0.67},
                    ],
                ),
                (
                    "Summarize the discovery deadline for the Johnson case",
                    98,
                    3240,
                    [
                        {"source": "lawyer-lit-DISCOVERY.md", "score": 0.88},
                        {"source": "lawyer-lit-MOTIONS.md", "score": 0.62},
                    ],
                ),
                (
                    "What is the QBI deduction limit for 2025?",
                    72,
                    1810,
                    [
                        {"source": "cpa-smb-QBI.md", "score": 0.91},
                        {"source": "cpa-smb-SELFEMPLOYED.md", "score": 0.73},
                    ],
                ),
                (
                    "Draft a motion to compel based on these facts",
                    185,
                    4620,
                    [
                        {"source": "lawyer-lit-MOTIONS.md", "score": 0.85},
                        {"source": "lawyer-lit-DISCOVERY.md", "score": 0.71},
                        {"source": "base-DRAFTING.md", "score": 0.59},
                    ],
                ),
                (
                    "Explain the HIPAA privacy rule for patient records",
                    108,
                    2980,
                    [
                        {"source": "doctor-PATIENT.md", "score": 0.87},
                        {"source": "doctor-PRACTICE.md", "score": 0.69},
                        {"source": "base-COMPLIANCE.md", "score": 0.55},
                    ],
                ),
                (
                    "What are the earnest money requirements in Texas?",
                    64,
                    1430,
                    [
                        {"source": "realtor-CONTRACT.md", "score": 0.83},
                        {"source": "realtor-DISCLOSURE.md", "score": 0.74},
                    ],
                ),
                (
                    "Calculate the capital gains on this property sale",
                    125,
                    3950,
                    [
                        {"source": "cpa-personal-INVESTMENT.md", "score": 0.78},
                        {"source": "cpa-personal-INCOME.md", "score": 0.65},
                    ],
                ),
                (
                    "What are the zoning restrictions for mixed-use development?",
                    88,
                    2110,
                    [
                        {"source": "architect-REGULATORY.md", "score": 0.86},
                        {"source": "lawyer-re-ZONING.md", "score": 0.72},
                    ],
                ),
                (
                    "Summarize the engagement letter for the Smith consulting project",
                    112,
                    2560,
                    [
                        {"source": "consultant-ENGAGEMENT.md", "score": 0.89},
                        {"source": "consultant-DELIVERABLE.md", "score": 0.61},
                    ],
                ),
                (
                    "Draft a closing statement for the Oakwood property transfer",
                    156,
                    4780,
                    [
                        {"source": "lawyer-re-CLOSING.md", "score": 0.82},
                        {"source": "lawyer-re-PURCHASE.md", "score": 0.68},
                        {"source": "realtor-CONTRACT.md", "score": 0.56},
                    ],
                ),
                (
                    "What are the encryption requirements for client data under GDPR?",
                    95,
                    1690,
                    [
                        {"source": "tech-PRIVACY.md", "score": 0.84},
                        {"source": "base-COMPLIANCE.md", "score": 0.70},
                        {"source": "base-ETHICS.md", "score": 0.52},
                    ],
                ),
                (
                    "Review this trust distribution schedule for compliance",
                    134,
                    3170,
                    [
                        {"source": "advisor-ESTATE.md", "score": 0.90},
                        {"source": "cpa-personal-ESTATE.md", "score": 0.77},
                    ],
                ),
            ]
            now = time.time()
            with _lock:
                _log.clear()
                total_before = total_after = 0
                for i, (q, b, a, hits) in enumerate(demo_queries):
                    ts = datetime.fromtimestamp(
                        now - (len(demo_queries) - i) * 120
                    ).strftime("%H:%M:%S")
                    pct = round(a / 32768 * 100, 1)
                    _log.appendleft(
                        {
                            "ts": ts,
                            "query": q,
                            "tokens_before": b,
                            "tokens_after": a,
                            "ctx_limit": 32768,
                            "pct": pct,
                            "hits": hits,
                        }
                    )
                    total_before += b
                    total_after += a
                _stats = {
                    "total_requests": len(demo_queries),
                    "total_saved": max(0, total_before - total_after),
                    "max_tokens_seen": max(e[2] for e in demo_queries),
                    "last_seen": datetime.fromtimestamp(now).strftime("%H:%M:%S"),
                    "start_time": datetime.fromtimestamp(
                        now - len(demo_queries) * 120
                    ).isoformat(),
                    "cache_hits": 3,
                }
            body = json.dumps({"ok": True, "count": len(demo_queries)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/agent/tools":
            from agent_handler import TOOL_DESCRIPTIONS, ALL_TOOLS

            tools_list = []
            for t in ALL_TOOLS:
                tools_list.append(
                    {
                        "name": t.name,
                        "description": t.description,
                        "summary": TOOL_DESCRIPTIONS.get(t.name, ""),
                    }
                )
            body = json.dumps({"tools": tools_list}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/ollama-ps":
            upstream = get_current_upstream()
            req = urllib.request.Request(f"{upstream}/api/ps", method="GET")
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    raw = json.loads(r.read().decode("utf-8"))
                body = json.dumps(raw, indent=2).encode("utf-8")
            except Exception as e:
                body = json.dumps({"error": str(e)[:200]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/knowledge/"):
            filename = self.path.split("/knowledge/")[-1]
            fpath = (KB_DIR / filename).resolve()
            kb_resolved = KB_DIR.resolve()
            ext = fpath.suffix.lower()
            if not str(fpath).startswith(str(kb_resolved)) or ext not in ALLOWED_EXT:
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"Forbidden")
                return
            if not fpath.exists():
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return
            TEXT_EXTS = {".md",".txt",".py",".js",".ts",".html",".css",".csv",".json",".xml",".yaml",".yml",
                         ".go",".rs",".rb",".java",".c",".cpp",".h",".sh",".sql",".log"}
            if ext in TEXT_EXTS:
                raw = fpath.read_text(encoding="utf-8", errors="replace")
                escaped = raw.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                body = self._md_to_html(escaped, filename)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                data = fpath.read_bytes()
                ct = {"pdf":"application/pdf","docx":"application/vnd.openxmlformats-officedocument.wordprocessingml.document","xlsx":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}.get(ext.lstrip("."), "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Disposition", f'inline; filename="{filename}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
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
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

    def _md_to_html(self, text, filename):
        lines = text.split("\n")
        out = []
        in_code_block = False
        in_list = False

        def _inline(s):
            s = s.replace("&amp;", "\x00a").replace("&lt;", "\x00l").replace("&gt;", "\x00g")
            s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
            s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
            s = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', s)
            s = s.replace("\x00a", "&amp;").replace("\x00l", "&lt;").replace("\x00g", "&gt;")
            return s

        for line in lines:
            if line.startswith("```"):
                if in_code_block:
                    out.append("</pre>")
                    in_code_block = False
                else:
                    out.append("<pre>")
                    in_code_block = True
                continue
            if in_code_block:
                out.append(line)
                continue
            if line.startswith("### "):
                if in_list: out.append("</ul>"); in_list = False
                out.append(f"<h3>{line[4:]}</h3>")
            elif line.startswith("## "):
                if in_list: out.append("</ul>"); in_list = False
                out.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith("# "):
                if in_list: out.append("</ul>"); in_list = False
                out.append(f"<h2>{line[2:]}</h2>")
            elif line.strip() == "---":
                if in_list: out.append("</ul>"); in_list = False
                out.append("<hr>")
            elif line.strip().startswith("- "):
                if not in_list: out.append("<ul>"); in_list = True
                out.append(f"<li>{_inline(line.strip()[2:])}</li>")
            elif line.strip() == "":
                if in_list: out.append("</ul>"); in_list = False
                out.append("")
            else:
                if in_list: out.append("</ul>"); in_list = False
                out.append(f"<p>{_inline(line)}</p>")
        if in_list: out.append("</ul>")
        html_body = "\n".join(out)
        return ("<html><head><meta charset='utf-8'>"
                "<style>body{background:#0f172a;color:#e2e8f0;font-family:system-ui;padding:24px;max-width:720px;margin:0 auto;line-height:1.7}"
                "pre{background:#1e293b;padding:12px;border-radius:6px;overflow-x:auto;white-space:pre-wrap;word-wrap:break-word}"
                "code{font-size:13px;background:#1e293b;padding:2px 6px;border-radius:3px}"
                "h1{color:#0ea5e9}h2{color:#38bdf8;border-bottom:1px solid #334155;padding-bottom:4px}h3{color:#7dd3fc}"
                "a{color:#0ea5e9}ul{padding-left:20px}li{margin:4px 0}p{margin:8px 0}"
                "</style>"
                f"<title>{filename}</title></head>"
                f"<body><h1>{filename}</h1><hr>"
                f"{html_body}"
                "<hr><p style='color:#64748b;font-size:12px'><a href='/'>Back to dashboard</a></p></body></html>").encode("utf-8")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length)

        # ── Settings endpoints ──
        if self.path == "/api/settings/provider":
            try:
                body = json.loads(raw_body)
                global \
                    _provider_name, \
                    _custom_base_url, \
                    _ollama_url, \
                    _api_key, \
                    _free_only, \
                    _local_only, \
                    UPSTREAM
                _provider_name = body.get("provider", "Ollama")
                _custom_base_url = body.get("custom_url", "").strip()
                incoming_key = body.get("api_key", "").strip()
                ollama_url = body.get("ollama_url", "").strip()
                _free_only = body.get("free_only", False)
                _local_only = body.get("local_only", False)

                # If frontend sent masked value, keep server-side key
                if incoming_key and incoming_key != "••••••••••••••••":
                    _api_key = incoming_key

                if _provider_name == "Ollama" and ollama_url:
                    _ollama_url = ollama_url

                # Save securely to disk
                CredentialManager.save("provider", _provider_name)
                CredentialManager.save("custom_url", _custom_base_url)
                CredentialManager.save("ollama_url", ollama_url)
                CredentialManager.save("free_only", _free_only)
                CredentialManager.save("local_only", _local_only)
                if _api_key:
                    CredentialManager.save("api_key", _api_key)

                print(
                    f"[contextcut] Provider switched to {_provider_name} | upstream: {UPSTREAM}"
                )
                is_cloud = _provider_name != "Ollama" or not _local_only
                _log.appendleft(
                    {
                        "ts": datetime.now().strftime("%H:%M:%S"),
                        "query": f"⚠ Provider switched to {'☁ ' + _provider_name if is_cloud else '✓ Ollama (local)'}",
                        "tokens_before": "—",
                        "tokens_after": "—",
                        "pct": 0,
                        "hits": [],
                        "type": "provider_switch",
                        "is_cloud": is_cloud,
                    }
                )
                resp = json.dumps(
                    {"ok": True, "upstream": UPSTREAM, "has_key": bool(_api_key)}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return
            except Exception as e:
                err = json.dumps(
                    {"error": str(e).encode("ascii", errors="replace").decode("ascii")}
                ).encode()
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
                free_only = body.get("free_only", False)
                local_only = body.get("local_only", False)

                # If frontend sent masked value, use server-side stored key
                if not api_key or api_key == "••••••••••••••••":
                    api_key = _api_key

                if provider == "Ollama":
                    # Ollama uses /api/tags, NOT /v1/models
                    base = (
                        ollama_url
                        if ollama_url
                        else (_ollama_url or UPSTREAM or "http://localhost:11434")
                    )
                    req = urllib.request.Request(f"{base}/api/tags", method="GET")
                    with urllib.request.urlopen(req, timeout=5) as r:
                        data = json.loads(r.read().decode("utf-8"))
                        models = sorted(
                            [
                                m["name"]
                                for m in data.get("models", [])
                                if not (local_only and "cloud" in m["name"].lower())
                            ]
                        )
                elif provider == "Custom" and custom_url:
                    base = custom_url.rstrip("/")
                    req = urllib.request.Request(f"{base}/v1/models", method="GET")
                    if api_key:
                        req.add_header("Authorization", f"Bearer {api_key}")
                    req.add_header("Accept", "application/json")
                    with urllib.request.urlopen(req, timeout=15) as r:
                        raw = r.read()
                        if r.headers.get("Content-Encoding") == "gzip":
                            import gzip

                            raw = gzip.decompress(raw)
                        data = json.loads(raw.decode("utf-8"))
                        models = sorted(
                            [m.get("id", str(m)) for m in data.get("data", [])]
                        )
                else:
                    base = PROVIDERS.get(provider, {}).get("url", "")
                    url = f"{base}/v1/models"
                    req = urllib.request.Request(url, method="GET")
                    if api_key:
                        req.add_header("Authorization", f"Bearer {api_key}")
                    req.add_header("Accept", "application/json")
                    with urllib.request.urlopen(req, timeout=15) as r:
                        raw = r.read()
                        if r.headers.get("Content-Encoding") == "gzip":
                            import gzip

                            raw = gzip.decompress(raw)
                        data = json.loads(raw.decode("utf-8"))
                        if free_only:

                            def is_free(m):
                                p = m.get("pricing", {})
                                return (
                                    p.get("prompt", "0") == "0"
                                    and p.get("completion", "0") == "0"
                                )

                            models = sorted(
                                [
                                    m.get("id", str(m))
                                    for m in data.get("data", [])
                                    if is_free(m)
                                ]
                            )
                        else:
                            models = sorted(
                                [m.get("id", str(m)) for m in data.get("data", [])]
                            )

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
                resp = json.dumps(
                    {"models": [], "error": err_msg}, ensure_ascii=True
                ).encode("utf-8")
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
                resp = json.dumps(
                    {"models": [], "error": err_msg}, ensure_ascii=True
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return
            except Exception as e:
                err_msg = str(e)[:200].encode("ascii", errors="replace").decode("ascii")
                resp = json.dumps(
                    {"models": [], "error": err_msg}, ensure_ascii=True
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return

        # ── Settings endpoint: update global MIN_SCORE / TOP_K live ──
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
                if "top_k" in body:
                    global TOP_K
                    with _lock:
                        TOP_K = int(body["top_k"])
                    print(f"[contextcut] Top-K updated live: {TOP_K}")
                    resp = json.dumps({"ok": True, "top_k": TOP_K}).encode()
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

        # ── Embed model config ──
        if self.path == "/api/embed/config":
            try:
                body = json.loads(raw_body)
                global _EMBED_MODE, _VK, _LOCAL_EMBED, _VOYAGE_AVAILABLE, _voyage_mod
                proposed_mode = body.get("mode", "voyage")

                if proposed_mode == "voyage" and not _VOYAGE_AVAILABLE:
                    print(
                        "[contextcut] voyageai not installed — attempting auto-install..."
                    )
                    import subprocess

                    pip_path = str(Path(sys.executable).parent / "pip")
                    result = subprocess.run(
                        [pip_path, "install", "voyageai", "-q"],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if result.returncode == 0:
                        import importlib

                        _voyage_mod = importlib.import_module("voyageai")
                        globals()["_voyage_mod"] = _voyage_mod
                        _VOYAGE_AVAILABLE = True
                        print("[contextcut] voyageai installed successfully")
                    else:
                        raise RuntimeError(f"pip install failed: {result.stderr[:200]}")

                old_mode = _EMBED_MODE
                old_model = _LOCAL_EMBED
                _EMBED_MODE = proposed_mode
                incoming_key = body.get("voyage_key", "").strip()
                if incoming_key and incoming_key != "••••••••••••••••":
                    _VK = incoming_key
                _LOCAL_EMBED = body.get("ollama_model", "").strip()

                CredentialManager.save("embed_mode", _EMBED_MODE)
                if _VK:
                    CredentialManager.save("voyage_key", _VK)
                if _LOCAL_EMBED:
                    CredentialManager.save("embed_model", _LOCAL_EMBED)

                # Also update .env so ingest.py picks up the change on restart
                try:
                    env_path = Path(__file__).parent / ".env"
                    env_lines = {}
                    if env_path.exists():
                        for line in env_path.read_text().splitlines():
                            if "=" in line and not line.startswith("#"):
                                k, v = line.split("=", 1)
                                env_lines[k.strip()] = v.strip()
                    env_lines["CONTEXTCUT_EMBED_MODE"] = _EMBED_MODE
                    if _EMBED_MODE == "ollama":
                        env_lines["CONTEXTCUT_EMBED_MODEL"] = _LOCAL_EMBED
                    elif "CONTEXTCUT_EMBED_MODEL" in env_lines:
                        del env_lines["CONTEXTCUT_EMBED_MODEL"]
                    if _VK:
                        env_lines["VOYAGE_API_KEY"] = _VK
                    with open(env_path, "w") as f:
                        for k, v in env_lines.items():
                            f.write(f"{k}={v}\n")
                except Exception as e:
                    print(f"[contextcut] .env update warning: {e}")

                # Recreate collection whenever embed mode/model changes (different dimensions = mixed embedding spaces = broken retrieval)
                if old_mode != _EMBED_MODE or old_model != _LOCAL_EMBED:
                    try:
                        expected_dim = _get_embed_dim(_LOCAL_EMBED)
                        qclient = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
                        qclient.delete_collection(COLLECTION)
                        import time

                        time.sleep(2)
                        qclient.create_collection(
                            collection_name=COLLECTION,
                            vectors_config=VectorParams(
                                size=expected_dim, distance=Distance.COSINE
                            ),
                        )
                        print(
                            f"[contextcut] Collection recreated with dim={expected_dim}"
                        )
                        # Auto trigger re-ingest
                        print(
                            f"[contextcut] Triggering re-ingest with new embedding config..."
                        )
                        try:
                            import subprocess

                            ingest_path = Path(__file__).parent / "ingest.py"
                            if ingest_path.exists():
                                env = os.environ.copy()
                                env["CONTEXTCUT_EMBED_MODE"] = _EMBED_MODE
                                if _EMBED_MODE == "voyage" and _VK:
                                    env["VOYAGE_API_KEY"] = _VK
                                if _EMBED_MODE == "ollama" and _LOCAL_EMBED:
                                    env["CONTEXTCUT_EMBED_MODEL"] = _LOCAL_EMBED
                                env["CONTEXTCUT_QDRANT_HOST"] = QDRANT_HOST
                                env["CONTEXTCUT_QDRANT_PORT"] = str(QDRANT_PORT)
                                env["CONTEXTCUT_KB_DIR"] = str(KB_DIR)
                                env["CONTEXTCUT_COLLECTION"] = COLLECTION
                                result = subprocess.run(
                                    [sys.executable, str(ingest_path)],
                                    env=env,
                                    capture_output=True,
                                    text=True,
                                    timeout=300,
                                )
                                for line in result.stdout.strip().split("\n"):
                                    print(f"  [re-ingest] {line}")
                                if result.stderr.strip():
                                    for line in result.stderr.strip().split("\n"):
                                        print(f"  [re-ingest:err] {line}")
                            else:
                                print(
                                    f"[contextcut] ingest.py not found at {ingest_path}"
                                )
                        except subprocess.TimeoutExpired:
                            print(f"[contextcut] Re-ingest timed out after 5 minutes")
                        except Exception as e:
                            print(f"[contextcut] Re-ingest error: {e}")
                    except Exception as e:
                        print(f"[contextcut] Dimension check warning: {e}")

                print(
                    f"[contextcut] Embed mode: {_EMBED_MODE} | model: {_LOCAL_EMBED or 'voyage-3'}"
                )
                resp = json.dumps({"ok": True, "mode": _EMBED_MODE}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return
            except Exception as e:
                err = json.dumps(
                    {"error": str(e).encode("ascii", errors="replace").decode("ascii")}
                ).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
                return

        # ── Re-ingest endpoint ──
        if self.path == "/api/embed/reingest":
            try:
                import subprocess

                ingest_path = Path(__file__).parent / "ingest.py"
                if not ingest_path.exists():
                    raise FileNotFoundError(f"ingest.py not found at {ingest_path}")

                env = os.environ.copy()
                env["CONTEXTCUT_EMBED_MODE"] = _EMBED_MODE
                if _EMBED_MODE == "voyage" and _VK:
                    env["VOYAGE_API_KEY"] = _VK
                if _EMBED_MODE == "ollama" and _LOCAL_EMBED:
                    env["CONTEXTCUT_EMBED_MODEL"] = _LOCAL_EMBED
                env["CONTEXTCUT_QDRANT_HOST"] = QDRANT_HOST
                env["CONTEXTCUT_QDRANT_PORT"] = str(QDRANT_PORT)
                env["CONTEXTCUT_KB_DIR"] = str(KB_DIR)
                env["CONTEXTCUT_COLLECTION"] = COLLECTION
                env["CONTEXTCUT_UPSTREAM"] = UPSTREAM

                result = subprocess.run(
                    [sys.executable, str(ingest_path)],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                lines = (
                    result.stdout.strip().split("\n") if result.stdout.strip() else []
                )
                resp = json.dumps(
                    {"ok": True, "output": lines[-10:] if lines else ["No output"]}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return
            except subprocess.TimeoutExpired:
                err = json.dumps({"error": "Ingest timed out after 5 minutes"}).encode()
                self.send_response(504)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
                return
            except Exception as e:
                err = json.dumps(
                    {"error": str(e).encode("ascii", errors="replace").decode("ascii")}
                ).encode()
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
                return

        # ── Knowledge: save file ──
        if self.path == "/api/knowledge/save":
            try:
                body = json.loads(raw_body)
                fp = body.get("path", "")
                content = body.get("content", "")
                fpath = Path(fp)
                if (
                    not fpath.suffix.lower() in ALLOWED_EXT
                    or not fpath.resolve()
                    .absolute()
                    .as_posix()
                    .startswith(KB_DIR.resolve().absolute().as_posix())
                ):
                    resp = json.dumps({"error": "Forbidden"}).encode()
                    self.send_response(403)
                elif fpath.suffix.lower() in (".pdf", ".docx", ".xlsx"):
                    resp = json.dumps({"error": "Cannot edit binary files"}).encode()
                    self.send_response(400)
                else:
                    fpath.write_text(content, encoding="utf-8")
                    print(f"[contextcut] File saved: {fpath.name}")
                    resp = json.dumps({"ok": True}).encode()
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

        # ── Knowledge: upload new file ──
        if self.path == "/api/knowledge/upload":
            try:
                body = json.loads(raw_body)
                name = body.get("name", "").strip()
                ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext not in ALLOWED_EXT:
                    resp = json.dumps({"error": "File type not supported"}).encode()
                    self.send_response(400)
                elif "/" in name or "\\" in name:
                    resp = json.dumps({"error": "Invalid filename"}).encode()
                    self.send_response(400)
                else:
                    fpath = KB_DIR / name
                    content_b64 = body.get("content_b64", "")
                    content = body.get("content", "")
                    if content_b64:
                        import base64

                        raw_bytes = base64.b64decode(content_b64)
                        if len(raw_bytes) > 10 * 1024 * 1024:
                            resp = json.dumps(
                                {"error": "Too large (max 10MB)"}
                            ).encode()
                            self.send_response(400)
                        else:
                            fpath.write_bytes(raw_bytes)
                            print(f"[contextcut] File created: {fpath.name}")
                            resp = json.dumps({"ok": True, "path": str(fpath)}).encode()
                            self.send_response(200)
                    else:
                        if len(content) > 10 * 1024 * 1024:
                            resp = json.dumps(
                                {"error": "Too large (max 10MB)"}
                            ).encode()
                            self.send_response(400)
                        else:
                            fpath.write_text(content, encoding="utf-8")
                            print(f"[contextcut] File created: {fpath.name}")
                            resp = json.dumps({"ok": True, "path": str(fpath)}).encode()
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

        # ── Knowledge: delete file + Qdrant vector ──
        if self.path == "/api/knowledge/delete":
            try:
                body = json.loads(raw_body)
                fp = body.get("path", "")
                fpath = Path(fp)
                if (
                    not fpath.suffix.lower() in ALLOWED_EXT
                    or not fpath.resolve()
                    .absolute()
                    .as_posix()
                    .startswith(KB_DIR.resolve().absolute().as_posix())
                ):
                    resp = json.dumps({"error": "Forbidden"}).encode()
                    self.send_response(403)
                elif not fpath.exists():
                    resp = json.dumps({"error": "Not found"}).encode()
                    self.send_response(404)
                else:
                    _remove_qdrant_point(fpath)
                    fpath.unlink()
                    print(f"[contextcut] File deleted: {fpath.name}")
                    resp = json.dumps({"ok": True}).encode()
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

        # ── Agent endpoints ──
        if self.path == "/api/agent/shell-mode":
            try:
                body = json.loads(raw_body)
                sid = body.get("session_id", _current_sid)
                mode = body.get("mode", "ask")
                if mode not in ("ask", "always", "reject"):
                    raise ValueError("mode must be ask/always/reject")
                if sid and sid in _sessions:
                    _sessions[sid]["shell_confirm_mode"] = mode
                resp = json.dumps({"ok": True, "mode": mode}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                err = json.dumps({"error": str(e)}).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
            return

        if self.path == "/api/agent/confidence-scan":
            try:
                body = json.loads(raw_body)
                text = body.get("text", "")
                model_name = body.get("model", DEFAULT_MODEL or "qwen3:14b-q8_0")
                if not text.strip():
                    resp = json.dumps({"error": "text is required"}).encode()
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return
                from agent_handler import _confidence_scan

                result = _confidence_scan(
                    text,
                    model_name,
                    upstream=get_current_upstream(),
                    api_key=get_current_api_key(),
                )
                body_resp = json.dumps({"passages": result}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body_resp)))
                self.end_headers()
                self.wfile.write(body_resp)
            except Exception as e:
                err = json.dumps({"error": str(e)}).encode()
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
            return

        if self.path == "/api/agent":
            try:
                body = json.loads(raw_body)
                message = body.get("message", "")
                sid = body.get("session_id", _current_sid)
                model_name = body.get("model", DEFAULT_MODEL)
                is_stream = body.get("stream", True)

                if not sid or sid not in _sessions:
                    sid = new_session()
                if not message.strip():
                    resp = json.dumps({"error": "message is required"}).encode()
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return

                from agent_handler import (
                    build_agent,
                    build_messages_from_history,
                    _check_tool_usage,
                    _shell_is_safe,
                )
                from langchain_core.messages import HumanMessage

                add_to_history(sid, "user", message)
                session = _sessions[sid]
                chat_history = build_messages_from_history(session["history"][:-1])
                try:
                    agent = build_agent(
                        model_name,
                        upstream=get_current_upstream(),
                        api_key=get_current_api_key(),
                    )
                except Exception as e:
                    err_str = str(e)
                    if "does not support tools" in err_str:
                        msg = (
                            f"Model '{model_name}' does not support tool calling. "
                            "Agent mode requires a model with tool-use capability "
                            "(e.g. qwen3, llama3, deepseek-v3). "
                            "Switch to a compatible model or disable Agent ON."
                        )
                    else:
                        msg = f"Failed to initialize agent: {err_str}"
                    resp = json.dumps({"error": msg}).encode()
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                    return
                input_messages = chat_history + [HumanMessage(content=message)]
                shell_mode = session.get("shell_confirm_mode", "ask")

                import asyncio

                AGENT_TIMEOUT = 300

                async def _run_agent() -> str:
                    result = await asyncio.wait_for(
                        agent.with_config({"recursion_limit": 15}).ainvoke(
                            {"messages": input_messages}
                        ),
                        timeout=AGENT_TIMEOUT,
                    )
                    final_msgs = result.get("messages", [])
                    return final_msgs[-1].content if final_msgs else ""

                class _AgentAbort(Exception):
                    pass

                async def _run_agent_stream(write):
                    called_tools = set()
                    full_output = ""

                    def emit(data):
                        try:
                            write(data)
                            import sys; sys.stdout.flush()
                        except Exception:
                            raise _AgentAbort()

                    async def _invoke_and_stream(msgs, is_retry=False):
                        nonlocal full_output
                        local_tools = set()
                        try:
                            stream_agent = agent.with_config(
                                {"recursion_limit": 15}
                            )
                            async with asyncio.timeout(AGENT_TIMEOUT):
                                    async for event in stream_agent.astream_events(
                                        {"messages": msgs},
                                        version="v2",
                                    ):
                                        kind = event.get("event", "")
                                        if kind == "on_chat_model_stream":
                                            chunk = event.get("data", {}).get("chunk", None)
                                            if (
                                                chunk
                                                and hasattr(chunk, "content")
                                                and chunk.content
                                            ):
                                                text = chunk.content
                                                if isinstance(text, str) and text:
                                                    emit({'token': text})
                                        elif kind == "on_tool_start":
                                            tool_name = event.get("name", "unknown")
                                            local_tools.add(tool_name)
                                            tool_input = event.get("data", {}).get("input", {})
                                            if isinstance(tool_input, dict):
                                                cmd = tool_input.get(
                                                    "command",
                                                    tool_input.get(
                                                        "path", json.dumps(tool_input)
                                                    ),
                                                )
                                            else:
                                                cmd = str(tool_input)[:200]
                                            import sys
                                            print(f"[{datetime.now().strftime('%H:%M:%S')}] [Agent] \U0001f9e0 {tool_name}({cmd[:120]})", flush=True)
                                            if tool_name == "shell_exec" and not _shell_is_safe(cmd):
                                                emit({'name': tool_name, 'input': cmd, 'shell_mode': shell_mode})
                                                emit({'name': tool_name, 'result': 'Blocked by safety policy (dangerous pattern).', 'type': 'tool_result'})
                                            else:
                                                emit({'name': tool_name, 'input': cmd, 'shell_mode': shell_mode})
                                                if (
                                                    tool_name == "shell_exec"
                                                    and shell_mode == "reject"
                                                ):
                                                    emit({'name': tool_name, 'result': 'Rejected by policy.', 'type': 'tool_result'})
                                        elif kind == "on_tool_end":
                                            tool_name = event.get("name", "unknown")
                                            output_data = event.get("data", {}).get(
                                                "output", ""
                                            )
                                            output_str = (
                                                str(output_data)[:2000] if output_data else ""
                                            )
                                            import sys
                                            print(f"[{datetime.now().strftime('%H:%M:%S')}] [Agent] \u2705 {tool_name} -> {output_str[:80]}", flush=True)
                                            emit({'name': tool_name, 'result': output_str, 'type': 'tool_result'})
                            result = await asyncio.wait_for(
                                stream_agent.ainvoke({"messages": msgs}),
                                timeout=AGENT_TIMEOUT,
                            )
                            final_msgs = result.get("messages", [])
                            full_output = final_msgs[-1].content if final_msgs else ""
                        except _AgentAbort:
                            raise
                        except asyncio.TimeoutError:
                            emit({'error': f'Agent timed out ({AGENT_TIMEOUT}s). Try simplifying the prompt.'})
                            import sys
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] [Agent] \u23f0 Timeout", flush=True)
                            raise _AgentAbort()
                        except Exception as e:
                            err_msg = f"Agent error: {e}"
                            emit({'error': err_msg})
                            full_output = err_msg
                            import sys
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] [Agent] \u274c {err_msg[:200]}", flush=True)
                            raise _AgentAbort()
                        return local_tools

                    # First pass: stream + track tools
                    try:
                        called_tools = await _invoke_and_stream(input_messages)
                    except _AgentAbort:
                        return full_output

                    # Layer 1: Check tool usage and re-run if needed
                    try:
                        blocked, reason = _check_tool_usage(message, called_tools)
                        max_retries = 2
                        retry_count = 0
                        while blocked and retry_count < max_retries:
                            emit({'blocked': True, 'reason': reason, 'type': 'enforcer'})
                            retry_msgs = input_messages + [
                                HumanMessage(content=f"IMPORTANT: {reason}")
                            ]
                            retry_tools = await _invoke_and_stream(retry_msgs)
                            blocked, reason = _check_tool_usage(message, retry_tools)
                            retry_count += 1
                    except _AgentAbort:
                        return full_output

                    # Layer 2: Self-correction loop
                    if full_output:
                        try:
                            from agent_handler import _confidence_scan
                            loop = asyncio.get_event_loop()
                            scan_result = await loop.run_in_executor(
                                None,
                                lambda: _confidence_scan(
                                    full_output,
                                    model_name,
                                    upstream=get_current_upstream(),
                                    api_key=get_current_api_key(),
                                ),
                            )
                            low_passages = [
                                p for p in scan_result
                                if p.get("confidence") == "LOW"
                            ]
                            correction_retries = 0
                            max_corrections = 2
                            while low_passages and correction_retries < max_corrections:
                                reasons = "; ".join(
                                    p.get("reason", "") for p in low_passages
                                )
                                emit({'confidence': 'LOW', 'reasons': reasons, 'type': 'correction'})
                                correction_msg = (
                                    f"Your previous response contained passages with LOW factual confidence. "
                                    f"Reasons: {reasons}. "
                                    f"Please correct these issues in your response."
                                )
                                retry_msgs = input_messages + [
                                    AIMessage(content=full_output),
                                    HumanMessage(content=correction_msg),
                                ]
                                await _invoke_and_stream(retry_msgs)
                                correction_retries += 1
                                if full_output:
                                    scan_result = await loop.run_in_executor(
                                        None,
                                        lambda: _confidence_scan(
                                            full_output,
                                            model_name,
                                            upstream=get_current_upstream(),
                                            api_key=get_current_api_key(),
                                        ),
                                    )
                                    low_passages = [
                                        p for p in scan_result
                                        if p.get("confidence") == "LOW"
                                    ]
                        except _AgentAbort:
                            return full_output
                        except ImportError:
                            pass
                        except Exception as scan_e:
                            emit({'error': str(scan_e), 'type': 'correction'})

                    import sys
                    tok_count = len(full_output.split())
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] [Agent] \U0001f3af Done ({tok_count} words, {len(called_tools)} tools)", flush=True)
                    try:
                        emit({'response': full_output, 'type': 'done'})
                    except _AgentAbort:
                        pass
                    return full_output

                import sys
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [Agent] 🤖 Agent session started for model '{model_name}'", flush=True)
                if not is_stream:
                    output = asyncio.run(_run_agent())
                    add_to_history(sid, "assistant", output)
                    tok = count_tokens(message) + count_tokens(output)
                    record(
                        {
                            "ts": datetime.now().strftime("%H:%M:%S"),
                            "query": message[:120],
                            "tokens_before": count_tokens(message),
                            "tokens_after": tok,
                            "ctx_limit": CTX_LIMIT,
                            "pct": round(tok / CTX_LIMIT * 100, 1),
                            "hits": [],
                            "type": "agent",
                        }
                    )
                    resp = json.dumps({"response": output}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(resp)))
                    self.end_headers()
                    self.wfile.write(resp)
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()

                    full_output = asyncio.run(_run_agent_stream(
                        lambda data: self.wfile.write(f"event: {data.pop('type', 'message')}\ndata: {json.dumps(data)}\n\n".encode()) or self.wfile.flush()
                    ))

                    try:
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                    except BrokenPipeError:
                        pass

                    add_to_history(sid, "assistant", full_output)
                    tok = count_tokens(message) + count_tokens(full_output)
                    record(
                        {
                            "ts": datetime.now().strftime("%H:%M:%S"),
                            "query": message[:120],
                            "tokens_before": count_tokens(message),
                            "tokens_after": tok,
                            "ctx_limit": CTX_LIMIT,
                            "pct": round(tok / CTX_LIMIT * 100, 1),
                            "hits": [],
                            "type": "agent",
                        }
                    )
                return
            except Exception as e:
                import traceback

                traceback.print_exc()
                err = json.dumps({"error": str(e)}).encode()
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
                return

        try:
            parsed_body = json.loads(raw_body)
        except Exception:
            parsed_body = None
        safe_prefixes = (
            "/v1/chat/completions",
            "/api/chat",
            "/api/generate",
            "/v1/completions",
        )
        if not self.path.startswith(safe_prefixes):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"Not found"}')
            return
        is_streaming = isinstance(parsed_body, dict) and parsed_body.get(
            "stream", False
        )
        req = urllib.request.Request(
            f"http://127.0.0.1:{LISTEN_PORT}{self.path}", data=raw_body, method="POST"
        )
        for k, v in self.headers.items():
            if k.lower() not in ("host",):
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding", "content-length"):
                        self.send_header(k, v)
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
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    load_saved_credentials()

    # Sync .env first so ingest.py reads correct settings
    _sync_env_on_startup()

    if _EMBED_MODE == "voyage" and _VK and _VOYAGE_AVAILABLE:
        print(f"[contextcut] Embedding: Voyage AI (voyage-3)")
    elif _EMBED_MODE == "ollama" and _LOCAL_EMBED:
        print(f"[contextcut] Embedding: Ollama local ({_LOCAL_EMBED})")
    elif _VK and _VOYAGE_AVAILABLE:
        _EMBED_MODE = "voyage"
        print(f"[contextcut] Embedding: Voyage AI (voyage-3)")
    elif _LOCAL_EMBED:
        _EMBED_MODE = "ollama"
        print(f"[contextcut] Embedding: Ollama local ({_LOCAL_EMBED})")
    else:
        print("[contextcut] ERROR: No embedding backend configured")
        raise SystemExit(1)

    ensure_collection_dim()

    _init_db()
    _migrate_json_to_sqlite()
    load_sessions()

    if LICENSE_KEY:
        print("[contextcut] Validating license key...")
        if not validate_license():
            msg = _license_state["message"]
            print(f"ERROR: {msg}")
            if "limit reached" in msg.lower() or "seats" in msg.lower():
                try:
                    if sys.stdin.isatty():
                        answer = (
                            input("\n  Release all license seats and retry? [y/N]: ")
                            .strip()
                            .lower()
                        )
                        should_release = answer in ("y", "yes")
                    else:
                        print(
                            "[contextcut] Non-interactive mode — auto-releasing stale seats..."
                        )
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
                            print(
                                f"[contextcut] License: {_license_state.get('license_type', '?')} | {_license_state['message']}"
                            )
                            threading.Thread(target=heartbeat_loop, daemon=True).start()
                            print(
                                f"[contextcut] Heartbeat: every {HEARTBEAT_INTERVAL}s | grace: {GRACE_PERIOD}s"
                            )
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
            print(
                f"[contextcut] License: {_license_state.get('license_type', '?')} | {_license_state['message']}"
            )
            threading.Thread(target=heartbeat_loop, daemon=True).start()
            print(
                f"[contextcut] Heartbeat: every {HEARTBEAT_INTERVAL}s | grace: {GRACE_PERIOD}s"
            )
    else:
        print("[contextcut] WARNING: No license key set. Set CONTEXTCUT_LICENSE_KEY.")

    # Write ready marker so start.sh knows we're initialized
    _READY_FILE = Path(__file__).parent / ".proxy_ready"
    _READY_FILE.write_text("ready\n")

    dash = ReusableHTTPServer(("0.0.0.0", DASHBOARD_PORT), DashboardHandler)
    threading.Thread(target=dash.serve_forever, daemon=True).start()

    print(
        f"[contextcut] Dashboard  → http://localhost:{DASHBOARD_PORT}  (Chat + Monitor tabs)"
    )
    print(f"[contextcut] Proxy      → http://127.0.0.1:{LISTEN_PORT} → {UPSTREAM}")
    print(f"[contextcut] Qdrant     → {QDRANT_HOST}:{QDRANT_PORT} / {COLLECTION}")
    print(f"[contextcut] Min score  → {MIN_SCORE}  Top-K → {TOP_K}  CTX → {CTX_LIMIT}")
    print(f"[contextcut] Tokens     → {TOKEN_METHOD}")
    print(
        f"[contextcut] Params     → temp={DEFAULT_TEMP} top_p={DEFAULT_TOP_P} max_tokens={DEFAULT_MAX_TK}"
    )
    if DEFAULT_MODEL:
        print(f"[contextcut] Model      → {DEFAULT_MODEL}")

    ReusableHTTPServer(("0.0.0.0", LISTEN_PORT), ProxyHandler).serve_forever()
