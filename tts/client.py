"""Local BlueTTS (BlueV3 ONNX) client for ContextCut-PRO.

The service is an always-on HTTP worker; this module never starts or manages
the process.  All synthesis calls are serialized because the worker owns a
single ONNX engine.  Async callers use ``synthesize_async`` / ``stream_async``;
sync callers (stdlib HTTP handlers, LangChain tools) use the thread-safe
facades ``synthesize`` / ``iter_speech``.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import queue
import re
import threading
import time
import uuid
import wave
from pathlib import Path

import httpx

DEFAULT_BASE_URL = "http://localhost:8000/v1"
DEFAULT_VOICE = "noa"
DEFAULT_FORMAT = "wav"
MAX_CHARS = 4000
SAMPLE_RATE = 44100

NATIVE_VOICES = (
    "maya",
    "noa",
    "lily",
    "tamar",
    "shira",
    "yael",
    "emma",
    "sara",
    "adam",
    "daniel",
    "david",
    "jonathan",
    "ethan",
    "michael",
    "ariel",
)
VOICE_ALIASES = {
    "alloy": "maya",
    "echo": "adam",
    "fable": "daniel",
    "onyx": "david",
    "nova": "noa",
    "shimmer": "lily",
}
ROLE_VOICES = {
    "orchestrator": "david",
    "planner": "david",
    "coordinator": "david",
    "system": "david",
    "researcher": "noa",
    "rag": "noa",
    "retriever": "noa",
    "analyst": "noa",
    "assistant": "noa",
    "coder": "adam",
    "developer": "adam",
    "reviewer": "adam",
    "verifier": "adam",
}
CONTENT_TYPES = {
    "wav": "audio/wav",
    "pcm": "audio/x-pcm",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "opus": "audio/ogg",
    "aac": "audio/aac",
}
_FORMATS = tuple(CONTENT_TYPES)
_LANGUAGES = ("en", "he", "de", "es", "it", "ru", "yi")
_FALLBACK_VOICES = tuple(sorted(set(NATIVE_VOICES) | set(VOICE_ALIASES)))


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


BASE_URL = os.getenv("TTS_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
API_KEY = os.getenv("TTS_API_KEY", "local").strip()
DEFAULT_VOICE_NAME = os.getenv("TTS_DEFAULT_VOICE", DEFAULT_VOICE).strip().lower()
RESPONSE_FORMAT = os.getenv("TTS_FORMAT", DEFAULT_FORMAT).strip().lower()
ENABLED = _env_bool("TTS_ENABLED", True)
REQUEST_TIMEOUT = max(10, int(os.getenv("TTS_REQUEST_TIMEOUT", "120")))
OUTPUT_DIR = Path(
    os.getenv(
        "TTS_OUTPUT_DIR",
        str(Path(__file__).resolve().parent.parent / "outputs" / "audio"),
    )
).expanduser().resolve()

_config_lock = threading.Lock()
_loop = None
_loop_thread = None
_async_client = None
_async_lock = None
_voice_cache: tuple[str, ...] = ()
_voice_cache_ts = 0.0
_VOICE_CACHE_TTL = 30


def configure(base_url=None, api_key=None, voice=None, response_format=None, enabled=None):
    """Update service settings at runtime from the dashboard."""
    global BASE_URL, API_KEY, DEFAULT_VOICE_NAME, RESPONSE_FORMAT, ENABLED
    global _voice_cache_ts
    with _config_lock:
        if base_url is not None and str(base_url).strip():
            new_url = str(base_url).strip().rstrip("/")
            if new_url != BASE_URL:
                BASE_URL = new_url
                _voice_cache_ts = 0.0
        if api_key is not None:
            API_KEY = str(api_key).strip()
        if voice is not None and str(voice).strip():
            DEFAULT_VOICE_NAME = str(voice).strip().lower()
        if response_format is not None and str(response_format).strip():
            RESPONSE_FORMAT = str(response_format).strip().lower()
        if enabled is not None:
            ENABLED = (
                str(enabled).strip().lower() in ("1", "true", "yes", "on")
                if isinstance(enabled, str)
                else bool(enabled)
            )


def is_enabled() -> bool:
    return bool(ENABLED)


def api_base() -> str:
    return BASE_URL if BASE_URL.endswith("/v1") else BASE_URL + "/v1"


def root_url() -> str:
    base = BASE_URL.rstrip("/")
    return base[:-3].rstrip("/") if base.endswith("/v1") else base


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {API_KEY or 'local'}",
        "Accept": "*/*",
    }


def normalize_voice(voice=None) -> str:
    value = str(voice or DEFAULT_VOICE_NAME).strip().lower()
    return VOICE_ALIASES.get(value, value)


def normalize_format(response_format=None) -> str:
    value = str(response_format or RESPONSE_FORMAT).strip().lower()
    return value if value in _FORMATS else DEFAULT_FORMAT


def content_type(response_format=None) -> str:
    return CONTENT_TYPES.get(normalize_format(response_format), "audio/wav")


_sentence_boundary = re.compile(r"(?<=[.!?…。！？])\s+|\n+")
_marker_token = re.compile(r"\[[a-z]+\]|\S+")
_lang_tag = "en|he|de|es|it|ru|yi"


def _hard_split(text: str, limit: int) -> list[str]:
    tokens = _marker_token.findall(text)
    chunks: list[str] = []
    current = ""
    for token in tokens:
        if len(token) > limit:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(token), limit):
                pieces = token[start:start + limit]
                if start + limit < len(token):
                    chunks.append(pieces)
                else:
                    current = pieces
            continue
        candidate = token if not current else current + " " + token
        if len(candidate) <= limit:
            current = candidate
        else:
            chunks.append(current)
            current = token
    if current:
        chunks.append(current)
    return chunks


def split_text(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Split long text at sentence boundaries, then word/char boundaries."""
    limit = max(100, int(max_chars or MAX_CHARS))
    raw = str(text or "").strip()
    if not raw:
        return []
    if len(raw) <= limit:
        return [raw]
    chunks: list[str] = []
    current = ""
    for part in _sentence_boundary.split(raw):
        part = part.strip()
        if not part:
            continue
        if len(part) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_split(part, limit))
        elif not current:
            current = part
        elif len(current) + 1 + len(part) <= limit:
            current += " " + part
        else:
            chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks


