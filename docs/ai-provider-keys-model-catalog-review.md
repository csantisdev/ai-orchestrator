# Administracion de llaves IA, catalogo de modelos y ruteo

Este documento resume el analisis de la integracion requerida para administrar
llaves de proveedores IA desde la pestaña `Configuracion`, alinear los modelos
con el catalogo versionado del repositorio y aplicar el modelo correcto segun
contexto, responsabilidad y habilidad.

## Objetivo

Permitir configurar proveedores de IA desde el despliegue web sin exponer
secretos, usando el catalogo de modelos del repositorio como fuente de verdad
para modelos disponibles, precios, estado y proposito.

La configuracion web debe permitir:

- registrar o reemplazar API keys de proveedores IA;
- seleccionar modelos por defecto solo desde modelos conocidos por el catalogo;
- evitar que se muestren, devuelvan o registren API keys en logs/respuestas;
- diferenciar modelo por defecto de modelo elegido por ruteo;
- permitir que el router elija proveedor/modelo segun contexto, tarea,
  responsabilidad y habilidades del modelo.

## Estado actual

Las API keys se leen desde `~/.ai-orchestrator/config.yaml` bajo:

```yaml
providers:
  claude:
    api_key: "..."
    model: "claude-sonnet-4-6"
```

El runtime instancia proveedores en `orchestrator/providers/factory.py` usando
`providers.<provider>.api_key` y `providers.<provider>.model`.

El dashboard actualmente muestra el estado de proveedores desde
`GET /integrations/status`, indicando si cada proveedor esta configurado y que
modelo tiene. No permite editar las llaves desde la UI.

La pestaña `Configuracion` muestra que las API keys se configuran en
`~/.ai-orchestrator/config.yaml`, pero aun no ofrece formulario para guardarlas.

## Catalogo de modelos

El catalogo canonico vive en:

```text
docs/pricing/models.json
```

Su schema esta en:

```text
docs/pricing/schema.json
```

El catalogo contiene:

- proveedores canonicos (`anthropic`, `openai`, `deepseek`, `google`);
- aliases hacia nombres internos (`claude`, `gemini`, etc.);
- modelos por proveedor;
- `status`: `active`, `deprecated`, `preview`, `unknown`;
- `pricing`: precio por millon de tokens;
- `purpose`: resumen, fortalezas, debilidades, casos recomendados y casos a evitar;
- `source_url` y `verified_at`.

La resolucion de precios esta implementada en `orchestrator/catalog.py` con
este orden de precedencia:

1. `config.yaml` en la clave `pricing`;
2. cache local `~/.ai-orchestrator/pricing-cache.json`;
3. catalogo remoto si `refresh=True` y `catalog.allow_remote`;
4. catalogo estatico `docs/pricing/models.json`;
5. fallback `DEFAULT_PRICING`.

El catalogo ya esta aplicado de forma fuerte al calculo de costos mediante
`get_pricing_table(config)`.

## Actualizacion de modelos

Hay dos mecanismos distintos:

### Catalogo versionado

La actualizacion de modelos/precios/propositos se hace editando manualmente
`docs/pricing/models.json`, actualizando:

- `updated_at` global;
- `verified_at` por modelo;
- `pricing`;
- `status`;
- `purpose`, si corresponde.

El script `scripts/validate_pricing_catalog.py` valida:

- schema JSON;
- modelos con `verified_at` mayor a 180 dias;
- diferencias entre `models.json` y `DEFAULT_PRICING`.

No hace llamadas de red ni actualiza modelos automaticamente.

### Discovery de proveedores

`orchestrator/model_discovery.py` consulta las APIs reales de proveedores y
cachea disponibilidad en:

```text
~/.ai-orchestrator/models-cache.json
```

Esto se usa desde:

- `ai-orchestrator models refresh`;
- `ai-orchestrator models list`;
- `POST /models/refresh`;
- `GET /models`.

El discovery no modifica el catalogo. Solo compara modelos disponibles contra
modelos con precio.

## Propositos y habilidades

El campo `purpose` se usa como metadata semantica para orientar el router.

Ejemplos actuales:

- `claude-sonnet-4-6`: arquitectura, seguridad, code review, razonamiento;
- `claude-haiku-4-5-20251001`: tareas simples, documentacion, boilerplate;
- `gpt-4o`: refactors, integracion de APIs, generacion general de codigo;
- `gpt-4o-mini`: tareas simples y baratas;
- `deepseek-v4-flash`: tests repetitivos, boilerplate, bajo costo;
- `gemini-2.5-pro`: contexto largo, multimodal, analisis de repos;
- `gemini-2.5-flash`: tareas simples dentro de Gemini.

`orchestrator.catalog.get_model_profiles(config)` genera una vista compacta de
los modelos con `purpose`. Esa vista se inyecta en el prompt del router desde
`orchestrator/router.py`.

Limitacion importante: los modelos sin `purpose` no aparecen en esa vista y el
router cae en heuristicas generales.

Modelos activos actuales sin `purpose`:

- `claude-opus-4-8`;
- `gpt-5`;
- `gpt-5.4-mini`;
- `deepseek-v4-pro`;
- `gemini-2.5-flash-lite`.

## Aplicacion actual en el router

El router usa:

- contexto del proyecto (`context.yaml`);
- `preferred_models.default`;
- `preferred_models.notes`;
- `keyword_hints`;
- contexto activo y paso en progreso;
- agente preset, si existe;
- runs similares y ratings historicos;
- perfiles del catalogo con `purpose`.

