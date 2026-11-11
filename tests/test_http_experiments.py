"""HTTP tests for the AEO experiments dashboard/API."""

from __future__ import annotations

import json

import pytest


QUERIES = [f"query {index}" for index in range(20)]
ORIGINAL = "# HTTP Test\n\nBody.\n"


@pytest.fixture
def experiment_env(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "CONTEXTCUT_EXPERIMENT_DB", str(tmp_path / "experiments.db")
    )
    monkeypatch.setenv(
        "CONTEXTCUT_EXPERIMENT_ARTIFACTS", str(tmp_path / "artifacts")
    )
    content = tmp_path / "content"
    content.mkdir()
    (content / "index.md").write_text(ORIGINAL, encoding="utf-8")
    return tmp_path, content


def _json(response):
    raw = response[1]
    _, separator, payload = raw.partition(b"\r\n\r\n")
    if separator:
        raw = payload
    return json.loads(raw.decode("utf-8"))


def test_experiments_page_renders(make_handler, experiment_env):
    status, body = make_handler("/experiments")

    assert status == 200
    assert b"AEO Experiments" in body
    assert b"/api/experiments" in body


def test_experiment_api_lifecycle(make_handler, experiment_env):
    tmp_path, content = experiment_env
    payload = {
        "objective": "Improve citations",
        "site": "example.com",
        "page": "index.md",
        "content_root": str(content),
        "queries": QUERIES,
        "scenario": "improved",
        "min_lift": 0.05,
        "max_steps": 12,
    }

    status, body = make_handler(
        "/api/experiments",
        "POST",
        json.dumps(payload).encode("utf-8"),
    )
    assert status == 201
    created = _json((status, body))["experiment"]
    assert created["state"] == "PENDING_APPROVAL"
    assert created["status"] == "pending"
    assert content.joinpath("index.md").read_text(encoding="utf-8") == ORIGINAL

    status, body = make_handler("/api/experiments?limit=10")
    assert status == 200
    listing = _json((status, body))
    assert len(listing["experiments"]) == 1
    assert listing["experiments"][0]["id"] == created["id"]

    status, body = make_handler("/api/approvals?status=pending")
    assert status == 200
    approvals = _json((status, body))["approvals"]
    assert len(approvals) == 1
    assert approvals[0]["experiment_id"] == created["id"]

    status, body = make_handler(f"/api/experiments/{created['id']}")
    assert status == 200
    detail = _json((status, body))["experiment"]
    assert detail["approval"]["status"] == "pending"
    assert "## Direct Answer" in detail["approval"]["payload"]["diff"]

    status, body = make_handler(
        f"/api/experiments/{created['id']}/approve",
        "POST",
        json.dumps({"decision": "approve", "message": "ok"}).encode("utf-8"),
    )
    assert status == 200
    completed = _json((status, body))["experiment"]
    assert completed["state"] == "COMPLETED"
    assert completed["decision"] == "win"
    assert completed["result"]["evaluation"]["delta"] == pytest.approx(0.3)
    assert "## FAQ" in content.joinpath("index.md").read_text(encoding="utf-8")

    status, body = make_handler("/api/approvals?status=pending")
    assert status == 200
    assert _json((status, body))["approvals"] == []


def test_experiment_api_rejects_missing_content_root(make_handler, experiment_env):
    status, body = make_handler(
        "/api/experiments",
        "POST",
        json.dumps(
            {
                "objective": "No content root",
                "site": "example.com",
                "page": "index.md",
                "queries": ["q"],
            }
        ).encode("utf-8"),
    )

    assert status == 400
    assert "content_root" in _json((status, body))["error"]


def test_experiment_api_reject_decision(make_handler, experiment_env):
    tmp_path, content = experiment_env
    status, body = make_handler(
        "/api/experiments",
        "POST",
        json.dumps(
            {
                "objective": "Reject via API",
                "site": "example.com",
                "page": "index.md",
                "content_root": str(content),
                "queries": QUERIES,
            }
        ).encode("utf-8"),
    )
    experiment = _json((status, body))["experiment"]

    status, body = make_handler(
        f"/api/experiments/{experiment['id']}/approve",
        "POST",
        json.dumps({"decision": "reject", "message": "no"}).encode("utf-8"),
    )

    assert status == 200
    rejected = _json((status, body))["experiment"]
    assert rejected["state"] == "FAILED"
    assert content.joinpath("index.md").read_text(encoding="utf-8") == ORIGINAL
