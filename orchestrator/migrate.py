"""Migraciones one-shot: JSONL → SQLite, indexado en ChromaDB."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

import orchestrator.paths as _paths
_migration_lock = threading.Lock()


def _runs_jsonl():
    return _paths.HOME_DIR / "runs.jsonl"


def _already_applied(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM _migrations WHERE name=?", (name,)
    ).fetchone()
    return row is not None


def _mark_applied(conn: sqlite3.Connection, name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO _migrations (name, applied_at) VALUES (?, ?)",
        (name, datetime.now(timezone.utc).isoformat()),
    )


def _migrate_jsonl(conn: sqlite3.Connection) -> int:
    runs_jsonl = _runs_jsonl()
    if not runs_jsonl.exists():
        return 0

    count = 0
    for line in runs_jsonl.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue

        task_preview = r.get("task_preview", "")
        conn.execute(
            """INSERT OR IGNORE INTO runs
               (ts, project, provider, model, status,
                task, task_preview, response,
                duration_ms, input_tokens, output_tokens,
                routing_reason)
               VALUES (?, ?, ?, ?, 'done', ?, ?, '', ?, ?, ?, ?)""",
            (
                r.get("ts", datetime.now(timezone.utc).isoformat()),
                r.get("project", ""),
                r.get("provider", ""),
                r.get("model", ""),
                task_preview,
                task_preview,
                r.get("duration_ms"),
                r.get("input_tokens"),
                r.get("output_tokens"),
                r.get("routing_reason", ""),
            ),
        )
        count += 1

    if count:
        runs_jsonl = _runs_jsonl()
        migrated = runs_jsonl.with_suffix(".jsonl.migrated")
        runs_jsonl.rename(migrated)

    return count


def _index_existing_runs(conn: sqlite3.Connection) -> int:
    try:
        from orchestrator.similarity import get_backend
        backend = get_backend()
        rows = conn.execute(
            "SELECT id, task FROM runs WHERE status='done' AND task != '' ORDER BY id"
        ).fetchall()
        count = 0
        for row in rows:
            backend.upsert(row[0], row[1])
            count += 1
        return count
    except Exception:
        return 0


def run_migrations() -> None:
    with _migration_lock:
        from orchestrator.db import _conn, _write_lock
        conn = _conn()
        with _write_lock:
            if not _already_applied(conn, "jsonl_to_sqlite"):
                n = _migrate_jsonl(conn)
                _mark_applied(conn, "jsonl_to_sqlite")
                conn.commit()
                if n:
                    import logging
                    logging.getLogger(__name__).info(
                        "Migración JSONL→SQLite: %d runs importados.", n
                    )

        with _write_lock:
            if not _already_applied(conn, "add_session_id_column"):
                try:
                    conn.execute("ALTER TABLE runs ADD COLUMN session_id TEXT")
                except Exception:
                    pass
                _mark_applied(conn, "add_session_id_column")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "add_session_id_v2"):
                cols = [r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()]
                if "session_id" not in cols:
                    try:
                        conn.execute("ALTER TABLE runs ADD COLUMN session_id TEXT")
                    except Exception:
                        pass
                try:
                    conn.execute(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_session_id"
                        " ON runs(session_id) WHERE session_id IS NOT NULL"
                    )
                except Exception:
                    pass
                _mark_applied(conn, "add_session_id_v2")
                conn.commit()

        if not _already_applied(conn, "index_chroma"):
            n = _index_existing_runs(conn)
            with _write_lock:
                _mark_applied(conn, "index_chroma")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "create_contexts_table"):
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS contexts (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts          TEXT    NOT NULL,
                        updated_at  TEXT    NOT NULL,
                        project     TEXT    NOT NULL,
                        title       TEXT    NOT NULL DEFAULT '',
                        description TEXT    NOT NULL DEFAULT '',
                        status      TEXT    NOT NULL DEFAULT 'active',
                        metadata    TEXT    NOT NULL DEFAULT '{}'
                    );
                    CREATE INDEX IF NOT EXISTS idx_contexts_project ON contexts(project);
                    CREATE INDEX IF NOT EXISTS idx_contexts_status  ON contexts(status);
                """)
                _mark_applied(conn, "create_contexts_table")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "create_steps_table"):
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS steps (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        context_id   INTEGER NOT NULL REFERENCES contexts(id),
                        order_idx    INTEGER NOT NULL,
                        title        TEXT    NOT NULL DEFAULT '',
                        description  TEXT    NOT NULL DEFAULT '',
                        status       TEXT    NOT NULL DEFAULT 'pending',
                        provider     TEXT    NOT NULL DEFAULT '',
                        started_at   TEXT,
                        completed_at TEXT,
                        notes        TEXT    NOT NULL DEFAULT ''
                    );
                    CREATE INDEX IF NOT EXISTS idx_steps_context_order  ON steps(context_id, order_idx);
                    CREATE INDEX IF NOT EXISTS idx_steps_context_status ON steps(context_id, status);
                """)
                _mark_applied(conn, "create_steps_table")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "create_tool_calls_table"):
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS tool_calls (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts          TEXT    NOT NULL,
                        step_id     INTEGER NOT NULL REFERENCES steps(id),
                        context_id  INTEGER NOT NULL REFERENCES contexts(id),
                        tool_name   TEXT    NOT NULL DEFAULT '',
                        input       TEXT    NOT NULL DEFAULT '{}',
                        output      TEXT    NOT NULL DEFAULT '',
                        status      TEXT    NOT NULL DEFAULT 'ok',
                        duration_ms INTEGER
                    );
                    CREATE INDEX IF NOT EXISTS idx_tool_calls_step    ON tool_calls(step_id, ts);
                    CREATE INDEX IF NOT EXISTS idx_tool_calls_context ON tool_calls(context_id, ts);
                """)
                _mark_applied(conn, "create_tool_calls_table")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "create_alignments_table"):
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS alignments (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts         TEXT    NOT NULL,
                        step_id    INTEGER NOT NULL REFERENCES steps(id),
                        context_id INTEGER NOT NULL REFERENCES contexts(id),
                        agent      TEXT    NOT NULL DEFAULT '',
                        confirmed  INTEGER NOT NULL DEFAULT 1,
                        checkpoint TEXT    NOT NULL DEFAULT '',
                        message    TEXT    NOT NULL DEFAULT ''
                    );
                    CREATE INDEX IF NOT EXISTS idx_alignments_step    ON alignments(step_id);
                    CREATE INDEX IF NOT EXISTS idx_alignments_context ON alignments(context_id, ts);
                """)
                _mark_applied(conn, "create_alignments_table")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "add_step_id_to_runs"):
                try:
                    conn.execute("ALTER TABLE runs ADD COLUMN step_id INTEGER REFERENCES steps(id)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_step ON runs(step_id)")
                except Exception:
                    pass
                _mark_applied(conn, "add_step_id_to_runs")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "create_chunks_table"):
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS chunks (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        project     TEXT    NOT NULL,
                        source_path TEXT    NOT NULL,
                        chunk_count INTEGER NOT NULL DEFAULT 0,
                        ts          TEXT    NOT NULL,
                        collection  TEXT    NOT NULL DEFAULT 'docs',
                        UNIQUE(project, source_path)
                    );
                    CREATE INDEX IF NOT EXISTS idx_chunks_project ON chunks(project);
                """)
                _mark_applied(conn, "create_chunks_table")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "add_parent_step_id_to_contexts"):
                try:
                    conn.execute("ALTER TABLE contexts ADD COLUMN parent_step_id INTEGER REFERENCES steps(id)")
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_contexts_parent_step ON contexts(parent_step_id)"
                        " WHERE parent_step_id IS NOT NULL"
                    )
                except Exception:
                    pass
                _mark_applied(conn, "add_parent_step_id_to_contexts")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "create_context_hits_table"):
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS context_hits (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id     INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                        collection TEXT    NOT NULL DEFAULT 'docs',
                        source     TEXT    NOT NULL DEFAULT '',
                        chunk_idx  INTEGER,
                        score      REAL,
                        ts         TEXT    NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_context_hits_run ON context_hits(run_id);
                """)
                _mark_applied(conn, "create_context_hits_table")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "add_rating_to_runs"):
                try:
                    conn.execute("ALTER TABLE runs ADD COLUMN rating TEXT")
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_runs_rating ON runs(rating)"
                        " WHERE rating IS NOT NULL"
                    )
                except Exception:
                    pass
                _mark_applied(conn, "add_rating_to_runs")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "create_exchange_rates_table"):
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS exchange_rates (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        date       TEXT    NOT NULL,
                        currency   TEXT    NOT NULL DEFAULT 'USD_CLP',
                        rate       REAL    NOT NULL,
                        source     TEXT    NOT NULL DEFAULT 'bcentral',
                        fetched_at TEXT    NOT NULL,
                        UNIQUE(date, currency)
                    );
                    CREATE INDEX IF NOT EXISTS idx_rates_date ON exchange_rates(date DESC);
                """)
                _mark_applied(conn, "create_exchange_rates_table")
                conn.commit()

        with _write_lock:
            if not _already_applied(conn, "add_router_cost_usd_to_runs"):
                try:
                    conn.execute("ALTER TABLE runs ADD COLUMN router_cost_usd REAL")
                except Exception:
                    pass
                _mark_applied(conn, "add_router_cost_usd_to_runs")
                conn.commit()
