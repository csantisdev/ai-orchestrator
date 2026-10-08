"""Núcleo de comandos de la UI (RFC-010 §3.1-§3.2): invariantes I2-I6 sobre la base de test."""

import json
import uuid

import pytest

from orchestrator import api_v1, commands, mcp
from orchestrator.api_v1 import Request
from orchestrator.commands import catalog
from orchestrator.commands.catalog import Command
from orchestrator.commands.policy import ui_config_issues, ui_identity, write_ui_config
from orchestrator.db import _conn
from orchestrator.mcp_governance import PROFILE_CAPABILITIES, ExecutionIdentity

PROJECT = "mi-proyecto"
SECRET = "TEXTO-LIBRE-SECRETO"


def _identity(profile="workflow_operator", projects=(PROJECT,)):
    return ExecutionIdentity("dashboard", "http", None, profile, frozenset(projects))


@pytest.fixture
def ctx():
    conn = _conn()
    context_id = conn.execute(
        "INSERT INTO contexts (ts, updated_at, project, title, status) "
        "VALUES ('2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z', ?, 'c', 'active')",
        (PROJECT,),
    ).lastrowid
    step_id = conn.execute(
        "INSERT INTO steps (context_id, order_idx, title, status, notes) VALUES (?, 1, 's', 'in_progress', '')",
        (context_id,),
    ).lastrowid
    conn.commit()
    return {"context_id": context_id, "step_id": step_id}


def _version(table, row_id):
    return _conn().execute(f"SELECT version FROM {table} WHERE id=?", (row_id,)).fetchone()[0]


def _notes(step_id):
    return _conn().execute("SELECT notes FROM steps WHERE id=?", (step_id,)).fetchone()[0]


def _alignments(context_id):
    return _conn().execute("SELECT COUNT(*) FROM alignments WHERE context_id=?", (context_id,)).fetchone()[0]


def _record(request_id):
    return _conn().execute("SELECT * FROM ui_commands WHERE request_id=?", (request_id,)).fetchone()


def _attempts(request_id):
    return _conn().execute(
        "SELECT status, reason_code FROM ui_command_attempts WHERE request_id=? ORDER BY id", (request_id,)
    ).fetchall()


def _body(args, **extra):
    return {"request_id": str(uuid.uuid4()), "args": args, **extra}


def _notes_body(ctx, text=SECRET, version=None):
    return _body({"step_id": ctx["step_id"], "notes": text},
                 expected_version=version or _version("steps", ctx["step_id"]))


# ── I2: idempotencia ─────────────────────────────────────────────────────────

def test_same_request_id_does_not_repeat_the_effect(ctx):
    body = _notes_body(ctx)
    status, first = commands.execute("append_step_notes", body, _identity())
    assert status == 200 and first["status"] == "ok"
    notes_after = _notes(ctx["step_id"])
    version_after = _version("steps", ctx["step_id"])

    status, again = commands.execute("append_step_notes", body, _identity())
    assert status == 200 and again["status"] == "ok"
    assert again["receipt"]["replayed"] is True
    assert again["receipt"]["receipt_hash"] == first["receipt"]["receipt_hash"]
    assert again["version"] == first["version"] == version_after
    assert _notes(ctx["step_id"]) == notes_after
    assert notes_after.count(SECRET) == 1


def test_same_request_id_with_other_arguments_is_409(ctx):
    body = _body({"step_id": ctx["step_id"], "context_id": ctx["context_id"], "checkpoint": "a"})
    assert commands.execute("confirm_alignment", body, _identity())[0] == 200
    changed = {**body, "args": {**body["args"], "checkpoint": "b"}}
    status, payload = commands.execute("confirm_alignment", changed, _identity())
    assert status == 409 and payload["reason_code"] == "request_id_reused"
    other = commands.execute("append_step_notes", {**body, "args": {"step_id": ctx["step_id"], "notes": "x"}},
                             _identity())
    assert other[0] == 409 and other[1]["reason_code"] == "request_id_reused"
    assert _alignments(ctx["context_id"]) == 1


def test_terminal_denial_replays_the_same_receipt(ctx):
    body = _notes_body(ctx)
    first = commands.execute("append_step_notes", body, _identity("readonly"))[1]
    # Habilitar escrituras después no reaplica un request_id ya terminado.
    status, again = commands.execute("append_step_notes", body, _identity())
    assert status == 403 and again["status"] == "denied"
    assert again["receipt"]["receipt_hash"] == first["receipt"]["receipt_hash"]
    assert SECRET not in _notes(ctx["step_id"])


