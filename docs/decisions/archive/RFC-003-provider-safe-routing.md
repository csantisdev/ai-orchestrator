# RFC-003: Egress Gate + Provider-Safe Routing para `ai-orchestrator`

**Estado:** propuesta actualizada post-validación cruzada.  
**Fecha:** 2026-07-09.  
**Supersede:** RFC-002 `Egress Gate para ai-orchestrator`.  
**Destino recomendado:** rama `feat/egress-gate`, no merge directo a `production`.  
**Objetivo:** cerrar fuga de contexto antes del routing externo, mantener el modelo de costos mediante router local determinístico y cuantificar si el router externo aporta valor suficiente para seguir vivo.

---

## 0. Resumen ejecutivo

El hallazgo central sigue siendo válido:

> El router externo es el primer egress real. Hoy puede recibir contexto sensible antes de que exista una decisión de proveedor.

El RFC-002 corrigió bien la dirección de seguridad: un **egress gate fail-closed** en el borde de providers. La validación cruzada agrega tres ajustes obligatorios:

1. **El alcance de I1 debe acotarse.** El gate protege egress de prompts/contexto LLM. El repo también tiene `model_discovery` con HTTP directo; no filtra contexto de proyecto, pero sí es egress externo. Debe clasificarse como fuera de alcance o cubrirse por una política separada.
2. **El experimento §5 no debe llamar al router externo en proyectos donde la política lo bloquea.** La comparación correcta parte con **offline replay histórico**, sin red, sin costo y sin riesgo.
3. **La calidad del router local no es observable en divergencias offline.** Si el router externo eligió Claude y el router local habría elegido OpenAI, el rating real solo evalúa Claude. Para medir calidad real del router local se necesita una fase posterior de **canary controlado**.

Decisión actualizada:

```text
External full-context router  → solo si pasa egress policy.
Si no pasa                   → router local determinístico.
Metadata-only router          → solo shadow/canary futuro, no producción.
```

---

## 1. Cambio de versión: RFC-002 → RFC-003

### 1.1 Cambios incorporados

| Área | RFC-002 | RFC-003 |
|---|---|---|
| Alcance de I1 | “Sin política, ninguna llamada sale” | “Sin política, ninguna llamada LLM con prompt/contexto sale por `BaseProvider`” |
| Discovery de modelos | No tratado | Clasificado como egress externo no contextual; issue separado |
| Experimento §5 | Shadow local vs router externo en proyectos internal | Offline replay histórico primero; canary local después |
| Métrica de calidad | `agreement_rate`, `local_quality`, `external_quality` | Se separa acuerdo de calidad; se declara contrafactual no observable en divergencias |
| Router bloqueado | Riesgo de fallback fijo a Claude | Router local determinístico obligatorio |
| Merge | Patch implementado y verificado | Merge solo a rama; production condicionado a criterios cuantificables |
| Métricas | Primeras métricas vivas | Métricas de seguridad, costo, calidad y contrafactual económico |
| DB | `egress_decisions` como criterio | Se agrega propuesta concreta de `egress_decisions` y `router_shadow_decisions` |

### 1.2 Decisión explícita

Este RFC ya no busca demostrar originalidad académica. Busca validar un producto operativo:

> `ai-orchestrator` como control plane local-first para agentes de desarrollo multi-proveedor, con egress gate determinístico antes de cualquier salida de prompt/contexto hacia un LLM.

---

## 2. Problema validado contra repo real

### 2.1 Pre-routing egress

El router actual arma un prompt con datos del proyecto y de la tarea antes de decidir proveedor:

```text
Proyecto
Stack
Descripción
Convenciones
Notas de ruteo
Proveedor por defecto
Contexto activo
Señales detectadas
similar_runs
Tarea completa
```

Luego llama al proveedor router:

```python
router = build_provider(config, router_provider_name)
result = router.complete(prompt=prompt, system=ROUTER_SYSTEM_PROMPT)
```

Como el `config.example.yaml` usa DeepSeek como router por defecto, DeepSeek puede recibir contexto antes de que exista una decisión final de routing.

