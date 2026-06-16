"""
Tests for HTTP endpoint routing of ``DashboardHandler`` and ``ProxyHandler``.

Uses the ``make_handler`` fixture to construct handlers without a running server.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


class TestDashboardHandlerGET:
    @pytest.fixture(autouse=True)
    def _reset_state(self):
        """Reset module-level state before each test."""
        from qdrant_proxy_final import _log, _stats, _sessions, _response_cache

        _log.clear()
        _sessions.clear()
        _response_cache.clear()
        _stats.update(
            {
                "total_requests": 0,
                "total_saved": 0,
                "max_tokens_seen": 0,
                "last_seen": None,
                "start_time": "2025-01-01T00:00:00",
                "cache_hits": 0,
            }
        )

    @pytest.mark.parametrize(
        "path, expected_key",
        [
            ("/stats", "total_requests"),
            ("/api/agent/tools", "tools"),
            ("/api/embed/config", "mode"),
            ("/api/session/new", "session_id"),
            ("/api/license", "valid"),
            ("/api/context/clear", "ok"),
            ("/log", None),
        ],
    )
    def test_routes_return_json(self, make_handler, path, expected_key):
        status, raw = make_handler(path, "GET")
        assert status == 200, f"{path} returned {status}"
        if expected_key:
            body = json.loads(raw.split(b"\r\n\r\n", 1)[-1] if b"\r\n\r\n" in raw else raw)
            assert expected_key in body, f"key {expected_key} not in response for {path}"

    def test_dashboard_returns_html(self, make_handler):
        status, raw = make_handler("/", "GET")
        assert status == 200
        assert b"ContextCut" in raw

    def test_settings_returns_html(self, make_handler):
        status, raw = make_handler("/settings", "GET")
        assert status == 200
        assert b"Settings" in raw or b"settings" in raw.lower() or b"Provider" in raw

    @patch("qdrant_proxy_final.QDRANT_HOST", "localhost")
    @patch("qdrant_proxy_final.QDRANT_PORT", 6333)
    @patch("qdrant_proxy_final.KB_DIR", Path("/tmp/kb"))
    def test_knowledge_file_serving(self, make_handler):
        from qdrant_proxy_final import KB_DIR, ALLOWED_EXT

        kbd = KB_DIR
        kbd.mkdir(parents=True, exist_ok=True)
        test_file = kbd / "test.md"
        test_file.write_text("# Hello")
        status, raw = make_handler("/knowledge/test.md", "GET")
        assert status == 200
        assert b"Hello" in raw

    def test_knowledge_forbidden(self, make_handler):
        status, raw = make_handler("/knowledge/../../../etc/passwd", "GET")
        assert status == 403

    def test_knowledge_not_found(self, make_handler):
        status, raw = make_handler("/knowledge/nonexistent.md", "GET")
        assert status == 404

    def test_export_csv(self, make_handler):
        from qdrant_proxy_final import _log

        _log.append(
            {
                "ts": "12:00:00",
                "query": "test query",
                "tokens_before": 100,
                "tokens_after": 50,
                "pct": 50.0,
                "hits": [{"source": "doc.md", "score": 0.85}],
                "type": "normal",
            }
        )
        status, raw = make_handler("/api/logs/export", "GET")
        assert status == 200
        assert b"test query" in raw
        assert b"doc" in raw


class TestDashboardHandlerPOST:
    @pytest.fixture(autouse=True)
    def _reset_state(self):
        from qdrant_proxy_final import _log, _stats, _sessions, _response_cache

        _log.clear()
        _sessions.clear()
        _response_cache.clear()
        _stats.update(
            {
                "total_requests": 0,
                "total_saved": 0,
                "max_tokens_seen": 0,
                "last_seen": None,
                "start_time": "2025-01-01T00:00:00",
                "cache_hits": 0,
            }
        )

    def test_shell_mode_get(self, make_handler):
        status, raw = make_handler("/api/agent/shell-mode", "GET")
        assert status == 405 or status == 200

    def test_shell_mode_post(self, make_handler):
        body = json.dumps({"session_id": None, "mode": "always"}).encode()
        status, raw = make_handler("/api/agent/shell-mode", "POST", body)
        assert status == 200
        data = json.loads(raw.split(b"\r\n\r\n", 1)[-1])
        assert data.get("ok") or data.get("mode") == "always"

    def test_confidence_scan_no_text(self, make_handler):
        body = json.dumps({"text": ""}).encode()
        status, raw = make_handler("/api/agent/confidence-scan", "POST", body)
        assert status == 400

    def test_settings_min_score(self, make_handler):
        body = json.dumps({"min_score": 0.75}).encode()
        status, raw = make_handler("/api/settings", "POST", body)
        assert status == 200
        from qdrant_proxy_final import MIN_SCORE

        assert MIN_SCORE == pytest.approx(0.75, abs=0.01)

    def test_settings_top_k(self, make_handler):
        body = json.dumps({"top_k": 10}).encode()
        status, raw = make_handler("/api/settings", "POST", body)
        assert status == 200
        from qdrant_proxy_final import TOP_K

        assert TOP_K == 10

    @patch("qdrant_proxy_final.CredentialManager")
    def test_embed_config(self, mock_creds, make_handler):
        body = json.dumps({"mode": "ollama", "ollama_model": "nomic-embed-text"}).encode()
        status, raw = make_handler("/api/embed/config", "POST", body)
        assert status == 400 or status == 200

    def test_agent_no_message(self, make_handler):
        body = json.dumps({"message": "", "session_id": None}).encode()
        status, raw = make_handler("/api/agent", "POST", body)
        assert status == 400


class TestProxyHandler:
    def test_blocked_paths(self, make_handler):
        from qdrant_proxy_final import ProxyHandler

        for path in ["/api/pull", "/api/push", "/api/delete", "/api/copy", "/api/create"]:
            status, raw = make_handler(path, "POST", b'{"model": "test"}', handler_cls=ProxyHandler)
            assert status == 403, f"{path} should be blocked"
            assert b"Blocked" in raw

    def test_delete_session(self, make_handler):
        from qdrant_proxy_final import ProxyHandler

        status, raw = make_handler("/api/session/test123", "DELETE", handler_cls=ProxyHandler)
        assert status == 200
        assert b"cleared" in raw
