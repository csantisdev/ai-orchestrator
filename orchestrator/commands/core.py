"""Despacho de comandos de la UI (RFC-010 §3.1-§3.2, I2-I6).

Orden de evaluación de un comando nuevo: `request_id`, comando, sobre del pedido, argumentos,
capacidad del perfil, proyecto dueño, alcance y versión esperada. Todo pedido con un
`request_id` válido deja su registro lógico y su intento, termine como termine; lo que no
termina en `ok` no tiene efectos.

Concurrencia: el reclamo del `request_id`, la comprobación de versión, el efecto y el registro
`ok` van en una sola transacción `BEGIN IMMEDIATE`, que serializa también contra otros procesos
(un servidor MCP, la CLI). Si el comando falla, el registro del fallo se escribe en otra
transacción que vuelve a leer el `request_id` por si otro proceso lo registró mientras tanto.

Privacidad (I3): el registro guarda compromisos de la entrada y del recibo, nunca argumentos,
resultados ni el nombre de un comando desconocido; las respuestas solo llevan códigos, pistas
fijas, IDs, versión y conteos. El detalle de un error queda en el log del servidor.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from orchestrator.commands import budget, catalog, jobs
from orchestrator.commands.policy import ui_identity
from orchestrator.mcp_governance import (
    PROFILE_CAPABILITIES,
    ArgumentValidationError,
    ExecutionIdentity,
    _commitment,
    validate_arguments,
)

_log = logging.getLogger(__name__)

ENVELOPE_SCHEMA = {
    "type": "object",
    "required": ["request_id", "args"],
    "properties": {
        "request_id": {"type": "string"},
        "project": {"type": "string"},
        "expected_version": {"type": "integer", "minimum": 1},
        "confirmation": {"type": "string"},
        "args": {"type": "object", "additionalProperties": True},
    },
}

# Nombre y categoría con que se registra un comando que no está en el catálogo: su nombre real
# viene del cliente y no se guarda en claro (va dentro del compromiso de la entrada).
UNKNOWN_COMMAND = "_unknown"

_HINTS = {
    "capability_denied": (
        "El perfil de la UI no concede la categoría de este comando. Ejecutá "
        "'ai-orchestrator fix --ui-profile <perfil> --ui-projects <alias,...>' con un perfil que la "
        "conceda; project_admin y maintenance solo los concede admin."
    ),
    "project_out_of_scope": (
        "El proyecto no está en el alcance de la UI. Agregalo con "
        "'ai-orchestrator fix --ui-profile <perfil> --ui-projects <alias,...>'."
    ),
    "version_conflict": (
        "El objeto cambió desde que se leyó. Volvé a leerlo y reenviá el comando con un "
        "request_id nuevo y la versión actual."
    ),
    "request_id_reused": (
        "Ese request_id ya se usó con otro comando o con otros argumentos. Generá uno nuevo."
    ),
    "invalid_arguments": (
        "El pedido no cumple el esquema del comando (GET /api/v1/commands lo publica). "
        "Los comandos versionados exigen expected_version."
    ),
    "unknown_command": "El comando no existe en el catálogo (GET /api/v1/commands).",
    "not_found": "El objeto indicado no existe. Volvé a leer la vista.",
    "project_mismatch": "El proyecto declarado no es el dueño del objeto indicado.",
    "execution_error": "La operación rechazó el pedido; el detalle quedó en el log del servidor.",
    "internal_error": "Error interno; el detalle quedó en el log del servidor.",
    "resource_busy": (
        "Otro trabajo tiene el recurso (job_id). Reenviá el mismo pedido, con el mismo request_id, "
        "cuando termine."
    ),
    "budget_exceeded": (
        "La reserva de costo de este comando excede el presupuesto diario del proyecto. Subí "
        "daily_budget_usd en el context.yaml o budgets.default_daily_budget_usd en config.yaml."
    ),
    "scope_changed": "El perfil, el alcance o el objeto cambiaron entre encolar y ejecutar.",
    "server_restart": (
        "El servidor se reinició con el trabajo en curso. Revisá el estado antes de reintentar "
        "con un request_id nuevo; un run interrumpido no se reintenta solo."
    ),
}


class _Outcome(Exception):
    """Fin anticipado de un comando sin efectos (denegado, conflicto o error)."""

    def __init__(self, status: str, reason_code: str, project: Optional[str] = None,
                 job_id: Optional[str] = None):
        super().__init__(reason_code)
        self.status = status
        self.reason_code = reason_code
        self.project = project
        self.job_id = job_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _http_status(status: str, reason_code: Optional[str]) -> int:
    if status in {"ok", "interrupted"}:
        return 200
    if status == "accepted":
        return 202
    if status == "denied":
        return 403
    if status in {"conflict", "busy"}:
        return 409
    if reason_code in {"not_found", "unknown_command"}:
        return 404
    if reason_code == "internal_error":
        return 500
    return 400


def _response(status: str, reason_code: Optional[str] = None, *, receipt: Optional[dict] = None,
              version: Optional[int] = None, job_id: Optional[str] = None) -> tuple[int, dict]:
    return _http_status(status, reason_code), {
        "status": status,
        "reason_code": reason_code,
        "hint": _HINTS.get(reason_code or ""),
        "receipt": receipt,
        "job_id": job_id,
        "version": version,
    }


def _request_id(body: Any) -> Optional[str]:
    raw = body.get("request_id") if isinstance(body, dict) else None
    if not isinstance(raw, str):
        return None
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return None


def input_commitment(name: str, body: dict) -> str:
    """Compromiso de todo lo que define el pedido: comando, sobre y argumentos."""
    return _commitment(_canonical({
        "command": name,
        "project": body.get("project"),
        "expected_version": body.get("expected_version"),
        "confirmation": body.get("confirmation"),
        "args": body.get("args"),
    }))


def _attempt(conn, request_id: str, status: str, reason_code: Optional[str]) -> None:
    conn.execute(
        "INSERT INTO ui_command_attempts (request_id, ts, status, reason_code) VALUES (?, ?, ?, ?)",
        (request_id, _now(), status, reason_code),
    )


def make_receipt(request_id: str, command: str, status: str, reason_code: Optional[str],
             version: Optional[int], extra: Optional[dict] = None) -> dict:
    receipt = {
        "request_id": request_id,
        "command": command,
        "status": status,
        "reason_code": reason_code,
        "version": version,
        **(extra or {}),
    }
    receipt["receipt_hash"] = _commitment(_canonical(receipt))
    return receipt


def _write_record(conn, *, exists: bool, request_id: str, name: str, category: str,
                  identity: ExecutionIdentity, project: Optional[str], input_hash: str,
                  status: str, reason_code: Optional[str], receipt_hash: Optional[str],
                  version: Optional[int]) -> None:
    now = _now()
    if exists:
        conn.execute(
            "UPDATE ui_commands SET status=?, reason_code=?, receipt_hash=?, result_version=?, "
            "project=?, capability_profile=?, updated_at=? WHERE request_id=?",
            (status, reason_code, receipt_hash, version, project, identity.capability_profile,
             now, request_id),
        )
        return
    conn.execute(
        "INSERT INTO ui_commands (request_id, command, category, project, capability_profile, "
        "input_hash, status, reason_code, receipt_hash, result_version, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (request_id, name, category, project, identity.capability_profile,
         input_hash, status, reason_code, receipt_hash, version, now, now),
    )


def _existing(conn, request_id: str, name: str, input_hash: str):
    """Respuesta para un `request_id` ya registrado, o `None` si se puede (re)evaluar.

    Corre dentro de la transacción del llamador: así el reclamo es atómico entre procesos.
    """
    row = conn.execute(
        "SELECT command, input_hash, status, reason_code, receipt_hash, result_version "
        "FROM ui_commands WHERE request_id = ?",
        (request_id,),
    ).fetchone()
    if row is None:
        return None, False
    if row["command"] != name or row["input_hash"] != input_hash:
        _attempt(conn, request_id, "conflict", "request_id_reused")
        return _response("conflict", "request_id_reused"), True
    status, reason_code = row["status"], row["reason_code"]
    if status == "not_admitted":
        return None, True
    if status in {"queued", "running"}:
        job = conn.execute("SELECT id FROM jobs WHERE request_id = ?", (request_id,)).fetchone()
        _attempt(conn, request_id, "accepted", None)
        return _response("accepted", job_id=job["id"] if job else None), True
    _attempt(conn, request_id, status, reason_code)
    receipt = {
        "request_id": request_id,
        "command": row["command"],
        "status": status,
        "reason_code": reason_code,
        "version": row["result_version"],
        "receipt_hash": row["receipt_hash"],
        "replayed": True,
    }
    return _response(status, reason_code, receipt=receipt, version=row["result_version"]), True


def execute(name: str, body: Any, identity: Optional[ExecutionIdentity] = None) -> tuple[int, dict]:
    """Ejecuta un comando de la UI y devuelve `(status HTTP, respuesta)` (RFC-010 §3.1)."""
    from orchestrator.db import _conn, _write_lock, atomic_mutation

    request_id = _request_id(body)
    if request_id is None:
        # Sin un request_id válido no hay registro al que asociar el intento (I3).
        return _response("error", "invalid_arguments")

    command = catalog.get(name)
    record_name = command.name if command else UNKNOWN_COMMAND
    category = command.category if command else "none"
    identity = identity or ui_identity()
    input_hash = input_commitment(name, body)
    project = None
    holder = None

    with _write_lock:
        conn = _conn()
        exists = False
        try:
            with atomic_mutation():
                answer, exists = _existing(conn, request_id, record_name, input_hash)
                if answer is not None:
                    return answer
                if command is None:
                    raise _Outcome("error", "unknown_command")
                args = _validated(command, body)
                project = _admit(conn, command, identity, args, body)
                if command.versioned and catalog.owner_row(conn, command, args)["version"] != body["expected_version"]:
                    raise _Outcome("conflict", "version_conflict", project)
                record = dict(conn=conn, exists=exists, request_id=request_id, name=record_name,
                              category=category, identity=identity, project=project, input_hash=input_hash)
                if command.is_job:
                    job_id = _enqueue(command, args, record)
                else:
                    job_id = None
                    result = catalog.domain_handler(command)(command.to_domain(args))
                    row = catalog.owner_row(conn, command, args)
                    version = row["version"] if row is not None else None
                    receipt = make_receipt(request_id, name, "ok", None, version, command.receipt(args, result))
                    _write_record(**record, status="ok", reason_code=None,
                                  receipt_hash=receipt["receipt_hash"], version=version)
                    _attempt(conn, request_id, "ok", None)
            if job_id is not None:
                jobs.start(job_id, command, args, body)
                return _response("accepted", job_id=job_id)
            return _response("ok", receipt=receipt, version=version)
        except _Outcome as outcome:
            status, reason_code = outcome.status, outcome.reason_code
            project = outcome.project or project
            holder = outcome.job_id
        except ValueError as exc:
            _log.info("commands: %s rechazado por la operación: %s", record_name, exc)
            status, reason_code = "error", getattr(exc, "reason_code", "execution_error")
        except Exception:
            _log.exception("commands: error en %s", record_name)
            status, reason_code = "error", "internal_error"

        # `busy` no es terminal: el registro queda `not_admitted` y el mismo request_id se
        # vuelve a evaluar al reenviarlo (§3.2, I14).
        record_status = "not_admitted" if status == "busy" else status
        with atomic_mutation():
            # Otro proceso pudo registrar el mismo request_id mientras este fallaba.
            answer, exists = _existing(conn, request_id, record_name, input_hash)
            if answer is not None:
                return answer
            receipt = make_receipt(request_id, record_name, status, reason_code, None)
            _write_record(conn, exists=exists, request_id=request_id, name=record_name,
                          category=category, identity=identity, project=project,
                          input_hash=input_hash, status=record_status, reason_code=reason_code,
                          receipt_hash=receipt["receipt_hash"], version=None)
            _attempt(conn, request_id, status, reason_code)
        return _response(status, reason_code, receipt=receipt, job_id=holder)


def _enqueue(command: catalog.Command, args: dict, record: dict) -> str:
    """Admite y encola un trabajo dentro de la transacción del comando (§3.3, §3.5)."""
    conn, project, request_id = record["conn"], record["project"], record["request_id"]
    resources = command.resources(args, project) if command.resources else []
    holder = jobs.busy_holder(conn, resources)
    if holder is not None:
        raise _Outcome("busy", "resource_busy", project, job_id=holder)
    estimate = None
    if command.calls_provider:
        estimate = command.estimate_usd(args)
        limit = budget.daily_limit(project, catalog._config())
        if budget.committed_usd(conn, project) + estimate > limit:
            raise _Outcome("denied", "budget_exceeded", project)
    _write_record(**record, status="queued", reason_code=None, receipt_hash=None, version=None)
    if estimate is not None:
        budget.reserve(conn, request_id, project, estimate)
    job_id = jobs.enqueue(conn, request_id, command.name, resources)
    _attempt(conn, request_id, "accepted", None)
    return job_id


def _validated(command: catalog.Command, body: dict) -> dict:
    try:
        validate_arguments(ENVELOPE_SCHEMA, body)
        validate_arguments(command.schema, body["args"])
    except ArgumentValidationError as exc:
        _log.info("commands: argumentos inválidos para %s: %s", command.name, exc)
        raise _Outcome("error", "invalid_arguments") from None
    return body["args"]


def _admit(conn, command: catalog.Command, identity: ExecutionIdentity, args: dict, body: dict) -> Optional[str]:
    """Autoriza sin efectos; devuelve el proyecto dueño o lanza `_Outcome`."""
    if command.category not in PROFILE_CAPABILITIES[identity.capability_profile]:
        raise _Outcome("denied", "capability_denied")
    row = catalog.owner_row(conn, command, args)
    if row is None:
        raise _Outcome("error", "not_found")
    project = row["project"]
    declared = body.get("project")
    if declared is not None and declared != project:
        raise _Outcome("error", "project_mismatch", project)
    if project is not None and project not in identity.project_scope:
        raise _Outcome("denied", "project_out_of_scope", project)
    if command.versioned and "expected_version" not in body:
        raise _Outcome("error", "invalid_arguments", project)
    return project


def catalog_view(identity: Optional[ExecutionIdentity] = None) -> dict:
    """Catálogo con el estado de cada comando para el perfil actual de la UI (§3.1)."""
    identity = identity or ui_identity()
    granted = PROFILE_CAPABILITIES[identity.capability_profile]
    commands = []
    for command in catalog.CATALOG.values():
        reason = None
        if command.category not in granted:
            reason = "capability_denied"
        elif command.owner is not None and not identity.project_scope:
            reason = "project_out_of_scope"
        commands.append({
            "name": command.name,
            "category": command.category,
            "enabled": reason is None,
            "reason_code": reason,
            "versioned": command.versioned,
            "destructive": command.destructive,
            "is_job": command.is_job,
            "calls_provider": command.calls_provider,
            "args_schema": command.schema,
        })
    return {
        "profile": identity.capability_profile,
        "projects": sorted(identity.project_scope),
        "commands": commands,
    }
