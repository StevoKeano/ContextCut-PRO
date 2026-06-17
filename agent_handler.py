"""
agent_handler.py — LangChain agent for ContextCut-PRO.

Uses the new `create_agent` API from LangChain 1.3+ (langgraph-based).
All tools call ContextCut-PRO internals directly.
"""

import os
import re
import json
import hashlib
import subprocess
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain.tools import tool
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from qdrant_proxy_final import qdrant_context

# ── Blocked shell patterns ────────────────────────────────────────────────────
BLOCKED_PREFIXES = [
    "rm -rf /",
    "rm -rf ~",
    "mkfs",
    ":(){:|:&};:",
    "dd if=/dev/zero",
    "shutdown",
    "reboot",
    "halt",
    "sudo",
    "apt ",
    "apt-get ",
    "dpkg ",
]


def _shell_is_safe(cmd: str) -> bool:
    lower = cmd.strip().lower()
    return not any(lower.startswith(b) for b in BLOCKED_PREFIXES)


MAX_READ_BYTES = int(os.environ.get("AGENT_MAX_READ_BYTES", str(64 * 1024)))
SHELL_TIMEOUT = int(os.environ.get("AGENT_SHELL_TIMEOUT", "30"))


def _run_subprocess(args, timeout=None, **kwargs):
    """subprocess.run with thread-safe timeout (avoids signal.SIGALRM in threads)."""
    proc = subprocess.Popen(args, **kwargs)
    timer = None
    if timeout:

        def _kill():
            try:
                proc.kill()
            except Exception:
                pass

        timer = threading.Timer(timeout, _kill)
        timer.daemon = True
        timer.start()
    try:
        stdout, stderr = proc.communicate()
        return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
    finally:
        if timer:
            timer.cancel()


# ── Layer 1: Tool-usage enforcer ──────────────────────────────────────────────

_TOOL_KEYWORDS = {
    "shell_exec": [
        "execute command",
        "terminal",
        "bash",
        "shell command",
        "system command",
        "install",
        "compile",
        "build",
        "make",
        "git ",
        "npm ",
        "pip ",
        "apt ",
        "docker",
        "background process",
        "nohup",
    ],
    "read_file": [
        "read file",
        "show file",
        "open file",
        "cat ",
        "view file",
        "file content",
        "contents of",
        "what's in",
    ],
    "write_file": ["write file", "save file", "create file", "write to"],
    "web_search": [
        "search",
        "look up",
        "google",
        "duckduckgo",
        "what is",
        "who is",
        "find online",
        "latest news",
        "tell me about",
        "find information",
        "research",
    ],
    "fetch_url": [
        "fetch",
        "url",
        "http",
        "https://",
        "website",
        "web page",
        "download",
    ],
    "vector_search": [
        "search knowledge",
        "rag",
        "contextcut",
        "vector",
        "knowledge base",
        "query kb",
        "what do you know about",
    ],
    "get_context_logs": [
        "context log",
        "session log",
        "chat history",
        "conversation history",
        "what did we talk about",
        "get log",
        "show history",
    ],
    "get_session_stats": [
        "session stats",
        "token usage",
        "context usage",
        "how many tokens",
        "session info",
    ],
    "ingest_file": [
        "ingest",
        "re-ingest",
        "reingest",
        "add to knowledge",
        "embed file",
    ],
    "list_knowledge": [
        "list knowledge",
        "knowledge base",
        "what's ingested",
        "show knowledge",
        "ingested files",
        "qdrant files",
        "knowledge files",
    ],
    "delete_knowledge": [
        "delete knowledge",
        "remove from qdrant",
        "remove vector",
        "delete file from knowledge",
    ],
    "run_python": [
        "run python",
        "execute python",
        "python code",
        "run script",
        "calculate",
    ],
    "run_sql": [
        "run sql",
        "query database",
        "select from",
        "sql query",
    ],
    "plan": [
        "plan",
        "multi-step",
        "complex task",
        "step by step",
        "break down",
        "outline steps",
    ],
    "remember": [
        "remember",
        "store",
        "save fact",
        "keep this",
        "don't forget",
        "save my",
        "persist",
    ],
    "recall": [
        "recall",
        "remember what",
        "what do you know about me",
        "what did i tell you",
        "load memory",
        "persistent memory",
    ],
    "forget": [
        "forget",
        "delete memory",
        "remove memory",
        "erase",
    ],
    "compose_tool": [
        "compose",
        "create tool",
        "new compound",
        "chain tools",
        "custom tool",
    ],
    "system_info": [
        "system",
        "resource",
        "cpu",
        "gpu",
        "ram",
        "memory",
        "disk",
        "nvidia",
        "hardware",
        "specs",
        "specification",
    ],
    "list_dir": [
        "list dir",
        "list files",
        "directory",
        "ls ",
        "what files",
        "show folder",
        "browse",
    ],
    "diff_files": ["diff", "compare file", "difference between"],
}


