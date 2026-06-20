"""Capa de persistencia SQLite — reemplaza runs.jsonl."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from orchestrator.providers.base import CompletionResult

_local = threading.local()
_write_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    import orchestrator.paths as _paths
    if not hasattr(_local, "conn") or _local.conn is None:
        _paths.HOME_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_paths.DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS _migrations (
    name       TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                    TEXT    NOT NULL,
    project               TEXT    NOT NULL,
    provider              TEXT    NOT NULL DEFAULT '',
    model                 TEXT    NOT NULL DEFAULT '',
    status                TEXT    NOT NULL DEFAULT 'done',
    task                  TEXT    NOT NULL DEFAULT '',
    task_preview          TEXT    NOT NULL DEFAULT '',
    response              TEXT    NOT NULL DEFAULT '',
    duration_ms           INTEGER,
    input_tokens          INTEGER,
    output_tokens         INTEGER,
    cache_creation_tokens INTEGER DEFAULT 0,
    cache_read_tokens     INTEGER DEFAULT 0,
    cost_usd              REAL,
    routing_reason        TEXT    NOT NULL DEFAULT '',
    parent_run_id         INTEGER REFERENCES runs(id),
    session_id            TEXT    UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project);
CREATE INDEX IF NOT EXISTS idx_runs_ts      ON runs(ts DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status  ON runs(status);

CREATE VIRTUAL TABLE IF NOT EXISTS runs_fts USING fts5(
    task,
    routing_reason,
    content='runs',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS runs_fts_insert AFTER INSERT ON runs BEGIN
    INSERT INTO runs_fts(rowid, task, routing_reason)
    VALUES (new.id, new.task, new.routing_reason);
END;

CREATE TRIGGER IF NOT EXISTS runs_fts_delete AFTER DELETE ON runs BEGIN
    INSERT INTO runs_fts(runs_fts, rowid, task, routing_reason)
    VALUES ('delete', old.id, old.task, old.routing_reason);
END;

CREATE TRIGGER IF NOT EXISTS runs_fts_update AFTER UPDATE ON runs BEGIN
    INSERT INTO runs_fts(runs_fts, rowid, task, routing_reason)
    VALUES ('delete', old.id, old.task, old.routing_reason);
    INSERT INTO runs_fts(rowid, task, routing_reason)
    VALUES (new.id, new.task, new.routing_reason);
END;
"""


def init_db() -> None:
    conn = _conn()
    with _write_lock:
        conn.executescript(_SCHEMA)
        conn.commit()

    from orchestrator.migrate import run_migrations
    run_migrations()


def insert_run(
    project: str,
    task: str,
    provider: str = "",
    model: str = "",
    status: str = "pending",
    parent_run_id: Optional[int] = None,
) -> int:
    conn = _conn()
    ts = datetime.now(timezone.utc).isoformat()
    preview = task[:150].replace("\n", " ").strip()
    with _write_lock:
        cur = conn.execute(
            """INSERT INTO runs
               (ts, project, provider, model, status, task, task_preview, parent_run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, project, provider, model, status, task, preview, parent_run_id),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def _extract_tokens(result: CompletionResult) -> tuple[Optional[int], Optional[int]]:
    usage = (result.raw_response or {}).get("usage", {})
    if "input_tokens" in usage:
        return usage.get("input_tokens"), usage.get("output_tokens")
    if "prompt_tokens" in usage:
        return usage.get("prompt_tokens"), usage.get("completion_tokens")
    return None, None


def update_run(
    run_id: int,
    result: CompletionResult,
    duration_ms: int,
    routing_reason: str,
    cost_usd: Optional[float] = None,
) -> None:
    conn = _conn()
    in_tok, out_tok = _extract_tokens(result)
    with _write_lock:
        conn.execute(
            """UPDATE runs SET
               provider=?, model=?, status='done', response=?,
               duration_ms=?, input_tokens=?, output_tokens=?,
               cache_creation_tokens=?, cache_read_tokens=?,
               cost_usd=?, routing_reason=?
               WHERE id=?""",
            (
                result.provider, result.model, result.text,
                duration_ms, in_tok, out_tok,
                getattr(result, "cache_creation_tokens", 0),
                getattr(result, "cache_read_tokens", 0),
                cost_usd, routing_reason, run_id,
            ),
        )
        conn.commit()


def fail_run(run_id: int, error: str) -> None:
    conn = _conn()
    with _write_lock:
        conn.execute(
            "UPDATE runs SET status='failed', response=? WHERE id=?",
            (error, run_id),
        )
        conn.commit()


def read_runs(
    project: Optional[str] = None,
    last: int = 200,
    status: Optional[str] = None,
) -> list[sqlite3.Row]:
    conn = _conn()
    conditions = []
    params: list = []
    if project:
        conditions.append("project = ?")
        params.append(project)
    if status:
        conditions.append("status = ?")
        params.append(status)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(last)
    rows = conn.execute(
        f"SELECT * FROM runs {where} ORDER BY ts DESC LIMIT ?", params
    ).fetchall()
    return list(reversed(rows))


def get_run(run_id: int) -> Optional[sqlite3.Row]:
    return _conn().execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()


def fts_search(query: str, limit: int = 10) -> list[sqlite3.Row]:
    conn = _conn()
    try:
        rows = conn.execute(
            """SELECT runs.* FROM runs
               JOIN runs_fts ON runs.id = runs_fts.rowid
               WHERE runs_fts MATCH ?
               ORDER BY rank LIMIT ?""",
            (query, limit),
        ).fetchall()
        return rows
    except sqlite3.OperationalError:
        return []


def daily_cost(project: str) -> float:
    conn = _conn()
    today = datetime.now(timezone.utc).date().isoformat()
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0.0) FROM runs WHERE project=? AND date(ts)=?",
        (project, today),
    ).fetchone()
    return float(row[0]) if row else 0.0


def projects_list() -> list[str]:
    rows = _conn().execute(
        "SELECT DISTINCT project FROM runs ORDER BY project"
    ).fetchall()
    return [r["project"] for r in rows]
