"""LangChain tools exposing the local diffusion worker to the agent.

Pass these through ``agent_handler.build_agent(extra_tools=...)``. Results
contain proxy-relative ``/outputs/images/<filename>`` URLs.
"""

from __future__ import annotations

import json

from langchain.tools import tool

from . import client


def make_image_tools(ollama_url=None, provider=None) -> list:
    """Build image tools bound to the configured Ollama endpoint."""
    should_evict = bool(ollama_url) and provider in (None, "Ollama")

    @tool
    def generate_image(
        prompt: str,
        size: str = "1024x1024",
        model: str = "z-image-turbo",
        seed: int = 0,
        n: int = 1,
    ) -> str:
        """Generate a local image from a text prompt.

        Model choices: z-image-turbo (fast default), flux2-klein (fast FLUX),
        flux1-dev (higher quality). Returns JSON with an image URL.
        """
        payload = {
            "prompt": prompt,
            "model": model,
            "size": size,
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

        Model choices: auto (default), flux2-klein (fast, multi-reference),
        flux1-kontext (character/style consistency), flux1-dev (single image).
        Returns JSON with an image URL.
        """
        payload = {
            "prompt": prompt,
            "image": image,
            "model": model,
            "strength": strength,
            "size": size,
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
