"""Discovery de modelos disponibles por proveedor (Decision 0002, Etapa 3).

Separado de `orchestrator/providers/*`, que solo implementan `complete()`.
Cada proveedor se consulta best-effort: un error en uno no debe romper el
refresh global ni bloquear a los demas.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.paths import MODELS_CACHE_PATH, PROVIDERS

_log = logging.getLogger(__name__)

_ADAPTERS = {
    "claude": "orchestrator.discovery.anthropic",
    "openai": "orchestrator.discovery.openai",
    "deepseek": "orchestrator.discovery.deepseek",
    "gemini": "orchestrator.discovery.gemini",
}


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("model_discovery: no se pudo leer %s: %s", path, exc)
        return None


def _write_json(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError as exc:
        _log.warning("model_discovery: no se pudo escribir %s: %s", path, exc)


def list_provider_models(config: dict, provider: str) -> list[dict]:
    """Consulta el API de un unico proveedor. Lanza excepcion si falla.

    Para comportamiento best-effort agregado usar `refresh_available_models`.
    """
    import importlib

    from orchestrator.config import get_provider_config

    if provider not in _ADAPTERS:
        raise RuntimeError(f"proveedor desconocido para discovery: {provider}")

    provider_cfg = get_provider_config(config, provider)
    api_key = provider_cfg.get("api_key", "").strip()
    if not api_key:
        raise RuntimeError(f"{provider}: sin api_key configurada")

    adapter = importlib.import_module(_ADAPTERS[provider])
    return adapter.list_models(api_key)


def refresh_available_models(config: dict) -> dict:
    """Consulta todos los proveedores configurados y cachea el resultado.

    Retorna `{"fetched_at": ..., "providers": {provider: {"models": [...], "error": str|None}}}`.
    """
    providers_cfg = config.get("providers", {})
    result: dict = {"fetched_at": datetime.now(timezone.utc).isoformat(), "providers": {}}

    for provider in PROVIDERS:
        if provider not in providers_cfg:
            continue
        try:
            models = list_provider_models(config, provider)
            result["providers"][provider] = {"models": models, "error": None}
        except Exception as exc:
            _log.warning("model_discovery: %s fallo: %s", provider, exc)
            result["providers"][provider] = {"models": [], "error": str(exc)}

    _write_json(MODELS_CACHE_PATH, result)
    return result


def get_cached_models() -> dict:
    """Retorna el ultimo resultado de `refresh_available_models` desde cache local."""
    cache = _load_json(MODELS_CACHE_PATH) or {"fetched_at": None, "providers": {}}
    return cache.get("providers", {})


def compare_available_vs_priced(config: dict) -> list[dict]:
    """Compara modelos disponibles (cache de discovery) contra el catalogo de precios."""
    from orchestrator.catalog import get_effective_pricing

    pricing = get_effective_pricing(config)
    cached = get_cached_models()
    comparison = []
    for provider, data in cached.items():
        for m in data.get("models", []):
            comparison.append({
                "provider": provider,
                "id": m["id"],
                "has_price": m["id"] in pricing,
            })
    return comparison
