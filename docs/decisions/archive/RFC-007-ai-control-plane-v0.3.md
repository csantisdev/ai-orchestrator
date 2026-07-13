# RFC-007 — Local AI Control Plane para desarrollo asistido por IA

**Estado:** Draft
**Versión:** 0.3
**Fecha:** 2026-07-10
**Repo de referencia:** `csantisdev/ai-orchestrator@production` = `4ae9497` (verificado 2026-07-09; re-verificado parcialmente 2026-07-10 para §6)
**Relación con la serie:** documento paraguas. No supersede a RFC-001…006. RFC-006 vigente en implementación del gate; RFC-005 vigente en posicionamiento y modelo de datos.

---

## Changelog v0.2 → v0.3

| Área | v0.2 | v0.3 |
|---|---|---|
| Posicionamiento | "desarrollo multiagente gobernado" | Multi-provider y multi-tool hoy; multiagente como dirección, no afirmación (§3) |
| Jerarquía conceptual | "AI Control Plane" y PGDP competían | Categoría = Local AI Control Plane; capacidad central = PGDP; mecanismos subordinados (§3) |
| Contabilidad de componentes | Etiqueta única; Agent Registry mal clasificado | Doble atributo `implementation_status` / `evidence_status`; corrección verificada: `agents.py` es registro parcial real (3 implementados / 3 parciales / 2 diseñados-no-públicos) (§2) |
| Hipótesis H1 | Única, ambigua | Dividida en H1a (seguridad) y H1b (compatibilidad), cada una con métricas (§4) |
| Hipótesis H2 | Agreement ≥ 0.80 → decisión | Diseño de no inferioridad con margen δ; umbral 0.80 declarado provisional; estratificación por `routing_source` (§4, §5) |
| Dato nuevo verificado | — | `runs` **no** registra el origen del routing; migración `routing_source` declarada excepción justificada al modo análisis (§5) |
| Métricas | `blocked_total > 0` como liveness | Validación por fixtures deterministas en CI; fixture sintético reemplaza al proyecto real en la especificación (§10) |
| Economía | "SUM(router_cost_usd) es exactamente el ahorro" | `gross_external_router_cost_avoided` con supuestos declarados; neto ≠ bruto (§10) |
| **Acceso de red** | No tratado | **Estudio completo de superficie de red: dashboard y MCP remoto (§6) + dos work packages (WP-Net-1, WP-Net-2)** |
| Requisitos normativos | Solo invariantes | Sección de requisitos MUST / MUST NOT (§9) |
| Alcance de seguridad | Implícito | Declaración explícita: el gate no es un sandbox de red general (§7) |
| Trabajo diferido | — | Threat model completo, ontología de agentes, modelo de degradación y planos formales → RFC-008 / Research Notes (§12) |

Origen de los cambios: revisión externa del v0.2 (validada punto por punto contra el código el 2026-07-10) + auditoría de `server.py` y `mcp.py` motivada por la pregunta de acceso LAN.

---

## 0. Resumen ejecutivo

`ai-orchestrator` se define como un **control plane local para gobernar el uso de múltiples proveedores y herramientas de IA sobre proyectos de software**, preservando aislamiento por proyecto, memoria, trazabilidad, atribución de costos y políticas de salida.

La capacidad central es **Project-Scoped Governed Decision Provenance (PGDP)**: el vínculo verificable entre política, contexto autorizado, decisión de routing, proveedor, costo y outcome. La categoría de producto es Local AI Control Plane; los mecanismos (Egress Gate, Provider-Safe Routing, Decision Ledger, RAG project-scoped, cost attribution, outcome feedback) están subordinados a esa capacidad.

Lo que **no** se afirma: que exista un runtime autónomo multiagente; que el sistema sea un firewall de red general; que los componentes individuales sean originales (la contribución defendible es la composición situada, RFC-005 §5.2); que el router local sea mejor antes de medirlo.

Regla técnica que ancla el diseño: **the router is egress** (RFC-005 §2).

---

## 1. Problema

