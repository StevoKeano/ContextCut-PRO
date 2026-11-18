"""Isolated HTTP diffusion worker for ContextCut-PRO.

Runs in its own virtualenv with CUDA PyTorch/diffusers installed. The main
proxy never imports this module; only ``diffusion/client.py`` talks to it.
"""

from __future__ import annotations

import base64
import gc
import io
import json
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import unquote, urlparse

DEFAULT_MODEL_KEY = "z-image-turbo"
AUTO_MODEL_KEY = "auto"
STAGE1_MODEL_KEYS = (
    DEFAULT_MODEL_KEY,
    "flux2-klein",
    "flux1-dev",
    "flux1-kontext",
)
MODEL_IDS = STAGE1_MODEL_KEYS + (AUTO_MODEL_KEY,)
MODEL_ROOT = Path(
    os.getenv("DIFFUSION_MODEL_ROOT", "Z:/contextcut/models/official")
).expanduser()
GPU_SAMPLE_INTERVAL = float(os.getenv("DIFFUSION_GPU_SAMPLE_INTERVAL", "5"))
_gpu_sample_lock = threading.Lock()
_gpu_sample = {"ts": 0.0, "data": None}
_gpu_sampler_stop = threading.Event()
_gpu_sampler_thread = None

MODEL_ALIASES = {
    "flux.2-klein": "flux2-klein",
    "flux.2-klein-4b": "flux2-klein",
    "flux2-klein-4b": "flux2-klein",
    "flux1-dev": "flux1-dev",
    "flux.1-dev": "flux1-dev",
    "flux1-kontext": "flux1-kontext",
    "flux1-kontext-dev": "flux1-kontext",
    "flux.1-kontext": "flux1-kontext",
    "flux.1-kontext-dev": "flux1-kontext",
    "kontext": "flux1-kontext",
}
AUTO_DEFAULTS = {
    "text": DEFAULT_MODEL_KEY,
    "edit": "flux2-klein",
    "inpaint": DEFAULT_MODEL_KEY,
    "multiref": "flux2-klein",
}


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    pipelines: dict
    dtype_name: str = "bfloat16"
    steps: int = 8
    guidance_scale: float = 0.0
    local_dir: str | None = None
    max_reference_images: int = 1
    offload_mode: str | None = None
    agent_visible: bool = True


MODEL_REGISTRY = {
    DEFAULT_MODEL_KEY: ModelSpec(
        model_id="Tongyi-MAI/Z-Image-Turbo",
        pipelines={
            "text": "ZImagePipeline",
            "img2img": "ZImageImg2ImgPipeline",
            "inpaint": "ZImageInpaintPipeline",
        },
        dtype_name="bfloat16",
        steps=8,
        guidance_scale=0.0,
        local_dir="Z-Image-Turbo",
    ),
    "flux2-klein": ModelSpec(
        model_id="black-forest-labs/FLUX.2-klein-4B",
        pipelines={
            "text": "Flux2KleinPipeline",
            "img2img": "Flux2KleinPipeline",
        },
        dtype_name="bfloat16",
        steps=4,
        guidance_scale=1.0,
        local_dir="FLUX.2-klein-4B",
        max_reference_images=4,
    ),
    "flux1-dev": ModelSpec(
        model_id="black-forest-labs/FLUX.1-dev",
        pipelines={
            "text": "FluxPipeline",
            "img2img": "FluxPipeline",
        },
        dtype_name="bfloat16",
        steps=28,
        guidance_scale=3.5,
        local_dir="FLUX.1-dev",
        offload_mode="sequential",
        agent_visible=False,
    ),
    "flux1-kontext": ModelSpec(
        model_id="black-forest-labs/FLUX.1-Kontext-dev",
        pipelines={"img2img": "FluxKontextPipeline"},
        dtype_name="bfloat16",
        steps=28,
        guidance_scale=2.5,
        local_dir="FLUX.1-Kontext-dev",
        max_reference_images=4,
    ),
}

