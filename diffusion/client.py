"""Proxy-side client for the sibling diffusion worker.

Keeps the main proxy environment free of GPU dependencies. All heavy work is
done by ``diffusion/worker.py`` over plain HTTP; this module also owns the
bidirectional VRAM handoff between Ollama and the diffusion worker.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from urllib.parse import urlparse

import httpx

DEFAULT_WORKER_URL = "http://127.0.0.1:8189"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


WORKER_URL = os.getenv("DIFFUSION_WORKER_URL", DEFAULT_WORKER_URL).rstrip("/")
ENABLED = _env_bool("DIFFUSION_ENABLED", True)
IMAGE_BASE_URL = os.getenv("DIFFUSION_IMAGE_BASE_URL", "").strip().rstrip("/")
REQUEST_TIMEOUT = max(600, int(os.getenv("DIFFUSION_REQUEST_TIMEOUT", "900")))
OLLAMA_EVICT_TIMEOUT = max(
    5, int(os.getenv("DIFFUSION_OLLAMA_EVICT_TIMEOUT", "20"))
)
_MODEL_IDS_FALLBACK = (
    "z-image-turbo",
    "flux2-klein",
    "flux1-dev",
    "flux1-kontext",
    "auto",
)
_MODEL_CACHE_TTL = 30
_model_cache = []
_model_cache_ts = 0.0

_active_lock = threading.Lock()
_diffusion_active = False
_config_lock = threading.Lock()
_sync_client = None
_async_client = None


def configure(worker_url=None, enabled=None, image_base_url=None):
    """Update worker settings at runtime from the dashboard."""
    global WORKER_URL, ENABLED, IMAGE_BASE_URL, _model_cache_ts
    with _config_lock:
        if worker_url is not None and str(worker_url).strip():
            worker_url = str(worker_url).strip().rstrip("/")
            if worker_url != WORKER_URL:
                WORKER_URL = worker_url
                _model_cache_ts = 0.0
        if enabled is not None:
            if isinstance(enabled, str):
                ENABLED = enabled.strip().lower() in ("1", "true", "yes", "on")
            else:
                ENABLED = bool(enabled)
        if image_base_url is not None:
            IMAGE_BASE_URL = str(image_base_url).strip().rstrip("/")


def is_enabled() -> bool:
    return bool(ENABLED)


def _image_base_url() -> str:
    """Return the base URL clients should use for generated images."""
    if IMAGE_BASE_URL:
        return IMAGE_BASE_URL + "/"
    host = (urlparse(WORKER_URL).hostname or "").lower()
    if host in ("127.0.0.1", "localhost", "::1"):
        return "/outputs/images/"
    return WORKER_URL + "/outputs/images/"


def set_active(active=True):
    global _diffusion_active
    with _active_lock:
        _diffusion_active = bool(active)


def is_active() -> bool:
    with _active_lock:
        return _diffusion_active


def model_ids() -> tuple:
    """Return model keys from the worker, cached briefly for dashboard lists."""
    global _model_cache, _model_cache_ts
    now = time.monotonic()
    if _model_cache and now - _model_cache_ts < _MODEL_CACHE_TTL:
        return tuple(_model_cache)
    try:
        payload = _get_json(WORKER_URL + "/v1/models", 3)
        ids = tuple(
            item["id"]
            for item in (payload.get("data") or [])
            if isinstance(item, dict) and item.get("id")
        )
        if ids:
            _model_cache = list(ids)
            _model_cache_ts = now
            return ids
    except Exception as exc:
        print(f"[diffusion] model discovery failed: {exc}", flush=True)
    return _MODEL_IDS_FALLBACK


def _post_json(url: str, payload: dict, timeout: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str, timeout: int) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def evict_ollama(ollama_url=None) -> list:
    """Unload every model currently resident in Ollama's VRAM."""
    started = time.monotonic()
    base = (ollama_url or os.getenv("CONTEXTCUT_UPSTREAM") or "http://localhost:11434").rstrip("/")
    try:
        status = _get_json(base + "/api/ps", OLLAMA_EVICT_TIMEOUT)
    except Exception as exc:
        print(f"[diffusion] Ollama /api/ps probe failed: {exc}", flush=True)
        return []
    models = status.get("models") or []
    evicted = []
    for entry in models:
        name = None
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("model")
        elif isinstance(entry, str):
            name = entry
        if not name:
            continue
        try:
            _post_json(
                base + "/api/generate",
                {
                    "model": name,
                    "prompt": "",
                    "keep_alive": 0,
                    "stream": False,
                },
                OLLAMA_EVICT_TIMEOUT,
            )
            evicted.append(name)
        except Exception as exc:
            print(f"[diffusion] failed to evict Ollama model {name}: {exc}", flush=True)
    elapsed = time.monotonic() - started
    print(f"[timing] Ollama eviction {elapsed:.2f}s evicted={len(evicted)}", flush=True)
    if evicted:
        print(f"[diffusion] evicted Ollama models: {', '.join(evicted)}", flush=True)
    return evicted


