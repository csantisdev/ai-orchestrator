"""Esquema de RFC-010 (PR 1): versiones con triggers, tablas nuevas y upgrade desde una base vieja."""

import re
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import pytest

TS = "2026-01-01T00:00:00+00:00"
NEW_TABLES = {"projects", "project_identities", "ui_commands", "ui_command_attempts", "jobs",
              "durable_intents", "budget_reservations"}
ROOT = Path(__file__).resolve().parent.parent


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


def _tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _command(conn, request_id="r1", status="ok"):
    conn.execute(
        "INSERT INTO ui_commands (request_id, command, category, capability_profile, input_hash, status, created_at, updated_at)"
        " VALUES (?, 'close_context', 'workflow_transition', 'workflow_operator', 'h', ?, ?, ?)",
        (request_id, status, TS, TS))


def _legacy_database(path):
    conn = sqlite3.connect(path)
    # Base anterior: contextos y pasos ya creados por sus migraciones, sin `version`.
    conn.executescript(f"""
        CREATE TABLE _migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
        INSERT INTO _migrations VALUES ('create_contexts_table', '{TS}'), ('create_steps_table', '{TS}');
        CREATE TABLE contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, updated_at TEXT NOT NULL,
            project TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active', metadata TEXT NOT NULL DEFAULT '{{}}');
        CREATE TABLE steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT, context_id INTEGER NOT NULL REFERENCES contexts(id),
            order_idx INTEGER NOT NULL, title TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending', provider TEXT NOT NULL DEFAULT '',
            started_at TEXT, completed_at TEXT, notes TEXT NOT NULL DEFAULT '');
        INSERT INTO contexts (ts, updated_at, project, title) VALUES ('{TS}', '{TS}', 'mi-proyecto', 'viejo');
        INSERT INTO steps (context_id, order_idx, title) VALUES (1, 1, 'paso viejo');
    """)
    conn.commit()
    conn.close()


def _point_to(monkeypatch, tmp_path, db_path):
    import orchestrator.db as db_mod
    import orchestrator.paths as paths_mod

    monkeypatch.setattr(paths_mod, "HOME_DIR", tmp_path)
    monkeypatch.setattr(paths_mod, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "_local", threading.local())
    return db_mod


