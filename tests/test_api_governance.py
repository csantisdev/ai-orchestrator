"""Vertical Gobernanza de api_v1 (spec §19.6, §23.3) sobre una base SQLite sintética."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from orchestrator import api_v1
from orchestrator.api_v1 import Request, governance
from orchestrator.projections import parse_instant

SCHEMAS = Path(governance.__file__).resolve().parent.parent / "schemas"
NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


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


_SEQUENCE = iter(range(1, 10_000))


def _invocation(conn, project, ts, status, *, surface="claude_code", tool="advance_step",
                category="workflow_transition", is_error=0, reason=None, error_code=None):
    number = next(_SEQUENCE)
    return conn.execute(
        "INSERT INTO mcp_invocations (ts, request_id, server_instance_id, client_surface, transport, actor_id, "
        "capability_profile, tool_name, tool_category, project, input_hash, output_hash, is_error, status, "
        "reason_code, error_code, duration_ms, created_at) "
        "VALUES (?, ?, 'srv', ?, 'stdio', 'ACTOR-SECRETO', 'readonly', ?, ?, ?, 'HASH-ENTRADA', 'HASH-SALIDA', "
        "?, ?, ?, ?, 12, ?)",
        (ts, f"req-{number}", surface, tool, category, project, is_error, status, reason, error_code, ts),
    ).lastrowid


def _egress(conn, project, ts, decision="blocked", reason="sensitivity_exceeds_clearance", run_id=None):
    return conn.execute(
        "INSERT INTO egress_decisions (ts, project, provider, phase, decision, reason_code, sensitivity, "
        "clearance, run_id) VALUES (?, ?, 'deepseek', 'before_call', ?, ?, 'restricted', 'public', ?)",
        (ts, project, decision, reason, run_id),
    ).lastrowid


@pytest.fixture
def conn():
    db = _empty_db()
    db.execute("INSERT INTO contexts (ts, updated_at, project, title, status) VALUES "
               "('2026-06-01T00:00:00Z', '2026-06-01T00:00:00Z', 'mi-proyecto', 'c', 'active')")
    yield db
    db.close()


@pytest.fixture
def data(conn):
    ids = {
        "denied_old": _invocation(conn, "mi-proyecto", "2026-05-01T10:00:00Z", "denied",
                                  reason="project_out_of_scope"),
        "denied": _invocation(conn, "mi-proyecto", "2026-06-14T09:00:00-03:00", "denied", surface="codex_cli",
                              tool="list_steps", category="read", reason="capability_denied"),
        "error": _invocation(conn, "mi-proyecto", "2026-06-14T11:00:00Z", "error", is_error=1,
                             error_code="invalid_arguments"),
        "flagged": _invocation(conn, "mi-proyecto", "2026-06-14T10:00:00", "success", is_error=1),
        "ok": _invocation(conn, "mi-proyecto", "2026-06-14T13:00:00Z", "success"),
        "pending": _invocation(conn, "mi-proyecto", "2026-06-13T13:00:00Z", "in_progress"),
        "broken_ts": _invocation(conn, "mi-proyecto", "no es fecha", "denied", reason="project_out_of_scope"),
        "foreign": _invocation(conn, "otro-proyecto", "2026-06-14T12:00:00Z", "denied",
                               reason="project_out_of_scope"),
    }
    conn.commit()
    return ids


def _problem_ids(conn, project):
    """Orden esperado calculado sin SQL de fechas: instante UTC desc, id desc; ilegibles al final."""
    rows = conn.execute(
        "SELECT id, ts FROM mcp_invocations WHERE project = ? AND (status IN ('denied', 'error') OR is_error = 1)",
        (project,),
    ).fetchall()
    readable = [(parse_instant(ts), row_id) for row_id, ts in rows if parse_instant(ts)]
    unreadable = [row_id for row_id, ts in rows if not parse_instant(ts)]
    return [row_id for _, row_id in sorted(readable, reverse=True)] + sorted(unreadable, reverse=True)


def test_mcp_problems_are_listed_by_utc_instant_without_payloads(conn, data):
    page = governance.list_mcp_invocations(conn, "mi-proyecto")
    _validate(page, "governance_mcp_invocations.schema.json")
    ids = [item["id"] for item in page["items"]]
    assert ids == _problem_ids(conn, "mi-proyecto")
    # 09:00-03:00 son las 12:00 UTC: la más reciente aunque su texto ordene antes.
    assert ids == [data["denied"], data["error"], data["flagged"], data["denied_old"], data["broken_ts"]]
    assert page["next_cursor"] is None
    denied = next(item for item in page["items"] if item["id"] == data["denied"])
    assert denied == {
        "id": data["denied"], "sel": f"decision:mcp-{data['denied']}", "ts": "2026-06-14T12:00:00+00:00",
        "agent": "codex", "client_surface": "codex_cli", "transport": "stdio", "capability_profile": "readonly",
        "tool_name": "list_steps", "tool_category": "read", "status": "denied", "is_error": False,
        "reason_code": "capability_denied", "error_code": None, "duration_ms": 12,
        "request_source": "generated", "replay_safe": False,
    }
    payload = json.dumps(page)
    for secret in ("HASH-ENTRADA", "HASH-SALIDA", "ACTOR-SECRETO", "req-"):
        assert secret not in payload


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("denied", ["denied", "denied_old", "broken_ts"]),
        ("error", ["error", "flagged"]),
        ("in_progress", ["pending"]),
        ("all", ["ok", "denied", "error", "flagged", "pending", "denied_old", "broken_ts"]),
    ],
)
def test_mcp_status_filters(conn, data, status, expected):
    page = governance.list_mcp_invocations(conn, "mi-proyecto", status=status)
    assert [item["id"] for item in page["items"]] == [data[name] for name in expected]


@pytest.mark.parametrize("limit", [1, 2, 3])
def test_pagination_has_no_gaps_or_duplicates(conn, data, limit):
    # Empate de instante con offsets distintos: el id decide.
    tie = _invocation(conn, "mi-proyecto", "2026-06-14T08:00:00-03:00", "denied", reason="x")
    conn.commit()
    seen, cursor = [], None
    while True:
        page = governance.list_mcp_invocations(conn, "mi-proyecto", status="all", limit=limit, cursor=cursor)
        _validate(page, "governance_mcp_invocations.schema.json")
        seen += [item["id"] for item in page["items"]]
        if page["next_cursor"] is None:
            break
        cursor = governance.parse_cursor(page["next_cursor"])
    all_rows = conn.execute("SELECT id, ts FROM mcp_invocations WHERE project = 'mi-proyecto'").fetchall()
    readable = sorted(((parse_instant(ts), row_id) for row_id, ts in all_rows if parse_instant(ts)), reverse=True)
    expected = [row_id for _, row_id in readable] + [data["broken_ts"]]
    assert seen == expected
    assert seen.index(tie) == seen.index(data["error"]) - 1  # 08:00-03:00 = 11:00Z: a igual instante, id mayor primero
    assert len(seen) == len(set(seen))


def test_egress_decisions_hide_runs_of_other_projects(conn):
    local_run = conn.execute("INSERT INTO runs (ts, project) VALUES ('2026-06-14T10:00:00Z', 'mi-proyecto')").lastrowid
    foreign_run = conn.execute("INSERT INTO runs (ts, project) VALUES ('2026-06-14T10:00:00Z', 'otro')").lastrowid
    first = _egress(conn, "mi-proyecto", "2026-06-14T10:00:00Z", run_id=local_run)
    second = _egress(conn, "mi-proyecto", "2026-06-14T11:00:00Z", decision="allowed", reason="ok", run_id=foreign_run)
    _egress(conn, "otro", "2026-06-14T12:00:00Z")
    conn.commit()
    page = governance.list_egress_decisions(conn, "mi-proyecto")
    _validate(page, "governance_egress_decisions.schema.json")
    assert [(item["id"], item["run_id"]) for item in page["items"]] == [(second, None), (first, local_run)]
    assert page["items"][1]["sel"] == f"decision:egress-{first}"


def test_summary_counts_the_period_by_reason_tool_and_agent(conn, data):
    _egress(conn, "mi-proyecto", "2026-06-14T10:00:00Z")
    _egress(conn, "mi-proyecto", "2026-06-14T10:00:00Z", decision="allowed", reason="ok")
    _egress(conn, "mi-proyecto", "2026-04-01T10:00:00Z")
    conn.commit()
    summary = governance.governance_summary(conn, "mi-proyecto", now=NOW, period="30d")
    _validate(summary, "governance_summary.schema.json")
    mcp = summary["mcp"]
    # 30 días: fuera quedan `denied_old` (1 de mayo, antes del 16) y el `ts` ilegible.
    assert (mcp["invocations"], mcp["denied"], mcp["error"], mcp["in_progress"]) == (5, 1, 2, 1)
    assert mcp["by_reason"] == [
        {"key": "capability_denied", "count": 1},
        {"key": "invalid_arguments", "count": 1},
        {"key": "sin código", "count": 1},
    ]
    assert mcp["by_tool"] == [{"key": "advance_step", "count": 2}, {"key": "list_steps", "count": 1}]
    assert mcp["by_agent"] == [{"key": "claude", "count": 2}, {"key": "codex", "count": 1}]
    assert summary["egress"] == {"total": 2, "blocked": 1,
                                 "by_reason": [{"key": "sensitivity_exceeds_clearance", "count": 1}]}
    wider = governance.governance_summary(conn, "mi-proyecto", now=NOW, period="90d")
    assert (wider["mcp"]["denied"], wider["egress"]["total"]) == (2, 3)


def test_summary_window_edges(conn):
    _invocation(conn, "mi-proyecto", "2026-06-08T12:00:00Z", "denied", reason="dentro")
    _invocation(conn, "mi-proyecto", "2026-06-08T08:59:59-03:00", "denied", reason="fuera")
    _invocation(conn, "mi-proyecto", "2026-06-15T12:00:00Z", "denied", reason="ahora")
    conn.commit()
    summary = governance.governance_summary(conn, "mi-proyecto", now=NOW, period="7d")
    assert summary["mcp"]["by_reason"] == [{"key": "dentro", "count": 1}]


@pytest.mark.parametrize("value", ["", "x", "0", "101", "1.5", "-1", "01"])
def test_bad_limits_are_rejected(value):
    with pytest.raises(ValueError):
        governance.parse_limit(value)


@pytest.mark.parametrize("value", ["", "abc", "1|0", "2461192.5", "2461192.5|", "|5", "2461192.5|x", "-|-1", "1e5|3"])
def test_bad_cursors_are_rejected(value):
    with pytest.raises(ValueError):
        governance.parse_cursor(value)


@pytest.fixture
def api(conn, data, monkeypatch):
    monkeypatch.setattr(governance, "_connection", lambda: conn)
    monkeypatch.setattr(governance, "_registered_projects", lambda: {"mi-proyecto", "vacio"})
    api_v1.discover()

    def get(path, **query):
        return api_v1.dispatch(Request("GET", path, query={k: [v] for k, v in query.items()}))

    return get


def test_endpoints_answer_through_the_registry(api, data):
    status, payload = api("/api/v1/projects/mi-proyecto/mcp-invocations", status="denied", limit="2")
    assert status == 200
    assert [item["id"] for item in payload["items"]] == [data["denied"], data["denied_old"]]
    status, more = api("/api/v1/projects/mi-proyecto/mcp-invocations", status="denied", limit="2",
                       cursor=payload["next_cursor"])
    assert (status, [item["id"] for item in more["items"]], more["next_cursor"]) == (200, [data["broken_ts"]], None)
    status, payload = api("/api/v1/projects/mi-proyecto/egress-decisions")
    assert (status, payload["items"]) == (200, [])
    status, payload = api("/api/v1/projects/mi-proyecto/governance/summary", period="7d")
    assert status == 200 and payload["period"]["key"] == "7d"
    assert api("/api/v1/projects/vacio/mcp-invocations")[1]["items"] == []


@pytest.mark.parametrize(
    ("path", "query", "expected"),
    [
        ("/api/v1/projects/desconocido/mcp-invocations", {}, 404),
        ("/api/v1/projects/desconocido/egress-decisions", {}, 404),
        ("/api/v1/projects/desconocido/governance/summary", {}, 404),
        ("/api/v1/projects/mi-proyecto/mcp-invocations", {"status": "raro"}, 400),
        ("/api/v1/projects/mi-proyecto/mcp-invocations", {"limit": "500"}, 400),
        ("/api/v1/projects/mi-proyecto/mcp-invocations", {"cursor": "nope"}, 400),
        ("/api/v1/projects/mi-proyecto/egress-decisions", {"cursor": "nope"}, 400),
        ("/api/v1/projects/mi-proyecto/governance/summary", {"period": "1y"}, 400),
    ],
)
def test_endpoint_errors(api, path, query, expected):
    status, payload = api(path, **query)
    assert status == expected
    if expected == 404:
        assert payload == {"error": "unknown project"}


def test_a_denial_recorded_with_is_error_counts_once_as_denied(conn):
    _invocation(conn, "mi-proyecto", "2026-06-14T10:00:00Z", "denied", is_error=1, reason="capability_denied")
    _invocation(conn, "mi-proyecto", "2026-06-14T10:00:00Z", "success", is_error=1, error_code="execution_error")
    conn.commit()
    mcp = governance.governance_summary(conn, "mi-proyecto", now=NOW, period="7d")["mcp"]
    assert (mcp["denied"], mcp["error"], mcp["invocations"]) == (1, 1, 2)
    assert mcp["by_reason"] == [{"key": "capability_denied", "count": 1}, {"key": "execution_error", "count": 1}]
    problems = governance.list_mcp_invocations(conn, "mi-proyecto")
    assert len(problems["items"]) == 2
    assert [item["id"] for item in governance.list_mcp_invocations(conn, "mi-proyecto", status="error")["items"]] \
        == [item["id"] for item in problems["items"]]
