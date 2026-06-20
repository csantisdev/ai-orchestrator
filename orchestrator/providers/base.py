"""Interfaz base que todo provider debe implementar."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CompletionResult:
    text: str
    provider: str
    model: str
    raw_response: dict | None = None


class BaseProvider(ABC):
    name: str = "base"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    @abstractmethod
    def complete(self, prompt: str, system: str = "") -> CompletionResult:
        """Envía el prompt al proveedor y devuelve el resultado."""
        raise NotImplementedError