PUBLIC_MODEL_KEYS = tuple(
    key for key, spec in MODEL_REGISTRY.items() if spec.agent_visible
)
PUBLIC_MODEL_IDS = PUBLIC_MODEL_KEYS + (AUTO_MODEL_KEY,)


class GenerationCancelled(Exception):
    pass


def _hf_cache_dirs() -> list[Path]:
    roots = []
    value = os.getenv("HF_HUB_CACHE")
    if value:
        roots.append(Path(value).expanduser())
    value = os.getenv("HF_HOME")
    if value:
        roots.append(Path(value).expanduser() / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    result = []
    seen = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            result.append(root)
    return result


def _hf_snapshot_dir(model_id: str) -> str | None:
    folder = "models--" + model_id.replace("/", "--")
    for root in _hf_cache_dirs():
        snapshots = root / folder / "snapshots"
        try:
            candidates = [p for p in snapshots.iterdir() if p.is_dir()]
        except OSError:
            continue
        if candidates:
            return str(max(candidates, key=lambda p: p.stat().st_mtime_ns))
    return None


def _model_source(spec: ModelSpec) -> str:
    if spec.local_dir:
        candidate = MODEL_ROOT / spec.local_dir
        if candidate.is_dir():
            return str(candidate)
    cached = _hf_snapshot_dir(spec.model_id)
    return cached or spec.model_id


def _normalize_model_key(value) -> str:
    key = str(value or "").strip().lower().replace(" ", "")
    return MODEL_ALIASES.get(key, key)


def _configured_auto(*, reference_images: int, mask: bool) -> str:
    if mask:
        choice = "inpaint"
    elif reference_images > 1:
        choice = "multiref"
    elif reference_images:
        choice = "edit"
    else:
        choice = "text"
    key = _normalize_model_key(
        os.getenv(f"DIFFUSION_AUTO_{choice.upper()}_MODEL", AUTO_DEFAULTS[choice])
    )
    return key if key in STAGE1_MODEL_KEYS else AUTO_DEFAULTS[choice]


def resolve_model(requested=None, *, reference_images=0, mask=False) -> str:
    """Resolve a public model key to a concrete Stage 1 pipeline model key."""
    key = _normalize_model_key(requested or AUTO_MODEL_KEY)
    if key == AUTO_MODEL_KEY:
        return _configured_auto(reference_images=reference_images, mask=mask)
    if key not in MODEL_REGISTRY:
        raise ValueError(
            f"unknown diffusion model {key!r}; expected one of {', '.join(MODEL_IDS)}"
        )
    return key


def resolve_task(model_key: str, *, reference_images=0, mask=False) -> str:
    """Pick the pipeline task for a resolved model key."""
    spec = MODEL_REGISTRY[model_key]
    if mask:
        task = "inpaint"
    elif reference_images:
        task = "img2img"
    else:
        task = "text"
    if task not in spec.pipelines:
        raise ValueError(f"diffusion model {model_key!r} does not support {task}")
    if reference_images > spec.max_reference_images:
        raise ValueError(
            f"diffusion model {model_key!r} supports at most "
            f"{spec.max_reference_images} reference image(s)"
        )
    return task


def parse_size(value=None, default=1024) -> tuple[int, int]:
    """Parse an OpenAI-style ``WxH`` size into validated dimensions."""
    if not value:
        return default, default
    text = str(value).strip().lower()
    if "x" not in text:
        raise ValueError("size must look like '1024x1024'")
    width_s, height_s = text.split("x", 1)
    width, height = int(width_s), int(height_s)
    if width < 64 or height < 64 or width > 2048 or height > 2048:
        raise ValueError("size dimensions must be between 64 and 2048")
    return width - (width % 16), height - (height % 16)


def _vram_allocated() -> int:
    try:
        import torch

        if torch.cuda.is_available():
            return int(torch.cuda.memory_allocated())
    except Exception:
        pass
    return 0


def _gpu_number(value, cast=int):
    try:
        return cast(str(value).strip())
    except (TypeError, ValueError):
        return None


def _gpu_stats() -> dict:
    now = time.monotonic()
    with _gpu_sample_lock:
        cached = _gpu_sample["data"]
        if cached is not None and now - _gpu_sample["ts"] < GPU_SAMPLE_INTERVAL:
            return dict(cached)
    try:
        cmd = [
            "nvidia-smi",
            "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits",
        ]
        run_kwargs = {}
        if os.name == "nt":
            run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=3, **run_kwargs
        )
        line = (proc.stdout or "").strip().splitlines()[0]
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 6:
            raise ValueError("unexpected nvidia-smi output")
        used_mib = _gpu_number(parts[2], float)
        total_mib = _gpu_number(parts[3], float)
        data = {
            "gpu_name": parts[0] or None,
            "gpu_utilization_percent": _gpu_number(parts[1]),
            "gpu_memory_used_bytes": (
                int(used_mib * 1048576) if used_mib is not None else None
            ),
            "gpu_memory_total_bytes": (
                int(total_mib * 1048576) if total_mib is not None else None
            ),
            "gpu_temperature_c": _gpu_number(parts[4]),
            "gpu_power_watts": _gpu_number(parts[5], float),
            "gpu_error": None,
        }
    except Exception as exc:
        data = {
            "gpu_name": None,
            "gpu_utilization_percent": None,
            "gpu_memory_used_bytes": None,
            "gpu_memory_total_bytes": None,
            "gpu_temperature_c": None,
            "gpu_power_watts": None,
            "gpu_error": str(exc)[:200],
        }
    with _gpu_sample_lock:
        _gpu_sample["ts"] = time.monotonic()
        _gpu_sample["data"] = data
    return dict(data)


