"""Tests for raw/textual tool-call detection and repair helpers."""

from agent_handler import (
    extract_textual_tool_calls,
    malformed_tool_call_message,
    strip_textual_tool_calls,
    textual_tool_call_retry_message,
)


class TestExtractTextualToolCalls:
    def test_qwen_style_call(self):
        text = (
            "⚡ <function=list_dir> <parameter=path> . </parameter> "
            "</function> </tool_call>"
        )
        calls = extract_textual_tool_calls(text)
        assert calls == [
            {
                "name": "list_dir",
                "input": {"path": "."},
                "raw": (
                    "<function=list_dir> <parameter=path> . </parameter> "
                    "</function>"
                ),
            }
        ]

    def test_multiple_parameters(self):
        text = (
            "<function=read_file><parameter=path>/tmp/x</parameter>"
            "<parameter=start>1</parameter></function>"
        )
        calls = extract_textual_tool_calls(text)
        assert calls[0]["name"] == "read_file"
        assert calls[0]["input"] == {"path": "/tmp/x", "start": "1"}

    def test_partial_open_tag(self):
        calls = extract_textual_tool_calls("<function=list_dir>")
        assert calls[0]["name"] == "list_dir"
        assert calls[0]["input"] == {}

    def test_plain_text_is_not_a_call(self):
        assert extract_textual_tool_calls("No tool here") == []
        assert extract_textual_tool_calls("") == []


class TestStripTextualToolCalls:
    def test_removes_block_preserves_prose(self):
        text = (
            "Before\n<function=read_file><parameter=path>/tmp/x</parameter>"
            "</function>\nAfter"
        )
        cleaned = strip_textual_tool_calls(text)
        assert "<function" not in cleaned
        assert "<parameter" not in cleaned
        assert "Before" in cleaned
        assert "After" in cleaned

    def test_removes_wrappers(self):
        cleaned = strip_textual_tool_calls(
            "<tool_call><function=list_dir></function></tool_call>"
        )
        assert cleaned == ""

    def test_preserves_plain_text(self):
        assert strip_textual_tool_calls("hello") == "hello"


class TestRepairMessages:
    def test_retry_message_lists_attempted_call(self):
        msg = textual_tool_call_retry_message(
            [{"name": "list_dir", "input": {"path": "."}}]
        )
        assert "list_dir" in msg
        assert "NOT executed" in msg
        assert "native tool interface" in msg

    def test_malformed_message_is_clean(self):
        msg = malformed_tool_call_message(
            [{"name": "list_dir", "input": {"path": "."}}]
        )
        assert "malformed text-based tool call" in msg
        assert "<function=" not in msg
        assert "qwen3:14b-q8_0" in msg
