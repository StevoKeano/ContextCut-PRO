"""
Tests for the ContextCut-PRO MCP Knowledge Server.
"""

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastmcp")

from mcp_knowledge_server import (
    _chunk_text,
    _should_ingest,
    _sanitize_text,
    _extract_text,
    _file_content_hash,
    _is_file_current,
    ALLOWED_EXT,
    knowledge_search,
    knowledge_search_structured,
    knowledge_list_files,
    knowledge_stats,
    ingest_file,
    ingest_all,
    ingest_status,
    resource_files,
    resource_stats,
    resource_search,
)


# ── Tests ─────────────────────────────────────────────────────────────────


def test_import():
    """Module imports without error."""
    import mcp_knowledge_server
    assert hasattr(mcp_knowledge_server, "knowledge_search")


class TestSearchTools:
    @patch("mcp_knowledge_server.qdrant_context")
    def test_knowledge_search(self, mock_qdrant):
        """knowledge_search returns formatted context string."""
        mock_qdrant.return_value = (
            "Relevant chunk of text here.",
            [{"source": "doc.md", "score": 0.85}],
        )
        result = knowledge_search(query="test query", top_k=3)
        assert "Relevant chunk" in result
        assert "doc.md" in result
        assert "0.850" in result

    @patch("mcp_knowledge_server.qdrant_context")
    def test_knowledge_search_no_results(self, mock_qdrant):
        """knowledge_search returns clear message when nothing found."""
        mock_qdrant.return_value = ("", [])
        result = knowledge_search(query="nothing")
        assert "No relevant context" in result

    @patch("mcp_knowledge_server.qdrant_context")
    def test_search_structured(self, mock_qdrant):
        """knowledge_search_structured returns list of dicts."""
        mock_qdrant.return_value = (
            "Chunk A.\n\n---\n\nChunk B.",
            [{"source": "a.md", "score": 0.9}, {"source": "b.md", "score": 0.7}],
        )
        result = knowledge_search_structured(query="test", top_k=5)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["source"] == "a.md"
        assert result[0]["score"] == 0.9
        assert "Chunk A" in result[0]["text"]

    @patch("mcp_knowledge_server.qdrant_context")
    def test_search_structured_no_results(self, mock_qdrant):
        """knowledge_search_structured returns empty list when nothing found."""
        mock_qdrant.return_value = ("", [])
        assert knowledge_search_structured(query="nothing") == []


class TestListFiles:
    @patch("mcp_knowledge_server.KB_DIR", new_callable=lambda: Path("/tmp/mcp_test_kb"))
    def test_knowledge_list_files(self, mock_kb_dir):
        """knowledge_list_files returns files from KB_DIR."""
        mock_kb_dir.mkdir(parents=True, exist_ok=True)
        (mock_kb_dir / "test.md").write_text("hello")
        (mock_kb_dir / "data.csv").write_text("a,b,c")
        (mock_kb_dir / "MEMORY.md").write_text("skip")  # excluded

        result = knowledge_list_files()
        names = [f["name"] for f in result]
        assert "test.md" in names
        assert "data.csv" in names
        assert "MEMORY.md" not in names

        for f in result:
            for key in ("name", "path", "size", "modified"):
                assert key in f

        import shutil
        shutil.rmtree(mock_kb_dir, ignore_errors=True)

    @patch("mcp_knowledge_server.KB_DIR", new_callable=lambda: Path("/tmp/mcp_nonexistent"))
    def test_knowledge_list_files_empty(self, mock_kb_dir):
        """knowledge_list_files returns empty list when KB_DIR missing."""
        result = knowledge_list_files()
        assert result == []


class TestStatsTool:
    @patch("mcp_knowledge_server.knowledge_list_files")
    @patch("mcp_knowledge_server._proxy_stats")
    @patch("mcp_knowledge_server._get_qclient")
    def test_knowledge_stats(self, mock_get_qc, mock_stats, mock_list):
        """knowledge_stats returns dict with expected keys."""
        mock_qc = MagicMock()
        mock_qc.get_collection.return_value.points_count = 42
        mock_get_qc.return_value = mock_qc
        mock_stats.return_value = {"total_requests": 10, "total_saved": 5000}
        mock_list.return_value = [{"name": "doc.md"}]

        result = knowledge_stats()
        assert result["total_chunks"] == 42
        assert result["total_files"] == 1
        assert result["proxy_requests"] == 10
        assert result["proxy_tokens_saved"] == 5000
        for key in ("collection", "kb_dir", "qdrant", "embed_mode"):
            assert key in result


