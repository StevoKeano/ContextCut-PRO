"""
Tests for meta agent tools: ``plan``, ``compose_tool``, ``get_context_logs``, ``get_session_stats``, ``run_sql``.
"""

import json
from unittest.mock import MagicMock, patch

import pytest


class TestPlan:
    def test_with_context(self):
        from agent_handler import plan

        result = plan.invoke({"objective": "build a web app", "context": "React + Flask"})
        assert "build a web app" in result
        assert "React + Flask" in result
        assert "Analyze" in result

    def test_without_context(self):
        from agent_handler import plan

        result = plan.invoke({"objective": "write tests", "context": ""})
        assert "write tests" in result
        assert "Analyze" in result


class TestComposeTool:
    def test_valid_json_steps(self):
        from agent_handler import compose_tool, COMPOUND_TOOLS

        COMPOUND_TOOLS.clear()
        steps = json.dumps(
            [
                {"tool": "vector_search", "input": {"query": "topic", "top_k": 3}},
                {"tool": "web_search", "input": {"query": "topic recent"}},
            ]
        )
        result = compose_tool.invoke({"name": "research", "description": "research topic", "steps": steps})
        assert "created" in result.lower()
        assert "research" in COMPOUND_TOOLS

    def test_invalid_json(self):
        from agent_handler import compose_tool

        result = compose_tool.invoke({"name": "bad", "description": "desc", "steps": "not json"})
        assert "Invalid JSON" in result

    def test_missing_tool_in_step(self):
        from agent_handler import compose_tool

        result = compose_tool.invoke({"name": "bad2", "description": "desc", "steps": json.dumps([{"input": {"x": 1}}])})
        assert "tool" in result.lower()

    def test_nonexistent_tool(self):
        from agent_handler import compose_tool

        steps = json.dumps([{"tool": "nonexistent_tool", "input": {"x": 1}}])
        result = compose_tool.invoke({"name": "fail", "description": "desc", "steps": steps})
        assert "not a valid" in result.lower()


class TestGetContextLogs:
    @patch("qdrant_proxy_final._sessions", new_callable=dict)
    def test_session_with_messages(self, mock_s):
        from agent_handler import get_context_logs

        mock_s["test123"] = {
            "history": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
            "msg_count": 2,
        }
        result = get_context_logs.invoke({"session_id": "test123"})
        assert "hello" in result
        assert "hi" in result

    @patch("qdrant_proxy_final._sessions", new_callable=dict)
    def test_empty_session(self, mock_s):
        from agent_handler import get_context_logs

        mock_s["empty"] = {"history": [], "msg_count": 0}
        result = get_context_logs.invoke({"session_id": "empty"})
        assert "no messages" in result.lower()

    @patch("qdrant_proxy_final._sessions", new_callable=dict)
    def test_missing_session(self, mock_s):
        from agent_handler import get_context_logs

        result = get_context_logs.invoke({"session_id": "unknown"})
        assert "No active sessions" in result


class TestGetSessionStats:
    @patch("qdrant_proxy_final._sessions", new_callable=dict)
    @patch("qdrant_proxy_final.count_tokens", return_value=5)
    @patch("qdrant_proxy_final.CTX_LIMIT", 16384)
    def test_with_messages(self, mock_cnt, mock_s):
        from agent_handler import get_session_stats

        mock_s["test123"] = {"history": [{"role": "user", "content": "hello"}], "msg_count": 1, "created": "2025-01-01"}
        result = get_session_stats.invoke({"session_id": "test123"})
        assert "test123" in result
        assert "5" in result
        assert "16384" in result

    @patch("qdrant_proxy_final._sessions", new_callable=dict)
    @patch("qdrant_proxy_final.count_tokens", return_value=0)
    @patch("qdrant_proxy_final.CTX_LIMIT", 16384)
    def test_empty_session(self, mock_cnt, mock_s):
        from agent_handler import get_session_stats

        mock_s["empty"] = {"history": [], "msg_count": 0, "created": "2025-01-01"}
        result = get_session_stats.invoke({"session_id": "empty"})
        assert "0" in result


class TestRunSql:
    def test_select_returns_rows(self, mock_sqlite):
        from agent_handler import run_sql

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [{"name": "Alice"}]
        mock_sqlite.return_value.execute.return_value = mock_cursor
        mock_sqlite.return_value.row_factory = None

        result = run_sql.invoke({"query": "SELECT name FROM agents"})
        assert "Alice" in result

    def test_select_returns_empty(self, mock_sqlite):
        from agent_handler import run_sql

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_sqlite.return_value.execute.return_value = mock_cursor

        result = run_sql.invoke({"query": "SELECT name FROM agents"})
        assert "no results" in result.lower()

    def test_non_select_rejected(self, mock_sqlite):
        from agent_handler import run_sql

        result = run_sql.invoke({"query": "DROP TABLE agents"})
        assert "Only SELECT" in result
        mock_sqlite.assert_not_called()
