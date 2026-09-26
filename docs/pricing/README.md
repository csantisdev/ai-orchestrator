# Catalogo de precios de modelos

Fuente canonica y versionada de precios por modelo, referenciada en la
[ADR-002](../decisions/adrs/ADR-002-model-pricing-catalog.md).

## Archivos

- `schema.json`: JSON Schema (draft 2020-12) que valida la estructura de
  `models.json`.
- `models.json`: catalogo de modelos con precio vigente por proveedor.

## Como se resuelve el precio efectivo

`orchestrator/catalog.py` implementa `load_price_catalog(config, refresh=False)`
con este orden de precedencia:

1. `config.yaml` clave `pricing` — override explicito del usuario, por modelo:
   cada modelo declarado pisa su precio sobre la tabla base (la primera fuente
   disponible entre 2 y 5) y el resto del catalogo sigue vigente. Cada entrada
   necesita `input` y `output` numericos >= 0 (`cache_write` y `cache_read`
   opcionales); las entradas invalidas se ignoran con un warning. `pricing show`
   muestra la fuente como `config+<base>` y marca que modelos vienen de config.
2. Cache local en `~/.ai-orchestrator/pricing-cache.json`, si no expiro segun
   `catalog.refresh_ttl_hours`.
3. Catalogo remoto, solo si se llama con `refresh=True` y
   `config.yaml` tiene `catalog.allow_remote: true` y `catalog.pricing_url`
   definido. Si la descarga o el schema fallan, no rompe el caller.
4. Este archivo bundleado (`docs/pricing/models.json`).
5. `DEFAULT_PRICING` en `orchestrator/costs.py` como ultimo fallback.

Si un modelo no aparece en ninguna fuente, `calculate_cost` devuelve
`cost_usd = None` en vez de lanzar una excepcion. Si no hay precio exacto pero
alguna clave esta contenida en el nombre del modelo, se usa la mas larga como
aproximacion. Cada run guarda en `cost_pricing_key` la clave de precio usada,
y `doctor` avisa de los runs con tokens y sin costo y de los costeados con el
precio de otro modelo.

## Actualizar precios

Editar `models.json` a mano, respetando `schema.json`, y actualizar
`updated_at` (catalogo) y `verified_at` (por modelo). Cambiar precios no
recalcula los costos ya persistidos en `runs.db`; para eso:

```powershell
ai-orchestrator pricing recompute                       # simulacion: que runs cambian y cuanto
ai-orchestrator pricing recompute --apply               # aplica, previo respaldo en ~/.ai-orchestrator/backups/
ai-orchestrator pricing recompute --include-untracked   # suma runs con costo anterior al registro de la clave
```

Solo se recalculan runs sin costo o con costo aproximado, y solo cuando el
modelo tiene precio exacto. `--include-untracked` recalcula tambien costos
historicos con los precios vigentes, lo que cambia el gasto pasado si el precio
del modelo cambio desde entonces.

## Limitacion: precios de contexto largo

Los modelos gpt-5.4, gpt-5.5 y gpt-5.6 de OpenAI tienen una tarifa de
contexto largo: segun la ficha oficial de cada modelo, los prompts de mas de
272K tokens de entrada se cobran a 2x input y 1.5x output durante toda la
sesion (el `notes` de cada entrada de `models.json` lo recuerda). El catalogo
solo modela la tarifa de contexto corto, asi que el costo de esas sesiones
queda subestimado.

No se modela porque los runs no guardan el dato que dispara la tarifa: los
watchers de Claude Code y Codex suman los tokens de toda la sesion, sin el
tamano maximo de un prompt individual. Modelarlo requeriria registrar ese
maximo al importar (el rollout de Codex tiene un evento de tokens por turno) y
una tabla de precios con umbral por modelo.

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
[mapa de implementacion](../decisions/support/ADR-002/implementation-map.md) para el
detalle por etapa. Queda pendiente evaluar si conviene automatizar tambien
el discovery de modelos (Etapa 3) desde el mismo workflow, usando secrets de
API keys en CI — decision deliberadamente diferida por el riesgo de exponer
credenciales en logs de Actions.
