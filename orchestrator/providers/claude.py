"""Provider para la API de Anthropic (Claude)."""

from __future__ import annotations

import httpx

from orchestrator.providers.base import BaseProvider, CompletionResult

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class ClaudeProvider(BaseProvider):
    name = "claude"

    def complete(self, prompt: str, system: str = "") -> CompletionResult:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system

        response = httpx.post(API_URL, headers=headers, json=body, timeout=120)
        response.raise_for_status()
        data = response.json()

        text = "".join(
            block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
        )

        return CompletionResult(
            text=text,
            provider=self.name,
            model=self.model,
            raw_response=data,
        )
