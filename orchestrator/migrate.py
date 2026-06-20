"""Migraciones one-shot: JSONL → SQLite."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

from orchestrator.paths import HOME_DIR

_RUNS_JSONL = HOME_DIR / "runs.jsonl"
_migration_lock = threading.Lock()


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
    if not _RUNS_JSONL.exists():
        return 0

    count = 0
    for line in _RUNS_JSONL.read_text(encoding="utf-8").splitlines():
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
        migrated = _RUNS_JSONL.with_suffix(".jsonl.migrated")
        _RUNS_JSONL.rename(migrated)

    return count


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
