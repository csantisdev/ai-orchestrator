"""Provider para la API de Anthropic (Claude)."""

from __future__ import annotations

import json
from typing import Generator

import httpx

from orchestrator.providers.base import BaseProvider, CompletionResult, StreamResult

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class ClaudeProvider(BaseProvider):
    name = "claude"

    def _complete(self, prompt: str, system: str = "") -> CompletionResult:
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
        usage = data.get("usage", {})

        return CompletionResult(
            text=text,
            provider=self.name,
            model=self.model,
            raw_response=data,
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    def _complete_stream(
        self, prompt: str, system: str = ""
    ) -> Generator[str, None, StreamResult]:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system

        sr = StreamResult(provider=self.name, model=self.model)

        with httpx.stream("POST", API_URL, headers=headers, json=body, timeout=120) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    event = json.loads(data_str)
                except Exception:
                    continue

                etype = event.get("type")
                if etype == "message_start":
                    usage = event.get("message", {}).get("usage", {})
                    sr.input_tokens = usage.get("input_tokens", 0)
                    sr.cache_creation_tokens = usage.get("cache_creation_input_tokens", 0)
                    sr.cache_read_tokens = usage.get("cache_read_input_tokens", 0)
                elif etype == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        chunk = delta.get("text", "")
                        if chunk:
                            sr.text += chunk
                            yield chunk
                elif etype == "message_delta":
                    usage = event.get("usage", {})
                    sr.output_tokens = usage.get("output_tokens", 0)

        return sr
