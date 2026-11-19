"""LangChain tools exposing local BlueTTS speech to the agent.

Pass these through ``agent_handler.build_agent(extra_tools=...)``. Results
contain proxy-relative ``/outputs/audio/<filename>`` URLs.
"""

from __future__ import annotations

import json

from langchain.tools import tool

from . import client


def make_tts_tools() -> list:
    """Build speech tools bound to the configured BlueTTS endpoint."""

    @tool
    def speak(
        text: str,
        voice: str = "",
        response_format: str = "",
        speed: float = 1.0,
    ) -> str:
        """Read text aloud with the local BlueTTS voice service.

        Use [voice] markers inside text for multi-speaker lines, e.g.
        "[david] Retrieval complete. [noa] Here are the findings.". Markdown
        and URLs are stripped automatically. Returns JSON with an audio URL.
        """
        if not client.is_enabled():
            return json.dumps({"error": "local text-to-speech is disabled"})
        clean = client.strip_markdown(text)
        if not clean:
            return json.dumps({"error": "no speakable text was provided"})
        try:
            result = client.save_speech(
                clean,
                voice=voice or None,
                response_format=response_format or None,
                speed=speed,
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)[:300]})
        return json.dumps(result)

    @tool
    def audio_briefing(
        segments: str,
        title: str = "",
        response_format: str = "",
    ) -> str:
        """Read a multi-agent briefing aloud with one voice per role.

        Pass a JSON list of {"role": ..., "text": ...} objects (or plain text).
        Roles map to distinct voices: orchestrator/planner -> david,
        researcher/RAG -> noa, coder/reviewer -> adam. Returns JSON with an
        audio URL suitable for playback in the dashboard.
        """
        if not client.is_enabled():
            return json.dumps({"error": "local text-to-speech is disabled"})
        try:
            built = client.compose_briefing(segments)
        except Exception as exc:
            return json.dumps({"error": f"invalid briefing segments: {exc}"})
        if not built:
            return json.dumps({"error": "no speakable briefing content"})
        if title:
            built = f"{client.strip_markdown(title)}. {built}"
        try:
            result = client.save_speech(
                built, response_format=response_format or None
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)[:300]})
        result["roles"] = {
            role: voice for role, voice in client.ROLE_VOICES.items()
        }
        return json.dumps(result)

    return [speak, audio_briefing]
