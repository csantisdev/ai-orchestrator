# RFC-005: Project-Scoped Governed Decision Provenance

**Título corto:** Provider-Safe Routing + Governed Decision Ledger  
**Proyecto:** `csantisdev/ai-orchestrator`  
**Fecha:** 2026-07-09  
**Supersede:** RFC-004, RFC-003, RFC-002 y RFC-001  
**Estado del documento:** propuesta consolidada para implementación y validación empírica  
**Estado remoto verificado:** al 2026-07-09, la rama pública `production` no contiene `orchestrator/egress.py` y no se observa una rama remota visible con `egress` en el nombre. Las afirmaciones de implementación y resultados de tests del RFC-004 deben tratarse como **evidencia local no verificable remotamente** hasta publicar rama, commit, PR o logs reproducibles.

---

## 0. Decisión ejecutiva

`ai-orchestrator` no debe posicionarse como:

- un nuevo AI Gateway general;
- un DLP empresarial completo;
- una arquitectura original de information-flow control;
- una plataforma genérica de observabilidad;
- una memoria cerebral para agentes.

Debe posicionarse como:

> **Un control plane local-first para desarrollo asistido por IA que gobierna, registra y evalúa cómo cada proyecto utiliza proveedores LLM externos.**

La capacidad de entrada es **Provider-Safe Routing**:

> Antes de que contexto del proyecto salga hacia un proveedor —incluido el proveedor usado como router— el sistema aplica una política determinística local.

La joya de la corona es más amplia:

> **El vínculo verificable entre autorización, decisión, contexto enviado y resultado obtenido.**

Nombre técnico propuesto:

> **Project-Scoped Governed Decision Provenance (PGDP).**

La unidad de valor ya no es “un log de una llamada”. Es un ciclo cerrado:

```text
política del proyecto
        ↓
contexto candidato
        ↓
autorización de egress
        ↓
decisión de routing
        ↓
ejecución del modelo
        ↓
resultado verificable
        ↓
costo, rating y rerun
        ↓
replay / evaluación de política
```

---

## 1. Qué cambió desde RFC-004

RFC-004 se centraba en cerrar una fuga reproducible: el router externo recibía contexto sensible antes de seleccionar el proveedor final.

RFC-005 conserva ese hallazgo, pero corrige cuatro problemas de alcance:

### 1.1 Separa diseño de implementación verificable

El RFC-004 declaraba “implementado y verificado”. El repo remoto público no permite confirmar ese estado al 2026-07-09.

Este RFC diferencia explícitamente:

```text
Diseño validado             ≠ implementación local ejecutada
Implementación local        ≠ rama pública verificable
Tests reportados            ≠ CI reproducible
RFC aprobado                ≠ feature desplegada
```

### 1.2 El gate no es la joya completa

El egress gate es la primera frontera de seguridad, pero por sí solo puede ser replicado por gateways, proxies y herramientas DLP existentes.

El diferenciador potencial está en conectar:

```text
proyecto
+ política
+ contexto utilizado
+ decisión de router
+ proveedor final
+ costo
+ outcome
+ replay
```

### 1.3 La innovación no está en los componentes

Ya existen enfoques públicos para:

- routing sensible pre-call;
- DLP para coding agents;
- information-flow control para agentes;
- separación de control y datos;
- audit trails append-only;
- execution provenance;
- agent record & replay;
- telemetría con enforcement.

La contribución defendible es una **composición situada**, no una nueva teoría.

### 1.4 La evidencia interna pasa a ser obligatoria

No se afirmará valor de producto hasta medir:

- intentos reales de egress bloqueados;
- costo incremental o evitado;
- calidad del router local;
- cobertura de ratings;
- reruns y overrides;
- falsos positivos operacionales.

---

## 2. El problema concreto

El router LLM no es lógica interna. Es otro sink externo.

Flujo vulnerable:

```text
proyecto local
  → construir prompt del router con tarea/contexto
  → enviar a router externo barato
  → router elige proveedor final
  → enviar al proveedor final
```

La política aplicada solo al proveedor final llega tarde.

Regla central:

> **The router is egress.**

En español:

> **El router también es una salida de datos.**

Esto debe gobernar:

- router LLM;
- provider final;
- streaming;
- contexto RAG;
- runs similares;
- system prompts;
- callbacks que envíen contexto;
- futuros backends gateway o proxy.

---

## 3. Tesis del producto

### 3.1 Tesis principal

