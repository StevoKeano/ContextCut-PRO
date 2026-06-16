"""
Tests for Qdrant agent tools: ``vector_search``, ``ingest_file``, ``list_knowledge``, ``delete_knowledge``.

Uses ``mock_qdrant_client`` fixture and patches ``agent_handler.qdrant_context`` for vector_search.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestVectorSearch:
    @patch("agent_handler.qdrant_context")
    def test_hits(self, mock_qdrant_context):
        from agent_handler import vector_search

        mock_qdrant_context.return_value = (
            "relevant context from kb",
            [{"source": "doc.md", "score": 0.85, "chars": 200}],
        )
        result = vector_search.invoke({"query": "test query", "top_k": 5})
        assert "relevant context" in result
        assert "score=0.850" in result or "score=0.85" in result

    @patch("agent_handler.qdrant_context")
    def test_no_results(self, mock_qdrant_context):
        from agent_handler import vector_search

        mock_qdrant_context.return_value = ("", [])
        result = vector_search.invoke({"query": "unknown", "top_k": 5})
        assert "No relevant context" in result

    @patch("agent_handler.qdrant_context")
    def test_empty_query(self, mock_qdrant_context):
        from agent_handler import vector_search

        mock_qdrant_context.return_value = ("", [])
        result = vector_search.invoke({"query": "", "top_k": 5})
        assert "No relevant context" in result


class TestIngestFile:
    @patch("qdrant_proxy_final._EMBED_MODEL", "default", create=True)
    @patch("agent_handler._run_subprocess")
    @patch("pathlib.Path")
    def test_success(self, mock_path, mock_run):
        from agent_handler import ingest_file

        p = MagicMock()
        p.__truediv__.return_value = p
        p.resolve.return_value = p
        p.__str__.return_value = "/fake/kb/test.md"
        p.exists.return_value = True
        mock_path.return_value = p
        mock_run.return_value = MagicMock(returncode=0, stdout="ingested", stderr="")
        result = ingest_file.invoke({"filename": "test.md"})
        assert "success" in result.lower()

    @patch("qdrant_proxy_final._EMBED_MODEL", "default", create=True)
    @patch("agent_handler.Path")
    def test_file_not_found(self, mock_path):
        from agent_handler import ingest_file

        p = MagicMock()
        p.resolve.return_value = "/fake/kb/test.md"
        parent = MagicMock()
        parent.resolve.return_value = "/fake/kb"
        p.parent = parent
        mock_path.return_value = p
        from pathlib import Path

        p.exists.return_value = False
        result = ingest_file.invoke({"filename": "nonexistent.md"})
        assert "not found" in result.lower()

    @patch("qdrant_proxy_final._EMBED_MODEL", "default", create=True)
    @patch("agent_handler.Path")
    def test_path_traversal(self, mock_path):
        from agent_handler import ingest_file

        p = MagicMock()
        p.resolve.return_value = "/etc/passwd"
        parent = MagicMock()
        parent.resolve.return_value = "/fake/kb"
        p.parent = parent
        mock_path.return_value = p


class TestListKnowledge:
    @patch("qdrant_client.QdrantClient")
    def test_with_points(self, mock_qclient_class):
        from agent_handler import list_knowledge

        mock_client = MagicMock()
        mock_client.get_collection.return_value.points_count = 10
        pt1 = MagicMock()
        pt1.payload = {"source": "doc1.md"}
        pt2 = MagicMock()
        pt2.payload = {"source": "doc2.md"}
        mock_client.scroll.return_value = ([pt1, pt2], None)
        mock_qclient_class.return_value = mock_client

        result = list_knowledge.invoke({})
        assert "doc1.md" in result
        assert "doc2.md" in result

    @patch("qdrant_client.QdrantClient")
    def test_empty_collection(self, mock_qclient_class):
        from agent_handler import list_knowledge

        mock_client = MagicMock()
        mock_client.get_collection.return_value.points_count = 0
        mock_client.scroll.return_value = ([], None)
        mock_qclient_class.return_value = mock_client

        result = list_knowledge.invoke({})
        assert "empty" in result.lower()


class TestDeleteKnowledge:
    @patch("qdrant_client.QdrantClient")
    def test_success(self, mock_qclient_class):
        from agent_handler import delete_knowledge

        mock_client = MagicMock()
        mock_qclient_class.return_value = mock_client
        result = delete_knowledge.invoke({"filename": "test.md"})
        assert "Deleted" in result

    @patch("qdrant_client.QdrantClient")
    def test_error(self, mock_qclient_class):
        from agent_handler import delete_knowledge

        mock_client = MagicMock()
        mock_client.delete.side_effect = RuntimeError("Qdrant error")
        mock_qclient_class.return_value = mock_client
        result = delete_knowledge.invoke({"filename": "test.md"})
        assert "error" in result.lower()
