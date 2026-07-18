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

    def to_stream_result(self) -> StreamResult:
        return StreamResult(
            text=self.text,
            provider=self.provider,
            model=self.model,
            raw_response=self.raw_response,
            cache_creation_tokens=self.cache_creation_tokens,
            cache_read_tokens=self.cache_read_tokens,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


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

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for method_name in ("complete", "complete_stream"):
            if method_name in cls.__dict__:
                extension_name = f"_{method_name}"
                raise TypeError(
                    f"{cls.__name__} cannot override {method_name}(); "
                    f"implement {extension_name}() instead"
                )

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def complete(self, prompt: str, system: str = "") -> CompletionResult:
        """Envía el prompt si la política de egress autoriza al proveedor."""
        from orchestrator import egress

        egress.check(self.name, phase="provider")
        return self._complete(prompt, system)

    @abstractmethod
    def _complete(self, prompt: str, system: str = "") -> CompletionResult:
        """Implementa la llamada no streaming del proveedor."""
        raise NotImplementedError

    def complete_stream(
        self, prompt: str, system: str = ""
    ) -> Generator[str, None, StreamResult]:
        """Inicia streaming si la política de egress autoriza al proveedor."""
        from orchestrator import egress

        egress.check(self.name, phase="stream")
        return self._complete_stream(prompt, system)

    def _complete_stream(
        self, prompt: str, system: str = ""
    ) -> Generator[str, None, StreamResult]:
        """Streaming por defecto: envuelve _complete() y emite un solo chunk."""
        result = self._complete(prompt, system)
        yield result.text
        return result.to_stream_result()
