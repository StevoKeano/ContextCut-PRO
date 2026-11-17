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
        from untrusted_content import END_MARKER, SAFETY_WARNING, wrap_untrusted

        wrapped = wrap_untrusted("Z" * 20_000, source="run_python", kind="command-output")
        result = clamp_tool_output(wrapped, 4000)
        assert result.startswith(SAFETY_WARNING)
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
        assert "output truncated" in clamped.content
        assert clamped.tool_call_id == "1"
        assert clamped.name == "run_python"
        assert clamped.status == "success"

    def test_leaves_small_result_alone(self):
        from agent_handler import ContextTuningMiddleware

        result = ToolMessage(content="ok", tool_call_id="1", name="run_python")
        assert ContextTuningMiddleware._clamp_result(result) is result

    def test_read_file_keeps_more(self):
        from agent_handler import ContextTuningMiddleware

        result = ToolMessage(content="z" * 9000, tool_call_id="1", name="read_file")
        assert ContextTuningMiddleware._clamp_result(result) is result

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
        assert "output truncated" in result.content

    def test_wrap_tool_call_async(self):
        from agent_handler import ContextTuningMiddleware

        async def handler(request):
            return ToolMessage(content="q" * 9000, tool_call_id="1", name="shell_exec")

        mw = ContextTuningMiddleware(provider="DeepSeek")
        result = asyncio.run(mw.awrap_tool_call(None, handler))
        assert "output truncated" in result.content


class TestModelCallTuning:
    def test_first_turn_keeps_settings(self):
        from agent_handler import ContextTuningMiddleware

        mw = ContextTuningMiddleware(provider="DeepSeek")
        request = _model_request(
            [HumanMessage(content="hi")],
            extra_body={"reasoning_effort": "high"},
            max_tokens=24576,
        )
        out = mw.wrap_model_call(request, lambda req: req)
        assert out.model.extra_body["reasoning_effort"] == "high"
        assert out.model.max_tokens == 24576

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
        assert out.model.extra_body["reasoning_effort"] == "low"
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
        assert out.model.extra_body["reasoning_effort"] == "low"
        assert out.model.max_tokens == 8192


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
