"""Discovery de modelos disponibles via API de Google Gemini (Generative Language API)."""

from __future__ import annotations

import httpx

API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def list_models(api_key: str) -> list[dict]:
    response = httpx.get(API_URL, params={"key": api_key}, timeout=10)
    response.raise_for_status()
    data = response.json()
    models = []
    for m in data.get("models", []):
        name = m.get("name", "")
        model_id = name.split("/")[-1] if name else ""
        models.append({
            "id": model_id,
            "display_name": m.get("displayName"),
            "context_window": m.get("inputTokenLimit"),
            "max_output_tokens": m.get("outputTokenLimit"),
        })
    return models
