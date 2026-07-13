---
type: support
supports: ADR-002
status: completed
updated: 2026-07-07
---

# Mapa de implementación de ADR-002

Este mapa aterriza ADR-002 (catálogo versionado de modelos y precios) en cambios concretos dentro de
`ai-orchestrator`. La regla de orden es mantener primero compatibilidad con el
calculo actual de costos y despues abrir nuevas superficies: API local, CLI,
discovery y router.

## Objetivo operativo

Crear un catalogo versionado de modelos y precios que pueda ser publicado en
`docs/pricing/`, cacheado localmente y consumido por el runtime sin bloquear
runs. El primer punto de integracion debe ser `get_pricing_table(config)`,
porque los callers actuales ya dependen de esa funcion o de la forma legacy de
`DEFAULT_PRICING`.

## Mapa de modulos

| Area | Archivos actuales | Cambio recomendado |
|---|---|---|
| Fuente legacy de precios | `orchestrator/costs.py` | Mantener `DEFAULT_PRICING` como fallback minimo. No mover `calculate_cost` en la primera etapa. |
| Resolucion de config | `orchestrator/config.py` | Cambiar `get_pricing_table(config)` para delegar en `orchestrator.catalog.get_effective_pricing(config)`. |
| Catalogo nuevo | `orchestrator/catalog.py` | Nuevo modulo para cargar JSON, cache, remoto, alias y tabla efectiva legacy. |
| Catalogo publico | `docs/pricing/schema.json`, `docs/pricing/models.json`, `docs/pricing/README.md` | Nueva fuente versionada y auditable. |
| Cache local | `orchestrator/paths.py` | Agregar constantes para `PRICING_CACHE_PATH` y, despues, `MODELS_CACHE_PATH`. |
| CLI | `orchestrator/cli.py` | Agregar grupo `pricing` con `show`, `refresh`, `validate`. Agregar `models` en etapa posterior. |
| API local | `orchestrator/server.py` | Agregar `GET /pricing` y `POST /pricing/refresh` junto a los endpoints existentes. |
| Imports externos | `orchestrator/watcher.py`, `orchestrator/codex_watcher.py` | Migrar de `config.get("pricing") or DEFAULT_PRICING` a `get_pricing_table(config)`. |
| Router | `orchestrator/router.py` | En etapa 5, reemplazar heuristicas fijas por una vista compacta de perfiles del catalogo. |
| Tests | `tests/` | Agregar `test_catalog.py`; extender tests de CLI/API cuando existan endpoints. |

## Etapa 1: catalogo estatico y resolver local

Entregable:

- `docs/pricing/schema.json`
- `docs/pricing/models.json`
- `docs/pricing/README.md`
- `orchestrator/catalog.py`
- `get_pricing_table(config)` usando el resolver nuevo
- tests unitarios de precedencia

Orden de precedencia que debe probarse:

1. `config["pricing"]`
2. cache local valida
3. remoto si `catalog.allow_remote=true` y se solicita refresh
4. `DEFAULT_PRICING`
5. sin precio si el modelo no existe

Funciones minimas sugeridas:

```python
def load_price_catalog(config: dict, refresh: bool = False) -> dict: ...
def get_effective_pricing(config: dict) -> dict: ...
def get_model_price(config: dict, provider: str, model: str) -> dict | None: ...
def list_catalog_models(config: dict, provider: str | None = None) -> list[dict]: ...
```

Criterio de cierre:

- `calculate_cost(result, get_pricing_table(config))` sigue funcionando sin
  cambios en `cli.py`, `background.py` y `router.py`.
- Si no hay catalogo ni cache, se usa `DEFAULT_PRICING`.
- Si hay override en `config.yaml`, gana sobre todo lo demas.

## Etapa 2: CLI y API local

Entregable:

- `ai-orchestrator pricing show`
- `ai-orchestrator pricing refresh`
- `ai-orchestrator pricing validate`
- `GET /pricing`
- `POST /pricing/refresh`

Semantica recomendada:

- `pricing show`: imprime tabla efectiva, fuente y fecha de verificacion.
- `pricing refresh`: descarga catalogo remoto y actualiza cache; si falla, no
  rompe el comando.
- `pricing validate`: lista modelos usados en `runs` sin entrada de precio.
- `/pricing`: devuelve tabla efectiva y metadatos de fuente.
- `/pricing/refresh`: ejecuta refresh manual desde dashboard.

Criterio de cierre:

- Un error de red devuelve warning/error controlado y conserva cache/fallback.
- El dashboard puede consumir `/pricing` sin exponer credenciales.

## Etapa 3: discovery de modelos

Entregable:

- `orchestrator/model_discovery.py`
- `orchestrator/discovery/openai.py`
- `orchestrator/discovery/anthropic.py`
- `orchestrator/discovery/deepseek.py`
- `orchestrator/discovery/gemini.py`
- `ai-orchestrator models list`
- `ai-orchestrator models refresh`
- `GET /models`
- `POST /models/refresh`

Regla de diseno:

