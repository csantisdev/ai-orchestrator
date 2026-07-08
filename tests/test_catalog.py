"""Tests de precedencia del catalogo de precios (Decision 0002, Etapa 1)."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import orchestrator.catalog as catalog


def _write_cache(path, payload, fetched_at=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    cache = {
        "fetched_at": (fetched_at or datetime.now(timezone.utc)).isoformat(),
        "schema_version": catalog.SCHEMA_VERSION,
        "payload": payload,
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(cache, f)


def _catalog_payload(model_id="fake-model", input_price=1.0, output_price=2.0):
    return {
        "schema_version": catalog.SCHEMA_VERSION,
        "currency": "USD",
        "unit": "per_1m_tokens",
        "updated_at": "2026-07-01T00:00:00Z",
        "providers": {
            "fake": {
                "display_name": "Fake",
                "models": {
                    model_id: {
                        "id": model_id,
                        "provider": "fake",
                        "status": "active",
                        "pricing": {"input": input_price, "output": output_price},
                        "source_url": "https://example.com",
                        "verified_at": "2026-07-01",
                    }
                },
            }
        },
    }


def test_config_pricing_override_wins_over_everything(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", tmp_path / "pricing-cache.json")
    _write_cache(tmp_path / "pricing-cache.json", _catalog_payload("cached-model"))

    override = {"my-model": {"input": 9.0, "output": 9.0}}
    result = catalog.load_price_catalog({"pricing": override})

    assert result == override


def test_valid_cache_wins_over_static_catalog(tmp_path, monkeypatch):
    cache_path = tmp_path / "pricing-cache.json"
    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", cache_path)
    _write_cache(cache_path, _catalog_payload("cached-model", 7.0, 8.0))

    result = catalog.load_price_catalog({})

    assert result == {"cached-model": {"input": 7.0, "output": 8.0}}


def test_expired_cache_falls_back_to_static_catalog(tmp_path, monkeypatch):
    cache_path = tmp_path / "pricing-cache.json"
    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", cache_path)
    stale = datetime.now(timezone.utc) - timedelta(hours=catalog._DEFAULT_REFRESH_TTL_HOURS + 1)
    _write_cache(cache_path, _catalog_payload("cached-model"), fetched_at=stale)

    result = catalog.load_price_catalog({})

    assert "cached-model" not in result
    assert result.get("claude-sonnet-4-6") == {
        "input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30,
    }


def test_refresh_fetches_remote_and_writes_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "pricing-cache.json"
    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", cache_path)

    remote_payload = _catalog_payload("remote-model", 3.0, 4.0)
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = remote_payload

    config = {"catalog": {"allow_remote": True, "pricing_url": "https://example.com/models.json"}}
    with patch("httpx.get", return_value=mock_resp) as mock_get:
        result = catalog.load_price_catalog(config, refresh=True)

    mock_get.assert_called_once()
    assert result == {"remote-model": {"input": 3.0, "output": 4.0}}
    assert cache_path.exists()
    saved = json.loads(cache_path.read_text(encoding="utf-8"))
    assert saved["payload"] == remote_payload


def test_refresh_remote_failure_falls_back_without_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", tmp_path / "pricing-cache.json")
    config = {"catalog": {"allow_remote": True, "pricing_url": "https://example.com/models.json"}}

    with patch("httpx.get", side_effect=OSError("network down")):
        result = catalog.load_price_catalog(config, refresh=True)

    assert result.get("claude-sonnet-4-6") is not None


def test_remote_not_fetched_without_allow_remote(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", tmp_path / "pricing-cache.json")
    config = {"catalog": {"pricing_url": "https://example.com/models.json"}}

    with patch("httpx.get") as mock_get:
        catalog.load_price_catalog(config, refresh=True)

    mock_get.assert_not_called()


def test_no_cache_no_static_falls_back_to_default_pricing(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", tmp_path / "pricing-cache.json")
    monkeypatch.setattr(catalog, "STATIC_CATALOG_PATH", tmp_path / "missing-models.json")

    result = catalog.load_price_catalog({})

    from orchestrator.costs import DEFAULT_PRICING
    assert result == DEFAULT_PRICING


def test_get_model_price_known_and_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", tmp_path / "pricing-cache.json")

    assert catalog.get_model_price({}, "anthropic", "claude-sonnet-4-6") == {
        "input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30,
    }
    assert catalog.get_model_price({}, "anthropic", "no-existe") is None


def test_list_catalog_models_from_static_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", tmp_path / "pricing-cache.json")

    models = catalog.list_catalog_models({})
    ids = {m["id"] for m in models}

    assert "claude-sonnet-4-6" in ids
    assert "gemini-2.5-flash" in ids


def test_list_catalog_models_filters_by_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", tmp_path / "pricing-cache.json")

    models = catalog.list_catalog_models({}, provider="deepseek")

    assert models
    assert all(m["provider"] == "deepseek" for m in models)


def test_resolve_pricing_reports_source_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", tmp_path / "pricing-cache.json")

    pricing, meta = catalog.resolve_pricing({"pricing": {"x": {"input": 1, "output": 1}}})
    assert meta["source"] == "config"

    pricing, meta = catalog.resolve_pricing({})
    assert meta["source"] == "static"
    assert pricing.get("claude-sonnet-4-6") is not None

    monkeypatch.setattr(catalog, "STATIC_CATALOG_PATH", tmp_path / "missing.json")
    pricing, meta = catalog.resolve_pricing({})
    assert meta["source"] == "default"


def test_list_used_models_without_price(tmp_path, monkeypatch):
    import threading

    import orchestrator.db as db_mod
    import orchestrator.paths as paths_mod

    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", tmp_path / "pricing-cache.json")
    monkeypatch.setattr(paths_mod, "HOME_DIR", tmp_path)
    monkeypatch.setattr(paths_mod, "DB_PATH", tmp_path / "runs.db")
    monkeypatch.setattr(db_mod, "_local", threading.local())
    db_mod.init_db()

    db_mod.insert_run("proj", "tarea 1", "claude", "claude-sonnet-4-6")
    db_mod.insert_run("proj", "tarea 2", "mystery", "modelo-inexistente")

    missing = catalog.list_used_models_without_price({})

    assert {"provider": "mystery", "model": "modelo-inexistente"} in missing
    assert not any(m["model"] == "claude-sonnet-4-6" for m in missing)


def _catalog_payload_with_purpose(model_id="fake-model", status="active", has_purpose=True, has_price=True):
    model_entry = {
        "id": model_id,
        "provider": "fake",
        "status": status,
        "source_url": "https://example.com",
        "verified_at": "2026-07-01",
    }
    if has_price:
        model_entry["pricing"] = {"input": 1.0, "output": 2.0}
    if has_purpose:
        model_entry["purpose"] = {
            "summary": "resumen de prueba",
            "strengths": ["test_generation"],
            "weaknesses": ["architecture"],
            "routing_weight": 0.5,
        }
    return {
        "schema_version": catalog.SCHEMA_VERSION,
        "currency": "USD",
        "unit": "per_1m_tokens",
        "updated_at": "2026-07-01T00:00:00Z",
        "providers": {"fake": {"display_name": "Fake", "models": {model_id: model_entry}}},
    }


def test_get_model_profiles_only_includes_models_with_purpose(tmp_path, monkeypatch):
    cache_path = tmp_path / "pricing-cache.json"
    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", cache_path)
    payload = _catalog_payload_with_purpose("with-purpose", has_purpose=True)
    payload["providers"]["fake"]["models"]["no-purpose"] = {
        "id": "no-purpose", "provider": "fake", "status": "active",
        "pricing": {"input": 1.0, "output": 1.0},
        "source_url": "https://example.com", "verified_at": "2026-07-01",
    }
    _write_cache(cache_path, payload)

    profiles = catalog.get_model_profiles({})

    ids = {p["id"] for p in profiles}
    assert "with-purpose" in ids
    assert "no-purpose" not in ids


def test_get_model_profiles_excludes_deprecated_by_default(tmp_path, monkeypatch):
    cache_path = tmp_path / "pricing-cache.json"
    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", cache_path)
    _write_cache(cache_path, _catalog_payload_with_purpose("old-model", status="deprecated"))

    assert catalog.get_model_profiles({}) == []
    profiles = catalog.get_model_profiles({}, include_deprecated=True)
    assert len(profiles) == 1
    assert profiles[0]["status"] == "deprecated"


def test_get_model_profiles_flags_models_without_price(tmp_path, monkeypatch):
    cache_path = tmp_path / "pricing-cache.json"
    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", cache_path)
    _write_cache(cache_path, _catalog_payload_with_purpose("free-model", has_price=False))

    profiles = catalog.get_model_profiles({})

    assert len(profiles) == 1
    assert profiles[0]["has_price"] is False


def test_get_model_profiles_maps_canonical_provider_to_short_name(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", tmp_path / "pricing-cache.json")

    profiles = catalog.get_model_profiles({})
    providers = {p["provider"] for p in profiles}

    assert providers <= {"claude", "openai", "deepseek", "gemini"}
    assert "anthropic" not in providers
    assert "google" not in providers


def test_calculate_cost_still_works_via_get_pricing_table():
    from orchestrator.config import get_pricing_table
    from orchestrator.costs import calculate_cost
    from orchestrator.providers.base import CompletionResult

    pricing = get_pricing_table({})
    result = CompletionResult(
        text="ok", provider="claude", model="claude-sonnet-4-6",
        input_tokens=1_000_000, output_tokens=1_000_000, raw_response={},
    )
    cost = calculate_cost(result, pricing)

    assert cost == 18.0


# ---------------------------------------------------------------------------
# validate_model_for_provider
# ---------------------------------------------------------------------------

def test_validate_model_for_provider_known_active_model():
    result = catalog.validate_model_for_provider({}, "claude", "claude-sonnet-4-6")
    assert result["valid"] is True
    assert result["status"] == "active"
    assert result["has_price"] is True


def test_validate_model_for_provider_deprecated_model():
    result = catalog.validate_model_for_provider({}, "deepseek", "deepseek-chat")
    assert result["valid"] is True
    assert result["status"] == "deprecated"


def test_validate_model_for_provider_wrong_provider():
    # claude-sonnet-4-6 pertenece a claude/anthropic, no a openai
    result = catalog.validate_model_for_provider({}, "openai", "claude-sonnet-4-6")
    assert result["valid"] is False
    assert result["status"] is None


def test_validate_model_for_provider_unknown_model():
    result = catalog.validate_model_for_provider({}, "openai", "gpt-nonexistent-99")
    assert result["valid"] is False
    assert result["status"] is None


def test_validate_model_for_provider_unknown_provider():
    result = catalog.validate_model_for_provider({}, "unknownprov", "any-model")
    assert result["valid"] is False
    assert result["status"] is None
    assert "no mapeado" in result["reason"]


def test_validate_model_for_provider_gemini_uses_google_canonical():
    result = catalog.validate_model_for_provider({}, "gemini", "gemini-2.5-flash")
    assert result["valid"] is True
    assert result["status"] == "active"
