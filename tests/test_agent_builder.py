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
        assert result == mock_agent
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
