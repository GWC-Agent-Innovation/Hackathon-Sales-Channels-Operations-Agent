import requests

from . import config
from .domo_dataset_mapping import DOMO_DATASET_IDS

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


def get_dataset_id(dataset_name: str) -> str | None:
    dataset_id = DOMO_DATASET_IDS.get(dataset_name)
    if not dataset_id:
        return None
    return dataset_id


def query_dataset(dataset_id: str, sql: str, timeout: int = 60) -> dict | None:
    if not config.DOMO_API_KEY or not config.DOMO_BASE_URL:
        return None

    endpoint = f"{config.DOMO_BASE_URL}/query/v1/execute/{dataset_id}"
    headers = {
        "Content-Type": "application/json",
        "X-DOMO-Developer-Token": config.DOMO_API_KEY,
    }
    body = {"sql": sql}

    try:
        resp = requests.post(endpoint, json=body, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def generate_text(prompt: str, system: str | None = None, timeout: int | None = None) -> str | None:
    if not config.DOMO_API_KEY or not _ENDPOINT:
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
        return None
