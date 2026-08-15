import logging
import requests
from . import config

logger = logging.getLogger("domo_client")

_ENDPOINT = f"{config.DOMO_BASE_URL}/ai/v1/text/generation" if config.DOMO_BASE_URL else ""


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


def generate_text(prompt: str, system: str | None = None, timeout: int = 20) -> str | None:
    """Calls the Domo AI Gateway (proxying Gemini). Returns None on any failure so
    callers can fall back to deterministic templates instead of breaking the demo."""
    if not config.DOMO_API_KEY or not _ENDPOINT:
        logger.warning("Domo API key/base URL not configured; skipping LLM call")
        return None

    body = {"input": prompt, "model": config.DOMO_MODEL}
    if system:
        body["system"] = system

    headers = {
        "Content-Type": "application/json",
        "X-DOMO-Developer-Token": config.DOMO_API_KEY,
    }

    try:
        resp = requests.post(_ENDPOINT, json=body, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return _extract_output(resp.json())
    except Exception:
        logger.exception("Domo AI Gateway call failed; falling back to template output")
        return None
