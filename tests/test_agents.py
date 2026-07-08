"""Tests del registro de agentes (presets reutilizables) — Fase 1 modulo de agentes."""
import pytest

import orchestrator.agents as agents_mod
from orchestrator.agents import AgentDefinition


def test_list_agents_empty_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(agents_mod, "AGENTS_PATH", tmp_path / "agents.yaml")
    assert agents_mod.list_agents() == []


def test_upsert_and_get_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(agents_mod, "AGENTS_PATH", tmp_path / "agents.yaml")
    agents_mod.upsert_agent(AgentDefinition(
        name="security-reviewer", provider="claude", system_prompt_addition="Sos estricto en seguridad.",
    ))
    got = agents_mod.get_agent("security-reviewer")
    assert got is not None
    assert got.provider == "claude"
    assert got.system_prompt_addition == "Sos estricto en seguridad."


def test_upsert_agent_invalid_provider_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(agents_mod, "AGENTS_PATH", tmp_path / "agents.yaml")
    with pytest.raises(ValueError):
        agents_mod.upsert_agent(AgentDefinition(name="x", provider="not-a-provider"))


def test_upsert_agent_overwrites_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(agents_mod, "AGENTS_PATH", tmp_path / "agents.yaml")
    agents_mod.upsert_agent(AgentDefinition(name="a", provider="claude"))
    agents_mod.upsert_agent(AgentDefinition(name="a", provider="openai"))
    assert agents_mod.get_agent("a").provider == "openai"
    assert len(agents_mod.list_agents()) == 1


def test_delete_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(agents_mod, "AGENTS_PATH", tmp_path / "agents.yaml")
    agents_mod.upsert_agent(AgentDefinition(name="a"))
    assert agents_mod.delete_agent("a") is True
    assert agents_mod.delete_agent("a") is False
    assert agents_mod.get_agent("a") is None


def test_get_agent_not_found_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(agents_mod, "AGENTS_PATH", tmp_path / "agents.yaml")
    assert agents_mod.get_agent("nope") is None


def test_agent_without_provider_or_model_is_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(agents_mod, "AGENTS_PATH", tmp_path / "agents.yaml")
    agents_mod.upsert_agent(AgentDefinition(name="only-prompt", system_prompt_addition="Se breve."))
    got = agents_mod.get_agent("only-prompt")
    assert got.provider is None
    assert got.model is None
    assert got.system_prompt_addition == "Se breve."


def test_list_agents_sorted_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(agents_mod, "AGENTS_PATH", tmp_path / "agents.yaml")
    agents_mod.upsert_agent(AgentDefinition(name="zeta"))
    agents_mod.upsert_agent(AgentDefinition(name="alpha"))
    names = [a.name for a in agents_mod.list_agents()]
    assert names == ["alpha", "zeta"]


def test_corrupt_yaml_does_not_crash_list_agents(tmp_path, monkeypatch):
    path = tmp_path / "agents.yaml"
    path.write_text("agents:\n  a: [broken yaml: :\n", encoding="utf-8")
    monkeypatch.setattr(agents_mod, "AGENTS_PATH", path)

    assert agents_mod.list_agents() == []
    assert agents_mod.get_agent("a") is None


def test_yaml_with_unexpected_top_level_shape_does_not_crash(tmp_path, monkeypatch):
    path = tmp_path / "agents.yaml"
    path.write_text("- esto\n- no es un dict\n", encoding="utf-8")
    monkeypatch.setattr(agents_mod, "AGENTS_PATH", path)

    assert agents_mod.list_agents() == []
    assert agents_mod.get_agent("a") is None


def test_unknown_key_in_one_entry_does_not_break_listing_all_agents(tmp_path, monkeypatch):
    path = tmp_path / "agents.yaml"
    path.write_text(
        "agents:\n"
        "  good:\n"
        "    provider: claude\n"
        "  bad:\n"
        "    provider: openai\n"
        "    campo_inventado: valor_typo\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(agents_mod, "AGENTS_PATH", path)

    names = {a.name for a in agents_mod.list_agents()}
    assert names == {"good", "bad"}
    assert agents_mod.get_agent("bad").provider == "openai"
