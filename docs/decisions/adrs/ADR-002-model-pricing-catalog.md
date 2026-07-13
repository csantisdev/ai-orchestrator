# ADR-002: Catálogo versionado de modelos y precios

Fecha: 2026-07-01

Estado: aceptada. Implementación: `implemented`, cerrada 2026-07-07 — ver la [tabla de trazabilidad](../support/ADR-002/implementation-map.md#tabla-de-trazabilidad) para las entregas reales por commit (los commits usan las etiquetas `etapa 1, 2, 3, 5, 6`; no existe un commit `etapa 4` — ver la nota en el mapa).

## Contexto

`ai-orchestrator` calcula costos por run con una tabla local de precios. La
tabla vive en `orchestrator/costs.py` como `DEFAULT_PRICING` y puede ser
sobrescrita desde `~/.ai-orchestrator/config.yaml` bajo la clave `pricing`.

Esta solucion es simple y estable, pero tiene cuatro limites:

- Los precios se vuelven obsoletos cuando un proveedor cambia tarifas.
- Un modelo nuevo puede aparecer en el proveedor antes de existir en el
  orquestador.
- Si el modelo no esta en la tabla, el dashboard muestra costo desconocido.
- La tabla no esta expuesta como referencia machine-readable para otros
  agentes, tareas programadas o servicios externos.

Ya existe un modulo `rates.py`, pero consulta el tipo de cambio USD/CLP del
Banco Central de Chile. No resuelve precios de modelos IA.

El requerimiento es evaluar si cada servicio configurado podria traer modelos
disponibles y precios vigentes, y si conviene publicar una tabla JSON dentro
del sitio estatico del proyecto para consumirla via GitHub.

## Observaciones del codigo actual

La integracion actual de proveedores esta concentrada en `orchestrator/providers`.
Cada provider implementa solo:

```python
complete(prompt: str, system: str = "") -> CompletionResult
```

No existe contrato para discovery de modelos, metadata ni precios. El factory
solo instancia proveedores por nombre (`claude`, `openai`, `deepseek`,
`gemini`) usando `config.yaml`.

El calculo de costo ocurre en tres caminos principales:

- `cli.py`: despues de ejecutar un run interactivo.
- `background.py`: despues de ejecutar un run desde dashboard/background.
- `watcher.py` y `codex_watcher.py`: al importar sesiones externas.

Todos terminan llamando `calculate_cost(result, pricing)`.

Esto indica que la integracion debe mantener compatibilidad con la forma actual:
`calculate_cost` necesita una tabla efectiva en memoria, no una llamada remota
sincronica por cada run.

## Auditoria por proveedor

### OpenAI

OpenAI expone API para listar modelos disponibles:

- `GET /v1/models`
- Documentacion: https://platform.openai.com/docs/api-reference/models/list

Ese endpoint sirve para discovery de modelos, pero no debe asumirse como fuente
de precios. Los precios se publican en documentacion de pricing:

- https://developers.openai.com/api/docs/pricing

Evaluacion:

- Modelos: automatizable con API oficial.
- Precios: requiere tabla mantenida, parsing controlado o revision manual.
- Riesgo: los modelos listados pueden incluir familias no aptas para chat,
  modelos legacy o variantes sin precio compatible con token input/output.

### Anthropic / Claude

Anthropic expone API para listar modelos:

- `GET /v1/models`
- Documentacion: https://platform.claude.com/docs/en/api/models/list

Los precios se publican en documentacion separada:

- https://platform.claude.com/docs/en/about-claude/pricing

Evaluacion:

- Modelos: automatizable con API oficial.
- Precios: mantener tabla propia es mas confiable que depender de scraping.
- Riesgo: Claude tiene cache write/read y descuentos por modalidad. El schema
  no puede limitarse a `input` y `output`.

### DeepSeek

DeepSeek documenta un endpoint compatible con listado de modelos:

- `GET /models`
- Documentacion: https://api-docs.deepseek.com/api/list-models

La documentacion publica modelos y precios en secciones separadas:

- https://api-docs.deepseek.com/

Evaluacion:

- Modelos: automatizable.
- Precios: tabla propia con fuente y fecha de verificacion.
- Riesgo: el proveedor puede mantener alias compatibles con OpenAI y nombres
  comerciales que no coincidan exactamente con los ids de API.

### Google Gemini

Gemini expone endpoint oficial de listado de modelos:

- `GET /v1beta/models`
- Documentacion: https://ai.google.dev/api/models

La pagina de precios esta separada:

- https://ai.google.dev/gemini-api/docs/pricing

Evaluacion:

- Modelos: muy automatizable. La respuesta incluye metadata util como metodos
  soportados, limites de input/output y nombre versionado.
- Precios: deben venir de tabla propia o revision controlada.
- Riesgo: Gemini tiene precios que pueden variar por modalidad, contexto,
  region, free tier o SKU de Google Cloud.

## Conclusion de viabilidad

La capacidad debe separarse en dos dominios:

1. Catalogo de modelos disponibles.
2. Catalogo de precios aplicables al calculo de costo.

El primer dominio puede actualizarse desde APIs oficiales de proveedor con bajo
riesgo. El segundo dominio no tiene una API uniforme ni garantizada entre
proveedores. Por eso, los precios no deberian depender de scraping en caliente
ni de llamadas remotas durante el run.

La estrategia viable es hibrida:

- consultar APIs oficiales para descubrir modelos;
- mantener un JSON versionado como fuente canonica de precios;
- cachear localmente ese JSON;
- permitir override manual en `config.yaml`;
- conservar `DEFAULT_PRICING` como fallback minimo;
- usar tareas programadas o skills para detectar cambios y abrir revision.

## Decision propuesta

Crear un catalogo publico versionado en JSON dentro de `docs/pricing/`, servido
por GitHub Pages o por raw GitHub.

Archivos propuestos:

```text
docs/pricing/schema.json
docs/pricing/models.json
docs/pricing/README.md
```

`models.json` seria la fuente de referencia de precios para el proyecto y para
agentes externos. El runtime lo consumiria con cache local y fallback.

Orden de precedencia para el calculo:

1. `config.yaml.pricing` si el usuario definio un precio explicito.
2. Cache local del catalogo remoto.
3. Catalogo remoto publicado en GitHub.
4. `DEFAULT_PRICING` embebido en `costs.py`.
5. `None` si el modelo no existe en ninguna fuente.

Este orden conserva control local y evita que un cambio remoto altere costos de
forma inesperada cuando el usuario ya definio valores propios.

## Schema recomendado

El schema debe representar mas que input/output. Recomendacion:

```json
{
  "schema_version": "1.0",
  "currency": "USD",
  "unit": "per_1m_tokens",
  "updated_at": "2026-07-01T00:00:00Z",
  "providers": {
    "anthropic": {
      "display_name": "Anthropic",
      "models": {
        "claude-sonnet-4-6": {
          "status": "active",
          "aliases": ["claude-sonnet-latest"],
          "capabilities": ["text", "code"],
          "purpose": {
            "summary": "Modelo balanceado para desarrollo general, arquitectura y codigo complejo.",
            "strengths": ["arquitectura", "seguridad", "codigo complejo", "razonamiento"],
            "weaknesses": ["tareas masivas de bajo valor", "boilerplate repetitivo"],
            "recommended_for": ["decisiones tecnicas", "auditoria", "refactors riesgosos"],
            "avoid_for": ["formateo simple", "generacion mecanica de archivos"],
            "routing_weight": 0.85
          },
          "pricing": {
            "input": 3.0,
            "output": 15.0,
            "cache_write": 3.75,
            "cache_read": 0.3
          },
          "context_window": null,
          "max_output_tokens": null,
          "source_url": "https://platform.claude.com/docs/en/about-claude/pricing",
          "verified_at": "2026-07-01",
          "notes": "Precios por millon de tokens. Verificar variantes de cache."
        }
      }
    }
  }
}
```

Campos minimos:

- `schema_version`: permite migrar el formato.
- `currency`: inicialmente `USD`.
- `unit`: inicialmente `per_1m_tokens`.
- `updated_at`: fecha del catalogo completo.
- `providers.<provider>.models.<model>.pricing`: precios normalizados.
- `source_url`: URL oficial de origen.
- `verified_at`: fecha de verificacion humana o automatica.
- `status`: `active`, `deprecated`, `preview`, `unknown`.
- `aliases`: nombres alternativos o ids historicos.

Campos recomendados:

- `purpose`
- `context_window`
- `max_output_tokens`
- `modalities`
- `supports_cache`
- `supports_batch`
- `billing_notes`
- `confidence`: `official_api`, `official_page`, `manual`, `estimated`

## Proposito especializado por modelo

El catalogo no deberia limitarse a precios. Para que el router elija bien, cada
modelo necesita un perfil de uso auditable: para que es bueno, para que no es
bueno y bajo que condiciones conviene elegirlo.

Hoy esa informacion existe de forma incompleta y rigida en
`router.py:ROUTER_SYSTEM_PROMPT`:

```text
claude: arquitectura, seguridad, decisiones de diseno, codigo complejo.
openai: refactors, integracion de APIs, tareas de proposito general.
deepseek: tareas repetitivas, tests, boilerplate, volumen economico.
gemini: contexto largo, repos completos, multimodal.
```

Ese enfoque funciona como punto de partida, pero tiene problemas:

- esta definido por proveedor, no por modelo;
- no se puede actualizar desde el catalogo;
- no distingue modelo barato vs modelo fuerte dentro del mismo proveedor;
- no registra fuente, confianza ni fecha de revision;
- obliga a cambiar codigo para ajustar criterios de ruteo.

La decision recomendada es mover esas heuristicas a `models.json` como metadata
de proposito. El router deberia consumir un resumen compacto del catalogo en vez
de tener reglas fijas embebidas.

### Forma recomendada de `purpose`

```json
{
  "purpose": {
    "summary": "Texto corto para humanos y router.",
    "strengths": ["codigo", "razonamiento", "contexto_largo"],
    "weaknesses": ["latencia", "costo", "multimodal"],
    "recommended_for": [
      "auditoria de seguridad",
      "arquitectura",
      "debugging complejo"
    ],
    "avoid_for": [
      "boilerplate masivo",
      "formateo trivial"
    ],
    "routing_tags": ["secure_code", "deep_reasoning"],
    "routing_weight": 0.85,
    "confidence": "manual_verified",
    "source_url": "https://...",
    "verified_at": "2026-07-01"
  }
}
```

`routing_weight` no debe ser una verdad absoluta. Es una preferencia base que
el router combina con:

- notas del proyecto en `context.yaml`;
- `keyword_hints`;
- rating historico de runs similares;
- costo estimado;
- disponibilidad del modelo;
- presupuesto diario;
- contexto requerido por la tarea.

### Taxonomia inicial de capacidades

Para evitar texto libre dificil de comparar, conviene usar tags normalizados:

```text
code_generation
code_review
security_review
architecture
debugging
test_generation
boilerplate
api_integration
long_context
multimodal
reasoning
low_latency
low_cost
data_extraction
documentation
```

Cada modelo puede declarar fortalezas y debilidades con esos tags. El texto
libre queda como explicacion, pero la decision programatica usa tags.

### Ejemplos de perfiles

Estos ejemplos deben validarse contra documentacion oficial y experiencia local
antes de convertirse en catalogo canonico:

```json
{
  "claude-sonnet-4-6": {
    "purpose": {
      "summary": "Trabajo de desarrollo general con buena calidad en codigo complejo.",
      "strengths": ["code_review", "architecture", "security_review", "reasoning"],
      "weaknesses": ["low_cost", "boilerplate"],
      "recommended_for": ["auditorias", "refactors riesgosos", "decisiones tecnicas"],
      "avoid_for": ["generacion masiva de archivos simples"],
      "routing_weight": 0.85
    }
  },
  "claude-haiku-4-5-20251001": {
    "purpose": {
      "summary": "Modelo economico/rapido para tareas simples dentro de Claude.",
      "strengths": ["low_latency", "low_cost", "documentation", "boilerplate"],
      "weaknesses": ["architecture", "security_review"],
      "recommended_for": ["resumenes", "ediciones pequenas", "clasificacion"],
      "avoid_for": ["analisis de seguridad profundo"],
      "routing_weight": 0.55
    }
  },
  "deepseek-v4-flash": {
    "purpose": {
      "summary": "Modelo economico para routing, borradores, tests y volumen.",
      "strengths": ["low_cost", "test_generation", "boilerplate"],
      "weaknesses": ["security_review", "architecture"],
      "recommended_for": ["router", "tests repetitivos", "tareas mecanicas"],
      "avoid_for": ["decisiones criticas"],
      "routing_weight": 0.45
    }
  },
  "gemini-2.5-pro": {
    "purpose": {
      "summary": "Modelo fuerte para contexto largo y analisis amplio.",
      "strengths": ["long_context", "reasoning", "multimodal", "data_extraction"],
      "weaknesses": ["low_cost"],
      "recommended_for": ["repos grandes", "documentos largos", "analisis multimodal"],
      "avoid_for": ["tareas cortas de bajo valor"],
      "routing_weight": 0.75
    }
  }
}
```

### Fuentes y limites

Las APIs de modelos suelen entregar metadata tecnica, pero no un "proposito"
completo y comparable. Gemini, por ejemplo, puede entregar metodos soportados y
limites; OpenAI, Anthropic y DeepSeek pueden listar modelos disponibles. Eso no
equivale a saber que modelo conviene para seguridad, tests o arquitectura.

Por eso el proposito debe ser una capa editorial del catalogo:

- parte puede venir de documentacion oficial;
- parte puede venir de benchmark interno del orquestador;
- parte puede venir de experiencia acumulada por ratings;
- toda afirmacion debe tener fecha y nivel de confianza.

Fuentes oficiales de referencia:

- OpenAI models: https://platform.openai.com/docs/models
- Anthropic models overview: https://platform.claude.com/docs/en/about-claude/models/overview
- DeepSeek docs: https://api-docs.deepseek.com/
- Gemini models: https://ai.google.dev/gemini-api/docs/models

## Atributos transversales relevantes

No todos los atributos del catalogo tienen el mismo valor para el orquestador.
Conviene separar campos operativos, campos de ruteo, campos de auditoria y
campos derivados. Esta separacion evita que el JSON crezca como documentacion
sin utilidad programatica.

### Campos obligatorios por modelo

Estos campos deberian existir para cada modelo del catalogo:

| Campo | Tipo | Uso |
|---|---|---|
| `provider` | string | Resolver factory, endpoints, dashboard y agrupacion de costos. |
| `id` | string | Identificador exacto usado en API y en `runs.model`. |
| `status` | string | Evitar modelos deprecated o preview en ruteo normal. |
| `pricing` | object/null | Calcular `cost_usd`; si es null, mostrar "sin precio" y penalizar ruteo. |
| `purpose.summary` | string | Explicacion breve para dashboard y resumen compacto del router. |
| `purpose.strengths` | list[string] | Senales positivas de ruteo. |
| `purpose.weaknesses` | list[string] | Senales negativas de ruteo. |
| `source_url` | string | Auditoria de origen. |
| `verified_at` | string | Control de vigencia. |

## Fechas de actualizacion, consulta y verificacion

El catalogo debe distinguir tres fechas distintas. Usar una sola fecha genera
ambiguedad: no es lo mismo cuando se edito el JSON, cuando una instalacion local
lo descargo, y cuando se verifico contra una fuente oficial.

Fechas requeridas:

| Campo | Nivel | Significado |
|---|---|---|
| `updated_at` | catalogo | Fecha en que se genero o modifico el JSON publicado. |
| `verified_at` | modelo/precio/proposito | Fecha en que se verifico manual o automaticamente la informacion contra la fuente. |
| `last_checked_at` | disponibilidad | Fecha de consulta a la API del proveedor para saber si el modelo existe o esta habilitado. |
| `fetched_at` | cache local | Fecha en que esta instalacion descargo el catalogo remoto. |

Ejemplo:

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-07-01T00:00:00Z",
  "providers": {
    "anthropic": {
      "models": {
        "claude-sonnet-4-6": {
          "verified_at": "2026-07-01",
          "availability": {
            "last_checked_at": "2026-07-01T12:30:00Z"
          }
        }
      }
    }
  },
  "cache": {
    "fetched_at": "2026-07-01T13:00:00Z"
  }
}
```

Reglas:

- `updated_at` cambia cuando cambia el archivo publicado.
- `verified_at` cambia solo cuando se revisa una fuente o se confirma el dato.
- `last_checked_at` cambia cada vez que se consulta una API de modelos.
- `fetched_at` no pertenece al JSON publico canonico; pertenece al cache local.
- Si `verified_at` supera un umbral configurable, el dashboard debe marcar el
  precio o proposito como potencialmente desactualizado.

### Campos recomendados por modelo

Estos campos mejoran la decision, pero pueden ser null al inicio:

| Campo | Tipo | Uso |
|---|---|---|
| `display_name` | string | UI legible. |
| `aliases` | list[string] | Resolver nombres devueltos por APIs o modelos versionados. |
| `modalities` | list[string] | Filtrar texto, imagen, audio, video o multimodal. |
| `context_window` | integer/null | Elegir modelos de contexto largo cuando la tarea lo requiere. |
| `max_output_tokens` | integer/null | Evitar modelos que no pueden producir salidas largas. |
| `supports_streaming` | boolean/null | UI y latencia percibida. |
| `supports_tools` | boolean/null | Futuro uso con function calling/tool use. |
| `supports_structured_output` | boolean/null | Tareas donde se exige JSON confiable. |
| `supports_vision` | boolean/null | Tareas con imagen o screenshots. |
| `supports_cache` | boolean/null | Calculo fino de costo y estrategia para prompts largos. |
| `supports_batch` | boolean/null | Tareas masivas o diferibles. |
| `latency_tier` | string/null | Preferencia para tareas interactivas. |
| `quality_tier` | string/null | Preferencia para tareas criticas. |
| `cost_tier` | string/null | Preferencia cuando manda presupuesto. |
| `availability` | string/null | `configured`, `available`, `unavailable`, `unknown`. |
| `billing_notes` | string/null | Requisitos de billing/free tier/cuotas. |

### Campos de pricing

El pricing debe mantenerse normalizado a USD por millon de tokens, aunque el
proveedor publique precios en otra forma. Campos utiles:

```json
{
  "pricing": {
    "input": 3.0,
    "output": 15.0,
    "cache_write": 3.75,
    "cache_read": 0.3,
    "batch_input": null,
    "batch_output": null,
    "reasoning": null,
    "image_input": null,
    "audio_input": null
  }
}
```

Campos minimos para el calculo actual:

- `input`
- `output`
- `cache_write`
- `cache_read`

Campos futuros:

- `batch_input`
- `batch_output`
- `reasoning`
- `image_input`
- `image_output`
- `audio_input`
- `audio_output`

Si un campo no aplica, debe ir como `null` o omitirse; si aplica pero se
desconoce, conviene marcar el modelo como `pricing: null` para evitar costos
falsos.

### Historial de precios

Conviene mantener historial de precios, pero no mezclado de forma ambigua con el
precio vigente. El calculo normal necesita resolver un precio actual de forma
simple; la auditoria necesita reconstruir que precio estaba vigente en una fecha
determinada.

Decision recomendada:

- `pricing` contiene el precio vigente normalizado.
- `pricing_history` contiene versiones anteriores y vigencias.
- Cada entrada historica referencia una entrada padre o grupo de precio estable.
- Los runs nuevos usan `pricing`.
- Los reportes historicos pueden usar `pricing_history` para recalculo o
  auditoria, pero no deben modificar `runs.cost_usd` ya persistido salvo una
  accion explicita.

Ejemplo:

```json
{
  "id": "claude-sonnet-4-6",
  "pricing": {
    "price_ref": "anthropic.claude-sonnet-4-6.current",
    "effective_from": "2026-06-01",
    "effective_to": null,
    "input": 3.0,
    "output": 15.0,
    "cache_write": 3.75,
    "cache_read": 0.3,
    "source_url": "https://platform.claude.com/docs/en/about-claude/pricing",
    "verified_at": "2026-07-01"
  },
  "pricing_history": [
    {
      "price_ref": "anthropic.claude-sonnet-4-6.2026-06-01",
      "parent_ref": "anthropic.claude-sonnet-4-6",
      "effective_from": "2026-06-01",
      "effective_to": null,
      "input": 3.0,
      "output": 15.0,
      "cache_write": 3.75,
      "cache_read": 0.3,
      "source_url": "https://platform.claude.com/docs/en/about-claude/pricing",
      "verified_at": "2026-07-01",
      "change_reason": "verificacion inicial"
    },
    {
      "price_ref": "anthropic.claude-sonnet-4-6.2025-12-01",
      "parent_ref": "anthropic.claude-sonnet-4-6",
      "effective_from": "2025-12-01",
      "effective_to": "2026-05-31",
      "input": 3.0,
      "output": 15.0,
      "cache_write": 3.75,
      "cache_read": 0.3,
      "source_url": "https://platform.claude.com/docs/en/about-claude/pricing",
      "verified_at": "2025-12-01",
      "change_reason": "precio anterior"
    }
  ]
}
```

Campos relevantes:

| Campo | Uso |
|---|---|
| `price_ref` | Identificador unico de la version de precio. |
| `parent_ref` | Agrupa todas las versiones de precio del mismo modelo/SKU. |
| `effective_from` | Fecha desde la que aplica el precio. |
| `effective_to` | Fecha hasta la que aplica; null significa vigente. |
| `verified_at` | Fecha de verificacion del dato. |
| `source_url` | Fuente oficial del precio. |
| `change_reason` | Explicacion breve del cambio. |

Este modelo permite:

- auditar cambios de precio por proveedor/modelo;
- recalcular costos historicos si se desea;
- explicar diferencias entre costo registrado y costo recalculado;
- detectar runs ejecutados con precios desactualizados;
- mantener una referencia publica util para otros agentes.

No se recomienda recalcular automaticamente `runs.cost_usd` cuando cambia el
catalogo. Ese valor representa el costo estimado al momento del run. Si se
necesita recalculo, debe exponerse como valor separado, por ejemplo
`recalculated_cost_usd`, en reportes o endpoints analiticos.

Para una primera version, `pricing_history` puede ser opcional. Lo importante es
que el schema ya reserve `price_ref`, `effective_from` y `effective_to` para no
tener que romper compatibilidad despues.

## Relaciones y accesibilidad

El catalogo debe ser facil de mantener como JSON humano, pero tambien facil de
consultar por el runtime. Para lograr ambas cosas, conviene distinguir entre la
estructura canonica publicada y las vistas/indexes derivados que construye el
orquestador al cargarla.

### Entidades principales

Relaciones conceptuales:

```text
Provider
  -> Model
       -> Pricing vigente
       -> Pricing history
       -> Purpose
       -> Availability
       -> Aliases

