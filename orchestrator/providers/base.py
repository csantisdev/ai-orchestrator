"""Interfaz base que todo provider debe implementar."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Generator, Optional


@dataclass
class CompletionResult:
    text: str
    provider: str
    model: str
    raw_response: dict | None = None
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


@dataclass
class StreamResult:
    text: str = ""
    provider: str = ""
    model: str = ""
    raw_response: dict | None = None
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def to_completion_result(self) -> CompletionResult:
        return CompletionResult(
            text=self.text,
            provider=self.provider,
            model=self.model,
            raw_response=self.raw_response,
            cache_creation_tokens=self.cache_creation_tokens,
            cache_read_tokens=self.cache_read_tokens,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


class BaseProvider(ABC):
    name: str = "base"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    @abstractmethod
    def complete(self, prompt: str, system: str = "") -> CompletionResult:
        """Envía el prompt al proveedor y devuelve el resultado completo."""
        raise NotImplementedError

    def complete_stream(
        self, prompt: str, system: str = ""
    ) -> Generator[str, None, StreamResult]:
        """Streaming por defecto: envuelve complete() y emite el texto en un solo chunk."""
        result = self.complete(prompt, system)
        yield result.text
        return StreamResult(
            text=result.text,
            provider=result.provider,
            model=result.model,
            raw_response=result.raw_response,
            cache_creation_tokens=result.cache_creation_tokens,
            cache_read_tokens=result.cache_read_tokens,
            input_tokens=result.input_tokens or 0,
            output_tokens=result.output_tokens or 0,
        )
