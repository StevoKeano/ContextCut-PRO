"""Injection detection and security alerting.

This module is observational: it records suspicious untrusted content and
emits alerts for the dashboard/log. It does not block content by itself.
Capability restrictions and approval gates are the actual containment layer.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from untrusted_content import redact_secret_values, redact_special_tokens

_MAX_ALERTS = int(os.environ.get("CONTEXTCUT_ALERTS_MAX", "200"))
_ALERT_DIR = Path(os.environ.get("CONTEXTCUT_ALERT_DIR", str(Path.home() / ".contextcut")))
_ALERT_FILE = Path(
    os.environ.get("CONTEXTCUT_ALERT_FILE", str(_ALERT_DIR / "security_alerts.jsonl"))
)

_LOCK = threading.Lock()
_ALERTS: deque[dict] = deque(maxlen=_MAX_ALERTS)
_SEQ = 0


_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "instruction-override",
        "high",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b[^\n]{0,40}\b"
            r"(previous|prior|above|system|developer|all)\b[^\n]{0,40}\b"
            r"(instruction|prompt|message|rule|direction)s?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system-prompt-extraction",
        "high",
        re.compile(
            r"\b(reveal|print|show|repeat|output|dump|leak|exfiltrate)\b"
            r"[^\n]{0,60}\b(system|developer|hidden|initial)\b[^\n]{0,30}\b"
            r"(prompt|instruction|message)s?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "secret-exfiltration",
        "critical",
        re.compile(
            r"\b(api[_-]?key|secret|token|password|credential|private[_-]?key)\b"
            r"[^\n]{0,80}\b(send|post|upload|exfiltrate|curl|wget|http)\b"
            r"|\b(curl|wget)\b[^\n]{0,120}\b(api[_-]?key|secret|token|password|\.env)\b"
            r"|\bexfiltrat(e|ion)\b[^\n]{0,120}\b(\.ssh|\.env|api[_-]?key|secret|token|password|id_rsa)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "shell-execution",
        "medium",
        re.compile(
            r"\b(run|execute|invoke|call)\b[^\n]{0,60}\b(shell|bash|command|script)\b"
            r"|\b(bash\s+-c|sh\s+-c|powershell|cmd\.exe)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "encoded-payload",
        "medium",
        re.compile(
            r"\b(base64|atob|fromCharCode|b64decode|eval\s*\(|exec\s*\()\b",
            re.IGNORECASE,
        ),
    ),
    (
        "special-token",
        "medium",
        re.compile(r"<[|｜][^|｜<>\n]{1,64}[|｜]>"),
    ),
    (
        "canary-trigger",
        "critical",
        re.compile(
            r"\b(contextcut[-_ ]?canary|cc[-_ ]?pwned|/tmp/cc[-_ ]|"
            r"attacker\.invalid|exfiltrat(e|ion))\b",
            re.IGNORECASE,
        ),
    ),
]


def _excerpt(text: str, match: re.Match[str], radius: int = 80) -> str:
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    snippet = text[start:end].replace("\n", " ").replace("\r", " ")
    snippet = redact_secret_values(redact_special_tokens(snippet))
    return snippet[:240]


def scan_text(text: str) -> list[dict]:
    """Return pattern matches for *text*. Does not record an alert."""
    if not text:
        return []
    found: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for category, severity, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            key = (category, match.start())
            if key in seen:
                continue
            seen.add(key)
            found.append(
                {
                    "category": category,
                    "severity": severity,
                    "match": _excerpt(text, match),
                }
            )
    return found


def _enabled() -> bool:
    return os.environ.get("CONTEXTCUT_INJECTION_ALERTS", "1").strip().lower() not in {
        "0",
        "false",
        "off",
        "no",
    }


def record_alert(
    source: str,
    kind: str,
    matches: list[dict],
    *,
    excerpt: str = "",
) -> dict | None:
    """Store a security alert in memory and JSONL. Returns the alert dict."""
    if not matches or not _enabled():
        return None
    global _SEQ
    alert = {
        "seq": 0,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "source": (source or "unknown")[:160],
        "kind": (kind or "data")[:40],
        "severity": max(
            (m.get("severity", "low") for m in matches),
            key=lambda s: {"low": 0, "medium": 1, "high": 2, "critical": 3}.get(s, 0),
        ),
        "categories": sorted({m.get("category", "unknown") for m in matches}),
        "matches": matches[:5],
        "excerpt": redact_secret_values(redact_special_tokens((excerpt or "")[:500])),
    }
    with _LOCK:
        _SEQ += 1
        alert["seq"] = _SEQ
        _ALERTS.append(alert)
    try:
        _ALERT_DIR.mkdir(parents=True, exist_ok=True)
        with open(_ALERT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(alert, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return alert


def observe_untrusted(text: str, source: str, kind: str) -> list[dict]:
    """Scan and record an alert for untrusted content entering the model."""
    matches = scan_text(text)
    if matches:
        record_alert(source, kind, matches, excerpt=text)
    return matches


def get_alerts_since(seq: int = 0) -> list[dict]:
    with _LOCK:
        return [a for a in _ALERTS if a.get("seq", 0) > seq]


def get_recent_alerts(limit: int = 50) -> list[dict]:
    with _LOCK:
        return list(_ALERTS)[-max(1, min(int(limit), _MAX_ALERTS)) :]


def latest_seq() -> int:
    with _LOCK:
        return _SEQ


def reset_alerts() -> None:
    """Test helper: clear in-memory alerts (does not truncate the JSONL file)."""
    global _SEQ
    with _LOCK:
        _ALERTS.clear()
        _SEQ = 0


__all__ = [
    "get_alerts_since",
    "get_recent_alerts",
    "latest_seq",
    "observe_untrusted",
    "record_alert",
    "reset_alerts",
    "scan_text",
]
