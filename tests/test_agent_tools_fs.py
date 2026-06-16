"""
Tests for filesystem agent tools: ``read_file``, ``write_file``, ``append_file``, ``list_dir``.

Uses ``tmp_path`` fixture for real file I/O.
"""

import os
from pathlib import Path

import pytest

MAX_READ_BYTES = 64 * 1024


class TestReadFile:
    def test_exists(self, tmp_path):
        from agent_handler import read_file

        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = read_file.invoke({"path": str(f)})
        assert "hello world" in result

    def test_missing(self, tmp_path):
        from agent_handler import read_file

        result = read_file.invoke({"path": str(tmp_path / "nonexistent.txt")})
        assert "not found" in result.lower()

    def test_binary(self, tmp_path):
        from agent_handler import read_file

        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x00\x01\x02\xff\xfe")
        result = read_file.invoke({"path": str(f)})
        assert "binary" in result.lower()
        assert "hex" in result or "00" in result

    def test_truncated(self, tmp_path):
        from agent_handler import read_file

        f = tmp_path / "large.txt"
        f.write_text("x" * (MAX_READ_BYTES + 1000))
        result = read_file.invoke({"path": str(f)})
        assert "truncated" in result


class TestWriteFile:
    def test_new_file(self, tmp_path):
        from agent_handler import write_file

        f = tmp_path / "new.txt"
        result = write_file.invoke({"path": str(f), "content": "fresh content"})
        assert "Wrote" in result
        assert f.read_text() == "fresh content"

    def test_overwrite_with_backup(self, tmp_path):
        from agent_handler import write_file

        f = tmp_path / "existing.txt"
        f.write_text("original")
        result = write_file.invoke({"path": str(f), "content": "updated", "backup": True})
        assert "Wrote" in result
        assert f.read_text() == "updated"
        backups = list(tmp_path.glob("existing.txt.bak-*"))
        assert len(backups) >= 1

    def test_overwrite_no_backup(self, tmp_path):
        from agent_handler import write_file

        f = tmp_path / "nobackup.txt"
        f.write_text("original")
        result = write_file.invoke({"path": str(f), "content": "updated", "backup": False})
        assert "Wrote" in result
        assert f.read_text() == "updated"
        backups = list(tmp_path.glob("nobackup.txt.bak-*"))
        assert len(backups) == 0


class TestAppendFile:
    def test_to_existing(self, tmp_path):
        from agent_handler import append_file

        f = tmp_path / "existing.txt"
        f.write_text("base\n")
        result = append_file.invoke({"path": str(f), "content": "appended"})
        assert "Appended" in result
        assert f.read_text() == "base\nappended"

    def test_to_new_file(self, tmp_path):
        from agent_handler import append_file

        f = tmp_path / "new_append.txt"
        result = append_file.invoke({"path": str(f), "content": "first line"})
        assert "Appended" in result
        assert f.read_text() == "first line"


class TestListDir:
    def test_directory_tree(self, tmp_path):
        from agent_handler import list_dir

        (tmp_path / "file_a.txt").write_text("a")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "nested.txt").write_text("b")
        result = list_dir.invoke({"path": str(tmp_path), "max_depth": 5})
        assert "file_a.txt" in result
        assert "sub/" in result
        assert "nested.txt" in result

    def test_max_depth(self, tmp_path):
        from agent_handler import list_dir

        (tmp_path / "l1").mkdir()
        (tmp_path / "l1" / "l2").mkdir()
        (tmp_path / "l1" / "l2" / "l3.txt").write_text("deep")
        result = list_dir.invoke({"path": str(tmp_path), "max_depth": 1})
        assert "l1/" in result
        assert "l2" not in result

    def test_path_not_found(self, tmp_path):
        from agent_handler import list_dir

        result = list_dir.invoke({"path": str(tmp_path / "ghost"), "max_depth": 3})
        assert "not found" in result.lower()
