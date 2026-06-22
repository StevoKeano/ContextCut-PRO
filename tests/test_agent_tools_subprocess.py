"""
Tests for subprocess-based agent tools: ``shell_exec``, ``run_python``, ``diff_files``.

Uses the ``mock_subprocess`` fixture to avoid real subprocess calls.
"""

import subprocess
from unittest.mock import MagicMock

import pytest


class TestShellExec:
    def test_safe_command(self, mock_subprocess):
        from agent_handler import shell_exec

        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=["echo", "hi"], returncode=0, stdout="hello\n", stderr=""
        )
        result = shell_exec.invoke({"command": "echo hello"})
        assert "hello" in result
        mock_subprocess.assert_called_once()

    def test_blocked_command(self, mock_subprocess):
        from agent_handler import shell_exec

        result = shell_exec.invoke({"command": "rm -rf /"})
        assert "BLOCKED" in result
        mock_subprocess.assert_not_called()

    def test_timeout(self, mock_subprocess):
        from agent_handler import shell_exec

        mock_subprocess.side_effect = subprocess.TimeoutExpired(cmd="sleep 100", timeout=5)
        result = shell_exec.invoke({"command": "sleep 100"})
        assert "timed out" in result.lower()

    def test_stderr_output(self, mock_subprocess):
        from agent_handler import shell_exec

        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=["ls", "/nonexistent"], returncode=1, stdout="", stderr="No such file"
        )
        result = shell_exec.invoke({"command": "ls /nonexistent"})
        assert "[stderr]" in result
        assert "No such file" in result

    def test_all_blocked_patterns(self, mock_subprocess):
        from agent_handler import shell_exec, BLOCKED_PREFIXES

        for prefix in BLOCKED_PREFIXES:
            # Append a dummy argument so .strip() doesn't eat the trailing
            # space that some prefixes (e.g. "apt ", "apt-get ") rely on.
            cmd = prefix + "something" if prefix.endswith(" ") else prefix
            result = shell_exec.invoke({"command": cmd})
            assert "BLOCKED" in result, f"{prefix!r} should be blocked"
        mock_subprocess.assert_not_called()


class TestRunPython:
    def test_stdout_output(self, mock_subprocess):
        from agent_handler import run_python

        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=["python3", "-c", "print('hi')"],
            returncode=0,
            stdout="hi\n",
            stderr="",
        )
        result = run_python.invoke({"code": "print('hi')", "timeout": 30})
        assert "hi" in result

    def test_stderr_output(self, mock_subprocess):
        from agent_handler import run_python

        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=["python3", "-c", "import sys; sys.stderr.write('err')"],
            returncode=1,
            stdout="",
            stderr="err",
        )
        result = run_python.invoke({"code": "import sys; sys.stderr.write('err')", "timeout": 30})
        assert "[stderr]" in result
        assert "err" in result

    def test_timeout(self, mock_subprocess):
        from agent_handler import run_python

        mock_subprocess.side_effect = subprocess.TimeoutExpired(
            cmd=["python3", "-c", "while True: pass"], timeout=5
        )
        result = run_python.invoke({"code": "while True: pass", "timeout": 5})
        assert "timed out" in result.lower()


class TestDiffFiles:
    def test_diff_output(self, mock_subprocess):
        from agent_handler import diff_files

        diff_text = "--- a/file1\n+++ b/file2\n@@ -1 +1 @@\n-old\n+new\n"
        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=["diff", "-u", "a", "b"], returncode=0, stdout=diff_text, stderr=""
        )
        result = diff_files.invoke({"path_a": "a", "path_b": "b"})
        assert "old" in result
        assert "new" in result

    def test_identical_files(self, mock_subprocess):
        from agent_handler import diff_files

        mock_subprocess.return_value = subprocess.CompletedProcess(
            args=["diff", "-u", "a", "b"],
            returncode=0,
            stdout="",
            stderr="",
        )
        result = diff_files.invoke({"path_a": "a", "path_b": "b"})
        assert "identical" in result.lower()

    def test_error(self, mock_subprocess):
        from agent_handler import diff_files

        mock_subprocess.side_effect = FileNotFoundError("diff not found")
        result = diff_files.invoke({"path_a": "a", "path_b": "b"})
        assert "error" in result.lower()