### 2.2 Cross-project leak en `similar_runs`

`_fetch_similar_runs()` consulta similitud de manera global y agrega:

```text
project
provider
routing_reason
task_preview
rating
```

Luego `_build_router_prompt()` formatea:

```text
[project] → provider: "routing_reason"
```

Si una tarea de proyecto A recupera runs similares de proyecto B, el router externo recibe nombres y razones de ruteo de otro proyecto.

### 2.3 Severidad

```text
Severity: High
Tipo: Sensitive context egress before policy enforcement
Vector: router LLM call
Scope: project metadata, task text, routing notes, active context, similar runs
Default affected config: router.provider = deepseek
Impact: sensitive project context can reach a provider before provider policy is evaluated
```

No se clasifica como `critical` aún porque no se demostró exfiltración de secretos reales tipo `.env` en el PoC. Pero el diseño permite egress sensible por defecto.

---

## 3. Alcance de seguridad actualizado

### 3.1 Dentro de alcance

Este RFC cubre:

```text
- prompts enviados a providers LLM
- system prompts
- streaming prompts
- router prompts
- RAG/context blocks agregados al prompt
- task text
- project context usado para ruteo o respuesta
```

### 3.2 Fuera de alcance, pero auditado

El repo tiene `model_discovery` con llamadas HTTP directas a APIs de proveedores para listar modelos. Esto no envía contexto de proyecto ni prompt, pero sí es egress externo.

Decisión RFC-003:

```text
model_discovery = egress externo no contextual
No bloquea este RFC.
Debe abrirse issue separado:
  audit: classify model discovery under non-contextual egress policy
```

### 3.3 Frase corregida de I1

Antes:

```text
Sin política, ninguna llamada sale.
```

Ahora:

```text
Sin política activa, ninguna llamada LLM con prompt/contexto sale por BaseProvider.
```

Si se quiere cubrir absolutamente todo egress externo, `model_discovery` y cualquier `httpx.*` fuera de providers deben pasar por un segundo gate. Ese es otro RFC.

---

## 4. Diseño actualizado

### 4.1 Fail-closed por construcción

La política no debe ser un parámetro opcional en cada call site. Debe vivir en un `ContextVar` sin default:

```python
_POLICY: ContextVar[EgressPolicy] = ContextVar("egress_policy")


def current_policy() -> EgressPolicy:
    try:
        return _POLICY.get()
    except LookupError as exc:
        raise EgressBlocked("No active egress policy") from exc
```

Si se olvida setear política, el sistema falla cerrado.

### 4.2 Borde sellado en `BaseProvider`

El gate debe vivir en el borde común, no en `cli.py`, `background.py` o `router.py`.

Patrón:

```python
class BaseProvider(ABC):
    def complete(self, prompt: str, system: str = "") -> CompletionResult:
        check_egress(prompt=prompt, system=system, phase="provider")
        return self._complete(prompt, system)

    def complete_stream(self, prompt: str, system: str = ""):
        check_egress(prompt=prompt, system=system, phase="stream")
        return self._complete_stream(prompt, system)

    @abstractmethod
    def _complete(self, prompt: str, system: str = "") -> CompletionResult:
        ...

    def _complete_stream(self, prompt: str, system: str = ""):
        result = self._complete(prompt, system)
        yield result.text
        return result.to_stream_result()
```

Crítico: `complete_stream()` no debe ser un generator method si el check queda antes del `yield`, porque en Python el código del generator se ejecuta recién al iterar. Debe ser método normal que retorna un generator.

### 4.3 Impedir override del borde

```python
def __init_subclass__(cls, **kwargs):
    super().__init_subclass__(**kwargs)
    for method in ("complete", "complete_stream"):
        if method in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} must implement _{method}(), not {method}(). "
                "The egress boundary is sealed."
            )
```

Esto convierte la política en contrato de clase, no en disciplina humana.

### 4.4 Router externo como provider normal

El router externo no es un componente interno. Si llama a un LLM remoto, es un provider externo.

