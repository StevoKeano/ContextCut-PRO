"""typesafe_scan.py — TypeSafe (Jev) backed claim verifier for ContextCut-PRO.

Sends batched questions to the TypeSafe System One API to estimate how strongly
a supplied evidence bundle supports (or contradicts) each claim in an agent
response.

Cost model (per TypeSafe docs):
  - You pay per input token ($0.042/Mtok); output tokens are free.
  - ``state`` is ingested once per request and every question is evaluated
    against it in parallel. There is no server-side state handle, so the only
    way to amortize state is to ask every question in one request.
  - Consequently we put the evidence *and the claims* in ``state`` (claims once,
    with stable IDs) and make each question a short reference to a claim ID.
    Fanning out many questions is cheap; repeating claim text per question is not.

Question IDs are the keys in ``questions``; TypeSafe returns answers keyed by the
same names. That is the API's ID mechanism (there is no separate ``id`` field).

Environment:
  CONTEXTCUT_SCAN_BACKEND=llm|typesafe      backend selector (default: llm)
  TYPESAFE_API_KEY=<key>                    required for typesafe
  CONTEXTCUT_TYPESAFE_MODEL=jev-latest      model id/alias (pin for stability)
  CONTEXTCUT_TYPESAFE_TIMEOUT=20            request timeout in seconds
  CONTEXTCUT_TYPESAFE_YES=0.7               noul >= yes -> supported/contradicted
  CONTEXTCUT_TYPESAFE_NO=0.3                below no -> unsupported (not "false")
  CONTEXTCUT_TYPESAFE_MIN_SOURCES=80        min evidence chars; below -> uncertain
  CONTEXTCUT_TYPESAFE_MAX_SOURCES=28000     max evidence chars in state
  CONTEXTCUT_TYPESAFE_DIMENSIONS=...        per-claim dimensions (comma list)
  CONTEXTCUT_TYPESAFE_GLOBALS=...           global dimensions (comma list)
  CONTEXTCUT_TYPESAFE_MAX_REQUEST_TOKENS=60000  soft request budget (state+questions)
  CONTEXTCUT_TYPESAFE_MAX_QUESTIONS=400     hard cap on questions per request
  CONTEXTCUT_TYPESAFE_MIN_CONFIDENCE=0.8    Choice confidence below this needs review
  CONTEXTCUT_TYPESAFE_CACHE_TTL=900         in-memory answer cache TTL (0=off)
  CONTEXTCUT_TYPESAFE_CACHE_SIZE=128        max cached responses
  CONTEXTCUT_TYPESAFE_MAX_RETRIES=2         retries for HTTP 429/rate limits
  CONTEXTCUT_TYPESAFE_RETRY_BACKOFF=1.0     base seconds between retries
  CONTEXTCUT_TYPESAFE_LONG_CONTEXT=0        send the 262k long-context header

Design notes (per TypeSafe's integration guidance):
  - Jev makes the judgment; this module makes the decisions (thresholds in code).
  - Decompose broad judgments into atomic questions and combine in code.
  - A failed API call is surfaced as an error-backed "uncertain", never as a
    silent "correct".
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime

import requests

from untrusted_content import redact_secret_values, redact_special_tokens

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-1.14.0"
DEFAULT_TIMEOUT = 20.0
DEFAULT_MAX_SOURCES = 28000
DEFAULT_MIN_SOURCES = 80
DEFAULT_YES = 0.7
DEFAULT_NO = 0.3
DEFAULT_MAX_REQUEST_TOKENS = 60000
DEFAULT_MAX_REQUEST_CONTEXT = 64000
DEFAULT_MAX_QUESTION_CONTEXT = 32000
LONG_CONTEXT_LIMIT = 262000
DEFAULT_MAX_QUESTIONS = 400
DEFAULT_MIN_CONFIDENCE = 0.8
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF = 1.0
DEFAULT_CACHE_TTL = 900
DEFAULT_CACHE_SIZE = 128
USD_PER_MTOK = 0.042

# Per-claim dimensions. "verdict" is a Choice question; "severity" is a Score.
CORE_DIMS = ("verdict", "support", "contradict", "sufficient")
OPTIONAL_DIMS = ("subjective", "severity", "numeric", "entity", "temporal")
CONDITIONAL_DIMS = {"numeric", "entity", "temporal"}
KNOWN_DIMS = set(CORE_DIMS) | set(OPTIONAL_DIMS)
DEFAULT_DIMS = ("verdict", "support", "contradict", "sufficient", "subjective", "severity")

KNOWN_GLOBALS = {"sources_sufficient", "faithful_overall", "any_hallucination", "source_quality"}
DEFAULT_GLOBALS = ("sources_sufficient", "faithful_overall")

_NO_EVIDENCE_SENTINELS = {"no relevant context found", "no relevant context found."}

# Same sentence-ish split the deep scan already uses.
_CLAIM_SPLIT = re.compile(r"(?<=[.?!])\s+")
_URL_RE = re.compile(r"https?://[^\s)\]}<>\"']+")
_NUMERIC_RE = re.compile(r"\d")
_ENTITY_RE = re.compile(r"\b[A-Z][a-z]{2,}")
_TEMPORAL_RE = re.compile(
    r"\b(19|20)\d{2}\b|\b(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\b|\b\d{1,2}:\d{2}\b",
    re.IGNORECASE,
)

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()


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


def _env_flag(name: str, default: bool = False) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def is_enabled() -> bool:
    """True when the typesafe backend is selected and an API key is present."""
    backend = _env("CONTEXTCUT_SCAN_BACKEND", "llm").lower()
    return backend == "typesafe" and bool(_env("TYPESAFE_API_KEY"))


def thresholds() -> tuple[float, float]:
    return _env_float("CONTEXTCUT_TYPESAFE_YES", DEFAULT_YES), _env_float(
        "CONTEXTCUT_TYPESAFE_NO", DEFAULT_NO
    )


def clear_cache() -> None:
    """Drop all cached TypeSafe answers (used by tests and manual resets)."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _cache_key(body: dict) -> str:
    payload = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> dict | None:
    ttl = _env_float("CONTEXTCUT_TYPESAFE_CACHE_TTL", DEFAULT_CACHE_TTL)
    if ttl <= 0:
        return None
    now = time.time()
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if not item:
            return None
        ts, answers = item
        if now - ts > ttl:
            _CACHE.pop(key, None)
            return None
        return answers


