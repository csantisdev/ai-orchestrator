"""Inventario de las rutas POST heredadas del dashboard (RFC-010 §7, PR 2: transición).

Cada ruta con efectos que el servidor atiende fuera de `/api/v1/` está acá con la vista que la
usa, el comando gobernado que la va a reemplazar (RFC-010 §3.1) y cuándo se retira. Mientras su
vista no migre, la ruta sigue funcionando sin cambios de contrato. `tests/test_legacy_routes.py`
compara este inventario con las rutas reales del servidor: una ruta POST nueva fuera de
`/api/v1/` falla el test (invariante I1), y al migrar una vista sus rutas se borran de acá y del
servidor en el mismo PR.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Vistas del dashboard que todavía escriben por rutas heredadas (spec §24.5, ola 6).
OWNERS = {
    "flujos": "Trabajo › Flujos (heredado)",
    "actividad": "Ejecuciones › Actividad (heredado)",
    "proyectos": "Ajustes › Proyectos",
    "datos": "Ajustes › Datos",
    "config": "Control › Proveedores",
    "barra": "Barra de Activity (doctor, fix, sync, index)",
    "ninguna": "Sin llamador en la UI",
}

# Categorías de RFC-008 más las dos que agrega RFC-010 (§3.1).
CATEGORIES = frozenset({
    "read", "append", "workflow_mutation", "workflow_transition", "memory_ingest",
    "project_admin", "maintenance",
})


@dataclass(frozen=True)
class LegacyRoute:
    path: str
    owners: tuple[str, ...]
    command: Optional[str]
    category: Optional[str]
    job: bool = False
    destructive: bool = False
    provider: bool = False
    note: str = ""


# Retiro: cuando migra la última vista dueña, salvo que la nota diga otra cosa. Las rutas sin
# llamador en la UI se retiran en la ola 6 si siguen sin uso.
LEGACY_POST_ROUTES = (
    LegacyRoute("/clean/unmapped", ("datos",), "purge_unmapped_data", "maintenance", destructive=True),
    LegacyRoute("/purge-chroma-docs", ("datos",), "purge_rag_docs", "maintenance", job=True, destructive=True),
    LegacyRoute("/purge-chroma-responses", ("datos",), "purge_rag_responses", "maintenance", job=True, destructive=True),
    LegacyRoute("/delete-contexts", ("datos",), "delete_contexts", "maintenance", destructive=True),
    LegacyRoute("/context/{id}/delete", ("flujos",), "delete_context", "maintenance", destructive=True),
    LegacyRoute("/clear-imports", ("datos", "proyectos"), "clear_imports", "maintenance", destructive=True),
    LegacyRoute("/rate-run", ("actividad",), "rate_run", "append"),
    LegacyRoute("/evaluate-run", ("ninguna",), "evaluate_run", "append"),
    LegacyRoute("/import-context", ("proyectos",), "import_agent_context", "memory_ingest",
                note="Equivale a la herramienta MCP del mismo nombre."),
    LegacyRoute("/sync-cc", ("barra", "proyectos"), "sync_sessions", "maintenance", job=True),
    LegacyRoute("/sync-git", ("barra",), "sync_sessions", "maintenance", job=True),
    LegacyRoute("/sync-codex", ("barra",), "sync_sessions", "maintenance", job=True),
    LegacyRoute("/rates/refresh", ("config",), "refresh_exchange_rates", "maintenance", job=True),
    LegacyRoute("/pick-folder", ("proyectos",), None, None,
                note="Abre el selector de carpetas del sistema: no es un comando. Se retira con "
                     "Ajustes › Proyectos (la ruta del proyecto se escribe o se confirma desde git)."),
    LegacyRoute("/chroma-stats/refresh", ("datos",), "refresh_rag_stats", "maintenance", job=True),
    LegacyRoute("/pricing/refresh", ("ninguna",), "refresh_pricing_catalog", "maintenance", job=True),
    LegacyRoute("/models/refresh", ("ninguna",), "refresh_models_catalog", "maintenance", job=True),
    LegacyRoute("/config/bcentral", ("config",), "set_exchange_credentials", "maintenance"),
    LegacyRoute("/add-project", ("proyectos",), "register_project", "project_admin"),
    LegacyRoute("/project/rename", ("proyectos",), "merge_projects", "project_admin", job=True, destructive=True,
                note="Renombrar es el caso particular de la fusión con destino inexistente (RFC-010 §3.4.3)."),
    LegacyRoute("/index-docs", ("barra", "proyectos"), "index_project_docs", "maintenance", job=True),
    LegacyRoute("/create-context", ("flujos",), "create_context", "workflow_mutation",
                note="Equivale a la herramienta MCP del mismo nombre."),
    LegacyRoute("/advance-step", ("flujos",), "advance_step", "workflow_transition",
                note="Equivale a la herramienta MCP del mismo nombre."),
    LegacyRoute("/skip-step", ("flujos",), "skip_step", "workflow_transition",
                note="Equivale a la herramienta MCP del mismo nombre."),
    LegacyRoute("/run-doctor", ("barra",), "run_doctor", "read", job=True),
    LegacyRoute("/run-fix", ("barra",), "run_fix", "maintenance", job=True),
    LegacyRoute("/run", ("actividad", "flujos"), "run_task", "append", job=True, provider=True,
                note="Llama a un proveedor: admisión de presupuesto y gate de egress (RFC-010 §3.5)."),
)


def by_path() -> dict[str, LegacyRoute]:
    return {route.path: route for route in LEGACY_POST_ROUTES}
