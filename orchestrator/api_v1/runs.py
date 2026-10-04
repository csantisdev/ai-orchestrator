"""Runs y costos de solo lectura para la sección Ejecuciones.

Las listas usan cursores sobre el orden de SQLite. Así cada página lee a lo sumo
``limit + 1`` filas, incluso cuando el proyecto tiene un historial grande.
"""

from __future__ import annotations

import math
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from orchestrator.api_v1 import Request, route
from orchestrator.api_v1.work import project_known
from orchestrator.git_scanner import PROVIDER_NAME as GIT_PROVIDER
from orchestrator.projections import normalize_agent, parse_instant, to_utc

PERIODS = {"7d": 7, "30d": 30, "90d": 90}
_CURSOR = re.compile(r"(?:(?P<instant>-?[0-9]+(?:\.[0-9]+)?)|-)[|](?P<id>[1-9][0-9]*)$")


def registered_projects() -> set[str]:
    """Proyectos registrados, sin importar un detalle privado de otra vertical."""
    from orchestrator import index as index_module

    try:
        return set(index_module.list_projects())
    except Exception:
        return set()


def _cost(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def _source(provider: object, session_id: object) -> str:
    if provider == GIT_PROVIDER:
        return "commit"
    return "session" if session_id else "router"


def _decode_cursor(value: str | None) -> tuple[float | None, int] | None:
    if not value:
        return None
    match = _CURSOR.fullmatch(value)
    if match is None:
        raise ValueError("cursor inválido")
    instant_text = match.group("instant")
    try:
        instant = float(instant_text) if instant_text is not None else None
    except ValueError as exc:
        raise ValueError("cursor inválido") from exc
    if instant is not None and not math.isfinite(instant):
        raise ValueError("cursor inválido")
    return instant, int(match.group("id"))


def _encode_cursor(instant: object, row_id: int) -> str:
    return f"{instant:.17g}|{row_id}" if instant is not None else f"-|{row_id}"


def _source_clause(source: str) -> tuple[str, list[str]]:
    if source == "all":
        return "", []
    if source == "commit":
        return " AND r.provider = ?", [GIT_PROVIDER]
    if source == "session":
        return " AND COALESCE(r.provider, '') != ? AND r.session_id IS NOT NULL", [GIT_PROVIDER]
    if source == "router":
        return " AND COALESCE(r.provider, '') != ? AND r.session_id IS NULL", [GIT_PROVIDER]
    raise ValueError("source inválido")


def _cursor_clause(cursor: tuple[float | None, int] | None) -> tuple[str, list[Any]]:
    if cursor is None:
        return "", []
    instant, row_id = cursor
    if instant is None:
        return " AND julianday(r.ts) IS NULL AND r.id < ?", [row_id]
    return (
        " AND (julianday(r.ts) IS NULL OR julianday(r.ts) < ? "
        "OR (julianday(r.ts) = ? AND r.id < ?))",
        [instant, instant, row_id],
    )


def _run_rows(conn: sqlite3.Connection, project: str, source: str, limit: int,
              cursor: tuple[float | None, int] | None) -> list[sqlite3.Row | tuple]:
    source_sql, source_params = _source_clause(source)
    cursor_sql, cursor_params = _cursor_clause(cursor)
    return conn.execute(
        "SELECT r.id, r.ts, julianday(r.ts), r.provider, r.model, r.status, r.task_preview, "
        "r.input_tokens, r.output_tokens, r.duration_ms, r.cost_usd, r.rating, r.routing_source, "
        "r.step_id, r.session_id, c.id "
        "FROM runs r LEFT JOIN steps s ON s.id = r.step_id "
        "LEFT JOIN contexts c ON c.id = s.context_id AND c.project = ? "
        "WHERE r.project = ?"
        f"{source_sql}{cursor_sql} "
        "ORDER BY julianday(r.ts) IS NULL, julianday(r.ts) DESC, r.id DESC LIMIT ?",
        [project, project, *source_params, *cursor_params, limit + 1],
    ).fetchall()


def _cursor_exists(conn: sqlite3.Connection, project: str, source: str,
                   marker: tuple[float | None, int]) -> bool:
    """Un cursor debe ser uno emitido para esta lista, no sólo tener sintaxis válida."""
    instant, row_id = marker
    source_sql, source_params = _source_clause(source)
    if instant is None:
        time_sql, time_params = "julianday(r.ts) IS NULL", []
    else:
        time_sql, time_params = "julianday(r.ts) = ?", [instant]
    row = conn.execute(
        "SELECT 1 FROM runs r WHERE r.project = ? AND r.id = ? AND " + time_sql + source_sql,
        [project, row_id, *time_params, *source_params],
    ).fetchone()
    return row is not None


def list_runs(conn: sqlite3.Connection, project: str, *, limit: int = 50, cursor: str | None = None,
              source: str = "all") -> dict:
    """Página de runs sin cargar las páginas siguientes en memoria."""
    if not 1 <= limit <= 100:
        raise ValueError("limit debe estar entre 1 y 100")
    marker = _decode_cursor(cursor)
    if marker is not None and not _cursor_exists(conn, project, source, marker):
        raise ValueError("cursor inválido")
    fetched = _run_rows(conn, project, source, limit, marker)
    page = fetched[:limit]
    runs = []
    for row in page:
        preview = (row[6] or "").splitlines()[0][:160]
        context_id = row[15]
        runs.append({
            "id": row[0], "ts": to_utc(row[1]), "source": _source(row[3], row[14]),
            "provider": row[3] or "", "model": row[4] or "", "status": row[5] or "",
            "task_preview": preview, "input_tokens": row[7], "output_tokens": row[8],
            "duration_ms": row[9], "cost_usd": _cost(row[10]), "rating": row[11],
            "routing_source": row[12], "step_id": row[13] if context_id is not None else None,
            "context_id": context_id,
        })
    next_cursor = None
    if len(fetched) > limit and page:
        next_cursor = _encode_cursor(page[-1][2], page[-1][0])
    return {"project": project, "source": source, "runs": runs, "next_cursor": next_cursor}


def costs(conn: sqlite3.Connection, project: str, period: str, *, now: datetime | None = None) -> dict:
    """Agregados para [inicio, ahora) y una serie diaria UTC del período completo."""
    if period not in PERIODS:
        raise ValueError("period inválido")
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    start = now - timedelta(days=PERIODS[period])
    rows = conn.execute(
        "SELECT r.id, r.ts, r.provider, r.session_id, r.step_id, r.cost_usd, c.id, c.title "
        "FROM runs r LEFT JOIN steps s ON s.id = r.step_id "
        "LEFT JOIN contexts c ON c.id = s.context_id AND c.project = ? WHERE r.project = ?",
        (project, project),
    ).fetchall()
    selected = []
    for row in rows:
        instant = parse_instant(row[1])
        if instant is not None and start <= instant < now:
            selected.append((row, instant, _cost(row[5])))

    # Incluye cada fecha UTC cubierta por [start, now), incluso si no hubo runs ese día.
    days = {(start.date() + timedelta(days=index)).isoformat(): 0.0 for index in range(PERIODS[period] + 1)}
    contexts: dict[int | None, dict] = {}
    agents: dict[str, dict] = {}
    for row, instant, cost in selected:
        amount = cost or 0.0
        days[instant.date().isoformat()] += amount
        context_id = row[6]
        context = contexts.setdefault(context_id, {
            "context_id": context_id, "title": row[7] or "Sin paso", "cost_usd": 0.0, "runs": 0,
        })
        context["cost_usd"] += amount
        context["runs"] += 1
        agent = "git" if _source(row[2], row[3]) == "commit" else normalize_agent(row[2])
        bucket = agents.setdefault(agent, {"agent": agent, "cost_usd": 0.0, "runs": 0})
        bucket["cost_usd"] += amount
        bucket["runs"] += 1

    def rounded(items: list[dict]) -> list[dict]:
        for item in items:
            item["cost_usd"] = round(item["cost_usd"], 6)
        return items

    with_cost = [item for item in selected if item[2] is not None]
    attributed = [item for item in selected if item[0][6] is not None]
    total = round(sum(item[2] or 0.0 for item in selected), 6)
    attributed_cost = round(sum(item[2] or 0.0 for item in attributed), 6)
    return {
        "project": project,
        "period": {"key": period, "from": to_utc(start.isoformat()), "to": to_utc(now.isoformat())},
        "totals": {"cost_usd": total, "runs": len(selected), "runs_with_cost": len(with_cost),
                   "attributed_runs": len(attributed), "attributed_cost_usd": attributed_cost},
        "daily": [{"date": day, "cost_usd": round(amount, 6)} for day, amount in days.items()],
        "by_context": rounded(sorted(contexts.values(), key=lambda item: (-item["cost_usd"], item["context_id"] or 0))),
        "by_agent": rounded(sorted(agents.values(), key=lambda item: (-item["cost_usd"], item["agent"]))),
    }


@route("GET", "/api/v1/projects/{project}/runs")
def runs_endpoint(request: Request):
    from orchestrator import db

    conn = db._conn()
    project = request.params["project"]
    if not project_known(conn, project, registered_projects()):
        return 404, {"error": "unknown project"}
    try:
        limit = int(request.arg("limit", "50"))
    except (TypeError, ValueError) as exc:
        raise ValueError("limit debe ser un entero") from exc
    return list_runs(conn, project, limit=limit, cursor=request.arg("cursor"),
                     source=request.arg("source", "all") or "all")


@route("GET", "/api/v1/projects/{project}/costs")
def costs_endpoint(request: Request):
    from orchestrator import db

    conn = db._conn()
    project = request.params["project"]
    if not project_known(conn, project, registered_projects()):
        return 404, {"error": "unknown project"}
    return costs(conn, project, request.arg("period", "30d") or "30d")
