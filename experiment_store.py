"""Persistent experiment ledger for the AEO supervisor.

The store is intentionally small and dependency-free.  It keeps the durable
state that the supervisor needs to resume after a crash, while large artifacts
(diffs, snapshots, prompts) live on disk under ~/.contextcut/experiments/.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_DB = Path.home() / ".contextcut" / "experiments.db"
DEFAULT_ARTIFACT_ROOT = Path.home() / ".contextcut" / "experiments"

_EXPERIMENT_JSON_FIELDS = {
    "queries",
    "baseline",
    "hypothesis",
    "result",
    "config",
    "budget",
}

_EXPERIMENT_COLUMNS = {
    "objective",
    "site",
    "page",
    "queries",
    "target_metric",
    "baseline",
    "hypothesis",
    "state",
    "status",
    "approval_id",
    "decision",
    "result",
    "config",
    "budget",
    "error",
}


def default_db_path() -> Path:
    override = os.environ.get("CONTEXTCUT_EXPERIMENT_DB")
    return Path(override).expanduser() if override else DEFAULT_DB


def default_artifact_root() -> Path:
    override = os.environ.get("CONTEXTCUT_EXPERIMENT_ARTIFACTS")
    return Path(override).expanduser() if override else DEFAULT_ARTIFACT_ROOT


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def json_load(value: Any, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path).expanduser() if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db(db_path: str | Path | None = None) -> Path:
    path = Path(db_path).expanduser() if db_path else default_db_path()
    db = connect(path)
    try:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                objective TEXT NOT NULL,
                site TEXT NOT NULL,
                page TEXT NOT NULL,
                queries_json TEXT NOT NULL,
                target_metric TEXT NOT NULL,
                baseline_json TEXT,
                hypothesis_json TEXT,
                state TEXT NOT NULL,
                status TEXT NOT NULL,
                approval_id TEXT,
                decision TEXT,
                result_json TEXT,
                config_json TEXT,
                budget_json TEXT,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS experiment_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id TEXT NOT NULL,
                state TEXT NOT NULL,
                role TEXT NOT NULL,
                run_id TEXT,
                status TEXT NOT NULL,
                input_json TEXT,
                output_json TEXT,
                cost_json TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                FOREIGN KEY(experiment_id) REFERENCES experiments(id)
            );

            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id TEXT NOT NULL,
                name TEXT NOT NULL,
                value REAL,
                unit TEXT NOT NULL DEFAULT "",
                source TEXT NOT NULL DEFAULT "",
                scenario TEXT NOT NULL DEFAULT "",
                window_json TEXT,
                raw_json TEXT,
                observed_at TEXT NOT NULL,
                FOREIGN KEY(experiment_id) REFERENCES experiments(id)
            );

            CREATE TABLE IF NOT EXISTS lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id TEXT NOT NULL,
                lesson TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.0,
                tags_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(experiment_id) REFERENCES experiments(id)
            );

            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                experiment_id TEXT NOT NULL,
                action TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                resolved_at TEXT,
                resolved_by TEXT,
                decision TEXT,
                message TEXT,
                metadata_json TEXT,
                FOREIGN KEY(experiment_id) REFERENCES experiments(id)
            );

            CREATE INDEX IF NOT EXISTS idx_experiments_state
                ON experiments(state, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_steps_experiment
                ON experiment_steps(experiment_id, id);
            CREATE INDEX IF NOT EXISTS idx_metrics_experiment
                ON metrics(experiment_id, id);
            CREATE INDEX IF NOT EXISTS idx_approvals_status
                ON approvals(status, requested_at DESC);
            """
        )
        db.commit()
    finally:
        db.close()
    return path