def _empty_gpu_stats(error: str) -> dict:
    return {
        "gpu_name": None,
        "gpu_utilization_percent": None,
        "gpu_memory_used_bytes": None,
        "gpu_memory_total_bytes": None,
        "gpu_temperature_c": None,
        "gpu_power_watts": None,
        "gpu_error": error,
    }


def _cached_gpu_stats() -> dict:
    with _gpu_sample_lock:
        data = dict(_gpu_sample["data"]) if _gpu_sample["data"] else None
        ts = _gpu_sample["ts"]
    if data is None:
        return _empty_gpu_stats("GPU sample pending")
    if time.monotonic() - ts > GPU_SAMPLE_INTERVAL * 3:
        data["gpu_error"] = "GPU sample is stale"
    return data


def _gpu_sampler_loop():
    global _gpu_sampler_thread
    while not _gpu_sampler_stop.wait(max(0.1, GPU_SAMPLE_INTERVAL)):
        try:
            _gpu_stats()
        except Exception:
            pass
    _gpu_sampler_thread = None


def start_gpu_sampler():
    global _gpu_sampler_thread
    if _gpu_sampler_thread and _gpu_sampler_thread.is_alive():
        return
    _gpu_sampler_stop.clear()
    _gpu_sampler_thread = threading.Thread(
        target=_gpu_sampler_loop,
        name="diffusion-gpu-sampler",
        daemon=True,
    )
    _gpu_sampler_thread.start()


def stop_gpu_sampler():
    _gpu_sampler_stop.set()
    if _gpu_sampler_thread and _gpu_sampler_thread.is_alive():
        _gpu_sampler_thread.join(timeout=2)