def strip_markdown(text: str) -> str:
    """Remove markdown/URLs before TTS, preserving [voice] and <lang> spans."""
    value = str(text or "")
    value = re.sub(r"```.*?```", " ", value, flags=re.DOTALL)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"!?\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(rf"<(?!/?(?:{_lang_tag})\b)[^>]+>", " ", value)
    value = re.sub(r"^\s{0,3}#{1,6}\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s*[-*+]\s+", "", value, flags=re.MULTILINE)
    value = re.sub(r"[*_~]{1,3}", "", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def compose_briefing(segments, default_voice=None) -> str:
    """Build a multi-voice utterance from ``{role, text}`` segments."""
    if isinstance(segments, str):
        try:
            segments = json.loads(segments)
        except (ValueError, TypeError):
            segments = [{"role": "assistant", "text": segments}]
    if not isinstance(segments, (list, tuple)):
        segments = [{"role": "assistant", "text": str(segments)}]
    lines = []
    for item in segments:
        if not isinstance(item, dict):
            continue
        text = strip_markdown(item.get("text") or "")
        if not text:
            continue
        role = str(item.get("role") or "").lower()
        voice = normalize_voice(
            item.get("voice") or ROLE_VOICES.get(role) or default_voice
        )
        if re.match(r"^\[[a-z]+\]\s", text):
            lines.append(text)
        else:
            lines.append(f"[{voice}] {text}")
    return " ".join(lines)


def _wav_header(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)
    return buffer.getvalue()


def _merge_wav(chunks: list[bytes]) -> bytes:
    """Join WAV responses while preserving the worker's sample rate."""
    if len(chunks) == 1:
        return chunks[0]
    frames = bytearray()
    params = None
    for blob in chunks:
        try:
            with wave.open(io.BytesIO(blob), "rb") as wav:
                shape = (
                    wav.getnchannels(),
                    wav.getsampwidth(),
                    wav.getframerate(),
                    wav.getcomptype(),
                    wav.getcompname(),
                )
                if params is None:
                    params = shape
                elif shape != params:
                    raise ValueError("mismatched WAV parameters")
                frames.extend(wav.readframes(wav.getnframes()))
        except (wave.Error, EOFError, ValueError):
            return b"".join(chunks)
    if params is None:
        return b"".join(chunks)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(params[0])
        wav.setsampwidth(params[1])
        wav.setframerate(params[2])
        wav.writeframes(bytes(frames))
    return buffer.getvalue()


def _ensure_loop():
    global _loop, _loop_thread
    if _loop is not None and not _loop.is_closed():
        return _loop
    with _config_lock:
        if _loop is None or _loop.is_closed():
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=loop.run_forever, name="contextcut-tts", daemon=True
            )
            thread.start()
            _loop, _loop_thread = loop, thread
    return _loop


