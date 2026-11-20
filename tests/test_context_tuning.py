"""Tests for ContextTuningMiddleware and tool-output clamping."""

import asyncio

import pytest
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI


def _chat_model(*, extra_body=None, max_tokens=None):
    return ChatOpenAI(
        model="test-model",
        openai_api_base="http://localhost:11434/v1",
        openai_api_key="not-needed",
        extra_body=extra_body,
        max_tokens=max_tokens,
    )


def _model_request(messages, *, extra_body=None, max_tokens=None):
    return ModelRequest(
        model=_chat_model(extra_body=extra_body, max_tokens=max_tokens),
        messages=messages,
        system_message=None,
        tool_choice=None,
        tools=[],
        response_format=None,
        state={},
        runtime=None,
        model_settings={},
    )


class TestClampToolOutput:
    def test_short_text_unchanged(self):
        from agent_handler import clamp_tool_output

        assert clamp_tool_output("hello", 4000) == "hello"

    def test_zero_limit_disables(self):
        from agent_handler import clamp_tool_output

        text = "x" * 10_000
        assert clamp_tool_output(text, 0) == text

    def test_long_text_keeps_head_and_tail(self):
        from agent_handler import clamp_tool_output

        text = "A" * 3000 + "B" * 3000 + "C" * 3000
        result = clamp_tool_output(text, 4000)
        assert result.startswith("A")
        assert result.endswith("C")
        assert "output truncated" in result
        assert len(result) <= 4000 + 60

    def test_preserves_untrusted_markers(self):
        from agent_handler import clamp_tool_output
        from untrusted_content import END_MARKER, BEGIN_PREFIX, wrap_untrusted

        wrapped = wrap_untrusted("Z" * 20_000, source="run_python", kind="command-output")
        result = clamp_tool_output(wrapped, 4000)
        assert result.startswith(BEGIN_PREFIX)
        assert result.endswith(END_MARKER)
        assert "output truncated" in result

    def test_idempotent(self):
        from agent_handler import clamp_tool_output

        text = "x" * 20_000
        once = clamp_tool_output(text, 4000)
        assert clamp_tool_output(once, 4000) == once


class TestToolOutputLimit:
    def test_per_tool_limits(self):
        from agent_handler import tool_output_limit

        assert tool_output_limit("read_file") == 12000
        assert tool_output_limit("vector_search") == 6000
        assert tool_output_limit("run_python") == 4000
        assert tool_output_limit("shell_exec") == 4000
        assert tool_output_limit(None) == 4000
        assert tool_output_limit("unknown_tool") == 4000