Sin cambios sustantivos respecto de v0.2 §1: fragmentación del conocimiento entre herramientas, costos opacos, decisiones no auditables, y dos fugas reproducidas contra `production` que siguen abiertas en el remoto público — pre-routing egress (el prompt al router contiene la política que lo prohíbe) y cross-project leak (`_fetch_similar_runs`, `router.py:124`, sin scope de proyecto).

---

## 2. Estado verificado del repositorio

Taxonomía de doble atributo (corrección del review externo, adoptada):

- `implementation_status` ∈ {implemented, partial, designed, absent} — *implemented* cumple el contrato funcional descrito; *partial* existe pero no cumple todo el contrato; *designed* existe especificación o patch no público; *absent* no existe código ni patch.
- `evidence_status` ∈ {verifiable, local-only, none} — *verifiable* = público y comprobable por un tercero.

| Componente | Implementación | Evidencia | Detalle verificado |
|---|---|---|---|
| Context Manager | implemented | verifiable | `context.py`, contexto por proyecto |
| Routing Engine | partial | verifiable | Router LLM externo existe con fuga activa (`router.py:124`); router local determinístico ausente (`_calculate_keyword_signals` solo alimenta el prompt) |
| Memory (RAG) | implemented (con deuda) | verifiable | `rag.py`; embedding default débil para código, sin re-ranking |
| Policy Engine | designed | local-only | Patch RFC-006 (+512/−28, 15 invariantes); no hay `egress.py` ni rama remota |
| Cost Engine | implemented | verifiable | `costs.py` + `catalog.py` (Decision 0002 cerrada) |
| Decision Ledger | partial | verifiable | `runs` con provider/reason/rating/router_cost; **sin** `routing_source` (§5); sin `decision_events`/lineage; spans de `tracer.py` no persistidos |
| Agent Registry | partial | verifiable | `agents.py`: registro global real de presets (`AgentDefinition`, YAML, resolución en `decide_provider`) — no es registry gobernado con capacidades/permisos |
| Provider Gateway | designed | local-only | Borde sellado solo en patch RFC-006; en remoto, los 4 providers hacen `httpx.stream` directo |

**Conteo honesto: 3 implementados, 3 parciales, 2 diseñados sin evidencia pública.** (Corrige el 3/2/3 de v0.2: Agent Registry estaba mal clasificado como inexistente.)

---

## 3. Posicionamiento

```text
Categoría de producto:
    Local AI Control Plane
Capacidad central:
    Project-Scoped Governed Decision Provenance (PGDP)
Mecanismos:
    Egress Gate · Provider-Safe Routing · Decision Ledger
    RAG project-scoped · Cost attribution · Outcome feedback

Estado actual:      control plane multi-provider y multi-tool
Dirección:          gobernanza multiagente
No afirmación:      runtime autónomo multiagente
```

Lo que PGDP responde y ningún gateway, observabilidad, DLP o router responde por sí solo:

> Para el proyecto P, bajo la política V, con sensibilidad efectiva S, se rechazó el router R, se seleccionó el proveedor Q, se autorizó el payload H, costó C, y el resultado obtuvo evaluación O.

Segmento inicial donde el problema es más agudo (análisis de valor del review, aceptado): desarrolladores y equipos pequeños que trabajan simultáneamente con múltiples proyectos, clientes, herramientas y proveedores, sin infraestructura empresarial de gobernanza. El producto no vende capacidad de usar IA; vende **control sobre un uso de IA que ya está ocurriendo**.

---

## 4. Hipótesis falsables

### H1a — Seguridad
> Toda llamada LLM con contexto gobernado atraviesa exactamente una evaluación de política antes de emitir bytes de payload de aplicación hacia el proveedor.

Métricas: `gate_bypass_paths_detected = 0` · `unsafe_fallbacks_executed = 0` · `unknown_policy_levels_allowed = 0` · `known_forbidden_fixture_block_rate = 100%`.

Precisión adoptada: "cero bytes" significa **cero bytes de payload de aplicación con contexto gobernado** hacia el endpoint del proveedor — no ausencia de DNS/TCP/TLS. El método de verificación (mock httpx, transporte instrumentado, proxy de captura) MUST declararse junto al resultado.

### H1b — Compatibilidad
> La introducción del gate no degrada materialmente los workflows autorizados.

