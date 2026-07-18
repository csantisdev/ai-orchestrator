"""Tests unitarios del router: keyword signals, decide_provider, fallback y step override."""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from orchestrator import egress
from orchestrator.context import ProjectContext
from orchestrator.egress import EgressBlocked, policy_for_project, set_policy
from orchestrator.paths import PROVIDERS
from orchestrator.router import (
    RoutingDecision,
    _calculate_keyword_signals,
    _fetch_similar_runs,
    _format_profiles_section,
    decide_provider,
    decide_with_local_router,
    force_provider,
)

_CONFIG = {
    "router": {"provider": "deepseek", "fallback_provider": "claude"},
    "defaults": {"default_provider": "claude"},
    "providers": {
        "deepseek": {"api_key": "sk-test", "model": "deepseek-v4-flash"},
        "claude": {"api_key": "sk-ant-test", "model": "claude-sonnet-4-6"},
        "openai": {"api_key": "sk-openai-test", "model": "gpt-4o"},
        "gemini": {"api_key": "AIza-test", "model": "gemini-2.5-flash"},
    },
}


def _ctx(**kwargs) -> ProjectContext:
    defaults = {"name": "test-proj", "stack": "Python", "description": ""}
    return ProjectContext(**{**defaults, **kwargs})


@contextmanager
def _active_project_policy(ctx: ProjectContext, config: dict = _CONFIG):
    token = set_policy(policy_for_project(ctx, config))
    try:
        yield
    finally:
        egress._POLICY.reset(token)


def test_local_router_is_deterministic():
    ctx = _ctx()

    with _active_project_policy(ctx):
        first = decide_with_local_router("documentar el módulo", ctx, _CONFIG)
        second = decide_with_local_router("documentar el módulo", ctx, _CONFIG)

    assert first == second
    assert first.routing_source == "local_router"
    assert first.used_fallback is True


def test_local_router_respects_keyword_signals():
    ctx = _ctx(keyword_hints=[
        {"match": "tests", "provider": "deepseek", "weight": 2},
        {"match": "tests unitarios", "provider": "openai", "weight": 5},
    ])

    with _active_project_policy(ctx):
        decision = decide_with_local_router("crear tests unitarios", ctx, _CONFIG)

    assert decision.provider == "openai"
    assert "keyword" in decision.reason


def test_local_router_falls_back_to_project_default():
    ctx = _ctx(default_provider="openai")

    with _active_project_policy(ctx):
        decision = decide_with_local_router("documentar el módulo", ctx, _CONFIG)

    assert decision.provider == "openai"
    assert "default del proyecto" in decision.reason


def test_local_router_falls_back_to_cheapest_permitted():
    ctx = _ctx(blocked_providers=["claude", "openai"])
    config = {
        **_CONFIG,
        "pricing": {
            "deepseek-v4-flash": {"input": 0.14, "output": 0.28},
        },
    }

    with _active_project_policy(ctx, config):
        decision = decide_with_local_router("documentar el módulo", ctx, config)

    assert decision.provider == "deepseek"
    assert "precio de input" in decision.reason


def test_local_router_reports_missing_prices_without_claiming_known_minimum():
    ctx = _ctx(default_provider="ghost")
    config = {
        **_CONFIG,
        "defaults": {"default_provider": "ghost"},
        "pricing": {
            "claude-v4": {"input": None},
            "gpt-4o": {"input": None},
            "deepseek-v4-flash": {"input": None},
            "gemini-2.5-flash": {"input": None},
        },
    }

    with _active_project_policy(ctx, config):
        decision = decide_with_local_router("documentar el módulo", ctx, config)

    assert decision.provider in PROVIDERS
    assert "sin precio de input disponible" in decision.reason
    assert "menor precio de input" not in decision.reason


def test_local_router_never_returns_blocked_provider():
    ctx = _ctx(
        blocked_providers=["claude"],
        keyword_hints=[
            {"match": "seguridad", "provider": "claude", "weight": 10},
            {"match": "seguridad", "provider": "openai", "weight": 1},
        ],
    )

    with _active_project_policy(ctx):
        decision = decide_with_local_router("revisar seguridad", ctx, _CONFIG)

    assert decision.provider == "openai"
    assert decision.provider not in ctx.blocked_providers


def test_no_provider_available_raises_egress_blocked():
    task = "TASK_TEXT_MUST_NOT_LEAK"
    ctx = _ctx(blocked_providers=list(PROVIDERS))

    with _active_project_policy(ctx):
        with pytest.raises(EgressBlocked) as exc_info:
            decide_with_local_router(task, ctx, _CONFIG)

    message = str(exc_info.value)
    assert ctx.name in message
    assert task not in message