class TestIngestTools:
    @patch("mcp_knowledge_server._extract_text")
    @patch("mcp_knowledge_server._batch_embed")
    @patch("mcp_knowledge_server._get_qclient")
    @patch("mcp_knowledge_server.KB_DIR", new_callable=lambda: Path("/tmp/mcp_ingest_test"))
    def test_ingest_file(self, mock_kb_dir, mock_get_qc, mock_embed, mock_extract):
        """ingest_file ingests a single file successfully."""
        mock_kb_dir.mkdir(parents=True, exist_ok=True)
        fpath = mock_kb_dir / "test.md"
        fpath.write_text("Hello world. " * 200)

        mock_extract.return_value = fpath.read_text()
        mock_embed.return_value = [[0.1, 0.2]] * 3

        mock_qc = MagicMock()
        mock_get_qc.return_value = mock_qc

        result = ingest_file(filename="test.md")
        assert "Ingested" in result
        assert "test.md" in result
        assert "chunk" in result
        mock_qc.upsert.assert_called_once()

        import shutil
        shutil.rmtree(mock_kb_dir, ignore_errors=True)

    @patch("mcp_knowledge_server.KB_DIR", new_callable=lambda: Path("/tmp/mcp_ingest_test2"))
    def test_ingest_file_outside_kb(self, mock_kb_dir):
        """ingest_file rejects paths outside KB_DIR."""
        mock_kb_dir.mkdir(parents=True, exist_ok=True)
        result = ingest_file(filename="../etc/passwd")
        assert "ERROR" in result
        assert "must be under" in result

        import shutil
        shutil.rmtree(mock_kb_dir, ignore_errors=True)

    @patch("mcp_knowledge_server.KB_DIR", new_callable=lambda: Path("/tmp/mcp_ingest_test3"))
    def test_ingest_file_not_found(self, mock_kb_dir):
        """ingest_file returns error for missing file."""
        mock_kb_dir.mkdir(parents=True, exist_ok=True)
        result = ingest_file(filename="nonexistent.md")
        assert "ERROR" in result
        assert "not found" in result

        import shutil
        shutil.rmtree(mock_kb_dir, ignore_errors=True)

    @patch("mcp_knowledge_server._is_file_current")
    @patch("mcp_knowledge_server._ensure_collection")
    @patch("mcp_knowledge_server.ingest_file")
    @patch("mcp_knowledge_server.KB_DIR", new_callable=lambda: Path("/tmp/mcp_ingest_all"))
    def test_ingest_all(self, mock_kb_dir, mock_ingest, mock_ensure, mock_current):
        """ingest_all processes only changed files."""
        mock_kb_dir.mkdir(parents=True, exist_ok=True)
        (mock_kb_dir / "a.md").write_text("aaa")
        (mock_kb_dir / "b.md").write_text("bbb")

        mock_current.side_effect = lambda p: p.name == "a.md"
        mock_ingest.side_effect = lambda f: f"Ingested {f}: 2 chunk(s)"

        result = ingest_all()
        assert "a.md: unchanged, skipped" in result
        assert "Ingested b.md" in result

        import shutil
        shutil.rmtree(mock_kb_dir, ignore_errors=True)

    @patch("mcp_knowledge_server._is_file_current")
    @patch("mcp_knowledge_server.KB_DIR", new_callable=lambda: Path("/tmp/mcp_ingest_status"))
    def test_ingest_status(self, mock_kb_dir, mock_current):
        """ingest_status returns current/stale for each file."""
        mock_kb_dir.mkdir(parents=True, exist_ok=True)
        (mock_kb_dir / "current.md").write_text("aaa")
        (mock_kb_dir / "stale.md").write_text("bbb")

        mock_current.side_effect = lambda p: p.name == "current.md"

        result = ingest_status()
        by_name = {r["name"]: r["current"] for r in result}
        assert by_name["current.md"] is True
        assert by_name["stale.md"] is False

        import shutil
        shutil.rmtree(mock_kb_dir, ignore_errors=True)

    @patch("mcp_knowledge_server.KB_DIR", new_callable=lambda: Path("/tmp/mcp_ingest_nonexistent"))
    def test_ingest_all_no_kb_dir(self, mock_kb_dir):
        """ingest_all returns error when KB_DIR missing."""
        result = ingest_all()
        assert "ERROR" in result
        assert "not found" in result

    @patch("mcp_knowledge_server.KB_DIR", new_callable=lambda: Path("/tmp/mcp_ingest_nonexistent"))
    def test_ingest_status_no_kb_dir(self, mock_kb_dir):
        """ingest_status returns empty list when KB_DIR missing."""
        assert ingest_status() == []


