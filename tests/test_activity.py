"""Activity D4: orden UTC, aislamiento y DTO sin texto libre."""

import json
from pathlib import Path

import jsonschema
import pytest

from orchestrator import api_v1, projections_activity
from orchestrator.api_v1 import Request, activity, work
from orchestrator.projections_activity import project_activity
from tests.test_api_work import _context, _empty_db, _run, _step


def _schema(payload):
    schema = json.loads((Path(projections_activity.__file__).parent / "schemas" / "project_activity.schema.json").read_text())
    jsonschema.validate(payload, schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)


@pytest.fixture
def data():
    conn = _empty_db()
    own = _context(conn, "mi-proyecto", "TEXTO_CONTEXTO", "active", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    foreign = _context(conn, "otro-proyecto", "TEXTO_AJENO", "active", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    step = _step(conn, own, 7, "TEXTO_PASO", "completed", "claude", "TEXTO_NOTAS", "2026-01-02T10:00:00-03:00", "2026-01-02T14:00:00Z")
    other_step = _step(conn, foreign, 1, "AJENO", "completed", started="2026-01-04T00:00:00Z")
    run = _run(conn, "mi-proyecto", "2026-01-02T13:00:00Z", provider="claude", model="opus", step_id=step,
               task="TEXTO_TAREA", response="TEXTO_RESPUESTA", duration_ms=12, cost_usd=.2)
    _run(conn, "otro-proyecto", "2026-01-05T00:00:00Z", task="TEXTO_RUN_AJENO", step_id=other_step)
    conn.execute("INSERT INTO tool_calls (ts, step_id, context_id, tool_name, input, output, status, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 ("2026-01-02T12:00:00Z", step, own, "pytest", "TEXTO_INPUT", "TEXTO_OUTPUT", "ok", 9))
    conn.execute("INSERT INTO alignments (ts, step_id, context_id, agent, confirmed, checkpoint, message) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 ("2026-01-02T13:00:00+00:00", step, own, "codex", 1, "TEXTO_CHECK", "TEXTO_MENSAJE"))
    conn.execute("INSERT INTO egress_decisions (ts, project, provider, phase, decision, reason_code, run_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 ("2026-01-02T13:00:00Z", "mi-proyecto", "openai", "preflight", "allow", "ok", run))
    conn.execute("INSERT INTO mcp_invocations (ts, request_id, server_instance_id, client_surface, transport, capability_profile, tool_name, tool_category, project, input_hash, output_hash, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 ("2026-01-02T13:00:00Z", "request-1", "server", "codex", "stdio", "write", "start_step", "write", "mi-proyecto", "HASH", "HASH", "done", "2026-01-02T13:00:00Z"))
    conn.execute("INSERT INTO mcp_invocations (ts, request_id, server_instance_id, client_surface, transport, capability_profile, tool_name, tool_category, project, input_hash, output_hash, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 ("2026-01-03T13:00:00Z", "request-2", "server", "codex", "stdio", "read", "get_context", "read", "mi-proyecto", "HASH", "HASH", "done", "2026-01-03T13:00:00Z"))
    conn.commit()
    yield conn
    conn.close()


def test_activity_is_utc_ordered_private_and_scoped(data):
    payload = project_activity(data, "mi-proyecto")
    _schema(payload)
    assert [item["ts"] for item in payload["items"]] == sorted((item["ts"] for item in payload["items"]), reverse=True)
    tied = [item["kind"] for item in payload["items"] if item["ts"] == "2026-01-02T13:00:00+00:00"]
    assert tied == ["run", "alignment", "egress", "step_started", "mcp"]
    assert all("otro-proyecto" not in json.dumps(item) for item in payload["items"])
    encoded = json.dumps(payload)
    for secret in ("TEXTO_CONTEXTO", "TEXTO_PASO", "TEXTO_NOTAS", "TEXTO_TAREA", "TEXTO_RESPUESTA", "TEXTO_INPUT", "TEXTO_OUTPUT", "TEXTO_MENSAJE", "HASH"):
        assert secret not in encoded
    assert "mcp:2" not in {item["id"] for item in payload["items"]}


def test_activity_alignment_state_is_a_status_token(data):
    data.execute("INSERT INTO alignments (ts, step_id, context_id, agent, confirmed, checkpoint, message) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 ("2026-01-02T11:00:00Z", 1, 1, "claude", 0, "CHECK", "MESSAGE"))
    data.commit()

    alignments = [item for item in project_activity(data, "mi-proyecto")["items"] if item["kind"] == "alignment"]

    assert {(item["attrs"]["confirmed"], item["state"]) for item in alignments} == {
        (True, "confirmed"), (False, "deviation"),
    }


def test_activity_cursor_has_no_duplicates_or_gaps(data):
    expected = [item["id"] for item in project_activity(data, "mi-proyecto", 200)["items"]]
    found, cursor = [], None
    while True:
        page = project_activity(data, "mi-proyecto", 2, cursor)
        found.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert found == expected and len(found) == len(set(found))
    with pytest.raises(ValueError, match="invalid cursor"):
        project_activity(data, "mi-proyecto", cursor="no-es-base64")


def test_activity_endpoint_validates_cursor_limit_and_project(data, monkeypatch):
    monkeypatch.setattr(activity, "_connection", lambda: data)
    monkeypatch.setattr(work, "_registered_projects", lambda: {"mi-proyecto"})
    api_v1.discover()
    assert api_v1.dispatch(Request("GET", "/api/v1/projects/mi-proyecto/activity", query={"cursor": ["bad"]}))[0] == 400
    assert api_v1.dispatch(Request("GET", "/api/v1/projects/mi-proyecto/activity", query={"limit": ["0"]}))[0] == 400
    assert api_v1.dispatch(Request("GET", "/api/v1/projects/desconocido/activity"))[0] == 404
