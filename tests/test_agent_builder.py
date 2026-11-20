"""
Tests for agent builder: ``build_agent``, ``build_messages_from_history``.

Patches ``ChatOpenAI`` and ``create_agent`` to avoid real LLM calls.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestBuildAgent:
    @patch("agent_handler.ChatOpenAI")
    @patch("agent_handler.create_agent")
    def test_returns_agent_with_tools(self, mock_create_agent, mock_chat):
        from agent_handler import build_agent, ALL_TOOLS

        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent

        result = build_agent(model_name="test-model", upstream="http://localhost:11434", api_key="test-key")
        assert result == mock_agent.with_config.return_value
        callbacks = mock_agent.with_config.call_args.args[0]["callbacks"]
        assert any(
            type(item).__name__ == "AgentTelemetryCallbackHandler"
            for item in callbacks
        )
        mock_chat.assert_called_once()
        mock_create_agent.assert_called_once()

    @patch("agent_handler.ChatOpenAI")
    @patch("agent_handler.create_agent")
    def test_uses_default_model(self, mock_create_agent, mock_chat):
        from agent_handler import build_agent

        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent

        build_agent(upstream="http://localhost:11434")
        call_kwargs = mock_chat.call_args[1]
        assert call_kwargs["model"] == "qwen3:14b-q8_0"

    @patch("agent_handler.ChatOpenAI")
    @patch("agent_handler.create_agent")
    @patch("agent_handler._get_dynamic_tools", return_value=[])
    def test_includes_dynamic_tools(self, mock_dyn, mock_create_agent, mock_chat):
        from agent_handler import build_agent, ALL_TOOLS

        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent

        build_agent(upstream="http://localhost:11434")
        tool_list_arg = mock_create_agent.call_args[1]["tools"]
        tool_names = [t.name if hasattr(t, "name") else str(t) for t in tool_list_arg]
        assert "shell_exec" in tool_names

    @patch("agent_handler.ChatOpenAI")
    @patch("agent_handler.create_agent")
    @patch("agent_handler._get_dynamic_tools", return_value=[])
    def test_includes_extra_tools(self, mock_dyn, mock_create_agent, mock_chat):
        from langchain.tools import tool

        from agent_handler import build_agent

        @tool
        def aeo_probe() -> str:
            """Probe tool."""
            return "ok"

        mock_create_agent.return_value = MagicMock()
        build_agent(upstream="http://localhost:11434", extra_tools=[aeo_probe])

        tool_names = [
            t.name if hasattr(t, "name") else str(t)
            for t in mock_create_agent.call_args[1]["tools"]
        ]
        assert "aeo_probe" in tool_names


class TestStrataReasoning:
    @pytest.mark.parametrize("value", ["none", "off", "false"])
    def test_disabled_values_authoritatively_disable_thinking(self, value):
        from agent_handler import reasoning_request_overrides

        assert reasoning_request_overrides(
            value, model_name="deepseek-v4.1-flash"
        ) == {"enable_thinking": False}

    @pytest.mark.parametrize(
        ("value", "budget"),
        [("low", 1), ("medium", 20), ("high", 50), ("max", 100)],
    )
    def test_preset_budgets(self, value, budget):
        from agent_handler import reasoning_request_overrides

        assert reasoning_request_overrides(
            value, model_name="deepseek-v4.1-flash"
        ) == {"reasoning_effort": budget}

    def test_default_budget_matches_low_preset(self):
        from agent_handler import reasoning_request_overrides

        assert reasoning_request_overrides(
            "default", model_name="deepseek-v4.1-flash"
        ) == {"reasoning_effort": 1}

    @pytest.mark.parametrize(
        ("value", "budget"), [("0", 1), ("50", 50), ("5000", 100)]
    )
    def test_raw_budget_is_clamped(self, value, budget):
        from agent_handler import reasoning_request_overrides

        assert reasoning_request_overrides(
            value, model_name="deepseek-v4.1-flash"
        ) == {"reasoning_effort": budget}

    def test_invalid_value_falls_back_to_low_preset(self):
        from agent_handler import reasoning_request_overrides

        assert reasoning_request_overrides(
            "nonsense", model_name="deepseek-v4.1-flash"
        ) == {"reasoning_effort": 1}

    @pytest.mark.parametrize("value", ["", "low", "high", "max"])
    def test_tool_turn_always_disables_strata_thinking(self, value):
        from agent_handler import reasoning_request_overrides

        assert reasoning_request_overrides(
            value,
            model_name="deepseek-v4.1-flash",
            tool_turn=True,
        ) == {"enable_thinking": False}

    def test_describe_reasoning_modes(self):
        from agent_handler import describe_reasoning_overrides

        assert describe_reasoning_overrides(
            "none", model_name="deepseek-v4.1-flash"
        ) == "thinking disabled"
        assert describe_reasoning_overrides(
            "max", model_name="deepseek-v4.1-flash"
        ) == "budget 100"
        assert describe_reasoning_overrides(
            "low", model_name="deepseek-v4.1-flash", tool_turn=True
        ) == "thinking disabled"

    def test_non_strata_values_are_unchanged(self):
        from agent_handler import reasoning_request_overrides

        assert reasoning_request_overrides(
            "low", model_name="qwen3:14b-q8_0"
        ) == {"reasoning_effort": "low"}

    @patch("agent_handler.ChatOpenAI")
    @patch("agent_handler.create_agent")
    @patch("agent_handler._get_dynamic_tools", return_value=[])
    def test_build_agent_applies_strata_overrides(
        self, mock_dyn, mock_create_agent, mock_chat
    ):
        from agent_handler import build_agent

        mock_create_agent.return_value = MagicMock()
        build_agent(
            model_name="deepseek-v4.1-flash",
            upstream="http://192.168.137.1:8080",
            provider="Custom",
            reasoning_effort="none",
        )
        call_kwargs = mock_chat.call_args[1]
        assert call_kwargs["extra_body"]["enable_thinking"] is False
        assert "reasoning_effort" not in call_kwargs["extra_body"]


class TestStrataToolTurnSuppression:
    @staticmethod
    def _request(extra_body):
        from langchain_core.messages import ToolMessage

        class FakeModel:
            def __init__(self, body):
                self.extra_body = dict(body)
                self.max_tokens = None

            def model_copy(self, update=None):
                model = FakeModel(self.extra_body)
                for key, value in (update or {}).items():
                    setattr(model, key, value)
                return model

        class FakeRequest:
            def __init__(self, model, messages):
                self.model = model
                self.messages = messages

            def override(self, *, model):
                self.model = model
                return self

        return FakeRequest(
            FakeModel(extra_body),
            [
                ToolMessage(
                    content="ok", name="shell_exec", tool_call_id="tool-1", id="tool-1"
                )
            ],
        )

    def test_clears_budgets_and_disables_thinking_after_tool_message(self):
        from agent_handler import ContextTuningMiddleware

        middleware = ContextTuningMiddleware(
            provider="Custom",
            model_name="deepseek-v4.1-flash",
            upstream="http://192.168.137.1:8080",
        )
        tuned = middleware._tune_model_request(
            self._request(
                {
                    "enable_thinking": True,
                    "reasoning_effort": 4096,
                    "budget_tokens": 8192,
                }
            )
        )
        assert tuned.model.extra_body == {"enable_thinking": False}


class TestAgentTelemetry:
    def test_logs_ttft_and_token_rate(self, capsys):
        from agent_handler import AgentTelemetryCallbackHandler

        handler = AgentTelemetryCallbackHandler("thinking disabled", "deepseek-v4.1-flash")
        response = MagicMock()
        response.llm_output = {"token_usage": {"completion_tokens": 10}}
        handler.on_llm_start({}, [], run_id="run-1")
        handler.on_llm_new_token("a", run_id="run-1")
        handler.on_llm_end(response, run_id="run-1")

        output = capsys.readouterr().out
        assert "[telemetry] llm start" in output
        assert "[telemetry] ttft" in output
        assert "[telemetry] llm end" in output
        assert "tokens=10" in output
        assert "tok/s" in output
        assert "reasoning=thinking disabled" in output

    @patch("agent_handler.ChatOpenAI")
    @patch("agent_handler.create_agent")
    def test_build_agent_attaches_telemetry(self, mock_create_agent, mock_chat):
        from agent_handler import AgentTelemetryCallbackHandler, build_agent

        mock_agent = MagicMock()
        mock_create_agent.return_value = mock_agent
        build_agent(upstream="http://localhost:11434")

        callbacks = mock_agent.with_config.call_args.args[0]["callbacks"]
        assert any(isinstance(item, AgentTelemetryCallbackHandler) for item in callbacks)


class TestStreamChunkTimeoutConfig:
    @patch("agent_handler.ChatOpenAI")
    @patch("agent_handler.create_agent")
    def test_default_is_600(self, mock_create_agent, mock_chat, monkeypatch):
        from agent_handler import build_agent

        monkeypatch.delenv("CONTEXTCUT_STREAM_CHUNK_TIMEOUT", raising=False)
        monkeypatch.delenv("LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S", raising=False)
        mock_create_agent.return_value = MagicMock()

        build_agent(upstream="http://localhost:11434")

        assert mock_chat.call_args[1]["stream_chunk_timeout"] == 600.0

    @patch("agent_handler.ChatOpenAI")
    @patch("agent_handler.create_agent")
    def test_app_env_override(self, mock_create_agent, mock_chat, monkeypatch):
        from agent_handler import build_agent

        monkeypatch.setenv("CONTEXTCUT_STREAM_CHUNK_TIMEOUT", "900")
        monkeypatch.delenv("LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S", raising=False)
        mock_create_agent.return_value = MagicMock()

        build_agent(upstream="http://localhost:11434")

        assert mock_chat.call_args[1]["stream_chunk_timeout"] == 900.0

    @patch("agent_handler.ChatOpenAI")
    @patch("agent_handler.create_agent")
    def test_langchain_env_fallback(self, mock_create_agent, mock_chat, monkeypatch):
        from agent_handler import build_agent

        monkeypatch.delenv("CONTEXTCUT_STREAM_CHUNK_TIMEOUT", raising=False)
        monkeypatch.setenv("LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S", "450")
        mock_create_agent.return_value = MagicMock()

        build_agent(upstream="http://localhost:11434")

        assert mock_chat.call_args[1]["stream_chunk_timeout"] == 450.0

    @patch("agent_handler.ChatOpenAI")
    @patch("agent_handler.create_agent")
    def test_zero_disables(self, mock_create_agent, mock_chat, monkeypatch):
        from agent_handler import build_agent

        monkeypatch.setenv("CONTEXTCUT_STREAM_CHUNK_TIMEOUT", "0")
        mock_create_agent.return_value = MagicMock()

        build_agent(upstream="http://localhost:11434")

        assert mock_chat.call_args[1]["stream_chunk_timeout"] is None


class TestContextTuningWiring:
    @patch("agent_handler.ChatOpenAI")
    @patch("agent_handler.create_agent")
    @patch("agent_handler._get_dynamic_tools", return_value=[])
    def test_middleware_and_reasoning_params(
        self, mock_dyn, mock_create_agent, mock_chat
    ):
        from agent_handler import ContextTuningMiddleware, build_agent

        mock_create_agent.return_value = MagicMock()
        build_agent(
            upstream="http://localhost:11434",
            provider="DeepSeek",
            reasoning_effort="high",
            max_tokens=24576,
        )

        call_kwargs = mock_chat.call_args[1]
        assert call_kwargs["extra_body"] == {"reasoning_effort": 50}
        assert call_kwargs["max_tokens"] == 24576

        middleware = mock_create_agent.call_args[1]["middleware"]
        assert any(isinstance(item, ContextTuningMiddleware) for item in middleware)


class TestBuildMessagesFromHistory:
    def test_converts_user_assistant_system(self):
        from agent_handler import build_messages_from_history
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

        history = [
            {"role": "system", "content": "You are a bot."},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        msgs = build_messages_from_history(history)
        assert len(msgs) == 3
        assert isinstance(msgs[0], SystemMessage)
        assert isinstance(msgs[1], HumanMessage)
        assert isinstance(msgs[2], AIMessage)

    def test_empty_history(self):
        from agent_handler import build_messages_from_history

        msgs = build_messages_from_history([])
        assert msgs == []

    def test_unknown_role_skipped(self):
        from agent_handler import build_messages_from_history

        history = [{"role": "unknown", "content": "test"}]
        msgs = build_messages_from_history(history)
        assert len(msgs) == 0
