"""Policy, validation, and observed audit records for the local MCP boundary."""

from __future__ import annotations

import hashlib
import json
import os
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
) -> None:
    """Write observed MCP evidence; deliberately never persists raw tool input."""
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
                output_hash, status, reason_code, duration_ms, error_code, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now, request_id, correlation_id, SERVER_INSTANCE_ID, identity.client_surface,
                identity.transport, identity.actor_id, identity.capability_profile, tool_name,
                TOOL_CATEGORIES.get(tool_name, "unknown"), project,
                _hash(canonical_input), _hash(canonical_output), status, reason_code,
                round((time.monotonic() - started_at) * 1000), error_code, now,
            ),
        )
        _conn().commit()


def new_request_id() -> str:
    return str(uuid.uuid4())


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
