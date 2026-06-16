"""
Live integration tests — require a running ContextCut-PRO server.

These tests are skipped unless ``--live`` is passed to pytest.

Target server: http://192.168.137.252:18788 (proxy) and :18787 (dashboard).
"""

import json

import pytest


@pytest.mark.live
class TestLiveIntegration:
    DASHBOARD = "http://192.168.137.252:18787"
    PROXY = "http://192.168.137.252:18788"

    def test_proxy_health(self):
        import urllib.request

        resp = urllib.request.urlopen(f"{self.PROXY}/health", timeout=5)
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

        resp = urllib.request.urlopen(f"{self.DASHBOARD}/api/stats", timeout=5)
        data = json.loads(resp.read().decode())
        assert isinstance(data, dict)

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
