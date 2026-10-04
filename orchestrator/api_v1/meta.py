"""Vertical meta: datos que el shell necesita antes de cualquier vista."""

from __future__ import annotations

from orchestrator.api_v1 import Request, route


@route("GET", "/api/v1/meta/projects")
def projects(request: Request) -> dict:
    """Proyectos conocidos: registrados en el índice o con runs, ordenados por alias."""
    from orchestrator import index as index_module
    from orchestrator.history import projects_list

    try:
        registered = set(index_module.list_projects().keys())
    except Exception:
        registered = set()
    with_runs = set(projects_list())
    return {
        "projects": [
            {"alias": alias, "registered": alias in registered, "has_runs": alias in with_runs}
            for alias in sorted(registered | with_runs)
        ]
    }
