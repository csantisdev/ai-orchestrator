"""Provider para la API de OpenAI."""

from __future__ import annotations

import httpx

from orchestrator.providers.base import BaseProvider, CompletionResult

API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(BaseProvider):
    name = "openai"

    def complete(self, prompt: str, system: str = "") -> CompletionResult:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": self.model,
            "messages": messages,
        }

        response = httpx.post(API_URL, headers=headers, json=body, timeout=120)
        response.raise_for_status()
        data = response.json()

        text = data["choices"][0]["message"]["content"]

        return CompletionResult(
            text=text,
            provider=self.name,
            model=self.model,
            raw_response=data,
        )
