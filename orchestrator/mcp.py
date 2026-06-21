"""MCP server — contexto, pasos y alineamiento para agentes IA."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Callable

_HANDLERS: dict[str, Callable[[dict], Any]] = {}

TOOLS = [
    {
        "name": "get_context",
        "description": (
            "Retorna el contexto activo de un proyecto: objetivo, descripción y estado global. "
            "Úsalo antes de empezar a trabajar para confirmar alineamiento con el plan."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "context_id": {
                    "type": "integer",
                    "description": "ID del contexto. Si se omite, retorna el más reciente activo del proyecto.",
                },
                "project": {
                    "type": "string",
                    "description": "Alias del proyecto (requerido si no se pasa context_id).",
                },
            },
        },
    },
    {
        "name": "list_steps",
        "description": (
            "Lista los pasos ordenados de un contexto con su estado (pending/in_progress/completed/blocked/skipped). "
            "Úsalo para saber qué sigue y cuál es el paso activo."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["context_id"],
            "properties": {
                "context_id": {"type": "integer"},
            },
        },
    },
    {
        "name": "confirm_alignment",
        "description": (
            "Registra un checkpoint de alineamiento: el agente declara que está en la ruta correcta "
            "antes de ejecutar una acción significativa. Si confirmed=false, registra una desviación."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["step_id", "context_id", "agent", "checkpoint"],
            "properties": {
                "step_id":    {"type": "integer"},
                "context_id": {"type": "integer"},
                "agent":      {"type": "string", "description": "Nombre del agente (e.g. 'claude-code')."},
                "confirmed":  {"type": "boolean", "default": True},
                "checkpoint": {"type": "string", "description": "Qué se está confirmando."},
                "message":    {"type": "string", "default": ""},
            },
        },
    },
    {
        "name": "record_tool_call",
        "description": "Registra una invocación de herramienta realizada por el agente en un paso.",
        "inputSchema": {
            "type": "object",
            "required": ["step_id", "context_id", "tool_name"],
            "properties": {
                "step_id":    {"type": "integer"},
                "context_id": {"type": "integer"},
                "tool_name":  {"type": "string"},
                "input":      {"type": "object", "default": {}},
                "output":     {"type": "string", "default": ""},
                "status":     {"type": "string", "enum": ["ok", "error"], "default": "ok"},
                "duration_ms": {"type": "integer"},
            },
        },
    },
    {
        "name": "advance_step",
        "description": (
            "Marca el paso actual como completado y activa el siguiente pendiente del contexto. "
            "Retorna el nuevo paso activo o indica que el contexto está completo."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["step_id"],
            "properties": {
                "step_id": {"type": "integer"},
                "notes":   {"type": "string", "default": ""},
            },
        },
    },
]


def _tool_get_context(args: dict) -> dict:
    from orchestrator.db import _conn
    conn = _conn()
    context_id = args.get("context_id")
    project = args.get("project")
    if context_id:
        row = conn.execute("SELECT * FROM contexts WHERE id=?", (context_id,)).fetchone()
    elif project:
        row = conn.execute(
            "SELECT * FROM contexts WHERE project=? AND status='active' ORDER BY ts DESC LIMIT 1",
            (project,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM contexts WHERE status='active' ORDER BY ts DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return {"error": "no active context found"}
    return dict(row)


def _tool_list_steps(args: dict) -> dict:
    from orchestrator.db import _conn
    rows = _conn().execute(
        "SELECT * FROM steps WHERE context_id=? ORDER BY order_idx",
        (args["context_id"],),
    ).fetchall()
    return {"steps": [dict(r) for r in rows]}


def _tool_confirm_alignment(args: dict) -> dict:
    from orchestrator.db import _conn, _write_lock
    conn = _conn()
    ts = datetime.now(timezone.utc).isoformat()
    with _write_lock:
        cur = conn.execute(
            """INSERT INTO alignments (ts, step_id, context_id, agent, confirmed, checkpoint, message)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                ts,
                args["step_id"],
                args["context_id"],
                args.get("agent", ""),
                1 if args.get("confirmed", True) else 0,
                args.get("checkpoint", ""),
                args.get("message", ""),
            ),
        )
        conn.commit()
    return {"id": cur.lastrowid, "ts": ts, "confirmed": args.get("confirmed", True)}


