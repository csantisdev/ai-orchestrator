"""Carga de config.yaml (API keys y configuración del router)."""

from __future__ import annotations

import yaml

from orchestrator.paths import CONFIG_PATH


class ConfigError(Exception):
    pass


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise ConfigError(
            f"No existe {CONFIG_PATH}. Copiá config.example.yaml a config.yaml "
            "y completá tus API keys."
        )

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if "providers" not in data:
        raise ConfigError("config.yaml inválido: falta la clave 'providers'.")

    return data


def get_provider_config(config: dict, provider: str) -> dict:
    providers = config.get("providers", {})
    if provider not in providers:
        raise ConfigError(f"El proveedor '{provider}' no está definido en config.yaml.")
    return providers[provider]


def get_router_config(config: dict) -> dict:
    return config.get("router", {"provider": "deepseek", "fallback_provider": "claude"})


def get_default_provider(config: dict) -> str:
    return config.get("defaults", {}).get("default_provider", "claude")
