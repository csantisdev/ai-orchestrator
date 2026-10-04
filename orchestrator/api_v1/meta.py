"""Vertical meta: datos que el shell necesita antes de cualquier vista."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from orchestrator.api_v1 import Request, route
from orchestrator.projections import parse_instant

_JULIAN_UNIX_EPOCH = 2440587.5


def _from_julian(day: object) -> Optional[datetime]:
    if not isinstance(day, (int, float)) or isinstance(day, bool):
        return None
    try:
        return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(days=float(day) - _JULIAN_UNIX_EPOCH)
    except (OverflowError, ValueError):
        return None


def project_summaries(conn, registered: Iterable[str]) -> list[dict]:
    """Proyectos conocidos con lo que hace falta para elegir uno.

    Un alias es conocido si está registrado en el índice o tiene runs o contextos. Los
    registrados van primero; dentro de cada grupo, el de actividad más reciente (último
    run o última actualización de un contexto, en UTC) y después por alias.
    """
    # Mismo criterio de alias válido que `work.project_known`: texto no vacío.
    registered = {alias for alias in registered if isinstance(alias, str) and alias}
    stats: dict[str, dict] = {}

    def entry(alias: str) -> dict:
        return stats.setdefault(alias, {"runs": 0, "contexts": 0, "active_contexts": 0, "last": None})

    def touch(item: dict, instant: Optional[datetime]) -> None:
        if instant is not None and (item["last"] is None or instant > item["last"]):
            item["last"] = instant

    for alias, count, last_day in conn.execute(
        "SELECT project, COUNT(*), MAX(julianday(ts)) FROM runs WHERE project IS NOT NULL AND project != '' "
        "GROUP BY project"
    ).fetchall():
        item = entry(alias)
        item["runs"] = count
        touch(item, _from_julian(last_day))
    for alias, status, updated in conn.execute(
        "SELECT project, status, updated_at FROM contexts WHERE project IS NOT NULL AND project != ''"
    ).fetchall():
        item = entry(alias)
        item["contexts"] += 1
        if status == "active":
            item["active_contexts"] += 1
        touch(item, parse_instant(updated))
    for alias in registered:
        entry(alias)

    def order(alias: str) -> tuple:
        last = stats[alias]["last"]
        return (alias not in registered, last is None, -(last.timestamp() if last else 0.0), alias)

    return [
        {
            "alias": alias,
            "registered": alias in registered,
            "has_runs": stats[alias]["runs"] > 0,
            "runs": stats[alias]["runs"],
            "contexts": stats[alias]["contexts"],
            "active_contexts": stats[alias]["active_contexts"],
            "last_activity": stats[alias]["last"].isoformat() if stats[alias]["last"] else None,
        }
        for alias in sorted(stats, key=order)
    ]


@route("GET", "/api/v1/meta/projects")
def projects(request: Request) -> dict:
    """Proyectos conocidos: registrados primero, después los alias detectados en runs o contextos."""
    from orchestrator import index as index_module
    from orchestrator.db import _conn

    try:
        registered = set(index_module.list_projects().keys())
    except Exception:
        registered = set()
    return {"projects": project_summaries(_conn(), registered)}
