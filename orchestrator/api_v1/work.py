"""Vertical Trabajo (spec §6.2, §23.1–§23.3): contextos, un contexto con sus pasos y el
Trace de un paso.

Solo lectura. A diferencia de los DTO de `projections` (sin texto libre), estas respuestas
llevan títulos, descripciones, notas y mensajes de alineamiento: las notas son la
evidencia principal del Trace (§20.2) y el dashboard heredado ya los mostraba. El frontend
los escribe siempre como texto (RFC-009 C7). Nunca llevan `task`, `response`, la entrada o
la salida de un tool call, ni el `session_id` de un run.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Iterable, Optional

from orchestrator.api_v1 import Request, route
from orchestrator.git_scanner import PROVIDER_NAME as GIT_PROVIDER
from orchestrator.projections import (
    CommitIndex,
    context_graph,
    normalize_agent,
    parse_instant,
    step_references,
    to_utc,
)

CONTEXT_STATUSES = ("active", "programado", "completed", "abandoned")
STEP_STATUSES = ("pending", "in_progress", "completed", "blocked", "skipped")
_COMMIT_SUBJECT_LIMIT = 160
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _registered_projects() -> set[str]:
    from orchestrator import index as index_module

    try:
        return set(index_module.list_projects().keys())
    except Exception:
        return set()


def project_known(conn: sqlite3.Connection, project: str, registered: Iterable[str]) -> bool:
    """Registrado en el índice, o con runs o contextos en la base."""
    if project in set(registered):
        return True
    return conn.execute(
        "SELECT 1 FROM contexts WHERE project = ? UNION ALL SELECT 1 FROM runs WHERE project = ? LIMIT 1",
        (project, project),
    ).fetchone() is not None


def _positive_id(value: str, name: str) -> int:
    if not value.isdigit() or value.startswith("0") or len(value) > 10:
        raise ValueError(f"{name} debe ser un entero positivo")
    return int(value)


def _instant_key(value: object) -> datetime:
    return parse_instant(value) or _EPOCH


def _step_counts() -> dict[str, int]:
    return {"total": 0, **{status: 0 for status in STEP_STATUSES}}


def list_contexts(conn: sqlite3.Connection, project: str, *, status: Optional[str] = None) -> list[dict]:
    """Contextos del proyecto: activos primero, después por última actualización."""
    where = "project = ?"
    params: list = [project]
    if status is not None:
        where += " AND status = ?"
        params.append(status)
    contexts = conn.execute(
        f"SELECT id, ts, updated_at, title, status, parent_step_id FROM contexts WHERE {where}",
        params,
    ).fetchall()
    ids = [row[0] for row in contexts]
    counts: dict[int, dict[str, int]] = {context_id: _step_counts() for context_id in ids}
    current: dict[int, dict] = {}
    if ids:
        marks = ",".join("?" * len(ids))
        for context_id, step_status, count in conn.execute(
            f"SELECT context_id, status, COUNT(*) FROM steps WHERE context_id IN ({marks}) "
            "GROUP BY context_id, status",
            ids,
        ).fetchall():
            bucket = counts[context_id]
            bucket["total"] += count
            if step_status in bucket:
                bucket[step_status] += count
        for context_id, step_id, title in conn.execute(
            f"SELECT context_id, id, title FROM steps WHERE context_id IN ({marks}) "
            "AND status = 'in_progress' ORDER BY order_idx DESC, id DESC",
            ids,
        ).fetchall():
            current[context_id] = {"id": step_id, "title": title or ""}
    rank = {name: position for position, name in enumerate(CONTEXT_STATUSES)}
    ordered = sorted(
        contexts,
        key=lambda row: (
            rank.get(row[4], len(rank)),
            -_instant_key(row[2] or row[1]).timestamp(),
            -row[0],
        ),
    )
    return [
        {
            "id": context_id,
            "title": title or "",
            "status": state or "",
            "created_at": to_utc(created),
            "updated_at": to_utc(updated),
            "parent_step_id": parent,
            "steps": counts[context_id],
            "current_step": current.get(context_id),
        }
        for context_id, created, updated, title, state, parent in ordered
    ]


def context_detail(
    conn: sqlite3.Connection,
    project: str,
    context_id: int,
    commits: Optional[CommitIndex] = None,
) -> Optional[dict]:
    """El contexto y sus pasos con los atributos del ProjectGraph (§10.1) y sus títulos."""
    row = conn.execute(
        "SELECT id, ts, updated_at, title, description, status, parent_step_id FROM contexts "
        "WHERE id = ? AND project = ?",
        (context_id, project),
    ).fetchone()
    if row is None:
        return None
    graph = context_graph(conn, context_id, commits)
    attrs = {node["id"]: node.get("attrs", {}) for node in graph["nodes"] if node["kind"] == "step"}
    verified: dict[str, int] = {}
    for edge in graph["edges"]:
        if edge["relation_type"] == "cites":
            verified[edge["source"]] = verified.get(edge["source"], 0) + 1
    tool_calls = dict(conn.execute(
        "SELECT step_id, COUNT(*) FROM tool_calls WHERE context_id = ? GROUP BY step_id", (context_id,)
    ).fetchall())
    children: dict[int, list[int]] = {}
    for child_id, parent_step in conn.execute(
        "SELECT c.id, c.parent_step_id FROM contexts c JOIN steps s ON s.id = c.parent_step_id "
        "WHERE s.context_id = ? ORDER BY c.id",
        (context_id,),
    ).fetchall():
        children.setdefault(parent_step, []).append(child_id)
    parent = None
    if row[6] is not None:
        found = conn.execute(
            "SELECT s.id, s.context_id, c.project FROM steps s JOIN contexts c ON c.id = s.context_id "
            "WHERE s.id = ?",
            (row[6],),
        ).fetchone()
        if found is not None and found[2] == project:
            parent = {"step_id": found[0], "context_id": found[1]}
    steps = []
    for step_id, title, status, provider, started, completed, notes in conn.execute(
        "SELECT id, title, status, provider, started_at, completed_at, notes FROM steps "
        "WHERE context_id = ? ORDER BY order_idx, id",
        (context_id,),
    ).fetchall():
        node = attrs.get(f"step:{step_id}", {})
        steps.append({
            "id": step_id,
            "idx": node.get("idx"),
            "title": title or "",
            "status": status or "",
            "provider": provider or "",
            "lane": node.get("lane"),
            "secondary": node.get("secondary", []),
            "started_at": to_utc(started),
            "completed_at": to_utc(completed),
            "has_notes": bool((notes or "").strip()),
            "alignments": node.get("alignments", 0),
            "deviations": node.get("deviations", 0),
            "tool_calls": tool_calls.get(step_id, 0),
            "runs": node.get("runs", 0),
            "cost_usd": node.get("cost_usd"),
            "verified_commits": verified.get(f"step:{step_id}", 0),
            "prs": node.get("prs", []),
            "children": children.get(step_id, []),
        })
    return {
        "project": project,
        "context": {
            "id": row[0],
            "title": row[3] or "",
            "description": row[4] or "",
            "status": row[5] or "",
            "created_at": to_utc(row[1]),
            "updated_at": to_utc(row[2]),
            "parent": parent,
        },
        "steps": steps,
    }


def _commit_details(conn: sqlite3.Connection, shas: list[str]) -> list[dict]:
    """Commit importado de cada SHA verificado: run, proyecto, instante y primera línea."""
    details = []
    for sha in shas:
        found = conn.execute(
            "SELECT id, project, ts, task_preview FROM runs WHERE provider = ? AND session_id LIKE ? "
            "ORDER BY id LIMIT 1",
            (GIT_PROVIDER, f"git::%::{sha}"),
        ).fetchone()
        subject = ""
        if found is not None and found[3]:
            subject = found[3].strip().splitlines()[0][:_COMMIT_SUBJECT_LIMIT] if found[3].strip() else ""
        details.append({
            "sha": sha,
            "run_id": found[0] if found is not None else None,
            "project": found[1] if found is not None else None,
            "ts": to_utc(found[2]) if found is not None else None,
            "subject": subject,
        })
    return details


def step_trace(
    conn: sqlite3.Connection,
    project: str,
    step_id: int,
    commits: Optional[CommitIndex] = None,
) -> Optional[dict]:
    """Trace de un paso (§6.2): notas, commits y PRs citados, alineamientos, tool calls y runs.

    Las invocaciones MCP no se asocian al paso (no tienen `step_id`, §6.2).
    """
    row = conn.execute(
        "SELECT s.id, s.context_id, s.title, s.description, s.status, s.provider, s.started_at, "
        "s.completed_at, s.notes, c.title, c.status FROM steps s JOIN contexts c ON c.id = s.context_id "
        "WHERE s.id = ? AND c.project = ?",
        (step_id, project),
    ).fetchone()
    if row is None:
        return None
    commits = commits if commits is not None else CommitIndex.from_db(conn)
    context_id = row[1]
    siblings = [sibling for (sibling,) in conn.execute(
        "SELECT id FROM steps WHERE context_id = ? ORDER BY order_idx, id", (context_id,)
    ).fetchall()]
    position = siblings.index(step_id)
    refs = step_references(row[8], commits)
    alignments = sorted(
        conn.execute(
            "SELECT id, ts, agent, confirmed, checkpoint, message FROM alignments WHERE step_id = ?",
            (step_id,),
        ).fetchall(),
        key=lambda item: (_instant_key(item[1]), item[0]),
    )
    tool_calls = sorted(
        conn.execute(
            "SELECT id, ts, tool_name, status, duration_ms FROM tool_calls WHERE step_id = ?", (step_id,)
        ).fetchall(),
        key=lambda item: (_instant_key(item[1]), item[0]),
    )
    runs = sorted(
        conn.execute(
            "SELECT id, ts, provider, model, status, cost_usd, routing_source, session_id FROM runs "
            "WHERE step_id = ?",
            (step_id,),
        ).fetchall(),
        key=lambda item: (_instant_key(item[1]), item[0]),
    )
    return {
        "project": project,
        "context": {"id": context_id, "title": row[9] or "", "status": row[10] or ""},
        "step": {
            "id": row[0],
            "idx": position + 1,
            "title": row[2] or "",
            "description": row[3] or "",
            "status": row[4] or "",
            "provider": row[5] or "",
            "started_at": to_utc(row[6]),
            "completed_at": to_utc(row[7]),
            "notes": row[8] or "",
        },
        "navigation": {
            "previous": siblings[position - 1] if position > 0 else None,
            "next": siblings[position + 1] if position + 1 < len(siblings) else None,
            "total": len(siblings),
        },
        "references": {
            "commits": _commit_details(conn, refs["verified_commits"]),
            "unverified_shas": refs["unverified_shas"],
            "prs": refs["prs"],
            "mentions_tests": refs["mentions_tests"],
        },
        "alignments": [
            {
                "id": align_id,
                "ts": to_utc(ts),
                "agent": normalize_agent(agent),
                "confirmed": bool(confirmed),
                "checkpoint": checkpoint or "",
                "message": message or "",
            }
            for align_id, ts, agent, confirmed, checkpoint, message in alignments
        ],
        "tool_calls": [
            {"id": call_id, "ts": to_utc(ts), "tool_name": name or "", "status": state or "",
             "duration_ms": duration if isinstance(duration, int) else None}
            for call_id, ts, name, state, duration in tool_calls
        ],
        "runs": [
            {
                "id": run_id,
                "ts": to_utc(ts),
                "provider": provider or "",
                "model": model or "",
                "status": state or "",
                "cost_usd": cost if isinstance(cost, (int, float)) and cost >= 0 else None,
                "imported": bool(session_id),
                "routing_source": routing_source or None,
            }
            for run_id, ts, provider, model, state, cost, routing_source, session_id in runs
        ],
    }


def _connection() -> sqlite3.Connection:
    from orchestrator.db import _conn

    return _conn()


def _require_project(conn: sqlite3.Connection, project: str) -> Optional[tuple[int, dict]]:
    if not project_known(conn, project, _registered_projects()):
        return 404, {"error": "unknown project"}
    return None


@route("GET", "/api/v1/projects/{project}/contexts")
def contexts(request: Request):
    status = request.arg("status")
    if status is not None and status not in CONTEXT_STATUSES:
        raise ValueError(f"status debe ser uno de: {', '.join(CONTEXT_STATUSES)}")
    project = request.params["project"]
    conn = _connection()
    missing = _require_project(conn, project)
    if missing:
        return missing
    return {"project": project, "status": status, "contexts": list_contexts(conn, project, status=status)}


@route("GET", "/api/v1/projects/{project}/contexts/{context_id}")
def context(request: Request):
    context_id = _positive_id(request.params["context_id"], "context_id")
    project = request.params["project"]
    conn = _connection()
    missing = _require_project(conn, project)
    if missing:
        return missing
    detail = context_detail(conn, project, context_id)
    return detail if detail is not None else (404, {"error": "unknown context"})


@route("GET", "/api/v1/projects/{project}/steps/{step_id}/trace")
def trace(request: Request):
    step_id = _positive_id(request.params["step_id"], "step_id")
    project = request.params["project"]
    conn = _connection()
    missing = _require_project(conn, project)
    if missing:
        return missing
    found = step_trace(conn, project, step_id)
    return found if found is not None else (404, {"error": "unknown step"})