Métricas: `existing_test_regressions = 0` · `authorized_run_success_rate_delta ≥ −1 pp` · `p95_gate_overhead_ms ≤ umbral declarado` · `provider_compatibility = 4/4` · streaming operativo (I3, I11).

### H2 — Economía del routing (no inferioridad)
> El router local determinístico es **no inferior** al router LLM externo dentro de un margen δ, en runs cuyo origen fue efectivamente el router LLM.

Formulación: `H0: quality_local < quality_external − δ` vs `H1: quality_local ≥ quality_external − δ`, con δ provisional = 5 pp en `pct_useful`, justificado como pérdida máxima aceptable a cambio de seguridad, privacidad y ahorro bruto.

Condiciones declaradas:
- El umbral de acuerdo 0.80 de RFC-006 §7.6 pasa a **provisional/operacional**, no científico.
- N ≥ 200 pasa a **meta operacional provisional**; el tamaño definitivo se fija con cálculo de potencia previo al canary. Para agreement offline pueden usarse runs sin rating; para calidad, no.
- Estratificación mínima: por `routing_source` (obligatoria, §5), por sensibilidad, y por clase de tarea cuando el N lo permita (con N provisional, solo análisis direccional por estrato — celdas pequeñas no soportan conclusiones).
- Métricas complementarias: `safe_set_agreement` (¿eligió un proveedor permitido y no inferior?) pesa más que `exact_provider_agreement`; `unsafe_disagreement_rate` MUST ser 0.
- Toda conclusión se reporta junto a `rating_coverage` (sesgo declarado en RFC-006 §7.7).

### H3 — Valor del provenance
> El ciclo política → contexto → decisión → costo → outcome tiene valor medible: bloqueos legítimos en fixtures, costo bruto evitable, cobertura de ratings, reconstrucción end-to-end de runs.

Sin datos. Requiere el ledger de la Fase 3 (§11).

---

## 5. Hallazgo nuevo: `routing_source` no existe — dato en decaimiento

Verificado el 2026-07-10 contra `db.py` y `router.py`: la tabla `runs` no registra **cómo** se eligió el provider. `decide_provider()` retorna por al menos cuatro caminos — provider fijado por step activo (`router.py:255`), provider de agent preset (`router.py:263`), router LLM, fallback — y el origen queda solo como texto libre en `routing_reason`.

Consecuencia: el gold standard de H2 está contaminado. "Runs decididos por el router LLM" no es filtrable sin parsear strings, y **cada run ejecutado hoy sin la columna es un dato degradado para el experimento futuro**.

Decisión: se declara la **única excepción justificada al modo análisis** vigente:

```sql
ALTER TABLE runs ADD COLUMN routing_source TEXT;
-- valores: llm_router | forced_step | agent_preset | fallback | default_provider | forced_cli
```

más el enum correspondiente en `RoutingDecision`. Costo: una migración y un campo. No implementa el gate; detiene la quema del dataset. Va en Fase 0 (§11).

---

## 6. Estudio: superficie de acceso de red

Motivación: evaluar el uso de `ai-orchestrator serve` y del servidor MCP desde otros equipos de la red local. Todo lo siguiente está verificado contra el código, no inferido.

### 6.1 Estado verificado

**Dashboard (`serve`):**
- Binding hardcodeado a loopback: `ThreadedServer(("127.0.0.1", port), ...)` — `server.py:1448`. El CLI solo expone `--port`, `--project`, `--open/--no-open`, `--background`. **No existe flag `--host`.**
- **Cero autenticación** en todas las rutas: sin token, sin `Authorization`, sin sesión.
- Los GET exponen la totalidad del historial: el export CSV (`server.py:342`) incluye las columnas `task` y `response` completas de todos los proyectos.
- POST destructivos sin protección: `/delete-contexts`, `/purge-chroma-docs`, `/purge-chroma-responses`, `/clear-imports`, `/sync-git`, `/config/bcentral`, entre otros (`server.py:540+`).
- CORS fijado a `http://127.0.0.1:<port>` (`server.py:1392`): protege solo contra browsers cross-origin; es irrelevante frente a HTTP directo desde otro host.

