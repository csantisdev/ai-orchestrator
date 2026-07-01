"""Provider para la API de OpenAI."""

from __future__ import annotations

import json
from typing import Generator

import httpx

from orchestrator.providers.base import BaseProvider, CompletionResult, StreamResult

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
        usage = data.get("usage", {})

        text = data["choices"][0]["message"]["content"]

        return CompletionResult(
            text=text,
            provider=self.name,
            model=self.model,
            raw_response=data,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    def complete_stream(
        self, prompt: str, system: str = ""
    ) -> Generator[str, None, StreamResult]:
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
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        sr = StreamResult(provider=self.name, model=self.model)

        with httpx.stream("POST", API_URL, headers=headers, json=body, timeout=120) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    event = json.loads(data_str)
                except Exception:
                    continue

                choices = event.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    chunk = delta.get("content") or ""
                    if chunk:
                        sr.text += chunk
                        yield chunk

                usage = event.get("usage")
                if usage:
                    sr.input_tokens = usage.get("prompt_tokens", 0)
                    sr.output_tokens = usage.get("completion_tokens", 0)

        return sr