def test_upgrade_from_a_database_without_the_rfc010_schema(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy-runs.db"
    _legacy_database(legacy)
    db_mod = _point_to(monkeypatch, tmp_path, legacy)
    db_mod.init_db()
    conn = db_mod._conn()
    try:
        assert NEW_TABLES <= _tables(conn)
        assert conn.execute("SELECT version FROM contexts WHERE id = 1").fetchone()[0] == 1
        assert conn.execute("SELECT version FROM steps WHERE id = 1").fetchone()[0] == 1
        assert conn.execute("SELECT title FROM steps WHERE id = 1").fetchone()[0] == "paso viejo"
        assert conn.execute("SELECT 1 FROM _migrations WHERE name = 'rfc010_command_schema'").fetchone()
        # Volver a migrar no rompe ni duplica nada.
        from orchestrator.migrate import run_migrations

        run_migrations()
        assert conn.execute("SELECT version FROM contexts WHERE id = 1").fetchone()[0] == 1
    finally:
        conn.close()


def test_a_failure_in_the_middle_leaves_the_old_schema_intact(tmp_path, monkeypatch):
    import orchestrator.migrate as migrate

    legacy = tmp_path / "legacy-runs.db"
    _legacy_database(legacy)
    db_mod = _point_to(monkeypatch, tmp_path, legacy)
    real = migrate._run_script
    calls = []

    def fail_on_tables(conn, script):
        calls.append(script)
        if script is migrate.RFC010_TABLES:
            raise sqlite3.OperationalError("falla inyectada")
        real(conn, script)

    monkeypatch.setattr(migrate, "_run_script", fail_on_tables)
    with pytest.raises(sqlite3.OperationalError, match="falla inyectada"):
        db_mod.init_db()
    check = sqlite3.connect(legacy)
    try:
        assert "version" not in {row[1] for row in check.execute("PRAGMA table_info(contexts)")}
        assert not (NEW_TABLES & _tables(check))
        assert not check.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'trg_%version%'").fetchone()
        assert not check.execute("SELECT 1 FROM _migrations WHERE name = 'rfc010_command_schema'").fetchone()
    finally:
        check.close()


def test_the_migration_waits_for_another_writer(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy-runs.db"
    _legacy_database(legacy)
    holder = sqlite3.connect(legacy, check_same_thread=False)
    holder.execute("PRAGMA journal_mode=WAL")
    holder.execute("BEGIN IMMEDIATE")
    releaser = threading.Timer(1.0, holder.commit)
    releaser.start()
    db_mod = _point_to(monkeypatch, tmp_path, legacy)
    started = time.monotonic()
    db_mod.init_db()
    releaser.join()
    holder.close()
    assert time.monotonic() - started >= 0.9
    assert db_mod._conn().execute("SELECT 1 FROM _migrations WHERE name = 'rfc010_command_schema'").fetchone()


def _version(conn, table, row_id):
    return conn.execute(f"SELECT version FROM {table} WHERE id = ?", (row_id,)).fetchone()[0]


def test_any_mutation_bumps_the_version_exactly_once(isolated_db):
    import orchestrator.mcp as mcp

    conn = isolated_db._conn()
    ctx = isolated_db.insert_context("mi-proyecto", "Título")
    step = isolated_db.insert_step(ctx, 1, "Paso")
    other = isolated_db.insert_step(ctx, 2, "Otro")
    assert (_version(conn, "contexts", ctx), _version(conn, "steps", step)) == (1, 1)

    # Vía MCP.
    mcp._tool_update_step({"step_id": step, "notes": "nuevas"})
    assert _version(conn, "steps", step) == 2
    # SQL directo (CLI, reparación a mano): una sola vez por UPDATE, también si es masivo.
    conn.execute("UPDATE steps SET title = 'Otro', notes = 'x' WHERE id = ?", (step,))
    conn.execute("UPDATE steps SET status = 'pending' WHERE context_id = ?", (ctx,))
    conn.commit()
    assert (_version(conn, "steps", step), _version(conn, "steps", other)) == (4, 2)
    # UPSERT sobre una fila existente es un UPDATE: también sube.
    conn.execute("INSERT INTO steps (id, context_id, order_idx, title) VALUES (?, ?, 1, 'x')"
                 " ON CONFLICT(id) DO UPDATE SET title = excluded.title", (step, ctx))
    conn.commit()
    assert _version(conn, "steps", step) == 5
    # Una mutación puede fijar la siguiente versión ella misma, sin doble incremento.
    conn.execute("UPDATE contexts SET version = 2, title = 'Fijada' WHERE id = ?", (ctx,))
    conn.commit()
    assert _version(conn, "contexts", ctx) == 2


@pytest.mark.parametrize("value", [1, 0, 4, 10])
def test_the_version_cannot_go_back_or_jump(isolated_db, value):
    conn = isolated_db._conn()
    ctx = isolated_db.insert_context("mi-proyecto", "Título")
    conn.execute("UPDATE contexts SET title = 'dos' WHERE id = ?", (ctx,))
    conn.commit()
    assert _version(conn, "contexts", ctx) == 2
    with pytest.raises(sqlite3.IntegrityError, match="solo avanza de a uno"):
        conn.execute("UPDATE contexts SET version = ? WHERE id = ?", (value, ctx))
    conn.rollback()
    assert _version(conn, "contexts", ctx) == 2


def test_recursive_triggers_do_not_double_count(isolated_db):
    conn = isolated_db._conn()
    conn.execute("PRAGMA recursive_triggers = ON")
    try:
        ctx = isolated_db.insert_context("mi-proyecto", "Título")
        conn.execute("UPDATE contexts SET title = 'x' WHERE id = ?", (ctx,))
        conn.commit()
        assert _version(conn, "contexts", ctx) == 2
    finally:
        conn.execute("PRAGMA recursive_triggers = OFF")


def test_no_code_replaces_contexts_or_steps():
    # INSERT OR REPLACE borra y vuelve a insertar: reiniciaría la versión a 1.
    pattern = re.compile(r"(?:OR\s+REPLACE|REPLACE)\s+INTO\s+(?:contexts|steps)\b", re.IGNORECASE)
    offenders = [str(path.relative_to(ROOT)) for path in (ROOT / "orchestrator").rglob("*.py")
                 if pattern.search(path.read_text(encoding="utf-8"))]
    assert offenders == []


def test_mcp_outputs_include_the_version(isolated_db):
    import orchestrator.mcp as mcp

    ctx = isolated_db.insert_context("mi-proyecto", "Título")
    step = isolated_db.insert_step(ctx, 1, "Paso")
    assert mcp._tool_get_context({"context_id": ctx})["version"] == 1
    listed = mcp._tool_list_steps({"context_id": ctx})["steps"]
    assert [item["version"] for item in listed] == [1]
    summary = mcp._tool_list_steps({"context_id": ctx, "fields": "summary"})["steps"]
    assert [item["version"] for item in summary] == [1]
    mcp._tool_update_step({"step_id": step, "notes": "n"})
    assert mcp._tool_get_step({"step_id": step})["step"]["version"] == 2


def test_the_attempt_log_is_append_only(isolated_db):
    conn = isolated_db._conn()
    _command(conn)
    conn.execute("INSERT INTO ui_command_attempts (request_id, ts, status) VALUES ('r1', ?, 'ok')", (TS,))
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="solo de agregar"):
        conn.execute("UPDATE ui_command_attempts SET status = 'error'")
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="solo de agregar"):
        conn.execute("DELETE FROM ui_command_attempts")
    conn.rollback()
    assert conn.execute("SELECT status FROM ui_command_attempts").fetchall()[0][0] == "ok"


