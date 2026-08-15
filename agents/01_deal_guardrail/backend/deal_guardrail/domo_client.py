"""
Drop-in replacement for the old GroqRotatingClient - same chat() /
transcribe() / parse_json_response() surface, so agent_logic.py needed no
changes beyond its import line. Calls the Domo AI Gateway (proxying
Gemini) instead of Groq. There's one shared Domo key/model for the whole
project (see the root .env), so there's no multi-key rotation here.
"""
import json
import logging
import re
from typing import Any

import requests

from . import config

logger = logging.getLogger("domo_client")

_ENDPOINT = f"{config.DOMO_BASE_URL}/ai/v1/text/generation" if config.DOMO_BASE_URL else ""


class NoDomoKeyConfigured(RuntimeError):
    pass


def _extract_output(payload: dict) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("output", "text", "content", "result"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            text = first.get("text") or first.get("message", {}).get("content")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return None


class DomoClient:
    """Round-robin/rotation is a no-op here (one key) - kept as a class so
    call sites (`client.chat(...)`) don't need to change from the Groq
    version."""

    def __init__(self):
        if not config.DOMO_API_KEY or not _ENDPOINT:
            raise NoDomoKeyConfigured(
                "DOMO_API_KEY / DOMO_BASE_URL are not configured in the shared .env."
            )

    def chat(
        self,
        messages: list[dict],
        json_mode: bool = True,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> str:
        """Sends a single-turn request built from a system + user message
        list (Groq/OpenAI-style). Returns the raw text content."""
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        user = "\n".join(m["content"] for m in messages if m["role"] != "system")

        if json_mode:
            system = (system + "\n\n" if system else "") + (
                "Respond with ONLY the JSON object described above - no markdown code "
                "fences, no commentary before or after it."
            )

        body: dict[str, Any] = {"input": user, "model": model or config.DOMO_MODEL}
        if system:
            body["system"] = system

        headers = {
            "Content-Type": "application/json",
            "X-DOMO-Developer-Token": config.DOMO_API_KEY,
        }

        resp = requests.post(_ENDPOINT, json=body, headers=headers, timeout=30)
        resp.raise_for_status()
        text = _extract_output(resp.json())
        if text is None:
            raise RuntimeError(f"Unexpected Domo response shape: {resp.text[:500]}")
        return text

    def transcribe(self, audio_bytes: bytes, filename: str = "call.wav") -> str:
        """The Domo AI Gateway (as used in this project) only exposes text
        generation, not speech-to-text - so voice-to-text isn't available
        through it. Callers should let the rep type notes directly instead."""
        raise RuntimeError(
            "Audio transcription isn't available through the Domo API in this project - "
            "type the call notes directly instead of uploading audio."
        )


def parse_json_response(raw_text: str) -> Any:
    """Same unwrapping behavior as the old Groq version, plus stripping a
    markdown code fence if the model added one anyway."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "actions", "result", "data"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return data
    return data
