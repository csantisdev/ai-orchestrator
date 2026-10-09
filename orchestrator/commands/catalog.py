"""Catálogo único de comandos de la UI (RFC-010 §3.1, §3.3).

Un comando es de uno de dos tipos:

- **Inmediato:** adapta la función de dominio de la herramienta MCP equivalente
  (`domain_tool`, resuelta en `orchestrator.mcp._HANDLERS`): no hay dos implementaciones de la
  misma operación.
- **Trabajo** (`job`): responde `accepted` con un `job_id` y corre en segundo plano con los
  recursos que declara (§3.3). Llama a las mismas funciones que la CLI y las rutas heredadas.

El recibo de ambos lleva IDs y conteos, nunca texto libre (I3).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional

from orchestrator.mcp_governance import ADMIN_ONLY_CATEGORIES, CATEGORIES
from orchestrator.paths import PROVIDERS

if TYPE_CHECKING:
    from orchestrator.commands.jobs import JobContext


def _no_receipt(args: dict, result: Any) -> dict:
    return {}


@dataclass(frozen=True)
class Command:
    name: str
    category: str
    schema: dict
    # Objeto dueño: ("context" | "step" | "project", argumento con su id o alias), o None para
    # un comando global (solo categorías de `admin`). Da el proyecto y, si aplica, la versión.
    owner: Optional[tuple[str, str]]
    receipt: Callable[[dict, Any], dict] = _no_receipt
    domain_tool: Optional[str] = None
    to_domain: Optional[Callable[[dict], dict]] = None
    job: Optional[Callable[["JobContext", dict, Optional[str]], dict]] = None
    resources: Optional[Callable[[dict, Optional[str]], list[str]]] = None
    estimate_usd: Optional[Callable[[dict], float]] = None
    versioned: bool = False
    destructive: bool = False

    @property
    def is_job(self) -> bool:
        return self.job is not None

    @property
    def calls_provider(self) -> bool:
        return self.estimate_usd is not None

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"categoría desconocida: {self.category}")
        if (self.domain_tool is None) == (self.job is None):
            raise ValueError(f"{self.name}: un comando es inmediato (domain_tool) o trabajo (job)")
        if self.domain_tool is not None and self.to_domain is None:
            raise ValueError(f"{self.name}: falta to_domain")
        if self.owner is None:
            if self.category not in ADMIN_ONLY_CATEGORIES:
                raise ValueError(f"{self.name}: un comando global solo puede ser de una categoría de admin")
        elif self.owner[0] not in {"context", "step", "project"}:
            raise ValueError(f"dueño desconocido: {self.owner[0]}")
        if self.versioned and (self.owner is None or self.owner[0] == "project"):
            raise ValueError(f"{self.name}: solo un contexto o un paso tienen versión")
        if self.calls_provider and not self.is_job:
            raise ValueError(f"{self.name}: un comando que llama a un proveedor es un trabajo")


def owner_row(conn, command: Command, args: dict) -> Optional[dict]:
    """Proyecto dueño y versión actual del objeto del comando; `None` si no existe."""
    if command.owner is None:
        return {"project": None, "version": None}
    kind, argument = command.owner
    if kind == "project":
        from orchestrator import index as index_module
        alias = args[argument]
        return {"project": alias, "version": None} if alias in index_module.list_projects() else None
    if kind == "step":
        row = conn.execute(
            "SELECT c.project AS project, s.version AS version FROM steps s "
            "JOIN contexts c ON c.id = s.context_id WHERE s.id = ?",
            (args[argument],),
        ).fetchone()
    else:
        row = conn.execute("SELECT project, version FROM contexts WHERE id = ?", (args[argument],)).fetchone()
    return dict(row) if row is not None else None


def _config() -> dict:
    from orchestrator.config import ConfigError, load_config
    try:
        return load_config()
    except ConfigError:
        return {}


# ── Comandos inmediatos ─────────────────────────────────────────────────────

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


# ── Trabajos ─────────────────────────────────────────────────────────────────

# Fuente de sesiones → (módulo, si su importador recibe la configuración).
SYNC_SOURCES = {
    "claude_code": ("orchestrator.watcher", True),
    "git": ("orchestrator.git_scanner", False),
    "codex": ("orchestrator.codex_watcher", True),
}


def _sync_sessions(job: "JobContext", args: dict, project: Optional[str]) -> dict:
    module_name, uses_config = SYNC_SOURCES[args["source"]]
    job.stage("importing")
    importer = importlib.import_module(module_name).scan_and_import
    imported = importer(_config() if uses_config else {}, quiet=True)
    return {"counts": {"imported": len(imported)}}


def _index_project_docs(job: "JobContext", args: dict, project: Optional[str]) -> dict:
    from pathlib import Path

    from orchestrator import index as index_module
    from orchestrator.rag import index_project_isolated

    job.stage("indexing")
    result = index_project_isolated(project, Path(index_module.list_projects()[project]))
    if result.get("error"):
        raise RuntimeError("index_project_isolated falló")
    return {"counts": {"chunks": int(result.get("chunks", 0))}}


def _run_task(job: "JobContext", args: dict, project: Optional[str]) -> dict:
    from orchestrator import background
    from orchestrator.db import _conn

    run_id, step_id = job.create_run(project, args["task"])
    job.stage("provider", run_id=run_id)
    background._worker(run_id, project, args["task"], _config(), args.get("provider"), None, step_id,
                       still_owned=job.owned)
    row = _conn().execute(
        "SELECT status, cost_usd, router_cost_usd FROM runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row["status"] != "done":
        raise RuntimeError("el run no terminó")
    actual = (row["cost_usd"] or 0.0) + (row["router_cost_usd"] or 0.0)
    return {"affected": {"run_id": run_id}, "actual_usd": actual}


def _estimate_run(args: dict) -> float:
    from orchestrator.commands.budget import estimate_run_usd
    return estimate_run_usd(_config(), args.get("provider"))


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
    Command(
        name="sync_sessions",
        category="maintenance",
        schema={
            "type": "object",
            "required": ["source"],
            "properties": {"source": {"type": "string", "enum": sorted(SYNC_SOURCES)}},
        },
        owner=None,
        job=_sync_sessions,
        resources=lambda args, project: ["imports"],
    ),
    Command(
        name="index_project_docs",
        category="maintenance",
        schema={
            "type": "object",
            "required": ["project"],
            "properties": {"project": {"type": "string", "minLength": 1}},
        },
        owner=("project", "project"),
        job=_index_project_docs,
        resources=lambda args, project: [f"project:{project}:rag"],
    ),
    Command(
        name="run_task",
        category="append",
        schema={
            "type": "object",
            "required": ["project", "task"],
            "properties": {
                "project": {"type": "string", "minLength": 1},
                "task": {"type": "string", "minLength": 1},
                "provider": {"type": "string", "enum": list(PROVIDERS)},
            },
        },
        owner=("project", "project"),
        job=_run_task,
        estimate_usd=_estimate_run,
    ),
)

CATALOG: dict[str, Command] = {command.name: command for command in _COMMANDS}


def domain_handler(command: Command) -> Callable[[dict], Any]:
    from orchestrator import mcp
    return mcp._HANDLERS[command.domain_tool]


def get(name: str) -> Optional[Command]:
    return CATALOG.get(name)
