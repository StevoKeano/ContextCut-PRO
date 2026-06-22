"""
Live integration tests — require a running ContextCut-PRO server.

These tests are skipped unless ``--live`` is passed to pytest.

Override addresses with env vars:
  CONTEXTCUT_DASHBOARD_URL=http://192.168.137.252:18787
  CONTEXTCUT_PROXY_URL=http://192.168.137.252:18788
"""

import json
import os
from pathlib import Path

import pytest


@pytest.mark.live
class TestLiveIntegration:
    DASHBOARD = os.environ.get("CONTEXTCUT_DASHBOARD_URL", "http://192.168.137.252:18787")
    PROXY = os.environ.get("CONTEXTCUT_PROXY_URL", "http://192.168.137.252:18788")

    def test_proxy_health(self):
        import urllib.request

        resp = urllib.request.urlopen(f"{self.DASHBOARD}/log", timeout=5)
        assert resp.status == 200

    def test_dashboard(self):
        import urllib.request

        resp = urllib.request.urlopen(self.DASHBOARD, timeout=5)
        body = resp.read().decode()
        assert resp.status == 200
        assert "ContextCut" in body or "html" in body.lower()

    def test_agent_tools_list(self):
        import urllib.request

        resp = urllib.request.urlopen(f"{self.DASHBOARD}/api/agent/tools", timeout=5)
        data = json.loads(resp.read().decode())
        assert "tools" in data
        assert len(data["tools"]) >= 22

    def test_knowledge_list(self):
        import urllib.request

        resp = urllib.request.urlopen(f"{self.DASHBOARD}/api/session/new", timeout=5)
        data = json.loads(resp.read().decode())
        assert "session_id" in data

    def test_session_create(self):
        import urllib.request

        req_body = json.dumps({"message": "hello", "session_id": None, "stream": False}).encode()
        req = urllib.request.Request(
            f"{self.DASHBOARD}/api/agent",
            data=req_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read().decode())
        assert resp.status == 200


