"""Factory: instancia el provider correcto a partir de config.yaml."""

from __future__ import annotations

from orchestrator.config import get_provider_config
from orchestrator.providers.base import BaseProvider
from orchestrator.providers.claude import ClaudeProvider
from orchestrator.providers.deepseek import DeepSeekProvider
from orchestrator.providers.gemini import GeminiProvider
from orchestrator.providers.openai import OpenAIProvider

_REGISTRY: dict[str, type[BaseProvider]] = {
    "claude": ClaudeProvider,
    "openai": OpenAIProvider,
    "deepseek": DeepSeekProvider,
    "gemini": GeminiProvider,
}


def build_provider(config: dict, provider_name: str) -> BaseProvider:
    if provider_name not in _REGISTRY:
        raise ValueError(
            f"Proveedor desconocido: '{provider_name}'. "
            f"Opciones válidas: {', '.join(_REGISTRY)}"
        )

    provider_cfg = get_provider_config(config, provider_name)
    provider_cls = _REGISTRY[provider_name]

    return provider_cls(
        api_key=provider_cfg["api_key"],
        model=provider_cfg["model"],
    )
