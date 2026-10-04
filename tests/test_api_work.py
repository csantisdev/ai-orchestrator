"""Vertical Trabajo de api_v1 (spec §6.2, §23.3) sobre una base SQLite sintética."""

import json
import sqlite3
from pathlib import Path

import jsonschema
import pytest

from orchestrator import api_v1
from orchestrator.api_v1 import Request, work
from orchestrator.git_scanner import PROVIDER_NAME as GIT_PROVIDER
from orchestrator.projections import CommitIndex

SCHEMAS = Path(work.__file__).resolve().parent.parent / "schemas"
SHA_A = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
SHA_OTHER = "b1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


def _validate(instance, name):
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    jsonschema.validate(instance, schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)


def _empty_db():
    """Base en memoria con el esquema real de la aplicación y sin datos."""
    from orchestrator.db import _conn

    target = sqlite3.connect(":memory:")
    for (sql,) in _conn().execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%'"
    ).fetchall():
        target.execute(sql)
    return target


def _context(conn, project, title, status, ts, updated, parent_step_id=None, description=""):
    cursor = conn.execute(
        "INSERT INTO contexts (ts, updated_at, project, title, description, status, parent_step_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ts, updated, project, title, description, status, parent_step_id),
    )
    return cursor.lastrowid


def _step(conn, context_id, order_idx, title, status, provider="", notes="", started=None, completed=None):
    cursor = conn.execute(
        "INSERT INTO steps (context_id, order_idx, title, status, provider, notes, started_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (context_id, order_idx, title, status, provider, notes, started, completed),
    )
    return cursor.lastrowid


def _run(conn, project, ts, **values):
    columns = {"ts": ts, "project": project, **values}
    cursor = conn.execute(
        f"INSERT INTO runs ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
        tuple(columns.values()),
    )
    return cursor.lastrowid


@pytest.fixture
def data():
    conn = _empty_db()
    ids = {}
    ids["done"] = _context(conn, "mi-proyecto", "Contexto cerrado", "completed",
                           "2026-05-01T10:00:00-03:00", "2026-05-20T10:00:00-03:00")
    ids["active"] = _context(conn, "mi-proyecto", "Contexto <b>activo</b>", "active",
                             "2026-05-10T09:00:00Z", "2026-05-11T09:00:00Z", description="Objetivo")
    ids["planned"] = _context(conn, "mi-proyecto", "Programado", "programado",
                              "2026-05-12T09:00:00", "2026-05-30T09:00:00")
    ids["foreign"] = _context(conn, "otro-proyecto", "Ajeno", "active",
                              "2026-05-10T09:00:00Z", "2026-05-31T09:00:00Z")
    ids["s1"] = _step(conn, ids["active"], 1, "Primero", "completed", "claude",
                      notes=f"Hecho en {SHA_A[:9]} y PR #12; pytest 10 passed. Sin verificar: abc1234",
                      started="2026-05-10T10:00:00-03:00", completed="2026-05-10T12:00:00-03:00")
    ids["s2"] = _step(conn, ids["active"], 2, "Segundo", "in_progress", "codex",
                      started="2026-05-11T08:00:00Z")
    ids["s3"] = _step(conn, ids["active"], 3, "Tercero", "pending")
    ids["foreign_step"] = _step(conn, ids["foreign"], 1, "Ajeno", "in_progress")
    ids["child"] = _context(conn, "mi-proyecto", "Hijo", "completed", "2026-05-10T11:00:00Z",
                            "2026-05-10T11:30:00Z", parent_step_id=ids["s1"])
    conn.execute(
        "INSERT INTO alignments (ts, step_id, context_id, agent, confirmed, checkpoint, message) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-10T14:00:00Z", ids["s1"], ids["active"], "claude-code", 1, "inicio", "Alineado"),
    )
    conn.execute(
        "INSERT INTO alignments (ts, step_id, context_id, agent, confirmed, checkpoint, message) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-10T10:30:00-03:00", ids["s1"], ids["active"], "codex", 0, "desvío", "Desvío <i>x</i>"),
    )
    conn.execute(
        "INSERT INTO tool_calls (ts, step_id, context_id, tool_name, input, output, status, duration_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("2026-05-10T13:00:00Z", ids["s1"], ids["active"], "pytest", '{"secret": 1}', "SALIDA", "ok", 1200),
    )
    ids["commit_run"] = _run(conn, "mi-proyecto", "2026-05-10T12:30:00-03:00", provider=GIT_PROVIDER,
                             session_id=f"git::mi-proyecto::{SHA_A}", task="feat: algo\n\ncuerpo largo",
                             task_preview="feat: algo")
    _run(conn, "otro-proyecto", "2026-05-10T12:30:00Z", provider=GIT_PROVIDER,
         session_id=f"git::otro-proyecto::{SHA_OTHER}", task="otro", task_preview="otro")
    ids["run"] = _run(conn, "mi-proyecto", "2026-05-10T13:30:00Z", provider="claude", model="opus",
                      step_id=ids["s1"], cost_usd=0.5, session_id="claude::sesion", task="TAREA",
                      response="RESPUESTA")
    ids["routed"] = _run(conn, "mi-proyecto", "2026-05-10T13:00:00Z", provider="deepseek", model="chat",
                         step_id=ids["s1"], cost_usd=None, routing_source="router")
    conn.commit()
    yield conn, ids
    conn.close()


