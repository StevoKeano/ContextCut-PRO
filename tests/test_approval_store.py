"""Tests for the persistent approval queue."""

from __future__ import annotations

import pytest

from approval_store import ApprovalStore
from experiment_store import ExperimentStore, connect


def _experiment(store: ExperimentStore) -> str:
    return store.create(
        objective="Test approval",
        site="example.com",
        page="index.md",
        queries=["q"],
        target_metric="aeo_citation_rate",
    )["id"]


def test_request_and_resolve_approval(tmp_path):
    db_path = tmp_path / "experiments.db"
    store = ExperimentStore(db_path)
    approvals = ApprovalStore(db_path)
    experiment_id = _experiment(store)

    approval = approvals.request(
        experiment_id=experiment_id,
        action="publish",
        payload={"diff": "+answer"},
        metadata={"page": "index.md"},
    )

    assert approval["status"] == "pending"
    assert approvals.latest_pending(experiment_id)["id"] == approval["id"]

    resolved = approvals.resolve(
        approval["id"],
        decision="approve",
        message="ok",
        resolved_by="test",
    )
    assert resolved["status"] == "approved"
    assert resolved["decision"] == "approve"
    assert resolved["resolved_by"] == "test"
    assert approvals.pending(experiment_id) == []


def test_reject_and_duplicate_resolution(tmp_path):
    db_path = tmp_path / "experiments.db"
    store = ExperimentStore(db_path)
    approvals = ApprovalStore(db_path)
    experiment_id = _experiment(store)
    approval = approvals.request(
        experiment_id=experiment_id,
        action="publish",
        payload={},
    )

    rejected = approvals.resolve(approval["id"], decision="reject", message="no")
    assert rejected["status"] == "rejected"

    with pytest.raises(ValueError, match="not pending"):
        approvals.resolve(approval["id"], decision="approve")


def test_invalid_decision(tmp_path):
    db_path = tmp_path / "experiments.db"
    store = ExperimentStore(db_path)
    approvals = ApprovalStore(db_path)
    approval = approvals.request(
        experiment_id=_experiment(store),
        action="publish",
        payload={},
    )

    with pytest.raises(ValueError, match="approve or reject"):
        approvals.resolve(approval["id"], decision="maybe")


def test_expire_stale(tmp_path):
    db_path = tmp_path / "experiments.db"
    store = ExperimentStore(db_path)
    approvals = ApprovalStore(db_path)
    approval = approvals.request(
        experiment_id=_experiment(store),
        action="publish",
        payload={},
    )

    db = connect(db_path)
    try:
        db.execute(
            "UPDATE approvals SET requested_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", approval["id"]),
        )
        db.commit()
    finally:
        db.close()

    assert approvals.expire_stale(max_age_hours=1) == 1
    assert approvals.get(approval["id"])["status"] == "expired"
