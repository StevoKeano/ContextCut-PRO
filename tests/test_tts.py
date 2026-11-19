"""Tests for the local BlueTTS client, routes, tools, and verification script."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestHelpers:
    def test_voice_aliases_and_defaults(self):
        from tts import client

        assert client.normalize_voice("alloy") == "maya"
        assert client.normalize_voice("Onyx") == "david"
        assert client.normalize_voice("shimmer") == "lily"
        assert client.normalize_voice("") == client.normalize_voice()

    def test_split_text_respects_sentences_and_limit(self):
        from tts import client

        text = "First sentence. Second sentence! Third sentence? " * 200
        chunks = client.split_text(text, max_chars=1000)
        assert len(chunks) > 1
        assert all(len(chunk) <= 1000 for chunk in chunks)
        assert " ".join(chunks).replace(" ", "") == text.replace(" ", "")
        assert client.split_text("   ") == []

    def test_strip_markdown_preserves_voice_and_language_tags(self):
        from tts import client

        text = (
            "# Heading\n[david] Read this `code` from "
            "[docs](https://example.com/x) <he>שלום</he> **loudly**.\n"
            "```python\nprint('secret')\n```"
        )
        clean = client.strip_markdown(text)
        assert "Heading" in clean
        assert "[david]" in clean
        assert "<he>שלום</he>" in clean
        assert "https://" not in clean
        assert "print" not in clean
        assert "**" not in clean

    def test_compose_briefing_assigns_role_voices(self):
        from tts import client

        briefing = client.compose_briefing(
            [
                {"role": "planner", "text": "Plan ready."},
                {"role": "researcher", "text": "**Findings** [link](https://x.dev)"},
                {"role": "coder", "text": "Patch applied."},
            ]
        )
        assert briefing.startswith("[david] Plan ready.")
        assert "[noa] Findings" in briefing
        assert "[adam] Patch applied." in briefing
        assert "https://" not in briefing

    def test_wav_rewrapping_produces_valid_header(self):
        import wave

        from tts import client

        pcm = b"\x00\x00" * 240
        wav = client._wav_header(pcm)
        with wave.open(__import__("io").BytesIO(wav), "rb") as handle:
            assert handle.getframerate() == client.SAMPLE_RATE
            assert handle.getnchannels() == 1
            assert handle.getsampwidth() == 2
            assert handle.readframes(240) == pcm


class TestAsyncClient:
    @pytest.fixture
    def fake_client(self):
        response = SimpleNamespace(
            status_code=200,
            content=b"RIFFfake-audio",
            text="",
            json=lambda: {"data": [{"id": "bluev3"}]},
            raise_for_status=lambda: None,
        )
        client = MagicMock()
        client.post = AsyncMock(return_value=response)
        client.get = AsyncMock(return_value=response)
        client.is_closed = False
        return client

    def test_health_reports_offline_without_raising(self, monkeypatch):
        from tts import client

        async def broken():
            raise OSError("connection refused")

        monkeypatch.setattr(client, "_client_and_lock", broken)
        result = client.health()
        assert result["ok"] is False
        assert "connection refused" in result["error"]
        assert "latency_ms" in result

    def test_synthesize_serializes_worker_calls(self, monkeypatch, fake_client):
        from tts import client

        active = {"count": 0, "peak": 0}

        async def post(*args, **kwargs):
            active["count"] += 1
            active["peak"] = max(active["peak"], active["count"])
            await asyncio.sleep(0.01)
            active["count"] -= 1
            return SimpleNamespace(
                status_code=200, content=b"RIFFfake-audio", text=""
            )

        fake_client.post = AsyncMock(side_effect=post)

        shared = {}

        async def patched():
            shared.setdefault("lock", asyncio.Lock())
            return fake_client, shared["lock"]

        monkeypatch.setattr(client, "_client_and_lock", patched)
        monkeypatch.setattr(client, "ENABLED", True)

        async def both():
            return await asyncio.gather(
                client.synthesize_async("One. Two. Three."),
                client.synthesize_async("Four. Five. Six."),
            )

        results = client._run(both())
        assert results == [b"RIFFfake-audio", b"RIFFfake-audio"]
        assert active["peak"] == 1
        assert fake_client.post.await_count == 2

    def test_long_input_is_chunked_and_rewrapped_as_wav(self, monkeypatch):
        from tts import client

        import io
        import wave

        def wav_blob():
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(44100)
                handle.writeframes(b"\x00\x00" * 240)
            return buffer.getvalue()

        async def post(url, json=None, **kwargs):
            return SimpleNamespace(
                status_code=200, content=wav_blob(), text=""
            )

        async def patched():
            fake = MagicMock()
            fake.post = AsyncMock(side_effect=post)
            return fake, asyncio.Lock()

        monkeypatch.setattr(client, "_client_and_lock", patched)
        monkeypatch.setattr(client, "ENABLED", True)

        audio = client._run(
            client.synthesize_async("Hello there. " * 1000, response_format="wav")
        )
        with wave.open(io.BytesIO(audio), "rb") as handle:
            assert handle.getframerate() == 44100
            assert handle.getnframes() > 240

    def test_disabled_client_raises(self, monkeypatch):
        from tts import client

        monkeypatch.setattr(client, "ENABLED", False)
        with pytest.raises(RuntimeError, match="disabled"):
            client._run(client.synthesize_async("hello"))


class TestRoutes:
    def test_proxy_speech_route_returns_audio(self, make_handler, monkeypatch):
        from qdrant_proxy_final import ProxyHandler

        monkeypatch.setattr("qdrant_proxy_final.TTS_ENABLED", True)
        monkeypatch.setattr(
            "qdrant_proxy_final.tts_client.synthesize",
            lambda **kwargs: b"RIFFfake-audio",
        )
        body = json.dumps({"model": "bluev3", "input": "[david] Hello."}).encode()
        status, raw = make_handler(
            "/v1/audio/speech", "POST", body, handler_cls=ProxyHandler
        )
        assert status == 200
        assert b"audio/wav" in raw
        assert b"RIFFfake-audio" in raw

    def test_models_endpoint_lists_bluev3(self, make_handler, monkeypatch):
        from qdrant_proxy_final import ProxyHandler

        monkeypatch.setattr("qdrant_proxy_final.TTS_ENABLED", True)
        monkeypatch.setattr("qdrant_proxy_final.DIFFUSION_ENABLED", False)
        with patch(
            "qdrant_proxy_final.urllib.request.urlopen",
            return_value=_FakeResponse({"data": [{"id": "llama"}]}),
        ):
            status, raw = make_handler("/v1/models", "GET", handler_cls=ProxyHandler)
        ids = [item["id"] for item in json.loads(raw.split(b"\r\n\r\n", 1)[-1])["data"]]
        assert status == 200
        assert "bluev3" in ids

    def test_proxy_voices_route(self, make_handler, monkeypatch):
        from qdrant_proxy_final import ProxyHandler

        monkeypatch.setattr("qdrant_proxy_final.TTS_ENABLED", True)
        monkeypatch.setattr(
            "qdrant_proxy_final.tts_client.voices", lambda: ("david", "noa")
        )
        status, raw = make_handler("/v1/audio/voices", "GET", handler_cls=ProxyHandler)
        data = json.loads(raw.split(b"\r\n\r\n", 1)[-1])
        assert status == 200
        assert data["voices"] == ["david", "noa"]

    def test_proxy_speech_route_rejects_empty_input(self, make_handler, monkeypatch):
        from qdrant_proxy_final import ProxyHandler

        monkeypatch.setattr("qdrant_proxy_final.TTS_ENABLED", True)
        status, raw = make_handler(
            "/v1/audio/speech", "POST", b"{}", handler_cls=ProxyHandler
        )
        assert status == 400
        assert b"input is required" in raw

    def test_proxy_streaming_speech_route_is_chunked(self, make_handler, monkeypatch):
        from qdrant_proxy_final import ProxyHandler

        monkeypatch.setattr("qdrant_proxy_final.TTS_ENABLED", True)
        monkeypatch.setattr(
            "qdrant_proxy_final.tts_client.iter_speech",
            lambda **kwargs: iter([b"RIFF", b"chunk"]),
        )
        body = json.dumps(
            {"input": "hello", "stream_format": "audio", "response_format": "wav"}
        ).encode()
        status, raw = make_handler(
            "/v1/audio/speech", "POST", body, handler_cls=ProxyHandler
        )
        assert status == 200
        assert b"Transfer-Encoding: chunked" in raw
        assert b"RIFF" in raw and b"chunk" in raw
        assert b"0\r\n\r\n" in raw

    def test_dashboard_status_reports_disabled(self, make_handler, monkeypatch):
        monkeypatch.setattr("qdrant_proxy_final.TTS_ENABLED", False)
        status, raw = make_handler("/api/tts/status", "GET")
        body = json.loads(raw.split(b"\r\n\r\n", 1)[-1])
        assert status == 200
        assert body["ok"] is False
        assert body["enabled"] is False

    def test_dashboard_test_probes_health(self, make_handler, monkeypatch):
        monkeypatch.setattr("qdrant_proxy_final.TTS_ENABLED", True)
        with patch(
            "qdrant_proxy_final.urllib.request.urlopen",
            return_value=_FakeResponse({"status": "ready"}),
        ) as mocked:
            status, raw = make_handler(
                "/api/tts/test?url=http://localhost:8000/v1", "GET"
            )
        assert status == 200
        body = json.loads(raw.split(b"\r\n\r\n", 1)[-1])
        assert body["ok"] is True
        assert "http://localhost:8000/health" == mocked.call_args.args[0]

    def test_dashboard_speak_applies_role_voice(self, make_handler, monkeypatch):
        captured = {}

        def fake_save(text, **kwargs):
            captured["text"] = text
            return {"ok": True, "url": "/outputs/audio/test.wav", "bytes": 12}

        monkeypatch.setattr("qdrant_proxy_final.TTS_ENABLED", True)
        monkeypatch.setattr("qdrant_proxy_final.tts_client.save_speech", fake_save)
        body = json.dumps(
            {"text": "# Summary\n**Done** with https://example.com", "role": "coder"}
        ).encode()
        status, raw = make_handler("/api/tts/speak", "POST", body)
        assert status == 200
        data = json.loads(raw.split(b"\r\n\r\n", 1)[-1])
        assert data["ok"] is True
        assert captured["text"].startswith("[adam] Summary")
        assert "https://" not in captured["text"]


class TestTools:
    def test_tools_expose_speak_and_briefing(self):
        from tts.tools import make_tts_tools

        tools = make_tts_tools()
        assert {tool.name for tool in tools} == {"speak", "audio_briefing"}

    def test_speak_tool_returns_audio_url(self):
        from tts import client
        from tts.tools import make_tts_tools

        speak = next(tool for tool in make_tts_tools() if tool.name == "speak")
        with patch.object(
            client,
            "save_speech",
            return_value={"ok": True, "url": "/outputs/audio/x.wav", "bytes": 10},
        ):
            result = json.loads(speak.invoke({"text": "[david] Hi [noa] there."}))
        assert result["url"] == "/outputs/audio/x.wav"


@pytest.mark.live
def test_live_blue_tts_service():
    import verify_tts

    assert verify_tts.main() == 0
