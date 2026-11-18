"""LangChain tools exposing the local diffusion worker to the agent.

Pass these through ``agent_handler.build_agent(extra_tools=...)``. Results
contain proxy-relative ``/outputs/images/<filename>`` URLs.
"""

from __future__ import annotations

import json
import re

from langchain.tools import tool

from . import client


def _normalize_size(value=None, default="1024x1024") -> str:
    text = str(value or "").strip().lower().replace("×", "x").replace("*", "x")
    match = re.fullmatch(r"(\d{2,4})(?:x(\d{2,4}))?", text)
    if not match:
        return default
    width = int(match.group(1))
    height = int(match.group(2) or width)
    if not (64 <= width <= 2048 and 64 <= height <= 2048):
        return default
    return f"{width}x{height}"


def make_image_tools(ollama_url=None, provider=None) -> list:
    """Build image tools bound to the configured Ollama endpoint."""
    should_evict = bool(ollama_url) and provider in (None, "Ollama")
    image_calls = {"count": 0}

    def _image_call_allowed() -> bool:
        if image_calls["count"]:
            return False
        image_calls["count"] += 1
        return True


    @tool
    def generate_image(
        prompt: str,
        size: str = "1024x1024",
        model: str = "z-image-turbo",
        seed: int = 0,
        n: int = 1,
    ) -> str:
        """Generate a local image from a text prompt.

        Use only these model choices: z-image-turbo (fast default) or
        flux2-klein (fast FLUX). Returns JSON with an image URL.
        """
        if not _image_call_allowed():
            return json.dumps(
                {
                    "error": "Only one image generation or edit is allowed per "
                    "message. Ask for changes in a new message."
                }
            )
        payload = {
            "prompt": prompt,
            "model": model,
            "size": _normalize_size(size),
            "n": n,
            "response_format": "url",
        }
        if seed:
            payload["seed"] = seed
        result = client.call_worker(
            "/v1/images/generations",
            payload,
            ollama_url=ollama_url if should_evict else None,
            evict=should_evict,
        )
        return json.dumps(result)

    @tool
    def edit_image(
        prompt: str,
        image: list[str],
        model: str = "auto",
        mask: str = "",
        strength: float = 0.6,
        size: str = "1024x1024",
    ) -> str:
        """Edit one or more base64 images locally, optionally with a mask.

        Use only these model choices: auto (default), flux2-klein (fast,
        multi-reference), or flux1-kontext (character/style consistency).
        Returns JSON with an image URL.
        """
        if not _image_call_allowed():
            return json.dumps(
                {
                    "error": "Only one image generation or edit is allowed per "
                    "message. Ask for changes in a new message."
                }
            )
        payload = {
            "prompt": prompt,
            "image": image,
            "model": model,
            "strength": strength,
            "size": _normalize_size(size),
            "response_format": "url",
        }
        if mask:
            payload["mask"] = mask
        result = client.call_worker(
            "/v1/images/edits",
            payload,
            ollama_url=ollama_url if should_evict else None,
            evict=should_evict,
        )
        return json.dumps(result)

    return [generate_image, edit_image]
