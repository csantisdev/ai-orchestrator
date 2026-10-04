"""Contratos de la vertical Ejecuciones sobre una base sintética."""

from datetime import datetime, timezone
import json
import math
from pathlib import Path

import jsonschema
import pytest

from orchestrator import api_v1
from orchestrator.api_v1 import Request, runs
from orchestrator.git_scanner import PROVIDER_NAME as GIT_PROVIDER
from tests.test_api_work import _context, _empty_db, _run, _step

SCHEMAS = Path(runs.__file__).resolve().parent.parent / "schemas"


def validate(instance, name):
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    jsonschema.validate(instance, schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)


@pytest.fixture
def data():
    conn = _empty_db()
    context = _context(conn, "mi-proyecto", "Contexto", "active", "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z")
    step = _step(conn, context, 1, "Paso", "in_progress")
    foreign = _context(conn, "otro-proyecto", "Ajeno", "active", "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z")
    foreign_step = _step(conn, foreign, 1, "Paso ajeno", "in_progress")
    ids = [
        _run(conn, "mi-proyecto", "2026-05-10T10:00:00-03:00", provider="claude", session_id="s", step_id=step, cost_usd=1.1, task_preview="sesión"),
        _run(conn, "mi-proyecto", "2026-05-10T13:00:00Z", provider="router", cost_usd=2.2, task_preview="router"),
        _run(conn, "mi-proyecto", "2026-05-10T13:00:00Z", provider=GIT_PROVIDER, session_id="git::mi-proyecto::a", cost_usd=3.3, task_preview="commit"),
        _run(conn, "mi-proyecto", "2026-05-09T12:00:00", provider="claude", step_id=foreign_step, cost_usd=-1, task_preview="ajeno"),
        _run(conn, "mi-proyecto", "inválido", provider="router", cost_usd=None, task_preview="malo"),
    ]
    conn.commit()
    yield conn, ids, step
    conn.close()


@pytest.mark.parametrize("limit", [1, 2, 3])
def test_pagination_is_complete_and_sql_ordered(data, limit):
    conn, ids, _ = data
    cursor = None
    found = []
    while True:
        page = runs.list_runs(conn, "mi-proyecto", limit=limit, cursor=cursor)
        found.extend(item["id"] for item in page["runs"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    expected = [row[0] for row in conn.execute(
        "SELECT id FROM runs WHERE project = ? "
        "ORDER BY julianday(ts) IS NULL, julianday(ts) DESC, id DESC", ("mi-proyecto",)
    )]
    assert found == expected and len(found) == len(set(found))


@pytest.mark.parametrize("source, expected", [
    ("router", "router"), ("session", "session"), ("commit", "commit"),
])
def test_source_filters_and_dto_privacy(data, source, expected):
    conn, _, _ = data
    page = runs.list_runs(conn, "mi-proyecto", source=source)
    validate(page, "runs_page.schema.json")
    assert page["runs"] and {item["source"] for item in page["runs"]} == {expected}
    assert all("task" not in item and "response" not in item and "session_id" not in item for item in page["runs"])


@pytest.mark.parametrize("cursor", ["bad", "1|0", "nan|1", "-|0", "1|x"])
def test_invalid_cursor_and_limits_are_rejected(data, cursor):
    conn, _, _ = data
    with pytest.raises(ValueError):
        runs.list_runs(conn, "mi-proyecto", cursor=cursor)
    with pytest.raises(ValueError):
        runs.list_runs(conn, "mi-proyecto", limit=101)


def test_costs_use_half_open_window_and_only_project_context(data):
    conn = _empty_db()
    context = _context(conn, "mi-proyecto", "Contexto", "active", "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z")
    step = _step(conn, context, 1, "Paso", "in_progress")
    _run(conn, "mi-proyecto", "2026-05-03T00:00:00Z", provider="claude", step_id=step, cost_usd=0.12345678)
    _run(conn, "mi-proyecto", "2026-05-10T00:00:00Z", provider="claude", cost_usd=9)
    _run(conn, "mi-proyecto", "2026-05-04T00:00:00Z", provider="claude", cost_usd=float("nan"))
    result = runs.costs(conn, "mi-proyecto", "7d", now=datetime(2026, 5, 10, tzinfo=timezone.utc))
    validate(result, "runs_costs.schema.json")
    assert result["totals"]["cost_usd"] == 0.123457
    assert result["totals"]["runs"] == 2
    assert result["totals"]["runs_with_cost"] == 1
    assert len(result["daily"]) == 8
    conn.close()


def test_dispatch_returns_400_for_bad_limit_and_routes_exist(monkeypatch, data):
    conn, _, _ = data
    monkeypatch.setattr("orchestrator.db._conn", lambda: conn)
    monkeypatch.setattr(runs, "registered_projects", lambda: {"mi-proyecto"})
    api_v1.discover()
    status, body = api_v1.dispatch(Request("GET", "/api/v1/projects/mi-proyecto/runs", query={"limit": ["no"]}))
    assert status == 400 and "limit" in body["error"]
    status, _ = api_v1.dispatch(Request("GET", "/api/v1/projects/desconocido/costs"))
    assert status == 404
