import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from orchestrator.db import _conn, _write_lock, daily_cost


def _insert(project: str, ts: str, cost_usd: float) -> None:
    conn = _conn()
    with _write_lock:
        conn.execute(
            "INSERT INTO runs (ts, project, status, cost_usd) VALUES (?, ?, 'done', ?)",
            (ts, project, cost_usd),
        )
        conn.commit()


def test_daily_cost_sums_only_local_today(request):
    project = f"daily-cost-{request.node.name}"
    now_utc = datetime.now(timezone.utc)

    _insert(project, now_utc.isoformat(), 1.5)
    _insert(project, (now_utc - timedelta(hours=26)).isoformat(), 100.0)
    _insert(project, (now_utc + timedelta(hours=26)).isoformat(), 200.0)

    assert daily_cost(project) == 1.5


def test_daily_cost_never_reuses_a_frozen_tz_per_row(request, monkeypatch):
    """Regresion (ronda 3 de auditoria): local_date_from_ts en si mismo ya
    esta cubierto (test_timeutil.py), pero ningun test protegia al CALLER -
    si daily_cost() volviera a capturar un tzinfo congelado una sola vez
    (datetime.now().astimezone().tzinfo) y pasarlo por fila, ese es
    exactamente el bug real de DST que se corrigio. Este test falla si
    alguien reintroduce un segundo argumento en la llamada."""
    project = f"daily-cost-tz-{request.node.name}"
    now_utc = datetime.now(timezone.utc)
    _insert(project, now_utc.isoformat(), 1.0)

    calls: list[tuple] = []
    import orchestrator.timeutil as timeutil_module
    real = timeutil_module.local_date_from_ts

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr("orchestrator.timeutil.local_date_from_ts", spy)
    daily_cost(project)

    assert calls, "daily_cost no llamo a local_date_from_ts"
    for args, kwargs in calls:
        assert len(args) == 1 and not kwargs, (
            "daily_cost esta pasando un tz explicito a local_date_from_ts - "
            "eso reintroduce el bug de offset congelado que rompia con DST"
        )


def test_daily_cost_ignores_other_projects(request):
    project = f"daily-cost-iso-{request.node.name}"
    other = f"{project}-other"
    now_utc = datetime.now(timezone.utc)

    _insert(project, now_utc.isoformat(), 3.0)
    _insert(other, now_utc.isoformat(), 999.0)

    assert daily_cost(project) == 3.0


def test_daily_cost_no_runs_returns_zero(request):
    assert daily_cost(f"never-seen-{request.node.name}") == 0.0


def test_insert_or_ignore_race_lastrowid_points_elsewhere(request):
    """Prueba el patron SQL en aislamiento (una sola conexion, sin threads):
    tras un INSERT OR IGNORE ignorado (rowcount=0), lastrowid de esa conexion
    apunta a la ULTIMA fila que esa conexion inserto, no al registro real con
    ese session_id. git_scanner/watcher/codex_watcher deben resolver el
    run_id real via SELECT por session_id en ese caso. No ejercita ninguno de
    los tres importadores reales bajo una carrera real - para eso ver
    test_git_scanner.py::test_insert_or_ignore_race_indexes_correct_run_id
    (con threads reales, end-to-end)."""
    project = f"race-{request.node.name}"
    sid = f"race::{request.node.name}"
    conn = _conn()
    now = datetime.now(timezone.utc).isoformat()

    with _write_lock:
        cur_real = conn.execute(
            "INSERT INTO runs (ts, project, status, session_id) VALUES (?, ?, 'done', ?)",
            (now, project, sid),
        )
        real_id = cur_real.lastrowid
        conn.commit()

        # Insercion no relacionada en la MISMA conexion, deja lastrowid
        # apuntando a una fila ajena antes del reintento.
        cur_unrelated = conn.execute(
            "INSERT INTO runs (ts, project, status) VALUES (?, ?, 'done')",
            (now, project),
        )
        unrelated_id = cur_unrelated.lastrowid
        conn.commit()
        assert unrelated_id != real_id

        # Reintento del mismo session_id (lo que hace el scanner tras perder
        # una carrera con otro proceso): no inserta nada.
        cur_retry = conn.execute(
            "INSERT OR IGNORE INTO runs (ts, project, status, session_id) VALUES (?, ?, 'done', ?)",
            (now, project, sid),
        )
        assert cur_retry.rowcount == 0
        # El bug: confiar en lastrowid aca devolveria la fila ajena.
        assert cur_retry.lastrowid == unrelated_id

        # El fix: resolver por session_id en vez de lastrowid.
        resolved = conn.execute(
            "SELECT id FROM runs WHERE session_id=?", (sid,)
        ).fetchone()
        assert resolved["id"] == real_id


