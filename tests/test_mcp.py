"""Tests de los tools MCP relacionados con agent_preset y list_agents.

Llama las funciones _tool_* directamente (no hace falta simular transporte
JSON-RPC) — no existia ningun test de mcp.py antes de esta fase.
"""
import tempfile
import threading
from pathlib import Path

import pytest


@pytest.fixture()
def isolated_db(monkeypatch):
    import orchestrator.paths as paths_mod
    import orchestrator.db as db_mod

    tmp_path = Path(tempfile.mkdtemp())
    monkeypatch.setattr(paths_mod, "HOME_DIR", tmp_path)
    monkeypatch.setattr(paths_mod, "DB_PATH", tmp_path / "runs.db")
    monkeypatch.setattr(db_mod, "_local", threading.local())
    db_mod.init_db()
    yield db_mod


@pytest.fixture()
def isolated_agents(monkeypatch, tmp_path):
    import orchestrator.agents as agents_mod
    monkeypatch.setattr(agents_mod, "AGENTS_PATH", tmp_path / "agents.yaml")
    return agents_mod


def test_add_step_persists_agent_preset(isolated_db):
    import orchestrator.mcp as mcp

    ctx_id = isolated_db.insert_context("proj", "Titulo")
    result = mcp._tool_add_step({"context_id": ctx_id, "title": "Revisar", "agent_preset": "reviewer"})

    assert result["agent_preset"] == "reviewer"
    row = isolated_db._conn().execute("SELECT agent_preset FROM steps WHERE id=?", (result["step_id"],)).fetchone()
    assert row["agent_preset"] == "reviewer"


def test_update_step_sets_agent_preset(isolated_db):
    import orchestrator.mcp as mcp

    ctx_id = isolated_db.insert_context("proj", "Titulo")
    step_id = isolated_db.insert_step(ctx_id, 1, "Paso")

    result = mcp._tool_update_step({"step_id": step_id, "agent_preset": "fast"})

    assert result["updated"] == ["agent_preset"]
    row = isolated_db._conn().execute("SELECT title, provider, agent_preset FROM steps WHERE id=?", (step_id,)).fetchone()
    assert row["agent_preset"] == "fast"
    assert row["title"] == "Paso"
    assert row["provider"] == ""


def test_update_step_clears_agent_preset_with_empty_string(isolated_db):
    import orchestrator.mcp as mcp

    ctx_id = isolated_db.insert_context("proj", "Titulo")
    step_id = isolated_db.insert_step(ctx_id, 1, "Paso", agent_preset="reviewer")

    mcp._tool_update_step({"step_id": step_id, "agent_preset": ""})

    row = isolated_db._conn().execute("SELECT agent_preset FROM steps WHERE id=?", (step_id,)).fetchone()
    assert row["agent_preset"] == ""


def test_create_context_propagates_agent_preset_per_step(isolated_db):
    import orchestrator.mcp as mcp

    result = mcp._tool_create_context({
        "project": "proj",
        "title": "Plan",
        "steps": [{"title": "Paso 1", "agent_preset": "reviewer"}, {"title": "Paso 2"}],
    })

    assert result["steps"][0]["agent_preset"] == "reviewer"
    assert result["steps"][1]["agent_preset"] == ""


def test_list_agents_tool_reflects_registry(isolated_agents):
    import orchestrator.mcp as mcp
    from orchestrator.agents import AgentDefinition

    isolated_agents.upsert_agent(AgentDefinition(name="reviewer", provider="claude"))

    result = mcp._tool_list_agents({})

    assert len(result["agents"]) == 1
    assert result["agents"][0]["name"] == "reviewer"


def test_list_agents_tool_empty_registry(isolated_agents):
    import orchestrator.mcp as mcp

    result = mcp._tool_list_agents({})

    assert result["agents"] == []
