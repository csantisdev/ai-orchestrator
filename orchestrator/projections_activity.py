"""Proyección Activity sin texto libre (spec §10.4)."""

from __future__ import annotations

import base64
import json
import math
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from orchestrator.projections import _token, to_utc

_KINDS = ("run", "tool_call", "alignment", "egress", "step_started", "step_completed", "mcp")
_RANK = {kind: index for index, kind in enumerate(_KINDS)}


def _cursor(value: Optional[str]) -> Optional[tuple[float, int, int]]:
    if value is None:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        parsed = json.loads(base64.urlsafe_b64decode((value + padding).encode("ascii")))
        day, rank, row_id = parsed["d"], parsed["r"], parsed["i"]
        if (not isinstance(day, (int, float)) or isinstance(day, bool) or not math.isfinite(day)
                or not isinstance(rank, int) or isinstance(rank, bool) or rank not in _RANK.values()
                or not isinstance(row_id, int) or isinstance(row_id, bool) or row_id < 1):
            raise ValueError
        return float(day), rank, row_id
    except (ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError):
        raise ValueError("invalid cursor") from None


def _encode_cursor(day: float, rank: int, row_id: int) -> str:
    raw = json.dumps({"d": day, "r": rank, "i": row_id}, separators=(",", ":")).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _number(value: object) -> Optional[float | int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def _item(kind: str, row: sqlite3.Row | tuple, attrs: dict, state: object, context: object = None,
          step: object = None, run: object = None) -> dict:
    row_id, day, ts = row[0], row[1], row[2]
    return {
        "id": f"{kind}:{row_id}", "kind": kind, "ts": to_utc(ts), "state": _token(state),
        "attrs": attrs,
        "refs": {
            "context": f"context:{context}" if isinstance(context, int) and context > 0 else None,
            "step": f"step:{step}" if isinstance(step, int) and step > 0 else None,
            "run": f"run:{run}" if isinstance(run, int) and run > 0 else None,
        },
        "_day": float(day), "_rank": _RANK[kind], "_row_id": row_id,
    }


def _rows(conn: sqlite3.Connection, sql: str, params: list, limit: int, cursor, kind: str) -> list:
    where = ""
    values = list(params)
    if cursor is not None:
        day, rank, row_id = cursor
        # La condición común usa el desempate global para poder paginar empates entre fuentes.
        where = (" WHERE (julianday(ts) < ? OR (julianday(ts) = ? AND (? > ? OR (? = ? AND id < ?))))")
        values.extend((day, day, _RANK[kind], rank, _RANK[kind], rank, row_id))
    if not where:
        where = ""
    return conn.execute("SELECT * FROM (" + sql + ") AS activity_source" + where
                        + " ORDER BY julianday(ts) DESC, id DESC LIMIT ?", [*values, limit + 1]).fetchall()


def project_activity(conn: sqlite3.Connection, project: str, limit: int = 50, cursor: Optional[str] = None,
                     now: Optional[datetime] = None) -> dict:
    """Une hitos del proyecto por instante UTC, con paginación estable."""
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    after = _cursor(cursor)
    items = []
    # Cada fuente conserva su propio LIMIT para que una fuente muy activa no oculte a las demás.
    for row in _rows(conn, "SELECT r.id, julianday(r.ts), r.ts, r.provider, r.model, r.status, r.cost_usd, r.duration_ms, r.step_id, s.context_id "
                     "FROM runs r LEFT JOIN steps s ON s.id = r.step_id "
                     "WHERE r.project = ? AND julianday(r.ts) IS NOT NULL", [project], limit, after, "run"):
        items.append(_item("run", row, {"provider": _token(row[3]), "model": _token(row[4]),
                                         "cost_usd": _number(row[6]), "duration_ms": _number(row[7])},
                           row[5], context=row[9], step=row[8], run=row[0]))
    for row in _rows(conn, "SELECT tc.id, julianday(tc.ts), tc.ts, tc.tool_name, tc.status, tc.duration_ms, tc.context_id, tc.step_id "
                     "FROM tool_calls tc JOIN contexts c ON c.id = tc.context_id "
                     "WHERE c.project = ? AND julianday(tc.ts) IS NOT NULL", [project], limit, after, "tool_call"):
        items.append(_item("tool_call", row, {"tool_name": _token(row[3]), "duration_ms": _number(row[5])}, row[4], row[6], row[7]))
    for row in _rows(conn, "SELECT a.id, julianday(a.ts), a.ts, a.agent, a.confirmed, a.context_id, a.step_id "
                     "FROM alignments a JOIN contexts c ON c.id = a.context_id "
                     "WHERE c.project = ? AND julianday(a.ts) IS NOT NULL", [project], limit, after, "alignment"):
        items.append(_item("alignment", row, {"agent": _token(row[3]), "confirmed": bool(row[4])},
                           "confirmed" if row[4] else "deviation", row[5], row[6]))
    for row in _rows(conn, "SELECT id, julianday(ts), ts, provider, phase, decision, reason_code, run_id "
                     "FROM egress_decisions WHERE project = ? AND julianday(ts) IS NOT NULL", [project], limit, after, "egress"):
        items.append(_item("egress", row, {"provider": _token(row[3]), "phase": _token(row[4]),
                                             "decision": _token(row[5]), "reason_code": _token(row[6])}, row[5], run=row[7]))
    for kind, column in (("step_started", "started_at"), ("step_completed", "completed_at")):
        status_filter = " AND s.status = 'completed'" if kind == "step_completed" else ""
        for row in _rows(conn, f"SELECT s.id, julianday(s.{column}), s.{column} AS ts, s.status, s.order_idx, s.provider, s.context_id "
                         f"FROM steps s JOIN contexts c ON c.id = s.context_id WHERE c.project = ? AND julianday(s.{column}) IS NOT NULL{status_filter}",
                         [project], limit, after, kind):
            items.append(_item(kind, row, {"idx": _number(row[4]), "provider": _token(row[5])}, row[3], row[6], row[0]))
    for row in _rows(conn, "SELECT id, julianday(ts), ts, tool_name, tool_category, client_surface, reason_code, is_error, status "
                     "FROM mcp_invocations WHERE project = ? AND tool_category != 'read' AND julianday(ts) IS NOT NULL",
                     [project], limit, after, "mcp"):
        items.append(_item("mcp", row, {"tool_name": _token(row[3]), "tool_category": _token(row[4]),
                                          "client_surface": _token(row[5]), "reason_code": _token(row[6]),
                                          "is_error": bool(row[7])}, row[8]))
    items.sort(key=lambda item: (-item["_day"], item["_rank"], -item["_row_id"]))
    more = len(items) > limit
    page = items[:limit]
    next_cursor = None
    if more and page:
        last = page[-1]
        next_cursor = _encode_cursor(last["_day"], last["_rank"], last["_row_id"])
    for item in page:
        item.pop("_day"); item.pop("_rank"); item.pop("_row_id")
    timestamp = now if now is not None else datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return {"items": page, "next_cursor": next_cursor,
            "metadata": {"project": project, "generated_at": timestamp.astimezone(timezone.utc).isoformat(),
                         "limit": limit, "sources": list(_KINDS)}}