def _run(coro):
    """Drive an async TTS coroutine from sync handler/tool threads."""
    return asyncio.run_coroutine_threadsafe(coro, _ensure_loop()).result(
        timeout=REQUEST_TIMEOUT + 30
    )


async def _client_and_lock():
    global _async_client, _async_lock
    if _async_client is None or _async_client.is_closed:
        _async_client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
    if _async_lock is None:
        _async_lock = asyncio.Lock()
    return _async_client, _async_lock


async def health_async() -> dict:
    """Probe /health with a short timeout; never raises."""
    started = time.monotonic()
    result = {
        "ok": False,
        "enabled": is_enabled(),
        "url": root_url(),
        "latency_ms": 0,
    }
    try:
        client, _ = await _client_and_lock()
        response = await client.get(
            root_url() + "/health", headers=_headers(), timeout=3.0
        )
        result["status_code"] = response.status_code
        result["ok"] = response.status_code == 200
        try:
            payload = response.json()
            if isinstance(payload, dict):
                result.update(
                    {
                        "status": payload.get("status", ""),
                        "engine": payload.get("engine", ""),
                    }
                )
        except ValueError:
            pass
        if not result["ok"]:
            result["error"] = f"HTTP {response.status_code}"
    except Exception as exc:
        result["error"] = str(exc)[:300]
    result["latency_ms"] = int((time.monotonic() - started) * 1000)
    return result


async def voices_async(use_cache: bool = True) -> tuple[str, ...]:
    global _voice_cache, _voice_cache_ts
    now = time.monotonic()
    if use_cache and _voice_cache and now - _voice_cache_ts < _VOICE_CACHE_TTL:
        return _voice_cache
    try:
        client, _ = await _client_and_lock()
        response = await client.get(
            api_base() + "/audio/voices", headers=_headers(), timeout=5.0
        )
        response.raise_for_status()
        payload = response.json()
        rows = (
            payload.get("voices") or payload.get("data") or payload
            if isinstance(payload, (dict, list))
            else []
        )
        ids = []
        for row in rows:
            if isinstance(row, str) and row.strip():
                ids.append(row.strip())
            elif isinstance(row, dict):
                name = row.get("id") or row.get("voice") or row.get("name")
                if name:
                    ids.append(str(name))
        if ids:
            _voice_cache, _voice_cache_ts = tuple(dict.fromkeys(ids)), now
            return _voice_cache
    except Exception as exc:
        print(f"[tts] voice discovery failed: {exc}", flush=True)
    return _FALLBACK_VOICES


async def models_async() -> tuple[str, ...]:
    try:
        client, _ = await _client_and_lock()
        response = await client.get(
            api_base() + "/models", headers=_headers(), timeout=5.0
        )
        response.raise_for_status()
        payload = response.json()
        ids = tuple(
            item["id"]
            for item in (payload.get("data") or [])
            if isinstance(item, dict) and item.get("id")
        )
        if ids:
            return ids
    except Exception as exc:
        print(f"[tts] model discovery failed: {exc}", flush=True)
    return ("bluev3",)