**Servidor MCP (`orchestrator/mcp.py`):**
- Transporte **stdio puro**: `main()` lee JSON-RPC de `sys.stdin` línea a línea y responde por stdout. Los clientes lo *lanzan* como subproceso (`.mcp.json`: `python -u -m orchestrator.mcp`). No hay URL; no hay socket.
- Declara soporte de protocolo hasta `2025-06-18`, versión de spec que ya define el transporte Streamable HTTP para servidores remotos — el protocolo lo permite; esta implementación no lo trae.
- Las 12 tools incluyen escrituras: `import_agent_context`, `advance_step`, creación de contextos y pasos.

### 6.2 Análisis de opciones

| Opción | Viabilidad hoy | Seguridad | Nota |
|---|---|---|---|
| **A. Exponer dashboard en `0.0.0.0`** (editar `server.py:1448`) | Trivial | **Inaceptable** | Sin auth, cualquier host de la LAN lee todos los prompts/respuestas y ejecuta POSTs destructivos. En el marco del propio proyecto: una fuga peor que el bug del router — no filtra a un proveedor bajo ToS, filtra a cualquiera. **Anti-patrón; prohibido en §9.** |
| **B. Túnel SSH al dashboard** | Inmediata, cero código | Aceptable | `ssh -L 8080:127.0.0.1:8080 usuario@host-A`; el servidor nunca escucha fuera de loopback. |
| **C. MCP remoto vía SSH-stdio** | Inmediata, cero código | Aceptable | En el equipo B: `{"command": "ssh", "args": ["usuario@host-A", "python -u -m orchestrator.mcp"]}`. SSH tuberiza stdin/stdout; el cliente MCP no nota la diferencia. Caveat operativo: entorno no interactivo de SSH (usar ruta absoluta al Python del venv en A). |
| **D. Segunda instalación en el equipo B** | Trivial | Segura pero **incorrecta** | Produce segunda SQLite + segunda Chroma: **split-brain de la memoria del proyecto** — exactamente la fragmentación que el producto dice combatir. Anti-patrón declarado. |
| **E. WP-Net-1: `--host` + token de autenticación (dashboard)** | Work package | Diseñable | Token generado al arrancar, exigido en header en toda ruta; `--host` opcional con warning explícito. Beneficio lateral estratégico: el dashboard es donde se puntúan los runs (`/rate-run`) → acceso multi-dispositivo **aumenta `rating_coverage`**, insumo directo del canary de H2. |
| **F. WP-Net-2: MCP Streamable HTTP** | Work package | Diseñable | Dos vías: adoptar SDK oficial (FastMCP, trae ambos transportes) o implementar a mano sobre el protocolo ya hand-rolled. Autenticación obligatoria (las tools escriben). **Precondición: borde de egress sellado primero** — exponer un endpoint de red que escribe en la memoria del proyecto antes de tener Policy Engine invierte las prioridades de seguridad. |

### 6.3 Regla de consistencia con la tesis

Todo acceso remoto MUST llegar a la **única** base de datos del host A (opciones B, C, E, F). La opción D viola la tesis anti-fragmentación y queda documentada como anti-patrón. La opción A viola H1a por construcción.

### 6.4 Ubicación en el roadmap

- B y C: disponibles hoy; se documentan en README/docs como patrón soportado (cambio documental, no de código).
- WP-Net-1: elegible después de la Fase 1; **candidato a adelantarse antes del canary de Fase 4** si `rating_coverage` resulta ser el cuello de botella del experimento H2 — es el único WP de red con justificación empírica, no solo de conveniencia.
- WP-Net-2: solo después de Fase 2 (borde sellado). Registrar además que su diseño debe pasar por el Policy Engine: un MCP remoto es un cliente más del control plane, no un bypass.

---

## 7. Alcance de seguridad (declaración obligatoria)

> El Egress Gate gobierna llamadas LLM realizadas mediante el Provider Gateway de `ai-orchestrator`. **No** constituye un sandbox de red general del agente ni controla: `requests.post()` fuera del gateway, exfiltración por shell o git push, browsers, herramientas MCP de terceros con red propia, DNS, ni telemetría de dependencias. `model_discovery` permanece clasificado como egress no contextual fuera de alcance, auditado como issue separado (RFC-003 §3.2).

