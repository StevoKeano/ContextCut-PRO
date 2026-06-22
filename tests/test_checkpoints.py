"""
Tests for episodic checkpoint system: CheckpointManager, resume, dashboard routes.
"""
import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestCheckpointManager:
    @pytest.fixture
    def mgr(self, tmp_path: Path):
        from agent_handler import CheckpointManager
        return CheckpointManager(base_dir=tmp_path)

    def test_save_creates_json_file(self, mgr):
        mgr.save("task-1", {
            "step_number": 1, "tool_name": "web_search",
            "tool_input": {"query": "test"}, "tool_output": "results",
            "goal": "test task", "model_used": "qwen3:4b",
        })
        p = mgr.base_dir / "task-1" / "0001.json"
        assert p.exists()
        data = json.loads(p.read_text())
        assert data["step_number"] == 1
        assert data["tool_name"] == "web_search"

    def test_load_returns_latest(self, mgr):
        for i in range(1, 4):
            mgr.save("task-2", {
                "step_number": i, "tool_name": "tool", "tool_input": {},
                "tool_output": str(i), "goal": "g", "model_used": "m",
            })
        data = mgr.load("task-2")
        assert data["step_number"] == 3
        assert data["tool_output"] == "3"

    def test_load_specific_step(self, mgr):
        mgr.save("task-3", {
            "step_number": 5, "tool_name": "t", "tool_input": {},
            "tool_output": "v5", "goal": "g", "model_used": "m",
        })
        data = mgr.load("task-3", step_number=5)
        assert data["step_number"] == 5
        assert data["tool_output"] == "v5"

    def test_load_nonexistent_returns_none(self, mgr):
        assert mgr.load("no-such-task") is None
        assert mgr.load("no-such-task", step_number=1) is None

    def test_list_all_returns_all_steps(self, mgr):
        for i in range(1, 4):
            mgr.save("task-4", {
                "step_number": i, "tool_name": "t", "tool_input": {},
                "tool_output": str(i), "goal": "g", "model_used": "m",
            })
        steps = mgr.list_all("task-4")
        assert len(steps) == 3
        assert [s["step_number"] for s in steps] == [1, 2, 3]

    def test_exists_true_when_checkpoints_present(self, mgr):
        mgr.save("task-5", {
            "step_number": 1, "tool_name": "t", "tool_input": {},
            "tool_output": "x", "goal": "g", "model_used": "m",
        })
        assert mgr.exists("task-5") is True

    def test_exists_false_when_no_checkpoints(self, mgr):
        assert mgr.exists("no-such-task") is False

    def test_latest_step_number(self, mgr):
        for i in [1, 2, 3]:
            mgr.save("task-6", {
                "step_number": i, "tool_name": "t", "tool_input": {},
                "tool_output": str(i), "goal": "g", "model_used": "m",
            })
        assert mgr.latest_step_number("task-6") == 3

    def test_latest_step_number_returns_zero_for_empty(self, mgr):
        assert mgr.latest_step_number("empty") == 0

    def test_build_resume_context_none_when_no_checkpoints(self, mgr):
        assert mgr.build_resume_context("no-such") is None

    def test_build_resume_context_includes_steps(self, mgr):
        mgr.save("task-7", {
            "step_number": 1, "tool_name": "web_search",
            "tool_input": {"query": "test"}, "tool_output": "found: xyz",
            "goal": "test task", "model_used": "qwen3:4b",
        })
        ctx = mgr.build_resume_context("task-7")
        assert ctx is not None
        assert "Step 1" in ctx
        assert "web_search" in ctx
        assert "found: xyz" in ctx
        assert "Resume at step 2" in ctx

    def test_kwargs_attached_to_checkpoint(self, mgr):
        mgr.save("task-kw", {
            "step_number": 1, "tool_name": "write_file",
            "tool_input": {"path": "/tmp/test.txt", "content": "hello"},
            "tool_output": "Wrote 5 bytes",
            "goal": "write a file", "model_used": "qwen3:4b",
        })
        data = mgr.load("task-kw")
        assert data["tool_input"]["path"] == "/tmp/test.txt"
        assert data["tool_input"]["content"] == "hello"

    def test_checkpoint_has_timestamp(self, mgr):
        mgr.save("task-ts", {
            "step_number": 1, "tool_name": "t", "tool_input": {},
            "tool_output": "x", "goal": "g", "model_used": "m",
        })
        data = mgr.load("task-ts")
        assert "timestamp" in data
        assert len(data["timestamp"]) > 10