El catalogo se aplica como texto dentro del prompt del router. Esto influye en
la decision, pero aun no es una restriccion dura.

Brechas actuales:

- el router valida que el provider este en `PROVIDERS`;
- no valida que el provider tenga API key configurada;
- no valida que el modelo devuelto exista en el catalogo;
- no valida que el modelo pertenezca al provider elegido;
- no valida que el modelo este `active`;
- no valida que el modelo tenga precio;
- no valida disponibilidad real desde `models-cache.json`.

## Requerimiento de configuracion web

La pestaña `Configuracion` deberia administrar proveedores de IA como una vista
write-only para secretos.

Debe permitir:

- elegir proveedor (`claude`, `openai`, `deepseek`, `gemini`);
- ingresar API key nueva;
- seleccionar modelo por defecto desde el catalogo;
- ver estado `Configurado` o `Sin API key`;
- ver modelos activos, deprecated y sin precio;
- refrescar modelos disponibles por API si hay key configurada;
- limpiar el input de API key despues de guardar.

No debe:

- mostrar API keys guardadas;
- devolver API keys en JSON;
- registrar API keys en logs;
- enviar API keys por query string;
- incluir API keys en mensajes de error;
- guardar API keys en `runs.db`.

## Endpoints recomendados

### `GET /config/providers`

Devuelve metadata segura para UI.

Ejemplo:

```json
{
  "providers": [
    {
      "name": "claude",
      "configured": true,
      "default_model": "claude-sonnet-4-6",
      "models": [
        {
          "id": "claude-sonnet-4-6",
          "status": "active",
          "has_price": true,
          "available": true,
          "purpose": {
            "strengths": ["architecture", "security_review"]
          }
        }
      ]
    }
  ]
}
```

Nunca debe devolver `api_key`.

### `POST /config/provider`

Guarda o actualiza proveedor.

Ejemplo:

```json
{
  "provider": "openai",
  "api_key": "sk-...",
  "model": "gpt-4o"
}
```

Respuesta esperada:

```json
{
  "saved": true,
  "provider": "openai",
  "configured": true,
  "model": "gpt-4o"
}
```

La respuesta no debe incluir la key ni fragmentos de la key.

## Validaciones recomendadas

Al guardar configuracion:

- provider debe existir en `orchestrator.paths.PROVIDERS`;
- model debe existir en el catalogo;
- model debe pertenecer al provider seleccionado;
- model no debe estar `deprecated`, salvo configuracion explicita;
- si el modelo no tiene precio, debe advertirse o bloquearse segun politica;
- si existe `models-cache.json`, se puede marcar si el modelo no aparece como
  disponible para esa cuenta.

Al rutear:

- excluir providers sin API key;
- excluir modelos deprecated por defecto;
- excluir modelos fuera de catalogo;
- validar que el modelo devuelto por el router pertenece al provider elegido;
- si el router devuelve un modelo invalido, caer al default del provider o al
  fallback configurado;
- registrar la razon de fallback sin incluir secretos.

## Helper sugerido

Crear `orchestrator/provider_config.py` para concentrar la logica:

- `list_configurable_providers(config)`;
- `save_provider_config(provider, api_key=None, model=None)`;
- `validate_provider_model(provider, model, config)`;
- `redact_provider_config(config)`;
- `merge_catalog_with_discovery(config)`.

Esto evita duplicar reglas en server, CLI y dashboard.

## Cambios en catalogo recomendados

Convertir `purpose` en una pieza gobernada, no opcional de facto.

Opciones:

1. Hacer `purpose` obligatorio para todo modelo `active`.
2. Mantenerlo opcional en schema, pero agregar auditoria que falle si un modelo
   activo no tiene `purpose`.
3. Normalizar tags de habilidades.

Tags sugeridos:

- `architecture`;
- `security_review`;
- `code_review`;
- `reasoning`;
- `api_integration`;
- `code_generation`;
- `test_generation`;
- `boilerplate`;
- `documentation`;
- `long_context`;
- `multimodal`;
- `data_extraction`;
- `low_latency`;
- `low_cost`.

Campos adicionales utiles:

- `cost_tier`: `low`, `medium`, `high`;
- `risk_tier`: `low`, `medium`, `high`;
- `context_window`;
- `default_for`;
- `routing_weight`;
- `requires_billing`, cuando aplique.

## Tests recomendados

Agregar cobertura para:

- `POST /config/provider` guarda key sin devolverla;
- `GET /config/providers` no contiene secretos;
- modelo fuera del catalogo se rechaza;
- modelo deprecated se rechaza por defecto;
- modelo de otro provider se rechaza;
- router no elige provider sin API key;
- router no acepta modelo fuera del catalogo;
- discovery no modifica `models.json`;
- modelos activos sin `purpose` son reportados por validacion;
- errores de configuracion no imprimen secretos.

## Decision tecnica recomendada

La UI de configuracion debe permitir registrar llaves y seleccionar defaults,
pero no debe convertir el modelo default en una decision fija.

El modelo default debe ser un fallback operativo. La eleccion correcta debe
seguir dependiendo de:

- contexto del proyecto;
- paso activo;
- agente preset;
- notas de ruteo;
- keywords;
- historial de ratings;
- proposito del modelo definido en el catalogo;
- costo y disponibilidad.

En resumen:

- `Configuracion` habilita proveedores y defaults seguros;
- `models.json` gobierna modelos, precios, estado y propositos;
- `models-cache.json` informa disponibilidad real de la cuenta;
- el router decide la asignacion final, pero validado contra catalogo y
  configuracion.