def _check_tool_usage(user_message: str, called_tools: set) -> tuple[bool, str]:
    lower_msg = user_message.lower()
    needed_tools = set()
    for tool_name, keywords in _TOOL_KEYWORDS.items():
        for kw in keywords:
            if kw in lower_msg:
                needed_tools.add(tool_name)
                break
    if needed_tools and not (needed_tools & called_tools):
        names = ", ".join(sorted(needed_tools))
        return (
            True,
            f"You must call a tool before answering. Your question requires real-time data that one of these tools provides: {names}. Try again with an explicit tool call.",
        )
    return False, ""


# ── Layer 2: Confidence scan ──────────────────────────────────────────────────

# Independent scan model — MUST differ from the agent model to avoid self-evaluation.
# Set CONTEXTCUT_SCAN_MODEL to a separate model (e.g. a smaller/cheaper one).
# If unset, the confidence scan is disabled.
_SCAN_MODEL = os.environ.get("CONTEXTCUT_SCAN_MODEL", "").strip()


def _confidence_scan(
    text: str, upstream: str = None, api_key: str = None
) -> list[dict] | None:
    model = _SCAN_MODEL or os.environ.get("CONTEXTCUT_SCAN_MODEL", "").strip()
    if not model:
        return None
    if not upstream or not text or len(text) < 80:
        return None
    llm = ChatOpenAI(
        model=model,
        openai_api_base=upstream + "/v1",
        openai_api_key=api_key or "not-needed",
        temperature=0.0,
    )
    prompt = f"""Does the following text contain any factual errors or hallucinations? Reply with ONLY a JSON array. Each object must have exactly "confidence" (HIGH, MEDIUM, or LOW) and "reason".

Examples:
Input: "Paris is in France."
Output: [{{"confidence": "HIGH", "reason": "Paris is the capital of France"}}]

Input: "Paris is in Germany."
Output: [{{"confidence": "LOW", "reason": "Paris is in France, not Germany"}}]

Text: {text}"""
    try:
        resp = llm.invoke([HumanMessage(content=prompt)])
        content = resp.content.strip()
        idx = content.find("[")
        if idx >= 0:
            content = content[idx:]
        end = content.rfind("]")
        if end >= 0:
            content = content[: end + 1]
        content = content.strip()
        results = json.loads(content)
        return results if isinstance(results, list) else []
    except Exception as e:
        return [{"text": text, "confidence": "HIGH", "reason": f"Scan error: {e}"}]


# ── Tool definitions ──────────────────────────────────────────────────────────