def _cache_put(key: str, answers: dict) -> None:
    ttl = _env_float("CONTEXTCUT_TYPESAFE_CACHE_TTL", DEFAULT_CACHE_TTL)
    if ttl <= 0:
        return
    size = max(1, _env_int("CONTEXTCUT_TYPESAFE_CACHE_SIZE", DEFAULT_CACHE_SIZE))
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), answers)
        if len(_CACHE) > size:
            overflow = len(_CACHE) - size
            for old_key in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:overflow]:
                _CACHE.pop(old_key, None)


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


def has_evidence(sources: str) -> bool:
    """True when ``sources`` contains usable evidence for TypeSafe.

    Empty strings, the DEEP prefetch sentinel, and trivially short snippets are
    treated as no evidence. Grading those would make every claim look
    "unsupported", which is not the same as "false".
    """
    text = (sources or "").strip()
    if not text:
        return False
    if text.lower() in _NO_EVIDENCE_SENTINELS:
        return False
    return len(text) >= _env_int("CONTEXTCUT_TYPESAFE_MIN_SOURCES", DEFAULT_MIN_SOURCES)


def _dimensions() -> tuple[str, ...]:
    raw = _env("CONTEXTCUT_TYPESAFE_DIMENSIONS")
    if not raw:
        return DEFAULT_DIMS
    dims = tuple(d.strip().lower() for d in raw.split(",") if d.strip())
    return tuple(d for d in dims if d in KNOWN_DIMS) or DEFAULT_DIMS


def _global_dimensions() -> tuple[str, ...]:
    raw = _env("CONTEXTCUT_TYPESAFE_GLOBALS")
    if not raw:
        return DEFAULT_GLOBALS
    dims = tuple(d.strip().lower() for d in raw.split(",") if d.strip())
    return tuple(d for d in dims if d in KNOWN_GLOBALS)


def _should_ask(dim: str, claim: str) -> bool:
    if dim == "numeric":
        return bool(_NUMERIC_RE.search(claim))
    if dim == "entity":
        return bool(_ENTITY_RE.search(claim))
    if dim == "temporal":
        return bool(_TEMPORAL_RE.search(claim))
    return True


