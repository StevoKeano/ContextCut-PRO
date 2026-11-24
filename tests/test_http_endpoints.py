"""
Tests for HTTP endpoint routing of ``DashboardHandler`` and ``ProxyHandler``.

Uses the ``make_handler`` fixture to construct handlers without a running server.
"""

import asyncio
import json
import urllib.error
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
        assert b"https://github.com/StevoKeano/ContextCut-PRO/blob/main/README.md" in raw

    def test_agent_kb_enabled_helper(self, monkeypatch):
        import qdrant_proxy_final as qpf

        monkeypatch.setattr(qpf, "AGENT_KB_DEFAULT", False)
        assert qpf.agent_kb_enabled({}) is False
        assert qpf.agent_kb_enabled({"kb": False}) is False
        assert qpf.agent_kb_enabled({"kb": True}) is True
        monkeypatch.setattr(qpf, "AGENT_KB_DEFAULT", True)
        assert qpf.agent_kb_enabled({}) is True

    def test_dashboard_has_agent_kb_toggle(self, make_handler):
        status, raw = make_handler("/", "GET")
        assert status == 200
        html = raw.decode("utf-8", errors="replace")
        assert 'id="kbToggle"' in html
        assert "function toggleAgentKb()" in html
        assert "cc_agentKbMode" in html
        assert "kb: agentKbMode" in html

    def test_dashboard_unattended_label_visibility_targets_label(self, make_handler):
        status, raw = make_handler("/", "GET")
        assert status == 200
        html = raw.decode("utf-8", errors="replace")
        assert 'id="unattendedLbl"' in html
        load_state = html.split("function loadState() {", 1)[1].split(
            "function resetDefaults()", 1
        )[0]
        assert "getElementById('unattendedLbl')" in load_state
        assert "getElementById('unattendedChk')" not in load_state
        assert "async function syncShellModeFromUi()" in html
        assert "initSession().then(() => syncShellModeFromUi())" in html

    def test_dashboard_has_timeout_dropdown(self, make_handler):
        status, raw = make_handler("/", "GET")
        assert status == 200
        html = raw.decode("utf-8", errors="replace")
        assert 'id="timeoutSelect"' in html
        assert 'id="timeoutVal"' in html
        assert "function updateAgentTimeout(" in html
        assert "let clientTimeoutMs =" in html

    def test_dashboard_has_opencode_controls(self, make_handler):
        status, raw = make_handler("/", "GET")
        assert status == 200
        html = raw.decode("utf-8", errors="replace")
        assert 'id="opencodeToggle"' in html
        assert 'id="opencodeCacheChk"' in html
        assert 'id="opencodeNextRunHint"' in html
        assert 'id="agentWorkspaceInput"' in html
        assert 'id="agentWorkspaceHint"' in html
        assert "applies to the next run" in html
        assert "function toggleOpenCodeMode(" in html
        assert "function setOpenCodeCache(" in html
        assert "function setWorkspace(" in html
        assert "data.type === 'done'" in html
        assert "toolCount" in html
        assert ".bubble:empty" in html

    def test_dashboard_has_live_status_indicator(self, make_handler):
        status, raw = make_handler("/", "GET")
        assert status == 200
        html = raw.decode("utf-8", errors="replace")
        assert "function setTypingStatus(status)" in html
        assert "_typingTimer = setInterval(" in html
        assert "data.type === 'phase'" in html
        assert "setTypingStatus('Waiting for approval…')" in html
        assert "setTypingStatus('Writing response…')" in html
        assert ".typing span.typing-status" in html

    def test_settings_returns_html(self, make_handler):
        status, raw = make_handler("/settings", "GET")
        assert status == 200
        assert b"Settings" in raw or b"settings" in raw.lower() or b"Provider" in raw
        assert b"https://github.com/StevoKeano/ContextCut-PRO/blob/main/README.md" in raw

    def test_settings_model_list_defines_esc(self, make_handler):
        status, raw = make_handler("/settings", "GET")
        assert status == 200
        html = raw.decode("utf-8", errors="replace")
        assert "function esc(" in html
        assert "esc(m)" in html

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

    def test_settings_agent_timeout(self, make_handler, monkeypatch):
        import qdrant_proxy_final as qpf

        monkeypatch.setattr(qpf, "_persist_env_key", lambda *a, **k: None)
        old_agent, old_client = qpf.AGENT_TIMEOUT, qpf.CLIENT_TIMEOUT_MS
        monkeypatch.setenv("CONTEXTCUT_AGENT_TIMEOUT", str(old_agent))
        monkeypatch.setenv("CONTEXTCUT_CLIENT_TIMEOUT", str(old_client // 1000))
        try:
            body = json.dumps({"agent_timeout": 1800}).encode()
            status, raw = make_handler("/api/settings", "POST", body)
            assert status == 200
            data = json.loads(raw.split(b"\r\n\r\n", 1)[-1])
            assert data["agent_timeout"] == 1800
            assert data["client_timeout_ms"] == 1800 * 1000
            assert qpf.AGENT_TIMEOUT == 1800
            assert qpf.CLIENT_TIMEOUT_MS == 1800 * 1000
        finally:
            qpf.AGENT_TIMEOUT = old_agent
            qpf.CLIENT_TIMEOUT_MS = old_client

    def test_settings_opencode_toggles(self, make_handler, monkeypatch):
        import qdrant_proxy_final as qpf

        monkeypatch.setattr(qpf, "_persist_env_key", lambda *a, **k: None)
        old_use, old_cache = qpf.USE_OPENCODE, qpf.OPENCODE_CACHE
        monkeypatch.setenv("CONTEXTCUT_USE_OPENCODE", "1" if old_use else "0")
        monkeypatch.setenv("CONTEXTCUT_OPENCODE_CACHE", "1" if old_cache else "0")
        try:
            body = json.dumps({"use_opencode": True}).encode()
            status, raw = make_handler("/api/settings", "POST", body)
            assert status == 200
            data = json.loads(raw.split(b"\r\n\r\n", 1)[-1])
            assert data["use_opencode"] is True
            assert qpf.USE_OPENCODE is True

            body = json.dumps({"opencode_cache": True}).encode()
            status, raw = make_handler("/api/settings", "POST", body)
            assert status == 200
            data = json.loads(raw.split(b"\r\n\r\n", 1)[-1])
            assert data["opencode_cache"] is True
            assert qpf.OPENCODE_CACHE is True
        finally:
            qpf.USE_OPENCODE = old_use
            qpf.OPENCODE_CACHE = old_cache

    def test_settings_workspace(self, make_handler, monkeypatch, tmp_path):
        import agent_handler
        import qdrant_proxy_final as qpf

        persisted = []
        monkeypatch.setattr(
            qpf, "_persist_env_key", lambda k, v: persisted.append((k, v))
        )
        old_agent_ws = qpf.AGENT_WORKSPACE
        old_oc_ws = qpf.OPENCODE_WORKSPACE
        old_handler_ws = agent_handler.AGENT_WORKSPACE
        monkeypatch.setenv("CONTEXTCUT_AGENT_WORKSPACE", old_agent_ws)
        monkeypatch.setenv("CONTEXTCUT_OPENCODE_WORKSPACE", old_oc_ws)
        try:
            body = json.dumps({"workspace": str(tmp_path)}).encode()
            status, raw = make_handler("/api/settings", "POST", body)
            assert status == 200
            data = json.loads(raw.split(b"\r\n\r\n", 1)[-1])
            expected = str(tmp_path.resolve())
            assert data["workspace"] == expected
            assert qpf.AGENT_WORKSPACE == expected
            assert qpf.OPENCODE_WORKSPACE == expected
            assert agent_handler.AGENT_WORKSPACE == tmp_path.resolve()
            assert ("CONTEXTCUT_AGENT_WORKSPACE", expected) in persisted
            assert ("CONTEXTCUT_OPENCODE_WORKSPACE", expected) in persisted
        finally:
            qpf.AGENT_WORKSPACE = old_agent_ws
            qpf.OPENCODE_WORKSPACE = old_oc_ws
            agent_handler.AGENT_WORKSPACE = old_handler_ws

    def test_settings_workspace_rejects_missing_dir(
        self, make_handler, monkeypatch, tmp_path
    ):
        import qdrant_proxy_final as qpf

        monkeypatch.setattr(qpf, "_persist_env_key", lambda *a, **k: None)
        old_agent_ws = qpf.AGENT_WORKSPACE
        old_oc_ws = qpf.OPENCODE_WORKSPACE
        try:
            body = json.dumps({"workspace": str(tmp_path / "missing")}).encode()
            status, _ = make_handler("/api/settings", "POST", body)
            assert status == 400
            assert qpf.AGENT_WORKSPACE == old_agent_ws
            assert qpf.OPENCODE_WORKSPACE == old_oc_ws
        finally:
            qpf.AGENT_WORKSPACE = old_agent_ws
            qpf.OPENCODE_WORKSPACE = old_oc_ws

    def test_agent_opencode_non_stream_does_not_shadow_asyncio(
        self, make_handler, monkeypatch
    ):
        import qdrant_proxy_final as qpf

        class _FakeCheckpointManager:
            def __init__(self, *args, **kwargs):
                pass

            def exists(self, task_id):
                return False

            def save_task_meta(self, *args, **kwargs):
                return None

            def build_resume_context(self, task_id):
                return None

        async def fake_run(prompt, **kwargs):
            return ("opencode ok", "")

        monkeypatch.setattr(qpf, "USE_OPENCODE", True)
        monkeypatch.setattr(qpf, "OPENCODE_CACHE", False)
        monkeypatch.setattr(qpf, "_run_opencode_chat", fake_run)
        monkeypatch.setattr("agent_handler.CheckpointManager", _FakeCheckpointManager)

        body = json.dumps(
            {"message": "hello", "stream": False, "model": "test-model"}
        ).encode()
        status, raw = make_handler("/api/agent", "POST", body)
        assert status == 200
        data = json.loads(raw.split(b"\r\n\r\n", 1)[-1])
        assert data["response"] == "opencode ok"

    def test_settings_agent_timeout_clamped(self, make_handler, monkeypatch):
        import qdrant_proxy_final as qpf

        monkeypatch.setattr(qpf, "_persist_env_key", lambda *a, **k: None)
        old_agent, old_client = qpf.AGENT_TIMEOUT, qpf.CLIENT_TIMEOUT_MS
        monkeypatch.setenv("CONTEXTCUT_AGENT_TIMEOUT", str(old_agent))
        monkeypatch.setenv("CONTEXTCUT_CLIENT_TIMEOUT", str(old_client // 1000))
        try:
            body = json.dumps({"agent_timeout": 99999}).encode()
            status, raw = make_handler("/api/settings", "POST", body)
            assert status == 200
            data = json.loads(raw.split(b"\r\n\r\n", 1)[-1])
            assert data["agent_timeout"] == 7200
            assert qpf.AGENT_TIMEOUT == 7200
        finally:
            qpf.AGENT_TIMEOUT = old_agent
            qpf.CLIENT_TIMEOUT_MS = old_client

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

    # ── Upstream retry (POST-only) ──────────────────────────────────────────

    @staticmethod
    def _fake_resp(status=200, body=b'{"choices":[{"message":{"content":"hi"}}]}'):
        import io as _io

        class _FakeResp:
            def __init__(self):
                self.status = status

            def getheaders(self):
                return [("Content-Type", "application/json")]

            def read(self, n=None):
                return body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def close(self):
                pass

        return _FakeResp()

    @staticmethod
    def _fake_http_error(code):
        import io as _io

        return urllib.error.HTTPError(
            "http://upstream", code, "err", None, _io.BytesIO(b"boom")
        )

    @patch("qdrant_proxy_final.qdrant_context", return_value=("", []))
    @patch("qdrant_proxy_final.add_to_history")
    @patch("qdrant_proxy_final.time.sleep")
    def test_post_retries_then_succeeds(self, mock_sleep, mock_history, mock_qd, make_handler):
        """Network error twice, then success — should retry and return 200."""
        from qdrant_proxy_final import ProxyHandler

        fail = urllib.error.URLError("connection reset")
        ok = TestProxyHandler._fake_resp()
        with patch(
            "qdrant_proxy_final.urllib.request.urlopen",
            side_effect=[fail, fail, ok],
        ) as m_urlopen:
            status, _ = make_handler(
                "/v1/chat/completions", "POST",
                b'{"messages":[{"role":"user","content":"hi"}],"model":"m"}',
                handler_cls=ProxyHandler,
            )
        assert status == 200
        assert m_urlopen.call_count == 3

    @patch("qdrant_proxy_final.qdrant_context", return_value=("", []))
    @patch("qdrant_proxy_final.add_to_history")
    @patch("qdrant_proxy_final.time.sleep")
    def test_post_5xx_retries_then_passthrough(self, mock_sleep, mock_history, mock_qd, make_handler):
        """Three 5xx responses — retries then returns the last 5xx code."""
        from qdrant_proxy_final import ProxyHandler

        with patch(
            "qdrant_proxy_final.urllib.request.urlopen",
            side_effect=[
                TestProxyHandler._fake_http_error(502),
                TestProxyHandler._fake_http_error(503),
                TestProxyHandler._fake_http_error(504),
            ],
        ) as m_urlopen:
            status, raw = make_handler(
                "/v1/chat/completions", "POST",
                b'{"messages":[{"role":"user","content":"hi"}],"model":"m"}',
                handler_cls=ProxyHandler,
            )
        assert status == 504
        assert m_urlopen.call_count == 3

    @patch("qdrant_proxy_final.qdrant_context", return_value=("", []))
    @patch("qdrant_proxy_final.add_to_history")
    @patch("qdrant_proxy_final.time.sleep")
    def test_post_4xx_no_retry(self, mock_sleep, mock_history, mock_qd, make_handler):
        """400 — client error, no retry, single call."""
        from qdrant_proxy_final import ProxyHandler

        with patch(
            "qdrant_proxy_final.urllib.request.urlopen",
            side_effect=[TestProxyHandler._fake_http_error(400)],
        ) as m_urlopen:
            status, _ = make_handler(
                "/v1/chat/completions", "POST",
                b'{"messages":[{"role":"user","content":"hi"}],"model":"m"}',
                handler_cls=ProxyHandler,
            )
        assert status == 400
        assert m_urlopen.call_count == 1

    @patch("qdrant_proxy_final.time.sleep")
    def test_get_no_retry(self, mock_sleep, make_handler):
        """GET requests are NOT retried (POST-only policy)."""
        from qdrant_proxy_final import ProxyHandler

        with patch(
            "qdrant_proxy_final.urllib.request.urlopen",
            side_effect=urllib.error.URLError("down"),
        ) as m_urlopen:
            status, _ = make_handler("/v1/models", "GET", handler_cls=ProxyHandler)
        assert status == 502
        assert m_urlopen.call_count == 1


def test_opencode_chat_stream_parses_text_and_forwards_tokens(tmp_path, monkeypatch):
    import qdrant_proxy_final as qpf

    lines = [
        json.dumps({"type": "text", "part": {"text": "hello"}}) + "\n",
        json.dumps({"type": "tool_use", "part": {"tool": "bash"}}) + "\n",
        json.dumps({"type": "text", "part": {"text": " world"}}) + "\n",
    ]
    captured = {}

    class _Stream:
        def __init__(self, data=b""):
            self._lines = list(lines)
            self._data = data

        async def readline(self):
            return self._lines.pop(0).encode() if self._lines else b""

        async def read(self):
            return self._data

    class _Proc:
        returncode = None

        def __init__(self):
            self.stdout = _Stream()
            self.stderr = _Stream()

        async def wait(self):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return _Proc()

    monkeypatch.setattr(qpf.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(qpf, "OPENCODE_WORKSPACE", str(tmp_path))

    events = []
    output, error = asyncio.run(
        qpf._run_opencode_chat("hello", model="provider/model", cache=True, emit=events.append)
    )

    assert error == ""
    assert output == "hello\n world"
    assert {"token": "hello"} in events
    assert {"token": " world"} in events
    assert any(e.get("name") == "bash" for e in events)
    assert "-c" in captured["cmd"]
    assert "--model" in captured["cmd"]
    assert captured["cwd"] == str(tmp_path)


def test_agent_completion_text_fallback():
    import qdrant_proxy_final as qpf

    assert (
        qpf.agent_completion_text(0)
        == "✅ Agent finished but returned no textual response."
    )
    assert (
        qpf.agent_completion_text(1)
        == "✅ Agent finished after 1 tool call, but returned no textual summary."
    )
    assert "after 3 tool calls" in qpf.agent_completion_text(3)


def test_agent_completion_text_with_tool_records():
    import qdrant_proxy_final as qpf

    text = qpf.agent_completion_text(
        3,
        goal="Build an Electromagnetics learning app",
        tool_records=[
            {"name": "run_python", "result": "VSWR = 1.5, Gamma = 0.2"},
        ],
    )
    assert "Build an Electromagnetics learning app" in text
    assert "run_python: VSWR = 1.5" in text
    assert "3 tool calls" in text


def test_agent_merge_text_state_keeps_best_text_on_tool_only_turn():
    import qdrant_proxy_final as qpf

    full, best, after = qpf.agent_merge_text_state(
        "Created the app.",
        "Created the app.",
        "Created the app.",
        "",
        "",
    )
    assert full == "Created the app."
    assert best == "Created the app."
    assert after == "Created the app."


def test_agent_text_after_last_tool():
    import qdrant_proxy_final as qpf

    timeline = [
        ("text", "Planning."),
        ("tool", "run_python"),
        ("text", "Created the sample problem."),
    ]
    assert qpf.agent_text_after_last_tool(timeline) == "Created the sample problem."
    assert qpf.agent_text_after_last_tool([("text", "No tools used.")]) == ""


def test_system_prompt_requires_final_answer_after_tools():
    import agent_handler

    assert "FINAL ANSWER IS REQUIRED" in agent_handler.SYSTEM_PROMPT


def test_system_prompt_has_tool_efficiency_rule():
    import agent_handler

    assert "TOOL-EFFICIENCY RULE:" in agent_handler.SYSTEM_PROMPT
    assert (
        "- When editing or appending to an existing file, inspect only the target "
        "region once (e.g., via `read_file`) before writing."
    ) in agent_handler.SYSTEM_PROMPT
    assert (
        "- NEVER use `run_python` to print or inspect file contents or line "
        "ranges: no `open(...).read()`, `.readlines()`, `.splitlines()`, or "
        "`Path(...).read_text()`."
    ) in agent_handler.SYSTEM_PROMPT
    assert (
        "- When extending an existing file, immediately call `append_file` with "
        "the next <= 100-line chunk"
    ) in agent_handler.SYSTEM_PROMPT
    assert (
        "- When harness tail context is provided (`Tail of <path> (lines N-M):`)"
    ) in agent_handler.SYSTEM_PROMPT


def test_strata_chat_defaults_include_reasoning_budget(monkeypatch):
    import qdrant_proxy_final as qpf

    monkeypatch.setattr(
        qpf, "get_current_upstream", lambda: "http://192.168.137.1:8080"
    )
    monkeypatch.setattr(qpf, "_provider_name", "Custom")
    body = {"model": "deepseek-v4.1-flash", "max_tokens": 16384}
    out = qpf._apply_strata_reasoning_defaults(body)
    assert out["reasoning_effort"] == "low"
    assert out["reasoning_budget_tokens"] == 256
    assert out["max_tokens"] == 16384


def test_strata_chat_defaults_respect_explicit_settings(monkeypatch):
    import qdrant_proxy_final as qpf

    monkeypatch.setattr(qpf, "get_current_upstream", lambda: "http://strata.local:8080")
    monkeypatch.setattr(qpf, "_provider_name", "Custom")
    body = {
        "model": "deepseek-v4.1-flash",
        "reasoning_effort": "medium",
        "reasoning_budget_tokens": 512,
    }
    assert qpf._apply_strata_reasoning_defaults(body)["reasoning_budget_tokens"] == 512

    disabled = {
        "model": "deepseek-v4.1-flash",
        "reasoning_effort": "none",
    }
    assert qpf._apply_strata_reasoning_defaults(disabled) == disabled


def test_non_strata_chat_is_unchanged(monkeypatch):
    import qdrant_proxy_final as qpf

    monkeypatch.setattr(qpf, "get_current_upstream", lambda: "http://localhost:11434")
    monkeypatch.setattr(qpf, "_provider_name", "Ollama")
    body = {"model": "qwen3:14b-q8_0", "max_tokens": 8192}
    assert qpf._apply_strata_reasoning_defaults(body) == body


def test_dashboard_migrates_stale_max_tokens(make_handler):
    status, raw = make_handler("/", "GET")
    assert status == 200
    assert b"cc_maxTokBudgetMigrated" in raw
