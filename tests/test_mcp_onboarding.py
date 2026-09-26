import json
import tempfile
import threading
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from orchestrator.cli import _apply_codex_mcp, _apply_json_mcp, _mcp_client_envs, app
from orchestrator.mcp_governance import governance_env, governance_env_issues


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


@pytest.fixture()
def readonly_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_MCP_PROFILE", "readonly")
    monkeypatch.setenv("ORCHESTRATOR_MCP_PROJECTS", "allowed,secret-neighbour")
    monkeypatch.setenv("ORCHESTRATOR_MCP_CLIENT_SURFACE", "codex_cli")
    monkeypatch.setenv("ORCHESTRATOR_MCP_TRANSPORT", "stdio")


def _entry(profile="workflow_operator", scope=("allowed",), surface="claude_code"):
    return {
        "command": "C:/venv/python.exe",
        "args": ["-u", "-m", "orchestrator.mcp"],
        "cwd": "C:/repo",
        "env": governance_env(profile, list(scope), surface),
    }


def _recorder():
    calls = {"did": [], "skip": [], "fail": []}
    return calls, calls["did"].append, calls["skip"].append, calls["fail"].append


def test_scope_denial_explains_fix_without_listing_other_projects(isolated_db, readonly_env):
    import orchestrator.mcp as mcp

    isolated_db.insert_context("other", "Private")
    result, is_error = mcp._governed_tool_call("get_context", {"project": "other"}, "r-1")

    assert is_error is True
    assert result["reason_code"] == "project_out_of_scope"
    assert result["capability_profile"] == "readonly"
    assert "ORCHESTRATOR_MCP_PROJECTS" in result["hint"]
    assert "secret-neighbour" not in json.dumps(result)


def test_capability_denial_names_the_profile_variable(isolated_db, readonly_env):
    import orchestrator.mcp as mcp

    context_id = isolated_db.insert_context("allowed", "Title")
    step_id = isolated_db.insert_step(context_id, 1, "Step")
    result, _ = mcp._governed_tool_call("advance_step", {"step_id": step_id}, "r-2")

    assert result["reason_code"] == "capability_denied"
    assert "ORCHESTRATOR_MCP_PROFILE" in result["hint"]


def test_governance_env_issues_flags_missing_and_unknown_values():
    assert len(governance_env_issues({}, {"allowed"})) == 2
    assert governance_env_issues(governance_env("readonly", ["allowed"], "other"), {"allowed"}) == []
    issues = governance_env_issues(
        {"ORCHESTRATOR_MCP_PROFILE": "root", "ORCHESTRATOR_MCP_PROJECTS": "allowed,ghost"},
        {"allowed"},
    )
    assert any("root" in issue for issue in issues)
    assert any("ghost" in issue for issue in issues)


def test_governance_env_rejects_unknown_profile():
    with pytest.raises(ValueError):
        governance_env("superuser", ["allowed"], "other")


def test_json_mcp_config_gets_env_without_overriding_operator_choice(tmp_path):
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps({"mcpServers": {"ai-orchestrator": {
        "command": "python", "env": {"ORCHESTRATOR_MCP_PROFILE": "admin", "OTHER": "kept"},
    }}}), encoding="utf-8")
    calls, did, skip, _ = _recorder()

    _apply_json_mcp(path, "mcpServers", "ai-orchestrator", _entry(), ".mcp.json", did, skip)

    env = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["ai-orchestrator"]["env"]
    assert env["ORCHESTRATOR_MCP_PROFILE"] == "admin"
    assert env["ORCHESTRATOR_MCP_PROJECTS"] == "allowed"
    assert env["OTHER"] == "kept"
    assert len(calls["did"]) == 1

    _apply_json_mcp(path, "mcpServers", "ai-orchestrator", _entry(), ".mcp.json", did, skip)
    assert len(calls["skip"]) == 1


def test_json_mcp_config_is_created_with_env(tmp_path):
    path = tmp_path / "nested" / "settings.json"
    _, did, skip, _ = _recorder()

    _apply_json_mcp(path, "mcpServers", "ai-orchestrator", _entry(), "settings", did, skip)

    server = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["ai-orchestrator"]
    assert governance_env_issues(server["env"], {"allowed"}) == []