@pytest.mark.parametrize("sql", [
    "INSERT INTO ui_command_attempts (request_id, ts, status) VALUES ('huerfano', 't', 'ok')",
    "INSERT INTO jobs (id, request_id, kind, status, created_at) VALUES ('j', 'huerfano', 'sync', 'queued', 't')",
    "INSERT INTO durable_intents (request_id, kind, status, created_at) VALUES ('huerfano', 'index_yaml', 'pending', 't')",
    "INSERT INTO budget_reservations (request_id, project, period, estimated_usd, status, created_at)"
    " VALUES ('huerfano', 'p', '2026-10', 1, 'reserved', 't')",
    "INSERT INTO project_identities (alias, kind, status, path, created_at, updated_at)"
    " VALUES ('sin-proyecto', 'folder', 'proposed', '/x', 't', 't')",
    "INSERT INTO projects (alias, parent_alias, created_at) VALUES ('hijo', 'padre-inexistente', 't')",
])
def test_nothing_points_to_a_missing_command_or_project(isolated_db, sql):
    conn = isolated_db._conn()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql)
    conn.rollback()


def test_a_path_belongs_to_a_single_project(isolated_db):
    conn = isolated_db._conn()
    conn.execute("INSERT INTO projects (alias, created_at) VALUES ('mi-proyecto', ?), ('otro', ?)", (TS, TS))
    identity = ("INSERT INTO project_identities (alias, kind, status, path, created_at, updated_at)"
                " VALUES (?, ?, 'confirmed', ?, ?, ?)")
    conn.execute(identity, ("mi-proyecto", "registered", "/src/mi-proyecto", TS, TS))
    conn.execute(identity, ("mi-proyecto", "worktree", "/src/mi-proyecto-wt-a", TS, TS))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(identity, ("otro", "folder", "/src/mi-proyecto-wt-a", TS, TS))
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO project_identities (alias, kind, status, path, created_at, updated_at)"
                     " VALUES ('mi-proyecto', 'folder', 'proposed', NULL, ?, ?)", (TS, TS))
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO projects (alias, parent_alias, created_at) VALUES ('yo', 'yo', ?)", (TS,))
    conn.rollback()


@pytest.mark.parametrize("sql", [
    "INSERT INTO ui_commands (request_id, command, category, capability_profile, input_hash, status, created_at, updated_at)"
    " VALUES ('r', 'c', 'read', 'readonly', 'h', 'pending', 't', 't')",
    "INSERT INTO jobs (id, request_id, kind, status, created_at) VALUES ('j', 'r1', 'sync', 'running-forever', 't')",
    "INSERT INTO jobs (id, request_id, kind, resources, status, created_at) VALUES ('j', 'r1', 'sync', 'no-json', 'queued', 't')",
    "INSERT INTO durable_intents (request_id, kind, status, created_at) VALUES ('r1', 'otra_cosa', 'pending', 't')",
    "INSERT INTO durable_intents (request_id, kind, payload, status, created_at) VALUES ('r1', 'index_yaml', '[1]', 'pending', 't')",
    "INSERT INTO budget_reservations (request_id, project, period, estimated_usd, status, created_at)"
    " VALUES ('r1', 'p', '2026-10', -1, 'reserved', 't')",
    "INSERT INTO budget_reservations (request_id, project, period, estimated_usd, actual_usd, status, created_at)"
    " VALUES ('r1', 'p', '2026-10', 1, -2, 'settled', 't')",
])
def test_status_kind_and_json_values_are_constrained(isolated_db, sql):
    conn = isolated_db._conn()
    _command(conn)
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql)
    conn.rollback()


def test_request_ids_are_unique_per_logical_command(isolated_db):
    conn = isolated_db._conn()
    _command(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _command(conn)
    conn.rollback()


def test_run_script_keeps_strings_and_rejects_truncated_sql():
    from orchestrator.migrate import _run_script

    conn = sqlite3.connect(":memory:")
    _run_script(conn, """
        -- comentario antes de la tabla
        CREATE TABLE t (x TEXT CHECK (x <> ';'));
        INSERT INTO t VALUES ('línea
-- no es comentario: es parte del texto');
        CREATE TRIGGER trg AFTER INSERT ON t BEGIN SELECT 1; SELECT 2; END;
    """)
    assert conn.execute("SELECT x FROM t").fetchone()[0].endswith("-- no es comentario: es parte del texto')"[:-2])
    assert conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchone()[0] == "trg"
    with pytest.raises(ValueError, match="SQL incompleto"):
        _run_script(conn, "CREATE TABLE u (y TEXT")


def test_lock_retry_retries_and_explains_a_persistent_lock(monkeypatch):
    import orchestrator.migrate as migrate

    monkeypatch.setattr("time.sleep", lambda seconds: None)
    calls = []

    def locked_twice():
        calls.append(1)
        if len(calls) < 3:
            raise sqlite3.OperationalError("database is locked")

    migrate._with_lock_retry(locked_twice)
    assert len(calls) == 3

    def always_locked():
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError, match="bloqueada por otro proceso"):
        migrate._with_lock_retry(always_locked)

    def other_error():
        raise sqlite3.OperationalError("no such table: x")

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        migrate._with_lock_retry(other_error)
