"""Tests for the persistent AEO experiment ledger."""

from __future__ import annotations

import pytest

from experiment_store import ExperimentStore


def test_create_get_and_detail(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.db")
    experiment = store.create(
        objective="Improve citations",
        site="example.com",
        page="index.md",
        queries=["what is x", "how does x work"],
        target_metric="aeo_citation_rate",
        baseline={"citation_rate": 0.25},
        config={"content_root": str(tmp_path / "content")},
        budget={"max_steps": 8},
    )

    assert experiment["state"] == "DRAFT"
    assert experiment["status"] == "active"
    assert experiment["queries"] == ["what is x", "how does x work"]
    assert experiment["baseline"]["citation_rate"] == 0.25

    detail = store.detail(experiment["id"])
    assert detail["id"] == experiment["id"]
    assert detail["steps"] == []
    assert detail["metrics"] == []
    assert detail["lessons"] == []


def test_update_steps_metrics_and_lessons(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.db")
    experiment = store.create(
        objective="Test",
        site="example.com",
        page="index.md",
        queries=["q"],
        target_metric="aeo_citation_rate",
    )
    experiment_id = experiment["id"]

    updated = store.update(experiment_id, hypothesis={"statement": "test"})
    assert updated["hypothesis"]["statement"] == "test"

    step = store.add_step(
        experiment_id,
        state="HYPOTHESIZED",
        role="hypothesis",
        status="done",
        output_data={"statement": "test"},
    )
    assert step["output"]["statement"] == "test"

    metric = store.add_metric(
        experiment_id,
        name="aeo_citation_rate",
        value=0.5,
        unit="ratio",
        source="mock",
        scenario="baseline",
    )
    assert metric["value"] == 0.5

    lesson = store.add_lesson(
        experiment_id,
        lesson="direct answers help",
        confidence=0.8,
        tags=["aeo"],
    )
    assert lesson["tags"] == ["aeo"]

    detail = store.detail(experiment_id)
    assert len(detail["steps"]) == 1
    assert len(detail["metrics"]) == 1
    assert len(detail["lessons"]) == 1


def test_rejects_unknown_update_field(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.db")
    experiment = store.create(
        objective="Test",
        site="example.com",
        page="index.md",
        queries=["q"],
        target_metric="aeo_citation_rate",
    )

    with pytest.raises(ValueError, match="unknown experiment fields"):
        store.update(experiment["id"], nope=True)


def test_state_derives_status_and_error(tmp_path):
    store = ExperimentStore(tmp_path / "experiments.db")
    experiment = store.create(
        objective="Test",
        site="example.com",
        page="index.md",
        queries=["q"],
        target_metric="aeo_citation_rate",
    )

    pending = store.set_state(experiment["id"], "PENDING_APPROVAL")
    assert pending["status"] == "pending"

    failed = store.set_state(experiment["id"], "FAILED", error="boom")
    assert failed["status"] == "failed"
    assert failed["error"] == "boom"