def test_codex_config_created_with_env_is_valid_toml(tmp_path):
    path = tmp_path / ".codex" / "config.toml"
    _, did, skip, fail = _recorder()

    _apply_codex_mcp(path, _entry(surface="codex_cli"), did, skip, fail)

    server = tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"]["ai_orchestrator"]
    assert server["env"]["ORCHESTRATOR_MCP_CLIENT_SURFACE"] == "codex_cli"
    assert server["cwd"] == "C:/repo"
    assert server["tools"]["advance_step"]["approval_mode"] == "approve"


def test_codex_config_without_env_gets_block_before_tool_tables(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[mcp_servers.ai_orchestrator]\ncommand = "C:\\\\py.exe"\nargs = ["-m", "orchestrator.mcp"]\n\n'
        '[mcp_servers.ai_orchestrator.tools.get_context]\napproval_mode = "approve"\n',
        encoding="utf-8",
    )
    calls, did, skip, fail = _recorder()

    _apply_codex_mcp(path, _entry(surface="codex_cli"), did, skip, fail)

    server = tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"]["ai_orchestrator"]
    assert server["env"]["ORCHESTRATOR_MCP_PROJECTS"] == "allowed"
    assert server["command"] == "C:\\py.exe"
    assert server["tools"]["get_context"]["approval_mode"] == "approve"
    assert len(calls["did"]) == 1


def test_codex_config_with_partial_env_is_reported_not_rewritten(tmp_path):
    path = tmp_path / "config.toml"
    original = (
        '[mcp_servers.ai_orchestrator]\ncommand = "py"\n\n'
        '[mcp_servers.ai_orchestrator.env]\nORCHESTRATOR_MCP_PROFILE = "readonly"\n'
    )
    path.write_text(original, encoding="utf-8")
    calls, did, skip, fail = _recorder()

    _apply_codex_mcp(path, _entry(surface="codex_cli"), did, skip, fail)

    assert path.read_text(encoding="utf-8") == original
    assert len(calls["fail"]) == 1


def test_client_env_discovery_reads_project_json_and_codex(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"ai-orchestrator": {"command": "py"}}}), encoding="utf-8"
    )
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text(
        '[mcp_servers.ai_orchestrator.env]\nORCHESTRATOR_MCP_PROFILE = "readonly"\n', encoding="utf-8"
    )

    found = {label: (env, error) for label, env, error in _mcp_client_envs(tmp_path, tmp_path / "missing.json")}

    assert found[".mcp.json"] == ({}, None)
    assert found[".codex/config.toml"] == ({"ORCHESTRATOR_MCP_PROFILE": "readonly"}, None)


def test_start_step_activates_out_of_order_step_and_reports_backlog(isolated_db):
    context_id = isolated_db.insert_context("allowed", "Title")
    isolated_db.insert_step(context_id, 1, "First")
    target = isolated_db.insert_step(context_id, 2, "Second")

    result = isolated_db.start_step(target)

    assert result["earlier_pending_steps"] == 1
    status = isolated_db._conn().execute("SELECT status FROM steps WHERE id=?", (target,)).fetchone()[0]
    assert status == "in_progress"


def test_start_step_refuses_second_active_step_and_non_pending(isolated_db):
    context_id = isolated_db.insert_context("allowed", "Title")
    first = isolated_db.insert_step(context_id, 1, "First")
    second = isolated_db.insert_step(context_id, 2, "Second")
    isolated_db.start_step(first)

    with pytest.raises(ValueError, match="in_progress"):
        isolated_db.start_step(second)
    with pytest.raises(ValueError, match="solo se pueden iniciar"):
        isolated_db.start_step(first)


@pytest.mark.parametrize("status", ["completed", "abandoned", "programado"])
def test_start_step_refuses_non_active_contexts_without_mutation(isolated_db, status):
    context_id = isolated_db.insert_context("allowed", "Title", status=status)
    step_id = isolated_db.insert_step(context_id, 1, "Step")

    with pytest.raises(ValueError, match="no admite iniciar") as exc:
        isolated_db.start_step(step_id)

    assert exc.value.reason_code == "context_not_active"
    assert isolated_db._conn().execute("SELECT status FROM steps WHERE id=?", (step_id,)).fetchone()[0] == "pending"


def test_cli_step_start_refuses_programmed_context(isolated_db):
    context_id = isolated_db.insert_context("allowed", "Title", status="programado")
    step_id = isolated_db.insert_step(context_id, 1, "Step")

    result = CliRunner().invoke(app, ["step", "start", str(step_id)])

    assert result.exit_code == 1
    assert "update_context(status='active')" in result.output


