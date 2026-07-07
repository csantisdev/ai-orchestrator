"""Discovery de modelos disponibles via API de Anthropic."""

from __future__ import annotations

import httpx

API_URL = "https://api.anthropic.com/v1/models"
ANTHROPIC_VERSION = "2023-06-01"


def list_models(api_key: str) -> list[dict]:
    headers = {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}
    response = httpx.get(API_URL, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()
    return [
        {"id": m["id"], "display_name": m.get("display_name"), "created_at": m.get("created_at")}
        for m in data.get("data", [])
    ]