Discovery no debe vivir en `providers/*`, porque esos providers hoy tienen una
responsabilidad limpia: ejecutar `complete(...)`. Los adaptadores de discovery
deben ser best-effort por proveedor y guardar estado local.

Criterio de cierre:

- Se pueden comparar modelos disponibles contra modelos con precio.
- Errores de un proveedor no rompen el refresh global.

## Etapa 6: automatizacion del catalogo publico

*Renumerada de "Etapa 4" (numeración original de este mapa) a "Etapa 6" para coincidir
con el commit real que la entregó: `8929138 — feat: automatizacion y validacion GitHub
del catalogo de precios (Decision 0002 etapa 6)`. No se reescribió el commit — el
historial de git es inmutable — se corrigió el mapa para que ambos coincidan. No existe
ningún commit etiquetado "Decision 0002 etapa 4": la integración de runtime que en algún
momento hubiera ocupado ese número quedó absorbida dentro del commit de Etapa 1
(`450e4a8`), y el número 4 nunca se usó. Ver la tabla de trazabilidad al final de este
documento.*

Entregable:

- GitHub Action o script de mantenimiento.
- Validacion de `docs/pricing/models.json` contra `schema.json`.
- Reporte de modelos nuevos, deprecados o sin precio.

Criterio de cierre:

- El proceso propone cambios, issues o PRs; no actualiza precios por scraping
  en caliente durante un run.

## Etapa 5: router basado en perfiles

Entregable:

- Vista compacta `profiles_for_router`.
- Prompt del router enriquecido con modelos disponibles, costo relativo,
  estado y tags de proposito.
- Fallback a heuristicas actuales si el catalogo no tiene `purpose`.

Reglas:

- No sugerir modelos `deprecated` salvo override explicito.
- Penalizar modelos sin precio para tareas normales.
- Priorizar notas del proyecto y provider definido en el paso activo.
- Combinar catalogo con ratings historicos ya usados por el router.

## Orden recomendado de PRs

1. `pricing-catalog-static`: schema, models, catalog loader, tests.
2. `pricing-runtime-integration`: `get_pricing_table`, watchers, cache paths.
3. `pricing-cli-api`: comandos y endpoints locales.
4. `models-discovery`: adaptadores por proveedor y cache de disponibilidad.
5. `router-model-profiles`: vista compacta y prompt actualizado.
6. `catalog-maintenance`: validacion automatica y flujo GitHub.

## Riesgos que deben quedar cubiertos por tests

- Override local pierde precedencia frente al remoto.
- Catalogo remoto invalido pisa cache valido.
- Error de red rompe un run.
- Modelo desconocido produce excepcion en vez de costo `None`.
- Alias resuelve a precio equivocado entre proveedores distintos.
- `pricing_history` tiene solapamiento de vigencias.

## Estado final de implementación

Todos los items de esta lista quedaron cerrados; se conserva el detalle como registro,
no como pendiente:

- [x] Crear archivos publicos en `docs/pricing/`.
- [x] Implementar `orchestrator/catalog.py`.
- [x] Agregar constantes de cache en `orchestrator/paths.py`.
- [x] Migrar `get_pricing_table(config)`.
- [x] Migrar `watcher.py` y `codex_watcher.py`.
- [x] Agregar tests de precedencia y fallback.
- [x] Agregar `pricing validate`.
- [x] Agregar `GET /pricing`.
- [x] Planificar discovery de modelos.
- [x] Planificar integracion del router con `purpose`.
- [x] Agregar validaciones post-LLM en el router (API key, modelo en catalogo, modelo deprecated).
- [x] Agregar `validate_model_for_provider` en `orchestrator/catalog.py`.

## Tabla de trazabilidad

Entregas reales, verificadas contra `git log --oneline`. Los commits son fuente de
verdad inmutable; esta tabla se ajusta a ellos, nunca al revés. No existe una entrega
etiquetada "etapa 4" — ver la nota en la sección "Etapa 6" más arriba.

| Entrega | Commit | Evidencia | Estado |
|---|---|---|---|
| Etapa 1 — catálogo estático y resolver local | `450e4a8` | `tests/test_catalog.py` | implementada |
| Etapa 2 — CLI y API local de pricing | `8d9b8ce` | comandos `pricing show/refresh/validate`, `GET/POST /pricing` | implementada |
| Etapa 3 — discovery de modelos por proveedor | `1017237` | `orchestrator/discovery/*.py`, comandos `models list/refresh` | implementada |
| Etapa 5 — perfiles del catálogo en el router | `cb7ee24` | `router.py::_format_profiles_section` | implementada |
| Etapa 6 — automatización y validación GitHub | `8929138` | `scripts/validate_pricing_catalog.py`, `.github/workflows/pricing-catalog.yml` | implementada |
| Hardening — validaciones post-LLM y `validate_model_for_provider` | `deb8be9` | `router.py`, `catalog.py` | implementada |
| Cierre — checklist final + `api_key` null tolerado | `e0189a3` | — | implementada |