Regla:

```text
Antes de construir/enviar prompt full-context al router externo:
  validar si el router provider tiene clearance suficiente para ver ese contexto.
```

Si no pasa:

```text
no llamar al router externo
usar router local determinístico
```

No usar fallback fijo a Claude salvo que el router local elija Claude y Claude pase política.

---

## 5. Política de sensibilidad y routing

### 5.1 Lattice inicial

```python
SENSITIVITY_RANK = {
    "public": 0,
    "internal": 1,
    "restricted": 2,
    "secret": 3,
}
```

Nivel desconocido bloquea:

```text
project.sensitivity desconocida → EgressBlocked
provider.clearance desconocido  → EgressBlocked
```

### 5.2 Evaluación de proveedor

Un provider pasa si:

```text
provider.clearance >= project.sensitivity
AND provider not in project.blocked_providers
AND, si project.allowed_providers no está vacío, provider in project.allowed_providers
```

Clearance no basta. Un proveedor puede tener clearance suficiente y aun así estar bloqueado por contrato, cliente o decisión del proyecto.

### 5.3 Secreto en payload escala sensibilidad efectiva

El repo ya tiene detección de secretos en RAG/indexación. RFC-003 la reutiliza antes del egress final:

```text
if secret pattern detected in prompt + system:
    effective_sensitivity = secret
```

Esto no es taint semántico. Es higiene mínima.

Ejemplo de bloqueo esperado:

```text
project.sensitivity = internal
provider.clearance = internal
payload contiene DB_PASSWORD=
→ effective_sensitivity = secret
→ provider no tiene clearance secret
→ EgressBlocked
```

No guardar payload en logs. Solo guardar razón:

```text
reason = "secret_pattern_detected"
```

---

## 6. Router seguro en cascada

### 6.1 Flujo final

```text
1. Calcular política efectiva del proyecto.
2. Verificar si el router externo puede recibir full-context.
3. Si puede:
     usar external full-context router.
4. Si no puede:
     usar local deterministic router.
5. Validar provider final con la misma política.
6. Si provider final no pasa:
     EgressBlocked.
7. Loguear decisión en egress_decisions.
```

### 6.2 Pseudocódigo

```python
def decide_provider(task: str, ctx: ProjectContext, config: dict) -> RoutingDecision:
    router_provider = get_router_config(config).get("provider", "deepseek")

    router_check = can_send_project_context(ctx, config, router_provider, phase="router")

    if router_check.allowed:
        decision = decide_with_external_router(task, ctx, config)
        source = "external_router"
    else:
        log_egress_decision(
            project=ctx.name,
            provider=router_provider,
            phase="router",
            decision="blocked",
            reason=router_check.reason,
        )
        decision = decide_with_local_router(task, ctx, config)
        source = "local_router"

    final_check = can_send_project_context(ctx, config, decision.provider, phase="provider")
    if not final_check.allowed:
        raise EgressBlocked(
            f"Router source={source} chose blocked provider={decision.provider}: {final_check.reason}"
        )

    decision.reason = f"{decision.reason} [router_source={source}]"
    return decision
```

### 6.3 Local deterministic router v1

Orden simple:

```text
1. Construir lista de providers permitidos.
2. Si no hay ninguno → EgressBlocked.
3. Si ctx.default_provider está permitido → usarlo.
4. Si keyword_hints apuntan a provider permitido → usarlo.
5. Si tarea es simple/barata → elegir provider permitido más barato.
6. Si tarea parece crítica/compleja → elegir provider permitido de mayor calidad configurada.
```

La v1 no necesita ML. Necesita ser segura, barata y explicable.

---

## 7. Invariantes actualizadas