Run local
  -> provider + model
  -> precio resuelto en el momento del run
  -> metricas reales: costo, tokens, duracion, rating
```

El catalogo publico describe `Provider`, `Model`, `Pricing`, `Purpose` y parte
de `Availability`. La base local describe `Run` y metricas observadas.

### Claves estables

La clave primaria logica de un modelo debe ser:

```text
provider + "/" + model_id
```

Ejemplos:

```text
anthropic/claude-sonnet-4-6
openai/gpt-4o
deepseek/deepseek-v4-flash
google/gemini-2.5-flash
```

En el codigo actual, `runs.provider` usa nombres cortos (`claude`, `openai`,
`deepseek`, `gemini`). El catalogo puede usar nombres canonicos de empresa, pero
debe incluir una tabla de aliases de provider:

```json
{
  "provider_aliases": {
    "claude": "anthropic",
    "anthropic": "anthropic",
    "openai": "openai",
    "deepseek": "deepseek",
    "gemini": "google",
    "google": "google"
  }
}
```

Sin esta normalizacion, el catalogo publico y `runs.provider` pueden quedar
desalineados.

### Resolucion de modelo

El runtime necesita resolver un modelo aunque venga con aliases, versiones o
nombres devueltos por API. Flujo recomendado:

1. Normalizar provider usando `provider_aliases`.
2. Buscar `model_id` exacto dentro del provider.
3. Si no existe, buscar en `aliases`.
4. Si no existe, aplicar fallback por sufijo solo como compatibilidad legacy.
5. Si no existe, retornar `unknown_model` y no calcular costo.

Indice derivado:

```json
{
  "model_index": {
    "anthropic/claude-sonnet-4-6": {
      "provider": "anthropic",
      "id": "claude-sonnet-4-6"
    },
    "anthropic/claude-sonnet-latest": {
      "provider": "anthropic",
      "id": "claude-sonnet-4-6",
      "alias": true
    }
  }
}
```

Este indice no necesita publicarse como verdad canonica; puede generarse al
cargar el catalogo. Publicarlo es opcional si se quiere facilitar consumo por
otros agentes.

### Resolucion de precio vigente

El acceso mas frecuente debe ser O(1): dado `provider`, `model` y fecha opcional,
resolver precio.

Firma conceptual:

```python
resolve_price(provider: str, model: str, at: date | None = None) -> Price | None
```

Reglas:

- Si `at` es null, usar `pricing`.
- Si `at` tiene fecha, buscar en `pricing_history` una entrada donde
  `effective_from <= at <= effective_to`.
- Si no hay history, usar `pricing` solo si `effective_from` permite inferir
  vigencia.
- Si hay multiples entradas vigentes, el catalogo es invalido.
- Si no hay entrada vigente, retornar `None`.

Esto permite mantener calculo simple para runs nuevos y analisis temporal para
reportes historicos.

### Relacion con runs locales

El schema actual de `runs` guarda `provider`, `model`, tokens, costo y fecha.
Eso basta para vincular un run con el catalogo mediante:

```text
normalize_provider(runs.provider) + "/" + normalize_model(runs.model)
```

Para mayor auditabilidad futura, se puede agregar una columna opcional:

```text
runs.price_ref TEXT
```

Ventaja:

- saber exactamente que version de precio se uso al calcular `runs.cost_usd`;
- evitar ambiguedad si despues cambia `pricing_history`;
- explicar diferencias entre costo registrado y recalculado.

No es obligatorio para la primera version. Si no existe `runs.price_ref`, se
puede inferir por `runs.ts`, `provider` y `model`.

### Vistas de acceso necesarias

El catalogo debe producir vistas especializadas segun consumidor:

| Vista | Consumidor | Contenido |
|---|---|---|
| `effective_pricing` | `calculate_cost` | Forma legacy `{model: {input, output...}}`. |
| `model_profiles` | router | Resumen compacto de modelos, purpose, costo y disponibilidad. |
| `pricing_audit` | dashboard/CLI | Fuente, fechas, price_ref, vigencia, cambios. |
| `availability_status` | dashboard/CLI | Modelos configurados, disponibles, bloqueados o desconocidos. |
| `unknown_models` | CLI/dashboard | Modelos usados en runs sin entrada de catalogo. |
| `local_model_metrics` | analitica/router | Ratings, latencia y costo real desde `runs`. |

Esta separacion es importante: el router no necesita todo el historial de precio,
y `calculate_cost` no necesita leer proposito ni disponibilidad.

### Accesibilidad publica y local

Informacion apta para JSON publico:

- providers;
- modelos;
- aliases;
- pricing vigente;
- pricing history;
- proposito;
- capacidades;
- fuentes;
- fechas de verificacion;
- notas de billing generales.

Informacion que debe quedar solo local:

- API keys;
- disponibilidad especifica de la cuenta;
- modelos habilitados para la cuenta si revelan datos privados;
- costos acumulados por proyecto;
- ratings de runs;
- prompts, respuestas y `task_preview`;
- cache local con `fetched_at`.

La disponibilidad tiene dos capas:

- `public_availability`: puede publicarse, indica si el modelo existe
  publicamente o esta deprecated.
- `account_availability`: debe ser local, indica si la cuenta configurada puede
  usarlo.

### Estructura recomendada para uso efectivo

La estructura canonica deberia optimizar legibilidad y estabilidad:

```json
{
  "schema_version": "1.0",
  "updated_at": "2026-07-01T00:00:00Z",
  "currency": "USD",
  "unit": "per_1m_tokens",
  "provider_aliases": {
    "claude": "anthropic",
    "gemini": "google"
  },
  "providers": {
    "anthropic": {
      "display_name": "Anthropic",
      "models": {
        "claude-sonnet-4-6": {
          "id": "claude-sonnet-4-6",
          "provider": "anthropic",
          "aliases": ["claude-sonnet-latest"],
          "status": "active",
          "pricing": {},
          "pricing_history": [],
          "purpose": {},
          "capabilities": {},
          "public_availability": {},
          "source_url": "https://...",
          "verified_at": "2026-07-01"
        }
      }
    }
  }
}
```

Al cargarlo, `orchestrator/catalog.py` deberia generar estructuras internas:

```python
Catalog(
    models_by_key,
    aliases_by_key,
    effective_pricing,
    profiles_for_router,
    audit_records,
)
```

Esto evita recorrer todo el JSON en cada run y mantiene la compatibilidad con la
funcion `calculate_cost`.

### Campos de proposito/ruteo

Para trabajar correctamente en el router, los campos mas importantes son:

```json
{
  "purpose": {
    "summary": "Modelo fuerte para auditoria y codigo complejo.",
    "strengths": ["code_review", "security_review", "architecture"],
    "weaknesses": ["low_cost", "low_latency"],
    "recommended_for": ["auditoria", "refactor critico"],
    "avoid_for": ["boilerplate masivo"],
    "routing_tags": ["secure_code", "deep_reasoning"],
    "routing_weight": 0.85,
    "confidence": "manual_verified"
  }
}
```

Campos con impacto directo:

- `strengths`: tags que aumentan preferencia.
- `weaknesses`: tags que reducen preferencia.
- `recommended_for`: texto para justificar decision.
- `avoid_for`: restricciones blandas.
- `routing_weight`: preferencia base.
- `confidence`: cuanto confiar en ese perfil.

No conviene usar solo `summary`, porque texto libre no permite comparar modelos
de forma consistente. El router puede leer el resumen, pero el sistema deberia
generar ese resumen desde tags normalizados.

### Campos de disponibilidad

Disponibilidad no es lo mismo que existencia publica del modelo. Un modelo puede
existir en la documentacion y no estar habilitado para la cuenta local.

Campos sugeridos:

```json
{
  "availability": {
    "public": true,
    "account_available": true,
    "configured": false,
    "requires_billing": false,
    "free_tier": "limited",
    "last_checked_at": "2026-07-01T00:00:00Z",
    "source": "provider_api"
  }
}
```

Uso en el orquestador:

- No sugerir modelos `account_available=false` salvo override.
- Avisar si `config.yaml` apunta a un modelo no disponible.
- Preferir modelos `configured=true` cuando no hay razon fuerte para cambiar.
- Mostrar advertencias de billing/cuota en dashboard.

### Campos derivados por el orquestador

Estos no deberian vivir como verdad canonica en `models.json`, porque dependen
del historial local:

| Campo | Fuente | Uso |
|---|---|---|
| `observed_success_rate` | `runs.rating` | Aprendizaje por experiencia local. |
| `observed_partial_rate` | `runs.rating` | Detectar modelos medianamente utiles. |
| `observed_wrong_rate` | `runs.rating` | Penalizar modelos en tareas similares. |
| `avg_latency_ms` | `runs.duration_ms` | Preferir modelos rapidos en tareas interactivas. |
| `avg_cost_usd` | `runs.cost_usd` | Comparar costo real por tipo de tarea. |
| `avg_input_tokens` | `runs.input_tokens` | Estimar costo esperado. |
| `avg_output_tokens` | `runs.output_tokens` | Estimar costo esperado. |
| `cache_hit_ratio` | cache tokens | Medir beneficio real de cache. |
| `last_used_at` | `runs.ts` | Detectar modelos obsoletos o sin uso. |

Estos campos deberian exponerse en un endpoint local de analitica, no publicarse
en el catalogo global. El catalogo dice "lo que el modelo promete"; el historial
local dice "como rindio en mis proyectos".

### Campos que ya existen en el sistema

El esquema actual de `runs` ya guarda senales utiles para enriquecer el catalogo
local o el dashboard:

- `provider`
- `model`
- `duration_ms`
- `input_tokens`
- `output_tokens`
- `cache_creation_tokens`
- `cache_read_tokens`
- `cost_usd`
- `router_cost_usd`
- `routing_reason`
- `rating`
- `step_id`
- `project`
- `task_preview`

Esto permite construir metricas por modelo sin cambiar el schema de runs. Lo que
falta es una tabla/catalogo que describa al modelo antes de usarlo.

### Campos que no conviene priorizar

Algunos datos son atractivos pero no deberian bloquear la primera version:

- benchmarks genericos externos;
- ranking global de calidad;
- latencia prometida por proveedor;
- precios regionales complejos;
- limites por plan comercial;
- metadata raw completa de APIs.

La razon: pueden cambiar, no son comparables entre proveedores o no afectan
directamente la decision actual del orquestador.

## Integracion con el router

El router no deberia recibir el catalogo completo si crece demasiado. Debe
recibir una vista compacta generada localmente, por ejemplo:

```text
Modelos disponibles y perfil resumido:
- claude/claude-sonnet-4-6: fuerte en architecture, security_review, reasoning; evitar low_cost.
- deepseek/deepseek-v4-flash: fuerte en low_cost, test_generation, boilerplate; evitar security_review.
- gemini/gemini-2.5-pro: fuerte en long_context, multimodal, reasoning; evitar tareas cortas de bajo valor.
```

Reglas de integracion:

- Si un modelo no tiene `purpose`, usar heuristica por proveedor como fallback.
- Si un modelo esta `deprecated`, no sugerirlo salvo override explicito.
- Si un modelo no tiene precio, penalizarlo para tareas normales.
- Si el proyecto define `preferred_models.notes`, esas notas tienen prioridad.
- Si runs similares tienen rating negativo para un modelo, bajar su score.
- Si runs similares tienen rating positivo, subir su score.

Esto convierte el proposito en una senal mas, no en una regla rigida.

## Integracion runtime

Agregar un modulo nuevo:

```text
orchestrator/catalog.py
```

Responsabilidades:

- cargar catalogo local/remoto;
- validar version de schema;
- normalizar provider/model;
- resolver aliases;
- devolver la tabla efectiva para `calculate_cost`;
- exponer metadata de fuente y fecha;
- escribir cache en `~/.ai-orchestrator/pricing-cache.json`.

Funciones sugeridas:

```python
def load_price_catalog(config: dict, refresh: bool = False) -> dict: ...
def get_effective_pricing(config: dict) -> dict: ...
def get_model_price(config: dict, provider: str, model: str) -> dict | None: ...
def list_catalog_models(config: dict, provider: str | None = None) -> list[dict]: ...
```

`orchestrator/config.py:get_pricing_table` podria migrar gradualmente a:

```python
def get_pricing_table(config: dict) -> dict:
    from orchestrator.catalog import get_effective_pricing
    return get_effective_pricing(config)
