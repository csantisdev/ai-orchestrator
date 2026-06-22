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
    step_id: Optional[int] = None,
) -> int:
    conn = _conn()
    ts = datetime.now(timezone.utc).isoformat()
    preview = task[:150].replace("\n", " ").strip()
    with _write_lock:
        cur = conn.execute(
            """INSERT INTO runs
               (ts, project, provider, model, status, task, task_preview, parent_run_id, step_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, project, provider, model, status, task, preview, parent_run_id, step_id),
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
    return list(rows)


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


def read_contexts_with_steps(
    project: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict]:
    conn = _conn()
    where_parts: list[str] = []
    params: list = []
    if project:
        where_parts.append("project=?")
        params.append(project)
    if status and status != "all":
        where_parts.append("status=?")
        params.append(status)
    elif status is None and not project:
        where_parts.append("status='active'")
    clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    ctx_rows = conn.execute(
        f"SELECT * FROM contexts {clause} ORDER BY ts DESC LIMIT 50",
        params,
    ).fetchall()
    result = []
    for ctx in ctx_rows:
        ctx_dict = dict(ctx)
        steps = conn.execute(
            "SELECT * FROM steps WHERE context_id=? ORDER BY order_idx",
            (ctx["id"],),
        ).fetchall()
        ctx_dict["steps"] = [dict(s) for s in steps]
        result.append(ctx_dict)
    return result


def read_tool_calls_for_step(step_id: int) -> list[sqlite3.Row]:
    return _conn().execute(
        "SELECT * FROM tool_calls WHERE step_id=? ORDER BY ts",
        (step_id,),
    ).fetchall()


def read_alignments_for_step(step_id: int) -> list[sqlite3.Row]:
    return _conn().execute(
        "SELECT * FROM alignments WHERE step_id=? ORDER BY ts",
        (step_id,),
    ).fetchall()


def read_inspector_data() -> dict:
    conn = _conn()

    def _rows(sql: str) -> list[dict]:
        try:
            return [dict(r) for r in conn.execute(sql).fetchall()]
        except Exception:
            return []

    return {
        "counts": {
            "runs":        conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
            "contexts":    conn.execute("SELECT COUNT(*) FROM contexts").fetchone()[0],
            "steps":       conn.execute("SELECT COUNT(*) FROM steps").fetchone()[0],
            "chunks":      conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "alignments":  conn.execute("SELECT COUNT(*) FROM alignments").fetchone()[0],
            "tool_calls":  conn.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0],
        },
        "chunks": _rows(
            "SELECT * FROM chunks ORDER BY ts DESC LIMIT 300"
        ),
        "contexts": _rows(
            "SELECT * FROM contexts ORDER BY ts DESC LIMIT 100"
        ),
        "steps": _rows(
            """SELECT s.*, c.title AS context_title, c.project
               FROM steps s JOIN contexts c ON s.context_id = c.id
               ORDER BY s.context_id DESC, s.order_idx LIMIT 300"""
        ),
        "alignments": _rows(
            """SELECT a.*, s.title AS step_title
               FROM alignments a JOIN steps s ON a.step_id = s.id
               ORDER BY a.ts DESC LIMIT 200"""
        ),
        "tool_calls": _rows(
            """SELECT tc.*, s.title AS step_title
               FROM tool_calls tc JOIN steps s ON tc.step_id = s.id
               ORDER BY tc.ts DESC LIMIT 200"""
        ),
    }


def insert_context(project: str, title: str, description: str = "", metadata: str = "{}", parent_step_id: Optional[int] = None) -> int:
    conn = _conn()
    ts = datetime.now(timezone.utc).isoformat()
    with _write_lock:
        cur = conn.execute(
            """INSERT INTO contexts (ts, updated_at, project, title, description, status, metadata, parent_step_id)
               VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
            (ts, ts, project, title, description, metadata, parent_step_id),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def insert_step(context_id: int, order_idx: int, title: str, description: str = "", provider: str = "") -> int:
    conn = _conn()
    with _write_lock:
        cur = conn.execute(
            """INSERT INTO steps (context_id, order_idx, title, description, status, provider)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (context_id, order_idx, title, description, provider),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
