"""Policy, validation, and observed audit records for the local MCP boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any

TOOL_CATEGORIES = {
    "get_context": "read",
    "list_steps": "read",
    "list_agents": "read",
    "confirm_alignment": "append",
    "record_tool_call": "append",
    "create_context": "workflow_mutation",
    "add_step": "workflow_mutation",
    "update_context": "workflow_mutation",
    "update_step": "workflow_mutation",
    "advance_step": "workflow_transition",
    "skip_step": "workflow_transition",
    "import_agent_context": "memory_ingest",
}

PROFILE_CAPABILITIES = {
    "readonly": frozenset({"read"}),
    "observability": frozenset({"read", "append"}),
    "workflow_operator": frozenset({"read", "append", "workflow_mutation", "workflow_transition"}),
    "memory_curator": frozenset({"read", "memory_ingest"}),
    "admin": frozenset(TOOL_CATEGORIES.values()),
}
_SURFACES = frozenset({"chatgpt_desktop", "codex_cli", "codex_ide", "claude_code", "ssh_client", "other"})
_TRANSPORTS = frozenset({"stdio", "ssh_stdio"})
SERVER_INSTANCE_ID = str(uuid.uuid4())
_commitment_key: bytes | None = None
_commitment_key_path = None


@dataclass(frozen=True)
class ExecutionIdentity:
    client_surface: str
    transport: str
    actor_id: str | None
    capability_profile: str
    project_scope: frozenset[str]


class PolicyDenied(ValueError):
    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


class ArgumentValidationError(ValueError):
    """A client input failure, distinct from a handler's domain error."""


def execution_identity() -> ExecutionIdentity:
    """Resolve trusted local-launch configuration; tool arguments never set identity."""
    profile = os.environ.get("ORCHESTRATOR_MCP_PROFILE", "readonly").strip()
    if profile not in PROFILE_CAPABILITIES:
        profile = "readonly"
    surface = os.environ.get("ORCHESTRATOR_MCP_CLIENT_SURFACE", "other").strip()
    transport = os.environ.get("ORCHESTRATOR_MCP_TRANSPORT", "stdio").strip()
    return ExecutionIdentity(
        client_surface=surface if surface in _SURFACES else "other",
        transport=transport if transport in _TRANSPORTS else "stdio",
        actor_id=os.environ.get("ORCHESTRATOR_MCP_ACTOR_ID", "").strip() or None,
        capability_profile=profile,
        project_scope=frozenset(
            project.strip()
            for project in os.environ.get("ORCHESTRATOR_MCP_PROJECTS", "").split(",")
            if project.strip()
        ),
    )