class TestCheckpointCrashRecovery:
    """Simulate crash by deleting in-memory state after partial checkpointing."""

    def test_checkpoint_integrity_after_crash(self, tmp_path: Path):
        from agent_handler import CheckpointManager
        mgr = CheckpointManager(base_dir=tmp_path)

        steps_data = [
            dict(step_number=1, tool_name="web_search",
                 tool_input={"query": "q1"}, tool_output="res1"),
            dict(step_number=2, tool_name="read_file",
                 tool_input={"path": "f1"}, tool_output="content1"),
            dict(step_number=3, tool_name="run_python",
                 tool_input={"code": "print(1)"}, tool_output="1"),
        ]

        for s in steps_data:
            s.update(goal="crash test", model_used="qwen3:4b")
            mgr.save("crash-task", s)
            # Simulate process crash: files survive on disk

        # Recovery: fresh manager reads disk
        mgr2 = CheckpointManager(base_dir=tmp_path)
        assert mgr2.exists("crash-task")
        assert mgr2.latest_step_number("crash-task") == 3
        checkpoints = mgr2.list_all("crash-task")
        assert len(checkpoints) == 3
        for i, cp in enumerate(checkpoints, 1):
            assert cp["step_number"] == i
            assert cp["tool_name"] == steps_data[i - 1]["tool_name"]

    def test_resume_after_crash_preserves_prior_context(self, tmp_path: Path):
        from agent_handler import CheckpointManager
        mgr = CheckpointManager(base_dir=tmp_path)
        mgr.save("resume-crash", {
            "step_number": 1, "tool_name": "web_search",
            "tool_input": {"query": "history"}, "tool_output": "found: Rome was built in a day",
            "goal": "research history", "model_used": "qwen3:4b",
        })
        mgr.save("resume-crash", {
            "step_number": 2, "tool_name": "web_search",
            "tool_input": {"query": "Rome founding"}, "tool_output": "found: 753 BC",
            "goal": "research history", "model_used": "qwen3:4b",
        })

        ctx = mgr.build_resume_context("resume-crash")
        assert "Step 1" in ctx
        assert "Step 2" in ctx
        assert "Rome was built" in ctx or "Rome founding" in ctx
        assert "Resume at step 3" in ctx

    def test_estimated_token_savings(self, tmp_path: Path):
        from agent_handler import CheckpointManager
        mgr = CheckpointManager(base_dir=tmp_path)
        for i in range(1, 11):
            mgr.save("big-task", {
                "step_number": i, "tool_name": "web_search",
                "tool_input": {"query": f"query {i}"},
                "tool_output": f"result {i}" * 100,
                "goal": "big research", "model_used": "qwen3:4b",
            })
        checkpoints = mgr.list_all("big-task")
        total_tok = sum(
            len(json.dumps(cp.get("tool_input", {})))
            + len(cp.get("tool_output", ""))
            for cp in checkpoints
        )
        # Checkpoint overhead from all 10 steps should be > 0 (it has data)
        # and < 50K chars (reasonable for disk-based resume context)
        assert total_tok > 0
        assert total_tok < 50000


