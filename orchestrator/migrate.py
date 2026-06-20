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

        if not _already_applied(conn, "index_chroma"):
            n = _index_existing_runs(conn)
            with _write_lock:
                _mark_applied(conn, "index_chroma")
                conn.commit()
