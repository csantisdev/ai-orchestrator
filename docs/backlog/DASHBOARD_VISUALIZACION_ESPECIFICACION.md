# ai-orchestrator — Especificación de visualización del dashboard

**Proyecto:** ai-orchestrator  
**Documento:** referencia de diseño para análisis e implementación gradual (backlog, no normativo)  
**Fecha:** 2026-10-02  
**Baseline verificado:** `production@985b74970477e729eda97ee0728ab6575b523014`  
**Estado:** validado (auditoría cruzada con Codex CLI y Copilot CLI cerrada en cada sección); referencia para las olas de §24

---

## 1. Objetivo y alcance

Este documento fija una base común para evolucionar la visualización de ai-orchestrator. No congela
un diseño final: ordena criterios de UX, datos, seguridad y entrega para decidir cada cambio con la
misma vara.

La pregunta central no es "¿cómo hacemos un dashboard más atractivo?", sino:

> ¿Cómo hacemos visible, comprensible y accionable la evolución gobernada de un proyecto asistido por IA?

El dashboard debe ayudar a responder:

1. ¿Qué está ocurriendo?
2. ¿Cómo llegamos aquí?
3. ¿Qué contexto influyó?
4. ¿Qué política permitió o bloqueó?
5. ¿Quién o qué ejecutó?
6. ¿Qué resultado produjo?
7. ¿Qué puedo hacer ahora?

### Fin principal

Según el análisis de datos reales de §19, la vista tiene un fin principal:

> **Mostrar en un solo lugar en qué está el trabajo que los agentes hacen sobre un proyecto, si está
> alineado con el plan, qué evidencia lo respalda y cuánto costó.**

La cadena primaria es Contexto → Paso → Notas y alineamientos → Commits y runs vinculados o citados
→ Resultado. Según §20, la evidencia principal hoy son las notas del paso y los commits que citan;
las invocaciones MCP se muestran como actividad del proyecto (§6.4), no como evidencia del paso.
La cadena de routing y egress es secundaria: se muestra cuando hay datos y pasa a primer plano
cuando el flujo `ai-orchestrator run` los genere.

### Alcance

- **Dashboard HTML actual** (`ai-orchestrator serve`): se rediseña de forma incremental. Es el único
  frente de implementación.

### Fuera de alcance de este documento

- Distribución del paquete Python: se sigue instalando como hoy (`pip install -e`).
- Reemplazo del stack del dashboard (ver §2).
- Extensión de VS Code: descartada por ahora (ver §12).

---

## 2. Decisiones de esta revisión

| # | Decisión | Motivo |
|---|---|---|
| D-1 | El rediseño se hace sobre el stack actual: HTML generado en `orchestrator/dashboard.py`, tokens CSS en `orchestrator/dashboard_css.py`, JS sin frameworks en `orchestrator/dashboard_js.py` y `http.server` en `orchestrator/server.py`. | Mantener la línea de diseño vigente y evitar una segunda base de frontend. |
| D-2 | No se adopta por ahora FastAPI, React/Svelte, Vite ni XYFlow. | Ninguna medición lo justifica todavía; ver §15. |
| D-3 | La extensión de VS Code queda descartada por ahora; todo el esfuerzo va al dashboard HTML. | La vista del dashboard en el navegador alcanza para centralizar la información y concentra el esfuerzo de implementación en un solo frente. |
| D-4 | Trace se implementa antes que Workspace (grafo). | Trace es una cadena lineal que el stack actual resuelve sin librería de grafos. |
| D-5 | Las entidades conceptuales (Decision, Evidence, Outcome) empiezan como proyecciones sobre SQLite, no como tablas nuevas. | Una sola fuente de verdad; ver §10. |
| D-6 | El Event Log durable requiere un RFC propio antes de implementarse. | Cambia persistencia y retención de datos; ver §11. |
| D-7 | Endurecer el servidor del dashboard (token, Origin, Host y endpoints con efectos) es prerrequisito del rediseño. | Hoy cualquier página abierta en el navegador puede disparar acciones con efectos, y el rediseño suma endpoints JSON; ver §13. |
| D-8 | D0 cambia una frontera de seguridad: antes de implementarla se escribe un RFC (fase R0). | Threat model, ciclo del token y exposición de datos son decisiones normativas, no de backlog. |

---

## 3. Tesis de experiencia

El dashboard no debe limitarse a presentar registros. Debe representar:

```text
estado + causalidad + contexto + provenance + acción
```

Relaciones que el usuario debe poder seguir:

```text
Contexto → Paso → Notas y alineamientos → Commits y runs vinculados o citados → Resultado
```

y, cuando el run pasó por el router:

```text
Política de egress → Contexto autorizado → Routing → Proveedor / agente → Run → Resultado
```

El grafo solo agrega valor cuando responde preguntas. Si solo aumenta líneas y nodos, es ruido.

### North Star

Un usuario debería poder mirar la interfaz y decir:

> Estoy viendo qué se está haciendo en mi proyecto, qué contexto influyó, qué decisión se tomó,
> quién o qué ejecutó, cuál fue el resultado y por qué ocurrió.

- Al seleccionar: entiendo qué significa y qué está relacionado.
- Ante un bloqueo: sé qué política lo produjo.
- Ante una degradación: sé qué parte falla y qué consecuencias tiene.

Frase guía:

> El dashboard no debería mostrar solamente dónde están los datos del proyecto. Debe mostrar cómo
> el proyecto llegó a ser lo que es, qué está ocurriendo ahora y qué puede hacer el usuario a continuación.

---

## 4. Principios de diseño

### 4.1 Progressive disclosure

> Mostrar lo necesario. Revelar lo demás cuando el usuario lo solicita.

Evitar mostrar a la vez todos los runs, contextos, decisiones, evidencias, relaciones y métricas.

Hipótesis iniciales (a validar con uso real, no leyes):

- 8–15 entidades relevantes visibles;
- máximo 3 regiones dominantes de pantalla;
- máximo 2 CTA principales;
- una selección primaria;
- una alerta fuerte visible a la vez.

### 4.2 Criterio de ruido

> Cada interacción debe disminuir incertidumbre.

Si una acción agrega nodos, relaciones, labels, paneles o métricas, debe justificar qué pregunta
responde. Evitar de forma permanente: minimap con pocos nodos, controles +/- innecesarios, labels en
cada relación, KPIs dentro de vistas de trabajo, timeline siempre expandida, acciones dentro de cada
nodo, glow constante, partículas y animaciones decorativas.

### 4.3 Gramática visual por familias

No usar un color por cada entidad posible.

| Familia | Ejemplos | Color conceptual |
|---|---|---|
| Knowledge | Contexto | Verde |
| Work | Paso | Azul |
| Decision | Routing | Ámbar |
| Execution | Run | Cian |
| Governance | Evidence / Egress | Violeta |
| Error técnico | Failure | Rojo |
| Neutral | Metadata | Gris |

Los colores se definen como tokens nuevos en `dashboard_css.py` para **todos** los temas existentes
(dark, light, midnight, nord, espresso, a11y). El color nunca es la única semántica: siempre va
acompañado de icono, forma o texto.

### 4.4 Semántica de relaciones

| Tipo | Trazo | Uso |
|---|---|---|
| Hecho confirmado | sólido `────▶` | FK real en SQLite |
| Inferencia | discontinuo `- - ▶` | relación deducida (p. ej. por timestamps) |
| Recomendación IA | punteado `· · ▶` | sugerencia no confirmada |
| Referencia verificada | sólido con rombo `───◇` | SHA citado en notas que existe como commit importado (§21.3) |

Distinguir lo observado, lo inferido y lo recomendado importa más que agregar colores.

Etiquetas: ocultas en estado normal, visibles en hover, enfatizadas en selección y explícitas en Trace.

### 4.5 Selección y foco

Seleccionar una entidad reduce ruido: actualiza el Inspector, enfatiza relaciones relevantes, baja
la opacidad del resto (≈15–25 %) y puede destacar eventos asociados en Activity.

> Selección = reducción temporal del universo visual.

### 4.6 Movimiento y glow

- Movimiento semántico, no decorativo: animar transiciones (seleccionar, abrir Inspector), nunca en
  bucle. Respetar `prefers-reduced-motion`.
- Glow representa estado (selected, running, blocked, attention), no tipo. Estado normal: borde
  fino y relleno sutil.

---

## 5. Estructura de pantalla

```text
┌───────────────────────────────────────────────────────────────┐
│ Header: proyecto · búsqueda                                   │
├──────────────┬─────────────────────────────┬──────────────────┤
│ Navegación   │        Vista central        │    Inspector     │
├──────────────┴─────────────────────────────┴──────────────────┤
│ Activity (colapsada por defecto)                              │
└───────────────────────────────────────────────────────────────┘
```

| Región | Pregunta |
|---|---|
| Navegación | ¿Dónde estoy? |
| Vista central | ¿Qué está ocurriendo y cómo se relaciona? |
| Inspector | ¿Qué significa lo seleccionado y qué puedo hacer? |
| Activity | ¿Qué acaba de cambiar? |

Se implementa con CSS grid sobre los tokens existentes. El panel lateral actual evoluciona hacia el
Inspector.

### 5.1 Header

```text
ai-orchestrator    mi-proyecto ▼      Buscar contextos, runs...
```

Evolución de la búsqueda: texto libre → filtros (`run:146`, `provider:claude`, `status:blocked`) →
comandos. No intentar resolverlo todo en la primera versión.

### 5.2 Navegación

```text
PROYECTO   Overview · Trace · Runs · Contextos · Egress
CONTROL    Proveedores · Políticas · Ajustes
```

> **Reemplazado por §23.3.** La navegación vigente es Inicio · Trabajo · Ejecuciones · Gobernanza;
> Trace pasa a ser el detalle de un paso. Esta lista queda como antecedente.

PROYECTO agrupa comprensión y trabajo; CONTROL agrupa configuración y gobernanza. Las secciones que
el dashboard ya tiene se reubican como vistas. Workspace se agrega cuando exista (§14).

---

## 6. Vistas

> Estas vistas se reorganizan en §23.2–§23.3: Overview es Inicio, Trace es el detalle del paso
> dentro de Trabajo, Activity es persistente.

### 6.1 Overview

Pregunta: ¿qué necesita mi atención?

Métricas verificables, cada una con link a la lista filtrada que la explica:

```text
Contextos activos · Pasos en curso · Pasos estancados · Actividad de agentes (24 h)
Llamadas MCP denegadas o con error · Costo del período · Salud del tracking
```

Cada métrica debe dar señal con los datos reales (§19.1). Se descartan por ahora "Runs fallidos"
(todos los runs registrados están en `done`), "Runs sin rating" (casi el 100 %) y "Bloqueados por
egress" (sin filas); vuelven cuando sus fuentes tengan datos. "Pasos estancados" usa la
advertencia de `orchestrator/tracking_health.py` sobre pasos `in_progress`, que mide su actividad
por alignments, tool calls y runs. Las demás advertencias del módulo (varios contextos activos,
contexto sin paso activo, contextos programados estancados) pueden mostrarse como alertas aparte.
"Salud del tracking" agrega esas advertencias y la calidad de datos de §20.2 (omitidos que no son
skip real, completados sin inicio). No se muestran duraciones de pasos: con los datos reales no
reflejan tiempo de trabajo (§20.2). La tarjeta Egress se muestra en estado vacío explicado.

Evitar porcentajes sin fórmula trazable ("Health 82 %").

> Si el usuario pregunta "¿de dónde salió este número?", el dashboard debe poder responder.

### 6.2 Trace

Pregunta: ¿por qué ocurrió esto?

Hay dos anclas:

**Trace de paso (primaria).** Responde qué se hizo en un paso y qué lo respalda:

```text
Contexto → Paso → Notas del paso → Commits citados (SHA verificado) / PRs citados
                → Alineamientos y tool calls (FK) → Runs vinculados (FK) → Resultado
```

- Las notas son el primer nivel: con los datos reales son la evidencia principal (§20.2).
- Los SHAs citados en las notas que existen como commit importado se muestran como "referencia
  verificada" (trazo sólido con etiqueta). Los que no existen, como texto. Los PRs citados, como
  referencia sin verificar.
- Alineamientos, tool calls y runs vinculados por FK: trazo sólido.
- Las invocaciones MCP no se asocian al paso: `mcp_invocations` no tiene `step_id` ni `context_id`,
  y con pasos que se activan y cierran en lote (§20.2) una ventana de tiempo sería engañosa. Se
  muestran en la Activity del proyecto. Una relación confirmada requiere la recomendación 1 de
  §20.4, que toca RFC-008.

**Trace de run (secundaria).** Solo cuando el run pasó por el router:

```text
Paso → Routing (routing_source, routing_reason) → Egress (decision, reason_code)
     → Proveedor / modelo → Run → Outcome (status + rating)
```

Un run importado (sesión de Claude Code o Codex, o commit de git) muestra "sin routing ni egress:
run importado" como estado explícito, no como cadena vacía. Prioriza causalidad, provenance,
política y resultado. Se dibuja como una cadena vertical; no necesita un grafo.

### 6.3 Inspector

Primer nivel: identidad, estado, atributos principales, relaciones importantes y acciones.
Segundo nivel, colapsado: rationale, metadata, historial, referencias crudas. No llenarlo todo de
inmediato.

