"""Perfil y alcance de la UI (RFC-010 §3.1): fail-closed como el MCP de RFC-008.

La configuración vive en `~/.ai-orchestrator/ui-governance.json` y la escribe
`ai-orchestrator fix --ui-profile <perfil> --ui-projects <alias,...>`. Sin archivo, con JSON
inválido o con un perfil desconocido, la UI es `readonly` y sin proyectos en alcance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestrator.mcp_governance import PROFILE_CAPABILITIES, ExecutionIdentity

UI_CONFIG_FILENAME = "ui-governance.json"


def ui_config_path() -> Path:
    import orchestrator.paths as paths
    return paths.HOME_DIR / UI_CONFIG_FILENAME


def _read_raw() -> Any:
    path = ui_config_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False


def _projects(raw: Any) -> list[str]:
    value = raw.get("projects") if isinstance(raw, dict) else None
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def ui_identity() -> ExecutionIdentity:
    """Identidad con la que la UI ejecuta comandos; se relee en cada comando."""
    raw = _read_raw()
    profile = raw.get("profile") if isinstance(raw, dict) else None
    if profile not in PROFILE_CAPABILITIES:
        profile = "readonly"
    return ExecutionIdentity(
        client_surface="dashboard",
        transport="http",
        actor_id=None,
        capability_profile=profile,
        project_scope=frozenset(_projects(raw)),
    )


def write_ui_config(profile: str, projects: list[str]) -> Path:
    if profile not in PROFILE_CAPABILITIES:
        raise ValueError(f"perfil de UI desconocido: {profile}")
    scope = sorted({p.strip() for p in projects if p.strip()})
    path = ui_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"profile": profile, "projects": scope}, indent=2) + "\n", encoding="utf-8")
    return path


def ui_config_issues(known_projects: set[str]) -> list[str]:
    """Motivos por los que la UI quedaría en solo lectura o con alcance incompleto."""
    raw = _read_raw()
    if raw is None:
        return ["sin configuración: la UI es 'readonly' (solo lee)"]
    if raw is False or not isinstance(raw, dict):
        return [f"{UI_CONFIG_FILENAME} ilegible: la UI es 'readonly' sin alcance"]
    issues = []
    profile = raw.get("profile")
    if profile not in PROFILE_CAPABILITIES:
        issues.append(f"perfil '{profile}' inválido: la UI es 'readonly'")
    projects = _projects(raw)
    if not projects:
        issues.append("sin proyectos en alcance: todo comando de proyecto se deniega")
    unknown = sorted(set(projects) - known_projects)
    if unknown:
        issues.append(f"alcance con alias no registrados: {', '.join(unknown)}")
    return issues