def test_not_admitted_is_evaluated_again(ctx):
    body = _notes_body(ctx)
    _conn().execute(
        "INSERT INTO ui_commands (request_id, command, category, project, capability_profile, input_hash, "
        "status, reason_code, created_at, updated_at) VALUES (?, 'append_step_notes', 'workflow_mutation', ?, "
        "'workflow_operator', ?, 'not_admitted', 'resource_busy', 'x', 'x')",
        (body["request_id"], PROJECT, _input_hash("append_step_notes", body)),
    )
    _conn().commit()
    status, payload = commands.execute("append_step_notes", body, _identity())
    assert status == 200 and payload["status"] == "ok"
    assert _record(body["request_id"])["status"] == "ok"
    assert _notes(ctx["step_id"]).count(SECRET) == 1


def test_queued_job_answers_accepted_with_the_same_job_id(ctx):
    body = _notes_body(ctx)
    _conn().execute(
        "INSERT INTO ui_commands (request_id, command, category, project, capability_profile, input_hash, "
        "status, created_at, updated_at) VALUES (?, 'append_step_notes', 'workflow_mutation', ?, "
        "'workflow_operator', ?, 'queued', 'x', 'x')",
        (body["request_id"], PROJECT, _input_hash("append_step_notes", body)),
    )
    _conn().execute(
        "INSERT INTO jobs (id, request_id, kind, status, created_at) VALUES ('job-1', ?, 'k', 'queued', 'x')",
        (body["request_id"],),
    )
    _conn().commit()
    for _ in range(2):
        status, payload = commands.execute("append_step_notes", body, _identity())
        assert status == 202 and payload["status"] == "accepted" and payload["job_id"] == "job-1"
    assert SECRET not in _notes(ctx["step_id"])


def _input_hash(name, body):
    from orchestrator.commands.core import input_commitment
    return input_commitment(name, body)


# ── I3: un registro lógico, un intento por pedido, sin texto en claro ────────

def test_one_record_and_one_attempt_per_request_without_plaintext(ctx):
    body = _notes_body(ctx)
    for _ in range(3):
        commands.execute("append_step_notes", body, _identity())
    commands.execute("append_step_notes", {**body, "args": {**body["args"], "notes": "otro"}}, _identity())

    records = _conn().execute("SELECT * FROM ui_commands WHERE request_id=?", (body["request_id"],)).fetchall()
    assert len(records) == 1
    assert [tuple(row) for row in _attempts(body["request_id"])] == [
        ("ok", None), ("ok", None), ("ok", None), ("conflict", "request_id_reused"),
    ]
    stored = json.dumps([dict(row) for row in records] + [dict(row) for row in _attempts(body["request_id"])])
    assert SECRET not in stored and "otro" not in stored


def test_receipts_carry_no_free_text(ctx):
    body = _body({"step_id": ctx["step_id"], "context_id": ctx["context_id"],
                  "checkpoint": SECRET, "message": SECRET})
    status, payload = commands.execute("confirm_alignment", body, _identity())
    assert status == 200
    assert SECRET not in json.dumps(payload)
    assert set(payload["receipt"]) == {"request_id", "command", "status", "reason_code", "version",
                                       "affected", "receipt_hash"}
    assert all(isinstance(value, int) for value in payload["receipt"]["affected"].values())


def test_invalid_request_id_is_rejected_without_a_record(ctx):
    for body in ({"request_id": "no-uuid", "args": {}}, {"args": {}}, ["x"]):
        status, payload = commands.execute("append_step_notes", body, _identity())
        assert status == 400 and payload["reason_code"] == "invalid_arguments"
    assert _record("no-uuid") is None


def test_unknown_command_is_recorded_without_its_name():
    body = _body({})
    status, payload = commands.execute(SECRET, {**body, "project": SECRET}, _identity("admin"))
    assert status == 404 and payload["reason_code"] == "unknown_command"
    assert SECRET not in json.dumps(payload)
    record = _record(body["request_id"])
    assert record["command"] == "_unknown" and record["status"] == "error"
    assert SECRET not in json.dumps(dict(record))
    assert [tuple(row) for row in _attempts(body["request_id"])] == [("error", "unknown_command")]
    assert commands.execute("confirm_alignment", body, _identity("admin"))[1]["reason_code"] == "request_id_reused"
    assert record["project"] is None


