"""typesafe_scan.py — TypeSafe (Jev) backed claim verifier for ContextCut-PRO.

Sends batched ``Noul`` questions to the TypeSafe System One API to estimate how
strongly a supplied evidence bundle supports each claim in an agent response.

Design notes (per TypeSafe's integration guidance):
  - Jev makes the judgment; this module makes the decisions (thresholds in code).
  - All claims that share the same evidence go in one request (questions are
    cheap and evaluated in parallel; the state is read once).
  - A failed API call is surfaced as an error-backed "uncertain", never as a
    silent "correct".

The returned entries match the payload the dashboard already renders:
``{text, factual, reason, source_url}``. Span offsets (``start``/``end``) are
added by ``agent_handler`` because that is where ``_find_flexible_offsets``
lives.

Environment:
  CONTEXTCUT_SCAN_BACKEND=llm|typesafe   backend selector (default: llm)
  TYPESAFE_API_KEY=<key>                 required for the typesafe backend
  CONTEXTCUT_TYPESAFE_MODEL=jev-latest   model id/alias (pin for stable results)
  CONTEXTCUT_TYPESAFE_TIMEOUT=20         request timeout in seconds
  CONTEXTCUT_TYPESAFE_YES=0.7            noul >= yes  -> "correct"
  CONTEXTCUT_TYPESAFE_NO=0.3             noul <= no   -> "incorrect"
  CONTEXTCUT_TYPESAFE_MAX_SOURCES=28000  max chars of evidence sent (per-question cap)
"""

from __future__ import annotations

import os
import re
from datetime import datetime

import requests

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
DEFAULT_TIMEOUT = 20.0
DEFAULT_MAX_SOURCES = 28000
DEFAULT_YES = 0.7
DEFAULT_NO = 0.3

# Same sentence-ish split the deep scan already uses.
_CLAIM_SPLIT = re.compile(r"(?<=[.?!])\s+")
_URL_RE = re.compile(r"https?://[^\s)\]}<>\"']+")


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name, default) or "").strip()


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def is_enabled() -> bool:
    """True when the typesafe backend is selected and an API key is present."""
    backend = _env("CONTEXTCUT_SCAN_BACKEND", "llm").lower()
    return backend == "typesafe" and bool(_env("TYPESAFE_API_KEY"))


def thresholds() -> tuple[float, float]:
    return _env_float("CONTEXTCUT_TYPESAFE_YES", DEFAULT_YES), _env_float(
        "CONTEXTCUT_TYPESAFE_NO", DEFAULT_NO
    )


def split_claims(text: str) -> list[str]:
    """Segment text into claim-sized units, preserving exact substrings."""
    if not text:
        return []
    parts = [c.strip() for c in _CLAIM_SPLIT.split(text)]
    return [c for c in parts if len(c) >= 10]


def _source_hint(sources: str) -> str:
    """Best-effort source URL; TypeSafe does not return citations."""
    match = _URL_RE.search(sources or "")
    return match.group(0) if match else "unverifiable"


def _classify(noul: float, yes: float, no: float) -> tuple[str, str]:
    if noul >= yes:
        return "correct", f"TypeSafe P(supported)={noul:.2f}"
    if noul <= no:
        return "incorrect", f"TypeSafe P(supported)={noul:.2f}"
    return "uncertain", f"TypeSafe P(supported)={noul:.2f} (unsettled)"


def _error_results(claims: list[str], message: str) -> list[dict]:
    return [
        {
            "text": c,
            "factual": "uncertain",
            "reason": f"TypeSafe error: {message}",
            "source_url": "unverifiable",
            "backend": "typesafe",
        }
        for c in claims
    ]


def build_request(claims: list[str], sources: str, model: str | None = None) -> dict:
    """Build the batched System One request body.

    Shared evidence goes in ``state`` once; each claim becomes its own Noul so
    the judgments stay independent.
    """
    max_sources = _env_int("CONTEXTCUT_TYPESAFE_MAX_SOURCES", DEFAULT_MAX_SOURCES)
    truncated = (sources or "")[:max_sources]
    questions = {
        f"claim_{i}": {
            "type": "noul",
            "instructions": (
                "Does `sources` support the following claim? "
                f"Claim: {claim}"
            ),
        }
        for i, claim in enumerate(claims)
    }
    return {
        "model": model or _env("CONTEXTCUT_TYPESAFE_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL,
        "state": {"sources": truncated},
        "questions": questions,
    }


def verify_claims(
    claims: list[str],
    sources: str,
    model: str | None = None,
    timeout: float | None = None,
) -> list[dict] | None:
    """Verify each claim against ``sources`` with one batched TypeSafe request.

    Returns ``None`` when the backend is disabled, an empty list when there are
    no claims, otherwise one payload-compatible dict per claim.
    """
    if not claims:
        return []
    if not is_enabled():
        return None
    if not (sources or "").strip():
        return [
            {
                "text": c,
                "factual": "uncertain",
                "reason": "TypeSafe: no evidence to verify against",
                "source_url": "unverifiable",
                "backend": "typesafe",
            }
            for c in claims
        ]

    api_key = _env("TYPESAFE_API_KEY")
    body = build_request(claims, sources, model=model)
    timeout_s = timeout if timeout is not None else _env_float(
        "CONTEXTCUT_TYPESAFE_TIMEOUT", DEFAULT_TIMEOUT
    )
    yes, no = thresholds()
    src_hint = _source_hint(sources)

    try:
        resp = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # network, HTTP, JSON, timeout
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] [TypeSafe] request failed: {exc}",
            flush=True,
        )
        return _error_results(claims, str(exc))

    answers = data.get("answers") or {}
    usage = data.get("usage") or {}
    if usage:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] [TypeSafe] "
            f"model={data.get('model', '?')} claims={len(claims)} "
            f"input_tokens={usage.get('input_tokens', '?')}",
            flush=True,
        )

    results: list[dict] = []
    for i, claim in enumerate(claims):
        answer = answers.get(f"claim_{i}") or {}
        noul = answer.get("noul")
        if not isinstance(noul, (int, float)):
            results.append(
                {
                    "text": claim,
                    "factual": "uncertain",
                    "reason": "TypeSafe: no answer returned",
                    "source_url": src_hint,
                    "backend": "typesafe",
                }
            )
            continue
        noul = float(noul)
        factual, reason = _classify(noul, yes, no)
        results.append(
            {
                "text": claim,
                "factual": factual,
                "reason": reason,
                "noul": noul,
                "source_url": src_hint,
                "backend": "typesafe",
            }
        )
    return results
