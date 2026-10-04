"""Runs y costos de solo lectura para Ejecuciones (spec §23.3)."""
from __future__ import annotations

import base64
import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone

from orchestrator.api_v1 import Request, route
from orchestrator.api_v1.work import _registered_projects, project_known
from orchestrator.git_scanner import PROVIDER_NAME as GIT_PROVIDER
from orchestrator.projections import normalize_agent, parse_instant, to_utc

PERIODS = {"7d": 7, "30d": 30, "90d": 90}

def _cost(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None

def _source(provider, session_id):
    if provider == GIT_PROVIDER: return "commit"
    return "session" if session_id else "router"

def _cursor(value):
    if not value: return None
    try:
        raw = base64.urlsafe_b64decode(value.encode() + b"=" * (-len(value) % 4))
        instant, row_id = json.loads(raw)
        if instant is not None and (not isinstance(instant, str) or parse_instant(instant) is None): raise ValueError
        if not isinstance(row_id, int) or row_id < 1: raise ValueError
        return instant, row_id
    except Exception as exc: raise ValueError("cursor inválido") from exc

def _encode(instant, row_id):
    return base64.urlsafe_b64encode(json.dumps([instant, row_id], separators=(",", ":")).encode()).decode().rstrip("=")

def _rows(conn, project, source):
    sql = """SELECT r.id,r.ts,r.provider,r.model,r.status,r.task_preview,r.input_tokens,r.output_tokens,
             r.duration_ms,r.cost_usd,r.rating,r.routing_source,r.step_id,r.session_id,c.id
             FROM runs r LEFT JOIN steps s ON s.id=r.step_id LEFT JOIN contexts c ON c.id=s.context_id AND c.project=?
             WHERE r.project=? ORDER BY julianday(r.ts) DESC, r.id DESC"""
    rows = conn.execute(sql, (project, project)).fetchall()
    result=[]
    for row in rows:
        kind = _source(row[2], row[13])
        if source != "all" and kind != source: continue
        instant = to_utc(row[1])
        preview = (row[5] or "").splitlines()[0][:160]
        result.append({"id":row[0],"ts":instant,"source":kind,"provider":row[2] or "","model":row[3] or "","status":row[4] or "",
          "task_preview":preview,"input_tokens":row[6],"output_tokens":row[7],"duration_ms":row[8],"cost_usd":_cost(row[9]),
          "rating":row[10],"routing_source":row[11],"step_id":row[12] if row[14] else None,"context_id":row[14]})
    # SQLite's julianday ordering is reproduced by UTC instants; invalid timestamps are last.
    return sorted(result, key=lambda r: (r["ts"] is None, r["ts"] or "", r["id"]), reverse=True)

def list_runs(conn, project, *, limit=50, cursor=None, source="all"):
    if not 1 <= limit <= 100: raise ValueError("limit debe estar entre 1 y 100")
    if source not in ("all", "router", "session", "commit"): raise ValueError("source inválido")
    rows = _rows(conn, project, source); mark = _cursor(cursor)
    if mark:
        rows = [r for r in rows if ((r["ts"] is None, r["ts"] or "", r["id"]) < (mark[0] is None, mark[0] or "", mark[1]))]
    page = rows[:limit]; more = len(rows) > limit
    return {"project":project,"source":source,"runs":page,"next_cursor":_encode(page[-1]["ts"], page[-1]["id"]) if more else None}

def costs(conn, project, period, *, now=None):
    if period not in PERIODS: raise ValueError("period inválido")
    now = now or datetime.now(timezone.utc); start = now - timedelta(days=PERIODS[period])
    rows = _rows(conn, project, "all")
    selected=[r for r in rows if r["ts"] and (instant:=parse_instant(r["ts"])) and start <= instant <= now]
    total=sum(r["cost_usd"] or 0 for r in selected); with_cost=[r for r in selected if r["cost_usd"] is not None]
    attributed=[r for r in selected if r["context_id"] is not None]
    days={ (start.date()+timedelta(days=i)).isoformat(): 0.0 for i in range(PERIODS[period]+1) }
    groups={}; agents={}
    titles={row[0]:row[1] for row in conn.execute("SELECT id,title FROM contexts WHERE project=?", (project,))}
    for r in selected:
        day=parse_instant(r["ts"]).date().isoformat(); days[day]+=r["cost_usd"] or 0
        key=r["context_id"]
        item=groups.setdefault(key,{"context_id":key,"title":titles.get(key, "Sin paso"),"cost_usd":0.0,"runs":0})
        item["runs"]+=1; item["cost_usd"]+=r["cost_usd"] or 0
        agent="git" if r["source"] == "commit" else normalize_agent(r["provider"])
        item=agents.setdefault(agent,{"agent":agent,"cost_usd":0.0,"runs":0}); item["runs"]+=1; item["cost_usd"]+=r["cost_usd"] or 0
    return {"project":project,"period":{"key":period,"from":to_utc(start.isoformat()),"to":to_utc(now.isoformat())},
      "totals":{"cost_usd":total,"runs":len(selected),"runs_with_cost":len(with_cost),"attributed_runs":len(attributed),"attributed_cost_usd":sum(r["cost_usd"] or 0 for r in attributed)},
      "daily":[{"date":k,"cost_usd":v} for k,v in days.items()],"by_context":sorted(groups.values(),key=lambda x:(-x["cost_usd"],x["context_id"] or 0)),"by_agent":sorted(agents.values(),key=lambda x:(-x["cost_usd"],x["agent"]))}

@route("GET", "/api/v1/projects/{project}/runs")
def runs_endpoint(request: Request):
    from orchestrator import db
    conn=db._conn(); project=request.params["project"]
    if not project_known(conn, project, _registered_projects()): return 404,{"error":"unknown project"}
    raw=request.arg("limit", "50")
    try: limit=int(raw)
    except (TypeError, ValueError): raise ValueError("limit debe ser un entero")
    return list_runs(conn,project,limit=limit,cursor=request.arg("cursor"),source=request.arg("source","all") or "all")

@route("GET", "/api/v1/projects/{project}/costs")
def costs_endpoint(request: Request):
    from orchestrator import db
    conn=db._conn(); project=request.params["project"]
    if not project_known(conn, project, _registered_projects()): return 404,{"error":"unknown project"}
    return costs(conn,project,request.arg("period","30d") or "30d")