```

Para compatibilidad, `get_effective_pricing` debe retornar la forma actual:

```python
{
  "claude-sonnet-4-6": {
    "input": 3.0,
    "output": 15.0,
    "cache_write": 3.75,
    "cache_read": 0.3
  }
}
```

## Integracion con APIs de modelos

No conviene mezclar ejecucion (`complete`) con discovery. El contrato actual de
`BaseProvider` es limpio y estable. Discovery deberia vivir en adaptadores
separados:

```text
orchestrator/model_discovery.py
orchestrator/discovery/openai.py
orchestrator/discovery/anthropic.py
orchestrator/discovery/deepseek.py
orchestrator/discovery/gemini.py
```

Funciones sugeridas:

```python
def list_provider_models(config: dict, provider: str) -> list[dict]: ...
def refresh_available_models(config: dict) -> dict: ...
```

La respuesta normalizada podria incluir:

```json
{
  "provider": "gemini",
  "id": "gemini-2.5-flash",
  "display_name": "Gemini 2.5 Flash",
  "source": "provider_api",
  "fetched_at": "2026-07-01T00:00:00Z",
  "capabilities": ["generateContent"],
  "context_window": 1048576,
  "max_output_tokens": 65536,
  "raw": {}
}
```

La metadata `raw` debe ser opcional y no exponerse completa por defecto para no
acoplar el sistema a formatos externos.

## Endpoints internos propuestos

Agregar endpoints al servidor HTTP:

```text
GET  /pricing
GET  /pricing/models
POST /pricing/refresh
GET  /models
POST /models/refresh
```

Semantica:

- `/pricing`: tabla efectiva usada por el runtime, con fuente por modelo.
- `/pricing/models`: catalogo completo normalizado.
- `/pricing/refresh`: descarga JSON remoto y actualiza cache local.
- `/models`: modelos disponibles conocidos, desde cache.
- `/models/refresh`: consulta APIs de proveedores configurados.

Estos endpoints deben ser locales. No deben requerir exponer API keys ni deben
publicar credenciales en ningun payload.

## CLI propuesta

Agregar comandos:

```powershell
ai-orchestrator pricing show
ai-orchestrator pricing refresh
ai-orchestrator pricing validate
ai-orchestrator models list
ai-orchestrator models refresh
```

Uso esperado:

- `pricing show`: ver tabla efectiva y fuente.
- `pricing refresh`: actualizar cache desde GitHub.
- `pricing validate`: detectar modelos usados en runs sin precio.
- `models refresh`: consultar proveedores configurados.
- `models list`: comparar modelos disponibles contra modelos con precio.

## Tarea programada o skill

Hay dos usos distintos:

### Runtime local

Una tarea programada local puede ejecutar:

```powershell
ai-orchestrator pricing refresh
ai-orchestrator models refresh
```

Frecuencia sugerida:

- modelos: diaria o semanal;
- precios: semanal, con cache y sin bloquear runs.

### Mantenimiento del catalogo publico

Una skill o GitHub Action puede:

1. Leer `docs/pricing/models.json`.
2. Consultar APIs de modelos.
3. Comparar modelos nuevos/deprecados.
4. Revisar paginas oficiales de pricing.
5. Proponer un patch o PR.
6. Actualizar `verified_at`, `updated_at` y notas.

La skill es adecuada para asistencia y auditoria, pero no deberia ser la unica
fuente de verdad del runtime. El runtime debe depender de JSON versionado y
cacheado, no de una conversacion con un agente.

## GitHub Pages vs raw GitHub

Opciones:

### GitHub Pages

URL esperada:

```text
https://<usuario>.github.io/ai-orchestrator/pricing/models.json
```

Ventajas:

- URL limpia y estable.
- Puede convivir con `docs/index.html`.
- Facil de consumir desde navegador, dashboard y agentes.

Riesgos:

- Requiere GitHub Pages habilitado.
- Puede tener cache CDN.

### raw.githubusercontent.com

URL esperada:

```text
https://raw.githubusercontent.com/<usuario>/ai-orchestrator/main/docs/pricing/models.json
```

Ventajas:

- No requiere GitHub Pages.
- Refleja el branch directamente.

Riesgos:

- No es ideal como API publica estable.
- Puede tener limites o comportamientos de cache menos predecibles.

Decision recomendada:

- usar GitHub Pages como fuente primaria configurable;
- aceptar raw GitHub como fallback o default de desarrollo;
- permitir override en `config.yaml`:

```yaml
catalog:
  pricing_url: "https://<usuario>.github.io/ai-orchestrator/pricing/models.json"
  refresh_ttl_hours: 168
  allow_remote: true
