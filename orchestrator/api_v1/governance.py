"""Vertical Gobernanza (spec §19.1, §19.6, §23.3): ¿qué se denegó o falló, y por qué?

Empieza por el acceso MCP (RFC-008), que es la gobernanza con datos: invocaciones
denegadas, con error o que quedaron en curso. Egress se muestra cuando tiene filas.

Solo lectura. Las invocaciones guardan hashes, nunca payloads; acá no viajan ni los hashes
ni el `actor_id`. Todo se limita al proyecto de la ruta.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from orchestrator.api_v1 import Request, route
from orchestrator.projections import normalize_agent, parse_instant, to_utc

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
PERIODS = {"7d": 7, "30d": 30, "90d": 90}
# Filtros de invocaciones: `problems` (por defecto) junta denegadas y con error.
MCP_FILTERS = {
    "problems": "(status = 'denied' OR status = 'error' OR is_error = 1)",
    "denied": "status = 'denied'",
    "error": "(status = 'error' OR is_error = 1)",
    "in_progress": "status = 'in_progress'",
    "all": "1 = 1",
}
_CURSOR = re.compile(r"(?:(?P<day>[0-9]{1,7}\.[0-9]{1,17}|[0-9]{1,7})|-)\|(?P<id>[1-9][0-9]{0,9})")
# Orden estable por instante UTC (§19.4 O2): `julianday` entiende `Z` y `±HH:MM`; los `ts`
# que no puede leer van al final, por id.
_ORDER = "julianday(ts) IS NULL, julianday(ts) DESC, id DESC"


def _registered_projects() -> set[str]:
    from orchestrator import index as index_module

    try:
        return set(index_module.list_projects().keys())
    except Exception:
        return set()


def project_known(conn: sqlite3.Connection, project: str, registered: Iterable[str]) -> bool:
    """Registrado en el índice, o con runs o contextos en la base (mismo criterio que Trabajo)."""
    if project in set(registered):
        return True
    return conn.execute(
        "SELECT 1 FROM contexts WHERE project = ? UNION ALL SELECT 1 FROM runs WHERE project = ? LIMIT 1",
        (project, project),
    ).fetchone() is not None


def parse_limit(value: Optional[str]) -> int:
    if value is None:
        return DEFAULT_LIMIT
    if not re.fullmatch(r"[1-9][0-9]{0,2}", value) or int(value) > MAX_LIMIT:
        raise ValueError(f"limit debe ser un entero entre 1 y {MAX_LIMIT}")
    return int(value)


def parse_cursor(value: Optional[str]) -> Optional[tuple[Optional[float], int]]:
    """`<julianday>|<id>` o `-|<id>` (tramo de `ts` ilegibles); None sin cursor."""
    if value is None:
        return None
    found = _CURSOR.fullmatch(value)
    if found is None:
        raise ValueError("cursor inválido")
    day = found.group("day")
    return (float(day) if day is not None else None, int(found.group("id")))


def _encode_cursor(day: Optional[float], row_id: int) -> str:
    return f"{'-' if day is None else repr(day)}|{row_id}"


def _page(conn, table: str, columns: str, where: str, params: list, limit: int, cursor) -> tuple[list, Optional[str]]:
    """Página ordenada por instante UTC con cursor compuesto (instante, id), sin saltos ni duplicados."""
    if cursor is not None:
        day, row_id = cursor
        if day is None:
            where += " AND julianday(ts) IS NULL AND id < ?"
            params = [*params, row_id]
        else:
            where += (" AND (julianday(ts) IS NULL OR julianday(ts) < ? "
                      "OR (julianday(ts) = ? AND id < ?))")
            params = [*params, day, day, row_id]
    rows = conn.execute(
        f"SELECT julianday(ts), {columns} FROM {table} WHERE {where} ORDER BY {_ORDER} LIMIT ?",
        [*params, limit + 1],
    ).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _encode_cursor(rows[-1][0], rows[-1][1]) if more else None
    return [row[1:] for row in rows], next_cursor


def list_mcp_invocations(
    conn: sqlite3.Connection, project: str, *, status: str = "problems", limit: int = DEFAULT_LIMIT,
    cursor: Optional[tuple[Optional[float], int]] = None,
) -> dict:
    """Invocaciones MCP del proyecto, las más recientes primero."""
    if status not in MCP_FILTERS:
        raise ValueError(f"status debe ser uno de: {', '.join(MCP_FILTERS)}")
    rows, next_cursor = _page(
        conn, "mcp_invocations",
        "id, ts, client_surface, transport, capability_profile, tool_name, tool_category, status, "
        "is_error, reason_code, error_code, duration_ms, request_source, replay_safe",
        f"project = ? AND {MCP_FILTERS[status]}", [project], limit, cursor,
    )
    items = [
        {
            "id": row_id,
            "sel": f"decision:mcp-{row_id}",
            "ts": to_utc(ts),
            "agent": normalize_agent(surface),
            "client_surface": surface or "",
            "transport": transport or "",
            "capability_profile": profile or "",
            "tool_name": tool or "",
            "tool_category": category or "",
            "status": state or "",
            "is_error": bool(is_error),
            "reason_code": reason,
            "error_code": error_code,
            "duration_ms": duration if isinstance(duration, int) and not isinstance(duration, bool) else None,
            "request_source": source or "",
            "replay_safe": bool(replay_safe),
        }
        for (row_id, ts, surface, transport, profile, tool, category, state, is_error, reason, error_code,
             duration, source, replay_safe) in rows
    ]
    return {"project": project, "status": status, "items": items, "next_cursor": next_cursor}


def list_egress_decisions(
    conn: sqlite3.Connection, project: str, *, limit: int = DEFAULT_LIMIT,
    cursor: Optional[tuple[Optional[float], int]] = None,
) -> dict:
    """Decisiones del gate de egress del proyecto, las más recientes primero."""
    rows, next_cursor = _page(
        conn, "egress_decisions",
        "id, ts, provider, phase, decision, reason_code, sensitivity, clearance, run_id",
        "project = ?", [project], limit, cursor,
    )
    run_ids = [row[8] for row in rows if row[8] is not None]
    local_runs: set[int] = set()
    if run_ids:
        marks = ",".join("?" * len(run_ids))
        local_runs = {run_id for (run_id,) in conn.execute(
            f"SELECT id FROM runs WHERE project = ? AND id IN ({marks})", (project, *run_ids)
        ).fetchall()}
    items = [
        {
            "id": row_id,
            "sel": f"decision:egress-{row_id}",
            "ts": to_utc(ts),
            "provider": provider or "",
            "phase": phase or "",
            "decision": decision or "",
            "reason_code": reason or "",
            "sensitivity": sensitivity,
            "clearance": clearance,
            # Un run de otro proyecto no se expone.
            "run_id": run_id if run_id in local_runs else None,
        }
        for row_id, ts, provider, phase, decision, reason, sensitivity, clearance, run_id in rows
    ]
    return {"project": project, "items": items, "next_cursor": next_cursor}


def _count(groups: dict[str, int], key: str) -> None:
    groups[key] = groups.get(key, 0) + 1


def _ranked(groups: dict[str, int]) -> list[dict]:
    return [{"key": key, "count": count} for key, count in sorted(groups.items(), key=lambda item: (-item[1], item[0]))]


def governance_summary(conn: sqlite3.Connection, project: str, *, now: datetime, period: str = "30d") -> dict:
    """Resumen del período: denegadas y con error por motivo, herramienta y agente; egress.

    `denied` y `error` son categorías excluyentes: una denegación también se registra con
    `is_error`, pero cuenta como denegada; `error` son los fallos que no fueron denegaciones.
    Los rankings cuentan cada invocación problemática una sola vez.
    """
    if period not in PERIODS:
        raise ValueError(f"period debe ser uno de: {', '.join(PERIODS)}")
    now = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    start = now - timedelta(days=PERIODS[period])

    def inside(ts: object) -> bool:
        instant = parse_instant(ts)
        return instant is not None and start <= instant < now

    totals = {"invocations": 0, "denied": 0, "error": 0, "in_progress": 0}
    reasons: dict[str, int] = {}
    tools: dict[str, int] = {}
    agents: dict[str, int] = {}
    for ts, surface, tool, state, is_error, reason, error_code in conn.execute(
        "SELECT ts, client_surface, tool_name, status, is_error, reason_code, error_code "
        "FROM mcp_invocations WHERE project = ?",
        (project,),
    ).fetchall():
        if not inside(ts):
            continue
        totals["invocations"] += 1
        if state == "in_progress":
            totals["in_progress"] += 1
        denied = state == "denied"
        failed = state == "error" or bool(is_error)
        if denied:
            totals["denied"] += 1
        elif failed:
            totals["error"] += 1
        if denied or failed:
            _count(reasons, reason or error_code or "sin código")
            _count(tools, tool or "—")
            _count(agents, normalize_agent(surface))
    egress = {"total": 0, "blocked": 0}
    egress_reasons: dict[str, int] = {}
    for ts, decision, reason in conn.execute(
        "SELECT ts, decision, reason_code FROM egress_decisions WHERE project = ?", (project,)
    ).fetchall():
        if not inside(ts):
            continue
        egress["total"] += 1
        if decision != "allowed":
            egress["blocked"] += 1
            _count(egress_reasons, reason or "sin código")
    return {
        "project": project,
        "period": {"key": period, "from": start.isoformat(), "to": now.isoformat()},
        "mcp": {
            **totals,
            "by_reason": _ranked(reasons),
            "by_tool": _ranked(tools),
            "by_agent": _ranked(agents),
        },
        "egress": {**egress, "by_reason": _ranked(egress_reasons)},
    }


def _connection() -> sqlite3.Connection:
    from orchestrator.db import _conn

    return _conn()


def _project(request: Request) -> tuple[sqlite3.Connection, str, Optional[tuple[int, dict]]]:
    project = request.params["project"]
    conn = _connection()
    if not project_known(conn, project, _registered_projects()):
        return conn, project, (404, {"error": "unknown project"})
    return conn, project, None


@route("GET", "/api/v1/projects/{project}/governance/summary")
def summary(request: Request):
    period = request.arg("period", "30d")
    if period not in PERIODS:
        raise ValueError(f"period debe ser uno de: {', '.join(PERIODS)}")
    conn, project, missing = _project(request)
    if missing:
        return missing
    return governance_summary(conn, project, now=datetime.now(timezone.utc), period=period)


@route("GET", "/api/v1/projects/{project}/mcp-invocations")
def mcp_invocations(request: Request):
    status = request.arg("status", "problems")
    if status not in MCP_FILTERS:
        raise ValueError(f"status debe ser uno de: {', '.join(MCP_FILTERS)}")
    limit = parse_limit(request.arg("limit"))
    cursor = parse_cursor(request.arg("cursor"))
    conn, project, missing = _project(request)
    if missing:
        return missing
    return list_mcp_invocations(conn, project, status=status, limit=limit, cursor=cursor)


@route("GET", "/api/v1/projects/{project}/egress-decisions")
def egress_decisions(request: Request):
    limit = parse_limit(request.arg("limit"))
    cursor = parse_cursor(request.arg("cursor"))
    conn, project, missing = _project(request)
    if missing:
        return missing
    return list_egress_decisions(conn, project, limit=limit, cursor=cursor)