| ID | Invariante | Estado esperado |
|---|---|---|
| I1 | Sin política activa, ninguna llamada LLM con prompt/contexto sale por `BaseProvider` | obligatoria |
| I2 | Proyecto `restricted` no llega a provider `public` | obligatoria |
| I3 | `blocked_providers` gana sobre clearance suficiente | obligatoria |
| I4 | `allowed_providers`, si existe, restringe la salida | obligatoria |
| I5 | Streaming no bypassea gate | obligatoria |
| I6 | Provider nuevo no puede sobreescribir `complete()` ni `complete_stream()` | obligatoria |
| I7 | Router externo bloqueado usa router local, no fallback fijo | obligatoria |
| I8 | No hay fallback inseguro | obligatoria |
| I9 | Typo/valor desconocido en sensibilidad o clearance bloquea | obligatoria |
| I10 | `similar_runs` no cruza proyectos | obligatoria |
| I11 | Secreto en prompt/system escala a `secret` | obligatoria v1.1, ideal v1 |
| I12 | Logs de egress no guardan payload sensible | obligatoria |

I1 queda acotada a prompt/context egress. `model_discovery` queda como issue separado si no se integra en este gate.

---

## 8. Validación cruzada de riesgos

### 8.1 Riesgo: ContextVar + threads

`ContextVar` no propaga automáticamente a `threading.Thread` nuevo. Como `background.py` crea threads, la política debe setearse dentro del worker, no solo en el thread padre.

Correcto:

```text
submit_run() crea thread
_worker() carga ctx
_worker() construye/setea EgressPolicy
_worker() decide_provider()
_worker() provider.complete_stream()
```

Incorrecto:

```text
submit_run() setea policy
thread nuevo espera heredarla
_worker() no la ve
```

Si no la ve y lanza `EgressBlocked`, ese es el fallo correcto. Pero producción debe tener test específico para evitar sorpresa.

Tests:

```text
test_background_worker_sets_policy_inside_thread
test_policy_set_in_parent_thread_does_not_silently_allow_worker_egress
```

### 8.2 Riesgo: discovery HTTP fuera del borde

No filtra prompt, pero sí es egress externo. No bloquear RFC, pero documentar.

Issue:

```text
audit: classify model discovery as non-contextual egress
```

### 8.3 Riesgo: post-filter en similar_runs pierde recall

Fix v1:

```text
query global → filtrar row.project == ctx.name
```

Seguro, pero puede devolver 0 resultados aunque existan buenos runs del mismo proyecto más abajo.

Fix v2:

```text
Chroma: where={"project": ctx.name}
FTS5: WHERE runs.project = ?
```

V1 no bloquea merge; V2 queda como mejora.

### 8.4 Riesgo: RAG con secretos accidentales

RAG agrega contexto al `system_prompt`. Si un fragmento contiene secreto, el gate por proyecto puede no bastar. Por eso I11 escala sensibilidad efectiva al inspeccionar payload.

### 8.5 Riesgo: reasons demasiado informativos

`egress_decisions.reason` no debe incluir payload, fragmentos de prompt, endpoints sensibles ni claves. Solo códigos:

```text
provider_clearance_too_low
project_blocked_provider
provider_not_in_allowed_list
unknown_sensitivity
unknown_clearance
secret_pattern_detected
no_policy_active
```

---

## 9. Modelo de datos propuesto

### 9.1 Tabla `egress_decisions`

```sql
CREATE TABLE IF NOT EXISTS egress_decisions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    project     TEXT NOT NULL,
    provider    TEXT NOT NULL,
    model       TEXT,
    phase       TEXT NOT NULL, -- router | provider | stream | discovery_future
    decision    TEXT NOT NULL, -- allowed | blocked
    reason      TEXT NOT NULL,
    sensitivity TEXT,
    clearance   TEXT,
    run_id      INTEGER REFERENCES runs(id),
    tokens_estimate INTEGER
);

CREATE INDEX IF NOT EXISTS idx_egress_project_ts ON egress_decisions(project, ts DESC);
CREATE INDEX IF NOT EXISTS idx_egress_decision ON egress_decisions(decision, phase);
```

### 9.2 Tabla `router_shadow_decisions`

Para evaluar router local vs router externo sin afectar producción:

