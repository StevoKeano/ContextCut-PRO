"""ContextCut PRO self-knowledge.

Single source of truth for what the assistant knows about its own capabilities
and how to use ContextCut PRO.

- ``capabilities_text()`` loads the full capabilities doc from ``CAPABILITIES.md``
  next to this module (cached), falling back to a short embedded summary.
- ``CAPABILITIES_BLURB`` is the compact always-on summary injected into the system
  prompt in both chat and agent modes.
- ``is_meta_question()`` detects capability / how-to-use questions so the proxy can
  inject the full doc on demand.
"""

from __future__ import annotations

import re
from pathlib import Path

_CAPABILITIES_PATH = Path(__file__).resolve().parent / "CAPABILITIES.md"

_FALLBACK_TEXT = (
    "ContextCut PRO is a local semantic RAG proxy placed in front of an "
    "OpenAI-compatible LLM. It retrieves the most relevant chunks from a Qdrant "
    "knowledge base and injects only those above the relevance threshold. It also "
    "provides an Agent mode with local tools (shell, file, web, Python, knowledge "
    "search, memory), a dashboard, a headless coding worker (coding_agent.py), and a "
    "two-agent coding orchestrator (orchestrator.py). See README.md for full docs."
)

CAPABILITIES_BLURB = (
    "CAPABILITIES (ContextCut PRO):\n"
    "You are running inside ContextCut PRO, a local semantic RAG proxy placed in "
    "front of an OpenAI-compatible LLM.\n"
    "- Normal chat (Agent OFF): answers with automatic knowledge-base retrieval; no tools.\n"
    "- Agent mode (Agent ON): a tool-use agent that can run shell commands, read/write "
    "files, search the knowledge base (vector_search), run Python, plan, and remember "
    "across sessions. High-impact tools ask for approval.\n"
    "- Dashboard (http://localhost:18787) toggles: Scan, DEEP, TypeSafe, Agent, "
    "Unattended, Workspace, OpenCode. Proxy endpoint: http://localhost:18788/v1.\n"
    "- Coding: use Agent mode with a Workspace, the headless coding_agent.py worker, or "
    "the two-agent orchestrator.py (implementer + verifier with deterministic gates).\n"
    "- Checkpoints save every agent step; resume with /resume <task_id> or the dashboard "
    "Resume button.\n"
    "- Add knowledge by dropping files into ~/contextcut/knowledge, uploading via the "
    "File Browser, or calling ingest_file in Agent mode.\n"
    "For questions about your own capabilities or how to use ContextCut PRO, call "
    "contextcut_help() in Agent mode, or answer from this summary. Do not invent features."
)

# Conservative patterns for capability / self-knowledge questions. Each requires an
# explicit reference to "you"/"contextcut"/"yourself" so ordinary usage questions
# (e.g. "how do I use Python") do not match.
_META_PATTERN = re.compile(
    r"(?:"
    r"what\s+(?:can|do)\s+you\s+(?:do|help(?:\s+with)?)"
    r"|how\s+can\s+you\s+help"
    r"|what\s+are\s+you(?:\s+(?:capable|able))?\b"
    r"|who\s+are\s+you"
    r"|tell\s+me\s+about\s+(?:yourself|contextcut)"
    r"|(?:your|the)\s+(?:capabilities|features|commands|options)"
    r"|what\s+(?:can|does)\s+contextcut"
    r"|what\s+is\s+contextcut"
    r"|how\s+does\s+contextcut\s+work"
    r"|how\s+do\s+you\s+work"
    r"|how\s+do\s+i\s+use\s+(?:you|contextcut)"
    r"|how\s+to\s+use\s+(?:you|contextcut)"
    r"|how\s+do\s+i\s+(?:code|work)\s+with\s+you"
    r"|how\s+do\s+i\s+(?:set\s+(?:you|it|contextcut)\s+up|get\s+started)"
    r"|what\s+(?:tools|features)\s+(?:do\s+you|does\s+contextcut)\s+have"
    r"|help\s+me\s+get\s+started"
    r")",
    re.IGNORECASE,
)

_text_cache: str | None = None


def capabilities_text() -> str:
    """Return the full capabilities doc (cached)."""
    global _text_cache
    if _text_cache is None:
        try:
            _text_cache = _CAPABILITIES_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            _text_cache = _FALLBACK_TEXT
    return _text_cache


def capabilities_block() -> str:
    """Return the trusted system block injected for meta questions."""
    return (
        "## ContextCut PRO capabilities (trusted, not untrusted data):\n\n"
        + capabilities_text()
    )


def is_meta_question(text: str) -> bool:
    """True when *text* asks about the assistant's own capabilities or usage."""
    if not text:
        return False
    return bool(_META_PATTERN.search(text))