def annotate_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return MCP discovery metadata without making annotations a security control."""
    annotated = []
    for tool in tools:
        category = TOOL_CATEGORIES[tool["name"]]
        copy = dict(tool)
        copy.setdefault("title", tool["name"].replace("_", " ").title())
        copy["annotations"] = {
            "readOnlyHint": category == "read",
            "destructiveHint": category in {"workflow_mutation", "workflow_transition", "memory_ingest"},
            "idempotentHint": category == "read",
            "openWorldHint": False,
        }
        annotated.append(copy)
    return annotated


def visible_tools(tools: list[dict[str, Any]], identity: ExecutionIdentity) -> list[dict[str, Any]]:
    return [
        tool for tool in annotate_tools(tools)
        if TOOL_CATEGORIES[tool["name"]] in PROFILE_CAPABILITIES[identity.capability_profile]
    ]


def validate_arguments(schema: dict[str, Any], args: Any) -> None:
    """Small dependency-free JSON-schema subset used by the MCP tool contracts."""
    try:
        if not isinstance(args, dict):
            raise ValueError("arguments must be an object")
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in args:
                raise ValueError(f"missing required argument: {required}")
        unknown = set(args) - set(properties)
        if unknown:
            raise ValueError(f"unexpected argument: {sorted(unknown)[0]}")
        for name, value in args.items():
            _validate_value(properties[name], value, name)
    except ValueError as exc:
        raise ArgumentValidationError(str(exc)) from exc


def _validate_value(schema: dict[str, Any], value: Any, path: str) -> None:
    expected = schema.get("type")
    checks = {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
    }
    if expected and not checks[expected](value):
        raise ValueError(f"{path} must be a {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} must be one of {schema['enum']}")
    if expected == "array":
        for index, item in enumerate(value):
            _validate_value(schema.get("items", {}), item, f"{path}[{index}]")
    elif expected == "object":
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                raise ValueError(f"missing required argument: {path}.{required}")
        unknown = set(value) - set(properties)
        if unknown:
            raise ValueError(f"unexpected argument: {path}.{sorted(unknown)[0]}")
        for name, item in value.items():
            _validate_value(properties[name], item, f"{path}.{name}")


def resolve_project(tool_name: str, args: dict[str, Any]) -> str | None:
    """Resolve resource ownership before a handler executes."""
    if tool_name in {"create_context", "import_agent_context"}:
        return str(args.get("project", "")).strip() or None
    if tool_name == "get_context" and args.get("project"):
        return str(args["project"]).strip()
    resource_id = args.get("context_id")
    if tool_name in {"advance_step", "skip_step", "update_step"}:
        resource_id = args.get("step_id")
        query = """SELECT c.project FROM steps s JOIN contexts c ON c.id=s.context_id WHERE s.id=?"""
    elif resource_id:
        query = "SELECT project FROM contexts WHERE id=?"
    else:
        return None
    if not resource_id:
        return None
    from orchestrator.db import _conn
    row = _conn().execute(query, (resource_id,)).fetchone()
    return row["project"] if row else None


def authorize(identity: ExecutionIdentity, tool_name: str, project: str | None) -> None:
    category = TOOL_CATEGORIES.get(tool_name)
    if category is None:
        raise PolicyDenied("unknown_tool")
    if category not in PROFILE_CAPABILITIES[identity.capability_profile]:
        raise PolicyDenied("capability_denied")
    if tool_name == "list_agents":
        return
    if project is None:
        raise PolicyDenied("project_scope_required")
    if project not in identity.project_scope:
        raise PolicyDenied("project_out_of_scope")


def audit_invocation(
    *,
    request_id: str,
    correlation_id: str | None,
    identity: ExecutionIdentity,
    tool_name: str,
    project: str | None,
    args: dict[str, Any],
    status: str,
    started_at: float,
    reason_code: str | None = None,
    output: Any = None,
    error_code: str | None = None,
    request_source: str = "generated",
    replay_safe: bool = False,
    is_error: bool = False,
) -> None:
    """Write observed MCP evidence; deliberately never persists tool payloads."""
    from datetime import datetime, timezone
    from orchestrator.db import _conn, _write_lock

    canonical_input = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    canonical_output = json.dumps(output, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    now = datetime.now(timezone.utc).isoformat()
    with _write_lock:
        _conn().execute(
            """INSERT INTO mcp_invocations
               (ts, request_id, correlation_id, server_instance_id, client_surface, transport,
                actor_id, capability_profile, tool_name, tool_category, project, input_hash,
                output_hash, is_error, request_source, replay_safe, status,
                reason_code, duration_ms, error_code, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now, request_id, correlation_id, SERVER_INSTANCE_ID, identity.client_surface,
                identity.transport, identity.actor_id, identity.capability_profile, tool_name,
                TOOL_CATEGORIES.get(tool_name, "unknown"), project,
                _hash(canonical_input), _commitment(canonical_output), int(is_error),
                request_source, int(replay_safe), status, reason_code,
                round((time.monotonic() - started_at) * 1000), error_code, now,
            ),
        )
        _conn().commit()


def new_request_id() -> str:
    return str(uuid.uuid4())