def _restricted_router_config(fallback_provider: str = "gemini") -> dict:
    return {
        **_CONFIG,
        "router": {
            "provider": "deepseek",
            "fallback_provider": fallback_provider,
        },
        "providers": {
            "deepseek": {
                **_CONFIG["providers"]["deepseek"],
                "clearance": "public",
            },
            "claude": {
                **_CONFIG["providers"]["claude"],
                "clearance": "restricted",
            },
            "openai": {
                **_CONFIG["providers"]["openai"],
                "clearance": "internal",
            },
            "gemini": {
                **_CONFIG["providers"]["gemini"],
                "clearance": "public",
            },
        },
    }


def test_external_router_allowed_when_clearance_sufficient():
    config = _restricted_router_config()
    config["providers"]["deepseek"]["clearance"] = "restricted"
    ctx = _ctx(sensitivity="restricted")
    mock_result = MagicMock()
    mock_result.text = '{"provider": "claude", "model": null, "reason": "seguro"}'
    mock_provider = MagicMock()
    mock_provider.complete.return_value = mock_result

    with _active_project_policy(ctx, config), \
         patch("orchestrator.router._fetch_active_context", return_value=None), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]), \
         patch("orchestrator.router.build_provider", return_value=mock_provider):
        decision = decide_provider("revisar seguridad", ctx, config)

    mock_provider.complete.assert_called_once()
    assert decision.provider == "claude"
    assert decision.routing_source == "llm_router"


def test_external_router_blocked_uses_local_router_not_fixed_fallback():
    config = _restricted_router_config(fallback_provider="gemini")
    ctx = _ctx(sensitivity="restricted", default_provider="claude")

    with _active_project_policy(ctx, config), \
         patch("orchestrator.router._fetch_active_context", return_value=None), \
         patch("orchestrator.router.build_provider") as mock_build:
        decision = decide_provider("revisar seguridad", ctx, config)

    mock_build.assert_not_called()
    assert decision.provider == "claude"
    assert decision.routing_source == "local_router"


def test_external_router_blocked_does_not_build_full_context_prompt():
    config = _restricted_router_config()
    ctx = _ctx(sensitivity="restricted", default_provider="claude")

    with _active_project_policy(ctx, config), \
         patch("orchestrator.router._fetch_active_context", return_value=None), \
         patch("orchestrator.router._build_router_prompt") as mock_prompt, \
         patch("orchestrator.router.build_provider") as mock_build:
        decide_provider("TASK_TEXT_MUST_NOT_LEAK", ctx, config)

    mock_prompt.assert_not_called()
    mock_build.assert_not_called()


def test_external_router_blocked_does_not_fetch_similar_runs():
    config = _restricted_router_config()
    ctx = _ctx(sensitivity="restricted", default_provider="claude")

    with _active_project_policy(ctx, config), \
         patch("orchestrator.router._fetch_active_context", return_value=None), \
         patch("orchestrator.router._fetch_similar_runs") as mock_similar:
        decide_provider("TASK_TEXT_MUST_NOT_LEAK", ctx, config)

    mock_similar.assert_not_called()


def test_no_fixed_claude_fallback_when_router_blocked():
    config = _restricted_router_config(fallback_provider="claude")
    config["providers"]["openai"]["clearance"] = "restricted"
    ctx = _ctx(
        sensitivity="restricted",
        default_provider="openai",
        blocked_providers=["claude"],
    )

    with _active_project_policy(ctx, config), \
         patch("orchestrator.router._fetch_active_context", return_value=None):
        decision = decide_provider("tarea", ctx, config)

    assert decision.provider == "openai"
    assert decision.routing_source == "local_router"


def test_blocked_fallback_provider_does_not_abort_when_other_provider_permitted():
    config = _restricted_router_config(fallback_provider="gemini")
    ctx = _ctx(
        sensitivity="restricted",
        blocked_providers=["deepseek", "gemini"],
    )

    with _active_project_policy(ctx, config), \
         patch("orchestrator.router._fetch_active_context", return_value=None):
        decision = decide_provider("tarea", ctx, config)

    assert decision.provider == "claude"
    assert decision.routing_source == "local_router"


def test_local_router_preserves_agent_metadata():
    from orchestrator.agents import AgentDefinition

    config = _restricted_router_config()
    config["providers"]["openai"]["clearance"] = "restricted"
    ctx = _ctx(sensitivity="restricted", default_provider="openai")
    active_ctx = {
        "active_step": {
            "agent_preset": "reviewer",
            "provider": None,
        }
    }
    agent = AgentDefinition(
        name="reviewer",
        model="gpt-4o-mini",
        system_prompt_addition="Revisa cada hallazgo.",
    )

    with _active_project_policy(ctx, config), \
         patch("orchestrator.router._fetch_active_context", return_value=active_ctx), \
         patch("orchestrator.agents.get_agent", return_value=agent):
        decision = decide_provider("revisar", ctx, config)

    assert decision.provider == "openai"
    assert decision.model == "gpt-4o-mini"
    assert decision.system_prompt_addition == "Revisa cada hallazgo."