class TestToolCallClamping:
    def test_clamps_large_run_python(self):
        from agent_handler import ContextTuningMiddleware

        result = ToolMessage(
            content="y" * 9000,
            tool_call_id="1",
            name="run_python",
            status="success",
        )
        clamped = ContextTuningMiddleware._clamp_result(result)
        assert "lines truncated" in clamped.content
        assert len(clamped.content) <= 2500
        assert clamped.tool_call_id == "1"
        assert clamped.name == "run_python"
        assert clamped.status == "success"

    def test_leaves_small_result_alone(self):
        from agent_handler import ContextTuningMiddleware

        result = ToolMessage(content="ok", tool_call_id="1", name="run_python")
        assert ContextTuningMiddleware._clamp_result(result) is result

    def test_read_file_capped_at_2500_with_line_marker(self):
        from agent_handler import ContextTuningMiddleware

        result = ToolMessage(content="z" * 9000, tool_call_id="1", name="read_file")
        clamped = ContextTuningMiddleware._clamp_result(result)
        assert len(clamped.content) <= 2500
        assert "lines truncated" in clamped.content

    def test_non_tool_message_untouched(self):
        from agent_handler import ContextTuningMiddleware

        assert ContextTuningMiddleware._clamp_result("plain") == "plain"

    def test_wrap_tool_call_sync(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        result = mw.wrap_tool_call(
            None,
            lambda request: ToolMessage(
                content="q" * 9000, tool_call_id="1", name="shell_exec"
            ),
        )
        assert "lines truncated" in result.content

    def test_wrap_tool_call_async(self):
        from agent_handler import ContextTuningMiddleware

        async def handler(request):
            return ToolMessage(content="q" * 9000, tool_call_id="1", name="shell_exec")

        mw = ContextTuningMiddleware(provider="DeepSeek")
        result = asyncio.run(mw.awrap_tool_call(None, handler))
        assert "lines truncated" in result.content


class TestModelCallTuning:
    def test_first_turn_caps_max_tokens_and_thinking_budget(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        request = _model_request(
            [HumanMessage(content="hi")],
            extra_body={"reasoning_effort": "high", "thinking_budget": 32578},
            max_tokens=24576,
        )
        out = mw.wrap_model_call(request, lambda req: req)
        assert out.model.extra_body["reasoning_effort"] == "high"
        assert out.model.extra_body["thinking_budget"] == 3072
        assert out.model.max_tokens == 8192

    def test_tool_turn_lowers_reasoning_and_caps_tokens(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        request = _model_request(
            [
                HumanMessage(content="hi"),
                AIMessage(content="", tool_calls=[]),
                ToolMessage(content="result", tool_call_id="1", name="run_python"),
            ],
            extra_body={"reasoning_effort": "high"},
            max_tokens=24576,
        )
        out = mw.wrap_model_call(request, lambda req: req)
        assert out.model.extra_body == {"enable_thinking": False}
        assert out.model.model_kwargs["extra_body"] == {"enable_thinking": False}
        assert out.model.max_tokens == 8192

    def test_tool_turn_keeps_lower_user_cap(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        request = _model_request(
            [ToolMessage(content="result", tool_call_id="1", name="run_python")],
            extra_body={"reasoning_effort": "high"},
            max_tokens=4096,
        )
        out = mw.wrap_model_call(request, lambda req: req)
        assert out.model.max_tokens == 4096

    def test_ollama_skips_reasoning_but_caps_tokens(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="Ollama")
        request = _model_request(
            [ToolMessage(content="result", tool_call_id="1", name="run_python")],
            extra_body={"reasoning_effort": "high"},
            max_tokens=24576,
        )
        out = mw.wrap_model_call(request, lambda req: req)
        assert out.model.extra_body["reasoning_effort"] == "high"
        assert out.model.max_tokens == 8192

    def test_async_tool_turn(self):
        from agent_handler import ContextTuningMiddleware

        async def handler(req):
            return req

        mw = ContextTuningMiddleware(provider="DeepSeek")
        request = _model_request(
            [ToolMessage(content="result", tool_call_id="1", name="run_python")],
            extra_body={"reasoning_effort": "high"},
            max_tokens=24576,
        )
        out = asyncio.run(mw.awrap_model_call(request, handler))
        assert out.model.extra_body == {"enable_thinking": False}
        assert out.model.model_kwargs["extra_body"] == {"enable_thinking": False}
        assert out.model.max_tokens == 8192


class _ToolRequest:
    def __init__(self, name, args, tool_call_id="call-1"):
        self.tool_call = {"name": name, "args": args, "id": tool_call_id}


def _tool_name(tool):
    if isinstance(tool, dict):
        return tool.get("name")
    return getattr(tool, "name", None)


def _tool_message(name, content="ok"):
    return ToolMessage(content=content, tool_call_id="call-1", name=name, status="success")


class TestInspectionBudget:
    def test_two_read_only_calls_are_permitted(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        first = mw.wrap_tool_call(
            _ToolRequest("read_file", {"path": "a.txt"}),
            lambda request: _tool_message("read_file"),
        )
        second = mw.wrap_tool_call(
            _ToolRequest("run_python", {"code": 'print(open("a.txt").read())'}),
            lambda request: _tool_message("run_python"),
        )

        assert first.content == "ok"
        assert second.content == "ok"
        assert mw.read_only_calls == 2

    def test_third_read_only_call_is_blocked_and_tools_are_pruned(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        for request in (
            _ToolRequest("read_file", {"path": "a.txt"}),
            _ToolRequest("run_python", {"code": 'print(open("a.txt").read())'}),
        ):
            mw.wrap_tool_call(request, lambda req: _tool_message("read_file"))

        def forbidden_handler(_request):
            pytest.fail("third read-only tool should not execute")

        blocked = mw.wrap_tool_call(
            _ToolRequest("run_python", {"code": "print('more')"}),
            forbidden_handler,
        )
        assert blocked.content == (
            "Inspection budget reached (2 reads). Do not run more read/python "
            "inspection commands—call append_file, edit_file, or write_file now."
        )
        assert blocked.status == "error"

        request = _model_request([ToolMessage(content="done", tool_call_id="1")]).override(
            tools=[
                {"name": "read_file"},
                {"name": "list_dir"},
                {"name": "grep"},
                {"name": "find_files"},
                {"name": "run_python"},
                {"name": "append_file"},
            ]
        )
        out = mw.wrap_model_call(request, lambda req: req)
        assert [_tool_name(tool) for tool in out.tools] == ["run_python", "append_file"]

    @pytest.mark.parametrize(
        "name,args",
        [
            ("append_file", {"path": "a.txt", "content": "more"}),
            ("edit_file", {"path": "a.txt", "old": "a", "new": "b"}),
            ("write_file", {"path": "b.txt", "content": "new"}),
        ],
    )
    def test_mutating_file_tool_resets_budget(self, name, args):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        for request in (
            _ToolRequest("read_file", {"path": "a.txt"}),
            _ToolRequest("run_python", {"code": 'print(open("a.txt").read())'}),
        ):
            mw.wrap_tool_call(request, lambda req: _tool_message("read_file"))
        assert mw.read_only_calls == 2

        mw.wrap_tool_call(_ToolRequest(name, args), lambda req: _tool_message(name))
        assert mw.read_only_calls == 0

        after_reset = mw.wrap_tool_call(
            _ToolRequest("list_dir", {"path": "."}),
            lambda req: _tool_message("list_dir"),
        )
        assert after_reset.content == "ok"
        assert mw.read_only_calls == 1

    def test_failed_mutating_file_tool_does_not_reset_budget(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        for request in (
            _ToolRequest("read_file", {"path": "a.txt"}),
            _ToolRequest("run_python", {"code": 'print(open("a.txt").read())'}),
        ):
            mw.wrap_tool_call(request, lambda req: _tool_message("read_file"))

        failed = mw.wrap_tool_call(
            _ToolRequest("append_file", {"path": "a.txt", "content": "more"}),
            lambda req: _tool_message("append_file", "append_file error: disk full"),
        )
        assert "error" in failed.content
        assert mw.read_only_calls == 2

    def test_file_writing_run_python_resets_budget(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        for request in (
            _ToolRequest("read_file", {"path": "a.txt"}),
            _ToolRequest("run_python", {"code": 'print(open("a.txt").read())'}),
        ):
            mw.wrap_tool_call(request, lambda req: _tool_message("read_file"))

        mw.wrap_tool_call(
            _ToolRequest("run_python", {"code": 'Path("a.txt").write_text("done")'}),
            lambda req: _tool_message("run_python"),
        )
        assert mw.read_only_calls == 0

    @pytest.mark.parametrize(
        "code,writes",
        [
            ('print(open("a.txt").read())', False),
            ('with open("a.txt") as f: print(f.read())', False),
            ('with open("a.txt", "r") as f: print(f.read())', False),
            ('with open("a.txt", "w") as f: f.write("x")', True),
            ("open('a.txt', mode='a')", True),
            ("open('a.txt', 'x')", True),
            ('Path("a.txt").write_text("x")', True),
            ('Path("a.txt").write_bytes(b"x")', True),
            ('os.replace("a.txt", "b.txt")', True),
            ('shutil.copy("a.txt", "b.txt")', True),
        ],
    )
    def test_run_python_write_detection(self, code, writes):
        from agent_handler import _run_python_writes_to_disk

        assert _run_python_writes_to_disk(code) is writes

    def test_before_agent_resets_on_new_user_turn_only(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        mw.read_only_calls = 2
        mw.before_agent({"messages": [ToolMessage(content="x", tool_call_id="1")]}, None)
        assert mw.read_only_calls == 2
        mw.before_agent({"messages": [HumanMessage(content="next task")]}, None)
        assert mw.read_only_calls == 0


class TestMessageOutputClamp:
    def test_read_file_and_shell_exec_capped_at_2500(self):
        from agent_handler import clamp_tool_output_message

        text = "".join(f"line {i}\n" for i in range(1000))
        for name in ("read_file", "shell_exec", "run_python"):
            out = clamp_tool_output_message(name, text)
            assert len(out) <= 2500
            assert "lines truncated" in out
            assert out.startswith("line 0")
            assert out.endswith("line 999\n")

    def test_other_tools_keep_general_limit(self):
        from agent_handler import clamp_tool_output_message

        out = clamp_tool_output_message("vector_search", "x" * 9000)
        assert "output truncated" in out
        assert "lines truncated" not in out

    def test_short_output_unchanged(self):
        from agent_handler import clamp_tool_output_message

        assert clamp_tool_output_message("read_file", "short") == "short"


class TestHistoricalWriteCompaction:
    @staticmethod
    def _messages(big, recent_payload):
        return [
            HumanMessage(content="go"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "write_file", "args": {"path": "a.py", "content": big}, "id": "1"}
                ],
            ),
            ToolMessage(content="wrote", tool_call_id="1", name="write_file"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "append_file",
                        "args": {"path": "a.py", "content": recent_payload, "code": recent_payload, "new_str": recent_payload},
                        "id": "2",
                    }
                ],
            ),
            ToolMessage(content="appended", tool_call_id="2", name="append_file"),
            AIMessage(content="thinking", tool_calls=[]),
            ToolMessage(content="done", tool_call_id="3", name="run_python"),
        ]

    def test_old_payloads_compacted_recent_turns_untouched(self):
        from agent_handler import compact_historical_write_payloads

        big = "x" * 1000
        messages = self._messages(big, "y" * 800)
        recent = messages[3]
        out = compact_historical_write_payloads(messages)
        assert out is not messages
        assert out[1].tool_calls[0]["args"]["content"] == f"<written to disk: {len(big)} chars>"
        assert out[3] is recent
        assert recent.tool_calls[0]["args"]["content"] == "y" * 800
        assert messages[1].tool_calls[0]["args"]["content"] == big

    def test_all_write_arg_keys_compacted(self):
        from agent_handler import compact_historical_write_payloads

        big = "x" * 500
        messages = self._messages(big, "short")
        messages[1].tool_calls[0]["args"] = {
            "path": "a.py",
            "content": big,
            "code": big,
            "new_str": big,
        }
        out = compact_historical_write_payloads(messages)
        args = out[1].tool_calls[0]["args"]
        for key in ("content", "code", "new_str"):
            assert args[key] == f"<written to disk: {len(big)} chars>"
        assert args["path"] == "a.py"

    def test_exactly_400_chars_untouched(self):
        from agent_handler import compact_historical_write_payloads

        messages = self._messages("z" * 400, "short")
        out = compact_historical_write_payloads(messages)
        assert out is messages

    def test_middleware_compacts_before_model_call(self):
        from agent_handler import ContextTuningMiddleware

        big = "x" * 1000
        mw = ContextTuningMiddleware(provider="DeepSeek")
        request = _model_request(self._messages(big, "y" * 800))
        out = mw.wrap_model_call(request, lambda req: req)
        assert out.messages[1].tool_calls[0]["args"]["content"] == (
            f"<written to disk: {len(big)} chars>"
        )
        assert out.messages[3].tool_calls[0]["args"]["content"] == "y" * 800


class TestThinkingBudgetLookback:
    def test_tool_message_third_from_end_keeps_low_cap(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        request = _model_request(
            [
                HumanMessage(content="go"),
                AIMessage(content="", tool_calls=[]),
                ToolMessage(content="result", tool_call_id="1", name="read_file"),
                HumanMessage(content="continue"),
                AIMessage(content="", tool_calls=[]),
            ],
            extra_body={"reasoning_effort": "high"},
            max_tokens=24576,
        )
        out = mw.wrap_model_call(request, lambda req: req)
        assert out.model.extra_body == {"enable_thinking": False}
        assert out.model.max_tokens == 8192

    def test_old_tool_message_still_uses_lower_ceiling(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        request = _model_request(
            [
                ToolMessage(content="old result", tool_call_id="1", name="read_file"),
                HumanMessage(content="go"),
                AIMessage(content="thinking", tool_calls=[]),
                HumanMessage(content="next"),
            ],
            extra_body={"reasoning_effort": "high", "thinking_budget": 24576},
            max_tokens=24576,
        )
        out = mw.wrap_model_call(request, lambda req: req)
        assert out.model.extra_body == {"reasoning_effort": "high", "thinking_budget": 1536}
        assert out.model.max_tokens == 8192


class TestReadSliceDedup:
    @staticmethod
    def _request():
        return _ToolRequest("read_file", {"path": "a.py", "start_line": 1, "end_line": 50})

    def test_second_identical_read_slice_short_circuits(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        first = mw.wrap_tool_call(
            self._request(), lambda req: _tool_message("read_file", "A" * 9000)
        )
        assert "A" in first.content

        def forbidden(_request):
            pytest.fail("duplicate read should not execute")

        second = mw.wrap_tool_call(self._request(), forbidden)
        assert second.content == (
            "Already in context—proceed directly to writing the next chunk."
        )
        assert second.tool_call_id == "call-1"

    def test_different_slice_and_tool_still_executes(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        mw.wrap_tool_call(self._request(), lambda req: _tool_message("read_file"))
        other = mw.wrap_tool_call(
            _ToolRequest("read_file", {"path": "a.py", "start_line": 51, "end_line": 100}),
            lambda req: _tool_message("read_file", "fresh"),
        )
        assert other.content == "fresh"

    def test_duplicate_read_seeded_from_history(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        mw.before_agent(
            {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "read_file",
                                "args": {"path": "a.py", "start_line": 1, "end_line": 50},
                                "id": "1",
                            }
                        ],
                    )
                ]
            },
            None,
        )
        result = mw.wrap_tool_call(
            self._request(), lambda req: pytest.fail("seeded read should not execute")
        )
        assert result.content == (
            "Already in context—proceed directly to writing the next chunk."
        )


class TestThinkingCeiling:
    def test_ceiling_values_and_history_detection(self):
        from agent_handler import (
            MAX_THINKING_TOKENS_FIRST_TURN,
            MAX_THINKING_TOKENS_TOOL_TURN,
            thinking_budget_ceiling,
        )

        assert MAX_THINKING_TOKENS_FIRST_TURN == 3072
        assert MAX_THINKING_TOKENS_TOOL_TURN == 1536
        assert thinking_budget_ceiling([HumanMessage(content="hi")]) == 3072
        assert thinking_budget_ceiling(
            [
                HumanMessage(content="hi"),
                ToolMessage(content="result", tool_call_id="1"),
                HumanMessage(content="continue"),
            ]
        ) == 1536

    def test_all_budget_keys_clamped(self):
        from agent_handler import cap_thinking_budget

        body = {
            "thinking_budget": 32578,
            "budget_tokens": 24576,
            "max_thinking_tokens": 9999,
            "reasoning_effort": 24576,
            "top_p": 0.9,
        }
        assert cap_thinking_budget(body, 3072) is True
        assert body == {
            "thinking_budget": 3072,
            "budget_tokens": 3072,
            "max_thinking_tokens": 3072,
            "reasoning_effort": 3072,
            "top_p": 0.9,
        }
        assert cap_thinking_budget(body, 3072) is False
        assert cap_thinking_budget({"reasoning_effort": "high"}, 3072) is False

    def test_ollama_first_turn_also_capped(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="Ollama")
        request = _model_request(
            [HumanMessage(content="hi")],
            extra_body={"thinking_budget": 32578},
            max_tokens=32768,
        )
        out = mw.wrap_model_call(request, lambda req: req)
        assert out.model.extra_body["thinking_budget"] == 3072
        assert out.model.max_tokens == 8192

    def test_no_oversized_token_budget_survives_human_turn(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        request = _model_request(
            [HumanMessage(content="hi")],
            extra_body={"thinking_budget": 24576, "budget_tokens": 32578},
            max_tokens=32578,
        )
        out = mw.wrap_model_call(request, lambda req: req)
        assert out.model.extra_body["thinking_budget"] == 3072
        assert out.model.extra_body["budget_tokens"] == 3072
        assert 6144 <= out.model.max_tokens <= 8192


class TestRunPythonInspectionDedup:
    @staticmethod
    def _request(code):
        return _ToolRequest("run_python", {"code": code})

    def test_near_identical_inspection_snippet_is_blocked(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        first = mw.wrap_tool_call(
            self._request('print(open("a.py").read())'),
            lambda req: _tool_message("run_python", "file contents"),
        )
        assert first.content == "file contents"

        second = mw.wrap_tool_call(
            self._request('print( open( "a.py" ).read() )'),
            lambda req: pytest.fail("duplicate inspection should not execute"),
        )
        assert second.content == "Already executed—do not re-read; call append_file now."

    def test_different_inspection_snippet_is_allowed(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        mw.wrap_tool_call(
            self._request('print(open("a.py").read())'),
            lambda req: _tool_message("run_python"),
        )
        other = mw.wrap_tool_call(
            self._request('print(open("b.py").read())'),
            lambda req: _tool_message("run_python", "other file"),
        )
        assert other.content == "other file"

    def test_non_file_snippet_is_allowed_twice(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        for _ in range(2):
            result = mw.wrap_tool_call(
                self._request("print(2 + 2)"),
                lambda req: _tool_message("run_python", "4"),
            )
            assert result.content == "4"

    def test_history_seeds_executed_hashes(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        mw.before_agent(
            {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "run_python",
                                "args": {"code": 'lines = open("a.py").read().splitlines()'},
                                "id": "1",
                            }
                        ],
                    )
                ]
            },
            None,
        )
        result = mw.wrap_tool_call(
            self._request('lines = open("a.py").read().splitlines()'),
            lambda req: pytest.fail("seeded inspection should not execute"),
        )
        assert result.content == "Already executed—do not re-read; call append_file now."

    def test_normalization_and_file_detection_helpers(self):
        from agent_handler import normalize_python_code, python_code_hash, python_reads_files

        assert normalize_python_code("  a  =  1\n b=2 ") == "a=1b=2"
        assert python_code_hash("print( open('a').read() )") == python_code_hash(
            "print(open('a').read())"
        )
        assert python_reads_files("for line in open('a').read().splitlines(): print(line)")
        assert not python_reads_files("print(2 + 2)")


class TestBuildAgentMiddleware:
    @pytest.mark.parametrize("provider", ["DeepSeek", "Ollama"])
    def test_context_tuning_registered(self, provider):
        from unittest.mock import MagicMock, patch

        with patch("agent_handler.ChatOpenAI") as mock_chat, patch(
            "agent_handler.create_agent"
        ) as mock_create_agent, patch(
            "agent_handler._get_dynamic_tools", return_value=[]
        ):
            from agent_handler import ContextTuningMiddleware, build_agent

            mock_create_agent.return_value = MagicMock()
            build_agent(upstream="http://localhost:11434", provider=provider)

            middleware = mock_create_agent.call_args[1]["middleware"]
            assert any(
                isinstance(item, ContextTuningMiddleware) for item in middleware
            )