El threat model completo (adversarios: error humano, prompt injection en el repo, plugin MCP malicioso, agente que modifica su propia política, dependencia comprometida) se difiere a RFC-008 / Research Notes (§12), con una excepción incorporada ya en esta versión: la separación política/contexto de §8.

---

## 8. Separación de política y contexto operativo

Riesgo aceptado del review: si `context.yaml` contiene a la vez el contexto del proyecto y la política que gobierna su salida, un agente con permiso de escritura sobre el repo puede rebajar su propia sensibilidad o desbloquear un proveedor — escalación de privilegios vía prompt injection.

Decisión de diseño para el gate (afecta a RFC-006 en su merge, no requiere código hoy):

```text
.orchestrator/context.yaml   → stack, convenciones, descripción, routing hints
.orchestrator/policy.yaml    → sensitivity, blocked_providers, clearance overrides,
                               policy_version
effective_policy = global_policy ∩ project_policy
```

Una política de proyecto MUST NOT ampliar permisos prohibidos globalmente. Cambios de política MUST quedar registrados (hash de política en cada evento del ledger). Semántica del lattice, adoptada:

| Nivel | Significado |
|---|---|
| `public` | Publicable sin restricciones |
| `internal` | No público; compartible con proveedores aprobados bajo términos estándar |
| `restricted` | Contractual/personal/sensible; solo proveedores explícitamente autorizados |
| `secret` | Credenciales y material que no debe salir a ningún proveedor externo |

Con distinción `declared_sensitivity` / `detected_sensitivity` / `effective = max(declared, detected)`. Granularidad v1: **project-level**, declarada como limitación (archivo/chunk/campo quedan como evolución).

---

## 9. Requisitos normativos

- Toda llamada LLM gobernada MUST atravesar el Provider Gateway.
- El router externo MUST evaluarse como destino de egress (the router is egress).
- Una política desconocida o ilegible MUST fallar cerrada.
- Una denegación de política MUST NOT reintentarse (I13).
- Contexto de otro proyecto MUST NOT entrar al payload (I8).
- Todo fallback MUST reevaluarse contra la política (I6, I14).
- El servidor del dashboard MUST NOT hacer binding fuera de loopback sin autenticación (§6).
- Todo transporte de red del MCP MUST exigir autenticación y MUST pasar por el Policy Engine (§6.2-F).
- El acceso remoto MUST operar contra la base única del host; instalaciones espejo MUST NOT usarse como acceso remoto (§6.3).
- Los eventos del ledger MUST incluir `policy_hash` y `reason_code`; las API keys MUST NOT aparecer en eventos.
- El gate MUST NOT ejecutarse dentro de un `try` sin `raise` (riesgo `cli.py:~237`).
- El dashboard MUST NOT ser la única ubicación de trazas (persistencia de spans, Fase 3).

---

## 10. Métricas

### 10.1 Validación de seguridad (reemplaza el liveness de v0.2)

El bloqueo se valida con **fixtures deterministas en CI**, no esperando incidentes reales:

```text
policy_evaluation_coverage                          = 100%
known_forbidden_fixture_block_rate                  = 100%
unknown_sensitivity_block_rate                      = 100%
unsafe_fallback_execution_total                     = 0
gate_bypass_total                                   = 0
restricted_fixture_payload_bytes_to_blocked_provider = 0
```

Fixture público sintético `fixtures/restricted-project/` (`sensitivity: restricted`, `blocked_providers: [deepseek]`) reemplaza al proyecto real en la especificación; el caso real se conserva como evidencia privada adicional. `router_egress_blocked_total` se degrada a métrica observacional (diagnóstico de despliegue), nunca criterio de éxito.

### 10.2 Economía

```text
gross_external_router_cost_avoided = SUM(router_cost_usd)   [medible hoy]

net_routing_savings = gross_external_router_cost_avoided
                    − local_routing_compute_cost      (≈0, declarado supuesto)
                    − quality_regret_cost             (requiere canary)
                    − additional_fallback_cost        (requiere canary)
```

Se abandona la formulación "es exactamente el ahorro". Métrica de valor del routing completo: `(C_frontier − C_route) / C_frontier × pct_useful`, cross-tab por proveedor y `routing_source`, calculable con datos de `runs` una vez migrada la columna de §5.

