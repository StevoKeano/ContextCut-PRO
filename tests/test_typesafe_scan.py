"""Tests for the TypeSafe (Jev) claim verifier.

All HTTP is mocked; no network or API key is required. Live calls belong in
``test_integration.py`` behind the ``--live`` flag.
"""

from unittest.mock import MagicMock, patch

import pytest

# Comfortably above CONTEXTCUT_TYPESAFE_MIN_SOURCES (80).
EVIDENCE = "Reference evidence text with enough detail to be usable. " * 4


@pytest.fixture
def typesafe_env(monkeypatch):
    """Enable the typesafe backend with deterministic settings."""
    monkeypatch.setenv("CONTEXTCUT_SCAN_BACKEND", "typesafe")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("CONTEXTCUT_TYPESAFE_MODEL", "jev-latest")
    monkeypatch.setenv("CONTEXTCUT_TYPESAFE_TIMEOUT", "5")
    monkeypatch.setenv("CONTEXTCUT_TYPESAFE_YES", "0.7")
    monkeypatch.setenv("CONTEXTCUT_TYPESAFE_NO", "0.3")
    monkeypatch.setenv("CONTEXTCUT_TYPESAFE_MIN_SOURCES", "80")
    monkeypatch.setenv("CONTEXTCUT_TYPESAFE_MAX_SOURCES", "28000")
    # Caching off by default so tests never see each other's answers.
    monkeypatch.setenv("CONTEXTCUT_TYPESAFE_CACHE_TTL", "0")

    import typesafe_scan

    typesafe_scan.clear_cache()
    yield monkeypatch
    typesafe_scan.clear_cache()


def _fake_response(payload, status_ok=True):
    resp = MagicMock()
    resp.json.return_value = payload
    if status_ok:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = Exception("HTTP 500")
    return resp


def _noul(value):
    return {"type": "noul", "noul": value}


def _choice(value):
    return {"type": "choice", "choice": value}


def _score(value):
    return {"type": "score", "score": value}


def _claim_ids(count):
    return [f"c{i:03d}" for i in range(count)]


def _answers(claim_id, **dims):
    """Build an answers dict for one claim's dimensions."""
    kinds = {"verdict": _choice, "severity": _score}
    return {f"{claim_id}_{dim}": kinds.get(dim, _noul)(value) for dim, value in dims.items()}


# ── configuration ────────────────────────────────────────────────────────────


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CONTEXTCUT_SCAN_BACKEND", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    import typesafe_scan

    assert typesafe_scan.is_enabled() is False


def test_requires_key_even_when_backend_selected(typesafe_env):
    typesafe_env.delenv("TYPESAFE_API_KEY", raising=False)
    import typesafe_scan

    assert typesafe_scan.is_enabled() is False


def test_enabled_with_backend_and_key(typesafe_env):
    import typesafe_scan

    assert typesafe_scan.is_enabled() is True


# ── request construction ─────────────────────────────────────────────────────


def test_build_request_state_holds_shared_sources_only(typesafe_env):
    import typesafe_scan

    claims = ["Paris is in France.", "The sky is green."]
    body, plan = typesafe_scan.build_request(claims, "SOURCE TEXT")

    assert body["model"] == "jev-latest"
    assert body["state"] == {"sources": "SOURCE TEXT"}
    assert plan["claims"]["c000"] == {"index": 0, "text": "Paris is in France."}
    assert plan["claims"]["c001"] == {"index": 1, "text": "The sky is green."}