> `ai-orchestrator` gobierna y registra el uso de IA externa por proyecto: qué contexto estaba autorizado, qué proveedor fue elegido, qué política permitió o bloqueó la salida, cuánto costó y si la decisión funcionó.

### 3.2 Frase comercial

> **A local firewall and decision ledger for what coding agents send to LLMs.**

### 3.3 Frase técnica

> **Local-first, project-scoped authorization and provenance for multi-provider coding-agent decisions.**

### 3.4 Lo que no se afirma

No se afirma que:

- IFC sea una técnica nueva;
- sensitive data routing sea original;
- no existan gateways con DLP;
- el sistema impida toda exfiltración;
- una regex equivalga a DLP;
- el router local sea mejor antes de medirlo;
- SQLite por sí solo sea un producto diferenciador.

---

## 4. Evidencia externa y productos similares

La revisión de fuentes públicas confirma que la categoría está ocupada parcialmente.

### 4.1 LiteLLM: Sensitive Data Routing

LiteLLM documenta un guardrail pre-call que detecta datos sensibles mediante patrones, regex y keywords y redirige la request hacia un modelo on-premise. También implementa sticky session después de detectar sensibilidad.

**Cubre:**

- detección antes de model selection;
- rerouting sensible;
- ejecución local del detector;
- continuidad de sesión.

**No cubre explícitamente como núcleo:**

- política raíz por repositorio/proyecto;
- el router externo como sink gobernado;
- lineage de contexto RAG/runs;
- vínculo entre autorización, costo y outcome de desarrollo.

Fuente: <https://docs.litellm.ai/docs/proxy/guardrails/sensitive_data_routing>

### 4.2 Cloudflare AI Gateway: coding agents + DLP

Cloudflare ofrece integración con coding agents, observabilidad, costos y DLP sobre prompts y respuestas. Reconoce que coding agents envían código, archivos de configuración y snippets que pueden incluir secretos o datos de clientes.

**Cubre:**

- gateway para coding agents;
- inspección y control de tráfico;
- DLP;
- logging, tokens, costos y latencia;
- routing hacia proveedores.

**Diferencia relevante:**

Cloudflare observa tráfico que pasa por su gateway. `ai-orchestrator` puede aplicar política antes, usando información local del proyecto, RAG, historial, cliente y router.

Fuentes:

- <https://developers.cloudflare.com/ai-gateway/integrations/coding-agents/>
- <https://developers.cloudflare.com/ai-gateway/features/dlp/>

### 4.3 FIDES: Information-Flow Control para agentes

FIDES formaliza confidencialidad, integridad, tracking dinámico y enforcement determinístico para planners de agentes.

**Valida:**

- labels de sensibilidad;
- políticas fuera del LLM;
- enforcement determinístico;
- seguridad como propiedad del planner, no del prompt.

Fuente: <https://arxiv.org/abs/2505.23643>

### 4.4 CaMeL: separación control/data flow

CaMeL separa flujo de control y flujo de datos y usa capacidades para impedir exfiltración por flujos no autorizados.

**Valida:**

- el router no debe recibir datos completos si no está autorizado;
- datos no confiables o sensibles no deben controlar el programa;
- seguridad puede reducir utilidad y debe medirse.

Fuente: <https://arxiv.org/abs/2503.18813>

### 4.5 Audit Trails for Accountability

Este trabajo propone audit trails cronológicos, contextuales, tamper-evident y append-only que conectan eventos técnicos con autorizaciones y decisiones de gobernanza.

**Valida:**

- ledger append-only;
- metadatos de autorización;
- reconstrucción posterior;
- separación entre ejecución y revisión.

Fuente: <https://arxiv.org/abs/2601.20727>

### 4.6 From Agent Traces to Trust

El survey organiza evidencia, tool outputs, memoria, acciones, claims y respuestas como execution provenance.

**Valida:**

- trazas de proceso, no solo resultado final;
- provenance de RAG y tool calls;
- auditoría y debugging;
- seguridad consciente de procedencia.

Fuente: <https://arxiv.org/abs/2606.04990>

### 4.7 Governance-Aware Agent Telemetry

GAAT describe el vacío “observe-but-do-not-act”: la observabilidad registra eventos, pero no necesariamente aplica políticas antes del daño. Propone cerrar el loop entre telemetría y enforcement.

**Es el enfoque académico más cercano a la joya completa.**

**Diferencias:**