def test_external_router_egress_blocked_uses_local_router():
    ctx = _ctx(default_provider="openai")
    mock_provider = MagicMock()
    mock_provider.complete.side_effect = EgressBlocked("policy changed")

    with _active_project_policy(ctx), \
         patch("orchestrator.router._fetch_active_context", return_value=None), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]), \
         patch("orchestrator.router.build_provider", return_value=mock_provider):
        decision = decide_provider("tarea", ctx, _CONFIG)

    assert decision.provider == "openai"
    assert decision.routing_source == "local_router"


def _completed_run(project: str, routing_reason: str) -> dict:
    return {
        "project": project,
        "provider": "claude",
        "routing_reason": routing_reason,
        "task_preview": "generic task",
        "rating": None,
        "status": "done",
    }


def test_fetch_similar_runs_filters_by_project():
    backend = MagicMock()
    backend.query.return_value = [
        {"run_id": 1},
        {"run_id": 2},
        {"run_id": 3},
        {"run_id": 4},
    ]
    runs = {
        1: _completed_run("project-beta", "foreign result"),
        2: _completed_run("project-alpha", "first local result"),
        3: _completed_run("project-alpha", "second local result"),
        4: _completed_run("project-alpha", "local result beyond limit"),
    }

    with patch("orchestrator.similarity.get_backend", return_value=backend), \
         patch("orchestrator.db.get_run", side_effect=runs.get):
        results = _fetch_similar_runs("generic task", "project-alpha", n=2)

    assert [result["project"] for result in results] == ["project-alpha", "project-alpha"]
    assert [result["routing_reason"] for result in results] == [
        "first local result",
        "second local result",
    ]


def test_router_prompt_excludes_other_projects():
    backend = MagicMock()
    backend.query.return_value = [{"run_id": 1}, {"run_id": 2}]
    runs = {
        1: _completed_run("project-beta", "FOREIGN_ONLY_ROUTING_NOTE"),
        2: _completed_run("project-alpha", "LOCAL_ROUTING_NOTE"),
    }
    mock_result = MagicMock()
    mock_result.text = '{"provider": "claude", "model": null, "reason": "generic reason"}'
    mock_provider = MagicMock()
    mock_provider.complete.return_value = mock_result

    with patch("orchestrator.similarity.get_backend", return_value=backend), \
         patch("orchestrator.db.get_run", side_effect=runs.get), \
         patch("orchestrator.router.build_provider", return_value=mock_provider), \
         patch("orchestrator.router._fetch_active_context", return_value=None):
        decide_provider("generic task", _ctx(name="project-alpha"), _CONFIG)

    sent_prompt = mock_provider.complete.call_args.kwargs["prompt"]
    assert "LOCAL_ROUTING_NOTE" in sent_prompt
    assert "FOREIGN_ONLY_ROUTING_NOTE" not in sent_prompt


def test_fetch_similar_runs_overqueries_before_filtering():
    backend = MagicMock()
    backend.query.return_value = []

    with patch("orchestrator.similarity.get_backend", return_value=backend):
        assert _fetch_similar_runs("generic task", "project-alpha", n=3) == []

    backend.query.assert_called_once_with("generic task", n_results=20)


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
    assert decision.routing_source == "llm_router"
    assert "compleja" in decision.reason


def test_decide_provider_fallback_on_exception():
    mock_provider = MagicMock()
    mock_provider.complete.side_effect = Exception("SENSITIVE_ERROR_DETAIL")

    with patch("orchestrator.router.build_provider", return_value=mock_provider), \
         patch("orchestrator.router._fetch_active_context", return_value=None), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decision = decide_provider("cualquier tarea", _ctx(), _CONFIG)

    assert decision.provider == "claude"
    assert decision.used_fallback is True
    assert decision.routing_source == "fallback_router_error"
    assert "router externo falló: error de red o parsing" in decision.reason.lower()
    assert "SENSITIVE_ERROR_DETAIL" not in decision.reason


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
    assert decision.routing_source == "forced_step"


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
    assert decision.routing_source == "agent_preset"


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


# ---------------------------------------------------------------------------
# Validaciones post-LLM: API key y modelo contra catalogo
# ---------------------------------------------------------------------------