class TestCheckpointCallbackHandler:
    @patch("agent_handler.CheckpointManager")
    def test_on_tool_end_saves_checkpoint(self, MockCkptMgr):
        from agent_handler import CheckpointCallbackHandler
        handler = CheckpointCallbackHandler(
            task_id="test-task", goal="test goal", model_used="qwen3:4b"
        )
        handler.on_tool_start(
            {"name": "web_search"},
            {"query": "test query"},
        )
        handler.on_tool_end("search results here")
        assert handler.step_number == 1
        handler._manager.save.assert_called_once()
        args, _ = handler._manager.save.call_args
        assert args[0] == "test-task"
        assert args[1]["tool_name"] == "web_search"
        assert args[1]["tool_output"] == "search results here"

    @patch("agent_handler.CheckpointManager")
    def test_on_tool_end_error_output_not_fail(self, MockCkptMgr):
        from agent_handler import CheckpointCallbackHandler
        handler = CheckpointCallbackHandler(
            task_id="t2", goal="g", model_used="m"
        )
        handler.on_tool_start({"name": "read_file"}, {"path": "/nonexistent"})
        handler.on_tool_end(None)
        assert handler.step_number == 1
        handler._manager.save.assert_called_once()


def _json(raw: bytes) -> dict:
    """Extract JSON body from HTTP response (strip headers)."""
    return json.loads(raw.split(b"\r\n\r\n", 1)[-1] if b"\r\n\r\n" in raw else raw)


class TestDashboardCheckpointRoutes:
    def test_get_checkpoints_list_empty(self, tmp_path, make_handler):
        from agent_handler import CheckpointManager
        mgr = CheckpointManager(base_dir=tmp_path)
        with patch("agent_handler._CHECKPOINT_DIR", tmp_path):
            status, raw = make_handler("/api/checkpoints", "GET")
        assert status == 200
        data = _json(raw)
        assert "tasks" in data
        assert data["tasks"] == []

    def test_get_checkpoints_by_task_id(self, tmp_path, make_handler):
        from agent_handler import CheckpointManager
        mgr = CheckpointManager(base_dir=tmp_path)
        mgr.save("task-view", {
            "step_number": 1, "tool_name": "web_search",
            "tool_input": {"query": "test"}, "tool_output": "results",
            "goal": "view test", "model_used": "qwen3:4b",
        })
        with patch("agent_handler._CHECKPOINT_DIR", tmp_path):
            status, raw = make_handler(
                "/api/checkpoints/task-view", "GET"
            )
        assert status == 200
        data = _json(raw)
        assert data["task_id"] == "task-view"
        assert data["step_count"] == 1
        assert data["steps"][0]["tool_name"] == "web_search"

    def test_get_checkpoints_not_found(self, make_handler):
        status, raw = make_handler("/api/checkpoints/no-such", "GET")
        assert status == 404

    def test_get_checkpoints_estimated_tokens(self, tmp_path, make_handler):
        from agent_handler import CheckpointManager
        mgr = CheckpointManager(base_dir=tmp_path)
        for i in range(1, 4):
            mgr.save("task-tok", {
                "step_number": i, "tool_name": "t", "tool_input": {},
                "tool_output": "x" * 100, "goal": "g", "model_used": "m",
            })
        with patch("agent_handler._CHECKPOINT_DIR", tmp_path):
            status, raw = make_handler("/api/checkpoints/task-tok", "GET")
        assert status == 200
        data = _json(raw)
        assert data["estimated_resume_tokens"] > 0

    def test_get_checkpoints_all_with_data(self, tmp_path, make_handler):
        from agent_handler import CheckpointManager
        mgr = CheckpointManager(base_dir=tmp_path)
        mgr.save("alpha", {
            "step_number": 1, "tool_name": "t1", "tool_input": {},
            "tool_output": "a", "goal": "g1", "model_used": "m",
        })
        mgr.save("beta", {
            "step_number": 1, "tool_name": "t2", "tool_input": {},
            "tool_output": "b", "goal": "g2", "model_used": "m2",
        })
        with patch("agent_handler._CHECKPOINT_DIR", tmp_path):
            status, raw = make_handler("/api/checkpoints", "GET")
        assert status == 200
        data = _json(raw)
        assert len(data["tasks"]) == 2
        tids = {t["task_id"] for t in data["tasks"]}
        assert tids == {"alpha", "beta"}