def _noul(instructions: str) -> dict:
    return {"type": "noul", "instructions": instructions}


def _claim_question(cid: str, dim: str, claim: str) -> dict:
    quoted = f'"{claim.strip()}"'
    if dim == "verdict":
        return {
            "type": "choice",
            "instructions": f"Classify the claim {quoted} against `sources`.",
            "criteria": {
                "correct": "`sources` support the claim.",
                "incorrect": "`sources` contradict the claim.",
                "unsupported": (
                    "`sources` neither support nor contradict the claim, or do "
                    "not contain enough information."
                ),
                "opinion": (
                    "The claim is subjective, an opinion, or not fact-checkable."
                ),
            },
        }
    if dim == "support":
        return _noul(f"Do `sources` support the claim {quoted}?")
    if dim == "contradict":
        return _noul(f"Do `sources` contradict the claim {quoted}?")
    if dim == "sufficient":
        return _noul(
            f"Do `sources` contain enough information to decide whether the claim "
            f"{quoted} is true or false?"
        )
    if dim == "subjective":
        return _noul(
            f"Is the claim {quoted} subjective, an opinion, or not fact-checkable?"
        )
    if dim == "severity":
        return {
            "type": "score",
            "instructions": f"How severe is any factual error in the claim {quoted}?",
            "criteria": [
                "No error",
                "Minor inaccuracy",
                "Material error",
                "Critical misinformation",
            ],
        }
    if dim == "numeric":
        return _noul(f"Do the numbers and units in the claim {quoted} match `sources`?")
    if dim == "entity":
        return _noul(f"Do the named entities in the claim {quoted} match `sources`?")
    if dim == "temporal":
        return _noul(
            f"Are the dates and times in the claim {quoted} consistent with `sources`?"
        )
    raise ValueError(f"unknown dimension: {dim}")


def _global_question(dim: str) -> dict:
    if dim == "sources_sufficient":
        return _noul(
            "Do `sources` contain enough information to verify all claims in `claims`?"
        )
    if dim == "faithful_overall":
        return _noul("Are all claims in `claims` faithful to `sources`?")
    if dim == "any_hallucination":
        return _noul(
            "Does `claims` contain at least one factual claim that is not "
            "supported by `sources`?"
        )
    if dim == "source_quality":
        return {
            "type": "score",
            "instructions": "Rate the quality and reliability of `sources` as evidence.",
            "criteria": ["Unreliable", "Weak", "Adequate", "Strong"],
        }
    raise ValueError(f"unknown global dimension: {dim}")


def _est_tokens(value: object) -> int:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return max(1, len(text) // 4 + 1)


def _answer_meta(answers: dict, qid: str, kind: str) -> dict:
    answer = answers.get(qid) or {}
    if not isinstance(answer, dict):
        answer = {}
    confidence = answer.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = None
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict):
        probabilities = None
    if kind == "noul":
        value = answer.get("noul")
        value = float(value) if isinstance(value, (int, float)) else None
    elif kind == "choice":
        value = answer.get("choice")
        value = value if isinstance(value, str) else None
    elif kind == "score":
        value = answer.get("score")
        value = float(value) if isinstance(value, (int, float)) else None
    else:
        value = None
    return {"value": value, "confidence": confidence, "probabilities": probabilities}


def _answer_value(answers: dict, qid: str, kind: str):
    return _answer_meta(answers, qid, kind)["value"]


def _noul_value(answers: dict, qid: str) -> float | None:
    return _answer_value(answers, qid, "noul")