def test_migration_removes_mcp_result_payloads_from_existing_database(
    tmp_path, monkeypatch
):
    import orchestrator.db as db_module
    import orchestrator.paths as paths_module

    legacy_db_path = tmp_path / "legacy-runs.db"
    legacy_conn = sqlite3.connect(legacy_db_path)
    legacy_conn.executescript("""
        CREATE TABLE mcp_invocations (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            ts                  TEXT NOT NULL,
            request_id          TEXT NOT NULL UNIQUE,
            correlation_id      TEXT,
            server_instance_id  TEXT NOT NULL,
            client_surface      TEXT NOT NULL,
            transport           TEXT NOT NULL,
            actor_id            TEXT,
            capability_profile  TEXT NOT NULL,
            tool_name           TEXT NOT NULL,
            tool_category       TEXT NOT NULL,
            project             TEXT,
            input_hash          TEXT NOT NULL,
            output_hash         TEXT NOT NULL,
            result_json         TEXT,
            status              TEXT NOT NULL,
            reason_code         TEXT,
            duration_ms         INTEGER,
            error_code          TEXT,
            created_at          TEXT NOT NULL
        );
        INSERT INTO mcp_invocations (
            ts, request_id, server_instance_id, client_surface, transport,
            capability_profile, tool_name, tool_category, input_hash,
            output_hash, result_json, status, created_at
        ) VALUES (
            '2026-01-01T00:00:00+00:00', 'legacy-request', 'server',
            'client', 'stdio', 'workflow_operator', 'create_context',
            'mutation', 'input-hash', 'output-hash', '{"secret":"MCP_OUTPUT_SECRET_do_not_retain"}', 'success',
            '2026-01-01T00:00:00+00:00'
        );
    """)
    legacy_conn.close()

    monkeypatch.setattr(paths_module, "HOME_DIR", tmp_path)
    monkeypatch.setattr(paths_module, "DB_PATH", legacy_db_path)
    monkeypatch.setattr(db_module, "_local", threading.local())

    db_module.init_db()
    conn = db_module._conn()
    try:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(mcp_invocations)")
        }
        assert "result_json" not in columns
        assert {"is_error", "request_source", "replay_safe"} <= columns

        row = conn.execute(
            """SELECT is_error, request_source, replay_safe
               FROM mcp_invocations WHERE request_id = 'legacy-request'"""
        ).fetchone()
        assert dict(row) == {
            "is_error": 0,
            "request_source": "generated",
            "replay_safe": 0,
        }
        assert "MCP_OUTPUT_SECRET_do_not_retain" not in "\n".join(
            str(value) for value in conn.execute(
                "SELECT * FROM mcp_invocations WHERE request_id = 'legacy-request'"
            ).fetchone()
        )
        assert conn.execute(
            "SELECT output_hash FROM mcp_invocations WHERE request_id = 'legacy-request'"
        ).fetchone()["output_hash"] == "redacted"
    finally:
        conn.close()


def test_migration_recovers_interrupted_mcp_payload_rebuild(tmp_path, monkeypatch):
    import orchestrator.db as db_module
    import orchestrator.paths as paths_module

    legacy_db_path = tmp_path / "interrupted-runs.db"
    legacy_conn = sqlite3.connect(legacy_db_path)
    legacy_conn.executescript("""
        CREATE TABLE _migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
        CREATE TABLE mcp_invocations_without_payload (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
            request_id TEXT NOT NULL UNIQUE, correlation_id TEXT,
            server_instance_id TEXT NOT NULL, client_surface TEXT NOT NULL,
            transport TEXT NOT NULL, actor_id TEXT, capability_profile TEXT NOT NULL,
            tool_name TEXT NOT NULL, tool_category TEXT NOT NULL, project TEXT,
            input_hash TEXT NOT NULL, output_hash TEXT NOT NULL,
            is_error INTEGER NOT NULL DEFAULT 0,
            request_source TEXT NOT NULL DEFAULT 'generated',
            replay_safe INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL,
            reason_code TEXT, duration_ms INTEGER, error_code TEXT, created_at TEXT NOT NULL
        );
        INSERT INTO mcp_invocations_without_payload (
            ts, request_id, server_instance_id, client_surface, transport,
            capability_profile, tool_name, tool_category, input_hash, output_hash,
            status, created_at
        ) VALUES (
            '2026-01-01T00:00:00+00:00', 'interrupted-request', 'server',
            'client', 'stdio', 'workflow_operator', 'create_context',
            'mutation', 'input-hash', 'legacy-plain-output-hash', 'success',
            '2026-01-01T00:00:00+00:00'
        );
    """)
    legacy_conn.close()

    monkeypatch.setattr(paths_module, "HOME_DIR", tmp_path)
    monkeypatch.setattr(paths_module, "DB_PATH", legacy_db_path)
    monkeypatch.setattr(db_module, "_local", threading.local())

    db_module.init_db()
    conn = db_module._conn()
    try:
        assert conn.execute(
            "SELECT request_id FROM mcp_invocations"
        ).fetchone()["request_id"] == "interrupted-request"
        assert conn.execute(
            "SELECT output_hash FROM mcp_invocations"
        ).fetchone()["output_hash"] == "redacted"
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mcp_invocations_without_payload'"
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM _migrations WHERE name='remove_mcp_result_payloads'"
        ).fetchone() is not None
        assert conn.execute(
            "SELECT 1 FROM _migrations WHERE name='redact_legacy_mcp_output_hashes'"
        ).fetchone() is not None
    finally:
        conn.close()
