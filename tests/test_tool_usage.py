"""
Tests for ``_check_tool_usage`` — the tool-usage enforcer.
"""

import pytest


class TestCheckToolUsage:
    @pytest.mark.parametrize(
        "message, called_tools, expect_blocked",
        [
            ("run this command for me", set(), True),
            ("execute the python script", set(), True),
            ("search the web for news", set(), True),
            ("what is the weather", {"read_file"}, True),
            ("hello, how are you?", set(), False),
            ("what do you think about ai?", set(), False),
            ("run this", {"shell_exec"}, False),
            ("search for x", {"web_search"}, False),
            ("search and run", {"web_search", "shell_exec"}, False),
        ],
    )
    def test_check_tool_usage(self, message, called_tools, expect_blocked):
        from agent_handler import _check_tool_usage

        blocked, reason = _check_tool_usage(message, called_tools)
        assert blocked == expect_blocked, (
            f"message={message!r} called={called_tools} "
            f"expect_blocked={expect_blocked} got={blocked} reason={reason!r}"
        )
        if blocked:
            assert "tool" in reason.lower()