class PipelineManager:
    """Owns at most one GPU pipeline and evicts it after an idle timeout."""

    def __init__(self, idle_timeout=None):
        raw_timeout = idle_timeout
        if raw_timeout is None:
            raw_timeout = os.getenv("DIFFUSION_IDLE_TIMEOUT", "900")
        self.idle_timeout = float(raw_timeout)
        self.max_generation_seconds = float(
            os.getenv("DIFFUSION_MAX_GENERATION_SECONDS", "240")
        )
        self.pipe = None
        self.active_model_key = None
        self.active_task = None
        self.last_used_timestamp = time.monotonic()
        self.last_load_seconds = 0.0
        self.last_generation_seconds = 0.0
        self.last_pipeline_reused = False
        self.load_count = 0
        self.generation_count = 0
        self._state_lock = threading.RLock()
        self.generation_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._watchdog_thread = None

    def touch(self):
        with self._state_lock:
            self.last_used_timestamp = time.monotonic()
        self._wake.set()

    def _load_pipeline(self, model_key, task):
        import torch
        import diffusers

        started = time.monotonic()
        spec = MODEL_REGISTRY[model_key]
        class_name = spec.pipelines.get(task) or spec.pipelines["text"]
        pipeline_class = getattr(diffusers, class_name)
        dtype = getattr(torch, spec.dtype_name)
        source = _model_source(spec)
        print(f"[diffusion] loading {model_key}/{task} from {source}", flush=True)
        try:
            try:
                pipe = pipeline_class.from_pretrained(source, dtype=dtype)
            except TypeError:
                pipe = pipeline_class.from_pretrained(source, torch_dtype=dtype)
            if spec.offload_mode == "sequential":
                pipe.enable_sequential_cpu_offload()
                return pipe
            if spec.offload_mode == "model":
                pipe.enable_model_cpu_offload()
                return pipe
            return pipe.to("cuda")
        finally:
            self.last_load_seconds = time.monotonic() - started
            self.load_count += 1
            print(
                f"[diffusion] load attempt {self.load_count} for {model_key} "
                f"took {self.last_load_seconds:.1f}s",
                flush=True,
            )

    def _unload_locked(self):
        if self.pipe is not None:
            del self.pipe
        self.pipe = None
        self.active_model_key = None
        self.active_task = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def unload(self):
        with self._state_lock:
            self._unload_locked()

    def _ensure_pipeline(self, model_key, task):
        with self._state_lock:
            reused = (
                self.pipe is not None
                and self.active_model_key == model_key
                and self.active_task == task
            )
            self.last_pipeline_reused = reused
            if reused:
                self.touch()
                return self.pipe
            self._unload_locked()
            self.pipe = self._load_pipeline(model_key, task)
            self.active_model_key = model_key
            self.active_task = task
            self.touch()
            return self.pipe

    def cancel_generation(self):
        self._cancel_event.set()

    def generate(
        self,
        model_key,
        task,
        *,
        prompt,
        images=None,
        mask=None,
        width=1024,
        height=1024,
        steps=None,
        guidance_scale=None,
        strength=0.6,
        seed=None,
    ):
        """Run one generation while holding the single VRAM generation lock."""
        spec = MODEL_REGISTRY[model_key]
        with self.generation_lock:
            pipe = self._ensure_pipeline(model_key, task)
            kwargs = {
                "prompt": prompt,
                "num_inference_steps": (
                    spec.steps if steps is None else int(steps)
                ),
                "guidance_scale": (
                    spec.guidance_scale
                    if guidance_scale is None
                    else float(guidance_scale)
                ),
            }
            if seed is not None:
                import torch

                generator = torch.Generator(device="cuda").manual_seed(int(seed))
                kwargs["generator"] = generator
            if task == "text":
                kwargs.update({"height": int(height), "width": int(width)})
            elif task == "inpaint":
                kwargs.update(
                    {
                        "image": images[0] if len(images) == 1 else images,
                        "mask_image": mask,
                        "strength": float(strength),
                        "height": int(height),
                        "width": int(width),
                    }
                )
            else:
                kwargs.update(
                    {
                        "image": images[0] if len(images) == 1 else images,
                        "strength": float(strength),
                        "height": int(height),
                        "width": int(width),
                    }
                )
            self._cancel_event.clear()
            started = time.monotonic()
            watchdog_state = {"fired": False}
            watchdog_done = threading.Event()

            def check_cancel(pipe, step_index, timestep, callback_kwargs):
                if self._cancel_event.is_set():
                    raise GenerationCancelled()
                return callback_kwargs

            kwargs["callback_on_step_end"] = check_cancel
            if self.max_generation_seconds >= 0:

                def watch_generation():
                    while True:
                        if (
                            time.monotonic() - started
                            > self.max_generation_seconds
                        ):
                            watchdog_state["fired"] = True
                            self._cancel_event.set()
                            print(
                                "[diffusion] generation exceeded "
                                f"{self.max_generation_seconds:.0f}s; "
                                "cancelling and unloading pipeline",
                                flush=True,
                            )
                            return
                        if watchdog_done.wait(1.0):
                            return

                watchdog = threading.Thread(
                    target=watch_generation,
                    name="diffusion-generation-watchdog",
                    daemon=True,
                )
                watchdog.start()
            else:
                watchdog = None
            try:
                try:
                    result = pipe(**kwargs)
                except TypeError as exc:
                    if "callback_on_step_end" not in str(exc):
                        raise
                    kwargs.pop("callback_on_step_end", None)
                    result = pipe(**kwargs)
            except GenerationCancelled:
                with self._state_lock:
                    self._unload_locked()
                watchdog_state["fired"] = True
                watchdog_state["unloaded"] = True
            finally:
                watchdog_done.set()
                if watchdog is not None:
                    watchdog.join(timeout=1)
            self.last_generation_seconds = time.monotonic() - started
            self.generation_count += 1
            if watchdog_state["fired"]:
                print(
                    f"[diffusion] generation {self.generation_count} cancelled "
                    f"after {self.last_generation_seconds:.1f}s",
                    flush=True,
                )
                if not watchdog_state.get("unloaded"):
                    with self._state_lock:
                        self._unload_locked()
                raise TimeoutError(
                    "diffusion generation cancelled or exceeded "
                    f"{self.max_generation_seconds:.0f}s; worker pipeline unloaded"
                )
            print(
                f"[diffusion] generation {self.generation_count} finished in "
                f"{self.last_generation_seconds:.1f}s "
                f"(pipeline_reused={self.last_pipeline_reused})",
                flush=True,
            )
            self.touch()
            return result.images[0]

    def _watchdog_loop(self):
        while not self._stop.is_set():
            with self._state_lock:
                elapsed = time.monotonic() - self.last_used_timestamp
                remaining = self.idle_timeout - elapsed
            if remaining > 0:
                self._wake.wait(min(remaining, 1.0))
                self._wake.clear()
                continue
            if self.generation_lock.locked():
                self._stop.wait(0.1)
                continue
            with self._state_lock:
                still_idle = (
                    time.monotonic() - self.last_used_timestamp >= self.idle_timeout
                )
                if self.pipe is not None and still_idle and not self.generation_lock.locked():
                    self._unload_locked()
                else:
                    self._wake.wait(0.1)
                    self._wake.clear()

    def start_watchdog(self, timeout=None):
        if timeout is not None:
            self.idle_timeout = float(timeout)
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return
        self._stop.clear()
        self._wake.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="diffusion-idle-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

    def stop_watchdog(self):
        self._stop.set()
        self._wake.set()
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=2)
        self._watchdog_thread = None

    def status(self) -> dict:
        acquired = self._state_lock.acquire(timeout=0.05)
        snapshot = {
            "active_model": self.active_model_key,
            "active_task": self.active_task,
            "idle_timeout": self.idle_timeout,
            "last_used_timestamp": self.last_used_timestamp,
            "last_load_seconds": self.last_load_seconds,
            "last_generation_seconds": self.last_generation_seconds,
            "last_pipeline_reused": self.last_pipeline_reused,
            "load_count": self.load_count,
            "generation_count": self.generation_count,
        }
        try:
            if not acquired:
                snapshot["vram_allocated_bytes"] = 0
                snapshot["status_busy"] = True
            else:
                snapshot["vram_allocated_bytes"] = _vram_allocated()
                snapshot["status_busy"] = False
            return snapshot
        finally:
            if acquired:
                self._state_lock.release()


