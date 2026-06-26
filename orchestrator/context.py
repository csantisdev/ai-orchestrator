"""Lectura y generación del context.yaml de cada proyecto."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from orchestrator.paths import PROJECT_CONTEXT_DIRNAME, PROJECT_CONTEXT_FILENAME


class ContextNotFoundError(Exception):
    """El proyecto no tiene context.yaml y no se pudo crear uno por defecto."""


@dataclass
class ProjectContext:
    name: str
    stack: str = ""
    description: str = ""
    conventions: list[str] = field(default_factory=list)
    default_provider: str | None = None
    routing_notes: str = ""
    keyword_hints: list[dict] = field(default_factory=list)
    daily_budget_usd: float | None = None
    skip_dirs: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def context_path(self) -> Path | None:
        return self.raw.get("_context_path")


def _context_file_path(project_path: Path) -> Path:
    return project_path / PROJECT_CONTEXT_DIRNAME / PROJECT_CONTEXT_FILENAME


def context_exists(project_path: Path) -> bool:
    return _context_file_path(project_path).exists()


def load_context(project_path: Path) -> ProjectContext:
    """Carga el context.yaml de un proyecto. Lanza si no existe."""
    ctx_path = _context_file_path(project_path)
    if not ctx_path.exists():
        raise ContextNotFoundError(
            f"No existe {ctx_path}. Corré 'ai-orchestrator add' para generarlo."
        )

    with ctx_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    preferred = raw.get("preferred_models", {}) or {}

    return ProjectContext(
        name=raw.get("name", project_path.name),
        stack=raw.get("stack", ""),
        description=raw.get("description", ""),
        conventions=raw.get("conventions", []) or [],
        default_provider=preferred.get("default"),
        routing_notes=preferred.get("notes", ""),
        keyword_hints=raw.get("keyword_hints", []) or [],
        daily_budget_usd=raw.get("daily_budget_usd"),
        skip_dirs=raw.get("skip_dirs", []) or [],
        raw={**raw, "_context_path": ctx_path},
    )


def create_default_context(
    project_path: Path,
    name: str,
    stack: str = "",
    description: str = "",
    default_provider: str = "claude",
) -> Path:
    """Genera un context.yaml base dentro del proyecto."""
    ctx_dir = project_path / PROJECT_CONTEXT_DIRNAME
    ctx_dir.mkdir(parents=True, exist_ok=True)
    ctx_path = ctx_dir / PROJECT_CONTEXT_FILENAME

    if ctx_path.exists():
        return ctx_path

    template = {
        "name": name,
        "stack": stack or "(completar: ej. PHP/Laravel, Java Spring Boot, React/Next.js)",
        "description": description or "(completar: breve descripción del proyecto)",
        "conventions": [
            "(ej. PSR-12, usar Form Requests para validación)",
        ],
        "preferred_models": {
            "default": default_provider,
            "notes": (
                "Texto libre para el router: cuándo preferir otro modelo. "
                "Ej: 'Tareas de seguridad o arquitectura -> siempre Claude. "
                "Tareas repetitivas de tests o boilerplate -> DeepSeek.'"
            ),
        },
        "keyword_hints": [
            {"match": "seguridad", "provider": "claude", "weight": 3},
            {"match": "arquitectura", "provider": "claude", "weight": 3},
            {"match": "test", "provider": "deepseek", "weight": 2},
            {"match": "boilerplate", "provider": "deepseek", "weight": 2},
            {"match": "refactor", "provider": "openai", "weight": 1},
        ],
    }

    with ctx_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(template, f, allow_unicode=True, sort_keys=False)

    return ctx_path


def save_skip_dirs(project_path: Path, skip_dirs: list[str]) -> None:
    """Persiste skip_dirs en el context.yaml del proyecto sin tocar el resto."""
    ctx_path = _context_file_path(project_path)
    if not ctx_path.exists():
        raise ContextNotFoundError(
            f"No existe {ctx_path}. Corré 'ai-orchestrator add' para generarlo."
        )
    with ctx_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data["skip_dirs"] = skip_dirs
    with ctx_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