### 6.4 Activity

Colapsada por defecto (`Run 146 completado · 14:32 ▴`). Expandida, lista eventos recientes con
acciones Ver / Trace / Filtrar. En la primera versión se alimenta de la proyección de §10.4; el SSE
actual solo dispara el refresco.

---

## 7. Estados especiales

| Estado | Ejemplo | Tratamiento |
|---|---|---|
| Degradado | ChromaDB no disponible; el routing sigue sin señales de similitud | borde discontinuo, warning, texto explícito |
| Bloqueado por política | Proveedor: gemini · reason_code: clearance_insufficient | no es error técnico; icono de escudo |
| Falla técnica | Falló la request al proveedor | semántica de error (rojo) |
| Desincronizado | La vista está detrás del último evento; reconectando | aviso no bloqueante |
| Vacío | Proyecto sin runs ni contextos | explicar qué se va a conectar y cómo empezar; nunca un canvas vacío sin contexto |

Operaciones largas: mostrar etapas ("Resolviendo relaciones ✓ · Aplicando política ✓ · Ejecutando ●")
en lugar de "Pensando...".

---

## 8. Tema y accesibilidad

### Tema

Se mantienen los 6 temas actuales y se agrega el modo **System** (sigue `prefers-color-scheme`)
como predeterminado.

### Accesibilidad

Todo debe funcionar sin mouse: Tab, flechas, Enter, Escape y atajos con alternativa visible.
Además: foco visible, contraste AA, semántica no dependiente del color, alternativa a todo drag,
zoom al 200 %, labels para lector de pantalla y `prefers-reduced-motion`. Forma parte de la
aceptación de cada fase, no se agrega al final.

### Performance percibida

- hover / selección / expandir: feedback ideal < 100 ms;
- INP p75 ≤ 200 ms.

---

## 9. Compatibilidad con el backend real

Verificado sobre el baseline:

| Dato | Tabla / columna | Relación |
|---|---|---|
| Runs | `runs` (status, provider, model, costos, tokens, `routing_reason`, `routing_source`, `rating`, `parent_run_id`) | `runs.step_id → steps` |
| Contextos | `contexts` | `contexts.parent_step_id → steps` |
| Pasos | `steps` | `steps.context_id → contexts` |
| Tool calls | `tool_calls` | `step_id`, `context_id` |
| Alineamientos | `alignments` | `step_id`, `context_id` |
| Contexto RAG usado | `context_hits` (collection, source, chunk_idx, score) | `run_id → runs` |
| Egress | `egress_decisions` (phase, decision, reason_code, sensitivity, clearance) | `run_id → runs` (nullable) |
| Invocaciones MCP | `mcp_invocations` | — |

Huecos conocidos:

- `egress_decisions` no guarda el identificador de la política aplicada; Trace muestra
  `reason_code`, `sensitivity` y `clearance`, no un nombre de política.
- No existe log de eventos durable: el bus SSE (`orchestrator/sse.py`) vive en memoria.
- Decision, Evidence, Outcome, Artifact y Agent no son tablas.

---

## 10. Modelo de datos para la UI

### 10.1 ProjectGraph neutral

El frontend no consume el esquema SQLite directamente. Un módulo de proyecciones (propuesto:
`orchestrator/projections.py`, funciones puras y testeables) devuelve:

```json
{
  "nodes": [{"id": "run:146", "kind": "run", "label": "Run 146", "state": "done"}],
  "edges": [{
    "source": "context:18",
    "target": "step:52",
    "relation_type": "contains",
    "origin": "system",
    "confidence": 1.0,
    "evidence_ref": "steps.context_id"
  }],
  "metadata": {"project": "mi-proyecto", "generated_at": "..."}
}
```

`origin` y `confidence` alimentan la semántica de trazo de §4.4. Cualquier librería de grafos
futura sería un adapter de este formato, nunca el modelo de dominio.

### 10.2 Decision como proyección

`routing_source` + `routing_reason` del run, más las filas de `egress_decisions` del mismo `run_id`.

### 10.3 Evidence y Outcome como proyecciones

- Evidence = colección de referencias verificables (`egress_decision:881`, `context_hit:3291`,
  `alignment:37`, `tool_call:122`). La UI muestra "7 referencias"; cada una mantiene provenance.
- Outcome = `runs.status` + `runs.rating`. Podrá ser entidad real cuando existan eventos como tests
  pasados, PR mergeado o aprobación humana.

### 10.4 Activity como proyección

Unión ordenada por timestamp de runs, tool_calls, alignments, egress_decisions, los hitos de pasos
disponibles (`steps.started_at` y `steps.completed_at`) y las invocaciones MCP que no son de solo
lectura (`mcp_invocations` con `tool_category` distinto de `read`), limitada por proyecto y ventana
de tiempo.
No requiere tabla nueva.

Límite: `steps` no guarda historial de estados, así que bloqueos, reaperturas, skips y cambios de
título no aparecen en Activity. El historial completo queda para el Event Log (§11).

### 10.5 Proyección antes que base de grafos

```text
SQLite → proyecciones → ProjectGraph → vistas
```

Solo materializar proyecciones si una medición demuestra necesidad.

---

## 11. Event Log durable (requiere RFC)

Objetivo futuro: `evento de dominio → tabla de eventos en SQLite → event_id → SSE → UI`, para
replay, reconexión, Trace e historial.

> SSE es transporte. El Event Log es evidencia durable.

Registrar: IDs, timestamps, estados, duración, reason codes, identificadores de proveedor/modelo,
conteos, hashes y referencias a entidades.

No persistir indiscriminadamente: prompts completos, system prompts, contexto RAG completo,
respuestas completas, secretos, excepciones arbitrarias ni payloads sensibles de tools.

> Registrar que algo ocurrió y cómo se relaciona; no copiar todo lo que ocurrió.

---

## 12. Extensión de VS Code (descartada por ahora)

Decisión del 2026-10-02: la vista en el navegador alcanza para centralizar la información, así que
no se construye una extensión. Si se retoma, partir de lo ya auditado:

- Contenedor solo visual: webview con un iframe al dashboard; no instala el paquete, no configura el
  MCP ni gestiona API keys.
- El `src` del iframe y el único origen de `frame-src` en la CSP son la URI exacta que devuelve
  `vscode.env.asExternalUri`; en Remote-SSH, Dev Containers o Codespaces puede ser un proxy o túnel.
- Dentro del iframe, los `fetch` salen con el origen del documento embebido, no del webview: la
  allowlist de §13.3 tendría que sumar ese origen remoto exacto.
- El dashboard no envía `X-Frame-Options`, así que hoy puede embeberse.
- Requiere ampliar el RFC de R0 antes de implementarse.

---

## 13. Seguridad: prerrequisito

### 13.1 Estado actual

- `do_POST` en `orchestrator/server.py` no valida `Origin` ni `Host` y despacha endpoints con
  efectos: borrar contextos, purgar colecciones de ChromaDB, avanzar o saltar pasos, ejecutar
  `doctor`/`fix` y lanzar runs.
- La única barrera es `_require_json_ct`, que exige `application/json` en `Content-Type`. Obliga a un
  preflight CORS que el servidor no responde, así que bloquea un `fetch` cross-origin con
  `Content-Type: application/json`. Es una barrera **parcial, no una autorización**: el chequeo es por
  subcadena, y un valor como `text/plain; x=application/json` mantiene la petición como CORS-simple
  (sin preflight) y aun así pasa el chequeo. D0 debe confirmarlo con un test.
- Hay GET con efectos o datos sensibles: `/pick-folder` lanza un proceso y un diálogo nativo;
  `/export-csv` y `/run/{id}` devuelven tareas y respuestas completas. Sin validar `Host`, un ataque
  de DNS rebinding podría leerlos desde otra página.

### 13.2 Objetivo de D0

- Validación centralizada **antes del despacho** de todo POST (incluido `/context/{id}/delete`):
  token por sesión, `Origin` permitido y `Host` permitido.
- `Content-Type` comparado por tipo MIME exacto, no por subcadena.
- Validación de `Host` también en GET.
- `/pick-folder` pasa a POST con token.
- Inventario explícito de los endpoints con efectos y de los que exponen datos de runs.

### 13.3 Orígenes permitidos

| Uso | Origin / Host permitidos |
|---|---|
| Navegador local | `http://127.0.0.1:<puerto>` y `http://localhost:<puerto>` |

Cualquier otro origen se rechaza. La generación, transporte y vida útil del token se definen en el
RFC de R0.

---

## 14. Plan por fases

Cada fase es un PR independiente con auditoría cruzada en dos rondas (ANL-003).

| Fase | Contenido | Depende de |
|---|---|---|
| R0 | RFC en `docs/decisions/rfcs/`: threat model del dashboard, ciclo y almacenamiento del token, orígenes permitidos y política de exposición de datos (§13) | — |
| D0 | Seguridad del dashboard (§13) | R0 |
| D1 | Plantilla única (§23.4), navegación 4 + 3 (§23.3), Inspector persistente y **contenedor** de Activity (con los eventos SSE actuales), tokens y componentes base (§23.5), handler estático para `static/dashboard/`, estructura de módulos con store y router (§23.7), test de línea base de colores y estilos literales, y Node fijado en CI. Incluye O3 de §19.4; O1 y O2 van con Ejecuciones en la ola 3 (§24.5), que es dueña de la lista de runs | D0 |
| D2 | Overview con métricas verificables y links a su origen (§6.1) | D1 |
| D3a | Proyecciones puras: `orchestrator/projections.py` (normalización de agentes y timestamps a UTC, extracción de SHAs y PRs), esquemas DTO y tests, sin endpoints ni UI (§10, §20, §24.4) | R0 |
| D3b | Trabajo: lista de contextos, página del contexto y detalle del paso con Trace (§23.3); endpoints JSON en `api_v1` (§6.2) | D1, D3a |
| D4 | **Contenido** de Activity desde la proyección de §10.4 (hitos que hoy existen en la base: runs, alineamientos, tool calls, decisiones de egress, inicio y cierre de pasos e invocaciones MCP), línea de tiempo con esos hitos y detección de cambios entre procesos (§19.4 O4–O5). Skips, reaperturas y cambios de título no aparecen hasta el Event Log (§11) | D3b |
| D5 | Estados especiales (§7), modo System, teclado y reduced motion (§8) | D1 |
| D6 | Experimental (Labs): representación Mapa de los pasos de un contexto (§21, §23.2) | D3b |
| D7 | Experimental (Labs): representación Constelación de los contextos (§22, §23.2) | D6 (mergeada y medida, §24.4) |

### Criterios de aceptación

La auditoría cruzada no reemplaza las pruebas automatizadas. Cada fase pasa `python -m pytest tests/`
y agrega lo suyo:

| Fase | Aceptación mínima |
|---|---|
| R0 | `python scripts/validate_decision_docs.py` en verde; RFC aceptado por el usuario. |
| D0 | Tests HTTP por cada ruta POST: token válido, ausente e inválido; `Origin` y `Host` permitidos y rechazados; `Content-Type` con subcadena engañosa rechazado; `/pick-folder` ya no accesible por GET simple; `Host` permitido y rechazado en `/run/{id}`, `/export-csv` y todo GET restante con efectos o datos sensibles; SSE (`/events`) sin regresión; el dashboard propio sigue funcionando. |
| D1–D2 | Tests de render de `build_html` por vista; cada métrica de Overview con test que compare su valor contra la consulta de origen. |
| D3–D4 | Tests unitarios de las proyecciones sobre una base SQLite sintética: nodos, relaciones, `origin`/`confidence` y orden de Activity. |
| D5 | Revisión de teclado y contraste en todos los temas, incluido a11y; `prefers-reduced-motion` respetado. |
| D6 | Ver §21.6: tests de la proyección del mapa, accesibilidad por nodo, lista sincronizada y criterio de permanencia medible. |
| D7 | Ver §22.5: proyección con puentes y portales, posiciones deterministas, invalidación de caché, Canvas y lista sincronizados, rendimiento medido en navegador. |

### API JSON sobre el servidor actual

Endpoints de solo lectura en el `http.server` existente, sin FastAPI:

```text
GET /api/v1/projects
GET /api/v1/projects/{p}/overview
GET /api/v1/projects/{p}/runs?limit=50&before=<ts>,<id>
GET /api/v1/projects/{p}/runs/{id}
GET /api/v1/projects/{p}/runs/{id}/trace
GET /api/v1/projects/{p}/contexts
GET /api/v1/projects/{p}/steps
GET /api/v1/projects/{p}/steps/{id}/trace
GET /api/v1/projects/{p}/egress-decisions
GET /api/v1/projects/{p}/activity?limit=50
GET /api/v1/projects/{p}/mcp-invocations?status=denied,error
```

### Diferido (después de D5)

- **Workspace (grafo) general:** fuera de D6 (§21), que cubre solo el mapa de un contexto. Subgrafo operativo de la tarea actual, lentes (Todo / Ejecución /
  Gobernanza; una lente cambia el énfasis, no la verdad), foco y selección múltiple. Requiere elegir
  cómo dibujar y ubicar nodos sin framework, o justificar una librería.
