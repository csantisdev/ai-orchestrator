"""Reproduccion en vivo del PoC de RFC-006 SS4.2 contra el codigo real de
feat/egress-gate@4deed8a. No pega ningun payload real, solo tareas sinteticas.
"""
from unittest.mock import patch

from orchestrator import egress
from orchestrator.context import ProjectContext
from orchestrator.egress import EgressBlocked
from orchestrator.router import decide_provider

CONFIG = {
    "router": {"provider": "deepseek", "fallback_provider": "claude"},
    "defaults": {"default_provider": "claude"},
    "providers": {
        "deepseek": {"api_key": "sk-test", "model": "deepseek-v4-flash", "clearance": "public"},
        "gemini":   {"api_key": "AIza-test", "model": "gemini-2.5-flash", "clearance": "public"},
        "openai":   {"api_key": "sk-openai-test", "model": "gpt-4o", "clearance": "internal"},
        "claude":   {"api_key": "sk-ant-test", "model": "claude-sonnet-4-6", "clearance": "restricted"},
    },
}


def run_scenario(name, ctx, expect):
    with patch("orchestrator.router._fetch_active_context", return_value=None), \
         patch("orchestrator.providers.deepseek.httpx.post") as ds_post, \
         patch("orchestrator.providers.deepseek.httpx.stream") as ds_stream:
        token = egress.set_policy(egress.policy_for_project(ctx, CONFIG))
        try:
            try:
                decision = decide_provider("tarea sintetica de PoC", ctx, CONFIG)
                result = decision.provider
            except EgressBlocked:
                result = "BLOQUEADO"
        finally:
            egress._POLICY.reset(token)

    ds_post.assert_not_called()
    ds_stream.assert_not_called()
    status = "OK" if result == expect else "FAIL"
    print(f"[{status}] {name}: sensitivity={ctx.sensitivity!r} -> {result} (esperado: {expect}) | cero bytes a deepseek: confirmado")
    assert result == expect, f"{name}: esperaba {expect}, obtuve {result}"


run_scenario(
    "ai-orchestrator",
    ProjectContext(name="ai-orchestrator", sensitivity="internal", default_provider="openai"),
    "openai",
)
run_scenario(
    "restricted-project.example",
    ProjectContext(name="restricted-project.example", sensitivity="restricted"),
    "claude",
)
run_scenario(
    "secreto",
    ProjectContext(name="secreto", sensitivity="secret"),
    "BLOQUEADO",
)

print("\nPoC RFC-006 SS4.2 reproducido OK contra feat/egress-gate@4deed8a -- 3/3 escenarios, cero bytes a DeepSeek en los 3.")