async def synthesize_async(
    text: str,
    voice: str | None = None,
    response_format: str | None = None,
    speed: float = 1.0,
    language: str | None = None,
    model: str = "bluev3",
) -> bytes:
    """Synthesize text to audio bytes, serializing all worker calls."""
    if not is_enabled():
        raise RuntimeError("local text-to-speech is disabled")
    chunks = split_text(text)
    if not chunks:
        raise ValueError("input text is empty")
    fmt = normalize_format(response_format)
    selected_voice = normalize_voice(voice)
    client, lock = await _client_and_lock()
    started = time.monotonic()
    audio_chunks: list[bytes] = []
    async with lock:
        for chunk in chunks:
            payload = {
                "model": model or "bluev3",
                "input": chunk,
                "voice": selected_voice,
                "response_format": fmt,
                "speed": max(0.25, min(4.0, float(speed or 1.0))),
            }
            if language:
                payload["language"] = str(language).strip().lower()
            response = await client.post(
                api_base() + "/audio/speech",
                json=payload,
                headers=_headers(),
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"BlueTTS HTTP {response.status_code}: {response.text[:300]}"
                )
            audio_chunks.append(response.content)
    elapsed = time.monotonic() - started
    print(
        f"[timing] TTS synthesis {len(chunks)} chunk(s) {elapsed:.2f}s", flush=True
    )
    if fmt == "wav" and len(audio_chunks) > 1:
        return _merge_wav(audio_chunks)
    return b"".join(audio_chunks)


async def stream_async(
    text: str,
    voice: str | None = None,
    response_format: str | None = None,
    speed: float = 1.0,
    language: str | None = None,
    model: str = "bluev3",
):
    """Yield audio byte chunks while holding the single-worker mutex."""
    if not is_enabled():
        raise RuntimeError("local text-to-speech is disabled")
    chunks = split_text(text)
    if not chunks:
        raise ValueError("input text is empty")
    fmt = normalize_format(response_format)
    selected_voice = normalize_voice(voice)
    client, lock = await _client_and_lock()
    async with lock:
        for chunk in chunks:
            payload = {
                "model": model or "bluev3",
                "input": chunk,
                "voice": selected_voice,
                "response_format": fmt,
                "speed": max(0.25, min(4.0, float(speed or 1.0))),
            }
            if language:
                payload["language"] = str(language).strip().lower()
            if fmt in ("wav", "pcm"):
                payload["stream_format"] = "audio"
                async with client.stream(
                    "POST",
                    api_base() + "/audio/speech",
                    json=payload,
                    headers=_headers(),
                    timeout=REQUEST_TIMEOUT,
                ) as response:
                    if response.status_code >= 400:
                        raise RuntimeError(f"BlueTTS HTTP {response.status_code}")
                    async for piece in response.aiter_bytes(4096):
                        yield piece
            else:
                response = await client.post(
                    api_base() + "/audio/speech",
                    json=payload,
                    headers=_headers(),
                    timeout=REQUEST_TIMEOUT,
                )
                if response.status_code >= 400:
                    raise RuntimeError(f"BlueTTS HTTP {response.status_code}")
                yield response.content


def health() -> dict:
    return _run(health_async())


def voices() -> tuple[str, ...]:
    return _run(voices_async())


def models() -> tuple[str, ...]:
    return _run(models_async())


def synthesize(text: str, **kwargs) -> bytes:
    return _run(synthesize_async(text, **kwargs))


def iter_speech(text: str, **kwargs):
    """Sync byte generator bridged to the async streaming client."""
    items: queue.Queue = queue.Queue(maxsize=16)
    sentinel = object()

    async def produce():
        try:
            async for piece in stream_async(text, **kwargs):
                items.put(piece)
        except Exception as exc:
            items.put(exc)
        finally:
            items.put(sentinel)

    future = asyncio.run_coroutine_threadsafe(produce(), _ensure_loop())
    try:
        while True:
            item = items.get()
            if item is sentinel:
                break
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        if not future.done():
            future.cancel()
        try:
            future.result()
        except asyncio.CancelledError:
            pass


def save_speech(
    text: str,
    filename: str | None = None,
    voice: str | None = None,
    response_format: str | None = None,
    **kwargs,
) -> dict:
    """Synthesize text, write it under OUTPUT_DIR, return proxy-served URL."""
    fmt = normalize_format(response_format)
    audio = synthesize(text, voice=voice, response_format=fmt, **kwargs)
    name = os.path.basename(str(filename or "")).strip()
    if not name:
        name = f"speech-{uuid.uuid4().hex[:12]}.{fmt}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / name
    target.write_bytes(audio)
    return {
        "ok": True,
        "name": name,
        "path": str(target),
        "url": "/outputs/audio/" + name,
        "bytes": len(audio),
        "format": fmt,
        "voice": normalize_voice(voice),
    }
