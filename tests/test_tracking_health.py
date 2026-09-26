from datetime import datetime, timedelta, timezone
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
    return db_mod


def _warnings(db, registered=(), **kwargs):
    from orchestrator.tracking_health import tracking_health_warnings

    now = datetime(2026, 1, 30, tzinfo=timezone.utc)
    return tracking_health_warnings(db._conn(), registered, now=now, **kwargs)


def _codes(warnings):
    return [warning["code"] for warning in warnings]


def test_tracking_health_reports_multiple_active_contexts(isolated_db):
    isolated_db.insert_context("demo", "First")
    isolated_db.insert_context("demo", "Second")

    warnings = _warnings(isolated_db, {"demo"})

    assert _codes(warnings) == ["multiple_active_contexts"]


def test_tracking_health_reports_unregistered_active_and_scheduled_contexts(isolated_db):
    isolated_db.insert_context("missing-active", "Active")
    isolated_db.insert_context("missing-scheduled", "Scheduled", status="programado")

    warnings = _warnings(isolated_db, set())

    assert _codes(warnings) == ["context_project_unregistered", "context_project_unregistered"]


def test_tracking_health_reports_active_context_with_pending_steps(isolated_db):
    context_id = isolated_db.insert_context("demo", "Waiting")
    isolated_db.insert_step(context_id, 1, "Pending")

    warnings = _warnings(isolated_db, {"demo"})

    assert _codes(warnings) == ["no_step_in_progress"]
    assert "start_step" in warnings[0]["hint"]


def test_tracking_health_reports_stale_in_progress_step(isolated_db):
    context_id = isolated_db.insert_context("demo", "Stale")
    step_id = isolated_db.insert_step(context_id, 1, "Work")
    isolated_db.start_step(step_id)
    old = (datetime(2026, 1, 30, tzinfo=timezone.utc) - timedelta(days=8)).isoformat()
    isolated_db._conn().execute("UPDATE steps SET started_at=? WHERE id=?", (old, step_id))
    isolated_db._conn().commit()

    warnings = _warnings(isolated_db, {"demo"}, stale_in_progress_days=7)

    assert _codes(warnings) == ["stale_in_progress_step"]
    assert "reset_step" in warnings[0]["hint"]


def test_tracking_health_uses_step_events_as_recent_activity(isolated_db):
    context_id = isolated_db.insert_context("demo", "Current")
    step_id = isolated_db.insert_step(context_id, 1, "Work")
    isolated_db.start_step(step_id)
    old = (datetime(2026, 1, 30, tzinfo=timezone.utc) - timedelta(days=8)).isoformat()
    recent = (datetime(2026, 1, 30, tzinfo=timezone.utc) - timedelta(days=1)).isoformat()
    isolated_db._conn().execute("UPDATE steps SET started_at=? WHERE id=?", (old, step_id))
    isolated_db._conn().execute(
        """INSERT INTO alignments (ts, step_id, context_id, agent, confirmed, checkpoint, message)
           VALUES (?, ?, ?, '', 1, '', '')""",
        (recent, step_id, context_id),
    )
    isolated_db._conn().commit()

    assert _warnings(isolated_db, {"demo"}, stale_in_progress_days=7) == []


def test_tracking_health_does_not_count_project_mcp_reads_as_step_activity(isolated_db):
    context_id = isolated_db.insert_context("demo", "Stale")
    step_id = isolated_db.insert_step(context_id, 1, "Work")
    isolated_db.start_step(step_id)
    old = (datetime(2026, 1, 30, tzinfo=timezone.utc) - timedelta(days=8)).isoformat()
    recent = (datetime(2026, 1, 30, tzinfo=timezone.utc) - timedelta(days=1)).isoformat()
    isolated_db._conn().execute("UPDATE steps SET started_at=? WHERE id=?", (old, step_id))
    isolated_db._conn().execute(
        """INSERT INTO mcp_invocations (ts, request_id, server_instance_id, client_surface,
           transport, capability_profile, tool_name, tool_category, input_hash, output_hash, status, created_at)
           VALUES (?, 'read-1', 'server', 'codex_cli', 'stdio', 'readonly', 'get_context', 'read', 'a', 'b', 'success', ?)""",
        (recent, recent),
    )
    isolated_db._conn().commit()

    assert _codes(_warnings(isolated_db, {"demo"}, stale_in_progress_days=7)) == ["stale_in_progress_step"]


def test_tracking_health_reports_stale_scheduled_context(isolated_db):
    context_id = isolated_db.insert_context("demo", "Later", status="programado")
    old = (datetime(2026, 1, 30, tzinfo=timezone.utc) - timedelta(days=61)).isoformat()
    isolated_db._conn().execute("UPDATE contexts SET ts=? WHERE id=?", (old, context_id))
    isolated_db._conn().commit()

    warnings = _warnings(isolated_db, {"demo"}, stale_scheduled_days=60)

    assert _codes(warnings) == ["stale_scheduled_context"]


def test_tracking_health_is_silent_for_healthy_context(isolated_db):
    context_id = isolated_db.insert_context("demo", "Healthy")
    step_id = isolated_db.insert_step(context_id, 1, "Work")
    isolated_db.start_step(step_id)

    assert _warnings(isolated_db, {"demo"}) == []


def test_tracking_health_uses_linked_runs_as_recent_activity(isolated_db):
    context_id = isolated_db.insert_context("demo", "Current")
    step_id = isolated_db.insert_step(context_id, 1, "Work")
    isolated_db.start_step(step_id)
    old = (datetime(2026, 1, 30, tzinfo=timezone.utc) - timedelta(days=8)).isoformat()
    recent = (datetime(2026, 1, 30, tzinfo=timezone.utc) - timedelta(days=1)).isoformat()
    isolated_db._conn().execute("UPDATE steps SET started_at=? WHERE id=?", (old, step_id))
    isolated_db._conn().execute(
        "INSERT INTO runs (ts, project, step_id) VALUES (?, 'demo', ?)",
        (recent, step_id),
    )
    isolated_db._conn().commit()

    assert _warnings(isolated_db, {"demo"}, stale_in_progress_days=7) == []


def test_tracking_health_limits_warnings_to_selected_project(isolated_db):
    isolated_db.insert_context("demo", "First")
    isolated_db.insert_context("demo", "Second")
    isolated_db.insert_context("other", "First")
    isolated_db.insert_context("other", "Second")
    isolated_db.insert_context("missing", "Unregistered")

    warnings = _warnings(isolated_db, {"demo", "other"}, project="demo")

    assert _codes(warnings) == ["multiple_active_contexts"]
    assert warnings[0]["message"].startswith("demo:")


def test_tracking_health_uses_run_end_time_as_activity(isolated_db):
    context_id = isolated_db.insert_context("demo", "Long session")
    step_id = isolated_db.insert_step(context_id, 1, "Work")
    isolated_db.start_step(step_id)
    old = (datetime(2026, 1, 30, tzinfo=timezone.utc) - timedelta(days=10)).isoformat()
    isolated_db._conn().execute("UPDATE steps SET started_at=? WHERE id=?", (old, step_id))
    isolated_db._conn().execute(
        "INSERT INTO runs (ts, project, step_id, duration_ms) VALUES (?, 'demo', ?, ?)",
        (old, step_id, int(timedelta(days=9).total_seconds() * 1000)),
    )
    isolated_db._conn().commit()

    assert _warnings(isolated_db, {"demo"}, stale_in_progress_days=7) == []
