"""Gestión del índice central de proyectos (alias -> path)."""

from __future__ import annotations

from pathlib import Path

import yaml

from orchestrator.paths import HOME_DIR, INDEX_PATH


class ProjectNotFoundError(Exception):
    """El alias solicitado no existe en el índice."""


def _ensure_home_dir() -> None:
    HOME_DIR.mkdir(parents=True, exist_ok=True)


def load_index() -> dict:
    """Carga el índice central. Si no existe, devuelve estructura vacía."""
    if not INDEX_PATH.exists():
        return {"projects": {}}

    with INDEX_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    data.setdefault("projects", {})
    return data


def save_index(data: dict) -> None:
    _ensure_home_dir()
    with INDEX_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=True)


def add_project(alias: str, path: str) -> None:
    data = load_index()
    data["projects"][alias] = str(Path(path).resolve())
    save_index(data)


def remove_project(alias: str) -> None:
    data = load_index()
    if alias not in data["projects"]:
        raise ProjectNotFoundError(f"El alias '{alias}' no existe en el índice.")
    del data["projects"][alias]
    save_index(data)


def get_project_path(alias: str) -> Path:
    data = load_index()
    projects = data.get("projects", {})
    if alias not in projects:
        raise ProjectNotFoundError(
            f"El alias '{alias}' no está registrado. "
            f"Usá 'ai-orchestrator add {alias} --path <ruta>' primero."
        )
    return Path(projects[alias])


def list_projects() -> dict:
    return load_index().get("projects", {})
