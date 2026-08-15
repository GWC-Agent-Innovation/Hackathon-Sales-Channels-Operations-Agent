"""
Drop-in replacement for the old GroqRotatingClient - same chat() /
transcribe() / parse_json_response() surface, so agent_logic.py needed no
changes beyond its import line.

Hybrid provider, deliberately: chat() (briefing synthesis + call-note
extraction) calls the Domo AI Gateway (proxying Gemini), matching the rest
of this project. transcribe() (voice-to-text on Screen 2) still calls Groq
Whisper, because Domo's AI Gateway as used here only exposes text
generation, not speech-to-text - there is no Domo equivalent to swap in.
"""
import json
import logging
import re
from typing import Any

import requests
from groq import Groq, APIStatusError, APIConnectionError

from . import config

logger = logging.getLogger("domo_client")

_ENDPOINT = f"{config.DOMO_BASE_URL}/ai/v1/text/generation" if config.DOMO_BASE_URL else ""


class NoGroqKeysConfigured(RuntimeError):
    pass


class AllGroqKeysExhausted(RuntimeError):
    pass


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
        self._groq_clients = [Groq(api_key=k) for k in config.GROQ_API_KEYS]
        self._groq_cursor = 0

    def _ordered_groq_clients(self):
        n = len(self._groq_clients)
        for offset in range(n):
            yield self._groq_cursor, self._groq_clients[(self._groq_cursor + offset) % n]

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
        """Voice-to-text via Groq Whisper - Domo's AI Gateway (as used in
        this project) has no speech-to-text equivalent, so this one call
        stays on Groq while chat() uses Domo."""
        if not self._groq_clients:
            raise NoGroqKeysConfigured(
                "No Groq API keys found. Set GROQ_API_KEY_1 (and optionally _2 / _3) "
                "in the shared .env to enable voice-to-text."
            )

        last_err: Exception | None = None
        for start_idx, client in self._ordered_groq_clients():
            try:
                resp = client.audio.transcriptions.create(
                    file=(filename, audio_bytes),
                    model=config.GROQ_WHISPER_MODEL,
                )
                self._groq_cursor = start_idx
                return resp.text
            except (APIStatusError, APIConnectionError) as e:
                status = getattr(e, "status_code", None)
                retryable = status in (429, 500, 502, 503, 504) or status is None
                logger.warning("Groq transcribe call failed on key #%d (status=%s): %s", start_idx, status, e)
                last_err = e
                if not retryable:
                    raise
                continue

        raise AllGroqKeysExhausted(f"All {len(self._groq_clients)} Groq API key(s) failed for transcribe(). Last error: {last_err}")


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