- GAAT está orientado a sistemas multi-agente empresariales;
- `ai-orchestrator` está orientado a coding workflows locales y proyectos concretos;
- este RFC usa política por proyecto y provider routing como primera cuña.

Fuente: <https://arxiv.org/abs/2604.05119>

### 4.8 AgentRR: Record & Replay

AgentRR registra trazas y decisiones, las estructura como experiencia y las reutiliza en ejecuciones futuras.

**Valida:**

- record & replay;
- reducción de costo;
- replay con validaciones;
- experiencias derivadas de ejecución real.

**Diferencia:**

Este RFC usa replay inicialmente para evaluar routing y política, no para convertir trazas en memoria prescriptiva.

Fuente: <https://arxiv.org/abs/2505.17716>

### 4.9 OpenTelemetry GenAI semantic conventions

OpenTelemetry ya desarrolla convenciones semánticas para spans, métricas y eventos GenAI.

**Decisión:**

SQLite será el almacenamiento local inicial, pero el modelo de eventos debe ser exportable a OpenTelemetry. No se debe crear una isla cerrada de observabilidad.

Fuente: <https://opentelemetry.io/docs/specs/semconv/gen-ai/>

### 4.10 Conclusión de prior art

No se encontró en las fuentes revisadas un producto o estudio público que presente exactamente como núcleo:

```text
policy root = proyecto/repositorio
+ router externo tratado como egress
+ enforcement local antes del router y provider final
+ lineage de contexto
+ ledger de decisiones
+ costo y outcome
+ replay de routing
+ enfoque específico en coding workflows locales
```

Esto es una conclusión limitada a la muestra revisada, no una prueba de inexistencia.

---

## 5. Innovación real

### 5.1 No innovación de componente

| Componente | Estado |
|---|---|
| AI Gateway | existente |
| Multi-provider routing | existente |
| DLP/secret scanning | existente |
| IFC/taint tracking | existente |
| Observabilidad LLM | existente |
| Audit ledger | existente |
| Record & replay | existente |
| Cost tracking | existente |
| RAG provenance | línea activa de investigación |

### 5.2 Innovación de composición

La composición potencialmente distintiva es:

> **Un governed decision loop local y project-aware para coding agents multi-proveedor.**

Sus propiedades:

1. La política nace en el proyecto, no en el request aislado.
2. El router se trata como proveedor externo.
3. El gate se ejecuta antes del router y antes del provider final.
4. El contexto enviado tiene lineage local.
5. La decisión se conecta con costo y outcome.
6. El routing puede re-evaluarse offline sobre historia real.
7. El sistema funciona sin SaaS obligatorio.

### 5.3 Innovación empírica posible

La contribución investigable no sería el diseño, sino una evaluación como:

> **Efecto de políticas project-scoped y pre-router sobre exposición, costo y calidad en workflows multi-proveedor de coding agents.**

Preguntas medibles:

- ¿Con qué frecuencia el router externo habría recibido contexto no autorizado?
- ¿Cuántos bloqueos ocurren antes del router vs provider final?
- ¿Qué costo agrega o evita el gate?
- ¿Puede el router local reemplazar al externo sin degradación material?
- ¿Qué proporción de runs necesita override o rerun?
- ¿Qué fuentes de contexto provocan más denegaciones?

---

## 6. Arquitectura mínima

La arquitectura inicial debe seguir siendo simple y local.

```text
.orchestrator/context.yaml
config.yaml
SQLite
BaseProvider gate
router local determinístico
decision_events
context_lineage
outcome_events
export OpenTelemetry opcional
```

No requiere:

- Kubernetes;
- un servicio remoto;
- OPA obligatorio;
- un grafo externo;
- blockchain;
- vector DB adicional;
- modelos locales obligatorios;
- un nuevo framework de agentes.

---

## 7. Modelo de datos

### 7.1 `decision_events`

Registra autorización y decisiones de routing/egress.

```sql
CREATE TABLE IF NOT EXISTS decision_events (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                    TEXT    NOT NULL,
    run_id                INTEGER,
    project               TEXT    NOT NULL,
    phase                 TEXT    NOT NULL,
    decision_type         TEXT    NOT NULL,
    decision              TEXT    NOT NULL,
    router_mode           TEXT,
    provider              TEXT,
    model                 TEXT,
    project_sensitivity   TEXT    NOT NULL,
    provider_clearance    TEXT,
    policy_version        TEXT    NOT NULL,
    reason_code           TEXT    NOT NULL,
    reason_detail         TEXT,
    estimated_input_tokens INTEGER,
    estimated_cost_usd    REAL,
    previous_event_hash   TEXT,
    event_hash            TEXT    NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_decision_events_run
    ON decision_events(run_id, ts);
CREATE INDEX IF NOT EXISTS idx_decision_events_project
    ON decision_events(project, ts);
CREATE INDEX IF NOT EXISTS idx_decision_events_decision
    ON decision_events(decision, phase);
```