def mutation_request_id(
    tool_name: str,
    args: dict[str, Any],
    correlation_id: str | None,
    identity: ExecutionIdentity,
) -> tuple[str, str, bool]:
    """Return a durable key only when the client explicitly supplied one."""
    supplied = str(args.get("request_id", "")).strip()
    if supplied:
        source, stable_value, replay_safe = "client", supplied, True
    else:
        source, stable_value, replay_safe = "generated", new_request_id(), False
    namespace = {
        "actor_id": identity.actor_id,
        "client_surface": identity.client_surface,
        "transport": identity.transport,
        "capability_profile": identity.capability_profile,
        "tool_name": tool_name,
        "request": stable_value,
    }
    return _hash(json.dumps(namespace, sort_keys=True, separators=(",", ":"))), source, replay_safe


def claim_mutation(
    *,
    request_id: str,
    correlation_id: str | None,
    identity: ExecutionIdentity,
    tool_name: str,
    project: str | None,
    args: dict[str, Any],
    request_source: str,
    replay_safe: bool,
) -> tuple[str, dict[str, Any] | None, bool]:
    """Reserve a mutation or return its durable completed/in-progress outcome."""
    from datetime import datetime, timezone
    from orchestrator.db import _conn, _local, _write_lock

    canonical_input = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    now = datetime.now(timezone.utc).isoformat()
    with _write_lock:
        conn = _conn()
        in_atomic_mutation = getattr(_local, "atomic_mutation_depth", 0)
        try:
            if not in_atomic_mutation:
                conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO mcp_invocations
                   (ts, request_id, correlation_id, server_instance_id, client_surface, transport,
                    actor_id, capability_profile, tool_name, tool_category, project, input_hash,
                    output_hash, is_error, request_source, replay_safe, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 'in_progress', ?)""",
                (
                    now, request_id, correlation_id, SERVER_INSTANCE_ID, identity.client_surface,
                    identity.transport, identity.actor_id, identity.capability_profile, tool_name,
                    TOOL_CATEGORIES[tool_name], project, _hash(canonical_input), _commitment("null"),
                    request_source, int(replay_safe), now,
                ),
            )
            from orchestrator.db import commit_if_not_atomic
            commit_if_not_atomic(conn)
            return "claimed", None, False
        except Exception as exc:
            if not in_atomic_mutation:
                conn.rollback()
            row = conn.execute(
                """SELECT tool_name, input_hash, status, output_hash, is_error
                   FROM mcp_invocations WHERE request_id=?""",
                (request_id,),
            ).fetchone()
            if row is None:
                raise exc
            if row["tool_name"] != tool_name or row["input_hash"] != _hash(canonical_input):
                return "mismatch", None, True
            if row["status"] == "in_progress":
                return "in_progress", None, True
            return "replay", {
                "request_id": request_id,
                "status": row["status"],
                "replayed": True,
            }, bool(row["is_error"])


def complete_mutation(
    request_id: str, result: Any, is_error: bool, started_at: float,
    reason_code: str | None = None, error_code: str | None = None,
) -> None:
    """Persist terminal outcome metadata without retaining the MCP result payload."""
    from orchestrator.db import _conn, _write_lock

    canonical_output = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    with _write_lock:
        conn = _conn()
        conn.execute(
            """UPDATE mcp_invocations
               SET output_hash=?, is_error=?, status=?, reason_code=?,
                   duration_ms=?, error_code=?
               WHERE request_id=? AND status='in_progress'""",
            (
                _commitment(canonical_output), int(is_error),
                "error" if is_error else "success", reason_code,
                round((time.monotonic() - started_at) * 1000), error_code, request_id,
            ),
        )
        from orchestrator.db import commit_if_not_atomic
        commit_if_not_atomic(conn)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _commitment(value: str) -> str:
    """Return an opaque, server-local commitment without exposing its key."""
    global _commitment_key, _commitment_key_path
    from orchestrator.paths import HOME_DIR

    key_path = HOME_DIR / "mcp-commitment.key"
    if _commitment_key is None or _commitment_key_path != key_path:
        HOME_DIR.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as key_file:
                key_file.write(secrets.token_bytes(32))
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass
        _commitment_key = key_path.read_bytes()
        _commitment_key_path = key_path
    return hmac.new(_commitment_key, value.encode("utf-8"), hashlib.sha256).hexdigest()
