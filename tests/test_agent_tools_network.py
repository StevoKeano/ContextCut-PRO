"""
Tests for network agent tools: ``web_search``, ``fetch_url``.

Mocks DDGS (duckduckgo_search) and requests.get.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestWebSearch:
    @patch("ddgs.DDGS")
    def test_results(self, mock_ddgs_class):
        from agent_handler import web_search

        mock_ddgs = MagicMock()
        mock_ddgs.text.return_value = [
            {"title": "Result 1", "href": "https://example.com/1", "body": "Snippet 1"},
            {"title": "Result 2", "href": "https://example.com/2", "body": "Snippet 2"},
        ]
        mock_ddgs_class.return_value.__enter__.return_value = mock_ddgs

        result = web_search.invoke({"query": "test query", "max_results": 5})
        assert "Result 1" in result
        assert "Result 2" in result
        assert "example.com" in result

    @patch("ddgs.DDGS")
    def test_no_results(self, mock_ddgs_class):
        from agent_handler import web_search

        mock_ddgs = MagicMock()
        mock_ddgs.text.return_value = []
        mock_ddgs_class.return_value.__enter__.return_value = mock_ddgs

        result = web_search.invoke({"query": "zzzzzzzzz", "max_results": 5})
        assert "No results" in result

    @patch("ddgs.DDGS")
    def test_error(self, mock_ddgs_class):
        from agent_handler import web_search

        mock_ddgs_class.side_effect = RuntimeError("network error")
        result = web_search.invoke({"query": "anything", "max_results": 5})
        assert "error" in result.lower()


class TestFetchUrl:
    @patch("requests.get")
    def test_html_response(self, mock_get):
        from agent_handler import fetch_url

        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = "<html><body><p>Hello World</p></body></html>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_url.invoke({"url": "https://example.com", "timeout": 15})
        assert "Hello World" in result
        assert "<html>" not in result

    @patch("requests.get")
    def test_text_response(self, mock_get):
        from agent_handler import fetch_url

        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.text = "plain text content"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_url.invoke({"url": "https://example.com/plain", "timeout": 15})
        assert "plain text content" in result

    @patch("requests.get")
    def test_timeout(self, mock_get):
        from agent_handler import fetch_url

        mock_get.side_effect = TimeoutError("Connection timed out")
        result = fetch_url.invoke({"url": "https://example.com", "timeout": 1})
        assert "error" in result.lower() or "timed out" in result.lower()