- **Scope:** lista explícita de entidades seleccionadas para consultar a la IA.
- **Chat contextual:** el navegador envía solo IDs (`["run:146", "context:18"]`) y una pregunta; el
  servidor resuelve scope, aplica la política de egress y decide qué contexto está autorizado.

  > El navegador expresa intención. El servidor decide qué contexto está autorizado.

- **Event Log durable** (§11, vía RFC).
- **Gobernanza de comandos desde la UI:** idempotencia, `expected_version`, conflictos, límites de
  presupuesto y consistencia entre pestañas.

---

## 15. Fuera de alcance por ahora

FastAPI, React/Svelte, Vite, XYFlow, Sigma/WebGL, WebGPU, Neo4j, GraphQL, Redis, NATS, WebSockets,
multi-worker, Tauri, extensión de VS Code (§12), microservicios, vista global multi-proyecto y tablas artificiales para cada
concepto visual. Pueden volver si una métrica lo justifica.

---

## 16. Métricas de UX

Hipótesis iniciales:

```text
INP p75 ≤ 200 ms
feedback visual local < 100 ms
8–15 entidades relevantes iniciales
0 acciones que solo se puedan hacer con drag
0 semántica dependiente solo del color
```

Medir además: tiempo para encontrar un run, tiempo para explicar por qué se usó un proveedor,
tiempo para explicar un bloqueo de egress, éxito de tareas con teclado y problemas de accesibilidad.

---

## 17. Preguntas de revisión para cada feature

1. ¿Reduce incertidumbre?
2. ¿Agrega más información visual de la que elimina?
3. ¿Debe estar visible todo el tiempo?
4. ¿Es entidad real o proyección?
5. ¿Tiene provenance? ¿Se puede explicar su origen?
6. ¿Funciona sin mouse?
7. ¿Funciona en todos los temas, incluido a11y?
8. ¿Tiene estado degradado?
9. ¿Necesita animación? ¿Necesita otro color?
10. ¿Necesita persistencia?
11. ¿Puede resolverse con una Web API nativa?
12. ¿Pertenece a Overview, Trace o Workspace?
13. ¿Responde una necesidad medida o imaginaria?

---

## 18. Cómo usar este documento

Sirve como base de un futuro RFC, guía de revisión con Claude/Codex, checklist de UX y contrato
conceptual entre proyecciones y vistas. No es dogma: si una medición, prueba de uso o restricción
técnica contradice algo de aquí, la evidencia tiene prioridad.

La meta no es preservar un mockup, sino la comprensibilidad, la trazabilidad, la gobernanza, la
mantenibilidad, el rendimiento, la accesibilidad y la capacidad de evolución.

---

## 19. Análisis de servicios, rendimiento, recursos y UX

Medido el 2026-10-02 sobre la base local de un usuario (`runs.db`, 11 MB) en solo lectura, con el
código de la rama. Solo se reportan conteos agregados. Es una instantánea anterior a la de §20: las
tablas de tracking crecen con el uso (cada llamada MCP, incluidas las de las auditorías, agrega una
fila a `mcp_invocations`), así que §19 y §20 pueden diferir en unas pocas filas.

### 19.1 Datos reales disponibles

| Tabla | Filas | Observación |
|---|---|---|
| `runs` | 1158 | 98 % importados (`session_id` no nulo): 930 commits de git, 114 sesiones de Codex, 92 de Claude Code; 22 de otras fuentes. Todos en `done`; 1 con `rating`; `routing_source` nulo en todos. 65 vinculados a un paso; ningún commit de git vinculado. |
| `contexts` / `steps` | 63 / 372 | Plan de trabajo con historial real. |
| `alignments` / `tool_calls` | 195 / 29 | Evidencia de alineamiento abundante; tool calls escasos. |
| `mcp_invocations` | 646 | Desde 2026-09-25. Guarda hashes, no payloads. 245 lecturas y 401 mutaciones o transiciones; 467 desde Claude Code y 152 desde Codex; **20 denegadas y 6 con error**. |
| `context_hits` / `egress_decisions` | 0 / 0 | Sin datos: los runs importados no pasan por el router ni por el gate de egress. |

Conclusiones:

1. La cadena política → routing → egress → RAG no tiene datos hoy. Diseñar la vista alrededor de
   ella mostraría estados vacíos casi siempre.
2. Los datos ricos son el plan y la evidencia de trabajo de los agentes: contextos, pasos,
   alineamientos e invocaciones MCP.
3. La gobernanza que sí tiene datos es la del acceso MCP (RFC-008): denegaciones con `reason_code`.
   La lente de gobernanza debe empezar por ahí.
4. `mcp_invocations` ya cumple buena parte de §11 (IDs, timestamps, estado, `reason_code`, hashes,
   duración, superficie del cliente). El RFC del Event Log debe partir de esta tabla en vez de crear
   otra en paralelo.

### 19.2 Servicios y APIs que usa la vista

Overview, Trace, Activity, Runs y la API nueva no llaman a proveedores de IA ni a servicios
externos: se resuelven contra SQLite local dentro del proceso de `serve`. ChromaDB queda fuera del
camino principal. Excepciones existentes, fuera de ese camino: Ajustes y Proveedores pueden consultar
la red (`orchestrator/rates.py` para tipos de cambio y `orchestrator/catalog.py` para el catálogo de
precios), y "ejecutar tarea" (`POST /run`) llama a un proveedor.

| Vista | Fuente | Endpoint hoy | Endpoint propuesto | Costo medido |
|---|---|---|---|---|
| Página inicial | `runs` (500 últimos) | `GET /` (HTML con runs embebidos) | `GET /` solo con el shell | 25 ms lectura + 8 ms render; 381 KB |
| Overview | conteos sobre contexts, steps, runs y mcp_invocations | `/metrics` (parcial) | `GET /api/v1/projects/{p}/overview` | 0,4 ms (6 consultas) |
| Trace | joins por FK (runs, steps, contexts, alignments, tool_calls, context_hits, egress_decisions) | `/run/{id}` (parcial) | `GET /api/v1/projects/{p}/steps/{id}/trace` y `.../runs/{id}/trace` | 0,1 ms |
| Activity | unión de §10.4 | — | `GET /api/v1/projects/{p}/activity?limit=50` | 0,5 ms |
| Runs | `runs` sin `task` ni `response` | HTML embebido | `GET /api/v1/projects/{p}/runs?limit=50&before=<ts>,<id>` | sin medir; misma consulta indexada que hoy, sin `task` ni `response` |
| Inspector de run | `runs` completo | `/run/{id}` | se mantiene | bajo demanda |
| Contextos | contexts, steps | `/contexts-html`, `/context/{id}` | se mantienen; JSON en `/api/v1/.../contexts` | — |
| Proveedores / Ajustes | pricing, models, rates, agents | `/pricing`, `/models`, `/rates`, `/agents`, `/integrations/status` | se mantienen | — |
| Datos de RAG | ChromaDB | `/inspect` | se mantiene fuera de Overview y Trace | 15 ms SQLite + carga de ChromaDB |
| Tiempo real | bus SSE en memoria | `/events` | `/events` + evento `db_changed` (§19.4) | — |

Todos los endpoints nuevos son GET de solo lectura, pasan por la validación de `Host` de D0 y no
devuelven `task` ni `response` salvo en el Inspector.

### 19.3 Tiempos de respuesta

Línea base (mediana de varias ejecuciones, en proceso, sin red):

- La página inicial pesa 381 KB, de los cuales 329 KB son script: ~215 KB son el JSON de 500 runs
  embebidos y ~114 KB el código JS. Con `Cache-Control: no-store`, todo se descarga y se parsea en
  cada recarga.
- `read_runs(500)` tarda 25 ms porque hace `SELECT *` y arrastra `task` y `response` (promedio
  6,9 KB, máximo 279 KB por run): ~3,4 MB leídos para mostrar previews.
- Las consultas de Overview, Trace y Activity tardan menos de 1 ms con el volumen actual.

Presupuestos (local, un usuario). Se miden de punta a punta, no en proceso:

- **Endpoints:** un harness que haga peticiones HTTP reales al servidor, con SQLite, serialización
  y red local incluidas, sobre la base actual y una sintética de 10×; se reporta p95.
- **INP:** medido en el navegador (Performance panel o `PerformanceObserver` de tipo `event`).
- **Cambio de un agente visible:** peor caso = intervalo de sondeo + debounce máximo + petición +
  render. Con sondeo de 2 s y debounce de 300 ms, el resto tiene ~700 ms. Se valida con una prueba
  que escribe desde otro proceso y mide cuándo cambia la vista.

| Operación | Objetivo |
|---|---|
| HTML inicial | < 150 KB, sin datos de runs embebidos |
| Endpoint JSON | p95 < 50 ms |
| Hover, selección, expandir | feedback < 100 ms, sin ida al servidor |
| INP p75 | ≤ 200 ms |
| Cambio hecho por un agente, visible en el dashboard | < 3 s |

### 19.4 Optimizaciones

| Id | Cambio | Efecto |
|---|---|---|
| O1 | Listados con columnas explícitas, sin `task` ni `response` | Elimina ~3,4 MB de lectura por carga |
| O2 | Runs paginados por API (50 por página) en vez de 500 embebidos, con orden estable por instante UTC (`ORDER BY julianday(ts) DESC, id DESC`) y cursor compuesto (instante, `id`). Ordenar `ts` como texto no sirve: mezcla offsets (§20.2). Un cursor solo por `id` saltaría o duplicaría filas: los runs importados no se insertan en orden temporal. Si la medición lo pide, índice de expresión sobre `julianday(ts)` o `ts` normalizado al importar (§20.4) | HTML inicial ~215 KB más liviano; DOM chico |
| O3 | JS y CSS del dashboard servidos como `/static/` con hash de contenido y caché; el HTML sigue `no-store` | El navegador no re-descarga ~130 KB en cada recarga. El patrón ya existe en `/static/docs-theme.*` |
| O4 | Detección de cambios entre procesos: un único hilo del servidor, con una conexión SQLite dedicada y persistente y sin transacciones abiertas, consulta `PRAGMA data_version` cada 1–2 s, compara con el valor anterior y publica un `db_changed` genérico por SSE. Ante un error reconecta y toma una nueva línea base. No se sondea por pestaña | Hoy el bus SSE es intra-proceso: lo que hacen los agentes vía MCP (otro proceso) no llega en vivo al dashboard. El contador es local a la conexión (reabrirla en cada sondeo invalida la comparación) y no dice qué proyecto ni qué tabla cambió; por eso el cliente refresca la vista visible |
| O5 | El cliente refresca solo la vista visible, con debounce, al recibir `db_changed` | Evita recargar la página completa |
| O6 | Índices para Activity (`steps.started_at`, `steps.completed_at`, `alignments.ts`) solo si una medición lo pide | Con el volumen actual no hace falta |
| O7 | ChromaDB perezosa y aislada; si falla, estado "degradado" | Overview y Trace no dependen de ella |

### 19.5 Uso de recursos

- **Servidor:** un proceso local, SQLite en WAL con `busy_timeout` de 5 s (ya configurado). Cada
  pestaña con SSE retiene un hilo; aceptable para un usuario.
- **Memoria:** O1 elimina el pico transitorio de varios MB por carga. ChromaDB es lo más pesado y
  queda fuera del camino principal.
- **CPU:** la consulta de `data_version` y las proyecciones son despreciables al volumen actual.
- **Navegador:** sin dependencias nuevas; DOM acotado a ~50 filas por lista.
- **Escala:** con 10× los datos actuales, las consultas deberían seguir en milisegundos con los
  índices existentes (a confirmar con una base sintética en D3); la paginación evita que el HTML
  crezca con el historial.

### 19.6 UX frente al fin de la vista

| Elemento | Evaluación con datos reales | Ajuste |
|---|---|---|
| Overview | Tres de las seis métricas originales serían siempre 0 o ~100 % | Reemplazadas por métricas con señal (§6.1) |
| Trace de run | En el 98 % de los runs no hay routing ni egress | Trace de paso como primario; run importado con estado explícito (§6.2). Ajustado por §20: notas y commits citados como evidencia principal |
| Lente de gobernanza | Egress vacío; denegaciones MCP con datos | Empezar por denegaciones MCP; sumar egress cuando tenga filas |
| Activity | `mcp_invocations` da actividad continua de los agentes | Fuente incluida en §10.4, sin las lecturas para no generar ruido; filtrada por proyecto, no por paso (§6.2). Timestamps normalizados a UTC (§20.2) |
| Tiempo real | Los cambios de los agentes no llegan hoy | O4 y O5 |
| Commits | Ningún commit vinculado a un paso | Mostrar la sugerencia de `suggest_step_commits` como relación recomendada (trazo punteado, §4.4) solo cuando haya candidatos. No es cobertura general: solo propone commits con referencia explícita a un paso o ticket compartido, y solo para pasos abiertos |

### 19.7 Fin principal

Por todo lo anterior, el fin principal de la vista es el que fija §1: **hacer visible el trabajo de
los agentes contra el plan y su evidencia**. Responde, en este orden:

1. ¿Qué está haciendo cada agente en el proyecto ahora?
2. ¿Está alineado con el plan (contexto y paso)?
3. ¿Qué evidencia lo respalda (notas, commits citados y verificados, alineamientos y runs vinculados)?
4. ¿Cuánto costó?
5. ¿Qué se denegó o falló, y por qué?

