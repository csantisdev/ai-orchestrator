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


@pytest.fixture
def conn(monkeypatch):
    from orchestrator import db
    result = sqlite3.connect(":memory:")
    result.row_factory = sqlite3.Row
    for (sql,) in db._conn().execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%'"
    ).fetchall():
        result.execute(sql)
    local = threading.local()
    local.conn = result
    monkeypatch.setattr(db, "_local", local)
    context = result.execute("INSERT INTO contexts(ts, updated_at, project, title, status, metadata) VALUES ('2026-06-01T12:00:00-03:00','2026-06-01T12:00:00-03:00','mi-proyecto','x','active','{}')").lastrowid
    result.execute("INSERT INTO steps(context_id,order_idx,title,status,started_at) VALUES (?,1,'x','in_progress','2026-06-01T12:00:00Z')", (context,))
    result.execute("INSERT INTO runs(ts,project,status,cost_usd) VALUES ('2026-06-14T10:00:00-03:00','mi-proyecto','done',2.5)")
    result.execute("INSERT INTO runs(ts,project,status,cost_usd) VALUES ('2026-06-14T10:00:00Z','otro-proyecto','done',9)")
    result.execute("INSERT INTO mcp_invocations(ts,request_id,server_instance_id,client_surface,transport,capability_profile,tool_name,tool_category,project,input_hash,output_hash,status,created_at) VALUES ('2026-06-15T11:00:00Z','a','x','codex_cli','stdio','readonly','x','append','mi-proyecto','x','x','success','2026-06-15T11:00:00Z')")
    result.execute("INSERT INTO mcp_invocations(ts,request_id,server_instance_id,client_surface,transport,capability_profile,tool_name,tool_category,project,input_hash,output_hash,status,is_error,reason_code,created_at) VALUES ('2026-06-14T11:00:00Z','b','x','claude_code','stdio','readonly','x','read','mi-proyecto','x','x','denied',1,'capability_denied','2026-06-14T11:00:00Z')")
    result.commit()
    yield result
    result.close()


def overview(conn):
    return build_overview(conn, "mi-proyecto", registered={"mi-proyecto"}, now=NOW)


def metric(payload, name): return next(item for item in payload["metrics"] if item["id"] == name)


def test_metrics_match_independent_queries(conn):
    payload = overview(conn)
    assert metric(payload, "active_contexts")["value"] == conn.execute("SELECT COUNT(*) FROM contexts WHERE project='mi-proyecto' AND status='active'").fetchone()[0]
    assert metric(payload, "steps_in_progress")["value"] == conn.execute("SELECT COUNT(*) FROM steps WHERE status='in_progress'").fetchone()[0]
    assert metric(payload, "agent_activity_24h")["value"] == 1
    assert metric(payload, "mcp_denied_or_error")["value"] == 1
    assert metric(payload, "cost_period")["value"] == 2.5
    assert metric(payload, "tracking_health")["value"] == 1


def test_schema_and_no_run_text(conn):
    payload = overview(conn)
    schema = json.loads((Path(__file__).parents[1] / "orchestrator/schemas/home_overview.schema.json").read_text())
    jsonschema.validate(payload, schema)
    encoded = json.dumps(payload)
    assert "task" not in encoded and "response" not in encoded


def test_unknown_project_and_bad_period(conn):
    assert build_overview(conn, "no", registered=set(), now=NOW)["_unknown"]
    with pytest.raises(ValueError, match="period"):
        build_overview(conn, "mi-proyecto", registered={"mi-proyecto"}, now=NOW, period="1y")


def test_dispatch_registers_the_vertical(conn):
    from orchestrator import api_v1
    api_v1.discover()
    status, payload = api_v1.dispatch(api_v1.Request("GET", "/api/v1/projects/mi-proyecto/overview"))
    assert status == 200
    assert payload["project"] == "mi-proyecto"