def _parse_multipart(content_type: str, raw_body: bytes) -> dict:
    message = policy.default.message_from_string(
        "Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n",
        policy=policy.default,
    )
    boundary = message.get_param("boundary")
    if not boundary:
        raise ValueError("multipart boundary missing")
    blob = b"Content-Type: " + content_type.encode("ascii", "replace")
    blob += b"\r\nMIME-Version: 1.0\r\n\r\n" + raw_body
    parsed = BytesParser(policy=policy.default).parsebytes(blob)
    result = {}
    for part in parsed.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            result.setdefault(name, []).append(
                {"filename": filename, "bytes": payload}
            )
        else:
            result[name] = payload.decode(part.get_content_charset() or "utf-8", "replace")
    return result


def parse_request_body(content_type: str, raw_body: bytes) -> dict:
    """Decode JSON or multipart form data into a plain dict."""
    content_type = (content_type or "").strip()
    if content_type.lower().startswith("multipart/form-data"):
        parsed = _parse_multipart(content_type, raw_body)
        for key, value in parsed.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                parsed[key] = value
        return parsed
    try:
        parsed = json.loads(raw_body or b"{}")
    except (ValueError, TypeError):
        raise ValueError("request body must be valid JSON")
    if not isinstance(parsed, dict):
        raise ValueError("request body must be a JSON object")
    return parsed