```sql
CREATE TABLE IF NOT EXISTS router_shadow_decisions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                 TEXT NOT NULL,
    run_id             INTEGER REFERENCES runs(id),
    project            TEXT NOT NULL,
    external_provider  TEXT NOT NULL,
    local_provider     TEXT NOT NULL,
    agreed             INTEGER NOT NULL,
    external_reason    TEXT NOT NULL DEFAULT '',
    local_reason       TEXT NOT NULL DEFAULT '',
    router_cost_usd    REAL,
    rating             TEXT
);

CREATE INDEX IF NOT EXISTS idx_router_shadow_project_ts ON router_shadow_decisions(project, ts DESC);
CREATE INDEX IF NOT EXISTS idx_router_shadow_agreed ON router_shadow_decisions(agreed);
```

Nota: `rating` puede copiarse al momento del análisis o resolverse vía join con `runs`. Si se copia, debe actualizarse cuando el usuario califique.

---

## 10. Validación cuantitativa

### 10.1 Métricas de seguridad

```text
egress_attempts_total
egress_allowed_total
egress_blocked_total
router_egress_blocked_total
provider_egress_blocked_total
streaming_egress_blocked_total
secret_payload_blocked_total
cross_project_similar_runs_blocked_total
```

Fórmulas:

```text
router_external_block_rate = router_egress_blocked_total / router_egress_attempts_total
provider_block_rate        = provider_egress_blocked_total / provider_egress_attempts_total
secret_block_rate          = secret_payload_blocked_total / egress_attempts_total
```

### 10.2 Métricas de costo

```text
external_router_calls_total
local_router_calls_total
external_router_spend_usd
estimated_router_spend_avoided_usd
cost_per_success_by_provider
```

La métrica real para borrar router externo:

```text
external_router_spend_usd = SUM(runs.router_cost_usd)
```

Si el router externo se elimina, ese es el ahorro directo observable.

No inventar:

```text
cost_saved_by_local_router_usd
```

si no se tiene contrafactual real de calidad/costo por provider alternativo.

### 10.3 Métricas de calidad

```text
rating_coverage
agreement_rate
wrong_rate_when_agree
wrong_rate_when_disagree_external
partial_rate_when_agree
partial_rate_when_disagree_external
rerun_rate_by_router_mode
manual_override_rate_by_router_mode
```

Advertencia:

```text
En offline replay, las divergencias no miden calidad del router local.
Solo miden qué habría elegido distinto.
La calidad real del local router requiere canary.
```

---

## 11. Experimento actualizado

### 11.1 Fase A — Offline replay histórico

No llama APIs. No envía contexto. No cuesta.

Entrada:

```sql
SELECT id, project, task, provider, routing_reason, rating, router_cost_usd
FROM runs
WHERE status = 'done'
  AND task != ''
  AND provider NOT IN ('claude-code', 'codex', 'git')
ORDER BY ts DESC;
```

Para cada run:

```text
external_choice = runs.provider
local_choice    = decide_with_local_router(task, ctx, config)
agreed          = external_choice == local_choice
```

Salida:

```text
total_runs
agreement_rate
disagreement_rate
rating_coverage
external_router_spend_usd
wrong_rate_when_agree
wrong_rate_when_disagree_external
partial_rate_when_agree
partial_rate_when_disagree_external
```

Comando sugerido:

```bash
ai-orchestrator router-eval --offline --limit 500
```

Criterios mínimos para decisión:

```text
N total >= 200
rating_coverage >= 40% o al menos 50 ratings humanos
N divergencias >= 30 para analizar desacuerdos
```

### 11.2 Regla de decisión Fase A

```text
Si agreement_rate >= 0.90:
    router local es candidato fuerte a default.
    Pasar a canary local pequeño.

Si 0.80 <= agreement_rate < 0.90:
    mantener cascada.
    Pasar a canary local 10–20% en proyectos no sensibles.

Si agreement_rate < 0.80:
    no borrar router externo.
    Mejorar local router o evaluar metadata-only router.
```

No decidir solo con `rating` en divergencias, porque mide el provider ejecutado, no el local no ejecutado.

### 11.3 Fase B — Canary local

