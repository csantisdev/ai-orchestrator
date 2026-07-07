"""Tests de discovery de modelos por proveedor (Decision 0002, Etapa 3)."""
from unittest.mock import MagicMock, patch

import orchestrator.model_discovery as model_discovery


def _mock_response(data: dict):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = data
    return resp


_CONFIG = {
    "providers": {
        "claude": {"api_key": "sk-ant-test", "model": "claude-sonnet-4-6"},
        "gemini": {"api_key": "AIza-test", "model": "gemini-2.5-flash"},
    }
}


def test_anthropic_adapter_normalizes_models():
    from orchestrator.discovery.anthropic import list_models
    payload = {"data": [{"id": "claude-sonnet-4-6", "display_name": "Claude Sonnet 4.6", "created_at": "2026-01-01"}]}
    with patch("httpx.get", return_value=_mock_response(payload)):
        models = list_models("sk-ant-test")
    assert models == [{"id": "claude-sonnet-4-6", "display_name": "Claude Sonnet 4.6", "created_at": "2026-01-01"}]


def test_openai_adapter_normalizes_models():
    from orchestrator.discovery.openai import list_models
    payload = {"data": [{"id": "gpt-4o", "object": "model", "created": 123}]}
    with patch("httpx.get", return_value=_mock_response(payload)):
        models = list_models("sk-test")
    assert models == [{"id": "gpt-4o", "display_name": None, "created_at": 123}]


def test_deepseek_adapter_normalizes_models():
    from orchestrator.discovery.deepseek import list_models
    payload = {"data": [{"id": "deepseek-v4-flash", "created": 456}]}
    with patch("httpx.get", return_value=_mock_response(payload)):
        models = list_models("sk-test")
    assert models == [{"id": "deepseek-v4-flash", "display_name": None, "created_at": 456}]


def test_gemini_adapter_normalizes_models():
    from orchestrator.discovery.gemini import list_models
    payload = {"models": [{
        "name": "models/gemini-2.5-flash",
        "displayName": "Gemini 2.5 Flash",
        "inputTokenLimit": 1048576,
        "outputTokenLimit": 65536,
    }]}
    with patch("httpx.get", return_value=_mock_response(payload)):
        models = list_models("AIza-test")
    assert models == [{
        "id": "gemini-2.5-flash",
        "display_name": "Gemini 2.5 Flash",
        "context_window": 1048576,
        "max_output_tokens": 65536,
    }]


def test_list_provider_models_unknown_provider_raises():
    import pytest
    with pytest.raises(RuntimeError, match="proveedor desconocido"):
        model_discovery.list_provider_models(_CONFIG, "unknown")


def test_list_provider_models_missing_api_key_raises():
    import pytest
    config = {"providers": {"claude": {"api_key": ""}}}
    with pytest.raises(RuntimeError, match="sin api_key"):
        model_discovery.list_provider_models(config, "claude")


def test_refresh_available_models_is_best_effort(tmp_path, monkeypatch):
    monkeypatch.setattr(model_discovery, "MODELS_CACHE_PATH", tmp_path / "models-cache.json")

    claude_payload = {"data": [{"id": "claude-sonnet-4-6", "display_name": "Claude Sonnet 4.6"}]}

    def _fake_get(url, headers=None, params=None, timeout=None):
        if "anthropic.com" in url:
            return _mock_response(claude_payload)
        raise ConnectionError("gemini caido")

    with patch("httpx.get", side_effect=_fake_get):
        result = model_discovery.refresh_available_models(_CONFIG)

    assert result["providers"]["claude"]["error"] is None
    assert len(result["providers"]["claude"]["models"]) == 1
    assert result["providers"]["gemini"]["error"] is not None
    assert result["providers"]["gemini"]["models"] == []

    cache_path = tmp_path / "models-cache.json"
    assert cache_path.exists()


def test_get_cached_models_reads_from_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "models-cache.json"
    monkeypatch.setattr(model_discovery, "MODELS_CACHE_PATH", cache_path)

    import json
    cache_path.write_text(json.dumps({
        "fetched_at": "2026-07-07T00:00:00Z",
        "providers": {"claude": {"models": [{"id": "claude-sonnet-4-6"}], "error": None}},
    }), encoding="utf-8")

    cached = model_discovery.get_cached_models()
    assert cached["claude"]["models"] == [{"id": "claude-sonnet-4-6"}]


def test_compare_available_vs_priced(tmp_path, monkeypatch):
    import orchestrator.catalog as catalog
    monkeypatch.setattr(catalog, "PRICING_CACHE_PATH", tmp_path / "pricing-cache.json")

    cache_path = tmp_path / "models-cache.json"
    monkeypatch.setattr(model_discovery, "MODELS_CACHE_PATH", cache_path)

    import json
    cache_path.write_text(json.dumps({
        "fetched_at": "2026-07-07T00:00:00Z",
        "providers": {
            "claude": {"models": [{"id": "claude-sonnet-4-6"}, {"id": "claude-nuevo-modelo"}], "error": None},
        },
    }), encoding="utf-8")

    comparison = model_discovery.compare_available_vs_priced({})
    by_id = {c["id"]: c["has_price"] for c in comparison}
    assert by_id["claude-sonnet-4-6"] is True
    assert by_id["claude-nuevo-modelo"] is False
