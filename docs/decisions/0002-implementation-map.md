# Mapa de implementacion: catalogo de modelos y precios

Este mapa aterriza la Decision 0002 en cambios concretos dentro de
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

## Etapa 4: automatizacion del catalogo publico

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

## Checklist inicial

- [ ] Crear archivos publicos en `docs/pricing/`.
- [ ] Implementar `orchestrator/catalog.py`.
- [ ] Agregar constantes de cache en `orchestrator/paths.py`.
- [ ] Migrar `get_pricing_table(config)`.
- [ ] Migrar `watcher.py` y `codex_watcher.py`.
- [ ] Agregar tests de precedencia y fallback.
- [ ] Agregar `pricing validate`.
- [ ] Agregar `GET /pricing`.
- [ ] Planificar discovery de modelos.
- [ ] Planificar integracion del router con `purpose`.