Valores de `phase`:

```text
router
provider
stream
rag
context_build
```

Valores de `decision`:

```text
allowed
blocked
rerouted
fallback_local
```

### 7.2 `context_lineage`

Registra qué elementos de contexto fueron considerados, incluidos, excluidos o bloqueados.

```sql
CREATE TABLE IF NOT EXISTS context_lineage (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                 TEXT    NOT NULL,
    run_id             INTEGER NOT NULL,
    project            TEXT    NOT NULL,
    source_type        TEXT    NOT NULL,
    source_ref         TEXT,
    source_project     TEXT,
    sensitivity        TEXT    NOT NULL,
    content_hash       TEXT    NOT NULL,
    action             TEXT    NOT NULL,
    destination_phase  TEXT,
    destination_provider TEXT,
    reason_code        TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_context_lineage_run
    ON context_lineage(run_id);
CREATE INDEX IF NOT EXISTS idx_context_lineage_source_project
    ON context_lineage(source_project, run_id);
```

Valores de `source_type`:

```text
user_task
project_context
active_context
rag_doc
rag_response
similar_run
system_addition
tool_output
```

Valores de `action`:

```text
included
excluded
blocked
redacted
```

Nunca se guarda el payload completo en estas tablas. Se guarda hash, referencia y metadatos mínimos.

### 7.3 `outcome_events`

Registra señales posteriores a la decisión.

```sql
CREATE TABLE IF NOT EXISTS outcome_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT    NOT NULL,
    run_id            INTEGER NOT NULL,
    project           TEXT    NOT NULL,
    provider          TEXT,
    model             TEXT,
    outcome_type      TEXT    NOT NULL,
    outcome_value     TEXT,
    rating            TEXT,
    tests_passed      INTEGER,
    tests_failed      INTEGER,
    rerun_of_run_id   INTEGER,
    manual_override   INTEGER NOT NULL DEFAULT 0,
    duration_ms       INTEGER,
    cost_usd          REAL,
    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_outcome_events_run
    ON outcome_events(run_id, ts);
CREATE INDEX IF NOT EXISTS idx_outcome_events_rating
    ON outcome_events(rating)
    WHERE rating IS NOT NULL;
```

### 7.4 Hash chaining local

Para hacer el ledger tamper-evident sin introducir blockchain:

```text
event_hash = SHA256(previous_event_hash + canonical_event_payload)
```

Propiedades:

- detecta alteraciones en secuencia;
- permite auditoría local;
- no impide físicamente borrar la base;
- no sustituye backups ni controles de acceso;
- debe ser opcional durante el primer MVP si complica el merge.

---

## 8. Egress policy

### 8.1 Niveles

```text
public < internal < restricted < secret
```

Un nivel desconocido bloquea.

### 8.2 Política de proyecto

Ejemplo:

```yaml
name: restricted-project.example
sensitivity: restricted
allowed_providers:
  - claude
blocked_providers:
  - deepseek
  - gemini
```

### 8.3 Clearance de proveedor

```yaml
providers:
  deepseek:
    clearance: public
  openai:
    clearance: internal
  claude:
    clearance: restricted
  gemini:
    clearance: internal
```

### 8.4 Regla de autorización

```text
allowed =
  provider.clearance >= effective_sensitivity
  AND provider not in project.blocked_providers
  AND (project.allowed_providers vacío OR provider in allowed_providers)
```

### 8.5 Sensibilidad efectiva

```text
effective_sensitivity = max(
    project_sensitivity,
    context_item_sensitivities,
    secret_scanner_escalation,
    sticky_run_sensitivity
)
```

V1 puede usar sensibilidad de proyecto + secret scanner. El lineage por chunk permite evolucionar después.

### 8.6 Sticky sensitivity

Si un run o una sesión toca contexto `restricted`, sus decisiones derivadas no pueden bajar automáticamente de nivel.

```text
run_sensitivity(t+1) >= run_sensitivity(t)
```

Una reducción requiere acción humana explícita y auditada. No se implementa declassification automática.

---

