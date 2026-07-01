"""Provider para la API de Google Gemini (Generative Language API v1beta)."""

from __future__ import annotations

import json
from typing import Generator

import httpx

from orchestrator.providers.base import BaseProvider, CompletionResult, StreamResult

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

        candidates = data.get("candidates", [])
        if not candidates:
            block_reason = data.get("promptFeedback", {}).get("blockReason", "unknown")
            raise RuntimeError(f"Gemini blocked prompt: {block_reason}")

        candidate = candidates[0]
        finish_reason = candidate.get("finishReason", "STOP")
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        if not text and finish_reason != "STOP":
            raise RuntimeError(f"Gemini no text returned (finishReason={finish_reason})")

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

    def complete_stream(
        self, prompt: str, system: str = ""
    ) -> Generator[str, None, StreamResult]:
        url = f"{API_BASE}/{self.model}:streamGenerateContent?key={self.api_key}&alt=sse"

        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 8192},
        }
        if system:
            body["system_instruction"] = {"parts": [{"text": system}]}

        sr = StreamResult(provider=self.name, model=self.model)

        with httpx.stream("POST", url, json=body, timeout=120) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                try:
                    event = json.loads(data_str)
                except Exception:
                    continue

                candidates = event.get("candidates", [])
                if candidates:
                    candidate = candidates[0]
                    finish_reason = candidate.get("finishReason", "STOP")
                    parts = candidate.get("content", {}).get("parts", [])
                    chunk = "".join(p.get("text", "") for p in parts)
                    if chunk:
                        sr.text += chunk
                        yield chunk
                    elif not chunk and finish_reason not in ("STOP", ""):
                        raise RuntimeError(f"Gemini no text (finishReason={finish_reason})")

                usage = event.get("usageMetadata", {})
                if usage:
                    sr.input_tokens = usage.get("promptTokenCount", 0)
                    sr.output_tokens = usage.get("candidatesTokenCount", 0)

                model_version = event.get("modelVersion")
                if model_version:
                    sr.model = model_version

        return sr