Solo después de Fase A.

```text
10% de runs no restricted usan local router real.
90% siguen con cascada actual.
```

Métricas:

```text
local_wrong_rate
external_wrong_rate
local_partial_rate
external_partial_rate
rerun_rate_after_local
rerun_rate_after_external
cost_per_success_local
cost_per_success_external
```

Regla:

```text
Si local_wrong_rate <= external_wrong_rate + 5 puntos porcentuales
Y costo baja:
    local router default.

Si local_wrong_rate empeora entre 5 y 10 puntos:
    mantener canary y mejorar heurísticas.

Si local_wrong_rate empeora > 10 puntos:
    conservar cascada y evaluar metadata-only router.
```

### 11.4 Fase C — Metadata-only router en shadow

Solo si local router no alcanza.

Payload permitido:

```json
{
  "task_family": "backend_debugging",
  "language_family": "php",
  "framework_family": "laravel",
  "estimated_complexity": "medium",
  "requires_security_review": true,
  "project_sensitivity": "restricted",
  "raw_task_included": false,
  "project_name_included": false,
  "domain_keywords_included": false
}
```

Prohibido:

```text
nombre del proyecto
texto de tarea
endpoints
identificador personal
nombres de clientes
fragmentos de código
routing_notes
similar_runs
```

---

## 12. SQL de métricas iniciales

### 12.1 Bloqueos por fase

```sql
SELECT phase, decision, COUNT(*) AS total
FROM egress_decisions
GROUP BY phase, decision
ORDER BY phase, decision;
```

### 12.2 Top proyectos bloqueados

```sql
SELECT project, provider, phase, COUNT(*) AS blocked
FROM egress_decisions
WHERE decision = 'blocked'
GROUP BY project, provider, phase
ORDER BY blocked DESC
LIMIT 20;
```

### 12.3 Router externo: gasto observable

```sql
SELECT
  COUNT(*) AS runs_with_router_cost,
  ROUND(SUM(COALESCE(router_cost_usd, 0)), 6) AS external_router_spend_usd
FROM runs
WHERE status = 'done'
  AND provider NOT IN ('claude-code', 'codex', 'git');
```

### 12.4 Agreement local vs externo

```sql
SELECT
  COUNT(*) AS total,
  ROUND(100.0 * SUM(CASE WHEN agreed = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS agreement_pct,
  ROUND(SUM(COALESCE(router_cost_usd, 0)), 6) AS router_spend_usd
FROM router_shadow_decisions;
```

### 12.5 Rating coverage

```sql
SELECT
  COUNT(*) AS total,
  SUM(CASE WHEN rating IS NOT NULL THEN 1 ELSE 0 END) AS rated,
  ROUND(100.0 * SUM(CASE WHEN rating IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS rating_coverage_pct
FROM router_shadow_decisions;
```

---

## 13. Orden de commits actualizado

```text
1. feat: add fail-closed egress policy
   - egress.py
   - EgressPolicy, EgressBlocked, can_send(), check()
   - ContextVar sin default
   - unknown sensitivity/clearance fail-closed

2. refactor: seal provider boundary via template methods
   - BaseProvider.complete() concreto
   - BaseProvider.complete_stream() concreto, no generator-wrapper
   - providers implementan _complete() / _complete_stream()
   - __init_subclass__ bloquea override de complete/complete_stream

3. feat: add project sensitivity and provider clearance
   - ProjectContext.sensitivity default internal
   - allowed_providers / blocked_providers
   - config.example.yaml con clearance por provider

4. feat: add local deterministic router
   - decide_with_local_router()
   - respeta allowed/blocked/clearance
   - no usa red
   - reason explicable

5. fix: prevent router egress before policy evaluation
   - router externo solo si pasa can_send()
   - si bloqueado, usar local router
   - no fallback fijo a Claude
   - si local elige bloqueado, EgressBlocked

6. fix: restrict router similar-runs to current project
   - _fetch_similar_runs(task, project, n)
   - filtro row["project"] == project

7. feat: escalate effective sensitivity on secret in payload
   - prompt + system scan
   - reason secret_pattern_detected
   - no payload logging

8. feat: log egress decisions
   - egress_decisions
   - phase router/provider/stream
   - decision allowed/blocked

9. feat: add offline router evaluation
   - router-eval --offline
   - router_shadow_decisions
   - report agreement/cost/rating coverage
```