---

## 11. Roadmap v0.3

Reordenado según la Alternativa B del review (gate mínimo antes del ledger completo, porque el bug está vivo) + integración de los WP de red.

**Fase 0 — Publicar y detener el decaimiento** *(bloqueante)*
- `git push -u origin feat/egress-gate` + PR + CI.
- Merge del fix I8 (`_fetch_similar_runs` scoped por proyecto).
- Migración `routing_source` (§5).
- Documentar patrones SSH (túnel dashboard + SSH-stdio MCP) como acceso remoto soportado.
- *Salida:* rama pública, CI verde, fuga cross-project cerrada en `production`, dataset de H2 dejando de degradarse.

**Fase 1 — Gate mínimo fail-closed**
- `EgressPolicy` + borde sellado + eventos mínimos en `runs` (allowed/blocked, phase).
- Fixture `restricted-project` + tests de §10.1 en CI.
- *Salida:* invariantes I1–I14 en CI; H1a/H1b con evidencia pública.

**Fase 2 — Provider-Safe Routing completo**
- Router local determinístico (degradación I5 + modo sombra).
- Separación `policy.yaml` / `context.yaml` (§8).
- *Salida:* cascada operativa; `unsafe_disagreement_rate` instrumentado.

**Fase 3 — Ledger normalizado + replay offline**
- Persistencia de spans; separación telemetría operacional / decision provenance / outcomes (esquema RFC-005 §7 sin hash chaining).
- `router-eval --offline` sobre runs con `routing_source = llm_router`.
- *Salida:* agreement estratificado publicado con `rating_coverage`.

**Fase 4 — Canary y decisión sobre el router externo**
- Cálculo de potencia → N definitivo; canary por hash determinístico de `run_id`; prueba de no inferioridad con δ.
- **WP-Net-1 elegible como habilitador previo** si `rating_coverage` es cuello de botella.
- *Salida:* decisión documentada; reconfigura §6.2 del RFC-006 y la arquitectura de routing.

**Fase 5 — Provenance completo**
- Lineage, export OTel (eventos operativos exportables; eventos de gobernanza con esquema propio y mapeo parcial — interoperabilidad, no dependencia conceptual).
- Hash chaining diferido a sub-RFC con threat model (review §12, aceptado: sin adversario definido es teatro).

**Fase 6 — Gobernanza multi-tool → multiagente**
- Agent Registry gobernado sobre ontología mínima: `Tool ≠ Provider ≠ Model ≠ Agent Profile ≠ Execution Identity ≠ Capability ≠ Permission`.
- WP-Net-2 (MCP Streamable HTTP) elegible desde aquí o desde el cierre de Fase 2.
- *Entrada:* Fases 0–4 cerradas + un agente externo real integrado.

---

## 12. Trabajo diferido (documentos de investigación, no RFCs de arquitectura)

Corrección al circuit breaker de v0.2 (aceptada del review): **RFC queda reservado para decisiones de arquitectura/implementación vinculadas a código publicado.** Sin rama pública de RFC-006, no hay RFC-008 de arquitectura. Sí se permiten, como *Research Notes / Evaluation Plans*:

- **RN-1 — Threat model** completo (adversarios, superficie, qué cubre el gate y qué no; base: §7).
- **RN-2 — Ontología de agentes y modelo de permisos** (base: §11 Fase 6).
- **RN-3 — Estado del arte** (la revisión bibliográfica antes prevista como RFC-008).
- **EP-1 — Pre-registro del experimento H2** (cálculo de potencia, δ definitivo, estratificación, protocolo de canary; antes previsto como RFC-009).
- **RN-4 — Métricas de fragmentación del conocimiento** (única pregunta abierta de v0.1 que sigue viva; candidatas: `repeated_context_ratio`, `cross_tool_memory_reuse_rate`, `time_to_context_ready`, `conflicting_recommendation_rate`, `lineage_coverage`).
- **RN-5 — Modelo de degradación** (¿la ausencia de evidencia bloquea la ejecución? propuesta: `enforcement_mode: strict | best_effort` por proyecto; tabla de fallos: policy ilegible → bloquear; ledger caído → según modo; RAG caído → ejecutar sin RAG y registrarlo; router externo caído → cascada local).
- **RN-6 — Planos formales** (control / datos / evidencia) — el esquema conceptual queda anticipado aquí:

```text
                 CONTROL PLANE
 Policies · Catalog · Routing Rules · Agent Profiles
                       │
INPUT ────────► DECISION / POLICY ENGINE
                       │
                  DATA PLANE
 Context Assembly → Provider Gateway → Modelo
                       │
                EVIDENCE PLANE
 Decisions · Spans · Costs · Outcomes · Lineage
```

---

## 13. Riesgos (delta respecto de v0.2)

Se mantienen: documentación por delante del código (11.1), contrafactual no observable (11.2), sesgo de rating (11.3), categoría en consolidación (11.5), convergencia de precios (11.6), fail-open silencioso (11.7). Cambian:

- **11.4 (N insuficiente)** reformulado: N definitivo por cálculo de potencia; 200 es meta operacional provisional. Si la cobertura de ratings es inviable para un usuario individual, WP-Net-1 (acceso multi-dispositivo al rating) es la mitigación con mejor relación costo/beneficio.
- **11.8 (nuevo) — Superficie de red del dashboard.** El único control actual es el binding a loopback. Cualquier "fix rápido" a `0.0.0.0` expone historial completo y POSTs destructivos sin auth. Mitigación: requisito normativo en §9 + WP-Net-1 como única vía sancionada.
- **11.9 (nuevo) — Inflación documental por review.** Aplicar las 25 recomendaciones del review externo en el documento rector reproduciría el patrón que el circuit breaker rompe. Mitigación: triage aplicado — correcciones textuales en esta versión; diseño sustantivo → RN-1…6; nada de lo anterior mueve la Fase 0.

---

## Conclusión

La v0.3 incorpora tres cosas: las correcciones validadas del review externo (con dos verificaciones contra código que ajustaron la contabilidad de componentes y destaparon la ausencia de `routing_source`), el estudio completo de la superficie de acceso de red con sus dos work packages y sus dos anti-patrones, y la restricción del circuit breaker a su forma fuerte (RFC = código; investigación = Research Notes).

El estado analítico del proyecto es ahora: dos fugas reproducidas y abiertas en `production`, un patch de gate maduro sin publicar, un experimento decisivo (H2) cuyo dataset se degrada con cada run sin `routing_source`, y una vía de acceso remoto soportable hoy sin escribir código. El siguiente paso sigue sin ser un documento: es `git push`, el merge de I8 y una migración de una columna.

---

## Apéndice A — Invariantes consolidadas (sin cambios, RFC-006 §4.3)

I1–I14 según RFC-006; I15 vacía a propósito. Se agregan a la fila de candidatas a I15 las derivadas de esta versión: *"ningún binding de red sin autenticación"* y *"una política de proyecto nunca amplía permisos globales"* — a formalizar cuando exista el código que las pruebe.

## Apéndice B — Vigencia documental

| Doc | Rol | Vigencia |
|---|---|---|
| RFC-001…004 | Hallazgo, diseño, bugs de streaming/threads/retry | Superseded por 006 |
| RFC-005 | PGDP, prior art, esquema de ledger | Vigente (posicionamiento y datos) |
| RFC-006 | Implementación del gate + protocolo experimental | Vigente (implementación); pendiente rama pública |
| RFC-007 v0.3 | Documento rector (este) | Vigente; reemplaza v0.2 |
| RN-1…6, EP-1 | Investigación diferida | Planificados (§12) |

## Apéndice C — Recetas de acceso remoto soportadas hoy

```bash
# Dashboard desde el equipo B (túnel SSH):
ssh -L 8080:127.0.0.1:8080 usuario@host-A
# luego abrir http://127.0.0.1:8080 en B

# MCP remoto desde el equipo B (.mcp.json del cliente):
{
  "command": "ssh",
  "args": ["usuario@host-A",
           "/ruta/absoluta/venv/bin/python -u -m orchestrator.mcp"]
}
```

Ambas llegan a la base única del host A. Ninguna requiere cambios en el repo.
