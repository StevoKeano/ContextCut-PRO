"""Tests for human-in-the-loop approval helpers and endpoint."""

import asyncio
import threading

import pytest

import qdrant_proxy_final as qp


def test_resolve_always_approves():
    decisions = asyncio.run(
        qp._resolve_approval_requests(
            [{"actions": [{"name": "shell_exec"}, {"name": "write_file"}]}],
            mode="always",
            task_id="t1",
            sid="s1",
            emit=None,
        )
    )
    assert decisions == [{"type": "approve"}, {"type": "approve"}]


def test_resolve_reject_mode():
    decisions = asyncio.run(
        qp._resolve_approval_requests(
            [{"actions": [{"name": "shell_exec"}]}],
            mode="reject",
            task_id="t1",
            sid="s1",
            emit=None,
        )
    )
    assert decisions[0]["type"] == "reject"


def test_non_streaming_auto_rejects():
    decisions = asyncio.run(
        qp._resolve_approval_requests(
            [{"actions": [{"name": "shell_exec"}]}],
            mode="ask",
            task_id="t1",
            sid="s1",
            emit=None,
        )
    )
    assert decisions[0]["type"] == "reject"


def test_streaming_waits_for_approval(monkeypatch):
    monkeypatch.setattr(qp, "APPROVAL_TIMEOUT", 5)
    events = []

    async def run():
        task = asyncio.create_task(
            qp._resolve_approval_requests(
                [{"actions": [{"name": "shell_exec"}]}],
                mode="ask",
                task_id="t-approve",
                sid="s1",
                emit=lambda data: events.append(data),
            )
        )
        for _ in range(100):
            if events:
                break
            await asyncio.sleep(0.01)
        assert events and events[0]["approval"] is True
        with qp._APPROVALS_LOCK:
            qp._APPROVALS["t-approve"]["decisions"] = [{"type": "approve"}]
            qp._APPROVALS["t-approve"]["event"].set()
        return await task

    decisions = asyncio.run(run())
    assert decisions == [{"type": "approve"}]


def test_approve_endpoint_no_pending(make_handler):
    status, raw = make_handler(
        "/api/agent/approve", "POST", b'{"task_id":"nope","decisions":[{"type":"approve"}]}'
    )
    assert status == 404


def test_approve_endpoint_sets_decisions(make_handler):
    gate = {"event": threading.Event(), "decisions": None, "created": 0}
    with qp._APPROVALS_LOCK:
        qp._APPROVALS["task-x"] = gate
    try:
        status, raw = make_handler(
            "/api/agent/approve",
            "POST",
            b'{"task_id":"task-x","decisions":[{"type":"approve"}]}',
        )
        assert status == 200
        assert gate["event"].is_set()
        assert gate["decisions"] == [{"type": "approve"}]
    finally:
        with qp._APPROVALS_LOCK:
            qp._APPROVALS.pop("task-x", None)


def test_extract_interrupt_requests_shape():
    class Intr:
        value = {
            "action_requests": [{"name": "shell_exec", "args": {"command": "id"}}],
            "review_configs": [{"allowed_decisions": ["approve", "reject"]}],
        }

    class Task:
        interrupts = [Intr()]

    class State:
        tasks = [Task()]

    reqs = qp._extract_interrupt_requests(State())
    assert reqs[0]["actions"][0]["name"] == "shell_exec"
    assert reqs[0]["actions"][0]["args"] == {"command": "id"}