def test_cli_step_commands_reconcile_context_without_mcp(isolated_db):
    runner = CliRunner()
    context_id = isolated_db.insert_context("allowed", "Title")
    first = isolated_db.insert_step(context_id, 1, "First")
    second = isolated_db.insert_step(context_id, 2, "Second")

    assert runner.invoke(app, ["step", "start", str(second)]).exit_code == 0
    done = runner.invoke(app, ["step", "done", str(second), "--notes", "cerrado fuera del MCP"])
    assert done.exit_code == 0
    skipped = runner.invoke(app, ["step", "skip", str(first), "--reason", "absorbido"])
    assert skipped.exit_code == 0

    rows = dict(isolated_db._conn().execute(
        "SELECT id, status FROM steps WHERE context_id=?", (context_id,)
    ).fetchall())
    assert rows == {first: "skipped", second: "completed"}


def test_cli_step_done_rejects_pending_step_with_exit_code(isolated_db):
    context_id = isolated_db.insert_context("allowed", "Title")
    step_id = isolated_db.insert_step(context_id, 1, "Only")

    result = CliRunner().invoke(app, ["step", "done", str(step_id)])

    assert result.exit_code == 1
    assert "in_progress" in result.output


def test_cli_step_reset_returns_active_step_to_pending_and_keeps_notes(isolated_db):
    context_id = isolated_db.insert_context("allowed", "Title")
    step_id = isolated_db.insert_step(context_id, 1, "Only")
    isolated_db.start_step(step_id)
    isolated_db._conn().execute("UPDATE steps SET notes='existing' WHERE id=?", (step_id,))
    isolated_db._conn().commit()

    result = CliRunner().invoke(app, ["step", "reset", str(step_id), "-n", "paused"])

    assert result.exit_code == 0
    row = isolated_db._conn().execute("SELECT status, started_at, notes FROM steps WHERE id=?", (step_id,)).fetchone()
    assert dict(row) == {"status": "pending", "started_at": None, "notes": "existing\npaused"}


def test_malformed_json_config_is_never_overwritten(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"mcpServers": {', encoding="utf-8")
    calls, did, skip, _ = _recorder()

    _apply_json_mcp(path, "mcpServers", "ai-orchestrator", _entry(), "settings", did, skip)

    assert path.read_text(encoding="utf-8") == '{"mcpServers": {'
    assert calls["did"] == [] and len(calls["skip"]) == 1


def test_json_config_with_non_object_env_is_not_rewritten(tmp_path):
    path = tmp_path / "settings.json"
    original = json.dumps({"mcpServers": {"ai-orchestrator": {"command": "py", "env": []}}})
    path.write_text(original, encoding="utf-8")
    calls, did, skip, _ = _recorder()

    _apply_json_mcp(path, "mcpServers", "ai-orchestrator", _entry(), "settings", did, skip)

    assert path.read_text(encoding="utf-8") == original
    assert calls["did"] == []


def test_existing_entry_is_completed_even_when_creation_is_disabled(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"mcpServers": {"ai-orchestrator": {"command": "py"}}}), encoding="utf-8")
    missing = tmp_path / "absent.json"
    calls, did, skip, _ = _recorder()

    _apply_json_mcp(path, "mcpServers", "ai-orchestrator", _entry(), "global", did, skip, create=False)
    _apply_json_mcp(missing, "mcpServers", "ai-orchestrator", _entry(), "global", did, skip, create=False)

    env = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["ai-orchestrator"]["env"]
    assert env["ORCHESTRATOR_MCP_PROJECTS"] == "allowed"
    assert not missing.exists()


def test_governance_env_issues_reports_non_object_env():
    issues = governance_env_issues([], {"allowed"})
    assert len(issues) == 1 and "objeto" in issues[0]


def test_codex_env_block_ignores_commented_tool_header(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[mcp_servers.ai_orchestrator]\ncommand = "py"\n'
        '# see [mcp_servers.ai_orchestrator.tools.get_context] below\n\n'
        '[mcp_servers.ai_orchestrator.tools.get_context]\napproval_mode = "approve"\n',
        encoding="utf-8",
    )
    _, did, skip, fail = _recorder()

    _apply_codex_mcp(path, _entry(surface="codex_cli"), did, skip, fail)

    server = tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"]["ai_orchestrator"]
    assert server["env"]["ORCHESTRATOR_MCP_PROJECTS"] == "allowed"
    assert "ORCHESTRATOR_MCP_PROFILE" not in server