## 9. Borde de provider

### 9.1 Template method sellado

`BaseProvider.complete()` y `complete_stream()` deben ser concretos y ejecutar el gate.

Los providers implementan:

```text
_complete()
_complete_stream()
```

`__init_subclass__` debe impedir sobreescribir el borde público.

### 9.2 Streaming eager

`complete_stream()` debe ejecutar el check antes de retornar el generator.

```python
def complete_stream(self, prompt: str, system: str = ""):
    check_egress(prompt=prompt, system=system, provider=self.name)
    return self._complete_stream(prompt=prompt, system=system)
```

### 9.3 Threads

La política debe establecerse dentro de cada worker thread. No se puede asumir propagación de `ContextVar` desde el thread padre.

### 9.4 Retry

`EgressBlocked` no es transitorio.

```python
except EgressBlocked:
    raise
except Exception as exc:
    retry_transient(exc)
```

---

## 10. Router seguro en cascada

### 10.1 Flujo

```text
1. Evaluar si el router externo está autorizado.
2. Si está autorizado, usar router externo full-context.
3. Si está bloqueado, usar router local determinístico.
4. Validar nuevamente el provider final.
5. Si ninguno está autorizado, bloquear.
6. Registrar todas las decisiones.
```

### 10.2 No fallback fijo

No usar:

```text
router bloqueado → Claude fijo
```

Usar:

```text
router bloqueado
→ router local
→ elegir entre providers autorizados
→ gate final
```

### 10.3 Router local v1

Orden de decisión simple:

1. providers explícitos del step/agente, si están autorizados;
2. `keyword_hints` fuertes;
3. `default_provider`, si está autorizado;
4. provider permitido más económico con capacidad suficiente;
5. provider permitido de mayor capacidad para tareas complejas;
6. bloqueo si no existe destino autorizado.

No implementar bandit antes de tener datos.

---

## 11. Invariantes

### Seguridad de borde

- **I1.** Sin política activa, ninguna llamada LLM con prompt/contexto sale por `BaseProvider`.
- **I2.** Un proyecto no puede enviar contexto a un provider con clearance inferior.
- **I3.** `blocked_providers` prevalece sobre clearance suficiente.
- **I4.** Si `allowed_providers` está definido, ningún otro provider es válido.
- **I5.** Nivel desconocido en sensibilidad o clearance bloquea.
- **I6.** Streaming no puede bypassear el gate.
- **I7.** El check de streaming es eager.
- **I8.** Providers no pueden sobreescribir `complete()` o `complete_stream()`.
- **I9.** Una denegación de política no se reintenta.
- **I10.** No existe fallback inseguro.

### Router y contexto

- **I11.** El router externo se evalúa como provider antes de construir/enviar payload.
- **I12.** Si el router externo está bloqueado, se usa router local, no provider fijo.
- **I13.** `similar_runs` no cruza proyectos salvo política explícita futura.
- **I14.** Todo context item enviado tiene un registro de lineage.
- **I15.** Contexto excluido o bloqueado no aparece en el prompt final.
- **I16.** Un secreto detectado eleva sensibilidad efectiva a `secret`.
- **I17.** La sensibilidad de un run no disminuye automáticamente.

### Ledger y outcome

- **I18.** Cada provider call genera un `decision_event` allowed/blocked.
- **I19.** Cada run completado genera al menos un `outcome_event` básico.
- **I20.** El ledger no almacena payload sensible completo.
- **I21.** Cada hash de evento valida contra el anterior si hash chaining está activo.
- **I22.** Un replay offline nunca llama a un provider externo.
- **I23.** En divergencias offline no se atribuye calidad al provider no ejecutado.

---

## 12. Validación empírica

### 12.1 Fase 0 — reproducibilidad remota

Antes de declarar implementación:

- publicar rama `feat/egress-gate` o equivalente;
- publicar commit SHA;
- incluir `orchestrator/egress.py`;
- incluir tests del gate;
- subir RFC-005 al repo;
- ejecutar CI o adjuntar log completo de pytest.

Criterio:

```text
Otra persona puede clonar, cambiar de rama y reproducir los tests.
```

### 12.2 Fase 1 — PoC de seguridad

Caso:

```text
project = restricted-project.example
sensitivity = restricted
router = deepseek
router.clearance = public
final default = claude
```

Resultados obligatorios:

```text
bytes enviados a DeepSeek como router = 0
bytes enviados a DeepSeek como provider final = 0
decision_event phase=router decision=blocked
router_mode=local
provider final autorizado
fallback inseguro = 0
```

