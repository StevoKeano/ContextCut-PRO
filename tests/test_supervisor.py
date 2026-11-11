"""End-to-end tests for the deterministic AEO supervisor."""

from __future__ import annotations

import pytest

from supervisor import BudgetExceeded, Supervisor


QUERIES = [f"query {index}" for index in range(20)]
ORIGINAL = "# Test Page\n\nExisting body.\n"


def _workspace(tmp_path):
    content = tmp_path / "content"
    content.mkdir()
    (content / "index.md").write_text(ORIGINAL, encoding="utf-8")
    return content, tmp_path / "published"


def _create(tmp_path, *, scenario="improved", **overrides):
    content, published = _workspace(tmp_path)
    supervisor = Supervisor(
        db_path=tmp_path / "experiments.db",
        artifact_root=tmp_path / "artifacts",
    )
    options = {
        "objective": "Improve AEO citations",
        "site": "example.com",
        "page": "index.md",
        "queries": QUERIES,
        "content_root": content,
        "publish_root": published,
        "variant_scenario": scenario,
    }
    options.update(overrides)
    return supervisor, supervisor.create(**options), content, published


def test_create_stops_for_approval_without_touching_content(tmp_path):
    supervisor, experiment, content, published = _create(tmp_path)

    assert experiment["state"] == "PENDING_APPROVAL"
    assert experiment["status"] == "pending"
    assert experiment["decision"] is None
    assert content.joinpath("index.md").read_text(encoding="utf-8") == ORIGINAL
    assert not published.exists()

    pending = supervisor.approvals.pending(experiment["id"])
    assert len(pending) == 1
    payload = pending[0]["payload"]
    assert payload["experiment_id"] == experiment["id"]
    assert payload["expected_metric"]["baseline"] == 0.35
    assert "## Direct Answer" in payload["diff"]
    assert payload["changed_paths"] == ["index.md"]


def test_approval_completes_win_and_persists(tmp_path):
    supervisor, experiment, content, published = _create(tmp_path)

    resumed = Supervisor(
        db_path=tmp_path / "experiments.db",
        artifact_root=tmp_path / "artifacts",
    )
    completed = resumed.approve(experiment["id"], message="ship it")

    assert completed["state"] == "COMPLETED"
    assert completed["status"] == "completed"
    assert completed["decision"] == "win"
    evaluation = completed["result"]["evaluation"]
    assert evaluation["baseline"] == 0.35
    assert evaluation["variant"] == 0.65
    assert evaluation["delta"] == pytest.approx(0.3)
    assert evaluation["guardrails"]["ok"] is True

    assert "## FAQ" in content.joinpath("index.md").read_text(encoding="utf-8")
    assert published.joinpath("index.md").exists()
    assert len(completed["lessons"]) == 1
    assert completed["lessons"][0]["confidence"] == 0.8

    states = [step["state"] for step in completed["steps"]]
    assert states == [
        "DRAFT",
        "HYPOTHESIZED",
        "PENDING_APPROVAL",
        "APPROVED",
        "OBSERVING",
        "EVALUATING",
        "LEARNING",
        "COMPLETED",
    ]
    assert [metric["scenario"] for metric in completed["metrics"]] == [
        "baseline",
        "improved",
        "improved",
    ]


def test_reject_leaves_content_untouched(tmp_path):
    supervisor, experiment, content, published = _create(tmp_path)

    rejected = supervisor.reject(experiment["id"], message="not now")

    assert rejected["state"] == "FAILED"
    assert rejected["status"] == "failed"
    assert "rejected" in rejected["error"]
    assert content.joinpath("index.md").read_text(encoding="utf-8") == ORIGINAL
    assert not published.exists()
    assert supervisor.approvals.get(experiment["approval_id"])["status"] == "rejected"


def test_regression_rolls_back_content_and_publish(tmp_path):
    supervisor, experiment, content, published = _create(
        tmp_path, scenario="regressed"
    )

    rolled_back = supervisor.approve(experiment["id"])

    assert rolled_back["state"] == "ROLLED_BACK"
    assert rolled_back["decision"] == "loss"
    assert rolled_back["result"]["rolled_back"] is True
    assert content.joinpath("index.md").read_text(encoding="utf-8") == ORIGINAL
    assert not published.joinpath("index.md").exists()


def test_invalid_measurement_is_not_treated_as_a_win(tmp_path):
    supervisor, experiment, content, _ = _create(tmp_path, scenario="invalid")

    result = supervisor.approve(experiment["id"])

    assert result["state"] == "ROLLED_BACK"
    assert result["decision"] == "invalid"
    assert content.joinpath("index.md").read_text(encoding="utf-8") == ORIGINAL


def test_inconclusive_result_still_learns(tmp_path):
    supervisor, experiment, _, _ = _create(tmp_path, scenario="no_change")

    result = supervisor.approve(experiment["id"])

    assert result["state"] == "COMPLETED"
    assert result["decision"] == "inconclusive"
    assert result["lessons"][0]["confidence"] == 0.4


def test_budget_exceeded_fails_closed(tmp_path):
    content, published = _workspace(tmp_path)
    supervisor = Supervisor(
        db_path=tmp_path / "experiments.db",
        artifact_root=tmp_path / "artifacts",
    )

    with pytest.raises(BudgetExceeded, match="step budget exceeded"):
        supervisor.create(
            objective="Too small a budget",
            site="example.com",
            page="index.md",
            queries=QUERIES,
            content_root=content,
            publish_root=published,
            budget={"max_steps": 2},
        )

    experiments = supervisor.store.list()
    assert len(experiments) == 1
    assert experiments[0]["state"] == "FAILED"
    assert "budget" in experiments[0]["error"]


def test_resume_honors_external_approval_decision(tmp_path):
    supervisor, experiment, _, _ = _create(tmp_path)
    supervisor.approvals.resolve(
        experiment["approval_id"], decision="approve", resolved_by="test"
    )

    result = supervisor.resume(experiment["id"])

    assert result["state"] == "COMPLETED"
    assert result["decision"] == "win"


def test_resume_fails_closed_on_expired_approval(tmp_path):
    supervisor, experiment, content, _ = _create(tmp_path)
    supervisor.approvals.resolve(
        experiment["approval_id"], decision="reject", resolved_by="test"
    )

    result = supervisor.resume(experiment["id"])

    assert result["state"] == "FAILED"
    assert "approval rejected" in result["error"]
    assert content.joinpath("index.md").read_text(encoding="utf-8") == ORIGINAL