Corrección crítica respecto a planes previos: el router local debe existir antes del fix que lo invoca.

---

## 14. Tests obligatorios

### 14.1 Egress core

```text
test_no_policy_blocks_provider_complete
test_no_policy_blocks_provider_stream
test_restricted_project_blocks_public_provider
test_blocked_provider_overrides_clearance
test_allowed_providers_restricts_even_with_clearance
test_unknown_project_sensitivity_fails_closed
test_unknown_provider_clearance_fails_closed
test_secret_payload_escalates_to_secret_and_blocks
test_egress_log_does_not_store_payload
```

### 14.2 Provider boundary

```text
test_provider_cannot_override_complete
test_provider_cannot_override_complete_stream
test_complete_invokes_check_before__complete
test_complete_stream_invokes_check_before__complete_stream
test_streaming_http_not_reached_when_blocked
```

### 14.3 Router

```text
test_external_router_allowed_when_clearance_sufficient
test_external_router_blocked_uses_local_router
test_external_router_blocked_does_not_call_provider
test_local_router_never_returns_blocked_provider
test_no_provider_available_raises_egress_blocked
test_no_fixed_claude_fallback_when_router_blocked
test_similar_runs_are_project_scoped
test_router_prompt_does_not_include_cross_project_runs
```

### 14.4 Background/threading

```text
test_background_worker_sets_policy_inside_thread
test_parent_thread_policy_does_not_silently_allow_worker_egress
test_background_streaming_blocked_before_http
```

### 14.5 Quantification

```text
test_router_eval_offline_does_not_call_external_provider
test_router_eval_records_agreement
test_router_eval_reports_rating_coverage
test_router_eval_reports_external_router_spend
```

---

## 15. Criterios de merge

### 15.1 A rama `feat/egress-gate`

Puede mergearse a rama si:

```text
- tests de egress core pasan
- provider boundary sellado
- router externo bloqueado usa router local
- no fallback fijo a Claude
- similar_runs scoped por proyecto
- egress_decisions registra allowed/blocked sin payload
```

### 15.2 A `production`

No mergear a `production` hasta cumplir:

```text
1. pytest tests/ -q no introduce fallos nuevos.
2. PoC restricted-project demuestra cero bytes a DeepSeek.
3. Streaming bloqueado no toca httpx.stream.
4. Router bloqueado no llama a proveedor externo.
5. No hay fallback inseguro.
6. egress_decisions muestra phase=router decision=blocked para el PoC.
7. router-eval --offline corre sobre al menos 200 runs o reporta muestra insuficiente.
8. Documentado alcance de model_discovery.
```

---

## 16. PoC obligatoria

### 16.1 Config

```yaml
providers:
  deepseek:
    model: deepseek-v4-flash
    clearance: public
  claude:
    model: claude-sonnet
    clearance: restricted

router:
  provider: deepseek
  fallback_provider: claude
```

### 16.2 Proyecto sensible

```yaml
name: restricted-project.example
sensitivity: restricted
blocked_providers:
  - deepseek
  - gemini
preferred_models:
  default: claude
```

### 16.3 Resultado esperado

```text
- DeepSeek no recibe bytes como router.
- DeepSeek no recibe bytes como provider final.
- Se registra egress_decision phase=router decision=blocked provider=deepseek.
- Router local elige Claude por política/default.
- Si Claude no está disponible o no tiene clearance, EgressBlocked.
```

---

## 17. Dashboard mínimo

Primera versión:

```text
Egress inspected: N
Allowed: N
Blocked: N
Router blocked: N
Provider blocked: N
Stream blocked: N
Secret payload blocked: N
Top blocked projects
Top blocked providers
External router spend USD
Local router usage
Agreement rate offline
Rating coverage
```

