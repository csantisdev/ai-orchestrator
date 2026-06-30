"""Provider para la API de Google Gemini (Generative Language API v1beta)."""

from __future__ import annotations

import httpx

from orchestrator.providers.base import BaseProvider, CompletionResult

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(BaseProvider):
    name = "gemini"

    def complete(self, prompt: str, system: str = "") -> CompletionResult:
        url = f"{API_BASE}/{self.model}:generateContent?key={self.api_key}"

        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 8192},
        }
        if system:
            body["system_instruction"] = {"parts": [{"text": system}]}

        response = httpx.post(url, json=body, timeout=120)
        response.raise_for_status()
        data = response.json()

        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts)

        usage = data.get("usageMetadata", {})
        model_version = data.get("modelVersion", self.model)

        return CompletionResult(
            text=text,
            provider=self.name,
            model=model_version,
            raw_response=data,
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
        )
