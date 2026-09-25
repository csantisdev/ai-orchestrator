import tempfile
import threading
from pathlib import Path

import pytest


@pytest.fixture()
def isolated_db(monkeypatch):
    import orchestrator.db as db_mod
    import orchestrator.paths as paths_mod

    tmp_path = Path(tempfile.mkdtemp())
    monkeypatch.setattr(paths_mod, "HOME_DIR", tmp_path)
    monkeypatch.setattr(paths_mod, "DB_PATH", tmp_path / "runs.db")
    monkeypatch.setattr(db_mod, "_local", threading.local())
    db_mod.init_db()
    yield db_mod


def _codes(result):
    return [w["code"] for w in result["workflow_state"]["warnings"]]


def test_get_context_warns_when_project_has_several_active_contexts(isolated_db):
    import orchestrator.mcp as mcp

    older = isolated_db.insert_context("backend", "Backlog")
    newer = isolated_db.insert_context("backend", "Current")
    isolated_db.insert_context("other", "Unrelated")
    step = isolated_db.insert_step(newer, 1, "Work")
    isolated_db.start_step(step)

    result = mcp._tool_get_context({"project": "backend"})

    assert result["id"] == newer
    assert _codes(result) == ["multiple_active_contexts"]
    assert result["workflow_state"]["other_active_context_ids"] == [older]
    assert result["workflow_state"]["active_step"]["id"] == step


def test_get_context_warns_when_no_step_is_in_progress(isolated_db):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("backend", "Stalled")
    isolated_db.insert_step(context_id, 1, "First")
    isolated_db.insert_step(context_id, 2, "Second")

    result = mcp._tool_get_context({"context_id": context_id})

    assert _codes(result) == ["no_step_in_progress"]
    assert result["workflow_state"]["pending_steps"] == 2
    assert result["workflow_state"]["active_step"] is None


def test_get_context_has_no_warnings_for_healthy_single_context(isolated_db):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("backend", "Healthy")
    isolated_db.insert_step(context_id, 1, "Only")
    isolated_db.activate_first_step(context_id)

    result = mcp._tool_get_context({"project": "backend"})

    assert _codes(result) == []


def test_other_active_contexts_never_include_other_projects(isolated_db):
    import orchestrator.mcp as mcp

    isolated_db.insert_context("secret", "Other project")
    context_id = isolated_db.insert_context("backend", "Mine")

    result = mcp._tool_get_context({"context_id": context_id})

    assert result["workflow_state"]["other_active_context_ids"] == []


def test_skipping_last_open_non_active_step_completes_context(isolated_db):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("backend", "Title")
    first = isolated_db.insert_step(context_id, 1, "First")
    second = isolated_db.insert_step(context_id, 2, "Second")
    isolated_db.start_step(second)
    mcp._tool_advance_step({"step_id": second})

    result = mcp._tool_skip_step({"step_id": first, "reason": "absorbed"})

    assert result["context_done"] is True
    status = isolated_db._conn().execute("SELECT status FROM contexts WHERE id=?", (context_id,)).fetchone()[0]
    assert status == "completed"


def test_skipping_pending_step_keeps_context_open_while_work_remains(isolated_db):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("backend", "Title")
    isolated_db.insert_step(context_id, 1, "Active")
    later = isolated_db.insert_step(context_id, 2, "Later")
    isolated_db.activate_first_step(context_id)

    result = mcp._tool_skip_step({"step_id": later})

    assert result["context_done"] is False


def test_server_instructions_are_project_agnostic_and_require_stopping_on_denial():
    from orchestrator.mcp import SERVER_INSTRUCTIONS

    assert "project='ai-orchestrator'" not in SERVER_INSTRUCTIONS
    assert "workflow_state.warnings" in SERVER_INSTRUCTIONS
    assert "hint" in SERVER_INSTRUCTIONS


def test_get_context_authorizes_owner_of_context_id_not_claimed_project(isolated_db, monkeypatch):
    import orchestrator.mcp as mcp

    monkeypatch.setenv("ORCHESTRATOR_MCP_PROFILE", "readonly")
    monkeypatch.setenv("ORCHESTRATOR_MCP_PROJECTS", "allowed")
    private = isolated_db.insert_context("private", "Secret title")

    result, is_error = mcp._governed_tool_call(
        "get_context", {"project": "allowed", "context_id": private}, "r-1"
    )

    assert is_error is True
    assert result["reason_code"] == "project_out_of_scope"
    assert "Secret title" not in str(result)


def test_explicit_context_id_does_not_claim_newest_was_returned(isolated_db):
    import orchestrator.mcp as mcp

    older = isolated_db.insert_context("backend", "Backlog")
    isolated_db.insert_context("backend", "Current")

    result = mcp._tool_get_context({"context_id": older})

    assert result["id"] == older
    assert "multiple_active_contexts" not in _codes(result)
    assert result["workflow_state"]["other_active_context_ids"] != []


def test_skip_does_not_report_completion_for_non_active_context(isolated_db):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("backend", "Planned", status="programado")
    step = isolated_db.insert_step(context_id, 1, "Only")

    result = mcp._tool_skip_step({"step_id": step})

    assert result["context_done"] is False
    status = isolated_db._conn().execute("SELECT status FROM contexts WHERE id=?", (context_id,)).fetchone()[0]
    assert status == "programado"
