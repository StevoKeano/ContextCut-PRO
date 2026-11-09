"""Tests for the TypeSafe (Jev) claim verifier.

All HTTP is mocked; no network or API key is required. Live calls belong in
``test_integration.py`` behind the ``--live`` flag.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def typesafe_env(monkeypatch):
    """Enable the typesafe backend with deterministic settings."""
    monkeypatch.setenv("CONTEXTCUT_SCAN_BACKEND", "typesafe")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("CONTEXTCUT_TYPESAFE_MODEL", "jev-latest")
    monkeypatch.setenv("CONTEXTCUT_TYPESAFE_TIMEOUT", "5")
    monkeypatch.setenv("CONTEXTCUT_TYPESAFE_YES", "0.7")
    monkeypatch.setenv("CONTEXTCUT_TYPESAFE_NO", "0.3")
    monkeypatch.setenv("CONTEXTCUT_TYPESAFE_MAX_SOURCES", "28000")
    return monkeypatch


def _fake_response(payload, status_ok=True):
    resp = MagicMock()
    resp.json.return_value = payload
    if status_ok:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = Exception("HTTP 500")
    return resp


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


def test_build_request_batches_claims(typesafe_env):
    import typesafe_scan

    claims = ["Paris is in France.", "The sky is green."]
    body = typesafe_scan.build_request(claims, "SOURCE TEXT")

    assert body["model"] == "jev-latest"
    assert body["state"] == {"sources": "SOURCE TEXT"}
    assert set(body["questions"]) == {"claim_0", "claim_1"}
    assert body["questions"]["claim_0"]["type"] == "noul"
    assert "Paris is in France." in body["questions"]["claim_0"]["instructions"]


def test_build_request_truncates_sources(typesafe_env):
    typesafe_env.setenv("CONTEXTCUT_TYPESAFE_MAX_SOURCES", "10")
    import typesafe_scan

    body = typesafe_scan.build_request(["A claim here."], "x" * 100)
    assert body["state"]["sources"] == "x" * 10


def test_split_claims_keeps_sentences():
    import typesafe_scan

    claims = typesafe_scan.split_claims(
        "First claim is here. Second one is too! Is it really?"
    )
    assert claims == ["First claim is here.", "Second one is too!", "Is it really?"]


# ── verification + threshold mapping ─────────────────────────────────────────


def test_verify_claims_threshold_mapping(typesafe_env):
    import typesafe_scan

    payload = {
        "model": "jev-1.14.0",
        "answers": {
            "claim_0": {"type": "noul", "noul": 0.9},
            "claim_1": {"type": "noul", "noul": 0.1},
            "claim_2": {"type": "noul", "noul": 0.5},
        },
        "usage": {"input_tokens": 42, "output_tokens": 3},
    }
    with patch("typesafe_scan.requests.post", return_value=_fake_response(payload)) as post:
        results = typesafe_scan.verify_claims(
            ["a claim", "b claim", "c claim"], "evidence http://example.com/doc"
        )

    assert [r["factual"] for r in results] == ["correct", "incorrect", "uncertain"]
    assert all(r["backend"] == "typesafe" for r in results)
    assert results[0]["source_url"] == "http://example.com/doc"
    post.assert_called_once()
    _, kwargs = post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"


def test_verify_claims_http_error_is_uncertain_not_correct(typesafe_env):
    import typesafe_scan

    with patch(
        "typesafe_scan.requests.post", return_value=_fake_response({}, status_ok=False)
    ):
        results = typesafe_scan.verify_claims(["claim"], "evidence")

    assert len(results) == 1
    assert results[0]["factual"] == "uncertain"
    assert "TypeSafe error" in results[0]["reason"]


def test_verify_claims_network_exception_is_uncertain(typesafe_env):
    import typesafe_scan

    with patch("typesafe_scan.requests.post", side_effect=TimeoutError("boom")):
        results = typesafe_scan.verify_claims(["claim"], "evidence")

    assert results[0]["factual"] == "uncertain"
    assert "boom" in results[0]["reason"]


def test_verify_claims_without_sources_skips_http(typesafe_env):
    import typesafe_scan

    with patch("typesafe_scan.requests.post") as post:
        results = typesafe_scan.verify_claims(["claim"], "")

    assert results[0]["factual"] == "uncertain"
    assert "no evidence" in results[0]["reason"].lower()
    post.assert_not_called()


def test_verify_claims_missing_answer_is_uncertain(typesafe_env):
    import typesafe_scan

    payload = {"model": "jev-1.14.0", "answers": {}, "usage": {}}
    with patch("typesafe_scan.requests.post", return_value=_fake_response(payload)):
        results = typesafe_scan.verify_claims(["claim"], "evidence")

    assert results[0]["factual"] == "uncertain"
    assert "no answer" in results[0]["reason"].lower()


# ── agent_handler integration ────────────────────────────────────────────────


def test_typesafe_scan_text_attaches_offsets(typesafe_env):
    import agent_handler

    text = "Paris is in France. The sky is green."
    payload = {
        "model": "jev-1.14.0",
        "answers": {
            "claim_0": {"type": "noul", "noul": 0.95},
            "claim_1": {"type": "noul", "noul": 0.05},
        },
        "usage": {},
    }
    with patch("typesafe_scan.requests.post", return_value=_fake_response(payload)):
        results = agent_handler._typesafe_scan_text(text, "evidence")

    assert results is not None
    assert results[0]["start"] == 0
    assert results[1]["start"] == text.index("The sky")


def test_confidence_scan_uses_typesafe_when_enabled(typesafe_env):
    import agent_handler

    payload = {
        "model": "jev-1.14.0",
        "answers": {"claim_0": {"type": "noul", "noul": 0.9}},
        "usage": {},
    }
    with patch("typesafe_scan.requests.post", return_value=_fake_response(payload)), patch(
        "agent_handler.ChatOpenAI"
    ) as fake_llm:
        result = agent_handler._confidence_scan(
            "Paris is in France.",
            upstream="http://localhost:11434",
            detailed=True,
            kb_context="Paris is the capital of France.",
        )

    assert result[0]["factual"] == "correct"
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
