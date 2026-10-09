"""Catálogo único de comandos de la UI (RFC-010 §3.1).

Cada comando es un adaptador de la función de dominio que usa la herramienta MCP equivalente
(`domain_tool`, resuelta en `orchestrator.mcp._HANDLERS`): no hay dos implementaciones de la
misma operación. El comando solo traduce sus argumentos y arma el recibo, que lleva IDs y
conteos, nunca texto libre (I3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from orchestrator.mcp_governance import CATEGORIES


@dataclass(frozen=True)
class Command:
    name: str
    category: str
    schema: dict
    domain_tool: str
    to_domain: Callable[[dict], dict]
    # Objeto dueño: ("context" | "step", argumento con su id). Da el proyecto y la versión.
    owner: tuple[str, str]
    receipt: Callable[[dict, Any], dict]
    versioned: bool = False
    destructive: bool = False
    is_job: bool = False
    calls_provider: bool = False
    resources: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"categoría desconocida: {self.category}")
        if self.owner[0] not in {"context", "step"}:
            raise ValueError(f"dueño desconocido: {self.owner[0]}")


def _confirm_alignment_args(args: dict) -> dict:
    return {
        "step_id": args["step_id"],
        "context_id": args["context_id"],
        "agent": "dashboard",
        "confirmed": args.get("confirmed", True),
        "checkpoint": args["checkpoint"],
        "message": args.get("message", ""),
    }


def _open_steps(context_id: int) -> int:
    from orchestrator.db import _conn
    return _conn().execute(
        "SELECT COUNT(*) FROM steps WHERE context_id=? AND status IN ('pending', 'in_progress', 'blocked')",
        (context_id,),
    ).fetchone()[0]


_COMMANDS = (
    Command(
        name="confirm_alignment",
        category="append",
        schema={
            "type": "object",
            "required": ["step_id", "context_id", "checkpoint"],
            "properties": {
                "step_id": {"type": "integer", "minimum": 1},
                "context_id": {"type": "integer", "minimum": 1},
                "checkpoint": {"type": "string", "minLength": 1},
                "message": {"type": "string"},
                "confirmed": {"type": "boolean"},
            },
        },
        domain_tool="confirm_alignment",
        to_domain=_confirm_alignment_args,
        owner=("context", "context_id"),
        receipt=lambda args, result: {
            "affected": {"alignment_id": result["id"], "step_id": args["step_id"],
                         "context_id": args["context_id"]},
        },
    ),
    Command(
        name="append_step_notes",
        category="workflow_mutation",
        schema={
            "type": "object",
            "required": ["step_id", "notes"],
            "properties": {
                "step_id": {"type": "integer", "minimum": 1},
                "notes": {"type": "string", "minLength": 1},
            },
        },
        domain_tool="update_step",
        to_domain=lambda args: {"step_id": args["step_id"], "notes_append": args["notes"]},
        owner=("step", "step_id"),
        versioned=True,
        receipt=lambda args, result: {"affected": {"step_id": args["step_id"]}},
    ),
    Command(
        name="close_context",
        category="workflow_transition",
        schema={
            "type": "object",
            "required": ["context_id", "status"],
            "properties": {
                "context_id": {"type": "integer", "minimum": 1},
                "status": {"type": "string", "enum": ["completed", "abandoned"]},
            },
        },
        domain_tool="update_context",
        to_domain=lambda args: {"context_id": args["context_id"], "status": args["status"]},
        owner=("context", "context_id"),
        versioned=True,
        receipt=lambda args, result: {
            "affected": {"context_id": args["context_id"]},
            "counts": {"open_steps": _open_steps(args["context_id"])},
        },
    ),
)

CATALOG: dict[str, Command] = {command.name: command for command in _COMMANDS}


def domain_handler(command: Command) -> Callable[[dict], Any]:
    from orchestrator import mcp
    return mcp._HANDLERS[command.domain_tool]


def get(name: str) -> Optional[Command]:
    return CATALOG.get(name)