### 12.3 Fase 2 — offline replay

```bash
ai-orchestrator router-eval --offline --limit 500
```

Elegibilidad:

- runs históricos `done`;
- task no vacía;
- excluir imports no comparables;
- contexto del proyecto disponible;
- no hacer llamadas de red.

Métricas:

```text
total_runs
eligible_runs
agreement_rate
disagreement_rate
rating_coverage
router_cost_usd_sum
wrong_rate_when_agree
wrong_rate_when_disagree_external
top_disagreement_patterns
```

Requisitos mínimos:

```text
N eligible >= 200
N divergencias >= 30 para análisis de divergencias
rating coverage >= 40% o >= 50 runs con rating
```

Interpretación:

- acuerdo no equivale a calidad;
- en divergencias, solo se conoce el outcome del provider realmente ejecutado;
- el replay decide si vale la pena un canary, no si el router local es superior.

### 12.4 Fase 3 — canary local

Asignación determinística:

```python
canary = stable_hash(project + task_hash) % 100 < 20
```

Elegibilidad:

- proyectos `internal`;
- provider permitido;
- no `forced_model`;
- no `restricted` o `secret` durante el primer canary;
- política y versión registradas.

Métricas:

```text
canary_runs
control_runs
local_wrong_rate
external_wrong_rate
local_partial_rate
external_partial_rate
rating_coverage_canary
rerun_rate_local
rerun_rate_external
manual_override_rate
cost_per_success_local
cost_per_success_external
```

Regla preliminar:

```text
Si rating_coverage < 40%:
    no decidir.

Si local_wrong_rate <= external_wrong_rate + 5 puntos porcentuales
Y cost_per_success_local < cost_per_success_external:
    promover router local por defecto.

Si local_wrong_rate empeora > 5 puntos porcentuales:
    conservar cascada o investigar metadata-only router.
```

### 12.5 Fase 4 — validación de valor

Después de 500 runs gobernados:

```text
egress_attempts_total
egress_blocked_total
router_egress_blocked_total
provider_egress_blocked_total
secret_escalation_total
cross_project_context_blocked_total
policy_false_positive_rate
manual_override_rate
cost_delta_due_to_policy
rerun_rate
```

Pregunta de supervivencia:

> **¿El sistema bloquea eventos reales, genera evidencia útil y mantiene calidad/costo aceptables?**

---

## 13. Métricas de producto

### 13.1 Seguridad

```text
blocked_sensitive_egress
blocked_router_calls
blocked_provider_calls
blocked_context_items
secret_escalations
unauthorized_provider_attempts
```

### 13.2 Operación

```text
policy_evaluation_latency_ms
false_positive_block_rate
manual_override_rate
runs_failed_closed
retry_suppressed_total
```

### 13.3 Calidad

```text
rating_coverage
wrong_rate_by_router_mode
partial_rate_by_router_mode
rerun_rate_by_router_mode
manual_provider_override_rate
```

### 13.4 Costo

```text
router_cost_usd_sum
cost_per_success
cost_delta_due_to_policy
cost_saved_by_removing_external_router
```

Solo se usa “cost_saved” cuando el contrafactual es observable o corresponde al costo explícito del router eliminado.

### 13.5 Evidencia/auditoría

```text
runs_with_complete_decision_chain
runs_with_complete_context_lineage
runs_with_outcome_event
ledger_hash_validation_rate
```

---

## 14. Simplicidad local

### 14.1 Regla de implementación

> Si una capacidad no puede explicarse en una línea del dashboard y probarse localmente, no entra en v1.

### 14.2 Dashboard mínimo

```text
Project: restricted-project.example
Sensitivity: restricted
Router external: deepseek → BLOCKED
Router mode: local
Provider final: claude → ALLOWED
Context items included: 5
Context items blocked: 2
Reason: provider clearance below project sensitivity
Bytes sent to DeepSeek: 0
Outcome: useful
Cost: $0.018
```

### 14.3 Policy-as-code simple

V1 usa YAML + Python.

OPA/Rego puede agregarse después como adapter opcional. No debe bloquear el MVP.

### 14.4 Secret scanner

No construir un DLP propio completo.

Estrategia:

```text
regex actual
+ adapter opcional detect-secrets/gitleaks
+ adapter opcional Presidio para PII
```

El gate consume un resultado normalizado:

```text
secret_detected: bool
categories: [...]
effective_sensitivity: secret
```

---

## 15. Sesgos y riesgos

### 15.1 Sesgo de novedad

Convergencia con FIDES, CaMeL, LiteLLM, Cloudflare y GAAT valida el criterio, no demuestra originalidad.

### 15.2 Sesgo de arquitectura

Una tesis elegante no prueba valor. La prueba son filas reales en `decision_events`, `context_lineage` y `outcome_events`.

### 15.3 Sesgo de observabilidad

Registrar mucho no significa gobernar. El gate debe actuar antes del egress.

### 15.4 Sesgo de seguridad

Más regex puede aumentar falsos positivos y provocar que el usuario desactive el sistema.

### 15.5 Sesgo de calidad

`rating` evalúa el resultado ejecutado y tiene cobertura incompleta. No es ground truth contrafactual.

### 15.6 Sesgo de mercado

El comprador enterprise exige SSO, RBAC, SIEM, SOC 2, soporte y contratos. El wedge inicial debe ser developer/tech lead/equipo pequeño.

### 15.7 Riesgo de sobreconstrucción

No agregar antes de 500 runs:

- bandits;
- semantic taint;
- memoria promovida;
- grafo externo;
- policy engine empresarial;
- marketplace de guardrails;
- multi-tenant SaaS.

---

## 16. Mercado y wedge inicial

### 16.1 Usuario inicial

```text
consultor
freelancer
tech lead
equipo pequeño
software factory con varios clientes
```

Problema:

> “Uso varios modelos y repos de clientes. Necesito saber qué salió, qué fue bloqueado, cuánto costó y por qué.”

### 16.2 No competir frontalmente

`ai-orchestrator` puede integrarse con:

- LiteLLM;
- Cloudflare AI Gateway;
- Portkey;
- OpenRouter;
- Ollama/vLLM;
- Langfuse/Phoenix mediante OpenTelemetry.

La política local ocurre antes de cualquiera de ellos.

### 16.3 Hipótesis de disposición a usar/pagar

Validación mínima:

```text
10 entrevistas con desarrolladores/tech leads
5 instalaciones reales
3 usuarios activos durante 2 semanas
2 equipos que exporten un reporte de auditoría
1 piloto pagado o carta explícita de intención
```

Sin esto, “mercado dispuesto” sigue siendo hipótesis.

---

## 17. Orden de implementación

```text
1. docs: publish RFC-005 and correct implementation status
2. feat: add fail-closed egress policy
3. refactor: seal provider boundary via template methods
4. feat: add project sensitivity and provider clearance
5. feat: add local deterministic router
6. fix: prevent router egress before policy evaluation
7. fix: restrict similar-runs to current project
8. feat: add secret escalation and sticky run sensitivity
9. fix: set policy inside background worker
10. fix: never retry EgressBlocked
11. feat: add decision_events
12. feat: add context_lineage
13. feat: add outcome_events
14. feat: add offline router evaluation
15. feat: export governance attributes via OpenTelemetry
16. feat: add canary router mode
```

No implementar los pasos 11–16 antes de que 2–10 estén estables.

---

## 18. Criterios de merge

### 18.1 A rama remota

- [ ] rama publicada y clonable;
- [ ] commit SHA registrado;
- [ ] RFC-005 incluido;
- [ ] `orchestrator/egress.py` presente;
- [ ] tests del gate presentes;
- [ ] log de pytest adjunto o CI visible.

### 18.2 A `production`

- [ ] PoC restricted demuestra cero bytes al provider bloqueado;
- [ ] router externo bloqueado usa router local;
- [ ] no existe fallback inseguro;
- [ ] streaming pasa por gate eager;
- [ ] worker establece política dentro del thread;
- [ ] `EgressBlocked` no se reintenta;
- [ ] `similar_runs` no cruza proyectos;
- [ ] decisiones allowed/blocked se registran sin payload;
- [ ] tests completos sin regresiones nuevas;
- [ ] estado del RFC coincide con el estado real del repo.

### 18.3 Para afirmar “joya validada”

- [ ] al menos 500 runs gobernados;
- [ ] al menos un bloqueo real reproducible;
- [ ] lineage completo en >= 95% de runs elegibles;
- [ ] outcome básico en >= 80% de runs;
- [ ] rating coverage >= 40% o alternativa implícita definida;
- [ ] costo y calidad comparados por router mode;
- [ ] al menos 3 usuarios externos activos.

---

## 19. Decisión final