La primera métrica viva:

```text
router_egress_blocked_total > 0
fallback_inseguro = 0
bytes_a_deepseek_en_restricted_project = 0
```

Si `router_egress_blocked_total = 0` después de una semana:

```text
- no hay proyectos sensibles/internal que bloqueen router public,
- o el gate no está corriendo,
- o la configuración no está aplicando sensitivity/clearance.
```

Las tres opciones merecen inspección.

---

## 18. Riesgos residuales

| Riesgo | Severidad | Mitigación |
|---|---:|---|
| `model_discovery` fuera del gate | Baja/media | clasificar como non-contextual egress; issue separado |
| secreto no detectado por regex | Alta | v1.1 secret scanner mejorado; nunca log payload |
| metadata-only router reconstruye dominio sensible | Media/alta | shadow only; payload con allowlist estricta |
| local router degrada calidad | Media | offline replay + canary |
| demasiados bloqueos elevan costo | Media | medir router_external_block_rate y local router cost |
| `ContextVar` mal seteado en worker | Alta | tests threading específicos; set policy dentro de worker |
| post-filter de similar_runs reduce recall | Baja/media | v2 con query scoped por proyecto |
| reason logs filtran detalles | Media | reason codes, no texto libre sensible |

---

## 19. Fuera de alcance

No implementar en esta fase:

```text
- memoria semántica
- promotion gates
- evidence lattice
- memoria negativa
- bandits
- reward diferido
- metadata-only router en producción
- provider profiles por tier
- taint tracking semántico
- declassification humana
- políticas enterprise/SOC2
```

El objetivo de esta fase es más pequeño:

```text
cerrar egress pre-routing
preservar costo con router local
medir si external router aporta valor
```

---

## 20. Veredicto final RFC-003

```text
Revert: no.
Merge directo a production: no.
Merge a rama feat/egress-gate: sí.
Condición para production: PoC + tests + offline replay + métricas mínimas.
```

La decisión de producto no se toma por argumento, sino por datos:

```text
Si local router coincide mucho y no empeora calidad en canary:
    borrar router externo por defecto.

Si local router no alcanza:
    mantener cascada y evaluar metadata-only router.

Si el gate bloquea eventos reales sin subir costo de forma absurda:
    hay producto.

Si no bloquea nada en uso real:
    queda como hardening útil, no como feature central.
```

---

## Apéndice A: comando sugerido para implementación

```bash
git checkout -b feat/egress-gate
pytest tests/ -q
pytest tests/test_egress.py -q
pytest tests/test_router_egress.py -q
pytest tests/test_providers.py -q
ai-orchestrator router-eval --offline --limit 500
```

---

## Apéndice B: prompt para Claude Code

```text
Actualiza el RFC-002 a RFC-003 e implementa egress gate con router seguro en cascada.

Puntos obligatorios:
- Scope I1: solo prompt/context egress por BaseProvider.
- model_discovery queda clasificado como non-contextual egress fuera de alcance, con issue separado.
- BaseProvider debe sellar complete() y complete_stream().
- Providers implementan _complete() y _complete_stream().
- complete_stream() no debe ser generator-wrapper con check diferido.
- ProjectContext agrega sensitivity, allowed_providers, blocked_providers.
- Providers agregan clearance.
- Router externo full-context solo corre si pasa policy.
- Si router externo está bloqueado, usar decide_with_local_router().
- No fallback fijo a Claude.
- similar_runs scoped por proyecto.
- Secret scan en prompt+system escala sensitivity efectiva a secret.
- egress_decisions registra phase, decision, reason, project, provider, sensitivity, clearance; nunca payload.
- Implementar router-eval --offline para comparar provider histórico vs local router sin red.

No implementar:
- bandits
- metadata-only router en producción
- memory claims
- taint semántico
- provider profiles por tier

Criterio de aceptación:
- tests egress/router/providers pasan
- PoC restricted-project no envía bytes a DeepSeek
- router-eval offline corre sin llamadas externas
```
