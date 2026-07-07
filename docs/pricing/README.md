# Catalogo de precios de modelos

Fuente canonica y versionada de precios por modelo, referenciada en la
[Decision 0002](../decisions/0002-model-pricing-catalog.md).

## Archivos

- `schema.json`: JSON Schema (draft 2020-12) que valida la estructura de
  `models.json`.
- `models.json`: catalogo de modelos con precio vigente por proveedor.

## Como se resuelve el precio efectivo

`orchestrator/catalog.py` implementa `load_price_catalog(config, refresh=False)`
con este orden de precedencia:

1. `config.yaml` clave `pricing` — override explicito del usuario, siempre gana.
2. Cache local en `~/.ai-orchestrator/pricing-cache.json`, si no expiro segun
   `catalog.refresh_ttl_hours`.
3. Catalogo remoto, solo si se llama con `refresh=True` y
   `config.yaml` tiene `catalog.allow_remote: true` y `catalog.pricing_url`
   definido. Si la descarga o el schema fallan, no rompe el caller.
4. Este archivo bundleado (`docs/pricing/models.json`).
5. `DEFAULT_PRICING` en `orchestrator/costs.py` como ultimo fallback.

Si un modelo no aparece en ninguna fuente, `calculate_cost` devuelve
`cost_usd = None` en vez de lanzar una excepcion.

## Actualizar precios

Editar `models.json` a mano, respetando `schema.json`, y actualizar
`updated_at` (catalogo) y `verified_at` (por modelo). No se recalculan
costos ya persistidos en `runs.db` al cambiar este archivo.

## Etapas futuras

Discovery de modelos por API de proveedor, comandos `pricing`/`models` en el
CLI, endpoints `/pricing` y `/models`, y uso del catalogo en el router estan
fuera del alcance de la Etapa 1 — ver el
[mapa de implementacion](../decisions/0002-implementation-map.md).