class TestResources:
    @patch("mcp_knowledge_server.knowledge_list_files")
    def test_resource_files(self, mock_list):
        """resource_files returns JSON string."""
        mock_list.return_value = [{"name": "doc.md"}]
        result = resource_files()
        data = json.loads(result)
        assert data[0]["name"] == "doc.md"

    @patch("mcp_knowledge_server.knowledge_stats")
    def test_resource_stats(self, mock_stats):
        """resource_stats returns JSON string."""
        mock_stats.return_value = {"total_chunks": 10}
        result = resource_stats()
        data = json.loads(result)
        assert data["total_chunks"] == 10

    @patch("mcp_knowledge_server.knowledge_search_structured")
    def test_resource_search(self, mock_search):
        """resource_search returns JSON string."""
        mock_search.return_value = [{"source": "doc.md", "score": 0.9, "text": "content"}]
        result = resource_search(query="test")
        data = json.loads(result)
        assert data[0]["source"] == "doc.md"


class TestInternalHelpers:
    def test_chunk_text_short(self):
        """_chunk_text returns single chunk for short text."""
        text = "Short text."
        result = _chunk_text(text, max_tokens=1000)
        assert result == [text]

    def test_chunk_text_long(self):
        """_chunk_text splits long text into multiple chunks."""
        text = "word " * 2000
        result = _chunk_text(text, max_tokens=500, overlap=50)
        assert len(result) > 1
        assert all(isinstance(c, str) for c in result)

    def test_should_ingest_allowed(self, tmp_path):
        """_should_ingest returns True for allowed extensions."""
        f = tmp_path / "doc.md"
        f.write_text("ok")
        assert _should_ingest(f) is True

    def test_should_ingest_excluded(self, tmp_path):
        """_should_ingest returns False for excluded files."""
        for name in ("MEMORY.md", "MEMORY.txt"):
            f = tmp_path / name
            f.write_text("skip")
            assert _should_ingest(f) is False

    def test_should_ingest_bak(self, tmp_path):
        """_should_ingest skips .bak- files."""
        f = tmp_path / "doc.bak-test.md"
        f.write_text("skip")
        assert _should_ingest(f) is False

    def test_should_ingest_disallowed_ext(self, tmp_path):
        """_should_ingest returns False for unlisted extensions."""
        f = tmp_path / "doc.exe"
        f.write_text("skip")
        assert _should_ingest(f) is False

    def test_sanitize_text(self):
        """_sanitize_text normalizes line endings and strips whitespace."""
        assert _sanitize_text("hello\r\nworld  ") == "hello\nworld"
        assert _sanitize_text("\n  hello\n") == "hello"

    def test_extract_text_plain(self, tmp_path):
        """_extract_text reads plain text files."""
        f = tmp_path / "test.txt"
        f.write_text("hello\nworld")
        assert _extract_text(f) == "hello\nworld"

    def test_file_content_hash(self, tmp_path):
        """_file_content_hash is deterministic."""
        f = tmp_path / "test.md"
        f.write_text("hello")
        h1 = _file_content_hash(f)
        h2 = _file_content_hash(f)
        assert h1 == h2
        assert isinstance(h1, str)
        assert len(h1) == 32

    @patch("mcp_knowledge_server._get_qclient")
    def test_is_file_current_true(self, mock_get_qc):
        """_is_file_current returns True when hash matches."""
        mock_qc = MagicMock()
        mock_qc.scroll.return_value = ([MagicMock()], None)
        mock_get_qc.return_value = mock_qc
        f = Path("/tmp/test_current.md")
        with patch.object(Path, "read_bytes", return_value=b"data"):
            assert _is_file_current(f) is True

    @patch("mcp_knowledge_server._get_qclient")
    def test_is_file_current_false(self, mock_get_qc):
        """_is_file_current returns False when hash doesn't match."""
        mock_qc = MagicMock()
        mock_qc.scroll.return_value = ([], None)
        mock_get_qc.return_value = mock_qc
        f = Path("/tmp/test_stale.md")
        with patch.object(Path, "read_bytes", return_value=b"newdata"):
            assert _is_file_current(f) is False

    @patch("mcp_knowledge_server._EMBED_MODE", "ollama")
    @patch("mcp_knowledge_server._LOCAL_EMBED", "nomic-embed-text")
    @patch("mcp_knowledge_server.UPSTREAM", "http://localhost:11434")
    @patch("mcp_knowledge_server.urllib.request.urlopen")
    def test_batch_embed_ollama(self, mock_urlopen):
        """_batch_embed uses Ollama when configured."""
        from mcp_knowledge_server import _batch_embed

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "embeddings": [[0.1, 0.2], [0.3, 0.4]]
        }).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        result = _batch_embed(["hello", "world"])
        assert len(result) == 2
        assert result[0] == [0.1, 0.2]


class TestLiveMCPServer:
    """Requires --live flag and a running ContextCut-PRO proxy with KB."""

    @pytest.mark.live
    def test_live_import(self):
        """Module imports without error in live mode."""
        import mcp_knowledge_server
        assert True