def test_build_request_questions_include_claim_text(typesafe_env):
    import typesafe_scan

    body, plan = typesafe_scan.build_request(["Paris is in France."], "SOURCE TEXT")
    questions = body["questions"]

    # Default dimension bank for one claim + two globals.
    expected = {
        "c000_verdict",
        "c000_support",
        "c000_contradict",
        "c000_sufficient",
        "c000_subjective",
        "c000_severity",
        "g_sources_sufficient",
        "g_faithful_overall",
    }
    assert set(questions) == expected
    assert questions["c000_verdict"]["type"] == "choice"
    assert questions["c000_severity"]["type"] == "score"
    assert questions["c000_support"]["type"] == "noul"
    # Per TypeSafe guidance, name the claim directly instead of an ID lookup.
    assert "Paris is in France." in questions["c000_support"]["instructions"]
    assert "c000" not in questions["c000_support"]["instructions"]
    assert plan["questions"]["c000_support"] == {
        "claim_id": "c000",
        "dim": "support",
        "kind": "noul",
    }


def test_build_request_truncates_sources(typesafe_env):
    typesafe_env.setenv("CONTEXTCUT_TYPESAFE_MAX_SOURCES", "10")
    import typesafe_scan

    body, _ = typesafe_scan.build_request(["A claim here."], "x" * 100)
    assert body["state"]["sources"] == "x" * 10


def test_build_request_redacts_special_tokens(typesafe_env):
    import typesafe_scan

    body, plan = typesafe_scan.build_request(
        ["Claim with <|im_start|>token"],
        "SOURCE <|im_start|>system<|im_end|> text",
    )
    assert "<|im_start|>" not in body["state"]["sources"]
    assert "[TAG_REDACTED]" in body["state"]["sources"]
    assert "<|im_start|>" not in body["questions"]["c000_support"]["instructions"]
    # The plan keeps the original claim text for display/result mapping.
    assert plan["claims"]["c000"]["text"] == "Claim with <|im_start|>token"


def test_build_request_redacts_secrets_before_cloud(typesafe_env):
    import typesafe_scan

    secret = "sk-abcdefghijklmnopqrstuvwxyz012345"
    body, _ = typesafe_scan.build_request(
        [f"Use token {secret} to call the API."],
        f"Evidence includes {secret} and a password.",
    )
    serialized = str(body)
    assert secret not in serialized
    assert "[REDACTED" in serialized or "REDACTED" in serialized


def test_build_request_conditional_dimensions(typesafe_env):
    typesafe_env.setenv(
        "CONTEXTCUT_TYPESAFE_DIMENSIONS", "support,numeric,entity,temporal"
    )
    import typesafe_scan

    body, plan = typesafe_scan.build_request(
        [
            "In 2024, Paris had 2.1 million residents.",
            "Bananas are tasty and yellow.",
        ],
        "SOURCE TEXT",
    )
    questions = body["questions"]

    assert "c000_numeric" in questions
    assert "c000_temporal" in questions
    assert "c000_entity" in questions
    assert "c001_numeric" not in questions
    assert "c001_temporal" not in questions
    assert plan["questions"]["c000_numeric"]["dim"] == "numeric"


def test_build_request_custom_globals(typesafe_env):
    typesafe_env.setenv("CONTEXTCUT_TYPESAFE_GLOBALS", "source_quality")
    import typesafe_scan

    body, _ = typesafe_scan.build_request(["A claim here."], "SOURCE TEXT")

    assert "g_source_quality" in body["questions"]
    assert "g_sources_sufficient" not in body["questions"]
    assert body["questions"]["g_source_quality"]["type"] == "score"


def test_build_request_respects_max_questions(typesafe_env):
    typesafe_env.setenv("CONTEXTCUT_TYPESAFE_MAX_QUESTIONS", "2")
    import typesafe_scan

    body, _ = typesafe_scan.build_request(["A claim here."], "SOURCE TEXT")

    assert len(body["questions"]) == 2
    # Core questions are prioritized over optional/global ones.
    assert all(qid.startswith("c000_") for qid in body["questions"])


def test_build_request_budget_drops_optional_not_core(typesafe_env):
    # A token budget so small that only priority-0 (core) questions survive.
    typesafe_env.setenv("CONTEXTCUT_TYPESAFE_MAX_REQUEST_TOKENS", "1")
    import typesafe_scan

    body, _ = typesafe_scan.build_request(["A claim here."], "SOURCE TEXT")

    assert set(body["questions"]) == {
        "c000_verdict",
        "c000_support",
        "c000_contradict",
        "c000_sufficient",
    }


