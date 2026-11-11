"""Persistent human-in-the-loop approval queue.

Both the headless supervisor and the dashboard use this store.  The store is
deliberately separate from LangGraph's in-memory interrupts so an approval can
survive a proxy restart and can be reviewed from the dashboard.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from experiment_store import (
    connect,
    init_db,
    json_dump,
    json_load,
    now_iso,
)

_APPROVAL_PUBLIC_JSON = {
    "payload": "payload_json",
    "metadata": "metadata_json",
}


def _public(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["payload"] = json_load(data.pop("payload_json", None), {})
    data["metadata"] = json_load(data.pop("metadata_json", None), {})
    return data


class ApprovalStore:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = init_db(db_path)

    def _db(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def request(
        self,
        *,
        experiment_id: str,
        action: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        approval_id = "ap-" + uuid.uuid4().hex[:12]
        db = self._db()
        try:
            db.execute(
                """
                INSERT INTO approvals (
                    id, experiment_id, action, payload_json, status,
                    requested_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval_id,
                    experiment_id,
                    action,
                    json_dump(payload or {}),
                    "pending",
                    now_iso(),
                    json_dump(metadata or {}),
                ),
            )
            db.commit()
            row = db.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        finally:
            db.close()
        return _public(row)

    def get(self, approval_id: str) -> dict[str, Any]:
        db = self._db()
        try:
            row = db.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError(f"approval not found: {approval_id}")
        return _public(row)

    def pending(self, experiment_id: str | None = None) -> list[dict[str, Any]]:
        db = self._db()
        try:
            if experiment_id:
                rows = db.execute(
                    "SELECT * FROM approvals WHERE status = 'pending' AND experiment_id = ? "
                    "ORDER BY requested_at DESC",
                    (experiment_id,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM approvals WHERE status = 'pending' "
                    "ORDER BY requested_at DESC"
                ).fetchall()
        finally:
            db.close()
        return [_public(row) for row in rows]

    def latest_pending(self, experiment_id: str) -> dict[str, Any] | None:
        pending = self.pending(experiment_id)
        return pending[0] if pending else None

    def resolve(
        self,
        approval_id: str,
        *,
        decision: str,
        message: str = "",
        resolved_by: str = "dashboard",
    ) -> dict[str, Any]:
        decision = str(decision).strip().lower()
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        status = "approved" if decision == "approve" else "rejected"
        db = self._db()
        try:
            cursor = db.execute(
                """
                UPDATE approvals
                   SET status = ?, decision = ?, message = ?, resolved_at = ?, resolved_by = ?
                 WHERE id = ? AND status = 'pending'
                """,
                (status, decision, message, now_iso(), resolved_by, approval_id),
            )
            db.commit()
            if cursor.rowcount == 0:
                row = db.execute(
                    "SELECT status FROM approvals WHERE id = ?", (approval_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(f"approval not found: {approval_id}")
                raise ValueError(f"approval is not pending: {approval_id} ({row['status']})")
            row = db.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        finally:
            db.close()
        return _public(row)

    def expire_stale(self, max_age_hours: float = 24.0) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=max(float(max_age_hours), 0.0))
        ).isoformat(timespec="seconds")
        db = self._db()
        try:
            cursor = db.execute(
                """
                UPDATE approvals
                   SET status = 'expired', decision = 'expired',
                       message = 'Approval expired before review.',
                       resolved_at = ?, resolved_by = 'system'
                 WHERE status = 'pending' AND requested_at < ?
                """,
                (now_iso(), cutoff),
            )
            db.commit()
            return int(cursor.rowcount)
        finally:
            db.close()

    def list(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        db = self._db()
        try:
            if status:
                rows = db.execute(
                    "SELECT * FROM approvals WHERE status = ? ORDER BY requested_at DESC LIMIT ?",
                    (status, max(1, int(limit))),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM approvals ORDER BY requested_at DESC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
        finally:
            db.close()
        return [_public(row) for row in rows]
