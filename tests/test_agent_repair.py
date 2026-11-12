"""Regression tests for malformed textual tool-call repair in /api/agent."""

import json
from unittest.mock import patch

import pytest


class _FakeChunk:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def with_config(self, *_args, **_kwargs):
        self.config_calls = getattr(self, "config_calls", 0) + 1
        return self

    async def astream_events(self, _stream_input, config=None, version="v2"):
        text = self.outputs.pop(0)
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": _FakeChunk(text)},
        }

    async def aget_state(self, _config):
        return {}


class _FakeNonStreamAgent:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def with_config(self, *_args, **_kwargs):
        return self

    async def ainvoke(self, _stream_input, config=None):
        from langchain_core.messages import AIMessage

        return {"messages": [AIMessage(content=self.outputs.pop(0))]}

    async def aget_state(self, _config):
        return {}


class _FakeCheckpointManager:
    def __init__(self, *_args, **_kwargs):
        pass

    def latest_step_number(self, _task_id):
        return 0

    def exists(self, _task_id):
        return False

    def save_task_meta(self, *_args, **_kwargs):
        pass

    def save(self, *_args, **_kwargs):
        pass

    def build_resume_context(self, _task_id):
        return None


RAW_CALL = (
    "⚡ <function=list_dir> <parameter=path> . </parameter> "
    "</function> </tool_call>"
)


def _parse_sse(raw: bytes):
    events = []
    for block in raw.decode("utf-8", errors="replace").split("\n\n"):
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:].strip()
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    pass
        if name:
            events.append((name, data))
    return events


def _run_agent(make_handler, agent, warning=None, stream=True):
    with patch("agent_handler.build_agent", return_value=agent), patch(
        "agent_handler.CheckpointManager", _FakeCheckpointManager
    ), patch("qdrant_proxy_final.qdrant_context", return_value=("", [])), patch(
        "qdrant_proxy_final.model_tool_template_warning", return_value=warning
    ):
        body = json.dumps(
            {
                "message": "Give me a complete seller report from the two PDFs",
                "model": "qwen3-coder:30b",
                "stream": stream,
                "scan": False,
                "loop_retries": 0,
            }
        ).encode()
        return make_handler("/api/agent", "POST", body)


def test_raw_tool_call_is_retried_and_hidden(make_handler):
    agent = _FakeAgent([RAW_CALL, "Here is the seller report."])
    status, raw = _run_agent(make_handler, agent)

    assert status == 200
    text = raw.decode("utf-8", errors="replace")
    assert "<function=" not in text
    assert "<parameter=" not in text

    events = _parse_sse(raw)
    names = [name for name, _ in events]
    assert "malformed_tool_call" in names
    assert "reset" in names
    final = [data for name, data in events if name == "done"][-1]
    assert final["response"] == "Here is the seller report."


def test_unrepairable_raw_call_returns_clean_error(make_handler):
    agent = _FakeAgent([RAW_CALL, RAW_CALL, RAW_CALL])
    status, raw = _run_agent(make_handler, agent)

    assert status == 200
    text = raw.decode("utf-8", errors="replace")
    assert "<function=" not in text
    assert "<parameter=" not in text

    events = _parse_sse(raw)
    final = [data for name, data in events if name == "done"][-1]
    assert "malformed text-based tool call" in final["response"]
    assert "qwen3:14b-q8_0" in final["response"]


def test_non_streaming_raw_tool_call_is_retried(make_handler):
    agent = _FakeNonStreamAgent([RAW_CALL, "Here is the seller report."])
    status, raw = _run_agent(make_handler, agent, stream=False)

    assert status == 200
    data = json.loads(raw.split(b"\r\n\r\n", 1)[-1])
    assert data["response"] == "Here is the seller report."
    assert "<function=" not in data["response"]


def test_model_template_warning_is_streamed(make_handler):
    agent = _FakeAgent(["ok"])
    warning = "Model 'qwen3-coder:30b' has no tool-call scaffolding."
    status, raw = _run_agent(make_handler, agent, warning=warning)

    assert status == 200
    events = _parse_sse(raw)
    warnings = [data for name, data in events if name == "warning"]
    assert warnings
    assert warnings[0]["warning"] == warning


class _FakeShowResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class TestModelToolTemplateWarning:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        from qdrant_proxy_final import _MODEL_TOOL_WARNING_CACHE

        _MODEL_TOOL_WARNING_CACHE.clear()
        yield
        _MODEL_TOOL_WARNING_CACHE.clear()

    def test_warns_when_tools_capability_has_no_template(self):
        from qdrant_proxy_final import model_tool_template_warning

        payload = {"capabilities": ["completion", "tools"], "template": "short"}
        with patch(
            "qdrant_proxy_final.urllib.request.urlopen",
            return_value=_FakeShowResponse(payload),
        ):
            warning = model_tool_template_warning(
                "qwen3-coder:30b", "http://localhost:11434", "Ollama"
            )
        assert "no tool-call scaffolding" in warning

    def test_no_warning_when_template_has_tool_scaffolding(self):
        from qdrant_proxy_final import model_tool_template_warning

        payload = {
            "capabilities": ["completion", "tools"],
            "template": "{{ .Tools }} {{ .Prompt }}",
        }
        with patch(
            "qdrant_proxy_final.urllib.request.urlopen",
            return_value=_FakeShowResponse(payload),
        ):
            warning = model_tool_template_warning(
                "qwen3:14b-q8_0", "http://localhost:11434", "Ollama"
            )
        assert warning is None

    def test_skips_non_ollama_providers(self):
        from qdrant_proxy_final import model_tool_template_warning

        assert model_tool_template_warning("gpt-4o", provider="OpenAI") is None
