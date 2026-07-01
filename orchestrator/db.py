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
    if result.input_tokens is not None or result.output_tokens is not None:
        return result.input_tokens, result.output_tokens
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
    router_cost_usd: Optional[float] = None,
) -> None:
    conn = _conn()
    in_tok, out_tok = _extract_tokens(result)
    with _write_lock:
        conn.execute(
            """UPDATE runs SET
               provider=?, model=?, status='done', response=?,
               duration_ms=?, input_tokens=?, output_tokens=?,
               cache_creation_tokens=?, cache_read_tokens=?,
               cost_usd=?, routing_reason=?, router_cost_usd=?
               WHERE id=?""",
            (
                result.provider, result.model, result.text,
                duration_ms, in_tok, out_tok,
                getattr(result, "cache_creation_tokens", 0),
                getattr(result, "cache_read_tokens", 0),
                cost_usd, routing_reason, router_cost_usd, run_id,
            ),
        )
        conn.commit()


def delete_imported_runs(project: str, provider: Optional[str] = None) -> list[int]:
    """Elimina runs importados de un proyecto. Si provider se especifica, filtra por él.
    Retorna lista de run_ids eliminados (para limpiar ChromaDB)."""
    conn = _conn()
    if provider:
        rows = conn.execute(
            "SELECT id FROM runs WHERE project=? AND provider=?",
            (project, provider),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id FROM runs WHERE project=?",
            (project,),
        ).fetchall()
    ids = [r["id"] for r in rows]
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    with _write_lock:
        conn.execute(f"DELETE FROM runs WHERE id IN ({placeholders})", ids)
        conn.commit()
    return ids


def import_external_run(
    project: str,
    task: str,
    response: str,
    provider: str,
    model: str = "",
    agent_label: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_ms: Optional[int] = None,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cost_usd: Optional[float] = None,
    session_id: Optional[str] = None,
    ts: Optional[str] = None,
) -> int:
    """Inserta un run completo importado de un agente externo. Retorna el run_id."""
    conn = _conn()
    ts = ts or datetime.now(timezone.utc).isoformat()
    preview = task[:150].replace("\n", " ").strip()
    label = agent_label or provider
    with _write_lock:
        cur = conn.execute(
            """INSERT INTO runs
               (ts, project, provider, model, status,
                task, task_preview, response,
                input_tokens, output_tokens,
                duration_ms, cache_read_tokens, cache_creation_tokens,
                cost_usd, routing_reason, session_id)
               VALUES (?, ?, ?, ?, 'done', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ts, project, provider, model,
                task, preview, response,
                input_tokens or None, output_tokens or None,
                duration_ms,
                cache_read_tokens or None,
                cache_creation_tokens or None,
                cost_usd,
                f"Importado de {label}",
                session_id,
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def rename_project_in_db(old_alias: str, new_alias: str) -> dict:
    """Actualiza el alias de proyecto en runs y contexts. Retorna conteos."""
    conn = _conn()
    with _write_lock:
        runs_n = conn.execute(
            "UPDATE runs SET project=? WHERE project=?", (new_alias, old_alias)
        ).rowcount
        ctx_n = conn.execute(
            "UPDATE contexts SET project=? WHERE project=?", (new_alias, old_alias)
        ).rowcount
        conn.commit()
    return {"runs": runs_n, "contexts": ctx_n}


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
        "rag_effectiveness": _rows(
            """SELECT
                 r.project,
                 COUNT(*) AS total_runs,
                 COUNT(DISTINCT ch.run_id) AS runs_with_hits,
                 ROUND(100.0 * COUNT(DISTINCT ch.run_id) / COUNT(*), 1) AS hit_pct
               FROM runs r
               LEFT JOIN context_hits ch ON r.id = ch.run_id
               WHERE r.provider NOT IN ('claude-code', 'codex', 'git')
               GROUP BY r.project
               ORDER BY total_runs DESC
               LIMIT 20"""
        ),
        "rag_top_chunks": _rows(
            """SELECT
                 r.project,
                 ch.source,
                 COUNT(*) AS frequency
               FROM context_hits ch
               JOIN runs r ON r.id = ch.run_id
               GROUP BY r.project, ch.source
               ORDER BY frequency DESC
               LIMIT 15"""
        ),
    }


def get_active_step_id(project: str) -> Optional[int]:
    """Retorna el id del paso in_progress del contexto activo del proyecto, o None."""
    try:
        conn = _conn()
        ctx = conn.execute(
            "SELECT id FROM contexts WHERE project=? AND status='active' ORDER BY ts DESC LIMIT 1",
            (project,),
        ).fetchone()
        if ctx is None:
            return None
        step = conn.execute(
            "SELECT id FROM steps WHERE context_id=? AND status='in_progress' ORDER BY order_idx LIMIT 1",
            (ctx["id"],),
        ).fetchone()
        return step["id"] if step else None
    except Exception:
        return None


def insert_context(project: str, title: str, description: str = "", metadata: str = "{}", parent_step_id: Optional[int] = None, status: str = "active") -> int:
    conn = _conn()
    ts = datetime.now(timezone.utc).isoformat()
    with _write_lock:
        cur = conn.execute(
            """INSERT INTO contexts (ts, updated_at, project, title, description, status, metadata, parent_step_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, ts, project, title, description, status, metadata, parent_step_id),
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


def delete_context(context_id: int) -> dict:
    """Elimina un contexto y todos sus datos asociados.

    Conserva los runs históricos pero desvincula su step_id.
    Retorna un resumen con los conteos eliminados.
    """
    conn = _conn()
    with _write_lock:
        row = conn.execute("SELECT id FROM contexts WHERE id=?", (context_id,)).fetchone()
        if row is None:
            raise ValueError(f"context {context_id} not found")

        alignments = conn.execute(
            "SELECT COUNT(*) FROM alignments WHERE context_id=?", (context_id,)
        ).fetchone()[0]
        tool_calls = conn.execute(
            "SELECT COUNT(*) FROM tool_calls WHERE context_id=?", (context_id,)
        ).fetchone()[0]
        steps_count = conn.execute(
            "SELECT COUNT(*) FROM steps WHERE context_id=?", (context_id,)
        ).fetchone()[0]

        conn.execute("DELETE FROM alignments WHERE context_id=?", (context_id,))
        conn.execute("DELETE FROM tool_calls WHERE context_id=?", (context_id,))
        conn.execute(
            "UPDATE runs SET step_id=NULL WHERE step_id IN "
            "(SELECT id FROM steps WHERE context_id=?)", (context_id,)
        )
        conn.execute(
            "UPDATE contexts SET parent_step_id=NULL WHERE parent_step_id IN "
            "(SELECT id FROM steps WHERE context_id=?)", (context_id,)
        )
        conn.execute("DELETE FROM steps WHERE context_id=?", (context_id,))
        conn.execute("DELETE FROM contexts WHERE id=?", (context_id,))
        conn.commit()

    return {
        "deleted_context_id": context_id,
        "steps": steps_count,
        "alignments": alignments,
        "tool_calls": tool_calls,
    }


def activate_first_step(context_id: int) -> bool:
    """Marca el primer paso pendiente del contexto como in_progress.

    Retorna True si activó un paso, False si no había pasos pendientes.
    """
    conn = _conn()
    ts = datetime.now(timezone.utc).isoformat()
    with _write_lock:
        row = conn.execute(
            "SELECT id FROM steps WHERE context_id=? AND status='pending' ORDER BY order_idx LIMIT 1",
            (context_id,),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE steps SET status='in_progress', started_at=? WHERE id=?",
            (ts, row["id"]),
        )
        conn.commit()
        return True