def build_request(
    claims: list[str], sources: str, model: str | None = None
) -> tuple[dict, dict]:
    """Build one batched System One request and the plan that maps IDs back.

    Each claim is named directly in its own questions (per the TypeSafe
    guidance to avoid ID indirection). ``state`` holds only the shared evidence,
    so claim text is repeated only across that claim's few short questions.
    """
    max_sources = _env_int("CONTEXTCUT_TYPESAFE_MAX_SOURCES", DEFAULT_MAX_SOURCES)
    raw_sources = redact_secret_values(sources or "")
    truncated = redact_special_tokens(raw_sources[:max_sources])
    safe_claims = [
        redact_special_tokens(redact_secret_values(claim)) for claim in claims
    ]
    claim_ids = [f"c{i:03d}" for i in range(len(claims))]
    state = {"sources": truncated}

    dims = _dimensions()
    globals_ = _global_dimensions()
    specs: list[tuple[int, str, str | None, str, str, dict]] = []
    for index, (cid, claim) in enumerate(zip(claim_ids, claims)):
        safe_claim = safe_claims[index]
        for dim in dims:
            if not _should_ask(dim, claim):
                continue
            question = _claim_question(cid, dim, safe_claim)
            priority = 0 if dim in CORE_DIMS else 1
            specs.append((priority, f"{cid}_{dim}", cid, dim, question["type"], question))
    for dim in globals_:
        question = _global_question(dim)
        specs.append((2, f"g_{dim}", None, dim, question["type"], question))

    # Core questions for every claim first, then optional diagnostics, then globals.
    specs.sort(key=lambda spec: spec[0])

    max_tokens = _env_int(
        "CONTEXTCUT_TYPESAFE_MAX_REQUEST_TOKENS", DEFAULT_MAX_REQUEST_TOKENS
    )
    max_questions = _env_int("CONTEXTCUT_TYPESAFE_MAX_QUESTIONS", DEFAULT_MAX_QUESTIONS)
    long_context = _env_flag("CONTEXTCUT_TYPESAFE_LONG_CONTEXT")
    per_question_limit = (
        LONG_CONTEXT_LIMIT if long_context else DEFAULT_MAX_QUESTION_CONTEXT
    )
    request_limit = LONG_CONTEXT_LIMIT if long_context else DEFAULT_MAX_REQUEST_CONTEXT

    state_tokens = _est_tokens(state)
    if state_tokens > per_question_limit - 2000:
        allowed_chars = max(0, (per_question_limit - 2000) * 4)
        truncated = truncated[:allowed_chars]
        state["sources"] = truncated
        state_tokens = _est_tokens(state)
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] [TypeSafe] state exceeded "
            f"per-question context; truncated sources to {len(truncated)} chars",
            flush=True,
        )

    selected: list[tuple[int, str, str | None, str, str, dict]] = []
    dropped = 0
    total_tokens = state_tokens
    for spec in specs:
        question_tokens = _est_tokens(spec[5])
        over_budget = total_tokens + question_tokens > max_tokens and spec[0] > 0
        over_question_limit = state_tokens + question_tokens > per_question_limit
        over_request_limit = total_tokens + question_tokens > request_limit
        if (
            len(selected) >= max_questions
            or over_budget
            or over_question_limit
            or over_request_limit
        ):
            dropped += 1
            continue
        selected.append(spec)
        total_tokens += question_tokens

    if dropped:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] [TypeSafe] budget: kept "
            f"{len(selected)}/{len(specs)} questions (est {total_tokens} tokens, "
            f"dropped {dropped})",
            flush=True,
        )

    questions = {spec[1]: spec[5] for spec in selected}
    plan = {
        "claims": {
            cid: {"index": index, "text": claim}
            for index, (cid, claim) in enumerate(zip(claim_ids, claims))
        },
        "questions": {
            spec[1]: {"claim_id": spec[2], "dim": spec[3], "kind": spec[4]}
            for spec in selected
        },
    }
    body = {
        "model": (
            model or _env("CONTEXTCUT_TYPESAFE_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL
        ),
        "state": state,
        "questions": questions,
    }
    return body, plan


def _no_evidence_results(claims: list[str]) -> list[dict]:
    return [
        {
            "text": claim,
            "claim_id": f"c{i:03d}",
            "factual": "uncertain",
            "reason": "TypeSafe: no evidence to verify against",
            "source_url": "unverifiable",
            "backend": "typesafe",
        }
        for i, claim in enumerate(claims)
    ]


def _error_results(claims: list[str], message: str) -> list[dict]:
    return [
        {
            "text": claim,
            "claim_id": f"c{i:03d}",
            "factual": "uncertain",
            "reason": f"TypeSafe error: {message}",
            "source_url": "unverifiable",
            "backend": "typesafe",
        }
        for i, claim in enumerate(claims)
    ]


def _decide(
    dims: dict,
    yes: float,
    no: float,
    insufficient: bool,
    *,
    confidences: dict | None = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> tuple[str, str, bool]:
    """Combine atomic answers into (verdict, note, needs_review)."""
    confidences = confidences or {}
    if insufficient:
        claim_sufficient = dims.get("sufficient")
        # The global question can be pessimistic when only some claims are
        # covered. A confident per-claim sufficiency judgment takes precedence.
        if claim_sufficient is None or claim_sufficient < yes:
            return "uncertain", "insufficient evidence", False

    verdict = dims.get("verdict")
    support = dims.get("support")
    contradict = dims.get("contradict")
    sufficient = dims.get("sufficient")
    subjective = dims.get("subjective")
    verdict_conf = confidences.get("verdict")
    verdict_trusted = verdict is not None and (
        verdict_conf is None or verdict_conf >= min_confidence
    )
    review = verdict is not None and not verdict_trusted

    if contradict is not None and contradict >= yes:
        return "incorrect", "", review
    if verdict_trusted and verdict == "incorrect":
        return "incorrect", "", review
    if subjective is not None and subjective >= yes:
        return "correct", "subjective/opinion (not fact-checked)", review
    if verdict_trusted and verdict == "opinion":
        return "correct", "subjective/opinion (not fact-checked)", review
    if verdict_trusted and verdict == "correct":
        return "correct", "", review
    if support is not None and support >= yes and (contradict is None or contradict <= no):
        return "correct", "", review
    if verdict_trusted and verdict == "unsupported":
        return "uncertain", "", review
    if sufficient is not None and sufficient <= no:
        return "uncertain", "insufficient evidence", review

    ambiguous = any(
        value is not None and no < value < yes
        for value in (support, contradict, sufficient)
    )
    if ambiguous:
        review = True
    return "uncertain", "", review


def _reason(
    dims: dict,
    note: str,
    sources_sufficient: float | None,
    faithful_overall: float | None,
    *,
    confidence: float | None = None,
    review: bool = False,
) -> str:
    parts = []
    if "verdict" in dims:
        parts.append(f"verdict={dims['verdict']}")
    if "support" in dims:
        parts.append(f"P(support)={dims['support']:.2f}")
    if "contradict" in dims:
        parts.append(f"P(contradict)={dims['contradict']:.2f}")
    if "sufficient" in dims:
        parts.append(f"P(sufficient)={dims['sufficient']:.2f}")
    if "subjective" in dims:
        parts.append(f"P(subjective)={dims['subjective']:.2f}")
    if "severity" in dims:
        parts.append(f"severity={dims['severity']:.0f}")
    if confidence is not None:
        parts.append(f"confidence={confidence:.2f}")
    if sources_sufficient is not None:
        parts.append(f"P(sources_sufficient)={sources_sufficient:.2f}")
    if faithful_overall is not None:
        parts.append(f"P(faithful_overall)={faithful_overall:.2f}")
    reason = "TypeSafe " + " ".join(parts) if parts else "TypeSafe"
    if note:
        reason += " — " + note
    if review:
        reason += " — review recommended"
    return reason


def _compose(
    plan: dict,
    answers: dict,
    yes: float,
    no: float,
    src_hint: str,
) -> list[dict]:
    sources_sufficient = _noul_value(answers, "g_sources_sufficient")
    faithful_overall = _noul_value(answers, "g_faithful_overall")
    insufficient = sources_sufficient is not None and sources_sufficient <= no
    min_confidence = _env_float(
        "CONTEXTCUT_TYPESAFE_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE
    )

    by_claim: dict[str, list[tuple[str, dict]]] = {}
    for qid, meta in plan["questions"].items():
        cid = meta["claim_id"]
        if cid is None:
            continue
        by_claim.setdefault(cid, []).append((qid, meta))

    results: list[dict] = []
    for cid, claim_meta in plan["claims"].items():
        dims: dict = {}
        confidences: dict = {}
        probabilities: dict = {}
        for qid, meta in by_claim.get(cid, []):
            answer = _answer_meta(answers, qid, meta["kind"])
            if answer["value"] is None:
                continue
            dims[meta["dim"]] = answer["value"]
            if answer["confidence"] is not None:
                confidences[meta["dim"]] = answer["confidence"]
            if answer["probabilities"] is not None:
                probabilities[meta["dim"]] = answer["probabilities"]

        claim = claim_meta["text"]
        if not dims:
            results.append(
                {
                    "text": claim,
                    "claim_id": cid,
                    "factual": "uncertain",
                    "reason": "TypeSafe: no answer returned",
                    "source_url": src_hint,
                    "backend": "typesafe",
                }
            )
            continue

        factual, note, review = _decide(
            dims,
            yes,
            no,
            insufficient,
            confidences=confidences,
            min_confidence=min_confidence,
        )
        support = dims.get("support")
        contradict = dims.get("contradict")
        legacy_noul = (
            support if support is not None else (contradict if contradict is not None else 0.0)
        )
        confidence = confidences.get("verdict")
        if confidence is None:
            confidence = confidences.get("severity")
        entry = {
            "text": claim,
            "claim_id": cid,
            "factual": factual,
            "reason": _reason(
                dims,
                note,
                sources_sufficient,
                faithful_overall,
                confidence=confidence,
                review=review,
            ),
            "noul": legacy_noul,
            "source_url": src_hint,
            "backend": "typesafe",
            "dimensions": dict(dims),
            "review": review,
        }
        if confidence is not None:
            entry["confidence"] = confidence
        if probabilities:
            entry["probabilities"] = probabilities
        if support is not None:
            entry["noul_support"] = support
        if contradict is not None:
            entry["noul_contradict"] = contradict
        results.append(entry)
    return results

def _log_usage(
    data: dict, body: dict, usage: dict, sources: str, claims_count: int = 0
) -> None:
    input_tokens = usage.get("input_tokens")
    estimated_usd = (
        (input_tokens or 0) * USD_PER_MTOK / 1_000_000
        if isinstance(input_tokens, (int, float))
        else 0.0
    )
    state_chars = len(json.dumps(body["state"], ensure_ascii=False))
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] [TypeSafe] "
        f"model={data.get('model', '?')} claims={claims_count} "
        f"questions={len(body['questions'])} "
        f"state_chars={state_chars} source_chars={len(sources or '')} "
        f"input_tokens={input_tokens if input_tokens is not None else '?'} "
        f"est_usd=${estimated_usd:.6f}",
        flush=True,
    )