def test_fix_aborts_before_writing_when_scope_is_empty(tmp_path, monkeypatch):
    import orchestrator.cli as cli

    monkeypatch.setattr(cli, "_ensure_db", lambda: None)
    monkeypatch.setattr(cli, "_mcp_default_scope", lambda root: [])
    writes = []
    monkeypatch.setattr(cli, "_apply_json_mcp", lambda *a, **k: writes.append(a))
    monkeypatch.setattr(cli, "_apply_codex_mcp", lambda *a, **k: writes.append(a))

    result = CliRunner().invoke(app, ["fix"])

    assert result.exit_code == 1
    assert writes == []


def test_codex_env_is_not_written_inside_multiline_string(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[mcp_servers.ai_orchestrator]\ncommand = "py"\nnote = """\n'
        '[mcp_servers.ai_orchestrator.tools.fake]\n"""\n',
        encoding="utf-8",
    )
    calls, did, skip, fail = _recorder()

    _apply_codex_mcp(path, _entry(surface="codex_cli"), did, skip, fail)

    server = tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"]["ai_orchestrator"]
    assert server["env"]["ORCHESTRATOR_MCP_PROJECTS"] == "allowed"
    assert server["note"] == "[mcp_servers.ai_orchestrator.tools.fake]\n"
    assert len(calls["did"]) == 1


def test_codex_env_insertion_fails_closed_when_no_candidate_verifies(tmp_path, monkeypatch):
    import orchestrator.cli as cli

    path = tmp_path / "config.toml"
    original = '[mcp_servers.ai_orchestrator]\ncommand = "py"\n'
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(cli, "_codex_env_inserted_exactly", lambda *a: False)
    calls, did, skip, fail = _recorder()

    _apply_codex_mcp(path, _entry(surface="codex_cli"), did, skip, fail)

    assert path.read_text(encoding="utf-8") == original
    assert calls["did"] == [] and len(calls["fail"]) == 1


def test_codex_env_skips_fake_header_and_uses_real_tool_table(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[mcp_servers.ai_orchestrator]\ncommand = "py"\nnote = """\n'
        '[mcp_servers.ai_orchestrator.tools.fake]\n"""\n\n'
        '[mcp_servers.ai_orchestrator.tools.get_context]\napproval_mode = "approve"\n',
        encoding="utf-8",
    )
    calls, did, skip, fail = _recorder()

    _apply_codex_mcp(path, _entry(surface="codex_cli"), did, skip, fail)

    server = tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"]["ai_orchestrator"]
    assert server["env"]["ORCHESTRATOR_MCP_PROJECTS"] == "allowed"
    assert server["note"] == "[mcp_servers.ai_orchestrator.tools.fake]\n"
    assert len(calls["did"]) == 1


def test_client_env_discovery_reports_unreadable_configs(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    (tmp_path / ".mcp.json").write_text('{"mcpServers": {', encoding="utf-8")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text("[mcp_servers\n", encoding="utf-8")

    found = {label: error for label, _, error in _mcp_client_envs(tmp_path, tmp_path / "missing.json")}

    assert "JSON" in found[".mcp.json"]
    assert "TOML" in found[".codex/config.toml"]


def test_codex_scalar_env_fails_closed_without_rewriting(tmp_path):
    path = tmp_path / "config.toml"
    original = '[mcp_servers.ai_orchestrator]\ncommand = "py"\nenv = "broken"\n'
    path.write_text(original, encoding="utf-8")
    calls, did, skip, fail = _recorder()

    _apply_codex_mcp(path, _entry(surface="codex_cli"), did, skip, fail)

    assert path.read_text(encoding="utf-8") == original
    assert len(calls["fail"]) == 1 and calls["did"] == []


def test_client_env_discovery_reports_scalar_codex_servers(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text('mcp_servers = "broken"', encoding="utf-8")

    found = {label: error for label, _, error in _mcp_client_envs(tmp_path, tmp_path / "missing.json")}

    assert "mcp_servers" in found[".codex/config.toml"]


def test_codex_approved_tools_cover_every_mcp_tool():
    from orchestrator.cli import _CODEX_APPROVED_TOOLS
    from orchestrator.mcp import TOOLS

    template = tomllib.loads((Path(__file__).resolve().parents[1] / ".codex" / "config.toml.example").read_text(encoding="utf-8"))
    published = {tool["name"] for tool in TOOLS}
    assert set(_CODEX_APPROVED_TOOLS) == published
    assert set(template["mcp_servers"]["ai_orchestrator"]["tools"]) == published