@tool
def shell_exec(command: str) -> str:
    """
    Execute a bash shell command and return stdout + stderr.
    ONLY for system operations: git, apt, compilation, background processes, ffmpeg, docker.
    Do NOT use for Python scripts (use run_python), file reads (use read_file),
    file writes (use write_file), or system info (use system_info).
    Dangerous patterns (rm -rf /, mkfs, etc.) are blocked outright.
    The caller must check shell_confirm_mode before executing.
    """
    if not _shell_is_safe(command):
        return f"BLOCKED: command matched a dangerous pattern: {command!r}"
    try:
        result = _run_subprocess(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=SHELL_TIMEOUT,
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        parts = []
        if out:
            parts.append(out)
        if err:
            parts.append(f"[stderr]\n{err}")
        return "\n".join(parts) if parts else "(no output)"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {SHELL_TIMEOUT}s"
    except Exception as e:
        return f"shell_exec error: {e}"


@tool
def read_file(path: str) -> str:
    """
    Read a local file and return its contents as a string.
    Truncates at AGENT_MAX_READ_BYTES (default 64 KB).
    Supports text files; binary files return a hex summary.
    """
    p = Path(path).expanduser()
    if not p.exists():
        return f"File not found: {path}"
    if not p.is_file():
        return f"Not a file: {path}"
    try:
        raw = p.read_bytes()
        truncated = len(raw) > MAX_READ_BYTES
        chunk = raw[:MAX_READ_BYTES]
        try:
            text = chunk.decode("utf-8")
        except UnicodeDecodeError:
            return f"[Binary file — first 256 bytes hex]\n{chunk[:256].hex()}"
        suffix = f"\n\n… [truncated at {MAX_READ_BYTES} bytes]" if truncated else ""
        return text + suffix
    except Exception as e:
        return f"read_file error: {e}"


@tool
def write_file(path: str, content: str, backup: bool = True) -> str:
    """
    Write content to a local file, creating parent directories as needed.
    If backup=True (default) and the file already exists, a timestamped
    .bak copy is made first.
    Returns confirmation with byte count.
    """
    p = Path(path).expanduser()
    try:
        if backup and p.exists():
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            bak = p.with_suffix(p.suffix + f".bak-{ts}")
            shutil.copy2(p, bak)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Wrote {len(content.encode())} bytes to {path}"
    except Exception as e:
        return f"write_file error: {e}"


@tool
def append_file(path: str, content: str) -> str:
    """
    Append content to a local file.
    Creates the file and parent directories if they don't exist.
    """
    p = Path(path).expanduser()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(content)
        return f"Appended {len(content.encode())} bytes to {path}"
    except Exception as e:
        return f"append_file error: {e}"


@tool
def diff_files(path_a: str, path_b: str) -> str:
    """
    Return a unified diff between two local files.
    """
    try:
        result = _run_subprocess(
            ["diff", "-u", path_a, path_b],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout if result.stdout else "(files are identical)"
    except Exception as e:
        return f"diff_files error: {e}"


@tool
def list_dir(path: str = ".", max_depth: int = 3) -> str:
    """
    List files and directories up to max_depth levels deep.
    Shows file sizes in human-readable form.
    """
    p = Path(path).expanduser()
    if not p.exists():
        return f"Path not found: {path}"
    lines = []

    def _walk(current: Path, depth: int, prefix: str = ""):
        if depth > max_depth:
            return
        try:
            entries = sorted(current.iterdir(), key=lambda x: (x.is_file(), x.name))
        except PermissionError:
            lines.append(f"{prefix}[permission denied]")
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                lines.append(f"{prefix}{entry.name}/")
                _walk(entry, depth + 1, prefix + "  ")
            else:
                size = entry.stat().st_size
                if size < 1024:
                    sz = f"{size}B"
                elif size < 1024**2:
                    sz = f"{size / 1024:.1f}KB"
                else:
                    sz = f"{size / 1024**2:.1f}MB"
                lines.append(f"{prefix}{entry.name} ({sz})")

    lines.append(f"{p.resolve()}")
    _walk(p, 1)
    return "\n".join(lines)


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """
    Search the web using DuckDuckGo and return titles + snippets + URLs.
    """
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(f"**{r['title']}**\n{r['href']}\n{r['body']}\n")
        return "\n---\n".join(results) if results else "No results found."
    except Exception as e:
        return f"web_search error: {e}"


@tool
def fetch_url(url: str, timeout: int = 15) -> str:
    """
    Fetch a URL and return the page body as plain text (strips HTML tags).
    Truncates at 8 KB.
    """
    try:
        import requests

        resp = requests.get(
            url, timeout=timeout, headers={"User-Agent": "deep-agent/1.0"}
        )
        resp.raise_for_status()
        ct = resp.headers.get("content-type", "")
        if "html" in ct:
            text = re.sub(r"<[^>]+>", " ", resp.text)
            text = re.sub(r"\s{2,}", " ", text).strip()
        else:
            text = resp.text.strip()
        if len(text) > 8192:
            text = text[:8192] + "\n… [truncated]"
        return text
    except Exception as e:
        return f"fetch_url error: {e}"


@tool
def vector_search(query: str, top_k: int = 5) -> str:
    """
    Search the ContextCut-PRO Qdrant vector store for relevant context.
    Uses the proxy's own embedding pipeline.
    """
    try:
        context_str, meta = qdrant_context(query)
        if not context_str:
            return "No relevant context found in vector store."
        hits = "\n".join(
            f"[{i + 1}] score={m['score']:.3f} source={m['source']}"
            for i, m in enumerate(meta)
        )
        return f"Context results:\n{hits}\n\n---\n\n{context_str}"
    except Exception as e:
        return f"vector_search error: {e}"


@tool
def system_info(component: str = "all") -> str:
    """
    Return a system snapshot.
    component: 'all' | 'cpu' | 'ram' | 'gpu' | 'disk'
    Requires: psutil, nvidia-smi for GPU.
    """
    parts = {}
    try:
        import psutil

        if component in ("all", "cpu"):
            parts["cpu"] = {
                "percent": psutil.cpu_percent(interval=0.5),
                "cores_physical": psutil.cpu_count(logical=False),
                "cores_logical": psutil.cpu_count(logical=True),
                "freq_mhz": round(psutil.cpu_freq().current)
                if psutil.cpu_freq()
                else "n/a",
            }
        if component in ("all", "ram"):
            vm = psutil.virtual_memory()
            parts["ram"] = {
                "total_gb": round(vm.total / 1024**3, 1),
                "used_gb": round(vm.used / 1024**3, 1),
                "percent": vm.percent,
            }
        if component in ("all", "disk"):
            du = psutil.disk_usage("/")
            parts["disk"] = {
                "total_gb": round(du.total / 1024**3, 1),
                "used_gb": round(du.used / 1024**3, 1),
                "free_gb": round(du.free / 1024**3, 1),
                "percent": du.percent,
            }
    except ImportError:
        parts["psutil"] = "not installed"
    if component in ("all", "gpu"):
        try:
            r = _run_subprocess(
                [
                    "nvidia-smi",
                    "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            if r.returncode == 0:
                gpus = []
                for line in r.stdout.strip().splitlines():
                    name, temp, util, mem_used, mem_total = [
                        x.strip() for x in line.split(",")
                    ]
                    gpus.append(
                        {
                            "name": name,
                            "temp_c": temp,
                            "util_pct": util,
                            "vram_used_mb": mem_used,
                            "vram_total_mb": mem_total,
                        }
                    )
                parts["gpu"] = gpus
            else:
                parts["gpu"] = "nvidia-smi returned error (no NVIDIA GPU?)"
        except FileNotFoundError:
            parts["gpu"] = "nvidia-smi not found"
    return json.dumps(parts, indent=2)


# ── New tools ──────────────────────────────────────────────────────────────────


@tool
def get_context_logs(session_id: str = "") -> str:
    """
    Retrieve the conversation history for the current or specified session.
    Returns all messages with role labels and timestamps.
    """
    try:
        from qdrant_proxy_final import _sessions, add_to_history

        sessions = _sessions
        if session_id and session_id in sessions:
            sid = session_id
        elif sessions:
            sid = list(sessions.keys())[-1]
        else:
            return "No active sessions found."
        session = sessions.get(sid, {})
        history = session.get("history", [])
        if not history:
            return f"Session {sid} has no messages yet."
        lines = [f"Session: {sid} ({session.get('msg_count', 0)} messages)"]
        for m in history:
            role = m.get("role", "?")
            content = m.get("content", "")
            preview = content[:200] + "..." if len(content) > 200 else content
            lines.append(f"\n[{role.upper()}]\n{preview}")
        return "\n".join(lines)
    except Exception as e:
        return f"get_context_logs error: {e}"


@tool
def get_session_stats(session_id: str = "") -> str:
    """
    Return token counts, context usage %, and message count for a session.
    """
    try:
        from qdrant_proxy_final import _sessions, count_tokens, CTX_LIMIT

        sessions = _sessions
        if session_id and session_id in sessions:
            sid = session_id
        elif sessions:
            sid = list(sessions.keys())[-1]
        else:
            return "No active sessions found."
        session = sessions.get(sid, {})
        history = session.get("history", [])
        total_tok = sum(count_tokens(m["content"]) for m in history)
        pct = round(total_tok / CTX_LIMIT * 100, 1) if CTX_LIMIT > 0 else 0
        return (
            f"Session: {sid}\n"
            f"Messages: {len(history)}\n"
            f"Total tokens: {total_tok}\n"
            f"CTX limit: {CTX_LIMIT}\n"
            f"Usage: {pct}%\n"
            f"Created: {session.get('created', '?')}"
        )
    except Exception as e:
        return f"get_session_stats error: {e}"


@tool
def ingest_file(filename: str) -> str:
    """
    Ingest a knowledge file into Qdrant by filename (relative to the KB dir).
    Re-embeds a single .md / .pdf / .docx / .xlsx file.
    """
    try:
        from qdrant_proxy_final import KB_DIR, QDRANT_HOST, QDRANT_PORT, COLLECTION, _VK, _EMBED_MODE, _EMBED_MODEL, UPSTREAM
        import subprocess, sys, json
        from pathlib import Path

        fpath = (Path(KB_DIR) / filename).resolve()
        kb_resolved = Path(KB_DIR).resolve()
        if not str(fpath).startswith(str(kb_resolved)):
            return f"Access denied: file must be under KB_DIR ({KB_DIR})"
        if not fpath.exists():
            return f"File not found: {fpath}"
        ingest_path = Path(__file__).parent / "ingest.py"
        if not ingest_path.exists():
            return f"ingest.py not found at {ingest_path}"
        env = os.environ.copy()
        env["CONTEXTCUT_QDRANT_HOST"] = QDRANT_HOST
        env["CONTEXTCUT_QDRANT_PORT"] = str(QDRANT_PORT)
        env["CONTEXTCUT_COLLECTION"] = COLLECTION
        env["CONTEXTCUT_KB_DIR"] = str(KB_DIR)
        env["CONTEXTCUT_EMBED_MODE"] = _EMBED_MODE
        env["CONTEXTCUT_EMBED_MODEL"] = _EMBED_MODEL
        env["CONTEXTCUT_UPSTREAM"] = UPSTREAM
        if _VK:
            env["VOYAGE_API_KEY"] = _VK
        result = _run_subprocess(
            [sys.executable, str(ingest_path), "--file", str(fpath)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
        out = (result.stdout or "").strip()[:2000]
        err = (result.stderr or "").strip()[:500]
        if result.returncode != 0:
            return f"Ingest failed (code {result.returncode}):\n{err}\n{out}"
        return f"Ingested {filename} successfully.\n{out[:1000]}"
    except subprocess.TimeoutExpired:
        return "Ingest timed out after 120s"
    except Exception as e:
        return f"ingest_file error: {e}"


@tool
def list_knowledge() -> str:
    """
    List all files in the knowledge base with chunk counts from Qdrant.
    """
    try:
        from qdrant_proxy_final import KB_DIR, QDRANT_HOST, QDRANT_PORT, COLLECTION
        from qdrant_client import QdrantClient

        qclient = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        try:
            collection_info = qclient.get_collection(COLLECTION)
            total_points = collection_info.points_count
        except Exception:
            total_points = 0
        # Scroll all points to count chunks per source
        from qdrant_client import models
        seen = {}
        next_offset = None
        limit = 100
        while True:
            hits, next_offset = qclient.scroll(
                collection_name=COLLECTION,
                limit=limit,
                offset=next_offset,
                with_payload=["source"],
            )
            for pt in hits:
                src = pt.payload.get("source", "unknown") if pt.payload else "unknown"
                seen[src] = seen.get(src, 0) + 1
            if next_offset is None:
                break
        if not seen:
            return "Knowledge base is empty."
        lines = [f"Knowledge base: {KB_DIR} ({total_points} total vectors)"]
        for src, count in sorted(seen.items()):
            lines.append(f"  {src}: {count} chunk(s)")
        return "\n".join(lines)
    except Exception as e:
        return f"list_knowledge error: {e}"


@tool
def delete_knowledge(filename: str) -> str:
    """
    Delete a knowledge file's vectors from Qdrant by filename.
    The file itself is NOT removed from disk — only Qdrant vectors are deleted.
    To also delete the file from disk, use shell_exec rm afterward.
    """
    try:
        from qdrant_proxy_final import QDRANT_HOST, QDRANT_PORT, COLLECTION
        from qdrant_client import QdrantClient, models

        qclient = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        result = qclient.delete(
            collection_name=COLLECTION,
            points_selector=models.Filter(
                must=[
                    models.FieldCondition(
                        key="source",
                        match=models.MatchValue(value=filename),
                    )
                ]
            ),
        )
        return f"Deleted vectors for '{filename}' from Qdrant collection '{COLLECTION}'."
    except Exception as e:
        return f"delete_knowledge error: {e}"


@tool
def run_python(code: str, timeout: int = 30) -> str:
    """
    Execute Python code inline and return stdout + stderr.
    PREFERRED for: calculations, data analysis, text processing, quick scripts,
    simple web servers (use http.server), file parsing, and any Python work.
    Output is capped at 64 KB.
    WARNING: NOT for long-running processes (servers, listeners, loops).
    Use shell_exec to write a .py file and background it instead.
    """
    try:
        result = _run_subprocess(
            ["python3", "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        if len(out) > 64000:
            out = out[:64000] + "\n… [truncated at 64 KB]"
        if len(err) > 64000:
            err = err[:64000] + "\n… [truncated at 64 KB]"
        parts = []
        if out:
            parts.append(out)
        if err:
            parts.append(f"[stderr]\n{err}")
        return "\n".join(parts) if parts else "(no output)"
    except subprocess.TimeoutExpired:
        return f"Python execution timed out after {timeout}s"
    except Exception as e:
        return f"run_python error: {e}"


@tool
def run_sql(query: str) -> str:
    """
    Execute a read-only SELECT query on the ContextCut session database.
    Only SELECT statements are allowed. Returns results as JSON.
    """
    try:
        import sqlite3, json
        from pathlib import Path

        session_file = str(
            Path(__file__).parent / ".contextcut_sessions.db"
        )
        if not Path(session_file).exists():
            return f"Session database not found at {session_file}"
        qs = query.strip().upper()
        if not qs.startswith("SELECT"):
            return "Only SELECT queries are allowed."
        db = sqlite3.connect(session_file, check_same_thread=False)
        db.row_factory = sqlite3.Row
        cursor = db.execute(query)
        rows = [dict(row) for row in cursor.fetchall()]
        db.close()
        if not rows:
            return "Query returned no results."
        return json.dumps(rows, indent=2, default=str)[:16000]
    except Exception as e:
        return f"run_sql error: {e}"


@tool
def plan(objective: str, context: str = "") -> str:
    """
    Create a structured, multi-step plan to accomplish a complex objective.
    Use this for tasks that require multiple tool calls in sequence.
    The agent should execute each step in order and report progress.
    """
    steps = [
        f"1. Analyze: Understand the objective and identify key requirements.",
        f"2. Research: Gather information using tools (web_search, vector_search, fetch_url).",
        f"3. Execute: Process the information — write code, run queries, analyze data.",
        f"4. Verify: Check results for accuracy and completeness.",
        f"5. Deliver: Present the final result to the user.",
    ]
    header = f"## Plan: {objective}"
    if context:
        header += f"\n\nContext: {context[:500]}"
    return header + "\n\n" + "\n".join(steps) + "\n\nProceed step by step. Call this tool again to revise the plan as needed."


# ── Persistent Memory (key-value across sessions) ──────────────────────────────

_AGENT_MEMORY_DB: str | None = None


def _get_memory_db() -> str:
    global _AGENT_MEMORY_DB
    if _AGENT_MEMORY_DB is None:
        _AGENT_MEMORY_DB = str(Path(__file__).parent / ".contextcut_sessions.db")
    return _AGENT_MEMORY_DB


def _ensure_memory_table(db_path: str):
    import sqlite3
    db = sqlite3.connect(db_path, check_same_thread=False)
    db.execute(
        """CREATE TABLE IF NOT EXISTS agent_memory (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated TEXT NOT NULL
        )"""
    )
    db.commit()
    db.close()


@tool
def remember(key: str, value: str) -> str:
    """
    Store a fact or value in persistent memory that persists across sessions.
    Use this to remember user preferences, important facts, or context
    that should be available in future conversations.
    Key should be a short, descriptive name (e.g. 'user_name', 'project_path').
    """
    try:
        db_path = _get_memory_db()
        _ensure_memory_table(db_path)
        import sqlite3
        from datetime import datetime
        db = sqlite3.connect(db_path, check_same_thread=False)
        db.execute(
            "INSERT OR REPLACE INTO agent_memory (key, value, updated) VALUES (?, ?, ?)",
            (key, value, datetime.now().isoformat()),
        )
        db.commit()
        db.close()
        return f"Stored '{key}' in persistent memory."
    except Exception as e:
        return f"remember error: {e}"


@tool
def recall(key: str = "") -> str:
    """
    Retrieve facts from persistent memory. If key is provided, returns that
    specific value. If key is empty, returns ALL stored memories.
    Use this at the start of a conversation to recall relevant context.
    """
    try:
        db_path = _get_memory_db()
        _ensure_memory_table(db_path)
        import sqlite3
        db = sqlite3.connect(db_path, check_same_thread=False)
        db.row_factory = sqlite3.Row
        if key:
            cursor = db.execute(
                "SELECT key, value, updated FROM agent_memory WHERE key = ?", (key,)
            )
        else:
            cursor = db.execute(
                "SELECT key, value, updated FROM agent_memory ORDER BY updated DESC"
            )
        rows = cursor.fetchall()
        db.close()
        if not rows:
            if key:
                return f"No memory found for key '{key}'."
            return "No memories stored yet."
        results = []
        for r in rows:
            results.append(f"[{r['key']}] ({r['updated']})\n{r['value']}")
        return "\n\n".join(results)
    except Exception as e:
        return f"recall error: {e}"


@tool
def forget(key: str) -> str:
    """
    Delete a specific fact from persistent memory by key.
    """
    try:
        db_path = _get_memory_db()
        _ensure_memory_table(db_path)
        import sqlite3
        db = sqlite3.connect(db_path, check_same_thread=False)
        db.execute("DELETE FROM agent_memory WHERE key = ?", (key,))
        affected = db.total_changes
        db.commit()
        db.close()
        if affected:
            return f"Deleted memory '{key}'."
        return f"No memory found with key '{key}'."
    except Exception as e:
        return f"forget error: {e}"


# ── Tool Composition (custom compound tools) ──────────────────────────────────

COMPOUND_TOOLS: dict[str, dict] = {}

# Cache for dynamically created @tool functions so build_agent reuses them
_COMPOUND_TOOL_FUNCS: dict[str, object] = {}


def _execute_compound_tool(name: str, **kwargs) -> str:
    """Execute a registered compound tool by name."""
    spec = COMPOUND_TOOLS.get(name)
    if not spec:
        return f"Compound tool '{name}' not found."
    steps = spec.get("steps", [])
    lines = [f"Running compound tool '{name}':"]
    for i, step in enumerate(steps):
        tool_name = step.get("tool", "")
        step_input = step.get("input", {})
        lines.append(f"\nStep {i+1}: {tool_name}({step_input})")
        # Find the function in ALL_TOOLS by name
        func = None
        for t in ALL_TOOLS:
            if t.name == tool_name:
                func = t
                break
        if not func:
            lines.append(f"  Error: tool '{tool_name}' not found.")
            continue
        try:
            if isinstance(step_input, dict):
                result = func.invoke(step_input)
            else:
                result = func.invoke({"input": step_input})
            result_str = str(result)[:2000]
            lines.append(f"  Result: {result_str}")
        except Exception as e:
            lines.append(f"  Error: {e}")
    return "\n".join(lines)


@tool
def compose_tool(
    name: str,
    description: str,
    steps: str,
) -> str:
    """
    Create a new compound tool that chains multiple primitive tools together.
    Once created, the compound tool can be called by name like any other tool.
    
    Parameters:
      name: Short unique name for the new tool (e.g. 'research_and_summarize')
      description: What this compound tool does (shown to the LLM)
      steps: JSON array of step objects. Each step has:
             {"tool": "tool_name", "input": {"param": "value"}}
             
    Example steps:
      [{"tool": "vector_search", "input": {"query": "topic", "top_k": 3}},
       {"tool": "web_search", "input": {"query": "topic recent"}},
       {"tool": "run_python", "input": {"code": "print('done')"}}]
    """
    try:
        import json
        parsed_steps = json.loads(steps) if isinstance(steps, str) else steps
        if not isinstance(parsed_steps, list) or not parsed_steps:
            return "steps must be a non-empty JSON array."
        for s in parsed_steps:
            if not isinstance(s, dict) or "tool" not in s:
                return "Each step must be an object with a 'tool' key."
            # Validate tool exists
            found = False
            for t in ALL_TOOLS:
                if t.name == s["tool"]:
                    found = True
                    break
            if not found:
                return f"Tool '{s['tool']}' is not a valid primitive tool."
        COMPOUND_TOOLS[name] = {
            "description": description,
            "steps": parsed_steps,
        }
        # Clear cache so build_agent picks it up
        if name in _COMPOUND_TOOL_FUNCS:
            del _COMPOUND_TOOL_FUNCS[name]
        return (
            f"Compound tool '{name}' created with {len(parsed_steps)} steps.\n"
            f"Description: {description}\n"
            f"You can now call {name}() like any other tool."
        )
    except json.JSONDecodeError as e:
        return f"Invalid JSON in steps: {e}"
    except Exception as e:
        return f"compose_tool error: {e}"


def _get_dynamic_tools() -> list:
    """Return compound tool wrappers for registered COMPOUND_TOOLS."""
    import functools
    result = []
    for name, spec in COMPOUND_TOOLS.items():
        if name in _COMPOUND_TOOL_FUNCS:
            result.append(_COMPOUND_TOOL_FUNCS[name])
            continue

        def _make_runner(n=name):
            return lambda **kwargs: _execute_compound_tool(n, **kwargs)

        dynamic_func = tool(
            _make_runner(name),
            name=name,
            description=spec.get("description", ""),
        )
        _COMPOUND_TOOL_FUNCS[name] = dynamic_func
        result.append(dynamic_func)
    return result


# ── Tool registry ─────────────────────────────────────────────────────────────

ALL_TOOLS = [
    shell_exec,
    read_file,
    write_file,
    append_file,
    diff_files,
    list_dir,
    web_search,
    fetch_url,
    vector_search,
    system_info,
    get_context_logs,
    get_session_stats,
    ingest_file,
    list_knowledge,
    delete_knowledge,
    run_python,
    run_sql,
    plan,
    remember,
    recall,
    forget,
    compose_tool,
]

TOOL_DESCRIPTIONS = {
    "shell_exec": "Run bash commands (system ops: git, apt, compile, background processes). NOT for Python scripts — use run_python instead.",
    "read_file": "Read any local file (text or binary). Use instead of shell_exec cat.",
    "write_file": "Write / overwrite a local file (auto-backup). Use instead of shell_exec echo/heredoc.",
    "append_file": "Append content to a file.",
    "diff_files": "Unified diff between two files.",
    "list_dir": "Directory tree listing. Use instead of shell_exec ls.",
    "web_search": "DuckDuckGo web search for up-to-date information.",
    "fetch_url": "Fetch a URL as plain text.",
    "vector_search": "Query the local knowledge base (Qdrant RAG). Use for questions about the codebase or ingested docs.",
    "system_info": "CPU / RAM / GPU / disk snapshot. Use instead of shell_exec free/df/nvidia-smi.",
    "get_context_logs": "Retrieve conversation history for a session.",
    "get_session_stats": "Token counts and context usage for a session.",
    "ingest_file": "Re-ingest a knowledge file into Qdrant.",
    "list_knowledge": "List all files in KB with chunk counts from Qdrant.",
    "delete_knowledge": "Delete vectors for a file from Qdrant (not the file itself).",
    "run_python": "Execute Python code inline (calculations, data analysis, text processing, quick scripts). PREFER this over shell_exec for Python work. NOT for long-running processes.",
    "run_sql": "Run a SELECT query on the session database.",
    "plan": "Create a structured multi-step plan for complex tasks that need multiple tool calls.",
    "remember": "Store a fact in persistent memory (key-value across sessions).",
    "recall": "Retrieve facts from persistent memory (optionally by key). Call at conversation start.",
    "forget": "Delete a fact from persistent memory by key.",
    "compose_tool": "Create a new compound tool that chains multiple primitive tools.",
}

# ── Agent builder ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a powerful AI assistant with full tool-use capabilities.
You have access to:
- shell_exec: Run bash commands (requires user confirmation)
- read_file / write_file / append_file / diff_files: File operations
- list_dir: Browse directory structure
- web_search: Search the web via DuckDuckGo
- fetch_url: Fetch URL contents as text
- vector_search: Search the local knowledge base (Qdrant RAG)
- system_info: Hardware/software snapshot
- get_context_logs: Retrieve conversation history for a session
- get_session_stats: Token counts and context usage for a session
- ingest_file: Re-ingest a knowledge file into Qdrant
- list_knowledge: List all files in KB with chunk counts from Qdrant
- delete_knowledge: Delete vectors for a file from Qdrant
- run_python: Execute Python code in a subprocess (NOT for long-running processes; use shell_exec instead)
- run_sql: Run a SELECT query on the session database
- plan: Create a structured multi-step plan for complex tasks
- remember / recall / forget: Persistent key-value memory across sessions
- compose_tool: Create new compound tools that chain primitive tools

CRITICAL — NEVER overcomplicate:
- NEVER create Python virtual environments for simple tasks.
- NEVER install pip packages (flask, fastapi, requests) for trivial scripts or hello-world demos.
- Use Python's built-in `http.server` for simple web servers, not Flask.
- For calculations, data formatting, string manipulation, or quick scripts: use **run_python** with inline code, NOT shell_exec.
- For file reads/writes: use **read_file** / **write_file** tools, NOT shell_exec with cat/echo.
- For system info (CPU, RAM, disk, GPU): use **system_info** tool, NOT shell_exec with free/df/nvidia-smi.
- Only use shell_exec when you truly need a system operation (git, compilation, background process, package install via apt).

Rules:
1. For shell_exec, inform the user what command you want to run and why.
2. Use vector_search proactively when the question relates to the knowledge base.
3. Write well-structured, correct code.
4. When reading files, respect the file size limit.
5. Do NOT fabricate information — use tools to verify facts.
6. Always explain what you plan to do before doing it.
7. For complex tasks, call plan() first to create a structured approach, then execute each step.
8. At the start of a conversation, call recall() to load persistent memories relevant to the user's request.
9. Use remember() to store important facts about the user (name, preferences, project details) so they persist across sessions.
10. Prefer system_info over installing packages or writing custom scripts for CPU/RAM/disk/GPU data.
11. Use write_file to write multi-line files. Do NOT use echo with escaped \\n.
12. run_python is for short scripts only. For servers/background processes, use shell_exec to write the file then background it (& or nohup).
13. Avoid chaining commands with && when a preceding command might fail (e.g., kill -9 ... && ...). Use ; or separate steps instead."""


def build_agent(model_name: str = None, upstream: str = None, api_key: str = None):

    llm = ChatOpenAI(
        model=model_name or "qwen3:14b-q8_0",
        openai_api_base=upstream + "/v1",
        openai_api_key=api_key or "not-needed",
        temperature=0.3,
        streaming=True,
    )

    tools = ALL_TOOLS + _get_dynamic_tools()

    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
    )
    return agent


def build_messages_from_history(history: list[dict]) -> list:
    msgs = []
    for m in history:
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "user":
            msgs.append(HumanMessage(content=content))
        elif role == "assistant":
            msgs.append(AIMessage(content=content))
        elif role == "system":
            msgs.append(SystemMessage(content=content))
    return msgs
