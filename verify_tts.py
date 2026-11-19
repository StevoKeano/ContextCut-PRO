#!/usr/bin/env python3
"""Live smoke test for the always-on BlueTTS HTTP service.

Checks GET /health, synthesizes a multi-voice phrase to a .wav file, and
verifies the audio is non-empty. Does not start or manage the server.

    python verify_tts.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = os.getenv("TTS_BASE_URL", "http://localhost:8000/v1").rstrip("/")
API_KEY = os.getenv("TTS_API_KEY", "local")
PHRASE = "[david] System check. [noa] BlueTTS integration active."
OUTPUT = Path(
    os.getenv(
        "TTS_VERIFY_OUTPUT",
        str(Path(__file__).resolve().parent / "outputs" / "audio" / "tts-check.wav"),
    )
)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {API_KEY or 'local'}",
        "Content-Type": "application/json",
    }


def _root_url() -> str:
    return BASE_URL[:-3].rstrip("/") if BASE_URL.endswith("/v1") else BASE_URL


def _api_base() -> str:
    return BASE_URL if BASE_URL.endswith("/v1") else BASE_URL + "/v1"


def main() -> int:
    try:
        with urllib.request.urlopen(
            _root_url() + "/health", timeout=5
        ) as response:
            if response.status != 200:
                print(f"FAIL: /health returned HTTP {response.status}")
                return 1
            print("OK: /health -> 200")
    except Exception as exc:
        print(f"FAIL: /health unreachable at {_root_url()}: {exc}")
        return 1

    payload = {
        "model": "bluev3",
        "input": PHRASE,
        "voice": "noa",
        "response_format": "wav",
        "speed": 1.0,
    }
    request = urllib.request.Request(
        _api_base() + "/audio/speech",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            audio = response.read()
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        print(f"FAIL: speech request returned HTTP {exc.code}: {detail}")
        return 1
    except Exception as exc:
        print(f"FAIL: speech request errored: {exc}")
        return 1

    if not audio or len(audio) <= 44:
        print(f"FAIL: audio output is empty or too small ({len(audio)} bytes)")
        return 1
    if b"RIFF" not in audio[:16] and "wav" not in content_type.lower():
        print("FAIL: response is neither RIFF/WAV nor a WAV content type")
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(audio)
    print(f"OK: synthesized {len(audio)} bytes -> {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