Routing y egress siguen dentro del diseño como ruta secundaria, activada por los datos.

---

## 20. Alineamiento con el uso real

Análisis a nivel de datos sobre la base local de un usuario, en solo lectura. Los proyectos se
anonimizan como P1…P7; solo se reportan conteos.

### 20.0 Método

- **Instantánea:** 2026-10-02T23:50:15Z, base abierta con `sqlite3` en modo `?mode=ro`. Los
  desgloses de `mcp_invocations` se tomaron minutos antes, sobre 656 filas; a la hora de la
  instantánea había 659 y las proporciones no cambian.
- **Timestamps:** se parsean con su offset y se convierten a UTC; los valores sin zona se interpretan como UTC antes de comparar o restar.
- **Referencias en notas** (pasos `completed`):
  - candidato a SHA: token hexadecimal de 7 a 40 caracteres, no pegado a otros caracteres
    alfanuméricos, con al menos un dígito y una letra `a-f`; se pasa a minúsculas y se deduplica
    por paso;
  - SHA verificado: el token es prefijo del SHA de algún commit importado
    (`runs.session_id` = `git::<alias>::<sha>`);
  - PR: `PR`, espacios opcionales, `#` opcional y dígitos, sin distinguir mayúsculas;
  - mención de tests: palabra `pytest`, `test`, `tests` o `passed`.
- **Evidencia por FK:** al menos un alineamiento, tool call o run con `step_id` del paso.

### 20.1 Cómo se usa hoy

| Dimensión | Dato | Lectura |
|---|---|---|
| Proyectos | 7 con contextos, 13 con runs; P1 concentra 40 de 63 contextos | El tracking se usa en serio en pocos proyectos; el resto solo aporta commits importados (86 runs sin ningún contexto). |
| Contextos | 53 completados, 6 activos, 4 programados; P1 tiene 3 activos a la vez | La advertencia de varios contextos activos es frecuente, no excepcional. |
| Pasos | 307 completados, 4 en curso, 32 pendientes, 30 omitidos (20 con la nota "no es un skip real") | Plan de trabajo real y sostenido; hay ruido de calidad en los omitidos. |
| Ritmo | Pasos completados por semana: 47, 77 y 65 en las tres últimas semanas con datos | Uso creciente. |
| MCP | 659 invocaciones en 6 días hábiles (~110/día); p50 1 ms, p95 8 ms; 98 % con perfil `workflow_operator` | El MCP es el canal principal de trabajo y es rápido. |
| Agentes (MCP) | Claude Code hace mutaciones y transiciones; Codex sobre todo lecturas y alineamientos | Roles distintos y visibles en los datos. |
| Gobernanza | 20 denegadas: 17 `project_out_of_scope`, 3 `capability_denied`; 6 errores `invalid_arguments` | Señal real y accionable. |
| Costo | 223 runs con costo: Claude Code ≈ USD 2 047 en 92 sesiones; Codex ≈ USD 274 en 114 | El costo es una señal fuerte, pero solo 65 runs están vinculados a un paso. |

### 20.2 Calidad de la evidencia

| Hallazgo | Dato | Consecuencia para la vista |
|---|---|---|
| Duración de pasos sin significado | Mediana 0,8 min; 153 de 295 (52 %) duran menos de 1 min; 19 con `started_at = completed_at`; 12 completados sin `started_at` | Los pasos se activan y cierran en lote, a menudo después del trabajo. No mostrar duraciones de pasos como métrica. |
| Evidencia por FK escasa | 177 de 307 pasos completados (58 %) no tienen alineamiento, tool call ni run | Un Trace de paso basado solo en FK quedaría vacío en la mayoría de los casos. |
| La evidencia real está en las notas | 302 de 307 tienen notas (mediana 349 caracteres). 92 pasos citan candidatos a SHA (155 únicos por paso), de los cuales 74 se verifican contra commits importados, en 48 pasos; 26 pasos citan PRs y 122 mencionan tests. De los 177 pasos sin evidencia por FK, 19 tienen al menos un SHA verificado | Las notas son la fuente principal de evidencia. Los SHAs citados permiten vincular commits de forma verificable en una parte de los pasos; el resto de la evidencia es texto. |
| Alineamientos fuera de la ventana del paso | 64 de 195 (33 %) son anteriores al `started_at` del paso | Asociar por ventana de tiempo es poco confiable. |
| Tool calls marginales | 29 en total, con nombres libres; `record_tool_call` se invocó 5 veces por MCP | No es una fuente de evidencia confiable. |
| Identidad de agentes inconsistente | En `alignments.agent`: `copilot`, `copilot-cli`, `github-copilot`, `claude`, `claude-code` | "¿Qué hace cada agente?" requiere normalizar identidades. |
| Timestamps con offsets mezclados | En `runs.ts` conviven 238 valores en UTC, 553 con offset `-03:00` y 367 con `-04:00` (commits importados con la zona del committer, `%ci`); además hay 3 `steps.started_at` sin zona | Ordenar `ts` como texto mezcla offsets: comparado con el orden por instante real (`julianday(ts)`), 573 de 1158 runs quedan en otra posición. Afecta también al dashboard actual, porque `read_runs` ordena por `ts` como texto. Las proyecciones deben ordenar, paginar y comparar por instante UTC. |

### 20.3 Alineamiento de la especificación con el uso

| Elemento | ¿Alineado? | Ajuste |
|---|---|---|
| Fin principal (§1) | Sí: el uso real es seguimiento del trabajo de agentes | La evidencia principal son las notas y los commits citados, no solo las FK. |
| Trace de paso (§6.2) | Parcial | Mostrar las notas del paso como primer nivel, extraer SHAs y PRs citados y vincular los SHAs que existan en `runs` de git como "referencia verificada". Las invocaciones MCP pasan a la Activity del proyecto, no al Trace del paso. |
| Overview (§6.1) | Parcial | Agregar una tarjeta "Salud del tracking" (varios contextos activos, omitidos que no son skip real, completados sin inicio). No mostrar duraciones. |
| Agente como dimensión | No | Normalizar `alignments.agent` y `mcp_invocations.client_surface` a un catálogo común de agentes en la proyección. |
| Costo | Sí | Mostrarlo por proyecto y período; por contexto o paso solo cuando haya runs vinculados, indicando la cobertura. |
| Routing y egress (secundarios) | Sí | Sin cambios: siguen sin datos. |

### 20.4 Recomendaciones fuera del dashboard

D3 normaliza agentes y timestamps solo dentro de la proyección, para mostrar los datos; no modifica
los datos de origen. Las recomendaciones siguientes corrigen el origen y van cada una en su propio
contexto o PR:

1. Registrar `step_id` y `context_id` en `mcp_invocations`. Es viable con columnas nullable, una
   migración y cambios en los dos `INSERT` de auditoría, pero los argumentos hoy solo se guardan
   hasheados y no toda invocación los trae. Para que la relación sea confirmada, los IDs se guardan
   solo después de validarlos contra la relación paso → contexto, distinguiendo "declarado" de
   "verificado", y sin FK para invocaciones denegadas, inválidas o no verificadas. Retención y
   privacidad se definen en una revisión de RFC-008.
2. Normalizar la identidad del agente al registrar alineamientos.
3. Normalizar a UTC los timestamps de los commits importados y corregir el orden de `read_runs`
   (hoy por `ts` como texto).
4. Reclasificar los 20 omitidos que no son skip real (ya previsto en el contexto de integridad del
   tracking).
5. Atribución explícita sesión → paso: hoy los watchers asumen el contexto activo más reciente del
   proyecto (`get_active_step_id`), lo que falla con varias unidades en paralelo (§24.6). El agente
   debería declarar su paso (por ejemplo, registrando el identificador de su sesión en
   `confirm_alignment` o en una variable de entorno que el watcher lea), y el watcher usar esa
   declaración antes que el contexto más reciente.

---

## 21. Workspace como grafo: evaluación con los elementos predominantes

Medido el 2026-10-02 en solo lectura sobre la base local, con la metodología de §20.0. Validado por
Codex y Copilot CLI (dos auditores, solo lectura). Las cifras de §20 cuentan solo pasos completados;
las de esta sección cuentan pasos en todos los estados.

### 21.1 Elementos predominantes

| Elemento | Cantidad | Cómo se representa |
|---|---|---|
| Pasos | 374 | Nodo principal (familia Work). |
| Alineamientos | 197 | Atributo del paso: contador y marca de desviación. Son 1 a 6 por paso y casi siempre del mismo agente; el detalle queda en el Inspector. |
| Citas de commits verificados | 114 vínculos paso → commit en 67 pasos; 77 commits distintos (86 si se cuentan por contexto) | Nodo commit (familia Execution) y relación de "referencia verificada". **25 commits los citan dos o más pasos**: son las únicas relaciones que hacen que un contexto no sea un árbol. |
| Agentes | Carril principal: claude 151 pasos, codex 82, copilot 22, otros 6, sin agente 113. 19 pasos con dos o más agentes | Carril (fila), no nodo. |
| Runs vinculados | 66 | Atributo del paso (contador y costo); nodo solo en el Inspector. |
| Tool calls | 29 | Atributo del paso. |
| Relaciones entre contextos | 1 por `contexts.parent_step_id`; además 8 commits citados desde más de un contexto (§22.1) | El mapa de un contexto no las dibuja; las cubre la constelación (§22). |

**Regla de agente (reproducible y testeable):**

- Normalización previa: recortar espacios y pasar a minúsculas.
- Catálogo: `claude` (`claude`, `claude-code`, `claude_code`), `codex` (`codex`, `codex_cli`),
  `copilot` (`copilot`, `copilot-cli`, `github-copilot`) y `otros` (`deepseek`, `openai`, `gemini`).
- Agente principal del paso: `steps.provider` si está en el catálogo; si no, el agente con más
  alineamientos en el paso; si empatan, el del primer alineamiento en orden estable
  (`alignments.ts`, luego `alignments.id`); si no hay ninguno, carril `sin agente`.
- Agentes secundarios: los demás agentes del catálogo con alineamientos en el paso.
- Valores de `steps.provider` fuera del catálogo se ignoran (13 filas, varias dañadas por un bug
  conocido de `create-context`; su reparación va por separado).

### 21.2 Tamaño y estructura por contexto

- Nodos posibles por contexto: mínimo 2, mediana 7, p90 16, máximo 64; 3 de 63 superan 40.
- Carriles de agente por contexto, **sin contar el carril `sin agente`**: 17 contextos con ninguno,
  31 con uno, 11 con dos y 4 con tres o más.
- **Solo 19 de 63 contextos (30 %) tienen estructura que el grafo pueda mostrar**: 15 con dos o más
  carriles de agente, 7 con al menos un commit compartido y 3 en ambos grupos (15 + 7 − 3 = 19).
  Entre los contextos activos (`contexts.status = 'active'`), 4 de 7.
- Máximos por contexto: 22 commits verificados y 23 citas paso → commit.

Conclusiones:

1. Entre contextos solo hay 1 enlace explícito, pero 8 commits compartidos conectan 7 contextos en
   2 grupos (§22.1). Esas relaciones no entran en el mapa de un contexto; las trata la constelación
   (§22).
2. En un contexto de un solo carril y sin commits compartidos, el grafo es una lista ordenada con
   decoración: no aporta.
3. El grafo aporta en el 30 % de contextos con varios agentes o evidencia compartida. Muestra
   evidencia citada en común y distribución por agente, **no causalidad entre pasos**.

### 21.3 Propuesta: mapa del contexto

Pregunta que responde: **¿quién hizo qué en este contexto y qué pasos comparten evidencia?**