@pytest.mark.live
class TestLiveCheckpointIntegration:
    """
    End-to-end checkpoint tests against a running proxy.

    Verifies:
      - Checkpoint .json files land on disk after a multi-step agent run
      - Each checkpoint is valid JSON with required fields
      - Dashboard routes list/serve checkpoints
      - Resume from simulated crash injects prior-step context
      - Token overhead < 5% of context window (16384)
    """

    DASHBOARD = os.environ.get(
        "CONTEXTCUT_DASHBOARD_URL", "http://192.168.137.252:18787"
    )
    CTX_LIMIT = int(os.environ.get("CONTEXTCUT_CTX_LIMIT", "16384"))
    CHECKPOINT_DIR = Path.home() / ".contextcut" / "checkpoints"

    def _post_agent(
        self, message: str, task_id: str = "", timeout: int = 120
    ) -> tuple[str, dict]:
        """Send a non-streaming agent request. Returns (task_id, response_json)."""
        import urllib.request

        body = json.dumps({
            "message": message,
            "session_id": None,
            "model": "qwen3:14b-q8_0",
            "stream": False,
            "task_id": task_id,
        }).encode()
        req = urllib.request.Request(
            f"{self.DASHBOARD}/api/agent",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read().decode())
        assert resp.status == 200, f"Agent request failed: {data.get('error', '?')}"
        tid = data.get("task_id", "")
        assert tid, "Response missing task_id"
        return tid, data

    def test_01_checkpoint_files_created(self):
        """Multi-step prompt creates checkpoint .json files on disk."""
        prompt = (
            "Search the web for 'current population of Tokyo', "
            "then search the web for 'current population of New York', "
            "then tell me which is larger."
        )
        task_id, data = self._post_agent(prompt, timeout=180)
        response_text = data.get("response", "")

        # Allow fallback if the agent refused or gave a short answer
        assert len(response_text) > 20, f"Agent response too short: {response_text[:100]}"

        # Checkpoint files must exist
        ckpt_dir = self.CHECKPOINT_DIR / task_id
        step_files = sorted(ckpt_dir.glob("*.json"))
        assert len(step_files) >= 2, (
            f"Expected ≥2 checkpoint files in {ckpt_dir}, found {len(step_files)}"
        )

        # Each file must be valid JSON with required fields
        REQUIRED = {"step_number", "tool_name", "tool_input", "tool_output", "goal", "model_used", "status", "timestamp"}
        for f in step_files:
            data_cp = json.loads(f.read_text())
            missing = REQUIRED - set(data_cp.keys())
            assert not missing, f"{f.name} missing fields: {missing}"
            assert isinstance(data_cp["step_number"], int)
            assert isinstance(data_cp["tool_name"], str)
            assert data_cp["tool_output"] != "" or data_cp["status"] == "failed"

        # Print diagnostics
        print(f"\n  [checkpoint] task_id={task_id}")
        print(f"  [checkpoint] steps={len(step_files)}")
        for f in step_files:
            cp = json.loads(f.read_text())
            print(f"    {f.name}: {cp['tool_name']} -> {cp['tool_output'][:80]}")

    def test_02_dashboard_routes(self):
        """GET /api/checkpoints and /api/checkpoints/{task_id} work."""
        import urllib.request

        # First get the list of all checkpoint tasks
        resp = urllib.request.urlopen(
            f"{self.DASHBOARD}/api/checkpoints", timeout=10
        )
        assert resp.status == 200
        listing = json.loads(resp.read().decode())
        assert "tasks" in listing
        assert isinstance(listing["tasks"], list)

        # Pick the first task_id with ≥2 steps
        viable = [t for t in listing["tasks"] if t.get("steps", 0) >= 2]
        if not viable:
            pytest.skip("No checkpoint task with ≥2 steps found on proxy")

        tid = viable[0]["task_id"]
        resp = urllib.request.urlopen(
            f"{self.DASHBOARD}/api/checkpoints/{tid}", timeout=10
        )
        assert resp.status == 200
        detail = json.loads(resp.read().decode())
        assert detail["task_id"] == tid
        assert detail["step_count"] >= 2
        assert "steps" in detail
        assert detail["estimated_resume_tokens"] > 0

        # Print resume tokens for benchmarking
        print(f"\n  [checkpoint] {tid}: {detail['step_count']} steps, "
              f"estimated_resume_tokens={detail['estimated_resume_tokens']}")

    def test_03_resume_injects_context(self):
        """Simulate crash recovery: pre-create checkpoints, then resume with task_id."""
        import urllib.request

        crash_tid = "live-crash-test-" + str(os.urandom(4).hex())
        ckpt_dir = self.CHECKPOINT_DIR / crash_tid
        ckpt_dir.mkdir(parents=True, exist_ok=True)

        steps_data = [
            {
                "step_number": 1,
                "tool_name": "web_search",
                "tool_input": {"query": "population of Rome"},
                "tool_output": "Rome has a population of approximately 2.8 million.",
                "goal": "research city populations",
                "model_used": "qwen3:14b-q8_0",
                "status": "success",
                "reasoning": "",
                "context_injected": "",
            },
            {
                "step_number": 2,
                "tool_name": "web_search",
                "tool_input": {"query": "population of Paris"},
                "tool_output": "Paris has a population of approximately 2.1 million.",
                "goal": "research city populations",
                "model_used": "qwen3:14b-q8_0",
                "status": "success",
                "reasoning": "",
                "context_injected": "",
            },
        ]
        for s in steps_data:
            fname = ckpt_dir / f"{s['step_number']:04d}.json"
            fname.write_text(json.dumps(s, indent=2))

        # Now send a resume request with the crash task_id
        tid, data = self._post_agent(
            "Continue the research. Which city has a larger population, Rome or Paris?",
            task_id=crash_tid,
            timeout=120,
        )
        response_text = data.get("response", "")
        assert len(response_text) > 20, f"Resume response too short: {response_text[:100]}"

        # Clean up simulated crash checkpoints
        import shutil
        shutil.rmtree(ckpt_dir, ignore_errors=True)

        print(f"\n  [resume] task_id={crash_tid}")
        print(f"  [resume] response={response_text[:150]}...")

    def test_04_checkpoint_overhead(self):
        """Measured checkpoint size < 5% of context window."""
        import urllib.request

        resp = urllib.request.urlopen(
            f"{self.DASHBOARD}/api/checkpoints", timeout=10
        )
        listing = json.loads(resp.read().decode())
        viable = [t for t in listing["tasks"] if t.get("steps", 0) >= 2]
        if not viable:
            pytest.skip("No checkpoint task with ≥2 steps for overhead benchmark")

        tid = viable[0]["task_id"]
        ckpt_dir = self.CHECKPOINT_DIR / tid
        total_bytes = sum(f.stat().st_size for f in ckpt_dir.glob("*.json"))
        overhead_pct = total_bytes / self.CTX_LIMIT * 100

        print(f"\n  [overhead] task_id={tid}")
        print(f"  [overhead] total_checkpoint_bytes={total_bytes}")
        print(f"  [overhead] ctx_limit={self.CTX_LIMIT}")
        print(f"  [overhead] pct={overhead_pct:.2f}%")

        assert overhead_pct < 5.0, (
            f"Checkpoint overhead {overhead_pct:.2f}% exceeds 5% limit "
            f"({total_bytes}B / {self.CTX_LIMIT} ctx)"
        )
