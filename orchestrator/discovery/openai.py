"""Discovery de modelos disponibles via API de OpenAI."""

from __future__ import annotations

import httpx

API_URL = "https://api.openai.com/v1/models"


def list_models(api_key: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {api_key}"}
    response = httpx.get(API_URL, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()
    return [
        {"id": m["id"], "display_name": None, "created_at": m.get("created")}
        for m in data.get("data", [])
    ]
