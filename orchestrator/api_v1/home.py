"""Read-only projection for the dashboard Inicio view."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from orchestrator.api_v1 import Request, route
from orchestrator.projections import normalize_agent, parse_instant, to_utc
from orchestrator.tracking_health import tracking_health_warnings, tracking_thresholds


def _inside(value: object, start: datetime, end: datetime) -> bool:
    instant = parse_instant(value)
    return instant is not None and start <= instant < end


def _detail(items: dict[str, int]) -> list[dict[str, Any]]:
    return [{"label": key, "value": value} for key, value in sorted(items.items())]


def build_overview(conn: Any, project: str, *, registered: set[str], now: datetime,
                   period: str = "7d", thresholds: tuple[int, int] = (7, 60)) -> dict:
    """Build the Overview DTO; timestamp comparisons deliberately happen in Python."""
    if period not in {"7d", "30d"}:
        raise ValueError("period must be '7d' or '30d'")
    if project not in registered and not conn.execute("SELECT 1 FROM runs WHERE project=? LIMIT 1", (project,)).fetchone():
        return {"_unknown": True}
    # Callers pass a datetime; parse_instant is reserved for SQLite TEXT timestamps.
    now = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    start = now - timedelta(days=int(period[:-1]))
    active_contexts = conn.execute("SELECT COUNT(*) FROM contexts WHERE project=? AND status='active'", (project,)).fetchone()[0]
    progress = conn.execute("""SELECT COUNT(*) FROM steps s JOIN contexts c ON c.id=s.context_id
                              WHERE c.project=? AND s.status='in_progress'""", (project,)).fetchone()[0]
    warnings = tracking_health_warnings(conn, registered, project=project, now=now,
                                        stale_in_progress_days=thresholds[0], stale_scheduled_days=thresholds[1])
    stale = [warning for warning in warnings if warning["code"] == "stale_in_progress_step"]
    alerts = [warning for warning in warnings if warning["code"] != "stale_in_progress_step"]
    invocations = conn.execute("SELECT ts, client_surface, status, is_error, reason_code, tool_category FROM mcp_invocations WHERE project=?", (project,)).fetchall()
    activity: dict[str, int] = {}
    denials: dict[str, int] = {}
    for row in invocations:
        if _inside(row["ts"], now - timedelta(hours=24), now) and row["tool_category"] != "read":
            agent = normalize_agent(row["client_surface"])
            activity[agent] = activity.get(agent, 0) + 1
        if _inside(row["ts"], start, now) and (row["status"] == "denied" or row["is_error"]):
            reason = row["reason_code"] or "sin código"
            denials[reason] = denials.get(reason, 0) + 1
    runs = [row for row in conn.execute("SELECT ts, cost_usd, step_id FROM runs WHERE project=?", (project,)) if _inside(row["ts"], start, now)]
    cost = sum((row["cost_usd"] or 0) for row in runs)
    completed_without_start = conn.execute("""SELECT COUNT(*) FROM steps s JOIN contexts c ON c.id=s.context_id
                                             WHERE c.project=? AND s.status='completed' AND s.started_at IS NULL""", (project,)).fetchone()[0]
    skipped = conn.execute("""SELECT COUNT(*) FROM steps s JOIN contexts c ON c.id=s.context_id
                             WHERE c.project=? AND s.status='skipped'""", (project,)).fetchone()[0]
    links = {"work": {"view": "trabajo", "tab": None, "params": {}}, "governance": {"view": "gobernanza", "tab": None, "params": {}}, "cost": {"view": "ejecuciones", "tab": "costos", "params": {}}}
    metrics = [
        {"id":"active_contexts", "label":"Contextos activos", "value":active_contexts, "unit":"count", "detail":[], "source":"Cuenta los contextos del proyecto con estado active.", "link":links["work"]},
        {"id":"steps_in_progress", "label":"Pasos en curso", "value":progress, "unit":"count", "detail":[], "source":"Cuenta los pasos in_progress de los contextos del proyecto.", "link":links["work"]},
        {"id":"stale_steps", "label":"Pasos estancados", "value":len(stale), "unit":"count", "detail":[], "source":"Cuenta las advertencias de pasos in_progress sin actividad según la configuración de tracking.", "link":links["work"]},
        {"id":"agent_activity_24h", "label":"Actividad de agentes (24 h)", "value":sum(activity.values()), "unit":"count", "detail":_detail(activity), "source":"Cuenta invocaciones MCP no read del proyecto en las últimas 24 horas.", "link":links["governance"]},
        {"id":"mcp_denied_or_error", "label":"MCP denegadas o con error", "value":sum(denials.values()), "unit":"count", "detail":_detail(denials), "source":"Cuenta invocaciones MCP denegadas o marcadas con error durante el período.", "link":links["governance"]},
        {"id":"cost_period", "label":"Costo del período", "value":cost, "unit":"usd", "detail":[{"label":"runs", "value":len(runs)}, {"label":"runs con step_id", "value":sum(row["step_id"] is not None for row in runs)}], "source":"Suma cost_usd de los runs del proyecto durante el período; los nulos valen cero.", "link":links["cost"]},
        {"id":"tracking_health", "label":"Salud del tracking", "value":len(warnings), "unit":"count", "detail":[], "source":"Cuenta las advertencias accionables del diagnóstico de tracking del proyecto.", "link":links["work"]},
    ]
    egress_count = conn.execute("SELECT COUNT(*) FROM egress_decisions WHERE project=?", (project,)).fetchone()[0]
    egress = {"state":"available", "count":egress_count, "message":"Hay decisiones de egress registradas para el proyecto."} if egress_count else {"state":"empty", "message":"Los runs importados no pasan por el gate de egress, por eso todavía no hay decisiones."}
    return {"project":project, "generated_at":to_utc(now.isoformat()), "period":{"key":period,"from":to_utc(start.isoformat()),"to":to_utc(now.isoformat())}, "metrics":metrics, "alerts":alerts, "tracking_health":{"warning_count":len(warnings),"warnings":warnings,"data_quality":{"completed_without_start":completed_without_start,"skipped":skipped}}, "egress":egress}


@route("GET", "/api/v1/projects/{project}/overview")
def overview(request: Request):
    from orchestrator import db, index
    from orchestrator.config import ConfigError, load_config
    try: registered = set(index.list_projects())
    except Exception: registered = set()
    try: config = load_config()
    except ConfigError: config = {}
    tracking = config.get("tracking", {}) if isinstance(config.get("tracking", {}), dict) else {}
    result = build_overview(db._conn(), request.params["project"], registered=registered,
                            now=datetime.now(timezone.utc), period=request.arg("period", "7d") or "7d",
                            thresholds=tracking_thresholds(tracking))
    return (404, {"error":"unknown project"}) if result.pop("_unknown", False) else result