def test_invalid_envelope_or_arguments_are_recorded_without_echoing_input(ctx):
    bodies = [
        {**_notes_body(ctx), "expected_version": "uno"},
        {**_notes_body(ctx), "project": SECRET, "args": []},
        _body({"step_id": ctx["step_id"], "notes": "n", SECRET: 1}, expected_version=1),
        _body({"step_id": ctx["step_id"], "notes": "   "}, expected_version=1),
    ]
    for body in bodies:
        status, payload = commands.execute("append_step_notes", body, _identity())
        assert status == 400 and payload["reason_code"] == "invalid_arguments"
        assert SECRET not in json.dumps(payload) and "error" not in payload
        assert _record(body["request_id"])["status"] == "error"
        assert SECRET not in json.dumps(dict(_record(body["request_id"])))
        assert len(_attempts(body["request_id"])) == 1
    assert SECRET not in _notes(ctx["step_id"])


def test_concurrent_claim_from_another_process_is_replayed(ctx):
    """El reclamo se lee dentro de BEGIN IMMEDIATE: si otro proceso tiene la escritura y registra
    el mismo request_id, este pedido espera y responde con su recibo sin repetir el efecto."""
    import sqlite3
    import threading
    import time

    import orchestrator.paths as paths
    body = _notes_body(ctx)
    other = sqlite3.connect(str(paths.DB_PATH), isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    other.execute(
        "INSERT INTO ui_commands (request_id, command, category, project, capability_profile, input_hash, "
        "status, receipt_hash, result_version, created_at, updated_at) VALUES (?, 'append_step_notes', "
        "'workflow_mutation', ?, 'workflow_operator', ?, 'ok', 'hash-de-otro', 7, 'x', 'x')",
        (body["request_id"], PROJECT, _input_hash("append_step_notes", body)),
    )
    results = []
    worker = threading.Thread(
        target=lambda: results.append(commands.execute("append_step_notes", body, _identity())))
    worker.start()
    time.sleep(0.5)
    assert not results
    other.execute("COMMIT")
    other.close()
    worker.join(10)
    status, payload = results[0]
    assert status == 200 and payload["receipt"]["replayed"] is True
    assert payload["receipt"]["receipt_hash"] == "hash-de-otro"
    assert SECRET not in _notes(ctx["step_id"])


# ── I4: perfil ───────────────────────────────────────────────────────────────

def test_without_ui_config_every_non_read_command_is_denied(ctx, tmp_path, monkeypatch):
    import orchestrator.paths as paths
    monkeypatch.setattr(paths, "HOME_DIR", tmp_path)
    identity = ui_identity()
    assert identity.capability_profile == "readonly" and not identity.project_scope
    for name, command in catalog.CATALOG.items():
        assert command.category != "read"
        args = {"step_id": ctx["step_id"], "context_id": ctx["context_id"], "checkpoint": "c",
                "notes": "n", "status": "abandoned"}
        args = {key: value for key, value in args.items() if key in command.schema["properties"]}
        status, payload = commands.execute(name, _body(args, expected_version=1))
        assert status == 403 and payload["reason_code"] == "capability_denied", name
    assert _alignments(ctx["context_id"]) == 0
    assert _conn().execute("SELECT status FROM contexts WHERE id=?", (ctx["context_id"],)).fetchone()[0] == "active"


@pytest.mark.parametrize("raw", ["{no json", json.dumps({"profile": "root", "projects": [PROJECT]}),
                                 json.dumps(["admin"])])
def test_invalid_ui_config_fails_closed(raw, tmp_path, monkeypatch):
    import orchestrator.paths as paths
    monkeypatch.setattr(paths, "HOME_DIR", tmp_path)
    (tmp_path / "ui-governance.json").write_text(raw, encoding="utf-8")
    assert ui_identity().capability_profile == "readonly"
    assert ui_config_issues({PROJECT})


def test_written_ui_config_is_read_back(tmp_path, monkeypatch):
    import orchestrator.paths as paths
    monkeypatch.setattr(paths, "HOME_DIR", tmp_path)
    write_ui_config("workflow_operator", [PROJECT, " ", PROJECT])
    identity = ui_identity()
    assert identity.capability_profile == "workflow_operator"
    assert identity.project_scope == {PROJECT}
    assert ui_config_issues({PROJECT}) == []
    assert ui_config_issues(set()) == [f"alcance con alias no registrados: {PROJECT}"]


@pytest.mark.parametrize("category", ["project_admin", "maintenance"])
def test_admin_only_categories(category, ctx, monkeypatch):
    fake = Command(
        name=f"fake_{category}", category=category,
        schema={"type": "object", "required": ["context_id"], "properties": {"context_id": {"type": "integer"}}},
        domain_tool="confirm_alignment",
        to_domain=lambda args: {"step_id": ctx["step_id"], "context_id": args["context_id"],
                                "agent": "dashboard", "checkpoint": "c"},
        owner=("context", "context_id"),
        receipt=lambda args, result: {},
    )
    monkeypatch.setitem(catalog.CATALOG, fake.name, fake)
    for profile in ("readonly", "observability", "workflow_operator", "memory_curator"):
        status, payload = commands.execute(fake.name, _body({"context_id": ctx["context_id"]}), _identity(profile))
        assert status == 403 and payload["reason_code"] == "capability_denied", profile
    assert _alignments(ctx["context_id"]) == 0
    status, _ = commands.execute(fake.name, _body({"context_id": ctx["context_id"]}), _identity("admin"))
    assert status == 200 and _alignments(ctx["context_id"]) == 1
    assert category in PROFILE_CAPABILITIES["admin"]


# ── I5: alcance ──────────────────────────────────────────────────────────────

def test_project_out_of_scope_is_denied_without_effects(ctx):
    status, payload = commands.execute(
        "confirm_alignment",
        _body({"step_id": ctx["step_id"], "context_id": ctx["context_id"], "checkpoint": "c"}),
        _identity(projects=("otro-proyecto",)),
    )
    assert status == 403 and payload["reason_code"] == "project_out_of_scope"
    assert _alignments(ctx["context_id"]) == 0


def test_declared_project_must_own_the_target(ctx):
    body = _body({"step_id": ctx["step_id"], "context_id": ctx["context_id"], "checkpoint": "c"},
                 project="otro-proyecto")
    status, payload = commands.execute("confirm_alignment", body, _identity(projects=(PROJECT, "otro-proyecto")))
    assert status == 400 and payload["reason_code"] == "project_mismatch"
    assert _alignments(ctx["context_id"]) == 0


def test_missing_target_is_404(ctx):
    status, payload = commands.execute(
        "append_step_notes", _body({"step_id": 999_999, "notes": "n"}, expected_version=1), _identity())
    assert status == 404 and payload["reason_code"] == "not_found"


def test_step_must_belong_to_the_context(ctx):
    other = _conn().execute(
        "INSERT INTO contexts (ts, updated_at, project, title, status) VALUES ('x', 'x', ?, 'o', 'active')",
        (PROJECT,),
    ).lastrowid
    _conn().commit()
    status, payload = commands.execute(
        "confirm_alignment", _body({"step_id": ctx["step_id"], "context_id": other, "checkpoint": "c"}), _identity())
    assert status == 400 and payload["reason_code"] == "execution_error"
    assert _alignments(other) == 0


# ── I6: versión esperada ─────────────────────────────────────────────────────

def test_stale_expected_version_is_a_conflict_without_effects(ctx):
    current = _version("steps", ctx["step_id"])
    _conn().execute("UPDATE steps SET title='cambio externo' WHERE id=?", (ctx["step_id"],))
    _conn().commit()
    status, payload = commands.execute("append_step_notes", _notes_body(ctx, version=current), _identity())
    assert status == 409 and payload["status"] == "conflict" and payload["reason_code"] == "version_conflict"
    assert SECRET not in _notes(ctx["step_id"])
    assert _version("steps", ctx["step_id"]) == current + 1


def test_versioned_command_requires_expected_version(ctx):
    body = _body({"context_id": ctx["context_id"], "status": "abandoned"})
    status, payload = commands.execute("close_context", body, _identity())
    assert status == 400 and payload["reason_code"] == "invalid_arguments"


def test_ok_returns_the_resulting_version(ctx):
    before = _version("contexts", ctx["context_id"])
    status, payload = commands.execute(
        "close_context",
        _body({"context_id": ctx["context_id"], "status": "completed"}, expected_version=before),
        _identity(),
    )
    assert status == 200 and payload["version"] == before + 1 == _version("contexts", ctx["context_id"])
    assert payload["receipt"]["counts"] == {"open_steps": 1}
    assert _conn().execute("SELECT status FROM contexts WHERE id=?", (ctx["context_id"],)).fetchone()[0] == "completed"


def test_mcp_mutation_also_bumps_the_version(ctx):
    before = _version("steps", ctx["step_id"])
    mcp._HANDLERS["update_step"]({"step_id": ctx["step_id"], "notes_append": "mcp"})
    assert _version("steps", ctx["step_id"]) == before + 1


# ── Una implementación por operación y transporte ───────────────────────────

def test_every_command_adapts_an_mcp_domain_function():
    from orchestrator.mcp_governance import TOOL_CATEGORIES
    for command in catalog.CATALOG.values():
        assert command.domain_tool in TOOL_CATEGORIES
        assert catalog.domain_handler(command) is mcp._HANDLERS[command.domain_tool]


def test_failing_domain_function_rolls_back_and_records_error(ctx, monkeypatch):
    def boom(args):
        _conn().execute("INSERT INTO alignments (ts, step_id, context_id) VALUES ('x', ?, ?)",
                        (ctx["step_id"], ctx["context_id"]))
        raise RuntimeError("falla interna")

    monkeypatch.setitem(mcp._HANDLERS, "confirm_alignment", boom)
    body = _body({"step_id": ctx["step_id"], "context_id": ctx["context_id"], "checkpoint": "c"})
    status, payload = commands.execute("confirm_alignment", body, _identity())
    assert status == 500 and payload["reason_code"] == "internal_error" and "falla" not in json.dumps(payload)
    assert payload["hint"]
    assert _alignments(ctx["context_id"]) == 0
    assert _record(body["request_id"])["status"] == "error"


def test_api_routes(ctx, tmp_path, monkeypatch):
    import orchestrator.paths as paths
    monkeypatch.setattr(paths, "HOME_DIR", tmp_path)
    api_v1.discover()
    status, listing = api_v1.dispatch(Request("GET", "/api/v1/commands"))
    assert status == 200 and listing["profile"] == "readonly"
    assert {item["name"] for item in listing["commands"]} == set(catalog.CATALOG)
    assert all(not item["enabled"] and item["reason_code"] == "capability_denied" for item in listing["commands"])

    write_ui_config("observability", [PROJECT])
    status, listing = api_v1.dispatch(Request("GET", "/api/v1/commands"))
    enabled = {item["name"] for item in listing["commands"] if item["enabled"]}
    assert enabled == {"confirm_alignment"}

    body = _body({"step_id": ctx["step_id"], "context_id": ctx["context_id"], "checkpoint": "c"})
    status, payload = api_v1.dispatch(Request("POST", "/api/v1/commands/confirm_alignment", body=body))
    assert status == 200 and payload["status"] == "ok"
    assert _record(body["request_id"])["capability_profile"] == "observability"


def _fix_env(tmp_path, monkeypatch):
    from pathlib import Path

    import orchestrator.cli as cli
    import orchestrator.paths as paths
    repo, home = tmp_path / "repo", tmp_path / "home"
    repo.mkdir()
    home.mkdir()
    monkeypatch.setattr(paths, "HOME_DIR", tmp_path / "orchestrator-home")
    monkeypatch.setattr(cli, "_ensure_db", lambda: None)
    monkeypatch.setattr(cli, "_repo_root", lambda: repo)
    monkeypatch.setattr(cli.index_module, "list_projects", lambda: {})
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


def test_fix_writes_ui_config_only_when_asked(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from orchestrator.cli import app
    from orchestrator.commands.policy import ui_config_path
    _fix_env(tmp_path, monkeypatch)
    base = ["fix", "--mcp-profile", "workflow_operator", "--mcp-projects", PROJECT]

    assert CliRunner().invoke(app, base).exit_code == 0
    assert not ui_config_path().exists()

    result = CliRunner().invoke(app, [*base, "--ui-profile", "workflow_operator", "--ui-projects", PROJECT])
    assert result.exit_code == 0, result.output
    assert ui_identity() == _identity()

    result = CliRunner().invoke(app, [*base, "--ui-profile", "root"])
    assert result.exit_code == 1
    assert ui_identity() == _identity()
