"""Trabajos de los comandos largos (RFC-010 §3.3, I7, I13, I14).

- **Encolar** (dentro de la transacción del comando): el trabajo queda `queued` con sus
  recursos. Un recurso que tiene otro trabajo `queued` o `running` deja el comando `busy`
  (`not_admitted`), sin consumir el `request_id`.
- **Empezar:** en una transacción nueva se vuelven a comprobar perfil, alcance, dueño y versión
  (TOCTOU); si cambiaron, el trabajo termina en `conflict` sin efectos.
- **Etapas:** cada cambio se guarda en `jobs.stage` y se publica por SSE (`job_stage`).
- **Lease:** cada trabajo guarda el proceso que lo ejecuta (`executor`) y un latido
  (`heartbeat_at`) que ese proceso renueva mientras vive. Un trabajo solo se cierra si sigue
  `queued`/`running` y con el mismo `executor`: lo que otro proceso ya reconcilió no se
  sobrescribe.
- **Reinicio:** `reconcile()` corre al arrancar el servidor y después con cada latido, y deja
  `interrupted` todo trabajo `queued` o `running` cuyo ejecutor dejó de latir (un servidor
  muerto); los de un servidor vivo no se tocan. Un `run_task` interrumpido marca su run como
  fallido y no se reintenta.

Los argumentos del comando viven solo en memoria del hilo del trabajo (I3): tras un reinicio no
hay con qué reanudarlo, y por eso queda `interrupted`.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from orchestrator.commands import budget, catalog

_log = logging.getLogger(__name__)

ACTIVE = ("queued", "running")
EXECUTOR_ID = str(uuid.uuid4())
LEASE_SECONDS = 60
HEARTBEAT_SECONDS = 15
_heartbeat_lock = threading.Lock()
_heartbeat_started = False
# Estado del trabajo → estado del registro del comando.
_COMMAND_STATUS = {"done": "ok", "failed": "error", "conflict": "conflict", "interrupted": "interrupted"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _spawn(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True).start()


def _publish(job_id: str, status: str, stage: Optional[str], **extra: Any) -> None:
    from orchestrator.sse import BUS
    BUS.publish("job_stage", json.dumps({"job_id": job_id, "status": status, "stage": stage, **extra}))


@dataclass
class JobContext:
    job_id: str

    def stage(self, name: str, **extra: int) -> None:
        from orchestrator.db import _conn, _write_lock
        with _write_lock:
            conn = _conn()
            conn.execute("UPDATE jobs SET stage = ? WHERE id = ?", (name, self.job_id))
            conn.commit()
        _publish(self.job_id, "running", name, **extra)

    def owned(self) -> bool:
        """El trabajo sigue `running` en manos de este proceso (no lo reconcilió otro)."""
        from orchestrator.db import _conn
        row = _conn().execute("SELECT status, executor FROM jobs WHERE id = ?", (self.job_id,)).fetchone()
        return row is not None and row["status"] == "running" and row["executor"] == EXECUTOR_ID

    def create_run(self, project: str, task: str) -> tuple[int, Optional[int]]:
        """Crea el run pendiente y lo vincula al trabajo en una sola transacción."""
        from orchestrator import background
        from orchestrator.db import _conn, atomic_mutation
        with atomic_mutation():
            run_id, step_id = background.create_pending_run(project, task, announce=False)
            _conn().execute("UPDATE jobs SET run_id = ? WHERE id = ?", (run_id, self.job_id))
        background.announce_run(run_id, project)
        return run_id, step_id


def busy_holder(conn, resources: list[str]) -> Optional[str]:
    """Trabajo activo que ya tiene alguno de los recursos pedidos (I14)."""
    if not resources:
        return None
    wanted = set(resources)
    for row in conn.execute(
        "SELECT id, resources FROM jobs WHERE status IN ('queued', 'running') ORDER BY created_at"
    ).fetchall():
        if wanted & set(json.loads(row["resources"])):
            return row["id"]
    return None


def enqueue(conn, request_id: str, kind: str, resources: list[str]) -> str:
    job_id = str(uuid.uuid4())
    now = _now()
    conn.execute(
        "INSERT INTO jobs (id, request_id, kind, resources, status, created_at, executor, heartbeat_at) "
        "VALUES (?, ?, ?, ?, 'queued', ?, ?, ?)",
        (job_id, request_id, kind, json.dumps(sorted(set(resources))), now, EXECUTOR_ID, now),
    )
    return job_id


def start(job_id: str, command: catalog.Command, args: dict, body: dict) -> None:
    start_heartbeat()
    _publish(job_id, "queued", None)
    _spawn(lambda: run(job_id, command, args, body))


def _recheck(conn, command: catalog.Command, args: dict, body: dict, project: Optional[str]) -> Optional[str]:
    """Motivo por el que ya no se puede ejecutar lo que se encoló, o `None` (I13)."""
    from orchestrator.commands.policy import ui_identity
    from orchestrator.mcp_governance import PROFILE_CAPABILITIES

    identity = ui_identity()
    if command.category not in PROFILE_CAPABILITIES[identity.capability_profile]:
        return "scope_changed"
    row = catalog.owner_row(conn, command, args)
    if row is None or row["project"] != project:
        return "scope_changed"
    if project is not None and project not in identity.project_scope:
        return "scope_changed"
    if command.versioned and row["version"] != body.get("expected_version"):
        return "version_conflict"
    return None


def _finish(conn, job_id: str, executor: Optional[str], request_id: str, name: str, status: str,
            reason_code: Optional[str], extra: Optional[dict]) -> bool:
    """Cierra el trabajo si sigue activo y en manos de `executor`; si no, no toca nada."""
    from orchestrator.commands.core import make_receipt

    extra = dict(extra or {})
    actual = extra.pop("actual_usd", None)
    command_status = _COMMAND_STATUS[status]
    receipt = make_receipt(request_id, name, command_status, reason_code, None, extra)
    now = _now()
    closed = conn.execute(
        "UPDATE jobs SET status = ?, receipt_hash = ?, finished_at = ? "
        "WHERE id = ? AND executor IS ? AND status IN ('queued', 'running')",
        (status, receipt["receipt_hash"], now, job_id, executor),
    ).rowcount
    if not closed:
        return False
    conn.execute(
        "UPDATE ui_commands SET status = ?, reason_code = ?, receipt_hash = ?, updated_at = ? WHERE request_id = ?",
        (command_status, reason_code, receipt["receipt_hash"], now, request_id),
    )
    budget.close(conn, request_id, float(actual) if status == "done" and actual is not None else None)
    return True


def run(job_id: str, command: catalog.Command, args: dict, body: dict) -> None:
    from orchestrator.db import _conn, _write_lock, atomic_mutation

    with _write_lock:
        conn = _conn()
        with atomic_mutation():
            row = conn.execute(
                "SELECT j.status, j.executor, j.request_id, c.project FROM jobs j "
                "JOIN ui_commands c ON c.request_id = j.request_id WHERE j.id = ?",
                (job_id,),
            ).fetchone()
            if row is None or row["status"] != "queued" or row["executor"] != EXECUTOR_ID:
                return
            request_id, project = row["request_id"], row["project"]
            reason = _recheck(conn, command, args, body, project)
            if reason is not None:
                _finish(conn, job_id, EXECUTOR_ID, request_id, command.name, "conflict", reason, None)
            else:
                now = _now()
                conn.execute(
                    "UPDATE jobs SET status = 'running', started_at = ?, heartbeat_at = ? WHERE id = ?",
                    (now, now, job_id),
                )
                conn.execute(
                    "UPDATE ui_commands SET status = 'running', updated_at = ? WHERE request_id = ?",
                    (now, request_id),
                )
    if reason is not None:
        _publish(job_id, "conflict", None, reason_code=reason)
        return

    _publish(job_id, "running", None)
    try:
        extra = command.job(JobContext(job_id), args, project)
        status, reason = "done", None
    except Exception:
        _log.exception("jobs: falló el trabajo %s (%s)", job_id, command.name)
        extra, status, reason = None, "failed", "execution_error"

    with _write_lock:
        with atomic_mutation():
            closed = _finish(_conn(), job_id, EXECUTOR_ID, request_id, command.name, status, reason, extra)
    if not closed:
        _log.warning("jobs: %s ya fue reconciliado por otro proceso; no se sobrescribe", job_id)
        return
    _publish(job_id, status, None)


def reconcile() -> int:
    """Ningún trabajo de un ejecutor muerto queda `queued` ni `running` (I7). Un ejecutor está
    muerto si no es este proceso y su latido tiene más de `LEASE_SECONDS`. Devuelve cuántos cerró."""
    from orchestrator.db import _conn, _write_lock, atomic_mutation

    with _write_lock:
        conn = _conn()
        with atomic_mutation():
            rows = conn.execute(
                "SELECT j.id, j.executor, j.request_id, j.run_id, c.command FROM jobs j "
                "JOIN ui_commands c ON c.request_id = j.request_id "
                "WHERE j.status IN ('queued', 'running') AND (j.executor IS NULL OR (j.executor <> ? "
                "AND (j.heartbeat_at IS NULL OR julianday(j.heartbeat_at) < julianday(?) - ? / 86400.0)))",
                (EXECUTOR_ID, _now(), LEASE_SECONDS),
            ).fetchall()
            closed = 0
            for row in rows:
                if not _finish(conn, row["id"], row["executor"], row["request_id"], row["command"],
                               "interrupted", "server_restart", None):
                    continue
                closed += 1
                if row["run_id"] is not None:
                    conn.execute(
                        "UPDATE runs SET status = 'failed', response = ? WHERE id = ? AND status = 'pending'",
                        ("interrupted: el servidor se reinició durante el run", row["run_id"]),
                    )
    return closed


def heartbeat() -> None:
    """Renueva el lease de los trabajos activos de este proceso."""
    from orchestrator.db import _conn, _write_lock

    with _write_lock:
        conn = _conn()
        conn.execute(
            "UPDATE jobs SET heartbeat_at = ? WHERE executor = ? AND status IN ('queued', 'running')",
            (_now(), EXECUTOR_ID),
        )
        conn.commit()


def start_heartbeat() -> None:
    """Hilo del proceso que late y reconcilia los trabajos de ejecutores muertos (una vez)."""
    global _heartbeat_started
    with _heartbeat_lock:
        if _heartbeat_started:
            return
        _heartbeat_started = True

    def loop() -> None:
        import time
        while True:
            time.sleep(HEARTBEAT_SECONDS)
            try:
                heartbeat()
                reconcile()
            except Exception:
                _log.exception("jobs: falló el latido")

    threading.Thread(target=loop, daemon=True).start()