def _bytes_from_value(value) -> bytes:
    if isinstance(value, dict):
        value = value.get("bytes") or value.get("data") or b""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    text = str(value or "").strip()
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    return base64.b64decode(text + "==")


def decode_images(value) -> list:
    """Turn JSON base64 strings or multipart file parts into PIL images."""
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    from PIL import Image

    images = []
    for item in values:
        if isinstance(item, list):
            images.extend(decode_images(item))
            continue
        payload = _bytes_from_value(item)
        images.append(Image.open(io.BytesIO(payload)).convert("RGB"))
    return images


def _output_name() -> str:
    return f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:12]}.png"


def _save_image(image, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / _output_name()
    image.save(target, format="PNG")
    return target


def _data_item(path: Path, host: str, port: int, include_b64: bool) -> dict:
    item = {
        "url": f"http://{host}:{port}/outputs/images/{path.name}",
        "b64_json": None,
    }
    if include_b64:
        item["b64_json"] = base64.b64encode(path.read_bytes()).decode("ascii")
    return item


class DiffusionHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    manager = None
    output_dir = None
    bind_host = "0.0.0.0"
    public_host = "127.0.0.1"
    bind_port = 8189

    def log_message(self, fmt, *args):
        print("[diffusion] " + (fmt % args), flush=True)

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, message: str):
        self._send_json(status, {"error": str(message)[:1000]})

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        return self.rfile.read(length) if length > 0 else b""

    def _status_payload(self) -> dict:
        payload = {"status": "ok", "models": list(PUBLIC_MODEL_IDS)}
        payload.update(self.manager.status())
        payload.update(_cached_gpu_stats())
        return payload

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._send_json(200, self._status_payload())
            return
        if path == "/v1/models":
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": model, "object": "model", "owned_by": "local"}
                        for model in PUBLIC_MODEL_IDS
                    ],
                },
            )
            return
        if path.startswith("/outputs/images/"):
            name = unquote(path.rsplit("/", 1)[-1])
            target = (self.output_dir / name).resolve()
            root = self.output_dir.resolve()
            if name != Path(name).name or not target.is_relative_to(root):
                self._send_error(404, "not found")
                return
            if not target.is_file() or target.suffix.lower() != ".png":
                self._send_error(404, "not found")
                return
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._send_error(404, "not found")

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/internal/cancel":
            self.manager.cancel_generation()
            self._send_json(200, {"cancelled": True})
            return
        if path == "/internal/unload":
            self.manager.unload()
            self._send_json(200, {"unloaded": True, **self.manager.status()})
            return
        try:
            body = parse_request_body(self.headers.get("Content-Type", ""), self._read_body())
            if path == "/v1/images/generations":
                self._handle_generation(body)
                return
            if path == "/v1/images/edits":
                self._handle_edit(body)
                return
        except ValueError as exc:
            self._send_error(400, exc)
            return
        except Exception as exc:
            self._send_error(500, exc)
            return
        self._send_error(404, "not found")

    def _handle_generation(self, body: dict):
        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required")
        width, height = parse_size(body.get("size"))
        model_key = resolve_model(body.get("model"))
        spec = MODEL_REGISTRY[model_key]
        task = resolve_task(model_key)
        try:
            n = max(1, min(int(body.get("n", 1)), 4))
        except (TypeError, ValueError):
            raise ValueError("n must be an integer")
        seed = body.get("seed")
        include_b64 = str(body.get("response_format", "url")).lower() == "b64_json"
        data = []
        for index in range(n):
            item_seed = None if seed is None else int(seed) + index
            image = self.manager.generate(
                model_key,
                task,
                prompt=prompt.strip(),
                width=width,
                height=height,
                steps=body.get("steps", spec.steps),
                guidance_scale=body.get("guidance_scale", spec.guidance_scale),
                seed=item_seed,
            )
            target = _save_image(image, self.output_dir)
            data.append(
                _data_item(target, self.public_host, self.bind_port, include_b64)
            )
        self._send_json(200, {"created": int(time.time()), "data": data})

    def _handle_edit(self, body: dict):
        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required")
        images = decode_images(body.get("image") or body.get("images"))
        if not images:
            raise ValueError("at least one input image is required")
        masks = decode_images(body.get("mask"))
        mask = masks[0] if masks else None
        model_key = resolve_model(
            body.get("model", AUTO_MODEL_KEY),
            reference_images=len(images),
            mask=bool(mask),
        )
        task = resolve_task(model_key, reference_images=len(images), mask=bool(mask))
        spec = MODEL_REGISTRY[model_key]
        width, height = parse_size(body.get("size"), default=images[0].width)
        include_b64 = str(body.get("response_format", "url")).lower() == "b64_json"
        image = self.manager.generate(
            model_key,
            task,
            prompt=prompt.strip(),
            images=images,
            mask=mask,
            width=width,
            height=height,
            steps=body.get("steps", spec.steps),
            guidance_scale=body.get("guidance_scale", spec.guidance_scale),
            strength=body.get("strength", 0.6),
            seed=body.get("seed"),
        )
        target = _save_image(image, self.output_dir)
        self._send_json(
            200,
            {
                "created": int(time.time()),
                "data": [_data_item(target, self.public_host, self.bind_port, include_b64)],
            },
        )


class ReusableThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    output_dir = Path(
        os.getenv("DIFFUSION_OUTPUT_DIR", str(Path.cwd() / "outputs" / "images"))
    ).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    host = os.getenv("DIFFUSION_HOST", "0.0.0.0")
    port = int(os.getenv("DIFFUSION_PORT", "8189"))
    manager = PipelineManager()
    manager.start_watchdog()
    DiffusionHandler.manager = manager
    DiffusionHandler.output_dir = output_dir
    DiffusionHandler.bind_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    DiffusionHandler.public_host = os.getenv(
        "DIFFUSION_PUBLIC_HOST", DiffusionHandler.bind_host
    )
    DiffusionHandler.bind_port = port
    _gpu_stats()
    start_gpu_sampler()
    server = ReusableThreadingHTTPServer((host, port), DiffusionHandler)
    print(
        f"[diffusion] worker listening on {host}:{port}; outputs={output_dir}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_gpu_sampler()
        manager.stop_watchdog()
        manager.unload()
        server.server_close()


if __name__ == "__main__":
    main()
