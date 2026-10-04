from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from orchestrator.api_v1.home import build_overview

NOW = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
PROJECT = "mi-proyecto"
OTHER_PROJECT = "otro-proyecto"


@pytest.fixture
def conn(monkeypatch):
    from orchestrator import db

    result = sqlite3.connect(":memory:")
    result.row_factory = sqlite3.Row
    tables = db._conn().execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%'"
    ).fetchall()
    for (sql,) in tables:
        result.execute(sql)
    local = threading.local()
    local.conn = result
    monkeypatch.setattr(db, "_local", local)
    yield result
    result.close()


def insert_context(conn, project, status="active"):
    return conn.execute(
        "INSERT INTO contexts(ts, updated_at, project, title, status, metadata) "
        "VALUES (?, ?, ?, 'contexto', ?, '{}')",
        ("2026-06-01T12:00:00Z", "2026-06-01T12:00:00Z", project, status),
    ).lastrowid


def insert_step(conn, context_id, index, status, started_at=None):
    return conn.execute(
        "INSERT INTO steps(context_id, order_idx, title, status, started_at) "
        "VALUES (?, ?, 'paso', ?, ?)",
        (context_id, index, status, started_at),
    ).lastrowid


def insert_run(conn, project, ts, cost, step_id=None):
    conn.execute(
        "INSERT INTO runs(ts, project, status, task, cost_usd, step_id) "
        "VALUES (?, ?, 'done', 'x', ?, ?)",
        (ts, project, cost, step_id),
    )


def insert_invocation(conn, project, request_id, ts, surface, category, status, error=0, reason=None):
    conn.execute(
        "INSERT INTO mcp_invocations("
        "ts, request_id, server_instance_id, client_surface, transport, "
        "capability_profile, tool_name, tool_category, project, input_hash, "
        "output_hash, status, is_error, reason_code, created_at) "
        "VALUES (?, ?, 'server', ?, 'stdio', 'readonly', 'tool', ?, ?, 'in', "
        "'out', ?, ?, ?, ?)",
        (ts, request_id, surface, category, project, status, error, reason, ts),
    )


def insert_egress(conn, project, ts):
    conn.execute(
        "INSERT INTO egress_decisions("
        "ts, project, provider, phase, decision, reason_code) "
        "VALUES (?, ?, 'codex', 'before', 'allowed', 'ok')",
        (ts, project),
    )


@pytest.fixture
def populated(conn):
    for project in (PROJECT, OTHER_PROJECT):
        context_id = insert_context(conn, project)
        insert_step(conn, context_id, 1, "in_progress", "2026-06-01T12:00:00Z")
        current_step = insert_step(
            conn,
            context_id,
            2,
            "in_progress",
            "2026-06-15T11:00:00Z",
        )
        insert_step(conn, context_id, 3, "completed")
        insert_step(conn, context_id, 4, "skipped")
        insert_run(conn, project, "2026-06-14T09:00:00-03:00", 2.5, current_step)
        insert_invocation(
            conn, project, f"{project}-activity", "2026-06-15T11:30:00Z",
            "claude_code", "append", "success",
        )
        insert_egress(conn, project, "2026-06-15T10:00:00Z")
    insert_invocation(
        conn, PROJECT, "denied", "2026-06-14T11:00:00Z", "codex_cli",
        "read", "denied", 1, "capability_denied",
    )
    conn.commit()
    return conn


def overview(conn, period="7d"):
    return build_overview(
        conn,
        PROJECT,
        registered={PROJECT, OTHER_PROJECT},
        now=NOW,
        period=period,
    )


def metric(payload, name):
    return next(item for item in payload["metrics"] if item["id"] == name)


def detail(item):
    return {entry["label"]: entry["value"] for entry in item["detail"]}


def test_active_contexts_metric_matches_project_query(populated):
    payload = overview(populated)
    expected = populated.execute(
        "SELECT COUNT(*) FROM contexts WHERE project = ? AND status = 'active'",
        (PROJECT,),
    ).fetchone()[0]
    assert metric(payload, "active_contexts")["value"] == expected


def test_steps_in_progress_metric_matches_project_query(populated):
    payload = overview(populated)
    expected = populated.execute(
        "SELECT COUNT(*) FROM steps s JOIN contexts c ON c.id = s.context_id "
        "WHERE c.project = ? AND s.status = 'in_progress'",
        (PROJECT,),
    ).fetchone()[0]
    assert metric(payload, "steps_in_progress")["value"] == expected


def test_stale_steps_metric_uses_the_stale_threshold(populated):
    payload = overview(populated)
    expected = populated.execute(
        "SELECT COUNT(*) FROM steps s JOIN contexts c ON c.id = s.context_id "
        "WHERE c.project = ? AND s.status = 'in_progress' "
        "AND s.started_at < '2026-06-08T12:00:00+00:00'",
        (PROJECT,),
    ).fetchone()[0]
    assert metric(payload, "stale_steps")["value"] == expected == 1


