---
id: ANL-001
type: analysis
title: Evaluacion local de modelos para tests internos
status: active
created: 2026-09-25
updated: 2026-09-25
related: [RFC-006, RFC-007, ADR-002]
---

# ANL-001 - Evaluacion local de modelos para tests internos

## Objetivo

Comparar modelos para generacion y revision de tests sin publicar prompts,
respuestas, nombres de proyectos ni datos operativos. Esta es una metodologia de
medicion; no aprueba un modelo ni cambia el router.

## Datos permitidos

Cada run evaluado registra solamente etiquetas controladas y metricas:

| Campo | Valores o forma permitida |
|---|---|
| `task_class` | `unit`, `integration`, `regression`, `schema`, `edge_case` |
| `verification_result` | `passed`, `failed`, `manual_review` |
| `rating` | `useful`, `partial`, `wrong` |
| Metricas | proveedor, modelo, conteos, costo, duracion y cobertura de rating agregados |

No se incluye `task`, `task_preview`, `response`, `project`, identificadores,
fixtures reales ni rutas de proyecto. El comando `ai-orchestrator model-eval`
consulta exclusivamente las columnas permitidas y devuelve grupos agregados.

## Protocolo

1. Construir 30 a 50 casos sinteticos derivados de contratos ya conocidos.
2. Para cada caso, definir el oraculo y una mutacion o defecto que el test debe
   detectar. Un test verde sin detectar la mutacion no cuenta como validacion.
3. Asignar el modelo generador mediante hash deterministico de `case_id`; no
   seleccionar manualmente el modelo por sesgo de conveniencia.
4. Revisar la salida y el resultado de ejecucion sin revelar el modelo al
   evaluador. Registrar las tres etiquetas controladas al cerrar el caso.
5. Ejecutar `ai-orchestrator model-eval` localmente para comparar resultados
   agregados por modelo y clase de tarea.

## Medición y umbrales pre-registrados

El benchmark usa `ai-orchestrator benchmark-validate`. El manifest es local,
contiene solo casos sintéticos y define dos comandos sin shell por caso:

- **baseline:** debe terminar en código 0;
- **mutación:** debe terminar distinto de 0 para que el defecto sea detectado.

La métrica primaria es
`mutation_detection_rate = mutaciones detectadas / baselines exitosos`.
Un timeout no es una detección: invalida el caso y se reporta por separado. La
asignación se ordena por hash de `seed`, `task_class` y `case_id`, alternando
los modelos dentro de cada clase; por construcción, la diferencia de casos
asignados entre brazos es como máximo uno por clase.

| Hito | Tamaño y condición | Conclusión permitida |
|---|---|---|
| Viabilidad | 50 casos, 10 por clase, ejecución reproducible y sin timeouts | El corpus y el runner sirven; no elegir modelo. |
| Señal direccional | 200 casos, 20 por modelo y clase, cobertura de rating >= 80% | Inspeccionar resultados y ampliar si hay diferencia. |
| Decisión de promoción | 600 casos, 60 por modelo y clase, cobertura de rating >= 80% | Evaluar no inferioridad con margen máximo de 10 puntos porcentuales. |

Con 300 casos por modelo, el semiancho aproximado de 95% para una diferencia
de proporciones en el peor caso es 8 puntos porcentuales. Antes de ese tamaño,
las métricas son orientativas y no justifican cambiar el modelo predeterminado.

## Modelo inicial y limites

El piloto propuesto usa GPT-5.4-mini para generacion estandar, sujeto a
discovery local y verificacion de precio/disponibilidad, y Claude Sonnet 4.6
para revision independiente de casos criticos. Los modelos y precios deben
refrescarse antes de cada piloto; el catalogo no es una garantia de
disponibilidad.

No se concluye calidad con menos de 200 runs evaluados, y toda conclusion debe
mostrar `rating_coverage`. El rating observa el resultado entregado, no el
contrafactual de otro modelo; por eso el piloto requiere asignacion
deterministica y revision a ciegas.

## Criterio de decision

Un modelo puede ser candidato a predeterminado solo si:

- no es materialmente inferior en deteccion de mutaciones/regresiones;
- mantiene o reduce correccion humana, costo o latencia;
- tiene cobertura de rating suficiente para declarar una conclusion;
- cumple clearance y las politicas de egress del proyecto.

Una promocion requiere un ADR posterior que fije el modelo, alcance,
sensitivity/clearance, umbrales y fecha de revision.
