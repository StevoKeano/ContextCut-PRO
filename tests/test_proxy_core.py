"""
Tests for proxy core functions: ``qdrant_context``, ``inject_context``, ``cache_key``, ``cache_get``, ``cache_put``.
"""

import json
import time
from unittest.mock import patch, MagicMock

import pytest


class TestQdrantContext:
    @patch("qdrant_proxy_final._safe_embed")
    @patch("qdrant_proxy_final.get_clients")
    def test_vector_hits(self, mock_get_clients, mock_safe_embed):
        from qdrant_proxy_final import qdrant_context

        mock_safe_embed.return_value = [0.1, 0.2, 0.3]
        qclient = MagicMock()
        mock_point = MagicMock()
        mock_point.score = 0.85
        mock_point.id = "pt1"
        mock_point.payload = {"filename": "doc.md", "text": "relevant content"}
        qclient.query_points.return_value.points = [mock_point]
        mock_get_clients.return_value = (None, qclient)

        ctx_str, meta = qdrant_context("test query")

        assert "relevant content" in ctx_str
        assert len(meta) == 1
        assert meta[0]["source"] == "doc.md"
        assert meta[0]["score"] == pytest.approx(0.85, abs=0.01)

    @patch("qdrant_proxy_final._safe_embed")
    @patch("qdrant_proxy_final.get_clients")
    def test_keyword_fallback(self, mock_get_clients, mock_safe_embed):
        from qdrant_proxy_final import qdrant_context

        mock_safe_embed.return_value = [0.1, 0.2, 0.3]
        qclient = MagicMock()
        vector_point = MagicMock()
        vector_point.score = 0.95
        vector_point.id = "pt1"
        vector_point.payload = {"filename": "doc.md", "text": "something"}
        qclient.query_points.return_value.points = [vector_point]

        kw_point = MagicMock()
        kw_point.id = "pt2"
        kw_point.payload = {"filename": "AliceInfo.md", "text": "Alice lives in Paris"}
        qclient.scroll.return_value = ([kw_point], None)

        mock_get_clients.return_value = (None, qclient)

        ctx_str, meta = qdrant_context("Tell me about Alice")

        assert len(meta) >= 1
        assert any(m.get("keyword") for m in meta)

    @patch("qdrant_proxy_final._safe_embed")
    @patch("qdrant_proxy_final.get_clients")
    def test_no_results(self, mock_get_clients, mock_safe_embed):
        from qdrant_proxy_final import qdrant_context

        mock_safe_embed.return_value = [0.1, 0.2, 0.3]
        qclient = MagicMock()
        qclient.query_points.return_value.points = []
        mock_get_clients.return_value = (None, qclient)

        ctx_str, meta = qdrant_context("something completely unknown")
        assert ctx_str == ""
        assert meta == []

    @patch("qdrant_proxy_final._safe_embed")
    def test_error_from_qdrant(self, mock_safe_embed):
        from qdrant_proxy_final import qdrant_context

        mock_safe_embed.side_effect = RuntimeError("Qdrant connection failed")

        ctx_str, meta = qdrant_context("test")
        assert ctx_str == ""
        assert meta == []

    @patch("qdrant_proxy_final._safe_embed")
    def test_embed_returns_none(self, mock_safe_embed):
        from qdrant_proxy_final import qdrant_context

        mock_safe_embed.return_value = None
        ctx_str, meta = qdrant_context("test")

        assert ctx_str == ""
        assert meta == []


class TestInjectContext:
    def test_with_context_string(self):
        from qdrant_proxy_final import inject_context

        body = {"messages": [{"role": "user", "content": "hello"}]}
        result = inject_context(body, "some relevant context")
        msgs = result["messages"]
        assert msgs[0]["role"] == "system"
        assert "Relevant context" in msgs[0]["content"]
        assert "some relevant context" in msgs[0]["content"]
        assert "helpful AI assistant" in msgs[0]["content"]

    def test_without_context(self):
        from qdrant_proxy_final import inject_context

        body = {"messages": [{"role": "user", "content": "hello"}]}
        result = inject_context(body, "")
        msgs = result["messages"]
        assert msgs[0]["role"] == "system"
        assert "Relevant context" not in msgs[0]["content"]
        assert "helpful AI assistant" in msgs[0]["content"]

    def test_with_existing_system_message(self):
        from qdrant_proxy_final import inject_context

        body = {
            "messages": [
                {"role": "system", "content": "You are a helpful bot."},
                {"role": "user", "content": "hello"},
            ]
        }
        result = inject_context(body, "relevant data")
        msgs = result["messages"]
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"].startswith("You are a helpful bot.")
        assert "Relevant context" in msgs[0]["content"]

    def test_preserves_user_message(self):
        from qdrant_proxy_final import inject_context

        body = {"messages": [{"role": "user", "content": "tell me stuff"}]}
        result = inject_context(body, "context")
        assert result["messages"][-1]["content"] == "tell me stuff"


class TestCache:
    def test_cache_key(self):
        from qdrant_proxy_final import cache_key

        k1 = cache_key("Hello World", "gpt-4")
        k2 = cache_key("  hello world  ", "gpt-4")
        assert k1 == k2
        assert "gpt-4:" in k1
        assert "hello world" in k1

    @patch("qdrant_proxy_final._response_cache", {})
    @patch("qdrant_proxy_final._stats", {"cache_hits": 0})
    def test_cache_round_trip(self):
        from qdrant_proxy_final import cache_put, cache_get

        cache_put("test query", "gpt-4", "response text")
        result = cache_get("test query", "gpt-4")
        assert result == "response text"

    @patch("qdrant_proxy_final._response_cache", {})
    @patch("qdrant_proxy_final._stats", {"cache_hits": 0})
    def test_cache_miss(self):
        from qdrant_proxy_final import cache_get

        result = cache_get("unknown query", "gpt-4")
        assert result is None

    @patch("qdrant_proxy_final._response_cache", {})
    @patch("qdrant_proxy_final._stats", {"cache_hits": 0})
    def test_cache_expired(self):
        from qdrant_proxy_final import cache_put, cache_get

        cache_put("stale", "gpt-4", "old data")
        from qdrant_proxy_final import _response_cache

        key = "gpt-4:stale"
        _response_cache[key]["ts"] = 0
        result = cache_get("stale", "gpt-4")
        assert result is None