def test_agent_activity_metric_filters_window_project_and_reads(populated):
    insert_invocation(
        populated, PROJECT, "codex", "2026-06-15T08:30:00-03:00",
        "codex_cli", "append", "success",
    )
    insert_invocation(
        populated, PROJECT, "outside", "2026-06-14T11:59:59Z",
        "claude_code", "append", "success",
    )
    insert_invocation(
        populated, PROJECT, "invalid", "not-a-date", "claude_code", "append", "success",
    )
    populated.commit()
    item = metric(overview(populated), "agent_activity_24h")
    assert item["value"] == 2
    assert detail(item) == {"claude": 1, "codex": 1}


def test_denials_metric_counts_errors_and_reason_codes(populated):
    insert_invocation(
        populated, PROJECT, "error", "2026-06-14T12:00:00Z", "codex_cli",
        "append", "success", 1,
    )
    populated.commit()
    item = metric(overview(populated), "mcp_denied_or_error")
    assert item["value"] == 2
    assert detail(item) == {"capability_denied": 1, "sin código": 1}


def test_cost_metric_ignores_invalid_costs_and_counts_attributed_runs(populated):
    for cost in (None, -1, float("nan"), float("inf")):
        insert_run(populated, PROJECT, "2026-06-10T12:00:00Z", cost)
    insert_run(populated, PROJECT, "2026-06-08T11:59:59Z", 99)
    populated.commit()
    item = metric(overview(populated), "cost_period")
    assert item["value"] == 2.5
    assert detail(item) == {"runs": 5, "runs atribuidos a un paso": 1}


def test_tracking_health_metric_and_data_quality_are_project_scoped(populated):
    payload = overview(populated)
    warnings = payload["tracking_health"]["warnings"]
    assert metric(payload, "tracking_health")["value"] == len(warnings)
    assert payload["tracking_health"]["data_quality"] == {
        "completed_without_start": 1,
        "skipped": 1,
    }
    assert {warning["code"] for warning in payload["alerts"]} == set()
    assert all(warning["code"] != "stale_in_progress_step" for warning in payload["alerts"])


def test_period_boundaries_and_offsets_are_applied_independently(populated):
    insert_run(populated, PROJECT, "2026-06-08T12:00:00Z", 7)
    insert_run(populated, PROJECT, "2026-06-08T11:59:59Z", 70)
    insert_run(populated, PROJECT, "2026-05-16T12:00:00", 30)
    insert_run(populated, PROJECT, "2026-05-16T11:59:59Z", 300)
    populated.commit()
    assert metric(overview(populated, "7d"), "cost_period")["value"] == 9.5
    assert metric(overview(populated, "30d"), "cost_period")["value"] == 109.5


def test_egress_available_is_scoped_to_the_project(populated):
    payload = overview(populated)
    assert payload["egress"]["state"] == "available"
    assert payload["egress"]["count"] == 1


def test_schema_uses_a_format_checker(populated):
    payload = overview(populated)
    schema_path = Path(__file__).parents[1] / "orchestrator/schemas/home_overview.schema.json"
    schema = json.loads(schema_path.read_text())
    format_checker = jsonschema.Draft202012Validator.FORMAT_CHECKER

    @format_checker.checks("date-time")
    def is_date_time(value):
        if not isinstance(value, str):
            return True
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True

    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=format_checker,
    )
    validator.validate(payload)
    payload["generated_at"] = "not-a-date-time"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(payload)


def test_unknown_project_and_bad_period(conn):
    assert build_overview(conn, "no", registered=set(), now=NOW) is None
    with pytest.raises(ValueError, match="period"):
        build_overview(conn, PROJECT, registered={PROJECT}, now=NOW, period="1y")


def test_dispatch_registers_the_vertical(populated):
    from orchestrator import api_v1

    api_v1.discover()
    status, payload = api_v1.dispatch(api_v1.Request("GET", "/api/v1/projects/mi-proyecto/overview"))
    assert status == 200
    assert payload["project"] == PROJECT


def test_dispatch_returns_404_for_unknown_and_400_for_bad_period(populated):
    from orchestrator import api_v1

    api_v1.discover()
    status, payload = api_v1.dispatch(api_v1.Request("GET", "/api/v1/projects/no/overview"))
    assert (status, payload) == (404, {"error": "unknown project"})
    status, payload = api_v1.dispatch(
        api_v1.Request(
            "GET",
            "/api/v1/projects/mi-proyecto/overview",
            query={"period": ["1y"]},
        )
    )
    assert (status, payload) == (400, {"error": "period must be '7d' or '30d'"})


def test_project_with_context_but_without_runs_is_known(conn):
    insert_context(conn, "solo-contexto")
    conn.commit()
    assert build_overview(conn, "solo-contexto", registered=set(), now=NOW)["project"] == "solo-contexto"