def test_split_claims_keeps_sentences():
    import typesafe_scan

    claims = typesafe_scan.split_claims(
        "First claim is here. Second one is too! Is it really?"
    )
    assert claims == ["First claim is here.", "Second one is too!", "Is it really?"]


# ── evidence gate ────────────────────────────────────────────────────────────


def test_has_evidence_rejects_empty_sentinel_and_short(typesafe_env):
    import typesafe_scan

    assert typesafe_scan.has_evidence("") is False
    assert typesafe_scan.has_evidence("   ") is False
    assert typesafe_scan.has_evidence("No relevant context found.") is False
    assert typesafe_scan.has_evidence("No relevant context found") is False
    assert typesafe_scan.has_evidence("tiny") is False
    assert typesafe_scan.has_evidence(EVIDENCE) is True


# ── verdict composition ──────────────────────────────────────────────────────


def test_verify_claims_verdict_mapping(typesafe_env):
    import typesafe_scan

    payload = {
        "model": "jev-1.14.0",
        "answers": {
            **_answers("c000", verdict="correct"),
            **_answers("c001", verdict="incorrect"),
            **_answers("c002", verdict="unsupported"),
            **_answers("c003", verdict="opinion"),
            "g_sources_sufficient": _noul(0.9),
            "g_faithful_overall": _noul(0.5),
        },
        "usage": {"input_tokens": 42, "output_tokens": 3},
    }
    with patch(
        "typesafe_scan.requests.post", return_value=_fake_response(payload)
    ) as post:
        results = typesafe_scan.verify_claims(
            ["a claim", "b claim", "c claim", "d claim"],
            EVIDENCE + " http://example.com/doc",
        )

    assert [r["factual"] for r in results] == [
        "correct",
        "incorrect",
        "uncertain",
        "correct",
    ]
    assert all(r["backend"] == "typesafe" for r in results)
    assert results[3]["reason"].endswith("subjective/opinion (not fact-checked)")
    assert "verdict=unsupported" in results[2]["reason"]
    assert results[0]["source_url"] == "http://example.com/doc"
    assert [r["claim_id"] for r in results] == ["c000", "c001", "c002", "c003"]
    post.assert_called_once()
    _, kwargs = post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert len(kwargs["json"]["questions"]) == 26


def test_verify_claims_support_scores_compose(typesafe_env):
    import typesafe_scan

    payload = {
        "model": "jev-1.14.0",
        "answers": {
            **_answers("c000", support=0.9, contradict=0.05),
            **_answers("c001", support=0.05, contradict=0.9),
            **_answers("c002", support=0.1),
            "g_sources_sufficient": _noul(0.8),
        },
        "usage": {},
    }
    with patch("typesafe_scan.requests.post", return_value=_fake_response(payload)):
        results = typesafe_scan.verify_claims(
            ["a claim", "b claim", "c claim"], EVIDENCE
        )

    assert [r["factual"] for r in results] == ["correct", "incorrect", "uncertain"]
    assert results[0]["noul_support"] == 0.9
    assert results[0]["noul_contradict"] == 0.05
    assert results[1]["noul_contradict"] == 0.9
    assert "P(support)" in results[2]["reason"]


def test_verify_claims_low_support_only_is_uncertain_not_incorrect(typesafe_env):
    """Missing contradiction answers must never be reported as "incorrect"."""
    import typesafe_scan

    payload = {
        "model": "jev-1.14.0",
        "answers": {**_answers("c000", support=0.1)},
        "usage": {},
    }
    with patch("typesafe_scan.requests.post", return_value=_fake_response(payload)):
        results = typesafe_scan.verify_claims(["claim"], EVIDENCE)

    assert results[0]["factual"] == "uncertain"