def unload_if_active(force=False) -> bool:
    """Free diffusion VRAM before an LLM request, if weights are resident."""
    if not is_enabled():
        return False
    if not is_active() and not force:
        return False
    try:
        _post_json(WORKER_URL + "/internal/unload", {}, OLLAMA_EVICT_TIMEOUT)
        return True
    except Exception as exc:
        print(f"[diffusion] worker unload failed: {exc}", flush=True)
        return False
    finally:
        set_active(False)


def rewrite_image_urls(payload: dict) -> dict:
    """Point clients at proxy- or worker-served image URLs."""
    if not isinstance(payload, dict):
        return payload
    base = _image_base_url()
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not url:
            continue
        name = os.path.basename(urlparse(str(url)).path)
        if name:
            item["url"] = base + name
    return payload


def call_worker(path: str, payload: dict, ollama_url=None, evict=True) -> dict:
    """Evict Ollama, run a diffusion request, and rewrite returned URLs."""
    if not is_enabled():
        raise RuntimeError("local image diffusion is disabled")
    call_started = time.monotonic()
    if evict and ollama_url:
        evict_ollama(ollama_url)
    started = time.monotonic()
    try:
        result = _post_json(WORKER_URL + path, payload, REQUEST_TIMEOUT)
    finally:
        generation_elapsed = time.monotonic() - started
        print(
            f"[timing] worker generation {path} {generation_elapsed:.2f}s",
            flush=True,
        )
    if not isinstance(result, dict) or result.get("error"):
        set_active(False)
        return result
    result["elapsed_seconds"] = round(time.monotonic() - call_started, 2)
    rewrite_image_urls(result)
    set_active(True)
    return result


def forward_raw(path: str, raw_body: bytes, content_type="application/json",
                ollama_url=None) -> tuple:
    """Forward an already-encoded image request (JSON or multipart)."""
    if not is_enabled():
        raise RuntimeError("local image diffusion is disabled")
    call_started = time.monotonic()
    if ollama_url:
        evict_ollama(ollama_url)
    req = urllib.request.Request(
        WORKER_URL + path,
        data=raw_body,
        method="POST",
        headers={"Content-Type": content_type or "application/json"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            status = int(resp.status)
            try:
                payload = json.loads(resp.read().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                payload = {"error": "worker returned a non-JSON response"}
    finally:
        elapsed = time.monotonic() - started
        print(
            f"[timing] worker generation {path} {elapsed:.2f}s",
            flush=True,
        )
    if status < 400 and isinstance(payload, dict) and not payload.get("error"):
        payload["elapsed_seconds"] = round(time.monotonic() - call_started, 2)
        rewrite_image_urls(payload)
        set_active(True)
    return status, payload


def _is_chat_request(request) -> bool:
    return str(request.url.path).endswith(("/chat/completions", "/completions"))


def _sync_unload_hook(request):
    if _is_chat_request(request):
        unload_if_active()


async def _async_unload_hook(request):
    if _is_chat_request(request):
        unload_if_active()


def chat_client_kwargs() -> dict:
    """httpx clients that evict diffusion weights before agent LLM calls."""
    if not is_enabled():
        return {}
    global _sync_client, _async_client
    if _sync_client is None:
        _sync_client = httpx.Client(
            event_hooks={"request": [_sync_unload_hook]}, timeout=REQUEST_TIMEOUT
        )
    if _async_client is None:
        _async_client = httpx.AsyncClient(
            event_hooks={"request": [_async_unload_hook]}, timeout=REQUEST_TIMEOUT
        )
    return {"http_client": _sync_client, "http_async_client": _async_client}
