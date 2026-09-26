"""Read-only diagnostics for tracked contexts and steps."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def tracking_health_warnings(
    conn: Any,
    registered_projects: Iterable[str],
    *,
    now: datetime | None = None,
    stale_in_progress_days: int = 7,
    stale_scheduled_days: int = 60,
    project: str | None = None,
) -> list[dict[str, str]]:
    """Return actionable warnings without changing tracking records.

    ``project`` limits the diagnosis to one alias; ``registered_projects`` must
    still list every registered alias so the registration check stays accurate.
    """
    now = now or datetime.now(timezone.utc)
    registered = set(registered_projects)
    warnings: list[dict[str, str]] = []
    project_filter = " AND project=?" if project else ""
    project_params: tuple[str, ...] = (project,) if project else ()

    active_projects = conn.execute(
        f"""SELECT project, COUNT(*) AS count FROM contexts
           WHERE status='active'{project_filter} GROUP BY project HAVING COUNT(*) > 1""",
        project_params,
    ).fetchall()
    for row in active_projects:
        warnings.append({
            "code": "multiple_active_contexts",
            "message": f"{row['project']}: {row['count']} contextos active",
            "hint": "Dejá un único contexto active o marcá los demás como programado, completed o abandoned.",
        })

    contexts = conn.execute(
        f"""SELECT * FROM contexts WHERE status IN ('active', 'programado'){project_filter}
           ORDER BY id""",
        project_params,
    ).fetchall()
    for context in contexts:
        context_id = context["id"]
        project = context["project"]
        if project not in registered:
            warnings.append({
                "code": "context_project_unregistered",
                "message": f"contexto #{context_id} ({project}) no está registrado en index.yaml",
                "hint": "Registrá el proyecto o cerrá/archivá el contexto que ya no corresponda.",
            })

        if context["status"] == "active":
            state = conn.execute(
                """SELECT
                       SUM(status='pending') AS pending_count,
                       SUM(status='in_progress') AS active_count
                   FROM steps WHERE context_id=?""",
                (context_id,),
            ).fetchone()
            if (state["pending_count"] or 0) and not (state["active_count"] or 0):
                warnings.append({
                    "code": "no_step_in_progress",
                    "message": f"contexto #{context_id} ({project}) tiene pasos pending y ninguno in_progress",
                    "hint": "Usá start_step para activar el paso que se va a trabajar.",
                })

            active_steps = conn.execute(
                "SELECT * FROM steps WHERE context_id=? AND status='in_progress'",
                (context_id,),
            ).fetchall()
            for step in active_steps:
                timestamps = [_parse_datetime(step["started_at"])]
                for table in ("alignments", "tool_calls", "runs"):
                    row = conn.execute(
                        f"SELECT MAX(ts) AS ts FROM {table} WHERE step_id=?", (step["id"],)
                    ).fetchone()
                    timestamps.append(_parse_datetime(row["ts"]))
                activity = max((item for item in timestamps if item is not None), default=None)
                if activity and now - activity > timedelta(days=stale_in_progress_days):
                    age = (now - activity).days
                    warnings.append({
                        "code": "stale_in_progress_step",
                        "message": f"paso #{step['id']} del contexto #{context_id} sin actividad hace {age} día(s)",
                        "hint": "Retomalo y registrá actividad, o usá reset_step para devolverlo a pending.",
                    })

        if context["status"] == "programado":
            created = _parse_datetime(context["ts"])
            if created and now - created > timedelta(days=stale_scheduled_days):
                age = (now - created).days
                warnings.append({
                    "code": "stale_scheduled_context",
                    "message": f"contexto programado #{context_id} ({project}) creado hace {age} día(s)",
                    "hint": "Confirmá si sigue vigente o cerralo/actualizalo antes de iniciarlo.",
                })
    return warnings