def test_verify_claims_contradiction_only_high_is_incorrect(typesafe_env):
    import typesafe_scan

    payload = {
        "model": "jev-1.14.0",
        "answers": {**_answers("c000", contradict=0.9)},
        "usage": {},
    }
    with patch("typesafe_scan.requests.post", return_value=_fake_response(payload)):
        results = typesafe_scan.verify_claims(["claim"], EVIDENCE)

    assert results[0]["factual"] == "incorrect"


def test_verify_claims_global_insufficiency_vetoes(typesafe_env):
    import typesafe_scan

    payload = {
        "model": "jev-1.14.0",
        "answers": {
            **_answers("c000", verdict="correct"),
            "g_sources_sufficient": _noul(0.1),
        },
        "usage": {},
    }
    with patch("typesafe_scan.requests.post", return_value=_fake_response(payload)):
        results = typesafe_scan.verify_claims(["claim"], EVIDENCE)

    assert results[0]["factual"] == "uncertain"
    assert "insufficient evidence" in results[0]["reason"]


def test_verify_claims_per_claim_sufficiency_overrides_global_pessimism(typesafe_env):
    import typesafe_scan

    payload = {
        "model": "jev-1.14.0",
        "answers": {
            **_answers("c000", verdict="correct", sufficient=0.99),
            **_answers("c001", verdict="incorrect", sufficient=0.96),
            "g_sources_sufficient": _noul(0.3),
        },
        "usage": {},
    }
    with patch("typesafe_scan.requests.post", return_value=_fake_response(payload)):
        results = typesafe_scan.verify_claims(["a claim", "b claim"], EVIDENCE)

    assert [r["factual"] for r in results] == ["correct", "incorrect"]
    assert all("insufficient evidence" not in r["reason"] for r in results)


def test_verify_claims_severity_score_is_surfaced(typesafe_env):
    import typesafe_scan

    payload = {
        "model": "jev-1.14.0",
        "answers": {
            **_answers("c000", verdict="correct", severity=2),
            "g_sources_sufficient": _noul(0.9),
        },
        "usage": {},
    }
    with patch("typesafe_scan.requests.post", return_value=_fake_response(payload)):
        results = typesafe_scan.verify_claims(["claim"], EVIDENCE)

    assert results[0]["factual"] == "correct"
    assert results[0]["dimensions"]["severity"] == 2.0
    assert "severity=2" in results[0]["reason"]


def test_verify_claims_http_error_is_uncertain_not_correct(typesafe_env):
    import typesafe_scan

    with patch(
        "typesafe_scan.requests.post", return_value=_fake_response({}, status_ok=False)
    ):
        results = typesafe_scan.verify_claims(["claim"], EVIDENCE)

    assert len(results) == 1
    assert results[0]["factual"] == "uncertain"
    assert "TypeSafe error" in results[0]["reason"]


def test_verify_claims_network_exception_is_uncertain(typesafe_env):
    import typesafe_scan

    with patch("typesafe_scan.requests.post", side_effect=TimeoutError("boom")):
        results = typesafe_scan.verify_claims(["claim"], EVIDENCE)

    assert results[0]["factual"] == "uncertain"
    assert "boom" in results[0]["reason"]


@pytest.mark.parametrize("sources", ["", "   ", "No relevant context found.", "tiny"])
def test_verify_claims_without_usable_evidence_skips_http(typesafe_env, sources):
    import typesafe_scan

    with patch("typesafe_scan.requests.post") as post:
        results = typesafe_scan.verify_claims(["claim"], sources)

    assert results[0]["factual"] == "uncertain"
    assert "no evidence" in results[0]["reason"].lower()
    post.assert_not_called()


def test_verify_claims_missing_answer_is_uncertain(typesafe_env):
    import typesafe_scan

    payload = {"model": "jev-1.14.0", "answers": {}, "usage": {}}
    with patch("typesafe_scan.requests.post", return_value=_fake_response(payload)):
        results = typesafe_scan.verify_claims(["claim"], EVIDENCE)

    assert results[0]["factual"] == "uncertain"
    assert "no answer" in results[0]["reason"].lower()


