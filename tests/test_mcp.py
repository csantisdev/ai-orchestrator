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


@pytest.mark.parametrize(
    ("tool_name", "args", "table"),
    [
        (
            "_tool_confirm_alignment",
            {"agent": "agent", "checkpoint": "checkpoint"},
            "alignments",
        ),
        (
            "_tool_record_tool_call",
            {"tool_name": "tool"},
            "tool_calls",
        ),
    ],
)
def test_audit_tools_reject_steps_from_another_context(isolated_db, tool_name, args, table):
    import orchestrator.mcp as mcp

    authorized_context_id = isolated_db.insert_context("authorized", "Authorized")
    other_context_id = isolated_db.insert_context("other", "Other")
    other_step_id = isolated_db.insert_step(other_context_id, 1, "Other step")

    with pytest.raises(ValueError, match=f"step {other_step_id} does not belong to context {authorized_context_id}"):
        getattr(mcp, tool_name)({
            "context_id": authorized_context_id,
            "step_id": other_step_id,
            **args,
        })

    assert isolated_db._conn().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("tool_name", "args", "table"),
    [
        (
            "_tool_confirm_alignment",
            {"agent": "agent", "checkpoint": "checkpoint"},
            "alignments",
        ),
        (
            "_tool_record_tool_call",
            {"tool_name": "tool"},
            "tool_calls",
        ),
    ],
)
def test_audit_tools_persist_steps_from_their_context(isolated_db, tool_name, args, table):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("project", "Context")
    step_id = isolated_db.insert_step(context_id, 1, "Step")

    getattr(mcp, tool_name)({
        "context_id": context_id,
        "step_id": step_id,
        **args,
    })

    row = isolated_db._conn().execute(
        f"SELECT step_id, context_id FROM {table}"
    ).fetchone()
    assert dict(row) == {"step_id": step_id, "context_id": context_id}


@pytest.fixture()
def governed_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_MCP_PROFILE", "readonly")
    monkeypatch.setenv("ORCHESTRATOR_MCP_PROJECTS", "allowed")
    monkeypatch.setenv("ORCHESTRATOR_MCP_CLIENT_SURFACE", "codex_cli")
    monkeypatch.setenv("ORCHESTRATOR_MCP_TRANSPORT", "stdio")


def test_readonly_discovery_exposes_only_read_tools(governed_env):
    import orchestrator.mcp as mcp
    from orchestrator.mcp_governance import execution_identity, visible_tools

    assert [tool["name"] for tool in visible_tools(mcp.TOOLS, execution_identity())] == [
        "get_context", "list_steps", "list_agents",
    ]
    tool = visible_tools(mcp.TOOLS, execution_identity())[0]
    assert tool["annotations"]["readOnlyHint"] is True
    assert tool["annotations"]["destructiveHint"] is False


def test_readonly_direct_mutation_is_denied_and_audited(isolated_db, governed_env):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("allowed", "Title")
    result, is_error = mcp._governed_tool_call(
        "create_context", {"project": "allowed", "title": "Unexpected"}, "request-1"
    )

    assert is_error is True
    assert result["reason_code"] == "capability_denied"
    assert isolated_db._conn().execute("SELECT COUNT(*) FROM contexts").fetchone()[0] == 1
    audit = isolated_db._conn().execute(
        "SELECT status, reason_code, tool_name, project, input_hash FROM mcp_invocations"
    ).fetchone()
    assert dict(audit) == {
        "status": "denied",
        "reason_code": "capability_denied",
        "tool_name": "create_context",
        "project": "allowed",
        "input_hash": audit["input_hash"],
    }
    assert len(audit["input_hash"]) == 64


def test_project_scope_is_enforced_before_read_handler(isolated_db, governed_env):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("other", "Private")
    result, is_error = mcp._governed_tool_call(
        "list_steps", {"context_id": context_id}, "request-2"
    )

    assert is_error is True
    assert result["reason_code"] == "project_out_of_scope"
    row = isolated_db._conn().execute(
        "SELECT status, reason_code, project FROM mcp_invocations"
    ).fetchone()
    assert dict(row) == {
        "status": "denied",
        "reason_code": "project_out_of_scope",
        "project": "other",
    }


def test_valid_authorized_call_is_audited_without_storing_input(isolated_db, governed_env):
    import orchestrator.mcp as mcp

    isolated_db.insert_context("allowed", "Visible")
    result, is_error = mcp._governed_tool_call(
        "get_context", {"project": "allowed"}, "request-3"
    )

    assert is_error is False
    assert result["project"] == "allowed"
    row = isolated_db._conn().execute(
        "SELECT status, project, client_surface, transport, capability_profile, input_hash, output_hash "
        "FROM mcp_invocations"
    ).fetchone()
    assert dict(row) == {
        "status": "success",
        "project": "allowed",
        "client_surface": "codex_cli",
        "transport": "stdio",
        "capability_profile": "readonly",
        "input_hash": row["input_hash"],
        "output_hash": row["output_hash"],
    }
    assert len(row["input_hash"]) == len(row["output_hash"]) == 64
    columns = {column["name"] for column in isolated_db._conn().execute("PRAGMA table_info(mcp_invocations)")}
    assert "redacted_input_json" not in columns


def test_invalid_arguments_are_rejected_before_handler_and_audited(isolated_db, governed_env):
    import orchestrator.mcp as mcp

    result, is_error = mcp._governed_tool_call(
        "list_steps", {"context_id": "not-an-integer"}, "request-4"
    )

    assert is_error is True
    assert result["reason_code"] == "invalid_arguments"
    row = isolated_db._conn().execute(
        "SELECT status, reason_code FROM mcp_invocations"
    ).fetchone()
    assert dict(row) == {"status": "error", "reason_code": "invalid_arguments"}