```

## Persistencia y cache

Cache propuesta:

```text
~/.ai-orchestrator/pricing-cache.json
~/.ai-orchestrator/models-cache.json
```

Metadata de cache:

```json
{
  "fetched_at": "2026-07-01T00:00:00Z",
  "source_url": "https://...",
  "etag": "...",
  "schema_version": "1.0",
  "payload": {}
}
```

Reglas:

- Si refresh falla, usar cache anterior.
- Si cache no existe, usar `DEFAULT_PRICING`.
- Si schema remoto es incompatible, rechazar remoto y registrar warning.
- Nunca bloquear un run por no poder actualizar precios.

## Impacto en dashboard

El dashboard ya muestra `?` o "sin precio" cuando no hay pricing. Con catalogo
se puede mejorar:

- mostrar fuente de precio por modelo;
- mostrar fecha de verificacion;
- listar modelos usados sin precio;
- alertar si un modelo configurado esta deprecated;
- mostrar diferencia entre `config.yaml` y catalogo remoto;
- sugerir modelos disponibles por proveedor al crear runs o pasos.

Panel sugerido:

```text
Pricing Catalog
- Estado: actualizado / cache / fallback / error
- Ultima actualizacion
- Modelos sin precio detectados en runs
- Modelos configurados no disponibles segun provider
- Boton: refrescar catalogo
```

## Riesgos

### Riesgo 1: precios incorrectos

El mayor riesgo es registrar costos errados. Mitigacion:

- cada precio debe tener `source_url` y `verified_at`;
- no autoactualizar precios desde scraping sin revision;
- mantener override local en `config.yaml`;
- mostrar fuente en dashboard.

### Riesgo 2: cambios de schema

Mitigacion:

- `schema_version`;
- validacion estricta;
- fallback a cache/default.

### Riesgo 3: modelos disponibles sin precio

Esto ocurrira con frecuencia. Mitigacion:

- separar availability de pricing;
- marcar `pricing: null`;
- no enrutar automaticamente a modelos sin precio salvo override explicito.

### Riesgo 4: endpoints de proveedor con permisos variables

Algunos endpoints pueden requerir API keys o devolver solo modelos habilitados
para la cuenta. Mitigacion:

- `models refresh` debe ser best-effort por proveedor;
- errores por proveedor no deben romper todo el refresh;
- guardar `error` y `fetched_at` por proveedor.

### Riesgo 5: dependencia de GitHub

Mitigacion:

- cache local;
- fallback local;
- timeout bajo;
- refresh asincronico o manual.

### Riesgo 6: seguridad

Mitigacion:

- no publicar `config.yaml`;
- no enviar API keys al catalogo publico;
- no guardar respuestas raw con headers;
- no exponer paths locales en JSON publico.

## Criterios de aceptacion

Una primera implementacion queda aceptable si:

- existe `docs/pricing/models.json` con schema versionado;
- `get_pricing_table(config)` puede resolver precios desde config, cache,
  remoto o fallback;
- `calculate_cost` sigue funcionando sin cambios en callers;
- hay tests para precedencia de fuentes;
- hay endpoint local `/pricing`;
- hay comando `ai-orchestrator pricing validate`;
- un modelo desconocido no rompe runs y queda visible como sin precio;
- el refresh remoto falla de forma no fatal.

Una segunda etapa queda aceptable si:

- `models refresh` consulta OpenAI, Anthropic, DeepSeek y Gemini;
- el dashboard muestra modelos sin precio;
- una GitHub Action valida `models.json`;
- existe proceso documentado para actualizar precios.

## Plan de implementacion por etapas

### Etapa 1: catalogo estatico

- Crear `docs/pricing/schema.json`.
- Crear `docs/pricing/models.json` con los modelos actuales.
- Crear `orchestrator/catalog.py`.
- Cambiar `get_pricing_table` para usar catalogo efectivo.
- Agregar tests unitarios de carga, fallback y override.

### Etapa 2: API local y CLI

- Agregar `GET /pricing`.
- Agregar `POST /pricing/refresh`.
- Agregar comandos `pricing show`, `pricing refresh`, `pricing validate`.
- Mostrar fuente y fecha en dashboard o inspector.

### Etapa 3: discovery de modelos

- Agregar adaptadores de discovery por proveedor.
- Agregar `models refresh` y `models list`.
- Guardar cache de modelos.
- Comparar modelos disponibles contra precios conocidos.

### Etapa 4: automatizacion GitHub

- Agregar GitHub Action semanal.
- Validar schema.
- Detectar cambios de modelos.
- Generar issue o PR cuando haya modelos nuevos o precios por verificar.

### Etapa 5: uso en ruteo

- Evitar que el router sugiera modelos sin precio salvo override.
- Penalizar modelos deprecated.
- Incluir metadata de costo en prompt del router, si no aumenta demasiado el
  costo de decision.

## Recomendacion final

Implementar primero el catalogo JSON publico y el resolver local de precios.
Esto entrega valor inmediato, baja el riesgo y no depende de proveedores.

Despues agregar discovery de modelos, porque es una capacidad complementaria:
sirve para detectar drift entre lo disponible y lo costeado, pero no reemplaza
la tabla de precios.

No se recomienda que el runtime obtenga precios scrapeando paginas oficiales en
cada ejecucion. La fuente operativa debe ser JSON versionado, cacheado y
auditable.