def test_verify_claims_low_confidence_verdict_requires_review(typesafe_env):
    import typesafe_scan

    payload = {
        "model": "jev-1.14.0",
        "answers": {
            "c000_verdict": {
                "type": "choice",
                "choice": "correct",
                "confidence": 0.4,
                "probabilities": {"correct": 0.4, "incorrect": 0.35},
            },
            "g_sources_sufficient": _noul(0.9),
        },
        "usage": {},
    }
    with patch("typesafe_scan.requests.post", return_value=_fake_response(payload)):
        results = typesafe_scan.verify_claims(["claim"], EVIDENCE)

    # Low confidence is not trusted for the decision, so it cannot prove support.
    assert results[0]["factual"] == "uncertain"
    assert results[0]["review"] is True
    assert results[0]["confidence"] == 0.4
    assert results[0]["probabilities"]["verdict"]["correct"] == 0.4
    assert "review recommended" in results[0]["reason"]


def test_verify_claims_low_confidence_verdict_ignored_but_score_decides(typesafe_env):
    import typesafe_scan

    payload = {
        "model": "jev-1.14.0",
        "answers": {
            "c000_verdict": {
                "type": "choice",
                "choice": "incorrect",
                "confidence": 0.3,
            },
            "c000_support": _noul(0.9),
            "c000_contradict": _noul(0.05),
            "g_sources_sufficient": _noul(0.9),
        },
        "usage": {},
    }
    with patch("typesafe_scan.requests.post", return_value=_fake_response(payload)):
        results = typesafe_scan.verify_claims(["claim"], EVIDENCE)

    assert results[0]["factual"] == "correct"
    assert results[0]["review"] is True


def test_verify_claims_high_confidence_choice_is_trusted(typesafe_env):
    import typesafe_scan

    payload = {
        "model": "jev-1.14.0",
        "answers": {
            "c000_verdict": {
                "type": "choice",
                "choice": "incorrect",
                "confidence": 0.95,
                "probabilities": {"incorrect": 0.95, "correct": 0.05},
            },
            "g_sources_sufficient": _noul(0.9),
        },
        "usage": {},
    }
    with patch("typesafe_scan.requests.post", return_value=_fake_response(payload)):
        results = typesafe_scan.verify_claims(["claim"], EVIDENCE)

    assert results[0]["factual"] == "incorrect"
    assert results[0]["review"] is False
    assert results[0]["confidence"] == 0.95


def test_verify_claims_retries_429(typesafe_env):
    typesafe_env.setenv("CONTEXTCUT_TYPESAFE_MAX_RETRIES", "2")
    typesafe_env.setenv("CONTEXTCUT_TYPESAFE_RETRY_BACKOFF", "0")
    import typesafe_scan

    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.headers = {"retry-after": "0"}
    payload = {
        "model": "jev-1.14.0",
        "answers": {
            **_answers("c000", verdict="correct"),
            "g_sources_sufficient": _noul(0.9),
        },
        "usage": {},
    }
    ok = _fake_response(payload)
    ok.status_code = 200

    with patch(
        "typesafe_scan.requests.post", side_effect=[rate_limited, ok]
    ) as post:
        results = typesafe_scan.verify_claims(["claim"], EVIDENCE)

    assert post.call_count == 2
    assert results[0]["factual"] == "correct"


# ── caching ──────────────────────────────────────────────────────────────────