La feature central inmediata sigue siendo:

> **Provider-Safe Routing.**

Pero el activo estratégico es:

> **Project-Scoped Governed Decision Provenance.**

El sistema debe poder responder, para cada run:

```text
¿Qué proyecto originó esta decisión?
¿Qué contexto se consideró?
¿Qué política se aplicó?
¿Qué fue permitido o bloqueado?
¿Qué router y provider se usaron?
¿Cuánto costó?
¿Funcionó?
¿Qué habría elegido el router local?
```

La frase central del proyecto queda:

> **No solo qué hizo el agente, sino qué podía enviar, por qué y si funcionó.**

---

## Apéndice A — Primera evidencia viva

```text
router_egress_blocked_total       > 0
fallback_inseguro                 = 0
bytes_a_provider_bloqueado        = 0
runs_with_complete_decision_chain > 0
```

Si después de una semana `router_egress_blocked_total = 0`, revisar:

1. no existen proyectos sensibles;
2. la política no se está cargando;
3. el gate no está corriendo;
4. los clearances son demasiado permisivos;
5. el flujo real no pasa por `ai-orchestrator`.

---

## Apéndice B — CLI propuesta

```bash
ai-orchestrator policy show <project>
ai-orchestrator policy test <project> --provider deepseek
ai-orchestrator egress recent --project <project>
ai-orchestrator lineage show <run_id>
ai-orchestrator decision verify-chain
ai-orchestrator router-eval --offline --limit 500
ai-orchestrator router-canary status
ai-orchestrator audit export --project <project> --format json
```

---

## Apéndice C — Atributos OpenTelemetry propuestos

```text
ai.project.name
ai.project.sensitivity
ai.policy.version
ai.egress.phase
ai.egress.decision
ai.egress.reason_code
ai.provider.name
ai.provider.clearance
ai.router.mode
ai.context.item_count
ai.context.blocked_count
ai.context.source_types
ai.outcome.rating
ai.outcome.rerun
ai.outcome.manual_override
```

No incluir contenido sensible en atributos.

---

## Apéndice D — Referencias verificadas

1. Costa et al. **Securing AI Agents with Information-Flow Control (FIDES)**. 2025.  
   <https://arxiv.org/abs/2505.23643>

2. Debenedetti et al. **Defeating Prompt Injections by Design (CaMeL)**. 2025.  
   <https://arxiv.org/abs/2503.18813>

3. Ojewale, Suresh, Venkatasubramanian. **Audit Trails for Accountability in Large Language Models**. 2026.  
   <https://arxiv.org/abs/2601.20727>

4. Wang et al. **From Agent Traces to Trust: Evidence Tracing and Execution Provenance in LLM Agents**. 2026.  
   <https://arxiv.org/abs/2606.04990>

5. Pathak, Jain. **Governance-Aware Agent Telemetry for Closed-Loop Enforcement in Multi-Agent AI Systems**. 2026.  
   <https://arxiv.org/abs/2604.05119>

6. Feng et al. **Get Experience from Practice: LLM Agents with Record & Replay (AgentRR)**. 2025.  
   <https://arxiv.org/abs/2505.17716>

7. LiteLLM. **Sensitive Data Routing (Built-in Guardrail)**.  
   <https://docs.litellm.ai/docs/proxy/guardrails/sensitive_data_routing>

8. Cloudflare. **AI Gateway: Coding agents**.  
   <https://developers.cloudflare.com/ai-gateway/integrations/coding-agents/>

9. Cloudflare. **AI Gateway: Data Loss Prevention**.  
   <https://developers.cloudflare.com/ai-gateway/features/dlp/>

10. OpenTelemetry. **Generative AI semantic conventions**.  
    <https://opentelemetry.io/docs/specs/semconv/gen-ai/>

---

## Apéndice E — Evolución de los RFC

| RFC | Aporte central | Corrección posterior |
|---|---|---|
| 001 | Detecta pre-routing egress y propone fail-closed | No cubría streaming directo ni estado de implementación |
| 002 | Sella `BaseProvider` y agrega secret escalation | No cubría ejecución eager/threads |
| 003 | Corrige streaming, threads y replay offline | No cubría retry de denegación ni joya completa |
| 004 | Agrega no-retry y formaliza experimento | Mezcló evidencia local con estado remoto y centró el valor en el gate |
| 005 | Define governed decision provenance y separa seguridad, evidencia y outcome | Debe validarse con implementación pública y 500 runs reales |

