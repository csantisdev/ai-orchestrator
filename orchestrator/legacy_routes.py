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
    """Una ruta POST heredada.

    - `handler`: método de `DashboardHandler` que la atiende (el servidor despacha desde acá);
    - `job`: el comando que la reemplace corre como trabajo (RFC-010 §3.3);
    - `destructive`: borra o reescribe datos y exige el hash de una vista previa (I16); una
      transición de workflow como omitir un paso no lo es;
    - `llm_provider`: llama a un proveedor de IA (admisión de presupuesto y gate, §3.5);
    - `egress`: sale a la red (proveedor de IA o servicio externo);
    - `secrets`: recibe o guarda credenciales.
    """

    path: str
    handler: str
    owners: tuple[str, ...]
    command: Optional[str]
    category: Optional[str]
    job: bool = False
    destructive: bool = False
    llm_provider: bool = False
    egress: bool = False
    secrets: bool = False
    note: str = ""


# Retiro: cuando migra la última vista dueña, salvo que la nota diga otra cosa. Las rutas sin
# llamador en la UI se retiran en la ola 6 si siguen sin uso.
LEGACY_POST_ROUTES = (
    LegacyRoute("/clean/unmapped", "_post_clean_unmapped", ("datos",), "purge_unmapped_data", "maintenance", destructive=True),
    LegacyRoute("/purge-chroma-docs", "_post_purge_chroma_docs", ("datos",), "purge_rag_docs", "maintenance", job=True, destructive=True),
    LegacyRoute("/purge-chroma-responses", "_post_purge_chroma_responses", ("datos",), "purge_rag_responses", "maintenance", job=True, destructive=True),
    LegacyRoute("/delete-contexts", "_post_delete_contexts", ("datos",), "delete_contexts", "maintenance", destructive=True),
    LegacyRoute("/context/{id}/delete", "_post_context_delete", ("flujos",), "delete_context", "maintenance", destructive=True),
    LegacyRoute("/clear-imports", "_post_clear_imports", ("datos", "proyectos"), "clear_imports", "maintenance", destructive=True),
    LegacyRoute("/rate-run", "_post_rate_run", ("actividad",), "rate_run", "workflow_mutation",
                note="Sobrescribe (o borra) la valoración del run: no es `append`. Al migrar, la "
                     "valoración pasa a registrarse como evidencia de solo agregar o exige versión."),
    LegacyRoute("/evaluate-run", "_post_evaluate_run", ("ninguna",), "evaluate_run", "workflow_mutation",
                note="Sobrescribe clase de tarea, verificación y valoración del run; igual que rate_run."),
    LegacyRoute("/import-context", "_post_import_context", ("proyectos",), "import_agent_context", "memory_ingest",
                note="Equivale a la herramienta MCP del mismo nombre."),
    LegacyRoute("/sync-cc", "_post_sync_cc", ("barra", "proyectos"), "sync_sessions", "maintenance", job=True),
    LegacyRoute("/sync-git", "_post_sync_git", ("barra",), "sync_sessions", "maintenance", job=True),
    LegacyRoute("/sync-codex", "_post_sync_codex", ("barra",), "sync_sessions", "maintenance", job=True),
    LegacyRoute("/rates/refresh", "_post_rates_refresh", ("config",), "refresh_exchange_rates", "maintenance", job=True,
                egress=True),
    LegacyRoute("/pick-folder", "_post_pick_folder", ("proyectos",), None, None,
                note="Abre el selector de carpetas del sistema: no es un comando. Se retira con "
                     "Ajustes › Proyectos (la ruta del proyecto se escribe o se confirma desde git)."),
    LegacyRoute("/chroma-stats/refresh", "_post_chroma_stats_refresh", ("datos",), "refresh_rag_stats", "maintenance", job=True),
    LegacyRoute("/pricing/refresh", "_post_pricing_refresh", ("ninguna",), "refresh_pricing_catalog", "maintenance", job=True,
                egress=True),
    LegacyRoute("/models/refresh", "_post_models_refresh", ("ninguna",), "refresh_models_catalog", "maintenance", job=True,
                egress=True),
    LegacyRoute("/config/bcentral", "_post_config_bcentral", ("config",), "set_exchange_credentials", "maintenance",
                egress=True, secrets=True,
                note="Guarda credenciales y consulta el servicio externo de tipos de cambio."),
    LegacyRoute("/add-project", "_post_add_project", ("proyectos",), "register_project", "project_admin"),
    LegacyRoute("/project/rename", "_post_project_rename", ("proyectos",), "merge_projects", "project_admin", job=True, destructive=True,
                note="Renombrar es el caso particular de la fusión con destino inexistente (RFC-010 §3.4.3)."),
    LegacyRoute("/index-docs", "_post_index_docs", ("barra", "proyectos"), "index_project_docs", "maintenance", job=True),
    LegacyRoute("/create-context", "_post_create_context", ("flujos",), "create_context", "workflow_mutation",
                note="Equivale a la herramienta MCP del mismo nombre."),
    LegacyRoute("/advance-step", "_post_advance_step", ("flujos",), "advance_step", "workflow_transition",
                note="Equivale a la herramienta MCP del mismo nombre."),
    LegacyRoute("/skip-step", "_post_skip_step", ("flujos",), "skip_step", "workflow_transition",
                note="Equivale a la herramienta MCP del mismo nombre."),
    LegacyRoute("/run-doctor", "_post_run_doctor", ("barra",), "run_doctor", "read"),
    LegacyRoute("/run-fix", "_post_run_fix", ("barra",), "run_fix", "maintenance", job=True),
    LegacyRoute("/run", "_post_run", ("actividad", "flujos"), "run_task", "append", job=True, llm_provider=True,
                egress=True,
                note="Llama a un proveedor: admisión de presupuesto y gate de egress (RFC-010 §3.5)."),
)


CONTEXT_DELETE_ROUTE = "/context/{id}/delete"


def by_path() -> dict[str, LegacyRoute]:
    return {route.path: route for route in LEGACY_POST_ROUTES}


# Tabla de despacho del servidor: ruta → nombre del método que la atiende.
LEGACY_POST_HANDLERS = {route.path: route.handler for route in LEGACY_POST_ROUTES}
