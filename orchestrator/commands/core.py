"""Despacho de comandos de la UI (RFC-010 §3.1-§3.2, I2-I6).

Orden de evaluación de un comando nuevo: sobre del pedido, argumentos, capacidad del perfil,
proyecto dueño, alcance y versión esperada. Todo lo que no termina en `ok` se registra igual
(registro lógico + intento) y no tiene efectos. El efecto, la comprobación de versión y el
registro `ok` van en una sola transacción SQLite.

Privacidad (I3): el registro guarda el compromiso de la entrada y del recibo, nunca los
argumentos ni el resultado; el recibo solo lleva IDs, versión, conteos y códigos.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from orchestrator.commands import catalog
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

_TERMINAL = {"ok", "denied", "conflict", "error", "interrupted"}

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
}


class _Outcome(Exception):
    """Fin anticipado de un comando sin efectos (denegado, conflicto o error de entrada)."""

    def __init__(self, status: str, reason_code: str, error: Optional[str] = None,
                 project: Optional[str] = None):
        super().__init__(reason_code)
        self.status = status
        self.reason_code = reason_code
        self.error = error
        self.project = project


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _http_status(status: str, reason_code: Optional[str]) -> int:
    if status == "ok":
        return 200
    if status == "accepted":
        return 202
    if status == "denied":
        return 403
    if status in {"conflict", "busy"}:
        return 409
    if status == "interrupted":
        return 200
    if reason_code in {"not_found", "unknown_command"}:
        return 404
    if reason_code == "internal_error":
        return 500
    return 400


def _response(status: str, reason_code: Optional[str] = None, *, receipt: Optional[dict] = None,
              version: Optional[int] = None, job_id: Optional[str] = None,
              error: Optional[str] = None) -> tuple[int, dict]:
    payload: dict[str, Any] = {
        "status": status,
        "reason_code": reason_code,
        "hint": _HINTS.get(reason_code or ""),
        "receipt": receipt,
        "job_id": job_id,
        "version": version,
    }
    if error:
        payload["error"] = error
    return _http_status(status, reason_code), payload


def _request_id(raw: str) -> str:
    try:
        return str(uuid.UUID(raw))
    except (ValueError, AttributeError, TypeError):
        raise ArgumentValidationError("request_id must be a UUID") from None


def _owner_row(conn, command: catalog.Command, args: dict):
    kind, argument = command.owner
    if kind == "step":
        return conn.execute(
            "SELECT c.project AS project, s.version AS version FROM steps s "
            "JOIN contexts c ON c.id = s.context_id WHERE s.id = ?",
            (args[argument],),
        ).fetchone()
    return conn.execute(
        "SELECT project, version FROM contexts WHERE id = ?", (args[argument],)
    ).fetchone()


def _attempt(conn, request_id: str, status: str, reason_code: Optional[str]) -> None:
    conn.execute(
        "INSERT INTO ui_command_attempts (request_id, ts, status, reason_code) VALUES (?, ?, ?, ?)",
        (request_id, _now(), status, reason_code),
    )


def _receipt(request_id: str, command: str, status: str, reason_code: Optional[str],
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


def _write_record(conn, *, exists: bool, request_id: str, command: catalog.Command,
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
        (request_id, command.name, command.category, project, identity.capability_profile,
         input_hash, status, reason_code, receipt_hash, version, now, now),
    )


def _replay(conn, row, request_id: str) -> tuple[int, dict]:
    status, reason_code = row["status"], row["reason_code"]
    if status in {"queued", "running"}:
        job = conn.execute("SELECT id FROM jobs WHERE request_id = ?", (request_id,)).fetchone()
        _attempt(conn, request_id, "accepted", None)
        return _response("accepted", job_id=job["id"] if job else None)
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
    return _response(status, reason_code, receipt=receipt, version=row["result_version"])


def execute(name: str, body: Any, identity: Optional[ExecutionIdentity] = None) -> tuple[int, dict]:
    """Ejecuta un comando de la UI y devuelve `(status HTTP, respuesta)` (RFC-010 §3.1)."""
    from orchestrator.db import _conn, _write_lock, atomic_mutation

    command = catalog.get(name)
    if command is None:
        return _response("error", "unknown_command", error=f"unknown command: {name}")
    try:
        validate_arguments(ENVELOPE_SCHEMA, body)
        request_id = _request_id(body["request_id"])
    except ArgumentValidationError as exc:
        return _response("error", "invalid_arguments", error=str(exc))

    identity = identity or ui_identity()
    args = body["args"]
    input_hash = _commitment(_canonical({
        "command": name,
        "project": body.get("project"),
        "expected_version": body.get("expected_version"),
        "confirmation": body.get("confirmation"),
        "args": args,
    }))

    with _write_lock:
        conn = _conn()
        existing = conn.execute(
            "SELECT command, input_hash, status, reason_code, receipt_hash, result_version "
            "FROM ui_commands WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if existing is not None:
            if existing["command"] != name or existing["input_hash"] != input_hash:
                with atomic_mutation():
                    _attempt(conn, request_id, "conflict", "request_id_reused")
                return _response("conflict", "request_id_reused")
            if existing["status"] != "not_admitted":
                with atomic_mutation():
                    return _replay(conn, existing, request_id)

        project = body.get("project")
        try:
            with atomic_mutation():
                project = _admit(conn, command, identity, args, body)
                if command.versioned:
                    current = _owner_row(conn, command, args)["version"]
                    if current != body["expected_version"]:
                        raise _Outcome("conflict", "version_conflict")
                result = catalog.domain_handler(command)(command.to_domain(args))
                row = _owner_row(conn, command, args)
                version = row["version"] if row is not None else None
                receipt = _receipt(request_id, name, "ok", None, version, command.receipt(args, result))
                _write_record(conn, exists=existing is not None, request_id=request_id,
                              command=command, identity=identity, project=project,
                              input_hash=input_hash, status="ok", reason_code=None,
                              receipt_hash=receipt["receipt_hash"], version=version)
                _attempt(conn, request_id, "ok", None)
            return _response("ok", receipt=receipt, version=version)
        except _Outcome as outcome:
            status, reason_code, error = outcome.status, outcome.reason_code, outcome.error
            project = outcome.project or project
        except ValueError as exc:
            reason_code = getattr(exc, "reason_code", "execution_error")
            status, error = "error", str(exc)
        except Exception:
            _log.exception("commands: error en %s", name)
            status, reason_code, error = "error", "internal_error", None

        receipt = _receipt(request_id, name, status, reason_code, None)
        with atomic_mutation():
            _write_record(conn, exists=existing is not None, request_id=request_id,
                          command=command, identity=identity, project=project,
                          input_hash=input_hash, status=status, reason_code=reason_code,
                          receipt_hash=receipt["receipt_hash"], version=None)
            _attempt(conn, request_id, status, reason_code)
        return _response(status, reason_code, receipt=receipt, error=error)


def _admit(conn, command: catalog.Command, identity: ExecutionIdentity, args: dict, body: dict) -> str:
    """Valida y autoriza sin efectos; devuelve el proyecto dueño o lanza `_Outcome`."""
    try:
        validate_arguments(command.schema, args)
    except ArgumentValidationError as exc:
        raise _Outcome("error", "invalid_arguments", str(exc)) from None
    if command.category not in PROFILE_CAPABILITIES[identity.capability_profile]:
        raise _Outcome("denied", "capability_denied")
    row = _owner_row(conn, command, args)
    if row is None:
        raise _Outcome("error", "not_found", f"{command.owner[0]} {args[command.owner[1]]} not found")
    project = row["project"]
    declared = body.get("project")
    if declared is not None and declared != project:
        raise _Outcome("error", "project_mismatch", "project does not own the target object", project)
    if project not in identity.project_scope:
        raise _Outcome("denied", "project_out_of_scope", project=project)
    if command.versioned and "expected_version" not in body:
        raise _Outcome("error", "invalid_arguments", "expected_version is required for this command", project)
    return project


def catalog_view(identity: Optional[ExecutionIdentity] = None) -> dict:
    """Catálogo con el estado de cada comando para el perfil actual de la UI (§3.1)."""
    identity = identity or ui_identity()
    granted = PROFILE_CAPABILITIES[identity.capability_profile]
    commands = []
    for command in catalog.CATALOG.values():
        enabled = command.category in granted and bool(identity.project_scope)
        reason = None
        if command.category not in granted:
            reason = "capability_denied"
        elif not identity.project_scope:
            reason = "project_out_of_scope"
        commands.append({
            "name": command.name,
            "category": command.category,
            "enabled": enabled,
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