def test_decide_provider_falls_back_when_chosen_provider_has_no_api_key():
    """El router elige un provider, pero ese provider no tiene API key → fallback."""
    mock_result = MagicMock()
    mock_result.text = '{"provider": "openai", "model": null, "reason": "openai para esta tarea"}'
    mock_provider = MagicMock()
    mock_provider.complete.return_value = mock_result

    # openai no está en providers → sin API key
    config_no_openai_key = {
        "router": {"provider": "deepseek", "fallback_provider": "claude"},
        "defaults": {"default_provider": "claude"},
        "providers": {
            "deepseek": {"api_key": "sk-test", "model": "deepseek-v4-flash"},
            "claude": {"api_key": "sk-ant-test", "model": "claude-sonnet-4-6"},
        },
    }

    with patch("orchestrator.router.build_provider", return_value=mock_provider), \
         patch("orchestrator.router._fetch_active_context", return_value=None), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decision = decide_provider("task", _ctx(), config_no_openai_key)

    assert decision.used_fallback is True
    assert decision.provider == "claude"
    assert decision.routing_source == "fallback_no_api_key"


def test_force_provider_sets_forced_cli_routing_source():
    decision = force_provider("claude")

    assert decision.provider == "claude"
    assert decision.routing_source == "forced_cli"


def test_decide_provider_falls_back_when_chosen_provider_has_empty_api_key():
    """El provider está en config pero sin api_key → fallback."""
    mock_result = MagicMock()
    mock_result.text = '{"provider": "openai", "model": null, "reason": "openai"}'
    mock_provider = MagicMock()
    mock_provider.complete.return_value = mock_result

    config_empty_key = {
        "router": {"provider": "deepseek", "fallback_provider": "claude"},
        "defaults": {"default_provider": "claude"},
        "providers": {
            "deepseek": {"api_key": "sk-test", "model": "deepseek-v4-flash"},
            "openai": {"api_key": "", "model": "gpt-4o"},
            "claude": {"api_key": "sk-ant-test", "model": "claude-sonnet-4-6"},
        },
    }

    with patch("orchestrator.router.build_provider", return_value=mock_provider), \
         patch("orchestrator.router._fetch_active_context", return_value=None), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decision = decide_provider("task", _ctx(), config_empty_key)

    assert decision.used_fallback is True
    assert decision.provider == "claude"


_CONFIG_FULL = {
    "router": {"provider": "deepseek", "fallback_provider": "claude"},
    "defaults": {"default_provider": "claude"},
    "providers": {
        "deepseek": {"api_key": "sk-test", "model": "deepseek-v4-flash"},
        "openai": {"api_key": "sk-openai-test", "model": "gpt-4o"},
        "claude": {"api_key": "sk-ant-test", "model": "claude-sonnet-4-6"},
        "gemini": {"api_key": "AIza-test", "model": "gemini-2.5-flash"},
    },
}


def test_decide_provider_strips_deprecated_model():
    """Si el router sugiere un modelo deprecated, se descarta y model queda None."""
    mock_result = MagicMock()
    # deepseek-chat está marcado como deprecated en el catálogo estático
    mock_result.text = '{"provider": "deepseek", "model": "deepseek-chat", "reason": "economico"}'
    mock_provider = MagicMock()
    mock_provider.complete.return_value = mock_result

    with patch("orchestrator.router.build_provider", return_value=mock_provider), \
         patch("orchestrator.router._fetch_active_context", return_value=None), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decision = decide_provider("tarea boilerplate", _ctx(), _CONFIG_FULL)

    assert decision.provider == "deepseek"
    assert decision.model is None
    assert decision.used_fallback is False


def test_decide_provider_strips_model_not_in_catalog():
    """Si el router sugiere un modelo inexistente en el catálogo, se descarta."""
    mock_result = MagicMock()
    mock_result.text = '{"provider": "openai", "model": "gpt-999-fantasma", "reason": "test"}'
    mock_provider = MagicMock()
    mock_provider.complete.return_value = mock_result

    with patch("orchestrator.router.build_provider", return_value=mock_provider), \
         patch("orchestrator.router._fetch_active_context", return_value=None), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decision = decide_provider("tarea cualquiera", _ctx(), _CONFIG_FULL)

    assert decision.provider == "openai"
    assert decision.model is None
    assert decision.used_fallback is False


def test_decide_provider_keeps_valid_model_from_catalog():
    """Si el router sugiere un modelo válido y activo, se conserva."""
    mock_result = MagicMock()
    mock_result.text = '{"provider": "openai", "model": "gpt-4o-mini", "reason": "tarea simple"}'
    mock_provider = MagicMock()
    mock_provider.complete.return_value = mock_result

    with patch("orchestrator.router.build_provider", return_value=mock_provider), \
         patch("orchestrator.router._fetch_active_context", return_value=None), \
         patch("orchestrator.router._fetch_similar_runs", return_value=[]):
        decision = decide_provider("tarea simple", _ctx(), _CONFIG_FULL)

    assert decision.provider == "openai"
    assert decision.model == "gpt-4o-mini"
    assert decision.used_fallback is False
