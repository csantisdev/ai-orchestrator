# Esquema de `context.yaml`

Cada proyecto registrado tiene su propio `.orchestrator/context.yaml`,
versionado junto al código. Este archivo es la fuente de verdad que el
router consulta para decidir qué proveedor usar en cada tarea.

## Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `name` | string | Nombre legible del proyecto. |
| `stack` | string | Stack tecnológico principal (ej. "PHP/Laravel", "Java Spring Boot"). |
| `description` | string | Descripción breve del propósito del proyecto. |
| `conventions` | list[string] | Convenciones de código/arquitectura a respetar. |
| `preferred_models.default` | string | Proveedor por defecto si el router falla (`claude`, `openai`, `deepseek`). |
| `preferred_models.notes` | string | Texto libre en lenguaje natural con reglas de ruteo. El router lo lee directamente. |
| `keyword_hints` | list[object] | Señales calculadas en Python *antes* de llamar al router (ver abajo). |
| `skip_dirs` | list[string] | Carpetas a excluir de la indexación RAG. Se suman a las exclusiones globales (`.git`, `node_modules`, etc.). Ej: `["vendor", "storage", "bootstrap/cache"]`. Si está ausente, comportamiento idéntico a antes. |

## `keyword_hints`

Cada entrada:

```yaml
- match: "seguridad"      # substring a buscar en el texto de la tarea (case-insensitive)
  provider: "claude"      # proveedor sugerido si hay match
  weight: 3                # peso informativo (mayor = señal más fuerte)
```

Estas señales **no deciden el ruteo por sí solas** — se calculan localmente
y se le pasan al modelo router como contexto adicional, junto con
`preferred_models.notes`. El router (un modelo liviano, configurado en
`config.yaml`) es quien toma la decisión final, considerando todo el
contexto junto.

Esto da lo mejor de los dos mundos:
- Las reglas duras/conocidas quedan declaradas y versionadas (legibles, auditables).
- El router tiene flexibilidad para casos ambiguos que las keywords no cubren.

## Ejemplo completo

```yaml
name: mi-proyecto
stack: PHP/Laravel
description: Aplicación web con autenticación, roles y módulos de gestión
conventions:
  - Usar Form Requests para validación
  - PSR-12
  - Migraciones siempre con rollback probado

preferred_models:
  default: claude
  notes: >
    Tareas que toquen autenticación, permisos o datos sensibles van siempre
    a Claude por seguridad. Generación de tests unitarios o seeders puede ir
    a DeepSeek. Refactors de componentes frontend van bien con OpenAI.

keyword_hints:
  - match: "seguridad"
    provider: claude
    weight: 3
  - match: "permisos"
    provider: claude
    weight: 3
  - match: "ticket"
    provider: claude
    weight: 2
  - match: "test"
    provider: deepseek
    weight: 2
  - match: "seeder"
    provider: deepseek
    weight: 2
  - match: "refactor"
    provider: openai
    weight: 1

skip_dirs:
  - vendor
  - storage
  - bootstrap/cache
```

## Generación automática

`ai-orchestrator add <alias> --path <ruta>` genera un `context.yaml` base
con placeholders. Conviene completarlo a mano apenas se crea — el router
funciona mejor cuanto más específicas sean las `notes` y los `keyword_hints`.
