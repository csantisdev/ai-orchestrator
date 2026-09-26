"""Tests de los tools MCP relacionados con agent_preset y list_agents.

Llama las funciones _tool_* directamente (no hace falta simular transporte
JSON-RPC) — no existia ningun test de mcp.py antes de esta fase.
"""
import hashlib
import hmac
import json
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


@pytest.fixture()
def workflow_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_MCP_PROFILE", "workflow_operator")
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


@pytest.mark.parametrize("tool_name", ["start_step", "reset_step"])
def test_readonly_transition_tools_are_hidden_and_denied(isolated_db, governed_env, tool_name):
    import orchestrator.mcp as mcp
    from orchestrator.mcp_governance import execution_identity, visible_tools

    context_id = isolated_db.insert_context("allowed", "Title")
    step_id = isolated_db.insert_step(context_id, 1, "Step")
    assert tool_name not in {tool["name"] for tool in visible_tools(mcp.TOOLS, execution_identity())}

    result, is_error = mcp._governed_tool_call(tool_name, {"step_id": step_id}, "readonly-transition")

    assert is_error is True
    assert result["reason_code"] == "capability_denied"


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


def test_mutation_request_id_replays_payload_free_receipt_without_duplicate(isolated_db, workflow_env):
    import orchestrator.mcp as mcp

    args = {
        "project": "allowed",
        "title": "Idempotent context",
        "request_id": "create-context-001",
    }
    first, first_error = mcp._governed_tool_call("create_context", args, "rpc-1")
    replay, replay_error = mcp._governed_tool_call("create_context", args, "rpc-2")

    assert (first_error, replay_error) == (False, False)
    assert isolated_db._conn().execute("SELECT COUNT(*) FROM contexts").fetchone()[0] == 1
    row = isolated_db._conn().execute(
        "SELECT request_id, status, request_source, replay_safe, output_hash FROM mcp_invocations"
    ).fetchone()
    assert row["status"] == "success"
    assert row["request_source"] == "client"
    assert row["replay_safe"] == 1
    assert replay == {
        "request_id": row["request_id"],
        "status": "success",
        "replayed": True,
    }
    assert row["output_hash"] != hashlib.sha256(
        json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    from orchestrator.paths import HOME_DIR
    assert row["output_hash"] == hmac.new(
        (HOME_DIR / "mcp-commitment.key").read_bytes(),
        json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(),
        hashlib.sha256,
    ).hexdigest()
    assert "result_json" not in {
        column["name"] for column in isolated_db._conn().execute("PRAGMA table_info(mcp_invocations)")
    }


def test_mcp_invocations_never_retains_result_payload_secret(isolated_db, workflow_env):
    import orchestrator.mcp as mcp

    secret = "MCP_OUTPUT_SECRET_do_not_retain"
    args = {
        "project": "allowed",
        "title": secret,
        "request_id": "payload-free-idempotency",
    }
    first, first_error = mcp._governed_tool_call("create_context", args, "rpc-1")
    replay, replay_error = mcp._governed_tool_call("create_context", args, "rpc-2")

    assert (first_error, replay_error) == (False, False)
    assert first["title"] == secret
    assert replay["replayed"] is True
    assert isolated_db._conn().execute("SELECT COUNT(*) FROM contexts").fetchone()[0] == 1
    invocation = isolated_db._conn().execute(
        "SELECT * FROM mcp_invocations"
    ).fetchone()
    assert secret not in "\n".join(
        str(value) for value in dict(invocation).values() if value is not None
    )
    assert invocation["output_hash"] != hashlib.sha256(
        json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert "output_hash" not in replay


def test_reused_jsonrpc_id_without_request_id_executes_distinct_mutations(isolated_db, workflow_env):
    import orchestrator.mcp as mcp

    first, first_error = mcp._governed_tool_call(
        "create_context", {"project": "allowed", "title": "First"}, "reused-rpc-id"
    )
    second, second_error = mcp._governed_tool_call(
        "create_context", {"project": "allowed", "title": "Second"}, "reused-rpc-id"
    )

    assert (first_error, second_error) == (False, False)
    assert first["context_id"] != second["context_id"]
    rows = isolated_db._conn().execute(
        "SELECT correlation_id, request_source, replay_safe FROM mcp_invocations ORDER BY id"
    ).fetchall()
    assert [dict(row) for row in rows] == [
        {"correlation_id": "reused-rpc-id", "request_source": "generated", "replay_safe": 0},
        {"correlation_id": "reused-rpc-id", "request_source": "generated", "replay_safe": 0},
    ]


def test_sqlite_mutation_and_terminal_idempotency_record_rollback_together(
    isolated_db, workflow_env, monkeypatch
):
    import orchestrator.mcp as mcp

    original_dispatch = mcp._dispatch

    def fail_after_mutation(name, args):
        original_dispatch(name, args)
        raise RuntimeError("simulated process failure before terminal result")

    monkeypatch.setattr(mcp, "_dispatch", fail_after_mutation)
    result, is_error = mcp._governed_tool_call(
        "create_context",
        {"project": "allowed", "title": "Must roll back", "request_id": "atomic-rollback"},
        "rpc-atomic",
    )

    assert is_error is True
    assert result["reason_code"] == "execution_error"
    assert isolated_db._conn().execute("SELECT COUNT(*) FROM contexts").fetchone()[0] == 0
    invocation = isolated_db._conn().execute(
        "SELECT status, output_hash FROM mcp_invocations"
    ).fetchone()
    assert invocation["status"] == "error"
    assert invocation["output_hash"] != hashlib.sha256(
        json.dumps(
            {"error": "simulated process failure before terminal result", "reason_code": "execution_error"},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode()
    ).hexdigest()


def test_request_id_cannot_be_reused_for_another_mutation(isolated_db, workflow_env):
    import orchestrator.mcp as mcp

    mcp._governed_tool_call(
        "create_context",
        {"project": "allowed", "title": "First", "request_id": "one-logical-request"},
        "rpc-1",
    )
    result, is_error = mcp._governed_tool_call(
        "create_context",
        {"project": "allowed", "title": "Second", "request_id": "one-logical-request"},
        "rpc-2",
    )

    assert is_error is True
    assert result["reason_code"] == "request_id_reused"
    assert isolated_db._conn().execute("SELECT COUNT(*) FROM contexts").fetchone()[0] == 1


def test_transition_retry_and_competitor_do_not_activate_two_steps(isolated_db, workflow_env):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("allowed", "Workflow")
    first_step = isolated_db.insert_step(context_id, 1, "First")
    second_step = isolated_db.insert_step(context_id, 2, "Second")
    isolated_db.activate_first_step(context_id)

    completed, completed_error = mcp._governed_tool_call(
        "advance_step", {"step_id": first_step, "request_id": "advance-1"}, "rpc-1"
    )
    replay, replay_error = mcp._governed_tool_call(
        "advance_step", {"step_id": first_step, "request_id": "advance-1"}, "rpc-2"
    )
    competitor, competitor_error = mcp._governed_tool_call(
        "advance_step", {"step_id": first_step, "request_id": "advance-2"}, "rpc-3"
    )

    assert (completed_error, replay_error, competitor_error) == (False, False, True)
    assert replay["replayed"] is True
    assert replay["status"] == "success"
    assert "output_hash" not in replay
    assert competitor["reason_code"] == "execution_error"
    statuses = isolated_db._conn().execute(
        "SELECT id, status FROM steps WHERE context_id=? ORDER BY order_idx", (context_id,)
    ).fetchall()
    assert [dict(row) for row in statuses] == [
        {"id": first_step, "status": "completed"},
        {"id": second_step, "status": "in_progress"},
    ]


def test_mutation_ownership_is_checked_before_transition(isolated_db, workflow_env):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("other", "Private")
    step_id = isolated_db.insert_step(context_id, 1, "Private step")
    isolated_db.activate_first_step(context_id)

    result, is_error = mcp._governed_tool_call(
        "advance_step", {"step_id": step_id, "request_id": "private-advance"}, "rpc-1"
    )

    assert is_error is True
    assert result["reason_code"] == "project_out_of_scope"
    assert isolated_db._conn().execute(
        "SELECT status FROM steps WHERE id=?", (step_id,)
    ).fetchone()["status"] == "in_progress"


def test_start_and_reset_steps_are_governed_and_idempotent(isolated_db, workflow_env):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("allowed", "Workflow")
    first_step = isolated_db.insert_step(context_id, 1, "First")
    second_step = isolated_db.insert_step(context_id, 2, "Second")

    started, started_error = mcp._governed_tool_call(
        "start_step", {"step_id": first_step, "request_id": "start-1"}, "rpc-start-1"
    )
    replay, replay_error = mcp._governed_tool_call(
        "start_step", {"step_id": first_step, "request_id": "start-1"}, "rpc-start-2"
    )
    conflict, conflict_error = mcp._governed_tool_call(
        "start_step", {"step_id": second_step, "request_id": "start-2"}, "rpc-start-3"
    )
    reset, reset_error = mcp._governed_tool_call(
        "reset_step", {"step_id": first_step, "notes": "paused", "request_id": "reset-1"}, "rpc-reset-1"
    )
    invalid_reset, invalid_reset_error = mcp._governed_tool_call(
        "reset_step", {"step_id": first_step, "request_id": "reset-2"}, "rpc-reset-2"
    )

    assert (started_error, replay_error, conflict_error, reset_error, invalid_reset_error) == (False, False, True, False, True)
    assert started["started_step_id"] == first_step
    assert replay["replayed"] is True
    assert conflict["reason_code"] == "context_has_in_progress"
    assert reset["reset_step_id"] == first_step
    assert invalid_reset["reason_code"] == "step_not_in_progress"
    row = isolated_db._conn().execute("SELECT status, started_at, notes FROM steps WHERE id=?", (first_step,)).fetchone()
    assert dict(row) == {"status": "pending", "started_at": None, "notes": "paused"}


def test_start_step_rejects_programmed_context_via_mcp(isolated_db, workflow_env):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("allowed", "Later", status="programado")
    step_id = isolated_db.insert_step(context_id, 1, "Step")
    result, is_error = mcp._governed_tool_call(
        "start_step", {"step_id": step_id, "request_id": "programmed-start"}, "rpc-programmed"
    )

    assert is_error is True
    assert result["reason_code"] == "context_not_active"
    assert isolated_db._conn().execute("SELECT status FROM steps WHERE id=?", (step_id,)).fetchone()[0] == "pending"


def test_start_step_checks_project_ownership_and_add_start_advance_flow(isolated_db, workflow_env):
    import orchestrator.mcp as mcp

    private_context = isolated_db.insert_context("other", "Private")
    private_step = isolated_db.insert_step(private_context, 1, "Private step")
    denied, denied_error = mcp._governed_tool_call(
        "start_step", {"step_id": private_step, "request_id": "private-start"}, "rpc-private"
    )
    context_id = isolated_db.insert_context("allowed", "Workflow")
    added, added_error = mcp._governed_tool_call(
        "add_step", {"context_id": context_id, "title": "Added", "request_id": "add-1"}, "rpc-add"
    )
    started, started_error = mcp._governed_tool_call(
        "start_step", {"step_id": added["step_id"], "request_id": "start-added"}, "rpc-start"
    )
    completed, completed_error = mcp._governed_tool_call(
        "advance_step", {"step_id": added["step_id"], "request_id": "advance-added"}, "rpc-advance"
    )

    assert (denied_error, added_error, started_error, completed_error) == (True, False, False, False)
    assert denied["reason_code"] == "project_out_of_scope"
    assert started["started_step_id"] == added["step_id"]
    assert completed["completed_step_id"] == added["step_id"]


def test_step_notes_are_preserved_or_appended_by_transitions_and_reset(isolated_db):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("mi-proyecto", "Flujo")
    first_step = isolated_db.insert_step(context_id, 1, "Primero")
    second_step = isolated_db.insert_step(context_id, 2, "Segundo")
    isolated_db._conn().execute("UPDATE steps SET notes='previas' WHERE id=?", (first_step,))
    isolated_db._conn().execute("UPDATE steps SET notes='anteriores' WHERE id=?", (second_step,))
    isolated_db.activate_first_step(context_id)

    mcp._tool_advance_step({"step_id": first_step, "notes": "finales"})
    assert isolated_db._conn().execute("SELECT notes FROM steps WHERE id=?", (first_step,)).fetchone()[0] == "previas\nfinales"
    mcp._tool_skip_step({"step_id": second_step, "reason": "reemplazado"})
    assert isolated_db._conn().execute("SELECT notes FROM steps WHERE id=?", (second_step,)).fetchone()[0] == "anteriores\nreemplazado"

    third_step = isolated_db.insert_step(context_id, 3, "Tercero")
    isolated_db._conn().execute("UPDATE steps SET status='in_progress', notes='guardadas' WHERE id=?", (third_step,))
    reset = mcp._tool_reset_step({"step_id": third_step, "notes": "pausado"})
    assert reset["notes"] == "guardadas\npausado"


@pytest.mark.parametrize(("tool_name", "argument"), [("_tool_advance_step", "notes"), ("_tool_skip_step", "reason")])
def test_omitted_or_empty_transition_notes_do_not_clear_existing(isolated_db, tool_name, argument):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("mi-proyecto", "Flujo")
    step_id = isolated_db.insert_step(context_id, 1, "Paso")
    isolated_db._conn().execute("UPDATE steps SET status='in_progress', notes='previas' WHERE id=?", (step_id,))

    getattr(mcp, tool_name)({"step_id": step_id})
    assert isolated_db._conn().execute("SELECT notes FROM steps WHERE id=?", (step_id,)).fetchone()[0] == "previas"

    next_step = isolated_db.insert_step(context_id, 2, "Otro")
    isolated_db._conn().execute("UPDATE steps SET status='in_progress', notes='previas' WHERE id=?", (next_step,))
    getattr(mcp, tool_name)({"step_id": next_step, argument: ""})
    assert isolated_db._conn().execute("SELECT notes FROM steps WHERE id=?", (next_step,)).fetchone()[0] == "previas"


def test_update_step_replaces_or_appends_notes(isolated_db):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("mi-proyecto", "Flujo")
    step_id = isolated_db.insert_step(context_id, 1, "Paso")
    isolated_db._conn().execute("UPDATE steps SET notes='previas' WHERE id=?", (step_id,))

    assert mcp._tool_update_step({"step_id": step_id, "notes": "nuevas"})["updated"] == ["notes"]
    assert mcp._tool_update_step({"step_id": step_id, "notes_append": "agregadas"})["updated"] == ["notes_append"]
    assert isolated_db._conn().execute("SELECT notes FROM steps WHERE id=?", (step_id,)).fetchone()[0] == "nuevas\nagregadas"
    with pytest.raises(ValueError, match="mutuamente excluyentes"):
        mcp._tool_update_step({"step_id": step_id, "notes": "x", "notes_append": "y"})


def test_update_step_direct_append_rejects_missing_step(isolated_db):
    import orchestrator.mcp as mcp

    with pytest.raises(ValueError, match="step 999 not found"):
        mcp._tool_update_step({"step_id": 999, "notes_append": "nota"})


def test_advance_replay_does_not_duplicate_appended_notes(isolated_db, workflow_env):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("allowed", "Flujo")
    step_id = isolated_db.insert_step(context_id, 1, "Paso")
    isolated_db._conn().execute("UPDATE steps SET status='in_progress', notes='previas' WHERE id=?", (step_id,))
    isolated_db._conn().commit()
    args = {"step_id": step_id, "notes": "finales", "request_id": "append-once"}
    mcp._governed_tool_call("advance_step", args, "rpc-1")
    mcp._governed_tool_call("advance_step", args, "rpc-2")
    assert isolated_db._conn().execute("SELECT notes FROM steps WHERE id=?", (step_id,)).fetchone()[0] == "previas\nfinales"


@pytest.mark.parametrize("tool_name", ["_tool_advance_step", "_tool_skip_step"])
def test_transition_can_leave_next_step_pending(isolated_db, tool_name):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("mi-proyecto", "Flujo")
    first_step = isolated_db.insert_step(context_id, 1, "Primero")
    second_step = isolated_db.insert_step(context_id, 2, "Segundo")
    isolated_db.activate_first_step(context_id)
    result = getattr(mcp, tool_name)({"step_id": first_step, "activate_next": False})

    assert result["next_step"] is None
    assert result["context_done"] is False
    assert isolated_db._conn().execute("SELECT status FROM steps WHERE id=?", (second_step,)).fetchone()[0] == "pending"
    assert isolated_db._conn().execute("SELECT status FROM contexts WHERE id=?", (context_id,)).fetchone()[0] == "active"


@pytest.mark.parametrize("tool_name", ["_tool_advance_step", "_tool_skip_step"])
def test_transition_without_activation_completes_last_open_step(isolated_db, tool_name):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("mi-proyecto", "Flujo")
    step_id = isolated_db.insert_step(context_id, 1, "\u00danico")
    isolated_db.activate_first_step(context_id)

    result = getattr(mcp, tool_name)({"step_id": step_id, "activate_next": False})

    assert result["next_step"] is None
    assert result["context_done"] is True
    assert isolated_db._conn().execute(
        "SELECT status FROM contexts WHERE id=?", (context_id,)
    ).fetchone()[0] == "completed"


@pytest.mark.parametrize("tool_name", ["_tool_advance_step", "_tool_skip_step"])
@pytest.mark.parametrize("options", [{}, {"activate_next": True}])
def test_transition_activates_next_by_default_or_true(isolated_db, tool_name, options):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("mi-proyecto", "Flujo")
    first_step = isolated_db.insert_step(context_id, 1, "Primero")
    second_step = isolated_db.insert_step(context_id, 2, "Segundo")
    isolated_db.activate_first_step(context_id)
    result = getattr(mcp, tool_name)({"step_id": first_step, **options})

    assert result["next_step"]["id"] == second_step


def test_transitions_ignore_blocked_steps_and_break_pending_ties_by_id(isolated_db):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("mi-proyecto", "Flujo")
    first_step = isolated_db.insert_step(context_id, 1, "Primero")
    blocked_step = isolated_db.insert_step(context_id, 2, "Bloqueado")
    lower_id = isolated_db.insert_step(context_id, 3, "Pendiente A")
    higher_id = isolated_db.insert_step(context_id, 3, "Pendiente B")
    isolated_db._conn().execute("UPDATE steps SET status='blocked' WHERE id=?", (blocked_step,))
    isolated_db.activate_first_step(context_id)

    result = mcp._tool_advance_step({"step_id": first_step})
    assert result["next_step"]["id"] == lower_id
    assert isolated_db._conn().execute("SELECT status FROM steps WHERE id=?", (higher_id,)).fetchone()[0] == "pending"


def test_record_tool_call_accepts_open_input_and_rejects_oversized_input(isolated_db, workflow_env):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("allowed", "Flujo")
    step_id = isolated_db.insert_step(context_id, 1, "Paso")
    accepted, accepted_error = mcp._governed_tool_call(
        "record_tool_call", {"context_id": context_id, "step_id": step_id, "tool_name": "tool", "input": {"branch": "x", "n": 1}}, "rpc-ok"
    )
    exact_input = {"payload": "x" * (8192 - len(json.dumps({"payload": ""}, ensure_ascii=False).encode("utf-8")))}
    oversized_input = {"payload": "x" * (8193 - len(json.dumps({"payload": ""}, ensure_ascii=False).encode("utf-8")))}
    exact, exact_error = mcp._governed_tool_call(
        "record_tool_call", {"context_id": context_id, "step_id": step_id, "tool_name": "tool", "input": exact_input}, "rpc-exact"
    )
    rejected, rejected_error = mcp._governed_tool_call(
        "record_tool_call", {"context_id": context_id, "step_id": step_id, "tool_name": "tool", "input": oversized_input}, "rpc-large"
    )

    assert accepted_error is False
    assert accepted["id"]
    assert exact_error is False
    assert exact["id"]
    assert json.loads(isolated_db._conn().execute("SELECT input FROM tool_calls WHERE id=?", (accepted["id"],)).fetchone()[0]) == {"branch": "x", "n": 1}
    assert rejected_error is True
    assert rejected["reason_code"] == "invalid_arguments"
    assert isolated_db._conn().execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0] == 2


def test_tool_schemas_only_use_standard_keywords():
    import orchestrator.mcp as mcp

    standard_keywords = {
        "type", "properties", "required", "items", "enum", "default", "description",
        "additionalProperties", "minimum", "maximum",
    }

    def assert_schema_keywords(schema):
        assert set(schema) <= standard_keywords
        for property_schema in schema.get("properties", {}).values():
            assert_schema_keywords(property_schema)
        if "items" in schema:
            assert_schema_keywords(schema["items"])

    for tool in mcp.TOOLS:
        assert_schema_keywords(tool["inputSchema"])


def test_nested_objects_without_additional_properties_remain_strict(isolated_db, workflow_env):
    import orchestrator.mcp as mcp

    result, is_error = mcp._governed_tool_call(
        "create_context", {"project": "allowed", "title": "Flujo", "steps": [{"title": "Paso", "extra": "no"}]}, "rpc-extra"
    )
    assert is_error is True
    assert result["reason_code"] == "invalid_arguments"