def _public_experiment(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["queries"] = json_load(data.pop("queries_json", None), [])
    data["baseline"] = json_load(data.pop("baseline_json", None), {})
    data["hypothesis"] = json_load(data.pop("hypothesis_json", None), {})
    data["result"] = json_load(data.pop("result_json", None), {})
    data["config"] = json_load(data.pop("config_json", None), {})
    data["budget"] = json_load(data.pop("budget_json", None), {})
    return data


def _public_step(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["input"] = json_load(data.pop("input_json", None), {})
    data["output"] = json_load(data.pop("output_json", None), {})
    data["cost"] = json_load(data.pop("cost_json", None), {})
    return data


def _public_metric(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["window"] = json_load(data.pop("window_json", None), {})
    data["raw"] = json_load(data.pop("raw_json", None), {})
    return data


def _public_lesson(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["tags"] = json_load(data.pop("tags_json", None), [])
    return data


class ExperimentStore:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = init_db(db_path)

    def _db(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def create(
        self,
        *,
        objective: str,
        site: str,
        page: str,
        queries: Iterable[str],
        target_metric: str,
        baseline: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
        experiment_id: str | None = None,
    ) -> dict[str, Any]:
        experiment_id = experiment_id or (
            "exp-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        )
        query_list = [str(query).strip() for query in queries if str(query).strip()]
        if not query_list:
            raise ValueError("at least one query is required")
        timestamp = now_iso()
        db = self._db()
        try:
            db.execute(
                """
                INSERT INTO experiments (
                    id, created_at, updated_at, objective, site, page,
                    queries_json, target_metric, baseline_json, hypothesis_json,
                    state, status, approval_id, decision, result_json,
                    config_json, budget_json, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    timestamp,
                    timestamp,
                    objective.strip(),
                    site.strip(),
                    page.strip(),
                    json_dump(query_list),
                    target_metric.strip(),
                    json_dump(baseline or {}),
                    json_dump(None),
                    "DRAFT",
                    "active",
                    None,
                    None,
                    json_dump({}),
                    json_dump(config or {}),
                    json_dump(budget or {}),
                    None,
                ),
            )
            db.commit()
        finally:
            db.close()
        return self.get(experiment_id)

    def get(self, experiment_id: str) -> dict[str, Any]:
        db = self._db()
        try:
            row = db.execute(
                "SELECT * FROM experiments WHERE id = ?", (experiment_id,)
            ).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError(f"experiment not found: {experiment_id}")
        return _public_experiment(row)

    def list(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        db = self._db()
        try:
            if status:
                rows = db.execute(
                    "SELECT * FROM experiments WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                    (status, max(1, int(limit))),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM experiments ORDER BY updated_at DESC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
        finally:
            db.close()
        return [_public_experiment(row) for row in rows]

    def update(self, experiment_id: str, **fields: Any) -> dict[str, Any]:
        unknown = set(fields) - _EXPERIMENT_COLUMNS
        if unknown:
            raise ValueError(f"unknown experiment fields: {', '.join(sorted(unknown))}")
        if not fields:
            return self.get(experiment_id)

        updates: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key in _EXPERIMENT_JSON_FIELDS:
                key = f"{key}_json"
                value = json_dump(value)
            updates.append(f"{key} = ?")
            values.append(value)
        updates.append("updated_at = ?")
        values.append(now_iso())
        values.append(experiment_id)

        db = self._db()
        try:
            cursor = db.execute(
                f"UPDATE experiments SET {', '.join(updates)} WHERE id = ?", values
            )
            db.commit()
            if cursor.rowcount == 0:
                raise KeyError(f"experiment not found: {experiment_id}")
        finally:
            db.close()
        return self.get(experiment_id)

    def set_state(
        self,
        experiment_id: str,
        state: str,
        *,
        status: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        if status is None:
            if state in {"COMPLETED"}:
                status = "completed"
            elif state in {"FAILED", "ROLLED_BACK"}:
                status = "failed"
            elif state == "PENDING_APPROVAL":
                status = "pending"
            else:
                status = "active"
        fields: dict[str, Any] = {"state": state, "status": status}
        if error is not None:
            fields["error"] = error
        return self.update(experiment_id, **fields)

    def add_step(
        self,
        experiment_id: str,
        *,
        state: str,
        role: str,
        status: str,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        run_id: str | None = None,
        cost: dict[str, Any] | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        db = self._db()
        try:
            cursor = db.execute(
                """
                INSERT INTO experiment_steps (
                    experiment_id, state, role, run_id, status,
                    input_json, output_json, cost_json, started_at, ended_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    state,
                    role,
                    run_id,
                    status,
                    json_dump(input_data or {}),
                    json_dump(output_data or {}),
                    json_dump(cost or {}),
                    started_at or timestamp,
                    ended_at,
                ),
            )
            db.commit()
            step_id = cursor.lastrowid
            row = db.execute(
                "SELECT * FROM experiment_steps WHERE id = ?", (step_id,)
            ).fetchone()
        finally:
            db.close()
        return _public_step(row)

    def steps(self, experiment_id: str, limit: int = 200) -> list[dict[str, Any]]:
        db = self._db()
        try:
            rows = db.execute(
                "SELECT * FROM experiment_steps WHERE experiment_id = ? ORDER BY id ASC LIMIT ?",
                (experiment_id, max(1, int(limit))),
            ).fetchall()
        finally:
            db.close()
        return [_public_step(row) for row in rows]

    def add_metric(
        self,
        experiment_id: str,
        *,
        name: str,
        value: float | None,
        unit: str = "",
        source: str = "",
        scenario: str = "",
        window: dict[str, Any] | None = None,
        raw: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        db = self._db()
        try:
            cursor = db.execute(
                """
                INSERT INTO metrics (
                    experiment_id, name, value, unit, source, scenario,
                    window_json, raw_json, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    name,
                    value,
                    unit,
                    source,
                    scenario,
                    json_dump(window or {}),
                    json_dump(raw or {}),
                    now_iso(),
                ),
            )
            db.commit()
            row = db.execute("SELECT * FROM metrics WHERE id = ?", (cursor.lastrowid,)).fetchone()
        finally:
            db.close()
        return _public_metric(row)

    def metrics(self, experiment_id: str, limit: int = 200) -> list[dict[str, Any]]:
        db = self._db()
        try:
            rows = db.execute(
                "SELECT * FROM metrics WHERE experiment_id = ? ORDER BY id ASC LIMIT ?",
                (experiment_id, max(1, int(limit))),
            ).fetchall()
        finally:
            db.close()
        return [_public_metric(row) for row in rows]

    def add_lesson(
        self,
        experiment_id: str,
        *,
        lesson: str,
        confidence: float = 0.0,
        tags: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        db = self._db()
        try:
            cursor = db.execute(
                """
                INSERT INTO lessons (experiment_id, lesson, confidence, tags_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    lesson,
                    float(confidence),
                    json_dump(list(tags or [])),
                    now_iso(),
                ),
            )
            db.commit()
            row = db.execute("SELECT * FROM lessons WHERE id = ?", (cursor.lastrowid,)).fetchone()
        finally:
            db.close()
        return _public_lesson(row)

    def lessons(self, limit: int = 50) -> list[dict[str, Any]]:
        db = self._db()
        try:
            rows = db.execute(
                "SELECT * FROM lessons ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)
            ).fetchall()
        finally:
            db.close()
        return [_public_lesson(row) for row in rows]

    def detail(self, experiment_id: str) -> dict[str, Any]:
        experiment = self.get(experiment_id)
        experiment["steps"] = self.steps(experiment_id)
        experiment["metrics"] = self.metrics(experiment_id)
        experiment["lessons"] = [
            lesson for lesson in self.lessons(limit=200) if lesson["experiment_id"] == experiment_id
        ]
        return experiment