**Cuándo se muestra.** Por defecto solo en contextos con dos o más carriles de agente o al menos un
commit compartido. En el resto, la vista abre la lista de pasos con un aviso ("este contexto no
tiene relaciones que el mapa agregue") y un botón para ver el mapa igual.

```text
             paso 1    paso 2    paso 3    paso 4    paso 5      ← orden del plan (x)
claude   ─── [P1] ──────────────── [P3] ──────────────────
codex    ───────────── [P2] ────────┆─────── [P4] ────────        ← carril por agente (y)
sin agente ────────────────────────────────────────── [P5]
                  │         │          ╲     ╱
commits        ◇ 7d03e1b  ◇ a41f9c2   ◇ 5be88d0 (2 pasos)          ← franja de commits
```

- **Alcance:** solo pasos del contexto. Si un commit también lo citan pasos de otros contextos, esas
  citas no se dibujan; el Inspector del commit las lista.
- **Orden de columnas:** `order_idx` y luego `steps.id`, porque `order_idx` hoy no es único dentro
  de un contexto (problema de integridad ya registrado en el tracking).
- **Disposición determinista, sin simulación de fuerzas:** x = orden del paso; y = carril del agente
  principal; carril `sin agente` siempre al final. Los commits van en una franja inferior, bajo el
  primer paso que los cita; si coinciden en columna, se apilan por SHA completo ascendente.
- **Orden de dibujo de aristas** (todos los casos): commits en orden de colocación (columna, luego
  posición en la pila) y, dentro de cada commit, pasos citantes por `order_idx` y luego `steps.id`.
- **Relaciones y su trazo** (amplía §4.4):
  - FK real (paso → run, alineamiento): sólido.
  - **Referencia verificada** (paso cita un SHA que existe como commit importado): sólido con
    marca ◇ en el extremo. No es una FK; el rombo la distingue.
  - Inferido: discontinuo. Recomendado: punteado.
- **Ruteo de commits compartidos:** las aristas bajan verticalmente desde el paso hasta un canal
  horizontal bajo los carriles y desde ahí al commit, sin cruzar nodos de paso. Sin foco se dibujan
  finas; al seleccionar un paso o un commit se resaltan las suyas.
- **Segundo agente:** si su carril existe en el contexto, una marca fantasma punteada en ese carril y
  la misma columna; si no existe, un badge con la inicial del agente en el nodo. Nunca cambia la
  posición del paso.
- **Atributos en el nodo:** símbolo de estado (✓ ● ○ ⤼), contador de alineamientos, marca de
  desviación, runs y costo.
- **Presupuesto visual** (se mide por separado, no como un total de "nodos posibles"), con una
  salida determinista para cada límite:

  | Límite | Si se excede |
  |---|---|
  | 30 pasos visibles | Se agrupan rangos maximales de pasos consecutivos completados, sin desviaciones y sin commits compartidos. Si aun así se excede, la vista muestra una ventana de 30 columnas con desplazamiento por rango de pasos. |
  | 20 commits | Los commits citados por un solo paso dejan de ser nodos y pasan a un contador ◇n en el paso; los compartidos se dibujan salvo el caso extremo de abajo. Hoy afecta a 1 contexto (22 commits). |
  | 60 aristas | Misma regla que la de commits: solo se dibujan las aristas hacia commits compartidos, salvo el caso extremo de abajo. |
  | 5 carriles | No puede excederse: el catálogo tiene 4 agentes más `sin agente`. |

  **Caso extremo (excepción prioritaria sobre la tabla):** si, ya dentro de la ventana de 30
  columnas, los commits compartidos superan 20 o sus aristas superan 60, se aplica en este orden:

  1. Commits: se ordenan por cantidad de pasos citantes (descendente) y, en empate, por el
     orden de columna del primer paso que los cita y, si persiste, por SHA completo ascendente; se
     dibujan los primeros 20. El resto se resume en un
     nodo "+n commits compartidos" que abre la lista sincronizada filtrada.
  2. Aristas: se recorren los commits dibujados en ese mismo orden y, dentro de cada uno, sus pasos
     citantes por `order_idx` y luego por `steps.id`; se dibujan las primeras 60. Las que quedan se resumen como un
     contador "+k citas" en el nodo del commit.

  Así nunca se superan los dos topes, y el orden es determinista. Hoy el máximo por contexto es
  8 commits compartidos y 17 aristas, lejos de ambos límites.
- **Interacción:** seleccionar atenúa lo no relacionado (por clases CSS, sin regenerar el SVG) y
  abre el Inspector; desde un paso se pasa a su Trace.

### 21.4 Contrato de datos

`GET /api/v1/projects/{p}/contexts/{id}/map`, bajo las protecciones de D0. El DTO **es un
ProjectGraph (§10.1) del contexto más una extensión `map`**:

```json
{
  "nodes": [
    {"id": "step:12", "kind": "step", "label": "Paso 3", "state": "completed",
     "attrs": {"idx": 3, "lane": "claude", "secondary": ["codex"], "alignments": 2,
               "deviations": 0, "runs": 1, "cost_usd": 3.92}},
    {"id": "commit:5be88d0c41a7e9f2b3c4d5e6f708192a3b4c5d6e", "kind": "commit", "label": "5be88d0"}
  ],
  "edges": [
    {"source": "step:12", "target": "commit:5be88d0c41a7e9f2b3c4d5e6f708192a3b4c5d6e", "relation_type": "cites",
     "origin": "verified_reference", "confidence": 1.0, "evidence_ref": "steps.notes"}
  ],
  "metadata": {"project": "mi-proyecto", "context_id": 21, "generated_at": "…"},
  "map": {
    "lanes": ["claude", "codex", "sin agente"],
    "groups": [{"id": "group:3-11", "from_idx": 3, "to_idx": 11, "count": 9,
                "members": ["step:21", "step:22", "step:23", "step:24", "step:25",
                            "step:26", "step:27", "step:28", "step:29"],
                "lane": "claude", "lanes": {"claude": 6, "codex": 3}, "single_commits": 4}],
    "eligible": true
  }
}
```

- `nodes`, `edges` y `metadata` tienen el formato de ProjectGraph; los ids de nodo (`step:<id>`,
  `commit:<sha>`) son los mismos en todas las representaciones y en `sel=` (§23.3). Lo propio del
  mapa (carriles, grupos, elegibilidad) va solo dentro de `map`, y los atributos del paso dentro de
  `attrs`.
- El identificador del commit es el SHA completo; `label` (7 caracteres) es solo visual, así que
  dos commits con el mismo prefijo no se fusionan. Un token de las notas que es prefijo de más de un
  commit no se verifica (hoy: ninguno).
- Grupo: rango maximal de pasos consecutivos (por `order_idx`) que cumplen la regla de agrupamiento;
  se dibuja en el carril con más pasos del grupo (empate: orden del catálogo), con el desglose por
  carril en su etiqueta. Se expande en el cliente con `members`, sin otra petición.
- Sin texto de notas, títulos de commits ni contenido de runs: el detalle se pide al Inspector al
  seleccionar.

### 21.5 Qué no se dibuja

- MCP: no se puede vincular a un paso (§20.4).
- Grafo entre contextos o de todo el proyecto: lo cubre §22.
- Alineamientos, tool calls y runs como nodos permanentes.
- Etiquetas en todas las relaciones (solo al pasar el mouse o seleccionar, §4.4).

### 21.6 Lugar en el plan y criterio de permanencia

Fase **D6 (experimental)**, después de D3, porque reutiliza sus proyecciones (notas, SHAs
verificados, agentes normalizados). Según §23.2, el mapa es una representación de los pasos dentro
de Trabajo, activable desde Labs, no una entrada de navegación.

**Aceptación de D6:**

- Tests de la proyección del mapa sobre una base sintética: regla de agente, carriles, commits
  compartidos, agrupamiento y elegibilidad.
- Cada nodo con foco propio, rol y nombre accesible (paso, estado, agentes, alineamientos,
  desviación, commits citados); orden de tabulación por columna y carril; flechas recorren pasos.
- **Lista equivalente sincronizada** con la selección del mapa, que también sirve de alternativa
  para lectores de pantalla.
- Contraste AA en todos los temas, zoom al 200 % sin pérdida y `prefers-reduced-motion`.
- Selección con feedback < 100 ms en el contexto más grande.

**Criterio de permanencia (medible):**

- Tareas: "¿qué otro paso citó este commit?" y "¿qué agente hizo este paso y quién más participó?".
- Muestra: al menos 10 sesiones de prueba, solo sobre contextos elegibles (≥ 2 carriles o ≥ 1
  commit compartido), comparando mapa contra Contextos + Trace.
- Se mantiene si la mediana de tiempo baja al menos 20 % sin bajar el acierto. Si no, se retira o
  queda solo como enlace desde contextos elegibles.

---

## 22. Vista de constelación: grafo global del proyecto

Evaluación de una vista tipo "constelación": clusters con un nodo central grande, satélites, puentes
entre clusters y color por grupo, el estilo clásico de Gephi o del graph view de Obsidian. Medido el
2026-10-02 en solo lectura sobre la base local (metodología de §20.0 y regla de agente de §21.1),
con `networkx` instalado fuera del proyecto solo para el análisis.

### 22.1 Estructura real según qué se dibuje como nodo

| Variante | Nodos | Aristas | Componentes | Componente mayor | Hubs principales | Comunidades (Louvain) |
|---|---|---|---|---|---|---|
| A · contextos + pasos + commits | 514 | 489 | 57 | 161 nodos | contextos (grado 47, 33, 31) | 9 en la mayor, modularidad 0,70 |
| B · A + agentes como nodos | 518 | 769 | 16 | 437 nodos | **agente claude (164) y codex (86)** | 25, modularidad 0,63 |
| C · B + proyectos como nodos | 525 | 832 | 2 | 494 nodos | agentes, contextos y un proyecto (40) | 19, modularidad 0,63 |

Lectura:

1. **Los commits sí unen contextos.** 8 commits están citados desde más de un contexto (7 desde dos,
   1 desde tres). Conectan 7 contextos en 2 grupos (de 3 y de 4 contextos). A eso se suma el único
   enlace `parent_step_id`, entre dos contextos del mismo proyecto. Esto corrige la conclusión de
   §21.2, que solo miraba `parent_step_id`.
2. **Los puentes cruzan proyectos.** 6 de los 8 commits compartidos los citan contextos de proyectos
   distintos; el grupo de 4 contextos abarca 3 proyectos. Una constelación limitada a un proyecto
   ocultaría la mayoría de los puentes (ver §22.4).
3. **Con agentes como nodos (B, C) la imagen se parece a la referencia, pero miente.** El hub de
   claude conecta el 44 % de los pasos y el de codex el 23 %. Los "soles" grandes serían agentes y
   solo dirían "este agente trabajó mucho", algo que un número dice mejor. Es el problema clásico de
   los supernodos: dominan la disposición y aplastan la estructura útil.
4. **Sin agentes (A) la estructura es real y modular** (modularidad 0,70): cada contexto es un
   cluster natural con sus pasos como satélites, y los commits compartidos son los puentes. Pero 54
   de 57 componentes son contextos aislados.

### 22.2 Técnicas de plataformas y librerías conocidas

Características generales de cada herramienta, según su documentación pública; conviene
verificarlas antes de elegir una.

| Herramienta | Disposición | Render | Técnica que aporta |
|---|---|---|---|
| Gephi (ForceAtlas2) | Fuerzas continuas; modo LinLog separa comunidades | Escritorio | Color por comunidad (Louvain/modularidad) y tamaño por grado: es el origen visual de la referencia |
| Obsidian (graph view) | No documentada públicamente (aplicación cerrada; se percibe como una disposición por fuerzas) | No documentado públicamente | **Grafo local**: vecindario del nodo activo con profundidad ajustable; grupos de color por consulta |
| Sigma.js + graphology | ForceAtlas2 en un Web Worker | WebGL | Miles de nodos fluidos; comunidades con graphology; reducers para atenuar o resaltar sin recalcular |
| Cytoscape.js | fCoSE, Cola, CoSE-Bilkent | Canvas | **Nodos compuestos**: un contexto como contenedor de sus pasos; disposición que respeta esos grupos |
| d3-force | Fuerzas configurables (carga, enlace, colisión, gravedad por cluster) | SVG o Canvas, a elección | Simulación chica y controlable; fuerzas hacia el centro de cada cluster |
| vis-network | Barnes-Hut | Canvas | **API de clustering**: colapsar o expandir grupos por propiedad |
| AntV G6 | Varias, con combos | Canvas o WebGL | Combos (clusters contenedores) y nivel de detalle por zoom |
| Neo4j Bloom, Kumu, Linkurious | Fuerzas con expansión a pedido | Web | Exploración que empieza por una búsqueda, "expandir vecinos", reglas de estilo por propiedad (lentes) |
| Cosmograph / cosmos.gl | Fuerzas calculadas en GPU | WebGL | Cientos de miles de nodos: fuera de escala para este caso |
| Service maps (Datadog, Honeycomb) | Hub-and-spoke acotado | Web | Grafo chico, con estado de salud en color y foco en una pregunta |
| Apache ECharts (serie graph) | Fuerzas o circular | Canvas o SVG | Categorías con color, fuerza y énfasis del vecindario al pasar el mouse |

Técnicas transversales:

- **Detección de comunidades** (Louvain, Leiden) para color y agrupamiento.
- **Gravedad por cluster** o nodos compuestos, para que cada grupo quede junto.
- **Supresión de supernodos**: excluir o atenuar nodos de grado muy alto; filtrado por grado o
  k-core y muestreo de aristas cuando no alcanza.
- **Disposición distinta para componentes aislados**: radial, en arco o en grilla, en vez de forzar
  una simulación sobre un grafo mayormente desconectado.
- **Grafo local o ego network**: mostrar el vecindario de lo seleccionado, con profundidad.
- **Colapsar y expandir** clusters.
- **Nivel de detalle y zoom semántico**: etiquetas solo al acercarse; minimapa solo con grafos grandes.
- **Agrupamiento de aristas** (edge bundling) para reducir cruces.
- **Disposición estable**: semilla fija o posiciones precalculadas, para que el mapa no se reacomode
  en cada carga.

### 22.3 Rendimiento sin librerías

Simulación de fuerzas ingenua (O(n²) por iteración) en JS, 300 iteraciones, medida con Node 20:

| Nodos | Tiempo |
|---|---|
| 514 (volumen actual) | 0,37 s |
| 1 028 (2×) | 1,3 s |
| 5 140 (10×) | ~33 s (estimado) |

La re-ejecución de Codex dio 0,40 s, 0,86 s y ~21 s: el orden de magnitud se mantiene entre
máquinas. Es una medición **indicativa del cálculo**, no de la experiencia: no incluye navegador,
render en Canvas, detección de clics, capa accesible ni serialización. D7 debe medir en el
navegador, en frío y en caliente, global y local, con varias corridas, percentiles e INP, declarando
hardware y versiones.

Con el volumen actual alcanza con JS sin librerías. A 10× hace falta Barnes-Hut (árbol
cuaternario), una librería o precalcular en el servidor.

### 22.4 Propuesta: constelación del proyecto

Pregunta que responde: **¿cómo se agrupa el trabajo del proyecto y qué contextos comparten
evidencia?**

| Dimensión visual | Concepto | Motivo |
|---|---|---|
| Cluster (sol) | Contexto; tamaño por cantidad de pasos | Es la comunidad natural (modularidad 0,70) |
| Satélites | Pasos del contexto | Relación FK `steps.context_id` |
| Puentes | Commits citados por más de un contexto (referencia verificada, §4.4); grosor según la cantidad de commits que comparten los dos contextos | Es la relación real entre clusters |
| Color | Lente elegible: proyecto o agente dominante del contexto | Cambia el énfasis, no la estructura (§4.3: siempre con texto o icono). El estado no es una lente de color, para no duplicar la codificación del brillo |
| Brillo | Solo estado: en curso, seleccionado, con desviación | §4.6: glow por estado, no por tipo |
| Agentes | Lente de color, no nodo | Evita los supernodos de §22.1 |

Alcance y modos:

- **Alcance: el proyecto seleccionado** (§15 deja fuera la vista global multi-proyecto). Los puentes
  hacia contextos de otros proyectos se dibujan como **nodos portal**: un nodo pequeño con el alias
  del otro proyecto y la cantidad de commits compartidos, que abre el Inspector con las referencias
  sin desplegar ese proyecto. Así no se pierden los 6 puentes entre proyectos. Ver varios proyectos
  a la vez sería una excepción a §15 que decide el usuario.
- **Global (del proyecto):** los contextos conectados por commits, en el centro; los aislados, en
  una grilla o arco al costado y fuera de la simulación. Por defecto solo los contextos activos y
  los conectados a ellos, para respetar §4.1.
- **Local:** al seleccionar un contexto, su vecindario a profundidad 1 o 2. Que sea el modo más útil
  es una **hipótesis** tomada de Obsidian; se valida con la medición de §22.5.
- Desde un contexto se pasa a su mapa (§21) o a su Trace (§6.2).

Disposición: fuerzas con gravedad por cluster y semilla fija; posiciones calculadas en el servidor
en Python puro (sin dependencias nuevas); render en Canvas 2D con una capa accesible equivalente
(lista de clusters y puentes) sincronizada con la selección.

Contrato: igual que el mapa (§21.4), el DTO es un ProjectGraph del proyecto (contextos, pasos y
commits como nodos; `contains` y `cites` como aristas; los portales como nodos `portal:<alias>`)
más una extensión `constellation` con posiciones, generación de caché y lente.

Caché de posiciones: `PRAGMA data_version` es local a una conexión, así que no sirve como versión
global. El hilo de O4 (§19.4), con su conexión lectora dedicada y persistente, incrementa un
contador de generación en memoria cada vez que detecta un cambio; las escrituras hechas dentro del
proceso también lo incrementan. La clave de caché es (proyecto, generación, versión del algoritmo de
disposición).

Atractivo visual sin movimiento decorativo. No se adopta el brillo permanente, las partículas, los
nodos flotando ni los colores por tipo sin texto de la referencia, porque contradicen §4.2 y §4.6.
Para conservar su impacto:

- brillo **estático** proporcional a la actividad reciente del contexto, sin bucle;
- un **pulso único** cuando cambia un estado real (paso que se completa, desviación nueva);
- un **flujo breve** sobre el puente solo cuando aparece un commit compartido nuevo;
- animación de cámara solo como respuesta a una acción del usuario (seleccionar, expandir);
- pulido estático: gradiente sutil en los clusters, halo suave en el seleccionado y la paleta de
  familias de §4.3, en tema oscuro y claro.

Todo respeta `prefers-reduced-motion`.

### 22.5 Lugar en el plan

Fase **D7 (experimental)**, después de D6: reutiliza la proyección de commits verificados y la
regla de agentes. Según §23.2, la constelación es una representación de los contextos dentro de
Trabajo, activable desde Labs.

**Aceptación de D7:**

- Tests de la proyección sobre una base sintética: clusters, puentes con peso, nodos portal y
  contextos aislados.
- Posiciones deterministas: misma semilla y mismos datos dan las mismas coordenadas.
- Invalidación de caché: un cambio desde otro proceso cambia la generación y fuerza el recálculo.
- Canvas y lista accesible sincronizados; teclado por cluster y por puente; contraste AA en todos
  los temas; `prefers-reduced-motion`.
- Presupuesto de rendimiento medido en navegador (§22.3).

**Criterio de permanencia:** tarea "¿qué contextos comparten evidencia con este?", al menos 10
sesiones, comparando contra Contextos + Trace. Se mantiene si la mediana de tiempo baja al menos
20 % **y** la tasa de acierto (contextos correctos encontrados) es igual o mayor. El uso de los
modos global y local se mide por separado. Si no se cumple, queda solo el modo local como panel del
Inspector.

---

## 23. Arquitectura de experiencia: diseño escalable y mantenible

Las secciones anteriores agregaron superficies una por una, cada una para responder una pregunta:
Overview, Trace, Contextos, Runs, Gobernanza, Mapa, Constelación, Inspector y Activity. Son nueve.
Sumadas sin un modelo común, la navegación se fragmenta y cada vista nueva cuesta más que la
anterior. Esta sección ordena todo bajo un modelo de objetos, una sola plantilla de página, un
sistema de diseño y una estructura de código que crezca sin reescrituras.

### 23.1 Modelo de objetos

Se diseña a partir de los objetos del dominio, no de las vistas. Cada objeto tiene siempre las
mismas tres caras: una **fila** en las listas, un **panel** en el Inspector y un **detalle**. Todo
objeto tiene URL propia: contexto y paso como página; commit, run y decisión de acceso como
selección que abre su panel (§23.3). El **proyecto no es un objeto de esta tabla: es el scope** de toda la pantalla (selector en
el header) y su resumen es Inicio.

| Objeto | Familia (§4.3) | Contiene o se relaciona con | Detalle |
|---|---|---|---|
| Contexto | Knowledge | Pasos; otros contextos por commits compartidos | Página del contexto |
| Paso | Work | Alineamientos, tool calls, runs, commits citados | Trace del paso |
| Commit | Execution | Pasos que lo citan | Panel del Inspector |
| Run | Execution | Paso, routing, egress | Panel del Inspector |
| Agente | atributo (lente) | Pasos, alineamientos, invocaciones MCP | Filtro y lente, no página |
| Decisión de acceso | Governance | Invocación MCP o run | Panel del Inspector |

Regla de escala: **un objeto nuevo** (por ejemplo, PR o resultado de tests) se agrega definiendo su
fila, su panel y sus relaciones; no crea una sección nueva en la navegación.

### 23.2 Representaciones, no destinos

Mapa, Constelación y Activity no son lugares: son **formas de ver** una colección de objetos. Se
eligen con **pestañas** dentro del objeto que las contiene, siempre visibles para que el grafo esté a
un clic: en Trabajo, "Contextos | ◇ Grafo"; dentro de un contexto, "Pasos | ◇ Mapa". Inicio muestra
además una vista previa de la constelación que abre la pestaña Grafo. (Una primera versión usaba un
selector "Ver como" y el grafo quedaba poco visible; se cambió a pestañas por pedido del usuario.)

| Colección | Representación por defecto | Alternativas |
|---|---|---|
| Contextos del proyecto | Lista | Constelación (§22) |
| Pasos de un contexto | Lista | Mapa (§21), solo si el contexto es elegible |
| Evidencia de un paso | Trace (§6.2) | — |
| Eventos | Activity (barra inferior) | Línea de tiempo completa |

- La **lista es siempre la representación por defecto** y la equivalente accesible.
- La selección **se conserva** al cambiar de representación: el paso seleccionado en la lista sigue
  seleccionado en el mapa.
- Una representación nueva se agrega como un renderizador más sobre el modelo común de §10.1, sin
  tocar la navegación ni el Inspector. **ProjectGraph es la base**: nodos con id `tipo:id`
  (`context:21`, `step:12`, `commit:<sha>`) y aristas tipadas. Cada representación recibe un **DTO
  especializado que deriva de esa base**: conserva los mismos ids de nodo y los mismos tipos de
  arista, y agrega solo lo que su disposición necesita (carriles y grupos en el mapa, §21.4;
  posiciones, puentes y portales en la constelación, §22.4). Así la selección (`sel=tipo:id`) es la
  misma en todas las representaciones.
- Si una representación no aplica al objeto (mapa de un contexto no elegible, §21.3), su pestaña se
  muestra deshabilitada con el motivo y la opción de verla igual.

### 23.3 Arquitectura de información

La navegación baja de nueve entradas a cuatro de trabajo y tres de configuración:

```text
PROYECTO   Inicio · Trabajo · Ejecuciones · Gobernanza
CONTROL    Proveedores · Políticas · Ajustes
```

| Entrada | Responde | Contiene |
|---|---|---|
| Inicio | ¿Qué necesita mi atención? | Overview (§6.1) y Salud del tracking |
| Trabajo | ¿En qué está el plan y qué lo respalda? | Contextos (lista o constelación) → contexto (pasos en lista o mapa) → paso (Trace) |
| Ejecuciones | ¿Qué se ejecutó y cuánto costó? | Pestañas **Runs** (lista con filtro por fuente) y **Costos** (por período, contexto y agente, con la cobertura de atribución a pasos) |
| Gobernanza | ¿Qué se denegó o falló, y por qué? | Acceso MCP y egress |

Regla de fuente de verdad: **Ejecuciones es la vista agregada de runs y costos.** En Trabajo, los
runs de un paso aparecen solo como chips que abren su panel en el Inspector; no hay una segunda
lista de runs. Inicio enlaza a Costos.

Persistentes en toda la aplicación: **Inspector** a la derecha, **Activity** abajo y **búsqueda** en
el header, que pasa a ser la forma principal de llegar a un objeto cuando hay muchos.

Ubicación y enlaces:

- Breadcrumb: `mi-proyecto › Contexto #21 › Paso 3`.
- Estado en la URL: `?project=mi-proyecto&ctx=21&step=12&as=map&sel=commit:5be88d0c41a7e9f2b3c4d5e6f708192a3b4c5d6e`.
  - `ctx` y `step` indican la página;
  - `as`, la representación;
  - `sel`, el objeto seleccionado en el Inspector, con el formato `tipo:id`: `commit:<sha
    completo>`, `run:<id>`, `decision:<id de la invocación MCP o de egress>`, `step:<id>`.

  Cualquier vista y selección se puede compartir o recargar.
- Trace deja de ser una entrada de navegación: es el detalle de un paso.

### 23.4 Una sola plantilla de página

Todas las pantallas usan la misma estructura; cambia solo el contenido:

```text
┌ Header: scope del proyecto · búsqueda · estado (en vivo, degradado) ─────────────────┐
│ Nav │ Breadcrumb                                                │ Inspector          │
│     │ Título del objeto · estado · acciones (máximo 2 primarias)│ (panel del objeto  │
│     │ Pestañas de representación · filtros · orden              │  seleccionado)     │
│     │ Contenido (lista, mapa, constelación, Trace)              │                    │
├─────┴───────────────────────────────────────────────────────────┴────────────────────┤
│ Activity                                                                             │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

Puntos de corte:

| Ancho | Comportamiento |
|---|---|
| ≥ 1280 px | Tres columnas |
| 768–1279 px | Inspector como panel deslizable de 360 px como máximo, sobre el contenido; Activity reducida a una línea; nunca dos paneles superpuestos abiertos a la vez (abrir uno cierra el otro) |
| < 768 px | Una columna; navegación en barra horizontal; Inspector como hoja inferior; mapa y constelación se abren como lista por defecto |

### 23.5 Sistema de diseño

Se formaliza lo que hoy existe de forma implícita en `dashboard_css.py`.

**Tokens** (un único lugar; los temas solo redefinen valores):

| Grupo | Tokens |
|---|---|
| Superficies | base, surface, elevated, input, code |
| Texto | primary, secondary, muted, faint, detail |
| Bordes | default, subtle, faint |
| Familias | knowledge, work, decision, execution, governance, error, neutral |
| Estado | live, warning, danger, focus |
| Espaciado | escala de 4 px: 4, 8, 12, 16, 20, 24, 32 |
| Radios | 6 (controles), 10 (tarjetas internas), 16 (paneles) |
| Tipografía | UI (Inter), datos (JetBrains Mono); escala 10, 11, 12, 13, 15, 16, 22, 26 |
| Movimiento | rápido 120 ms, normal 200 ms; anulados con `prefers-reduced-motion` |

**Inventario de componentes** (cada uno con estados: normal, hover, foco, seleccionado, atenuado,
deshabilitado, cargando, vacío y error):

| Componente | Uso |
|---|---|
| Métrica con origen | Inicio; al hacer clic muestra su consulta |
| Pill de estado | Pasos, runs, decisiones |
| Chip de referencia | SHA (verificado o no), PR |
| Fila de objeto | Listas de contextos, pasos, runs y decisiones |
| Panel del Inspector | Identidad, atributos, relaciones, acciones y secciones colapsables |
| Cadena | Trace |
| Pestañas de representación | Cambio de representación dentro del objeto (§23.2) |
| Lista sincronizada | Equivalente accesible de mapa y constelación |
| Lienzo de grafo | Mapa y constelación (un solo módulo, dos disposiciones) |
| Leyenda | Familias y tipos de relación |
| Estado vacío | Explica qué falta y cómo empezar |
| Banner de estado | Degradado y desincronizado |
| Evento de Activity | Línea con acciones Ver y Trace |
| Tabla paginada | Ejecuciones y Gobernanza, con cursor (§19.4 O2) |
| Breadcrumb | Ubicación |
| Botón (primario, secundario, peligro) | Acciones; máximo dos primarios por pantalla |
| Campo de búsqueda e input | Búsqueda global y filtros |
| Tooltip | Etiquetas de relaciones y valores abreviados |
| Toast | Confirmación de acciones ("Paso avanzado") |
| Diálogo de confirmación | Acciones destructivas, construido en la página |

**Modelo de interacción único**, igual en todas las representaciones:

| Acción | Resultado |
|---|---|
| Hover | Vista previa (etiqueta de relación, tooltip) |
| Clic | Selecciona: Inspector, atenuación de lo no relacionado, resaltado en Activity |
| Enter o doble clic | Abre el detalle del objeto |
| Esc | Limpia la selección |
| `/` | Búsqueda |
| Flechas | Recorren la colección en su orden |

**Contenido:** un glosario fijo (contexto, paso, alineamiento, desviación, commit verificado,
denegación) y reglas de microcopy de §4. Los textos de estado dicen qué pasó y qué hacer.

### 23.6 Escalabilidad

| Eje | Riesgo | Respuesta |
|---|---|---|
| Volumen de datos | Listas y grafos que crecen con el historial | Paginación por cursor en toda lista (ya necesaria: 1 158 runs, 500 embebidos hoy); presupuestos y agrupamiento en grafos (§21.3); posiciones precalculadas (§22.4). La virtualización de filas se difiere hasta que una lista visible supere ~200 filas en uso real |
| Cantidad de contextos | Navegar por listas deja de servir | Búsqueda primero, filtros por estado y agente, Inicio con solo lo que pide atención |
| Nuevos objetos | Más secciones en la navegación | Modelo de objetos (§23.1): fila, panel y detalle |
| Nuevas representaciones | Vistas paralelas que divergen | Renderizadores sobre ProjectGraph y su extensión propia (§23.2), con la selección compartida |
| Más agentes | Colores y carriles cableados en el código | Catálogo de agentes como dato; el color y el carril salen del catálogo |
| Varios proyectos | Mezclar scopes | Selector de proyecto; nodos portal para relaciones entre proyectos (§22.4) |
| Funciones experimentales | Ruido para todos los usuarios | "Labs" en Ajustes: un interruptor simple por función (Mapa, Constelación), guardado en la configuración local, mientras se miden (§21.6, §22.5) |

### 23.7 Mantenibilidad sin frameworks

Estado actual, medido en el baseline:

- todo el JS vive en un string de Python de 2 203 líneas (`dashboard_js.py`), con 90 funciones y
  144 llamadas a `getElementById`: 75 IDs literales distintos y 12 patrones dinámicos (prefijo más
  variable, como `"tab-btn-" + name`);
- 449 atributos `style` en línea (83 en `dashboard.py` y 366 en `dashboard_js.py`), más 55
  asignaciones `.style.` desde JS;
- 149 colores hexadecimales fuera del CSS (124 en `dashboard_js.py` y 25 en `dashboard.py`).
  Conteo de ocurrencias con `grep -o`, no de líneas.

Estructura objetivo, sin bundler ni librerías:

```text
orchestrator/
  projections.py            proyecciones puras → DTO (§10)
  api_v1/                   endpoints JSON de solo lectura, un módulo por vertical (§24.3)
  static/dashboard/
    tokens.css              tokens y temas (@layer tokens)
    base.css components.css views.css   (@layer base, components, views)
    core/   store.js  router.js  api.js  selection.js  keyboard.js
    components/  metric.js  pill.js  ref-chip.js  object-row.js  inspector.js  ...
    views/       home.js  work.js  runs.js  governance.js
    renderers/   list.js  trace.js  timeline.js  graph-canvas.js  layouts/{map,constellation}.js
```

- **Módulos ES nativos** servidos como estáticos (§19.4 O3); el navegador los carga sin compilación.
  Hoy el servidor solo sirve dos rutas fijas (`/static/docs-theme.css` y `.js`), así que D1 agrega un
  handler restringido a `orchestrator/static/dashboard/`: tipo MIME explícito por extensión
  (`text/javascript`, `text/css`), rechazo de rutas con `..` y caché inmutable.
  **Versión por directorio, no por archivo:** al iniciar, el servidor calcula un hash del contenido
  de todo `static/dashboard/` y lo sirve bajo `/static/dashboard/<hash>/…` con
  `Cache-Control: public, max-age=31536000, immutable`. Los `import` relativos entre módulos
  (`import { store } from '../core/store.js'`) siguen funcionando, porque todos comparten el mismo
  prefijo; con nombres con hash por archivo se romperían. El HTML referencia solo el punto de
  entrada con ese prefijo.
- **Navegadores soportados:** Chromium, Firefox y Safari en sus dos últimas versiones mayores (módulos
  ES, `URL`, History API y `@layer`). Hay tests de navegación que recargan una URL compartida y
  verifican que se restauran la vista y la selección.
- **Un store** con suscripción y **un router** que sincroniza el estado con la URL (§23.3).
- **Componentes como funciones** que devuelven HTML a partir de datos, con un único helper de
  escape; eventos por delegación con atributos `data-*` como contrato.
- **CSS por capas** (`@layer`), solo tokens. Política verificable para colores literales y estilos
  en línea, sobre HTML generado por Python, JS y CSS:
  - **archivos nuevos:** prohibidos desde el primer día; los hexadecimales solo se permiten en
    `tokens.css`;
  - **código existente:** una línea base con los conteos actuales (449 `style="…"`, 55 `.style.` y
    149 hexadecimales); el test falla si algún conteo sube y la línea base se baja en cada PR que
    migra una vista.
- **Contratos versionados:** los DTO de `/api/v1` se validan con `jsonschema` (ya está en las
  dependencias de desarrollo) en los tests de Python.
- **Pruebas sin framework de JS:** las funciones puras (extracción de SHAs, disposición del mapa,
  presupuestos) viven en módulos sin acceso al DOM y se prueban con `node --test`; la lógica de
  dominio, en Python. Un `package.json` mínimo (`{"type": "module"}`) en `static/dashboard/` hace
  que Node cargue esos `.js` como módulos ES igual que el navegador; el handler estático no lo
  sirve. Los tests viven en `tests/js/` con extensión `.mjs`, que Node siempre trata como módulo
  ES, e importan los módulos de `orchestrator/static/dashboard/` por ruta relativa. El workflow de CI
  agrega `actions/setup-node` con una versión LTS fijada y un paso `node --test`; hoy no instala
  Node.
- **Migración por verticales completas:** el HTML actual usa handlers en línea (`onclick`,
  `onchange`) que dependen de funciones globales, y un módulo ES no las expone. Cada PR migra una
  vista entera: su HTML, sus eventos (por delegación) y su módulo, y retira en el mismo PR los
  handlers en línea de esa vista. Una vista nunca queda repartida entre el string heredado y un
  módulo.

### 23.8 Validación con usuarios

- **Tareas de referencia**, las mismas en cada fase: "¿qué pide atención hoy?", "¿qué respalda este
  paso?", "¿quién hizo qué en este contexto?", "¿qué se denegó y por qué?", "¿cuánto costó este
  contexto?".
- **Métricas:** acierto, tiempo, clics hasta la respuesta y tareas resueltas solo con teclado.
- **Muestra y cadencia:** de 3 a 5 sesiones por fase con las mismas tareas, comparando contra la
  línea base de la fase anterior. Para los criterios de permanencia de Labs (§21.6, §22.5) rige su
  mínimo de 10 sesiones.
- **Sesiones locales** con datos reales, sin telemetría (§12), registrando los resultados como
  evidencia en el tracking.
- Las funciones de Labs pasan a la navegación normal solo si cumplen su criterio de permanencia.

### 23.9 Ajuste del plan

| Fase | Cambio respecto de §14 |
|---|---|
| D1 | Además del layout: plantilla única, tokens y componentes base, handler estático para `static/dashboard/`, estructura de módulos, store, router con estado en la URL, contenedor de Activity con los eventos SSE actuales, test de línea base de colores y estilos literales, y Node fijado en CI |
| D2 | Inicio con métricas y Salud del tracking |
| D3 | Trabajo: contextos y página del contexto con pasos; detalle del paso con Trace; proyecciones y API. Se divide en D3a (proyecciones) y D3b (API y UI), §24.4 |
| D4 | Contenido de Activity desde la proyección de §10.4 (solo los hitos disponibles; el historial completo queda para el Event Log, §11), línea de tiempo con esos hitos y detección de cambios entre procesos |
| D5 | Estados, accesibilidad y puntos de corte |
| D6, D7 | Mapa y Constelación como renderizadores dentro de Trabajo, detrás de Labs |

---

## 24. Aplicación y olas de desarrollo con Claude Code, Codex CLI y Copilot

Cómo se construyen §14 y §23 sobre este repositorio repartiendo el trabajo entre tres agentes, con
la auditoría cruzada de ANL-003 y el tracking del orquestador. Validado con Codex (que lo rechazó en
la primera versión) y Copilot; esta versión incorpora sus correcciones.

### 24.1 Roles por agente

| Agente | Rol principal | Restricciones conocidas |
|---|---|---|
| **Claude Code** | Arquitectura e integración: RFC, contratos (DTO y esquemas), registro de rutas, esqueleto de módulos, PR, resolución de hilos de review, tracking | Hoy es el único que puede commitear el trabajo que Codex hace en un worktree: riesgo de cuello de botella (§24.7) |
| **Codex CLI** | Implementación acotada (backend, proyecciones, seguridad, tests) y auditoría en solo lectura | En Windows, dentro de un worktree no puede commitear y deja ACL: hay que restablecer permisos con `icacls . /reset /T /Q` antes de editar. Prompt con `-p no:cacheprovider` y temporales dentro del directorio de trabajo |
| **Copilot CLI (local)** | Auditor: diseño, UX, accesibilidad (con capturas, `--attachment`) y código | Prompt por stdin (`-p` multilínea se trunca en el lanzador de Windows); `--no-custom-instructions` para revisiones de diseño |
| **Copilot (review de PR)** | Revisor automático de cada push | Puede publicar hilos después de un merge: esperar la review del último push y leer el cuerpo |
| **Copilot (agente en la nube)** | Tareas chicas y aisladas, con archivos propios | Solo pushea a ramas `copilot/*`; puede desviarse sin avisar: verificar `git log production..origin/<rama>` y el diff antes de aceptar |

### 24.2 Unidad de trabajo

Cada unidad es **un PR**, con un conjunto de archivos declarado de antemano y esta ficha:

| Campo | Regla |
|---|---|
| Implementador | Un solo agente |
| Auditor de ronda 1 | Distinto del implementador y del integrador cuando el cambio es de seguridad |
| Corrector | El implementador |
| Auditor de ronda 2 | Distinto del implementador; revisa solo lo corregido. Si aparecen hallazgos nuevos, rondas focales hasta cerrar, informando al usuario |
| Revisor del PR | Copilot (automático), con todos los hilos resueltos |
| Integrador | Claude, salvo que la prueba de §24.7 habilite a Codex a commitear |
| Archivos | Lista explícita. Dos unidades en paralelo no comparten ningún archivo |

### 24.3 Prerrequisitos de las olas paralelas

1. **Separación mecánica del código heredado** (inicio de la ola 2): un archivo por vista para el
   HTML y el JS de `dashboard.py` y `dashboard_js.py`, sin cambio de comportamiento. La prueba de
   equivalencia fija el reloj y usa una base sintética determinista; compara un snapshot normalizado
   del HTML, el JS y el CSS generados, y suma pruebas HTTP de los IDs del DOM, los handlers, `/events`,
   `/contexts-html` y la navegación. Los tests actuales (`test_dashboard.py`,
   `test_server_and_rag.py`) no cubren esa estructura.
2. **Registro de rutas y paquete `orchestrator/api_v1/`** (ola 2): cada vertical declara sus
   endpoints en su propio módulo (`api_v1/<vertical>.py`) y el registro los descubre al iniciar. Ni
   `server.py` ni un archivo central de rutas se editan al sumar un vertical.
3. **Dueños únicos** de los archivos compartidos: `.github/workflows/tests.yml` (un solo PR en la
   ola 2), `router.js`, `store.js` y el shell (D1).
4. **Congelamiento de contratos** al cierre de cada ola: los esquemas DTO y las rutas que consume la
   ola siguiente no cambian sin un PR propio. Orden de merge documentado por ola y **rebase sobre
   `production` obligatorio** antes de abrir cada PR; un rebase con conflictos vuelve a auditarse
   sobre el diff final.

### 24.4 Ajustes a §14

- **D3 se divide.** D3a son las proyecciones puras (`projections.py`, esquemas DTO,
  `tests/test_projections.py`), sin endpoints ni UI, y depende solo de R0. D3b es la API y la UI de
  Trabajo, y depende de D1 y D3a.
- **D0 incluye el transporte del token de sesión en el frontend** (no confundir con los tokens de
  diseño de D1). R0 define el mecanismo. Una cookie
  `SameSite` no alcanza, porque otro puerto de `localhost` cuenta como el mismo sitio. La opción
  recomendada es que el servidor inyecte el token en el HTML y el JS lo envíe en un encabezado propio
  en cada POST. Por eso D0 también es dueño de `dashboard.py` y `dashboard_js.py`, con un único
  envoltorio de `fetch` y pruebas del flujo autenticado.
- **D6 y D7 son secuenciales**: D7 empieza después de mergear y medir D6.
- **Las migraciones SQLite de §20.4** (ids en `mcp_invocations`, timestamps en UTC) van en PRs
  propios, con prueba de upgrade desde una base de la versión anterior y compatibilidad de lectura.

### 24.5 Olas

| Ola | Unidades (implementador → auditor ronda 1 / ronda 2) | Paralelo | Sale con (verificable) |
|---|---|---|---|
| **0 · Especificación y arreglos** | Especificación: Claude → Codex / Copilot CLI (ya auditada). Orden de `read_runs`: Claude → Codex / Copilot CLI. R0: Claude → Codex / Copilot CLI. Prueba de Codex en un clon (§24.7) | Especificación ∥ `read_runs` | 3 PR mergeados; R0 con la lista de verificación de §13 firmada por el usuario; resultado de la prueba de §24.7 registrado |
| **1 · Seguridad y proyecciones** | D0 (server, `dashboard.py`, `dashboard_js.py`, tests de seguridad): Codex → **Copilot CLI / Claude**. D3a (archivos nuevos): Claude → Codex / Copilot CLI | D0 ∥ D3a (sin archivos en común) | Tests de §14 para D0 en verde, incluido el bypass por subcadena; proyecciones con tests sobre base sintética |
| **2 · Base del frontend** | Separación mecánica: Claude → Codex / Copilot CLI. D1 (shell, tokens de diseño, handler estático, registro de rutas, paquete `api_v1/`, store, router, línea base de literales, Node en `tests.yml`): Claude → Codex / Copilot CLI | Secuencial (todo depende de la separación) | Prueba de equivalencia en verde; shell nuevo con las vistas heredadas adentro; línea base registrada |
| **3 · Verticales** | Trabajo (D3b): Claude → Codex / Copilot CLI. Inicio (D2): Codex → Claude / Copilot CLI. Ejecuciones con Costos: Codex → Claude / Copilot CLI. Gobernanza: agente en la nube de Copilot → Claude / Codex | Trabajo, Gobernanza y **una sola unidad de Codex a la vez** (§24.7): Inicio primero y Ejecuciones después de integrar Inicio | Cada vertical sin handlers en línea; línea base bajando; tarea de referencia de §23.8 resuelta en la sesión de la ola |
| **4 · Tiempo real y accesibilidad** | D4 backend (hilo de `data_version`, proyección de Activity): Codex → Claude / Copilot CLI. D4 UI + D5: Claude → Codex / Copilot CLI (con capturas) | D4 backend ∥ D4 UI + D5 | Cambio desde otro proceso visible en < 3 s (prueba automatizada); test de contraste AA sobre los pares de tokens (cálculo en Python, sin dependencias) |
| **5a · Labs: Mapa** | D6: Claude → Codex / Copilot CLI | — | Mapa detrás de Labs; 10 sesiones registradas (§21.6) |
| **5b · Labs: Constelación** | D7 backend: Codex → Claude / Copilot CLI. D7 UI: Claude → Codex / Copilot CLI | Backend ∥ UI con contrato congelado | Constelación detrás de Labs; 10 sesiones registradas (§22.5) |
| **6 · Retiro del legado** | Borrado de `dashboard_js.py` y decisión de Labs: Claude → Codex / Copilot CLI | — | Línea base en 0; decisión de permanencia en el tracking |

Las migraciones SQLite (§24.4) se intercalan como unidades propias en la ola que las necesite.

**Archivos por unidad** (las olas 0, 2, 5a y 6 son secuenciales; acá se listan las que corren en
paralelo). Las rutas `static/dashboard/…` son relativas a `orchestrator/`, como en §23.7:

| Ola | Unidad | Archivos |
|---|---|---|
| 1 | D0 | `orchestrator/server.py`, `orchestrator/dashboard.py`, `orchestrator/dashboard_js.py`, `tests/test_server_security.py` |
| 1 | D3a | `orchestrator/projections.py`, `orchestrator/schemas/*.json`, `tests/test_projections.py` |
| 3 | Trabajo (D3b) | `orchestrator/api_v1/work.py`, `static/dashboard/views/work.js`, `static/dashboard/renderers/{list,trace}.js`, archivo heredado de la pestaña Flujos, `tests/test_api_work.py` |
| 3 | Inicio (D2) | `orchestrator/api_v1/home.py`, `static/dashboard/views/home.js`, archivo heredado de la pestaña Métricas, `tests/test_api_home.py` |
| 3 | Ejecuciones | `orchestrator/api_v1/runs.py`, `static/dashboard/views/runs.js`, archivo heredado de la pestaña Actividad, `orchestrator/db.py` (listado con columnas explícitas), `orchestrator/dashboard.py` (dejar de embeber los 500 runs), `tests/test_api_runs.py`. Entrega O1 y O2 de §19.4 |
| 3 | Gobernanza | `orchestrator/api_v1/governance.py`, `static/dashboard/views/governance.js`, `tests/test_api_governance.py` (sin heredado) |
| 4 | D4 backend | `orchestrator/change_watch.py`, `orchestrator/projections_activity.py`, `orchestrator/api_v1/activity.py`, `tests/test_change_watch.py` |
| 4 | D4 UI + D5 | `static/dashboard/components/activity.js`, `static/dashboard/{base,components}.css`, `static/dashboard/tokens.css` (modo System), `static/dashboard/core/keyboard.js` (navegación por teclado), `tests/test_token_contrast.py`, `tests/js/keyboard.test.mjs` |
| 5b | D7 backend | `orchestrator/constellation_layout.py`, `orchestrator/api_v1/constellation.py`, `tests/test_constellation_layout.py` |
| 5b | D7 UI | `static/dashboard/renderers/layouts/constellation.js`, `static/dashboard/views/work.js` (solo la pestaña Grafo), `tests/js/constellation.test.mjs` |

Las pestañas Proyectos, Datos y Configuración del dashboard actual pasan a Ajustes en la ola 6.

**Orden de merge por ola** (cada PR se rebasa sobre `production` antes de abrirse):

| Ola | Orden |
|---|---|
| 0 | Especificación → `read_runs` → R0 → resultado de la prueba de §24.7 |
| 1 | D0 → D3a |
| 2 | Separación mecánica → D1 |
| 3 | Los patrones de `api_v1/` y de las vistas los fija D1 en la ola 2. Arrancan juntos Trabajo, Gobernanza e Inicio; Ejecuciones (también de Codex) empieza cuando Inicio está integrado. Se mergea primero Trabajo (el más grande) y después el resto en el orden en que terminen su ronda 2 |
| 4 | D4 backend → D4 UI + D5 |
| 5a | D6 |
| 5b | **PR de contrato** (esquema DTO de la constelación y base sintética de prueba, Claude) → D7 backend y D7 UI en paralelo → integración |
| 6 | Retiro del legado |

### 24.6 Tracking en el orquestador

Con el modelo actual, `start_step` no permite dos pasos en curso en el mismo contexto, y
`create_context` con estado `active` activa solo el primer paso. Por eso:

- El contexto #63 queda para la especificación. **Cada unidad de trabajo tiene su propio contexto**,
  con `parent_step_id` apuntando al paso de su fase en #63, para que la relación quede trazada y la
  constelación del propio dashboard la muestre.
- Los contextos se crean con estado `programado`. Al empezar la unidad se pasa el contexto a
  `active` con `update_context(status="active")` y se inicia el paso con `start_step(step_id)`.
- Mientras corren unidades en paralelo **habrá varios contextos activos**: la advertencia
  `multiple_active_contexts` es esperada y no se resuelve cerrando contextos; cada agente trabaja con
  su `context_id` explícito.
- Pasos de cada unidad: `[<agente>] Implementación`, `[<agente>] Auditoría ronda 1`, `Correcciones`,
  `[<agente>] Auditoría ronda 2`, `PR y review de Copilot`. La especificación de la tarea va en la
  descripción del paso.
- Cada agente recibe el `context_id` explícito en su prompt.
- **Límite de la atribución automática:** los watchers de Claude Code y Codex vinculan cada sesión
  importada con `get_active_step_id(project)`, que elige el contexto activo **creado** más
  recientemente del proyecto (`db.py:559-573`), no el de la unidad que trabajó. Con unidades en
  paralelo, el `context_id` del prompt no controla esa vinculación: las sesiones (y su costo) pueden
  quedar en la unidad equivocada. Hasta que exista la atribución explícita de §20.4 (punto 5), la
  evidencia por unidad se toma de los alineamientos, las notas y los commits citados, que sí llevan
  el paso; el costo de las sesiones importadas se mide por proyecto y período, no por unidad.

### 24.7 Cuello de botella del integrador

Hoy Claude integra y commitea todo lo que hace Codex, porque en un worktree el sandbox de Codex no
llega a la metadata de git. Para que el paralelismo sea real:

- **Prueba en la ola 0:** ejecutar Codex en un **clon completo** del repositorio (con su propio
  `.git` dentro del sandbox) en lugar de un worktree, y verificar si puede commitear en su rama. Si
  funciona, Claude solo revisa, trae la rama con `git fetch` desde el clon y abre el PR.
- **Resultado (2026-10-03, contexto #66): negativo.** También en un clon completo `git add` falla
  con `.git/index.lock: Permission denied`: el sandbox `workspace-write` de Codex protege `.git` por
  diseño, no es un problema del worktree. En el clon, Claude pudo editar los archivos creados por
  Codex sin restablecer permisos. Rige la contingencia:
- **Contingencia:** la integración se vuelve un paso mecánico y corto, siempre igual:
  restablecer permisos, revisar `git diff --stat` y commitear con la atribución de Codex. Se limita a
  **una unidad de Codex en paralelo por ola**, para que la cola de integración no crezca.
- **Medición:** el tiempo y el costo de integración por ola se registran en Ejecuciones → Costos
  (§24.8). Si la integración demora más que la auditoría de la misma unidad, se baja el paralelismo.

### 24.8 El dashboard aplicado a su propio desarrollo

- Inicio muestra qué unidad pide atención; Trabajo, los contextos de cada unidad con sus pasos por
  agente.
- El Mapa de una unidad con tres agentes es un caso elegible real (§21.2), y la constelación muestra
  las unidades de una ola enlazadas por `parent_step_id` y por commits compartidos.
- Ejecuciones → Costos mide el costo por ola y por agente a nivel de proyecto y período. El costo por
  unidad solo es confiable para runs vinculados explícitamente, mientras la atribución automática
  tenga el límite de §24.6.
- Las sesiones de validación de §23.8 usan estos datos, no datos de prueba.

### 24.9 Riesgos de la coordinación

| Riesgo | Mitigación |
|---|---|
| Conflictos de merge entre unidades paralelas | Separación mecánica, registro de rutas, dueños únicos, lista de archivos por unidad y rebase obligatorio |
| Superposición de archivos no detectada | Antes de abrir un PR, Claude compara sus archivos con los de los PR abiertos de la ola (`gh pr view --json files`) |
| Permisos bloqueados tras trabajar Codex | `icacls . /reset /T /Q`; prueba del clon completo (§24.7) |
| El agente en la nube de Copilot se desvía, pierde commits o expone datos | **Antes:** sus tareas listan los archivos permitidos, prohíben tocar configuración, bases y logs, y no incluyen datos reales; activar *push protection* del escaneo de secretos de GitHub, que bloquea el push si detecta un secreto. **Después:** rama `copilot/*`, verificar la rama remota y el diff, revisión de privacidad (repo público) y revisar que no haya alertas abiertas del escaneo de secretos antes del merge (la protección del push no cubre secretos ya presentes en el historial ni patrones que no reconoce) |
| Hilos de review que llegan después del merge | Esperar la review del último push |
| Sesiones importadas atribuidas a la unidad equivocada cuando hay varias activas | Evidencia por unidad desde alineamientos, notas y commits citados; costo por proyecto y período; atribución explícita sesión → paso (§20.4, punto 5) |
| Agentes que eligen el contexto equivocado cuando hay varios activos (situación esperada, §24.6) | `context_id` explícito en cada prompt; los contextos de unidades que todavía no empezaron quedan en `programado` |
| `order_idx` duplicado | `start_step` explícito; reparación en el contexto de integridad del tracking |
| Rondas de auditoría que no convergen | Rondas focales sobre lo corregido; si tras dos focales siguen abiertas, el usuario decide si acepta el riesgo |
| Costo de las auditorías | Presupuesto por PR: 2 rondas regulares y hasta 2 focales. La re-auditoría por un rebase con conflictos **consume una de esas rondas focales**; pasar el límite escala al usuario. Tiempo y costo de auditorías y rebases registrados por ola en Costos |