def _tool_record_tool_call(args: dict) -> dict:
    from orchestrator.db import _conn, _write_lock
    conn = _conn()
    ts = datetime.now(timezone.utc).isoformat()
    with _write_lock:
        cur = conn.execute(
            """INSERT INTO tool_calls (ts, step_id, context_id, tool_name, input, output, status, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ts,
                args["step_id"],
                args["context_id"],
                args.get("tool_name", ""),
                json.dumps(args.get("input", {}), ensure_ascii=False),
                args.get("output", ""),
                args.get("status", "ok"),
                args.get("duration_ms"),
            ),
        )
        conn.commit()
    return {"id": cur.lastrowid, "ts": ts}


def _tool_advance_step(args: dict) -> dict:
    from orchestrator.db import _conn, _write_lock
    conn = _conn()
    ts = datetime.now(timezone.utc).isoformat()
    step_id = args["step_id"]
    with _write_lock:
        step = conn.execute("SELECT * FROM steps WHERE id=?", (step_id,)).fetchone()
        if step is None:
            raise ValueError(f"step {step_id} not found")
        context_id = step["context_id"]
        conn.execute(
            "UPDATE steps SET status='completed', completed_at=?, notes=? WHERE id=?",
            (ts, args.get("notes", ""), step_id),
        )
        next_step = conn.execute(
            """SELECT * FROM steps
               WHERE context_id=? AND order_idx > ? AND status='pending'
               ORDER BY order_idx LIMIT 1""",
            (context_id, step["order_idx"]),
        ).fetchone()
        context_done = False
        if next_step:
            conn.execute(
                "UPDATE steps SET status='in_progress', started_at=? WHERE id=?",
                (ts, next_step["id"]),
            )
        else:
            conn.execute(
                "UPDATE contexts SET status='completed', updated_at=? WHERE id=?",
                (ts, context_id),
            )
            context_done = True
        conn.commit()
    return {
        "completed_step_id": step_id,
        "next_step": dict(next_step) if next_step else None,
        "context_done": context_done,
    }


_HANDLERS.update({
    "get_context":        _tool_get_context,
    "list_steps":         _tool_list_steps,
    "confirm_alignment":  _tool_confirm_alignment,
    "record_tool_call":   _tool_record_tool_call,
    "advance_step":       _tool_advance_step,
})


def _dispatch(name: str, args: dict) -> Any:
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"tool not implemented: {name}")
    return handler(args)


def _respond(msg_id: Any, result: Any) -> None:
    sys.stdout.write(
        json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}, ensure_ascii=False) + "\n"
    )
    sys.stdout.flush()


def _error(msg_id: Any, code: int, message: str) -> None:
    sys.stdout.write(
        json.dumps({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}, ensure_ascii=False) + "\n"
    )
    sys.stdout.flush()


def main() -> None:
    from orchestrator.db import init_db
    init_db()

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "notifications/initialized":
            continue

        try:
            if method == "initialize":
                _respond(msg_id, {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "ai-orchestrator", "version": "0.1.0"},
                })
            elif method == "tools/list":
                _respond(msg_id, {"tools": TOOLS})
            elif method == "tools/call":
                name = params.get("name", "")
                args = params.get("arguments") or {}
                result = _dispatch(name, args)
                _respond(msg_id, {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
                })
            elif msg_id is not None:
                _error(msg_id, -32601, f"method not found: {method}")
        except Exception as exc:
            if msg_id is not None:
                _error(msg_id, -32603, str(exc))


if __name__ == "__main__":
    main()
