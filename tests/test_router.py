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


def test_decide_provider_step_agent_preset_sets_model_and_prompt_addition():
    from orchestrator.agents import AgentDefinition

    active_ctx = {
        "title": "t", "description": "d",
        "active_step": {
            "id": 1, "order_idx": 1, "title": "Revisar", "description": "",
            "provider": "claude", "agent_preset": "reviewer",
        },
    }
    fake_agent = AgentDefinition(name="reviewer", model="claude-opus-4-8", system_prompt_addition="Sé exhaustivo.")

    with patch("orchestrator.agents.get_agent", return_value=fake_agent), \
         patch("orchestrator.router.build_provider") as mock_build, \
         patch("orchestrator.router._fetch_active_context", return_value=active_ctx), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decision = decide_provider("revisar PR", _ctx(name="p"), _CONFIG)

    mock_build.assert_not_called()
    assert decision.provider == "claude"
    assert decision.model == "claude-opus-4-8"
    assert decision.system_prompt_addition == "Sé exhaustivo."


def test_decide_provider_step_agent_preset_without_step_provider_sets_provider():
    from orchestrator.agents import AgentDefinition

    active_ctx = {
        "title": "t", "description": "d",
        "active_step": {
            "id": 1, "order_idx": 1, "title": "Boilerplate", "description": "",
            "provider": "", "agent_preset": "fast",
        },
    }
    fake_agent = AgentDefinition(name="fast", provider="deepseek")

    with patch("orchestrator.agents.get_agent", return_value=fake_agent), \
         patch("orchestrator.router.build_provider") as mock_build, \
         patch("orchestrator.router._fetch_active_context", return_value=active_ctx), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decision = decide_provider("generar boilerplate", _ctx(name="p"), _CONFIG)

    mock_build.assert_not_called()
    assert decision.provider == "deepseek"


def test_decide_provider_agent_without_provider_still_applies_prompt_addition_via_llm_router():
    """Un agente que solo aporta system_prompt_addition (sin provider) debe seguir
    aplicandose aunque el router termine llamando al LLM para decidir el provider."""
    from orchestrator.agents import AgentDefinition

    mock_result = MagicMock()
    mock_result.text = '{"provider": "openai", "model": null, "reason": "decidido por el router"}'
    mock_provider = MagicMock()
    mock_provider.complete.return_value = mock_result

    active_ctx = {
        "title": "t", "description": "d",
        "active_step": {
            "id": 1, "order_idx": 1, "title": "x", "description": "",
            "provider": "", "agent_preset": "prompt-only",
        },
    }
    fake_agent = AgentDefinition(name="prompt-only", system_prompt_addition="Se breve y directo.")

    with patch("orchestrator.agents.get_agent", return_value=fake_agent), \
         patch("orchestrator.router.build_provider", return_value=mock_provider), \
         patch("orchestrator.router._fetch_active_context", return_value=active_ctx), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decision = decide_provider("tarea", _ctx(name="p"), _CONFIG)

    assert decision.provider == "openai"
    assert decision.system_prompt_addition == "Se breve y directo."


def test_decide_provider_mismatched_agent_provider_does_not_leak_model():
    """Si el step fija un provider y el agente define OTRO provider distinto,
    el model del agente NO debe aplicarse (evitaria un par provider/model
    incompatible, ej. un nombre de modelo Claude en un provider OpenAI)."""
    from orchestrator.agents import AgentDefinition

    active_ctx = {
        "title": "t", "description": "d",
        "active_step": {
            "id": 1, "order_idx": 1, "title": "x", "description": "",
            "provider": "openai", "agent_preset": "claude-persona",
        },
    }
    fake_agent = AgentDefinition(
        name="claude-persona", provider="claude", model="claude-opus-4-8",
        system_prompt_addition="Sé exhaustivo.",
    )

    with patch("orchestrator.agents.get_agent", return_value=fake_agent), \
         patch("orchestrator.router.build_provider") as mock_build, \
         patch("orchestrator.router._fetch_active_context", return_value=active_ctx), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decision = decide_provider("tarea", _ctx(name="p"), _CONFIG)

    mock_build.assert_not_called()
    assert decision.provider == "openai"
    assert decision.model is None
    assert decision.system_prompt_addition == "Sé exhaustivo."


def test_decide_provider_llm_fallthrough_applies_compatible_agent_model():
    """Si ni el step ni el agente fijan provider, el router LLM decide el
    provider — el model del agente debe aplicarse igual porque no hay
    conflicto posible (agent_def.provider es None)."""
    from orchestrator.agents import AgentDefinition

    mock_result = MagicMock()
    mock_result.text = '{"provider": "openai", "model": null, "reason": "decidido por el router"}'
    mock_provider = MagicMock()
    mock_provider.complete.return_value = mock_result

    active_ctx = {
        "title": "t", "description": "d",
        "active_step": {
            "id": 1, "order_idx": 1, "title": "x", "description": "",
            "provider": "", "agent_preset": "sin-provider",
        },
    }
    fake_agent = AgentDefinition(name="sin-provider", model="gpt-4o-mini")

    with patch("orchestrator.agents.get_agent", return_value=fake_agent), \
         patch("orchestrator.router.build_provider", return_value=mock_provider), \
         patch("orchestrator.router._fetch_active_context", return_value=active_ctx), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decision = decide_provider("tarea", _ctx(name="p"), _CONFIG)

    assert decision.provider == "openai"
    assert decision.model == "gpt-4o-mini"


def test_decide_provider_unknown_agent_preset_falls_back_to_router():
    mock_result = MagicMock()
    mock_result.text = '{"provider": "openai", "model": null, "reason": "ok"}'
    mock_provider = MagicMock()
    mock_provider.complete.return_value = mock_result

    active_ctx = {
        "title": "t", "description": "d",
        "active_step": {
            "id": 1, "order_idx": 1, "title": "x", "description": "",
            "provider": "", "agent_preset": "ghost",
        },
    }
    with patch("orchestrator.agents.get_agent", return_value=None), \
         patch("orchestrator.router.build_provider", return_value=mock_provider), \
         patch("orchestrator.router._fetch_active_context", return_value=active_ctx), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decision = decide_provider("tarea", _ctx(name="p"), _CONFIG)

    assert decision.provider == "openai"


def test_decide_provider_step_without_agent_preset_key_unaffected():
    """Simula una fila de steps pre-migracion (sin la columna agent_preset)."""
    active_ctx = {
        "title": "t", "description": "d",
        "active_step": {"id": 1, "order_idx": 1, "title": "x", "provider": "claude", "description": ""},
    }
    with patch("orchestrator.router.build_provider") as mock_build, \
         patch("orchestrator.router._fetch_active_context", return_value=active_ctx), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decision = decide_provider("tarea", _ctx(name="p"), _CONFIG)

    mock_build.assert_not_called()
    assert decision.provider == "claude"
    assert decision.system_prompt_addition is None


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