def test_contexts_lists_only_the_project_with_active_first(data):
    conn, ids = data
    items = work.list_contexts(conn, "mi-proyecto")
    assert [item["id"] for item in items] == [ids["active"], ids["planned"], ids["done"], ids["child"]]
    active = items[0]
    assert active["title"] == "Contexto <b>activo</b>"
    assert active["steps"] == {"total": 3, "pending": 1, "in_progress": 1, "completed": 1, "blocked": 0, "skipped": 0}
    assert active["current_step"] == {"id": ids["s2"], "title": "Segundo"}
    assert active["updated_at"] == "2026-05-11T09:00:00+00:00"
    done = next(item for item in items if item["id"] == ids["done"])
    assert done["created_at"] == "2026-05-01T13:00:00+00:00"
    assert next(item for item in items if item["id"] == ids["child"])["parent_step_id"] == ids["s1"]
    _validate({"project": "mi-proyecto", "status": None, "contexts": items}, "work_contexts.schema.json")


def test_completed_contexts_are_ordered_by_utc_update_not_by_text(data):
    conn, ids = data
    completed = work.list_contexts(conn, "mi-proyecto", status="completed")
    # "2026-05-20T10:00:00-03:00" es posterior a "2026-05-10T11:30:00Z" en UTC.
    assert [item["id"] for item in completed] == [ids["done"], ids["child"]]


def test_context_detail_carries_titles_and_graph_attributes(data):
    conn, ids = data
    detail = work.context_detail(conn, "mi-proyecto", ids["active"])
    _validate(detail, "work_context.schema.json")
    assert detail["context"]["description"] == "Objetivo"
    first, second, third = detail["steps"]
    assert [step["idx"] for step in detail["steps"]] == [1, 2, 3]
    assert first["lane"] == "claude"
    assert first["secondary"] == ["codex"]
    assert first["alignments"] == 2 and first["deviations"] == 1
    assert first["tool_calls"] == 1
    assert first["runs"] == 2 and first["cost_usd"] == 0.5
    assert first["verified_commits"] == 1
    assert first["prs"] == [12]
    assert first["children"] == [ids["child"]]
    assert first["has_notes"] is True and second["has_notes"] is False
    assert second["lane"] == "codex"
    assert third["started_at"] is None
    child = work.context_detail(conn, "mi-proyecto", ids["child"])
    assert child["context"]["parent"] == {"step_id": ids["s1"], "context_id": ids["active"]}


def test_context_of_another_project_is_not_found(data):
    conn, ids = data
    assert work.context_detail(conn, "mi-proyecto", ids["foreign"]) is None
    assert work.context_detail(conn, "mi-proyecto", 99999) is None


def test_step_trace_follows_the_evidence_of_the_step(data):
    conn, ids = data
    trace = work.step_trace(conn, "mi-proyecto", ids["s1"], CommitIndex.from_db(conn))
    _validate(trace, "work_step_trace.schema.json")
    assert trace["context"] == {"id": ids["active"], "title": "Contexto <b>activo</b>", "status": "active"}
    assert trace["step"]["idx"] == 1
    assert trace["navigation"] == {"previous": None, "next": ids["s2"], "total": 3}
    refs = trace["references"]
    assert refs["commits"] == [{
        "sha": SHA_A, "run_id": ids["commit_run"], "project": "mi-proyecto",
        "ts": "2026-05-10T15:30:00+00:00", "subject": "feat: algo",
    }]
    assert refs["unverified_shas"] == ["abc1234"]
    assert refs["prs"] == [12]
    assert refs["mentions_tests"] is True
    # Alineamientos por instante UTC: 13:30Z (10:30-03:00) antes que 14:00Z.
    assert [a["checkpoint"] for a in trace["alignments"]] == ["desvío", "inicio"]
    assert trace["alignments"][0] == {
        "id": trace["alignments"][0]["id"], "ts": "2026-05-10T13:30:00+00:00", "agent": "codex",
        "confirmed": False, "checkpoint": "desvío", "message": "Desvío <i>x</i>",
    }
    assert trace["tool_calls"] == [{
        "id": trace["tool_calls"][0]["id"], "ts": "2026-05-10T13:00:00+00:00", "tool_name": "pytest",
        "status": "ok", "duration_ms": 1200,
    }]
    assert [(run["id"], run["imported"], run["routing_source"], run["cost_usd"]) for run in trace["runs"]] == [
        (ids["routed"], False, "router", None),
        (ids["run"], True, None, 0.5),
    ]


