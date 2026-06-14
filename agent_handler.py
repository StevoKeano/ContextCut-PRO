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


# ── Tool definitions ──────────────────────────────────────────────────────────


@tool
def shell_exec(command: str) -> str:
    """
    Execute a bash shell command and return stdout + stderr.
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
        from qdrant_proxy_final import qdrant_context

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
]

TOOL_DESCRIPTIONS = {
    "shell_exec": "Run bash commands",
    "read_file": "Read any local file",
    "write_file": "Write / overwrite a local file (auto-backup)",
    "append_file": "Append to a file",
    "diff_files": "Unified diff between two files",
    "list_dir": "Directory tree listing",
    "web_search": "DuckDuckGo web search",
    "fetch_url": "Fetch a URL as plain text",
    "vector_search": "Query Qdrant RAG via ContextCut-PRO",
    "system_info": "CPU / RAM / GPU / disk snapshot",
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

Rules:
1. For shell_exec, inform the user what command you want to run and why.
2. Use vector_search proactively when the question relates to the knowledge base.
3. Write well-structured, correct code.
4. When reading files, respect the file size limit.
5. Do NOT fabricate information — use tools to verify facts.
6. Always explain what you plan to do before doing it."""


def build_agent(model_name: str = None):
    from qdrant_proxy_final import get_current_upstream, get_current_api_key

    upstream = get_current_upstream()
    api_key = get_current_api_key()

    llm = ChatOpenAI(
        model=model_name or "gpt-4o",
        openai_api_base=upstream + "/v1",
        openai_api_key=api_key or "not-needed",
        temperature=0.3,
        streaming=True,
    )

    agent = create_agent(
        model=llm,
        tools=ALL_TOOLS,
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
