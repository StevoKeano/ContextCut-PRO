"""Local multi-model image diffusion support for ContextCut-PRO."""

from .client import (
    DEFAULT_WORKER_URL,
    call_worker,
    chat_client_kwargs,
    configure,
    evict_ollama,
    forward_raw,
    is_active,
    is_enabled,
    model_ids,
    rewrite_image_urls,
    set_active,
    unload_if_active,
)
from .tools import make_image_tools
from .worker import MODEL_IDS, MODEL_REGISTRY, PipelineManager, resolve_model, resolve_task

__all__ = [
    "DEFAULT_WORKER_URL",
    "MODEL_IDS",
    "MODEL_REGISTRY",
    "PipelineManager",
    "call_worker",
    "chat_client_kwargs",
    "configure",
    "evict_ollama",
    "forward_raw",
    "is_active",
    "is_enabled",
    "make_image_tools",
    "model_ids",
    "resolve_model",
    "resolve_task",
    "rewrite_image_urls",
    "set_active",
    "unload_if_active",
]
