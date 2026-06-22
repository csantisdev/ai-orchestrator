"""MCP server — contexto, pasos y alineamiento para agentes IA."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Callable

_HANDLERS: dict[str, Callable[[dict], Any]] = {}

SERVER_INSTRUCTIONS = (
    "Use this server to coordinate work in ai-orchestrator. At the start of a "
    "substantial task call get_context(project='ai-orchestrator'); if an active "
    "context exists, call list_steps and work on its in_progress step. Use "
    "confirm_alignment before significant changes and advance_step only after "
    "implementation and verification are complete. Create a context only when "
    "no suitable active context exists. Do not skip or complete steps merely "
    "to clean up tracking."
)

SUPPORTED_PROTOCOL_VERSIONS = {
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
}
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

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
    {
        "name": "skip_step",
        "description": (
            "Marca un paso como omitido (skipped) sin ejecutarlo. "
            "Funciona sobre steps en estado pending o in_progress. "
            "Si el step estaba in_progress, activa el siguiente pending del contexto."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["step_id"],
            "properties": {
                "step_id": {"type": "integer"},
                "reason":  {"type": "string", "default": "", "description": "Motivo por el que se omite el paso."},
            },
        },
    },
    {
        "name": "create_context",
        "description": (
            "Crea un nuevo contexto de trabajo para un proyecto con pasos opcionales. "
            "Úsalo al inicio de una tarea estructurada para habilitar el tracking de pasos, "
            "alineamientos y tool calls desde el agente — sin necesidad de CLI."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["project", "title"],
            "properties": {
                "project":     {"type": "string", "description": "Alias del proyecto registrado."},
                "title":       {"type": "string", "description": "Objetivo o título del contexto."},
                "description": {"type": "string", "default": ""},
                "steps": {
                    "type": "array",
                    "description": "Pasos iniciales del contexto (opcional).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title":    {"type": "string"},
                            "provider": {"type": "string", "default": ""},
                        },
                        "required": ["title"],
                    },
                },
                "parent_step_id": {
                    "type": "integer",
                    "description": "ID del step que originó este contexto. Permite trazar la relación entre contextos.",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "programado"],
                    "default": "active",
                    "description": "Estado inicial. 'programado' indica trabajo planificado pero no iniciado aún.",
                },
            },
        },
    },
    {
        "name": "add_step",
        "description": (
            "Agrega un paso a un contexto existente. "
            "Útil para extender el plan de trabajo durante la ejecución."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["context_id", "title"],
            "properties": {
                "context_id":  {"type": "integer"},
                "title":       {"type": "string"},
                "provider":    {"type": "string", "default": ""},
                "description": {"type": "string", "default": ""},
                "order_idx":   {"type": "integer", "description": "Posición del paso. Si se omite, se agrega al final."},
            },
        },
    },
    {
        "name": "update_context",
        "description": (
            "Edita el título, descripción y/o estado de un contexto existente. "
            "Solo se actualizan los campos presentes en la llamada — los campos omitidos no se tocan. "
            "Útil para corregir contenido o transicionar un contexto de 'programado' a 'active'."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["context_id"],
            "properties": {
                "context_id":  {"type": "integer", "description": "ID del contexto a editar."},
                "title":       {"type": "string",  "description": "Nuevo título. Si se omite, no se modifica."},
                "description": {"type": "string",  "description": "Nueva descripción. Si se omite, no se modifica."},
                "status": {
                    "type": "string",
                    "enum": ["active", "programado", "completed", "abandoned"],
                    "description": "Nuevo estado. Si se omite, no se modifica.",
                },
            },
        },
    },
    {
        "name": "update_step",
        "description": (
            "Edita el título, descripción y/o notas de un paso existente. "
            "Solo se actualizan los campos presentes en la llamada — los campos omitidos no se tocan. "
            "No modifica estado, timestamps ni el orden del paso."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["step_id"],
            "properties": {
                "step_id":     {"type": "integer", "description": "ID del paso a editar."},
                "title":       {"type": "string",  "description": "Nuevo título. Si se omite, no se modifica."},
                "description": {"type": "string",  "description": "Nueva descripción. Si se omite, no se modifica."},
                "notes":       {"type": "string",  "description": "Nuevas notas. Si se omite, no se modifica."},
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


def _tool_skip_step(args: dict) -> dict:
    from orchestrator.db import _conn, _write_lock
    conn = _conn()
    ts = datetime.now(timezone.utc).isoformat()
    step_id = args["step_id"]
    with _write_lock:
        step = conn.execute("SELECT * FROM steps WHERE id=?", (step_id,)).fetchone()
        if step is None:
            raise ValueError(f"step {step_id} not found")
        if step["status"] not in ("pending", "in_progress"):
            raise ValueError(f"step {step_id} is '{step['status']}' — only pending/in_progress can be skipped")
        context_id = step["context_id"]
        was_active = step["status"] == "in_progress"
        conn.execute(
            "UPDATE steps SET status='skipped', completed_at=?, notes=? WHERE id=?",
            (ts, args.get("reason", ""), step_id),
        )
        next_step = None
        if was_active:
            next_step = conn.execute(
                """SELECT * FROM steps
                   WHERE context_id=? AND order_idx > ? AND status='pending'
                   ORDER BY order_idx LIMIT 1""",
                (context_id, step["order_idx"]),
            ).fetchone()
            if next_step:
                conn.execute(
                    "UPDATE steps SET status='in_progress', started_at=? WHERE id=?",
                    (ts, next_step["id"]),
                )
        conn.commit()
    return {
        "skipped_step_id": step_id,
        "was_active": was_active,
        "next_step": dict(next_step) if next_step else None,
    }


def _tool_create_context(args: dict) -> dict:
    from orchestrator.db import insert_context, insert_step
    project = args.get("project", "").strip()
    title = args.get("title", "").strip()
    if not project or not title:
        raise ValueError("project y title son requeridos")
    status = args.get("status", "active")
    if status not in ("active", "programado"):
        status = "active"
    ctx_id = insert_context(project, title, args.get("description", ""), parent_step_id=args.get("parent_step_id"), status=status)
    steps_out = []
    for i, s in enumerate(args.get("steps", []) or [], 1):
        step_title = (s.get("title", "") if isinstance(s, dict) else str(s)).strip()
        provider = s.get("provider", "") if isinstance(s, dict) else ""
        if step_title:
            sid = insert_step(ctx_id, i, step_title, provider=provider)
            steps_out.append({"id": sid, "order_idx": i, "title": step_title, "provider": provider})
    return {"context_id": ctx_id, "project": project, "title": title, "steps": steps_out, "parent_step_id": args.get("parent_step_id")}


def _tool_update_context(args: dict) -> dict:
    from orchestrator.db import _conn, _write_lock
    context_id = args.get("context_id")
    if not context_id:
        raise ValueError("context_id es requerido")
    conn = _conn()
    row = conn.execute("SELECT * FROM contexts WHERE id=?", (context_id,)).fetchone()
    if row is None:
        raise ValueError(f"context {context_id} not found")

    _VALID_STATUSES = {"active", "programado", "completed", "abandoned"}
    fields, params = [], []
    for col in ("title", "description"):
        if col in args:
            fields.append(f"{col}=?")
            params.append(args[col])
    if "status" in args:
        if args["status"] not in _VALID_STATUSES:
            raise ValueError(f"status inválido: {args['status']!r}")
        fields.append("status=?")
        params.append(args["status"])

    if not fields:
        return {"context_id": context_id, "updated": []}

    ts = datetime.now(timezone.utc).isoformat()
    fields.append("updated_at=?")
    params.extend([ts, context_id])

    with _write_lock:
        conn.execute(
            f"UPDATE contexts SET {', '.join(fields)} WHERE id=?",
            params,
        )
        conn.commit()

    updated_fields = [f for f in ("title", "description", "status") if f in args]
    return {"context_id": context_id, "updated": updated_fields, "updated_at": ts}


def _tool_update_step(args: dict) -> dict:
    from orchestrator.db import _conn, _write_lock
    step_id = args.get("step_id")
    if not step_id:
        raise ValueError("step_id es requerido")
    conn = _conn()
    row = conn.execute("SELECT * FROM steps WHERE id=?", (step_id,)).fetchone()
    if row is None:
        raise ValueError(f"step {step_id} not found")

    fields, params = [], []
    for col in ("title", "description", "notes"):
        if col in args:
            fields.append(f"{col}=?")
            params.append(args[col])

    if not fields:
        return {"step_id": step_id, "updated": []}

    params.append(step_id)
    with _write_lock:
        conn.execute(
            f"UPDATE steps SET {', '.join(fields)} WHERE id=?",
            params,
        )
        conn.commit()

    updated_fields = [f for f in ("title", "description", "notes") if f in args]
    return {"step_id": step_id, "updated": updated_fields}


def _tool_add_step(args: dict) -> dict:
    from orchestrator.db import _conn, insert_step
    context_id = args.get("context_id")
    title = args.get("title", "").strip()
    if not context_id or not title:
        raise ValueError("context_id y title son requeridos")
    conn = _conn()
    row = conn.execute(
        "SELECT COALESCE(MAX(order_idx), 0) FROM steps WHERE context_id=?",
        (context_id,),
    ).fetchone()
    order_idx = args.get("order_idx") or (row[0] + 1)
    provider = args.get("provider", "")
    description = args.get("description", "")
    sid = insert_step(context_id, order_idx, title, description=description, provider=provider)
    return {"step_id": sid, "context_id": context_id, "order_idx": order_idx, "title": title, "provider": provider}


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
            unresolved = conn.execute(
                """SELECT COUNT(*) FROM steps
                   WHERE context_id=? AND id!=? AND status IN ('pending','in_progress')""",
                (context_id, step_id),
            ).fetchone()[0]
            if unresolved == 0:
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
    "skip_step":          _tool_skip_step,
    "create_context":     _tool_create_context,
    "add_step":           _tool_add_step,
    "update_context":     _tool_update_context,
    "update_step":        _tool_update_step,
})


def _dispatch(name: str, args: dict) -> Any:
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"tool not implemented: {name}")
    return handler(args)


def _respond(msg_id: Any, result: Any) -> None:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": msg_id, "result": result},
        ensure_ascii=True,
    )
    sys.stdout.write(payload + "\n")
    sys.stdout.flush()


def _error(msg_id: Any, code: int, message: str) -> None:
    sys.stdout.write(
        json.dumps({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}, ensure_ascii=False) + "\n"
    )
    sys.stdout.flush()


def _tool_call_result(result: Any) -> dict:
    """Return a result shape supported by modern and legacy MCP clients."""
    return {
        "structuredContent": result,
        "content": [
            {
                "type": "text",
                "text": json.dumps(result, ensure_ascii=False, indent=2),
            }
        ],
    }


def main() -> None:
    from orchestrator.db import init_db
    init_db()

    # On Windows the default stdin encoding is cp1252; clients send UTF-8 JSON.
    # Reconfigure before reading to prevent mojibake in stored text.
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")

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
                requested_version = params.get("protocolVersion", "")
                protocol_version = (
                    requested_version
                    if requested_version in SUPPORTED_PROTOCOL_VERSIONS
                    else DEFAULT_PROTOCOL_VERSION
                )
                _respond(msg_id, {
                    "protocolVersion": protocol_version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "ai-orchestrator", "version": "0.4.0"},
                    "instructions": SERVER_INSTRUCTIONS,
                })
            elif method == "ping":
                _respond(msg_id, {})
            elif method == "tools/list":
                _respond(msg_id, {"tools": TOOLS})
            elif method == "tools/call":
                name = params.get("name", "")
                args = params.get("arguments") or {}
                result = _dispatch(name, args)
                _respond(msg_id, _tool_call_result(result))
            elif msg_id is not None:
                _error(msg_id, -32601, f"method not found: {method}")
        except Exception as exc:
            if msg_id is not None:
                _error(msg_id, -32603, str(exc))


if __name__ == "__main__":
    main()
