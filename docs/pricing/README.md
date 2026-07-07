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

## Perfiles de proposito (`purpose`)

Los modelos usados por defecto en `ROUTER_SYSTEM_PROMPT` tienen un campo
`purpose` (summary/strengths/weaknesses/recommended_for/avoid_for/routing_weight).
`orchestrator/catalog.get_model_profiles(config)` genera la vista compacta que
el router inyecta en su prompt — ver `orchestrator/router.py:_format_profiles_section`.
Modelos sin `purpose` simplemente no aparecen en esa vista; el router sigue
usando sus heuristicas generales de fallback para ellos.

## Validacion automatica

`scripts/validate_pricing_catalog.py` valida `models.json` contra
`schema.json` y, con `--report`, audita:

- modelos con `verified_at` de mas de 180 dias (potencialmente desactualizados);
- modelos en `DEFAULT_PRICING` (costs.py) sin entrada en el catalogo, o viceversa.

No hace llamadas de red ni modifica precios. El workflow
`.github/workflows/pricing-catalog.yml` lo corre en cada PR/push que toque
`docs/pricing/**` (falla el job solo si el schema es invalido) y semanalmente
por cron, abriendo o actualizando un issue de GitHub si hay hallazgos.

## Etapas futuras

Discovery de modelos por API de proveedor (`orchestrator/model_discovery.py`),
comandos `pricing`/`models` en el CLI, endpoints `/pricing` y `/models`, y uso
del catalogo en el router ya estan implementados — ver el
[mapa de implementacion](../decisions/0002-implementation-map.md) para el
detalle por etapa. Queda pendiente evaluar si conviene automatizar tambien
el discovery de modelos (Etapa 3) desde el mismo workflow, usando secrets de
API keys en CI — decision deliberadamente diferida por el riesgo de exponer
credenciales en logs de Actions.
