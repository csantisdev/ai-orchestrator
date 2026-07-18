"""Shim de compatibilidad — delega a orchestrator.db."""

from __future__ import annotations

import sqlite3
from typing import Optional

from orchestrator.paths import DB_PATH
from orchestrator.providers.base import CompletionResult

RUNS_PATH = DB_PATH


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def log_run(
    project: str,
    task: str,
    result: CompletionResult,
    duration_ms: int,
    routing_reason: str = "",
    cost_usd: Optional[float] = None,
    step_id: Optional[int] = None,
    routing_source: str = "unknown",
) -> int:
    from orchestrator.db import insert_run, update_run
    run_id = insert_run(
        project=project,
        task=task,
        provider=result.provider,
        model=result.model,
        status="pending",
        step_id=step_id,
    )
    update_run(
        run_id=run_id,
        result=result,
        duration_ms=duration_ms,
        routing_reason=routing_reason,
        cost_usd=cost_usd,
        routing_source=routing_source,
    )
    return run_id


def read_runs(project: Optional[str] = None, last: int = 200) -> list[dict]:
    from orchestrator.db import read_runs as db_read
    rows = db_read(project=project, last=last)
    return [_row_to_dict(r) for r in rows]


def projects_list() -> list[str]:
    from orchestrator.db import projects_list as db_projects
    return db_projects()