def _post_with_retries(url: str, headers: dict, body: dict, timeout: float):
    """POST with retry/backoff for TypeSafe rate limits (HTTP 429)."""
    retries = max(0, _env_int("CONTEXTCUT_TYPESAFE_MAX_RETRIES", DEFAULT_MAX_RETRIES))
    backoff = max(
        0.0, _env_float("CONTEXTCUT_TYPESAFE_RETRY_BACKOFF", DEFAULT_RETRY_BACKOFF)
    )
    for attempt in range(retries + 1):
        resp = requests.post(url, headers=headers, json=body, timeout=timeout)
        if getattr(resp, "status_code", None) == 429 and attempt < retries:
            wait = backoff * (attempt + 1)
            try:
                retry_after = resp.headers.get("retry-after")
                if retry_after is not None:
                    wait = float(retry_after)
            except Exception:
                pass
            time.sleep(min(30.0, max(0.0, wait)))
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("TypeSafe request retries exhausted")


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
    if not has_evidence(sources):
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] [TypeSafe] "
            f"no usable evidence ({len((sources or '').strip())} chars); "
            "returning uncertain without an API call",
            flush=True,
        )
        return _no_evidence_results(claims)

    body, plan = build_request(claims, sources, model=model)
    key = _cache_key(body)
    answers = _cache_get(key)

    if answers is not None:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] [TypeSafe] cache hit "
            f"(claims={len(claims)}, questions={len(body['questions'])})",
            flush=True,
        )
    else:
        api_key = _env("TYPESAFE_API_KEY")
        timeout_s = timeout if timeout is not None else _env_float(
            "CONTEXTCUT_TYPESAFE_TIMEOUT", DEFAULT_TIMEOUT
        )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if _env_flag("CONTEXTCUT_TYPESAFE_LONG_CONTEXT"):
            headers["TypeSafe-Danger-Zone-Long-Context"] = "true"
        try:
            data = _post_with_retries(API_URL, headers, body, timeout_s)
        except Exception as exc:  # network, HTTP, JSON, timeout
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] [TypeSafe] request failed: {exc}",
                flush=True,
            )
            return _error_results(claims, str(exc))

        answers = data.get("answers") or {}
        usage = data.get("usage") or {}
        _cache_put(key, answers)
        _log_usage(data, body, usage, sources, len(claims))

    yes, no = thresholds()
    return _compose(plan, answers, yes, no, _source_hint(sources))
