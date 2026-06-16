"""
Tests for ``_shell_is_safe`` — the shell command safety guard.
"""

import pytest

BLOCKED = [
    "rm -rf /",
    "rm -rf ~",
    "mkfs",
    ":(){:|:&};:",
    "dd if=/dev/zero",
    "shutdown",
    "reboot",
    "halt",
]

SAFE = [
    "ls",
    "echo hello",
    "git status",
    "cp /tmp/a /tmp/b",
    "diff file_a file_b",
    "make -j4",
]


class TestShellIsSafe:
    @pytest.mark.parametrize("cmd", BLOCKED)
    def test_blocked(self, cmd):
        from agent_handler import _shell_is_safe

        assert not _shell_is_safe(cmd), f"{cmd!r} should be BLOCKED"

    @pytest.mark.parametrize("cmd", SAFE)
    def test_safe(self, cmd):
        from agent_handler import _shell_is_safe

        assert _shell_is_safe(cmd), f"{cmd!r} should be SAFE"