def test_step_trace_never_leaks_run_or_tool_call_contents(data):
    conn, ids = data
    payload = json.dumps(work.step_trace(conn, "mi-proyecto", ids["s1"]))
    for secret in ("TAREA", "RESPUESTA", "cuerpo largo", "secret", "SALIDA", "claude::sesion", "git::"):
        assert secret not in payload


def test_step_trace_of_another_project_is_not_found(data):
    conn, ids = data
    assert work.step_trace(conn, "mi-proyecto", ids["foreign_step"]) is None
    middle = work.step_trace(conn, "mi-proyecto", ids["s2"])
    assert middle["navigation"] == {"previous": ids["s1"], "next": ids["s3"], "total": 3}
    assert middle["references"]["commits"] == []


def test_project_known_by_registry_runs_or_contexts(data):
    conn, _ = data
    assert work.project_known(conn, "mi-proyecto", [])
    assert work.project_known(conn, "solo-registrado", ["solo-registrado"])
    assert not work.project_known(conn, "desconocido", ["mi-proyecto"])


@pytest.fixture
def api(data, monkeypatch):
    conn, ids = data
    monkeypatch.setattr(work, "_connection", lambda: conn)
    monkeypatch.setattr(work, "_registered_projects", lambda: {"mi-proyecto", "vacio"})
    api_v1.discover()

    def get(path, **query):
        return api_v1.dispatch(Request("GET", path, query={k: [v] for k, v in query.items()}))

    return get, ids


def test_endpoints_answer_through_the_registry(api):
    get, ids = api
    status, payload = get("/api/v1/projects/mi-proyecto/contexts", status="active")
    assert status == 200
    assert [item["id"] for item in payload["contexts"]] == [ids["active"]]
    _validate(payload, "work_contexts.schema.json")
    status, payload = get(f"/api/v1/projects/mi-proyecto/contexts/{ids['active']}")
    assert status == 200 and payload["context"]["id"] == ids["active"]
    status, payload = get(f"/api/v1/projects/mi-proyecto/steps/{ids['s1']}/trace")
    assert status == 200 and payload["step"]["id"] == ids["s1"]
    status, payload = get("/api/v1/projects/vacio/contexts")
    assert (status, payload["contexts"]) == (200, [])


@pytest.mark.parametrize(
    ("path", "query", "expected"),
    [
        ("/api/v1/projects/desconocido/contexts", {}, (404, "unknown project")),
        ("/api/v1/projects/mi-proyecto/contexts", {"status": "x"}, (400, None)),
        ("/api/v1/projects/mi-proyecto/contexts/0", {}, (400, None)),
        ("/api/v1/projects/mi-proyecto/contexts/abc", {}, (400, None)),
        ("/api/v1/projects/mi-proyecto/contexts/99999", {}, (404, "unknown context")),
        ("/api/v1/projects/mi-proyecto/steps/-1/trace", {}, (400, None)),
        ("/api/v1/projects/mi-proyecto/steps/99999/trace", {}, (404, "unknown step")),
        ("/api/v1/projects/desconocido/steps/1/trace", {}, (404, "unknown project")),
    ],
)
def test_endpoint_errors(api, path, query, expected):
    get, _ = api
    status, payload = get(path, **query)
    assert status == expected[0]
    if expected[1]:
        assert payload == {"error": expected[1]}


def test_foreign_ids_are_not_found_through_the_api(api):
    get, ids = api
    assert get(f"/api/v1/projects/mi-proyecto/contexts/{ids['foreign']}")[0] == 404
    assert get(f"/api/v1/projects/mi-proyecto/steps/{ids['foreign_step']}/trace")[0] == 404
