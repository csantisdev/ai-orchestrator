"""Catalogo versionado de precios de modelos (Decision 0002).

Orden de precedencia de `load_price_catalog`:
1. `config["pricing"]` — override explicito del usuario.
2. Cache local vigente (`~/.ai-orchestrator/pricing-cache.json`).
3. Catalogo remoto, solo si `refresh=True` y `catalog.allow_remote` esta activo.
4. Catalogo estatico bundleado (`docs/pricing/models.json`).
5. `DEFAULT_PRICING` en `orchestrator/costs.py`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.costs import DEFAULT_PRICING
from orchestrator.paths import PRICING_CACHE_PATH

_log = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"
STATIC_CATALOG_PATH = Path(__file__).resolve().parent.parent / "docs" / "pricing" / "models.json"

_DEFAULT_REFRESH_TTL_HOURS = 168.0


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("catalog: no se pudo leer %s: %s", path, exc)
        return None


def _extract_pricing(catalog: dict) -> dict:
    pricing: dict = {}
    for provider_data in catalog.get("providers", {}).values():
        for model_id, model_data in provider_data.get("models", {}).items():
            price = model_data.get("pricing")
            if price:
                pricing[model_id] = price
    return pricing


def _cache_is_valid(cache: dict, ttl_hours: float) -> bool:
    fetched_at = cache.get("fetched_at")
    if not fetched_at:
        return False
    try:
        fetched = datetime.fromisoformat(fetched_at)
    except ValueError:
        return False
    age_hours = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600
    return age_hours < ttl_hours


def _read_cache(config: dict) -> dict | None:
    cache = _load_json(PRICING_CACHE_PATH)
    if not cache:
        return None
    ttl_hours = config.get("catalog", {}).get("refresh_ttl_hours", _DEFAULT_REFRESH_TTL_HOURS)
    if not _cache_is_valid(cache, ttl_hours):
        return None
    return cache.get("payload")


def _fetch_remote(config: dict) -> dict | None:
    catalog_cfg = config.get("catalog", {})
    if not catalog_cfg.get("allow_remote"):
        return None
    url = catalog_cfg.get("pricing_url")
    if not url:
        return None
    try:
        import httpx
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        _log.warning("catalog: fallo al descargar catalogo remoto: %s", exc)
        return None

    if data.get("schema_version") != SCHEMA_VERSION:
        _log.warning("catalog: schema remoto %r incompatible, se ignora", data.get("schema_version"))
        return None
    return data


def _write_cache(payload: dict) -> None:
    try:
        PRICING_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cache = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": SCHEMA_VERSION,
            "payload": payload,
        }
        with PRICING_CACHE_PATH.open("w", encoding="utf-8") as f:
            json.dump(cache, f)
    except OSError as exc:
        _log.warning("catalog: no se pudo escribir cache: %s", exc)


def resolve_pricing(config: dict, refresh: bool = False) -> tuple[dict, dict]:
    """Como `load_price_catalog`, pero retorna tambien metadata de la fuente usada.

    Metadata: `{"source": "config"|"cache"|"remote"|"static"|"default", "updated_at": str|None}`.
    """
    if config.get("pricing"):
        return config["pricing"], {"source": "config", "updated_at": None}

    cached = _read_cache(config)
    if cached:
        pricing = _extract_pricing(cached)
        if pricing:
            return pricing, {"source": "cache", "updated_at": cached.get("updated_at")}

    if refresh:
        remote = _fetch_remote(config)
        if remote:
            pricing = _extract_pricing(remote)
            if pricing:
                _write_cache(remote)
                return pricing, {"source": "remote", "updated_at": remote.get("updated_at")}

    static = _load_json(STATIC_CATALOG_PATH)
    if static:
        pricing = _extract_pricing(static)
        if pricing:
            return pricing, {"source": "static", "updated_at": static.get("updated_at")}

    return DEFAULT_PRICING, {"source": "default", "updated_at": None}


def load_price_catalog(config: dict, refresh: bool = False) -> dict:
    """Resuelve la tabla de precios efectiva (forma legacy `{model: {input, output, ...}}`)."""
    return resolve_pricing(config, refresh)[0]


def get_effective_pricing(config: dict) -> dict:
    return load_price_catalog(config)


def get_model_price(config: dict, provider: str, model: str) -> dict | None:
    return get_effective_pricing(config).get(model)


def list_catalog_models(config: dict, provider: str | None = None) -> list[dict]:
    catalog = _read_cache(config) or _load_json(STATIC_CATALOG_PATH) or {}
    models = []
    for prov, provider_data in catalog.get("providers", {}).items():
        if provider and prov != provider:
            continue
        for model_id, model_data in provider_data.get("models", {}).items():
            models.append(model_data)
    return models


def _canonical_to_short_provider(catalog: dict) -> dict:
    """Invierte `provider_aliases` para mapear el nombre canonico del catalogo
    (anthropic/google/...) al nombre corto que usa el resto del orquestador
    (claude/gemini/openai/deepseek, ver `orchestrator.paths.PROVIDERS`)."""
    from orchestrator.paths import PROVIDERS

    aliases = catalog.get("provider_aliases", {})
    return {aliases.get(short, short): short for short in PROVIDERS}


def get_model_profiles(config: dict, include_deprecated: bool = False) -> list[dict]:
    """Vista compacta del catalogo para el router (`profiles_for_router`).

    Solo incluye modelos con `purpose` definido en el catalogo — los que no
    tienen perfil quedan fuera para que el router siga usando sus heuristicas
    de fallback. Por defecto excluye modelos `deprecated` salvo
    `include_deprecated=True`.
    """
    pricing = get_effective_pricing(config)
    catalog = _read_cache(config) or _load_json(STATIC_CATALOG_PATH) or {}
    canonical_to_short = _canonical_to_short_provider(catalog)

    profiles = []
    for provider, provider_data in catalog.get("providers", {}).items():
        short_provider = canonical_to_short.get(provider, provider)
        for model_id, model_data in provider_data.get("models", {}).items():
            purpose = model_data.get("purpose")
            if not purpose:
                continue
            status = model_data.get("status", "unknown")
            if status == "deprecated" and not include_deprecated:
                continue
            profiles.append({
                "provider": short_provider,
                "id": model_id,
                "status": status,
                "has_price": model_id in pricing,
                "purpose": purpose,
            })
    return profiles


def list_used_models_without_price(config: dict) -> list[dict]:
    """Modelos con runs registrados en `runs.db` que no tienen entrada en la tabla efectiva."""
    from orchestrator.db import _conn

    pricing = get_effective_pricing(config)
    conn = _conn()
    rows = conn.execute(
        "SELECT DISTINCT provider, model FROM runs WHERE model != '' ORDER BY provider, model"
    ).fetchall()
    return [
        {"provider": row["provider"], "model": row["model"]}
        for row in rows
        if row["model"] not in pricing
    ]
