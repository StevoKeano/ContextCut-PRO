"""
Live integration tests — require a running ContextCut-PRO server.

These tests are skipped unless ``--live`` is passed to pytest.

Override addresses with env vars:
  CONTEXTCUT_DASHBOARD_URL=http://192.168.137.252:18787
  CONTEXTCUT_PROXY_URL=http://192.168.137.252:18788
"""

import json
import os

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
