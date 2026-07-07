"""Tests unitarios del router: keyword signals, decide_provider, fallback y step override."""
from unittest.mock import MagicMock, patch

from orchestrator.context import ProjectContext
from orchestrator.router import (
    RoutingDecision,
    _calculate_keyword_signals,
    _format_profiles_section,
    decide_provider,
)

_CONFIG = {
    "router": {"provider": "deepseek", "fallback_provider": "claude"},
    "defaults": {"default_provider": "claude"},
    "providers": {
        "deepseek": {"api_key": "sk-test", "model": "deepseek-v4-flash"},
    },
}


def _ctx(**kwargs) -> ProjectContext:
    defaults = {"name": "test-proj", "stack": "Python", "description": ""}
    return ProjectContext(**{**defaults, **kwargs})


def test_keyword_signals_match_and_no_match():
    ctx = _ctx(keyword_hints=[
        {"match": "test", "provider": "deepseek", "weight": 2},
        {"match": "arquitectura", "provider": "claude", "weight": 3},
    ])

    signals = _calculate_keyword_signals("crear tests unitarios para el módulo", ctx)
    assert len(signals) == 1
    assert signals[0]["match"] == "test"
    assert signals[0]["provider"] == "deepseek"

    no_signals = _calculate_keyword_signals("refactor del dashboard", ctx)
    assert no_signals == []


def test_decide_provider_uses_model_response():
    mock_result = MagicMock()
    mock_result.text = '{"provider": "claude", "model": null, "reason": "tarea compleja de arquitectura"}'
    mock_provider = MagicMock()
    mock_provider.complete.return_value = mock_result

    with patch("orchestrator.router.build_provider", return_value=mock_provider), \
         patch("orchestrator.router._fetch_active_context", return_value=None), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decision = decide_provider("diseñar arquitectura de seguridad", _ctx(), _CONFIG)

    assert isinstance(decision, RoutingDecision)
    assert decision.provider == "claude"
    assert decision.used_fallback is False
    assert "compleja" in decision.reason


def test_decide_provider_fallback_on_exception():
    mock_provider = MagicMock()
    mock_provider.complete.side_effect = Exception("connection timeout")

    with patch("orchestrator.router.build_provider", return_value=mock_provider), \
         patch("orchestrator.router._fetch_active_context", return_value=None), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decision = decide_provider("cualquier tarea", _ctx(), _CONFIG)

    assert decision.provider == "claude"
    assert decision.used_fallback is True
    assert "fallback" in decision.reason.lower() or "claude" in decision.reason


def test_format_profiles_section_empty():
    assert _format_profiles_section([]) == ""


def test_format_profiles_section_includes_flags():
    profiles = [
        {
            "provider": "deepseek", "id": "deepseek-v4-flash", "status": "active", "has_price": True,
            "purpose": {"summary": "económico para tests", "strengths": ["test_generation"], "weaknesses": ["architecture"]},
        },
        {
            "provider": "fake", "id": "fake-model", "status": "deprecated", "has_price": False,
            "purpose": {"summary": "viejo", "strengths": [], "weaknesses": []},
        },
    ]
    section = _format_profiles_section(profiles)

    assert "deepseek/deepseek-v4-flash" in section
    assert "test_generation" in section
    assert "[SIN PRECIO]" in section
    assert "[DEPRECATED]" in section


def test_decide_provider_includes_catalog_profiles_in_prompt():
    mock_result = MagicMock()
    mock_result.text = '{"provider": "deepseek", "model": null, "reason": "boilerplate economico"}'
    mock_provider = MagicMock()
    mock_provider.complete.return_value = mock_result

    with patch("orchestrator.router.build_provider", return_value=mock_provider), \
         patch("orchestrator.router._fetch_active_context", return_value=None), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decide_provider("generar tests de boilerplate", _ctx(), _CONFIG)

    sent_prompt = mock_provider.complete.call_args.kwargs["prompt"]
    assert "Perfiles de modelos desde el catálogo" in sent_prompt
    assert "deepseek/deepseek-v4-flash" in sent_prompt


def test_decide_provider_active_step_overrides_router():
    active_ctx = {
        "title": "Mejoras al router",
        "description": "Plan de hardening",
        "active_step": {
            "id": 42,
            "order_idx": 2,
            "title": "Escribir tests",
            "provider": "deepseek",
            "description": "",
        },
    }

    with patch("orchestrator.router.build_provider") as mock_build, \
         patch("orchestrator.router._fetch_active_context", return_value=active_ctx), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decision = decide_provider("generar test unitario", _ctx(name="test-proj"), _CONFIG)

    mock_build.assert_not_called()
    assert decision.provider == "deepseek"
    assert "Paso activo" in decision.reason