def test_cache_hit_skips_second_request(typesafe_env):
    typesafe_env.setenv("CONTEXTCUT_TYPESAFE_CACHE_TTL", "900")
    import typesafe_scan

    payload = {
        "model": "jev-1.14.0",
        "answers": {
            **_answers("c000", verdict="correct"),
            "g_sources_sufficient": _noul(0.9),
        },
        "usage": {},
    }
    with patch(
        "typesafe_scan.requests.post", return_value=_fake_response(payload)
    ) as post:
        first = typesafe_scan.verify_claims(["claim"], EVIDENCE)
        second = typesafe_scan.verify_claims(["claim"], EVIDENCE)

    assert post.call_count == 1
    assert [r["factual"] for r in first] == [r["factual"] for r in second]
    assert second[0]["factual"] == "correct"


def test_cache_disabled_with_zero_ttl(typesafe_env):
    typesafe_env.setenv("CONTEXTCUT_TYPESAFE_CACHE_TTL", "0")
    import typesafe_scan

    payload = {
        "model": "jev-1.14.0",
        "answers": {**_answers("c000", verdict="correct")},
        "usage": {},
    }
    with patch(
        "typesafe_scan.requests.post", return_value=_fake_response(payload)
    ) as post:
        typesafe_scan.verify_claims(["claim"], EVIDENCE)
        typesafe_scan.verify_claims(["claim"], EVIDENCE)

    assert post.call_count == 2


# ── agent_handler integration ────────────────────────────────────────────────


def test_typesafe_scan_text_attaches_offsets(typesafe_env):
    import agent_handler

    text = "Paris is in France. The sky is green."
    payload = {
        "model": "jev-1.14.0",
        "answers": {
            **_answers("c000", verdict="correct"),
            **_answers("c001", verdict="incorrect"),
            "g_sources_sufficient": _noul(0.9),
        },
        "usage": {},
    }
    with patch("typesafe_scan.requests.post", return_value=_fake_response(payload)):
        results = agent_handler._typesafe_scan_text(text, EVIDENCE)

    assert results is not None
    assert results[0]["start"] == 0
    assert results[1]["start"] == text.index("The sky")
    assert results[0]["factual"] == "correct"
    assert results[1]["factual"] == "incorrect"


def test_confidence_scan_uses_typesafe_when_enabled(typesafe_env):
    import agent_handler

    payload = {
        "model": "jev-1.14.0",
        "answers": {
            **_answers("c000", verdict="correct"),
            "g_sources_sufficient": _noul(0.9),
        },
        "usage": {},
    }
    with patch(
        "typesafe_scan.requests.post", return_value=_fake_response(payload)
    ), patch("agent_handler.ChatOpenAI") as fake_llm:
        result = agent_handler._confidence_scan(
            "Paris is in France.",
            upstream="http://localhost:11434",
            detailed=True,
            kb_context=EVIDENCE,
        )

    assert result[0]["factual"] == "correct"
    fake_llm.assert_not_called()


def test_confidence_scan_typesafe_without_evidence_is_uncertain_no_calls(typesafe_env):
    import agent_handler

    with patch("typesafe_scan.requests.post") as post, patch(
        "agent_handler.ChatOpenAI"
    ) as fake_llm:
        result = agent_handler._confidence_scan(
            "Paris is in France.",
            upstream="http://localhost:11434",
            detailed=True,
            kb_context="",
        )

    assert result[0]["factual"] == "uncertain"
    assert "no evidence" in result[0]["reason"].lower()
    post.assert_not_called()
    fake_llm.assert_not_called()


def test_confidence_scan_falls_back_to_llm_when_backend_llm(monkeypatch):
    monkeypatch.setenv("CONTEXTCUT_SCAN_BACKEND", "llm")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    import agent_handler

    fake_resp = MagicMock()
    fake_resp.content = "HIGH"
    llm_instance = MagicMock()
    llm_instance.invoke.return_value = fake_resp
    with patch("agent_handler.ChatOpenAI", return_value=llm_instance) as fake_llm:
        result = agent_handler._confidence_scan(
            "x" * 120,
            upstream="http://localhost:11434",
            detailed=False,
            kb_context="evidence",
        )

    fake_llm.assert_called_once()
    assert result[0]["confidence"] == "HIGH"
