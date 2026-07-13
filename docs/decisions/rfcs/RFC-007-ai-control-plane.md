# RFC-007 — Local AI Control Plane: Plan de Implementación Definitivo

**Estado:** Draft para ejecución (Codex)
**Versión:** 0.9 (revisión 2)
**Fecha:** 2026-07-12
**Repo de referencia:** `csantisdev/ai-orchestrator@production` = `4ae94970516d26a69e934cdd480e1634384ff5f1` (verificado 2026-07-12)
**Relación con la serie:** sucede a RFC-007 v0.3. No cubre MCP — eso es RFC-008 v0.1. **Incorpora el hallazgo de la serie RFC-001…006** (`RFC-egress-gate.md`, `RFC-002…006-*.md`), aportada por el usuario después de la primera redacción de este documento — ver Changelog.
**Destinatario de ejecución:** extensión Codex de VS Code, PR por PR, en el orden de la Parte II.

---

## Changelog

### v0.3 → v0.9 (revisión 1, primera redacción de este documento)

Convirtió el roadmap de 6 fases de v0.3 en un plan ejecutable PR-por-PR, verificado contra código real. En ese momento **RFC-006 no era accesible**: la Parte II de la revisión 1 diseñaba un `EgressPolicy`/`gateway.governed_complete()` propio, sin saber que ya existía un diseño distinto, más maduro y validado localmente (15 tests, patch +512/−28) en la serie RFC-001…006.

### v0.9 revisión 1 → v0.9 revisión 2 (esta versión)

El usuario agregó al repo `RFC-egress-gate.md` (ronda 0) y `RFC-002` a `RFC-006` — la serie completa de diseño y validación local del gate, nunca publicada (`git push -u origin feat/egress-gate` sigue sin ejecutarse). Esto cambia la Parte II de forma sustancial:

| Área | Rev. 1 (inventado) | Rev. 2 (RFC-006, validado localmente) |
|---|---|---|
| Módulo de política | `orchestrator/egress.py` con `PolicyDecision`/`PolicyError`/`evaluate(project_path, provider, phase)` | `orchestrator/egress.py` con `ContextVar[EgressPolicy]` sin default, `EgressBlocked`, `check()` (bloquea) / `can_send()` (consulta) |
| Punto de sellado | `orchestrator/gateway.py::governed_complete()` — wrapper que cada call site debe recordar usar | `BaseProvider.complete()`/`complete_stream()` como template methods concretos + `__init_subclass__` que prohíbe sobreescribirlos — un call site nuevo queda cubierto automáticamente, no depende de que alguien recuerde envolver la llamada |
| Ubicación de la política | `.orchestrator/policy.yaml` separado de `context.yaml` | `sensitivity`/`blocked_providers`/`allowed_providers` directamente en `.orchestrator/context.yaml` (RFC-006 Apéndice C) — la separación en archivo propio sigue siendo una mejora de seguridad válida (RFC-007 v0.3 §8, previene escalación vía prompt injection) pero **no es lo que el patch validado implementa hoy**; se reordena a Fase 2 explícitamente como evolución, no como parte del gate mínimo |
| Router bloqueado | Capturaba `EgressDenied` en el mismo `except Exception` genérico del fallback | `decide_with_local_router()`: algoritmo concreto (steps/agent explícito → keyword_hints → default_provider → más barato permitido → mayor capacidad permitida → bloqueo) — nunca fallback fijo a un proveedor que también podría estar bloqueado |
| Bug de fallback inseguro | No contemplado | **I14 (hallazgo real de RFC-006 §3.8):** un `fallback_provider` bloqueado no debe abortar el run si existe *otro* proveedor permitido — RFC-004 tenía este bug en su propio test I6, "un test de seguridad protegiendo un bug de usabilidad" |
| Threads | No contemplado | `ContextVar` no propaga a `threading.Thread` (confirmado contra `background.py:43-48` real): el worker debe fijar su propia política como primera sentencia |
| Retry | No contemplado | `background.py:126-153` tiene un loop `except Exception: retry con backoff` genérico que **hoy mismo** tragaría un futuro `EgressBlocked` y lo reintentaría 3 veces — confirmado leyendo el código real, no solo el RFC |
| Streaming | Diseño no discutía el detalle | `background.py:131` y los 4 providers implementan `complete_stream()` como generator function con `yield` (confirmado en `providers/claude.py:53-102`) — sellar esto mal deja el check diferido al primer `next()`, no eager. RFC-006 §3.3 documenta exactamente este error y cómo evitarlo |
| Secretos | No contemplado | Reutilizar `_contains_secrets()`, que **ya existe** en `rag.py:166` (confirmado) — no escribir un detector nuevo |
| Ledger | Diseño propio de `decision_events` en Fase 3 | `egress_decisions` (tabla lean, solo decisión — RFC-006 §6.2: "el log registra la DECISIÓN, nunca el PAYLOAD") ya en Fase 1; el ledger rico de RFC-005 (`decision_events`/`context_lineage`/`outcome_events`) queda **explícitamente fuera de alcance hasta 500 runs gobernados reales** (RFC-006 §8) — RFC-005 fue criticado en la propia serie por "scope creep con 0 runs" |
| Invariantes I1-I14 | 8 de 14 sin enunciado, marcadas `[FALTA RFC-006]`, bloqueante parcial declarado | **Las 14 tienen enunciado completo y verificado** (RFC-006 §4.3, reproducida en Apéndice A) — el bloqueo de la rev. 1 queda resuelto |
| Orden de commits | PRs agrupados por fase de alto nivel | **Mapeado 1:1 contra el orden de 12 commits de RFC-006 §10**, ya probado localmente en ese orden exacto (`git apply egress-gate.patch` → `126 passed, 1 failed` pre-existente de RAG) |

**Lección para este documento y para cualquier sesión futura:** antes de diseñar una implementación "definitiva", preguntar explícitamente si existe una ronda de diseño previa no commiteada. La serie RFC-001…006 vivía en el disco del usuario, fuera de este repo hasta este momento, y el documento anterior (rev. 1) hizo trabajo redundante — y en algunos puntos (el choque de diseño del punto de sellado) peor — por no saberlo.

---

## Parte I — Fundamentos

### 0. Resumen ejecutivo

`ai-orchestrator` se define como un **control plane local para gobernar el uso de múltiples proveedores y herramientas de IA sobre proyectos de software**, preservando aislamiento por proyecto, memoria, trazabilidad, atribución de costos y políticas de salida.

Regla técnica que ancla el diseño, formulada de forma idéntica en las seis rondas de la serie: **the router is egress** — el router LLM externo (DeepSeek por defecto) recibe el texto completo de la tarea antes de que exista ninguna evaluación de política, exactamente igual que el proveedor final.

Lo que **no** se afirma: que exista un runtime autónomo multiagente; que el sistema sea un firewall de red general; que los componentes individuales sean originales (FIDES, CaMeL, LiteLLM, Cloudflare AI Gateway ya cubren piezas — RFC-006 §5); que el router local sea mejor antes de medirlo.

### 1. El bug (verificado, no hipotético)

Reproducido en las seis rondas de la serie contra el código real, sin red:

- **Pre-routing egress**: el prompt enviado al router (`router.py:288-290`) contiene el texto completo de la tarea — incluyendo cualquier contenido sensible del proyecto — sin que exista ninguna política que lo evalúe antes. Por defecto ese router es DeepSeek (`config.example.yaml:27`).
- **Cross-project leak**: `_fetch_similar_runs()` (`router.py:124-143`) consulta el backend de similaridad sin acotar por proyecto; sus resultados (proyecto, provider, razón de ruteo, preview de tarea, rating) entran al prompt del router de cualquier otro proyecto.

Severidad alta, no crítica: ningún PoC de la serie demostró exfiltración de un secreto real, pero el diseño permite egress sensible por defecto.

### 2. Estado verificado del repositorio (2026-07-12)

| Componente | Implementación | Evidencia | Detalle verificado |
|---|---|---|---|
| Context Manager | implemented | verifiable | `context.py` — `ProjectContext`, `load_context()`, `.orchestrator/context.yaml` por proyecto |
| Routing Engine | partial | verifiable | `decide_provider()` en `router.py:234-336`; fuga cross-project activa; router local determinístico ausente en `production` — `_calculate_keyword_signals` (`router.py:71`) solo alimenta el prompt |
| Memory (RAG) | implemented (con deuda) | verifiable | `rag.py`; `_contains_secrets()` existe (`rag.py:166`) pero solo se usa al indexar, no en el borde de egress |
| Policy Engine | **diseñado y validado localmente, no publicado** | local-only | `orchestrator/egress.py` no existe en `production`; existió como parte de un patch efímero (`egress-gate.patch`, +512/−28) aplicado y testeado localmente por la serie RFC-001…006, nunca pusheado (`git push -u origin feat/egress-gate` es la primera acción pendiente, RFC-006 §0) |
| Cost Engine | implemented | verifiable | `costs.py` + `catalog.py` (Decision 0002 cerrada, 76/76 tests) |
| Decision Ledger | partial | verifiable | tabla `runs` con `provider`, `routing_reason`, `rating`, `router_cost_usd`, `session_id`, `step_id`; sin `routing_source`; sin `egress_decisions` |
| Agent Registry | partial | verifiable | `agents.py` — presets globales, resueltos en `decide_provider()` |
| Provider Gateway | **diseñado y validado localmente, no publicado** | local-only | `BaseProvider.complete()`/`complete_stream()` hoy son abstractos/con default débil (`providers/base.py:46-73`); los 4 providers implementan `complete()` y `complete_stream()` **directamente** (confirmado en `providers/claude.py:19,53`, mismo patrón en deepseek/gemini/openai), cada uno con su propio `httpx.stream(...)` — exactamente la superficie que RFC-006 §3.2 identificó y selló en el patch efímero |

**El estado real es mejor de lo que RFC-007 v0.3 documentaba**: no es que el diseño del gate no exista — existe, fue implementado, corrió 15 (RFC-006) tests localmente contra este mismo commit base, y nunca se publicó. El trabajo de este documento no es diseñar el gate: es **reconstruirlo contra el código actual y ejecutarlo con Codex**, en el orden que RFC-006 ya validó.

### 3. Posicionamiento

```text
Categoría de producto:      Local AI Control Plane
Capacidad central:          Project-Scoped Governed Decision Provenance (PGDP)
Mecanismos:                 Egress Gate · Provider-Safe Routing · Decision Ledger (lean)
                             RAG project-scoped · Cost attribution · Outcome feedback
Estado actual:               control plane multi-provider y multi-tool
Dirección:                   gobernanza multiagente
No afirmación:                runtime autónomo multiagente
```

### 4. Hipótesis falsables

- **H1a (seguridad):** toda llamada LLM con contexto gobernado atraviesa exactamente una evaluación de política antes de emitir bytes de payload de aplicación hacia el proveedor.
- **H1b (compatibilidad):** el gate no degrada workflows autorizados; `provider_compatibility = 4/4`; streaming operativo.
- **H2 (economía del routing):** el router local determinístico es no inferior al router LLM externo. RFC-006 §7.6 declara la regla de decisión exacta antes de mirar datos (reproducida en §11.5 de este documento).
- **H3 (valor del provenance):** sin datos; requiere ≥ 500 runs gobernados reales (RFC-006 §8, RFC-005 §18.3) — explícitamente diferido, no se construye la infraestructura de ledger rico hasta entonces.

### 5. Alcance de seguridad

> El Egress Gate gobierna llamadas LLM realizadas mediante `BaseProvider`. **No** constituye un sandbox de red general: no controla `model_discovery` (`orchestrator/discovery/*.py`, clasificado como "egress externo no contextual" — RFC-006 §2.2, issue separado), ni `requests.post()` fuera de providers, ni exfiltración por shell/git push, ni MCP de terceros con red propia.

### 6. Requisitos normativos

- Sin política activa, ninguna llamada LLM con prompt/contexto sale por `BaseProvider` (I1).
- El router externo se evalúa como provider antes de construir/enviar su payload — "the router is egress" (I5).
- Un nivel de sensibilidad o clearance desconocido MUST fallar cerrado (I7).
- Una denegación de política MUST NOT reintentarse (I13).
- `similar_runs` no cruza proyectos (I8).
- Streaming no puede bypassear el gate; el check es eager, no diferido al primer `next()` (I3, I11).
- Ningún provider puede sobreescribir `complete()`/`complete_stream()` (I4, I9).
- No existe fallback inseguro: si el router externo está bloqueado, se usa el router local, nunca un proveedor fijo sin re-evaluar política (I6); y un fallback bloqueado no aborta si existe *otro* proveedor permitido (I14).
- Un secreto detectado en el payload escala la sensibilidad efectiva a `secret` (I10).
- La política se fija dentro de cada worker thread, nunca se asume heredada (I12).
- El log de egress registra la decisión, nunca el payload (RFC-006 §6.2).
- El dashboard MUST NOT hacer binding fuera de loopback sin autenticación (WP-Net-1, §11.6).

---

## Parte II — Plan de Implementación Ejecutable

### 11.0 Cómo usar esta parte con Codex

Cada PR mapea **1:1** contra uno de los 12 commits ya validados localmente en RFC-006 §10 (reproducidos aquí con archivos y líneas reales de `production@4ae9497`, que RFC-006 no tenía porque trabajaba sobre un patch efímero, no sobre este checkout). Ejecutar en orden — cada uno asume que los anteriores están mergeados. El orden importa por una razón concreta y ya verificada: el commit que corrige el router (Fase 1, PR 1.5) invoca al router local (PR 1.4); si se invierte, no compila.

Suite de tests: `pytest tests/`. Bajo el gate, sin política declarada, ~21 tests existentes van a fallar con `EgressBlocked: Sin política activa` — RFC-006 §4.1 documenta que **eso es el hallazgo, no el daño**: enumera cada ruta de egress no gobernada de la suite actual. Se agrega un `conftest.py` que fija una política permisiva por defecto para no bloquear la suite existente (PR 1.1).

### 11.1 Fase 0 — Publicar y detener el decaimiento (bloqueante)

#### PR 0.1 — CI que corre la suite completa

*Archivos:* nuevo `.github/workflows/tests.yml`. (Hoy solo existe `pricing-catalog.yml`, acotado a paths de pricing — no hay CI genérico corriendo `pytest`.)

*Prompt Codex:*
```
Crea .github/workflows/tests.yml: se dispara en push a production y en todo
pull_request, instala Python 3.12 y las dependencias de test (revisa
pyproject.toml para el extra correcto), corre `pytest tests/ -v`.
No toques .github/workflows/pricing-catalog.yml.
```

#### PR 0.2 — Fix I8: scope de proyecto en `_fetch_similar_runs`

Corresponde al commit #7 de RFC-006 (`fix: restrict router similar-runs to current project`). Se adelanta a Fase 0 porque es independiente del resto del gate — no requiere `egress.py` ni el borde sellado para tener sentido, es un bug fix de scope aislado.

*Archivos:* `orchestrator/router.py` (`_fetch_similar_runs`, línea 124; call site línea 241), `tests/test_router.py`.

*Prompt Codex:*
```
Contexto: en orchestrator/router.py, _fetch_similar_runs(task, n=3) (línea ~124)
consulta orchestrator.similarity.get_backend().query() sin acotar por proyecto.
Sus resultados entran al prompt del router LLM externo de CUALQUIER proyecto,
no solo el que originó la tarea. RFC-006 lo documenta como invariante I8.

Tarea:
1. Cambia la firma a _fetch_similar_runs(task, project, n=3).
2. Filtra los resultados por row["project"] == project antes de agregarlos
   (revisa primero si similarity.get_backend().query() soporta un filtro de
   metadata nativo — si lo soporta, úsalo ahí; si no, filtra en Python).
3. Actualiza el call site en decide_provider() (línea ~241): pasa ctx.name.
4. Agrega en tests/test_router.py: un test que indexe runs de dos proyectos
   distintos y confirme que _fetch_similar_runs solo devuelve los del
   proyecto pedido; otro que confirme que el prompt final de decide_provider
   nunca contiene contenido de otro proyecto.
5. pytest tests/test_router.py -v verde.
No implementes el gate todavía.
```

#### PR 0.3 — Migración `routing_source` (hygiene, no bloqueante contra RFC-006)

RFC-006/RFC-004 confirman que `router-eval --offline` (PR 1.10) **no necesita telemetría nueva** — usa `runs.provider`, `runs.routing_reason`, `runs.rating`, `RoutingDecision.router_cost_usd`, todos existentes. `routing_source` no es requisito de RFC-006; es una mejora de precisión propia de este documento (RFC-007 v0.3 §5): sin ella, la elegibilidad de runs para el offline replay se decide parseando `routing_reason` como texto libre en vez de un valor filtrable, contaminando el N si se mezclan runs con provider forzado por step/agente.

*Archivos:* `orchestrator/migrate.py` (nueva migración, mismo patrón que `add_rating_to_runs`), `orchestrator/router.py` (`RoutingDecision`).

*Prompt Codex:*
```
Contexto: decide_provider() en orchestrator/router.py retorna por al menos
4 caminos (step forzado, agent preset, router LLM, fallback) y hoy esa
distinción solo vive como texto libre en routing_reason, no filtrable.
Esto no es parte del gate de egress (RFC-006) -- es una mejora de precisión
para que el futuro router-eval --offline (PR 1.10) pueda excluir runs cuyo
provider no lo decidió el router LLM, en vez de parsear texto.

Tarea:
1. En orchestrator/migrate.py agrega una migración "add_routing_source_to_runs"
   (mismo patrón que add_rating_to_runs: ALTER TABLE en try/except, dentro de
   _write_lock, _mark_applied, commit). Columna: routing_source TEXT.
2. Agrega routing_source: str = "unknown" a RoutingDecision (router.py).
3. Setea el valor en cada return de decide_provider(): "forced_step",
   "agent_preset", "llm_router", "fallback"; y "forced_cli" en force_provider().
4. Propaga el campo hasta la función que persiste el run en SQLite (revisa
   orchestrator/history.py y orchestrator/db.py) y desde ahí a cli.py y
   background.py.
5. Tests en tests/test_router.py verificando routing_source correcto por
   camino. pytest tests/ -v verde.
```

### 11.2 Fase 1 — Gate mínimo fail-closed (commits #2-#12 de RFC-006 §10)

Cada PR de esta fase corresponde exactamente a un commit ya validado. Cita el texto de RFC-006 directamente: no hay diseño que inventar, hay que **reconstruirlo contra el checkout actual**, que difiere del patch efímero solo en que ahora hay líneas reales verificables.

#### PR 1.1 — `egress.py`: política fail-closed por construcción (commit #2 — I1, I2, I7)

*Archivos:* nuevo `orchestrator/egress.py`, nuevo `tests/test_egress.py`, nuevo `conftest.py` (o extender el existente si hay uno en `tests/`).

*Diseño (RFC-006 §3.1, §3.10; RFC-005 §8.1/§8.4/§9.1-9.2, adaptado a la forma lean de RFC-006):*
```python
# orchestrator/egress.py
from contextvars import ContextVar
from dataclasses import dataclass, field

SENSITIVITY_RANK = {"public": 0, "internal": 1, "restricted": 2, "secret": 3}

class EgressBlocked(Exception):
    pass

@dataclass
class EgressPolicy:
    project: str
    sensitivity: str = "internal"          # DEFAULT_SENSITIVITY — preserva comportamiento actual
    allowed_providers: list[str] = field(default_factory=list)
    blocked_providers: list[str] = field(default_factory=list)
    provider_clearance: dict[str, str] = field(default_factory=dict)  # DEFAULT_CLEARANCE = "internal"

_POLICY: ContextVar[EgressPolicy] = ContextVar("egress_policy")   # SIN default

def current_policy() -> EgressPolicy:
    try:
        return _POLICY.get()
    except LookupError as exc:
        raise EgressBlocked("Sin política activa, no sale nada.") from exc

def set_policy(policy: EgressPolicy) -> None:
    if policy.sensitivity not in SENSITIVITY_RANK:
        raise EgressBlocked(f"Nivel de sensibilidad desconocido: {policy.sensitivity!r}")
    _POLICY.set(policy)

def can_send(provider: str) -> bool:
    policy = current_policy()
    if provider in policy.blocked_providers:
        return False
    if policy.allowed_providers and provider not in policy.allowed_providers:
        return False
    clearance = policy.provider_clearance.get(provider, "internal")
    if clearance not in SENSITIVITY_RANK:
        return False   # nivel desconocido = bloqueo, I7
    return SENSITIVITY_RANK[clearance] >= SENSITIVITY_RANK[policy.sensitivity]

def check(provider: str, phase: str = "provider") -> None:
    if not can_send(provider):
        raise EgressBlocked(f"Provider '{provider}' bloqueado en phase='{phase}' por política de egress.")
```

*Tests (`tests/test_egress.py`, nombrados como en RFC-006/003 §14.1):*
`test_no_policy_blocks_provider_complete`, `test_restricted_project_blocks_public_provider`, `test_blocked_provider_overrides_clearance`, `test_allowed_providers_restricts_even_with_clearance`, `test_unknown_project_sensitivity_fails_closed`, `test_unknown_provider_clearance_fails_closed`.

*`conftest.py`:* fixture `_default_egress_policy` (autouse) que llama `egress.set_policy(EgressPolicy(project="test", sensitivity="internal"))` antes de cada test — sin esto, ~21 tests existentes que llegan a un provider real empiezan a fallar con `EgressBlocked` en cuanto se conecte el borde en PR 1.2 (RFC-006 §4.1: es el hallazgo esperado, no una regresión).

*Prompt Codex:*
```
Contexto: ai-orchestrator no tiene ningún Policy Engine todavía. RFC-006
(docs/decisions/rfcs/RFC-006-provider-safe-routing.md, §3.1 y §3.10) ya diseñó y
validó localmente (nunca publicado) un módulo egress.py basado en ContextVar
sin default: si nadie fija una política activa, cualquier intento de leerla
levanta EgressBlocked. Es la propiedad central: la política no es un
parámetro que alguien puede olvidar pasar en un call site nuevo, es un
estado ambiental que si nadie fija, bloquea todo por diseño.

Tarea:
1. Crea orchestrator/egress.py con exactamente esta forma (adaptar nombres
   si el resto del código lo exige, pero preserva la semántica):
   - SENSITIVITY_RANK = {"public": 0, "internal": 1, "restricted": 2, "secret": 3}
   - EgressBlocked(Exception)
   - EgressPolicy: dataclass con project, sensitivity (default "internal"),
     allowed_providers (list, default vacío), blocked_providers (list,
     default vacío), provider_clearance (dict provider->nivel, default vacío).
   - _POLICY: ContextVar[EgressPolicy] SIN default.
   - current_policy(): lee _POLICY.get(), si LookupError levanta EgressBlocked.
   - set_policy(policy): valida que policy.sensitivity esté en
     SENSITIVITY_RANK (si no, EgressBlocked -- typo en política de seguridad
     no debe degradar a permisivo), luego _POLICY.set(policy).
   - can_send(provider) -> bool: False si provider en blocked_providers;
     False si allowed_providers no está vacío y provider no está en la lista;
     resuelve clearance del provider desde provider_clearance (default
     "internal" si no está declarado); si el clearance no está en
     SENSITIVITY_RANK, False (nivel desconocido = bloqueo); si no,
     SENSITIVITY_RANK[clearance] >= SENSITIVITY_RANK[policy.sensitivity].
   - check(provider, phase="provider"): si not can_send(provider), levanta
     EgressBlocked con un mensaje que incluya provider y phase pero NUNCA
     el prompt ni contexto del proyecto (el mensaje de excepción es
     candidato a terminar en logs).
2. Crea tests/test_egress.py con: test_no_policy_blocks_provider_complete
   (llamar check() o can_send() sin haber llamado set_policy() -> EgressBlocked),
   test_restricted_project_blocks_public_provider,
   test_blocked_provider_overrides_clearance,
   test_allowed_providers_restricts_even_with_clearance,
   test_unknown_project_sensitivity_fails_closed (set_policy con
   sensitivity="confidencial" -> EgressBlocked),
   test_unknown_provider_clearance_fails_closed.
3. Busca si ya existe un conftest.py en tests/; si no, créalo. Agrega un
   fixture autouse que llame egress.set_policy(EgressPolicy(project="test",
   sensitivity="internal")) antes de cada test, para no romper la suite
   existente cuando el borde se selle en un PR posterior. Documenta con un
   comentario de una línea por qué existe (referencia a RFC-006 §4.1: sin
   esto, ~21 tests que llegan a un provider real fallarían con
   "sin política activa" en cuanto el borde quede sellado).
4. pytest tests/test_egress.py -v verde. pytest tests/ -v sigue sin
   regresiones (el fixture autouse cubre los tests existentes).

No toques orchestrator/providers/ ni orchestrator/router.py todavía -- eso
es el PR siguiente. Este PR es solo el módulo de política y sus tests,
aislado del resto del sistema.
```

#### PR 1.2 — Sellar el borde de `BaseProvider` (commit #3 — I3, I4, I9, I11)

*Archivos:* `orchestrator/providers/base.py`, los 4 providers (`orchestrator/providers/{claude,deepseek,gemini,openai}.py`), `tests/test_providers.py`, `tests/test_egress.py`.

*Hallazgo crítico verificado en este repo (no en el patch efímero — en el código real):* `providers/claude.py:53-102` implementa `complete_stream()` como **generator function** (usa `yield` directo en el cuerpo del método). RFC-006 §3.3 documenta exactamente el error que esto produciría si se agrega el check ingenuamente: si `complete_stream()` en la base es también una función generadora con el check adentro, el check se difiere al primer `next()` — el caller nunca ve `EgressBlocked` en el `try` que envuelve la llamada. La base debe ser un método **normal** (no generador) que hace el check y *retorna* el generador de `_complete_stream()`.

*Diseño (RFC-006 §3.2-3.3):*
```python
# providers/base.py
from orchestrator import egress

class BaseProvider(ABC):
    name: str = "base"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for method in ("complete", "complete_stream"):
            if method in cls.__dict__:
                raise TypeError(
                    f"{cls.__name__} no puede sobreescribir {method}(). "
                    f"Implementa _{method}(). El borde de egress es sellado."
                )

    def complete(self, prompt: str, system: str = "") -> CompletionResult:
        egress.check(self.name, phase="provider")
        return self._complete(prompt, system)

    def complete_stream(self, prompt: str, system: str = ""):
        egress.check(self.name, phase="stream")
        return self._complete_stream(prompt, system)   # NO generator function: retorna el generator

    @abstractmethod
    def _complete(self, prompt: str, system: str = "") -> CompletionResult: ...

    def _complete_stream(self, prompt: str, system: str = ""):
        result = self._complete(prompt, system)
        yield result.text
        return result.to_stream_result()
```

Cada provider renombra su `complete` → `_complete` y su `complete_stream` → `_complete_stream` (que sigue siendo generador, ahí sí corresponde).

*Tests:* `test_provider_cannot_override_complete`, `test_provider_cannot_override_complete_stream` (definir una subclase de prueba que sobreescriba `complete()` directamente y verificar `TypeError` al definirse, no al ejecutarse), `test_complete_invokes_check_before__complete`, `test_complete_stream_check_is_eager_not_deferred` (verificar con `inspect.isgeneratorfunction(BaseProvider.complete_stream)` que es `False` — esta es la prueba real de I11, no `list(...)` que RFC-006 §3.3 señala como el test que "pasaba probando otra cosa"), `test_streaming_http_not_reached_when_blocked` (mockear `httpx.stream` a nivel de módulo, política que bloquea, confirmar que nunca se invoca).

*Prompt Codex:*
```
Contexto: orchestrator/egress.py ya existe (PR anterior). Ahora hay que
sellar el borde real: orchestrator/providers/base.py define BaseProvider
con complete() abstracto y complete_stream() con un wrapper débil que llama
a complete(). Los 4 providers reales (orchestrator/providers/claude.py,
deepseek.py, gemini.py, openai.py) IGNORAN ese wrapper: cada uno implementa
su propio complete_stream() directo con httpx.stream(...) -- confirma esto
leyendo providers/claude.py líneas 53-102 antes de tocar nada. Un gate solo
en complete() dejaría 4 rutas de streaming completamente abiertas.

ADVERTENCIA CRÍTICA (RFC-006 §3.3, verificada contra este código): en
providers/claude.py, complete_stream() usa `yield` directamente en su
cuerpo -- es una generator function. Si conviertes BaseProvider.complete_stream()
en una generator function con el check adentro, Python difiere TODO el
cuerpo (incluido el check) hasta el primer next() -- quien llama
`try: gen = provider.complete_stream(...) except EgressBlocked` NUNCA
captura la excepción, porque el cuerpo ni siquiera empezó a ejecutar todavía.
BaseProvider.complete_stream() debe ser un método NORMAL (sin yield en su
propio cuerpo) que hace el check y luego RETORNA el generador que produce
_complete_stream().

Tarea:
1. En orchestrator/providers/base.py:
   a. Agrega __init_subclass__(cls, **kwargs) que recorra ("complete",
      "complete_stream") y levante TypeError si el método aparece en
      cls.__dict__ (es decir, si la subclase lo sobreescribió), con mensaje
      indicando que debe implementar _complete()/_complete_stream() en su
      lugar.
   b. Convierte complete() en concreto: llama a
      `from orchestrator import egress; egress.check(self.name, phase="provider")`
      y luego `return self._complete(prompt, system)`.
   c. Convierte complete_stream() en concreto, NO generator function:
      hace el check con phase="stream" y luego `return self._complete_stream(prompt, system)`.
   d. Renombra el abstractmethod complete a _complete.
   e. Agrega _complete_stream() con un default razonable si no existe ya
      uno (puede envolver _complete() como hace hoy complete_stream(), pero
      como generador real).
2. En cada uno de los 4 providers (claude.py, deepseek.py, gemini.py,
   openai.py): renombra el método complete() existente a _complete(), y
   el método complete_stream() existente a _complete_stream(). NO cambies
   la lógica interna de ninguno -- solo el nombre del método y que ya no
   se llaman complete/complete_stream (eso ahora lo resuelve la base).
3. Verifica que ningún provider siga definiendo complete o complete_stream
   directamente -- si __init_subclass__ está bien implementado, un intento
   de dejar alguno sin renombrar debe fallar con TypeError al importar el
   módulo, no en runtime tardío.
4. Agrega tests en tests/test_providers.py:
   test_provider_cannot_override_complete y
   test_provider_cannot_override_complete_stream (define una subclase de
   prueba de BaseProvider que sobreescriba complete() directamente dentro
   del test y verifica que TypeError se levanta AL DEFINIR la clase, con
   pytest.raises envolviendo la definición de clase, no la instanciación).
5. Agrega en tests/test_egress.py:
   test_complete_invokes_check_before__complete (mock de _complete, política
   que bloquea el provider, confirma que _complete nunca se llama);
   test_complete_stream_check_is_eager_not_deferred (usa
   inspect.isgeneratorfunction(BaseProvider.complete_stream) y confirma que
   es False -- esta es la prueba real de que el check es eager, NO uses
   list(...) sobre el resultado como prueba, eso no distingue check eager
   de check diferido);
   test_streaming_http_not_reached_when_blocked (mockea httpx.stream a
   nivel de módulo en providers/claude.py, política que bloquea "claude",
   llama complete_stream() esperando EgressBlocked, confirma con
   Mock.assert_not_called() que httpx.stream nunca se invocó).
6. pytest tests/ -v -- vas a ver fallar tests existentes que llegan a un
   provider real sin declarar política explícita. Si el conftest.py del
   PR anterior ya tiene el fixture autouse de política permisiva, no
   deberían fallar; si alguno falla de todos modos, es una ruta de egress
   que el fixture no cubre -- repórtala, no la silencies agregando un
   try/except.

No toques orchestrator/router.py ni orchestrator/background.py todavía.
```

#### PR 1.3 — Sensibilidad de proyecto y clearance de provider (commit #4)

*Archivos:* `orchestrator/context.py` (`ProjectContext`), `orchestrator/config.py`, `config.example.yaml`, `tests/test_egress.py`.

*Diseño (RFC-006 Apéndice C):*
```yaml
# .orchestrator/context.yaml (agregar campos, no archivo nuevo)
sensitivity: restricted        # opcional, default "internal" si se omite
blocked_providers: [deepseek, gemini]
allowed_providers: []          # opcional

# config.yaml
providers:
  deepseek: { clearance: public,     model: deepseek-v4-flash }
  gemini:   { clearance: public,     model: gemini-2.5-flash }
  openai:   { clearance: internal,   model: gpt-4o }
  claude:   { clearance: restricted, model: claude-sonnet-4-6 }
```

*Nota de diseño explícita, no silenciar:* esto mezcla política de seguridad (`sensitivity`, `blocked_providers`) en el mismo archivo que contexto operativo (`stack`, `conventions`, `routing_notes`) que un agente con acceso de escritura al repo puede editar. RFC-007 v0.3 §8 señaló esto como riesgo de escalación de privilegios vía prompt injection. RFC-006 no lo resuelve — lo hereda de RFC-005 tal cual. **Se implementa así en esta fase porque es lo validado**, y la separación en `policy.yaml` queda como Fase 2 (§11.3), explícitamente, no como un supuesto ya resuelto.

*Prompt Codex:*
```
Contexto: orchestrator/egress.py y el borde sellado de BaseProvider ya
existen. Falta conectar la sensibilidad real de cada proyecto y el
clearance real de cada provider, en vez de valores hardcodeados en tests.

Tarea:
1. En orchestrator/context.py, agrega a ProjectContext (dataclass) los
   campos: sensitivity: str = "internal", blocked_providers: list[str] =
   field(default_factory=list), allowed_providers: list[str] =
   field(default_factory=list). Carga estos valores desde el
   context.yaml del proyecto en load_context() (raw.get("sensitivity",
   "internal"), etc.) -- mismo patrón que los campos existentes como
   daily_budget_usd.
2. En orchestrator/config.py, agrega soporte para leer providers.<name>.clearance
   desde config.yaml (revisa get_provider_config, que ya lee otros campos
   por provider, y sigue el mismo patrón). Default "internal" si no está
   declarado explícitamente para un provider.
3. Actualiza config.example.yaml con clearance de ejemplo para los 4
   providers, siguiendo exactamente esta tabla (documenta con un comentario
   de una línea que estos son los defaults recomendados, no obligatorios):
   deepseek: public, gemini: public, openai: internal, claude: restricted.
4. NO agregues un archivo policy.yaml separado en este PR -- sensitivity
   y blocked_providers/allowed_providers viven en el mismo context.yaml
   que ya existe. Esa separación es una mejora de seguridad de Fase 2,
   documentada pero fuera de alcance aquí.
5. Agrega tests en tests/test_egress.py que construyan una EgressPolicy a
   partir de un ProjectContext y una config con clearances reales (no
   valores hardcodeados en el test) y verifiquen el resultado de can_send()
   para el caso del PoC: proyecto sensitivity=restricted,
   blocked_providers=[deepseek, gemini], provider deepseek -> bloqueado;
   provider claude (clearance restricted) -> permitido.
6. pytest tests/ -v verde.

No conectes esto todavía con decide_provider() -- eso es el PR siguiente,
que primero necesita el router local (PR 1.4).
```

#### PR 1.4 — Router local determinístico (commit #5, va antes del #6)

*Archivos:* nuevo `orchestrator/local_router.py` (o función dentro de `router.py`, decidir según cómo quede de legible), `tests/test_router.py`.

*Diseño (RFC-006 §3.7, el más específico de la serie):*
```python
def decide_with_local_router(task: str, ctx: ProjectContext, config: dict) -> RoutingDecision:
    permitted = [p for p in PROVIDERS if egress.can_send(p)]
    if not permitted:
        raise EgressBlocked(f"Ningún proveedor pasa la política de egress para '{ctx.name}'.")

    # 1. keyword_hints del proyecto, por peso descendente
    for sig in sorted(_calculate_keyword_signals(task, ctx), key=lambda s: -s.get("weight", 1)):
        if sig.get("provider") in permitted:
            return RoutingDecision(provider=sig["provider"], used_fallback=True, routing_source="local_router", ...)

    # 2. default del proyecto, si pasa política
    if ctx.default_provider in permitted:
        return RoutingDecision(provider=ctx.default_provider, ...)

    # 3. default global, si pasa política
    # 4. el permitido más barato, por precio de input del catálogo (orchestrator.catalog)
```

Para el paso 4, reutilizar `orchestrator.catalog.get_model_profiles()` (ya existe, Decision 0002) en vez de escribir un lector de precios nuevo.

*Tests:* determinismo (misma tarea + mismo contexto → mismo resultado, sin red), respeta `permitted` en cada uno de los 4 pasos, `test_local_router_never_returns_blocked_provider`, `test_no_provider_available_raises_egress_blocked`.

*Prompt Codex:*
```
Contexto: RFC-006 §3.7 especifica un router local determinístico, sin LLM
y sin red, para cuando el router externo no puede recibir el contexto de
la tarea (por política) o como base de comparación futura en
router-eval --offline. orchestrator/router.py ya tiene
_calculate_keyword_signals() (línea ~71) pero hoy solo alimenta el prompt
del router LLM, nunca decide por sí sola.

Tarea:
1. Crea una función decide_with_local_router(task, ctx, config) ->
   RoutingDecision (en orchestrator/local_router.py nuevo, o en router.py
   si es más simple de integrar -- decide según legibilidad) que:
   a. Calcula permitted = [p for p in PROVIDERS if egress.can_send(p)]
      (importa PROVIDERS de orchestrator.paths, can_send de orchestrator.egress).
   b. Si permitted está vacío, levanta EgressBlocked con un mensaje que
      incluya el nombre del proyecto (ctx.name) pero no el texto de la tarea.
   c. Reutiliza _calculate_keyword_signals(task, ctx) (NO la reescribas),
      ordena por weight descendente, y devuelve el primer provider cuyo
      signal esté en permitted.
   d. Si no hay match de keywords, y ctx.default_provider está en permitted,
      úsalo.
   e. Si no, usa el default global de config (revisa
      orchestrator.config.get_default_provider) si está en permitted.
   f. Si no, elige el provider de permitted con el precio de input más bajo,
      usando orchestrator.catalog.get_model_profiles(config) -- NO escribas
      un lector de precios nuevo, ese catálogo ya existe (Decision 0002).
   g. Marca routing_source="local_router" en el RoutingDecision resultante,
      con used_fallback=True y una reason explicando qué regla lo eligió.
   h. Esta función NUNCA debe devolver un provider que no esté en permitted
      -- si por algún bug interno eso pasara, es mejor que la función
      levante antes que devolver un resultado inseguro.
2. Tests en tests/test_router.py:
   test_local_router_is_deterministic (misma task+ctx -> mismo resultado,
   sin ningún mock de red porque no debería llamar a ninguno),
   test_local_router_respects_keyword_signals,
   test_local_router_falls_back_to_project_default,
   test_local_router_falls_back_to_cheapest_permitted,
   test_local_router_never_returns_blocked_provider,
   test_no_provider_available_raises_egress_blocked.
3. pytest tests/ -v verde.

No conectes esto todavía a decide_provider() -- ese es el PR siguiente,
que sí depende de que este ya exista y esté probado.
```

#### PR 1.5 — Cerrar el pre-routing egress (commit #6 — I5, I6, I14)

Este es el PR que cierra el bug original de §1. **I14 es el hallazgo más importante de toda la serie (RFC-006 §3.8)**: en una iteración anterior, el sistema abortaba con `EgressBlocked` cuando el `fallback_provider` configurado estaba bloqueado, *aunque existiera otro provider permitido* — y un test de seguridad (`I6` en RFC-002/003/004) afirmaba que ese aborto era correcto. Es la clase de bug que mata productos de seguridad: bloquear de más hasta que el usuario desactiva el gate.

*Archivos:* `orchestrator/router.py` (`decide_provider`, líneas 234-336, específicamente la llamada al router LLM en 288-290 y el manejo de excepción en 331-336).

*Diseño (RFC-006 §3.6, §3.8; pseudocódigo más explícito en RFC-003 §6.2):*
```python
def decide_provider(task: str, ctx: ProjectContext, config: dict) -> RoutingDecision:
    router_cfg = get_router_config(config)
    router_provider_name = router_cfg.get("provider", "deepseek")

    # ... (lógica de step forzado / agent preset se mantiene igual, ya se evalúa
    #      antes de llegar acá; falta agregarle su propio egress.check en un
    #      PR posterior si se decide gobernar también esos caminos)

    if not egress.can_send(router_provider_name):
        # NO construir el prompt full-context: el router local no necesita verlo igual
        decision = decide_with_local_router(task, ctx, config)
        decision.routing_source = "local_router"
    else:
        try:
            # ... construir prompt, llamar router LLM (esto ya pasa por
            #     BaseProvider.complete() sellado en PR 1.2, así que el check
            #     de phase="provider" corre igual, pero acá se evita incluso
            #     construir el prompt si ya sabíamos que iba a fallar)
            decision = <llamada actual al router LLM>
        except EgressBlocked:
            decision = decide_with_local_router(task, ctx, config)
            decision.routing_source = "local_router"
        except Exception as exc:
            decision = decide_with_local_router(task, ctx, config)
            decision.routing_source = "local_router"
            decision.reason += f" (router externo falló: {exc})"

    # I14: revalidar el resultado, pero el chequeo real es sobre 'decision.provider'
    # ya elegido por decide_with_local_router (que nunca devuelve uno bloqueado) o
    # por el router LLM (que ya pasó por BaseProvider.complete() sellado). No
    # levantar EgressBlocked aquí solo porque un *fallback preconfigurado en
    # config.yaml* esté bloqueado -- eso es exactamente el bug de I14.
    return decision
```

*Tests:* `test_external_router_allowed_when_clearance_sufficient`, `test_external_router_blocked_uses_local_router_not_fixed_fallback`, `test_external_router_blocked_does_not_build_full_context_prompt` (verificar que `_build_router_prompt` nunca se llama cuando `can_send(router_provider_name)` es `False` — esta es la prueba dura de "cero bytes"), `test_no_fixed_claude_fallback_when_router_blocked`, **`test_blocked_fallback_provider_does_not_abort_when_other_provider_permitted`** (el test de I14: `fallback_provider="gemini"` bloqueado, pero `claude` permitido → debe devolver `claude` vía router local, no levantar `EgressBlocked`).

*Prompt Codex:*
```
Contexto: este es el PR que cierra el bug original documentado en RFC-006 §1
y §3 (pre-routing egress: el router LLM recibe el contexto completo de la
tarea antes de que exista ninguna política). orchestrator/egress.py,
BaseProvider sellado y decide_with_local_router() ya existen de los PRs
anteriores. Falta conectar todo en decide_provider() (orchestrator/router.py,
líneas 234-336).

LEE PRIMERO docs/decisions/rfcs/RFC-006-provider-safe-routing.md §3.6 y §3.8
completos antes de escribir código -- §3.8 documenta un bug real que un
test de seguridad anterior (I6 en versiones previas del mismo RFC) protegía
por error: el sistema abortaba con EgressBlocked cuando el fallback_provider
configurado estaba bloqueado, AUNQUE existiera otro provider permitido.
Ese comportamiento es incorrecto -- es la clase de bug que hace que un
usuario desactive el gate de seguridad por frustración.

Tarea:
1. En decide_provider(), ANTES de construir el prompt del router LLM
   (orchestrator.router._build_router_prompt) y ANTES de llamarlo, verifica
   egress.can_send(router_provider_name).
2. Si can_send() es False: NO construyas el prompt full-context en absoluto
   (ni siquiera para descartarlo después -- la política prohíbe que ese
   contexto exista en memoria camino a ese provider). Llama directamente a
   decide_with_local_router(task, ctx, config) y marca
   decision.routing_source = "local_router" en el resultado.
3. Si can_send() es True: procede con la llamada al router LLM como hoy
   (ya pasa por BaseProvider.complete() sellado, PR 1.2). Envuelve esa
   llamada en un try/except que capture tanto EgressBlocked como Exception
   genérica (por ejemplo si el router LLM falla por red) y en AMBOS casos
   caiga a decide_with_local_router(), NO a un fallback_provider fijo de
   config.yaml.
4. CRÍTICO (esto es I14): en ningún punto de esta función debe levantarse
   EgressBlocked solo porque el fallback_provider configurado en config.yaml
   esté bloqueado. decide_with_local_router() ya se encarga de elegir entre
   TODOS los providers permitidos, no solo el fallback_provider preconfigurado.
   Solo debe levantarse EgressBlocked cuando decide_with_local_router() en sí
   mismo determina que NINGÚN provider está permitido (eso ya lo hace el PR
   anterior).
5. Tests en tests/test_router.py:
   test_external_router_allowed_when_clearance_sufficient,
   test_external_router_blocked_uses_local_router_not_fixed_fallback,
   test_external_router_blocked_does_not_build_full_context_prompt (mockea
   _build_router_prompt y confirma con assert_not_called() que nunca se
   invoca cuando el router está bloqueado -- esta es la prueba de "cero bytes"),
   test_no_fixed_claude_fallback_when_router_blocked,
   test_blocked_fallback_provider_does_not_abort_when_other_provider_permitted
   (config con fallback_provider="gemini" bloqueado por policy, pero "claude"
   permitido -- decide_provider debe devolver claude via router local, NUNCA
   levantar EgressBlocked).
6. pytest tests/ -v verde. Presta atención especial a que ningún test
   existente que dependía del comportamiento viejo (fallback fijo) empiece
   a fallar por buenas razones -- si alguno lo hace, es evidencia de que
   dependía del bug, actualízalo para reflejar el comportamiento correcto,
   no lo borres sin entender por qué fallaba.

No toques orchestrator/background.py todavía -- el fix de threads es el
PR siguiente.
```

#### PR 1.6 — Escalación por secreto en el payload (commit #8 — I10)

*Archivos:* `orchestrator/egress.py` (extender `check`), `orchestrator/rag.py` (reutilizar `_contains_secrets`, ya existe en línea 166 — confirmado, no reescribir).

*Prompt Codex:*
```
Contexto: orchestrator/rag.py ya tiene _contains_secrets(text) (línea 166),
usado hoy solo al indexar contenido para RAG. RFC-006 §3.9 reutiliza esta
misma función en el borde de egress: si el prompt o system prompt que se
va a enviar a un provider contiene un patrón de secreto, la sensibilidad
efectiva de ESE envío escala a "secret" -- nivel que ningún clearance
configurado normalmente alcanza, así que el envío se bloquea.

Tarea:
1. En orchestrator/egress.py, agrega una función check_payload(provider,
   prompt, system, phase) (o extiende check() con parámetros opcionales
   prompt/system) que: si prompt o system contienen un secreto según
   rag._contains_secrets() (impórtala, no la dupliques), evalúa can_send()
   como si policy.sensitivity fuera "secret" en vez del valor real de la
   política, sin mutar la policy real en el ContextVar (usa
   dataclasses.replace sobre una copia local).
2. Conecta esto en BaseProvider.complete()/complete_stream() (PR 1.2): en
   vez de solo egress.check(self.name, phase=...), pasa también prompt y
   system para que la escalación por secreto se evalúe en cada llamada real.
3. IMPORTANTE: el mensaje de la excepción EgressBlocked en este caso NO debe
   incluir el prompt, el system, ni ningún fragmento del secreto detectado
   -- solo un reason_code fijo como "secret_pattern_detected".
4. Tests en tests/test_egress.py: test_secret_in_prompt_escalates_to_secret_and_blocks
   (payload con un patrón tipo API_KEY= o similar de los que ya detecta
   _contains_secrets, sensitivity del proyecto "internal", provider con
   clearance "internal" -- debería pasar SIN el secreto y bloquearse CON él),
   test_egress_error_message_never_contains_payload (verifica con un string
   secreto conocido que ese string nunca aparece en str(exc) de EgressBlocked).
5. pytest tests/ -v verde.
```

#### PR 1.7 — Política dentro del worker thread (commit #9 — I12)

*Archivos:* `orchestrator/background.py` (`_worker`, líneas 52-90; `submit_run`, líneas 22-49).

*Hallazgo confirmado contra el código real de este repo (no solo el patch efímero):* `submit_run()` (línea 43-48) crea `threading.Thread(target=_worker, ...)`. `ContextVar` no se copia automáticamente a un thread nuevo — si la política se fija en el thread que llama a `submit_run()` (por ejemplo en `server.py::_post_run`), `_worker()` corriendo en su propio thread jamás la ve, y **cualquier llamada a un provider dentro de `_worker()` levantaría `EgressBlocked` por "sin política activa"**, aunque el usuario sí tenga una política válida configurada. Sin el fix de este PR, todo run disparado desde el dashboard moriría en cuanto se conecte el gate.

*Prompt Codex:*
```
Contexto: orchestrator/background.py::submit_run() (línea ~43) crea un
threading.Thread nuevo que ejecuta _worker(). Python's ContextVar NO se
propaga automáticamente a un thread creado con threading.Thread (sí se
propaga a asyncio tasks, pero no a threads del módulo threading). Esto
significa que aunque alguien fije una política de egress ANTES de llamar
submit_run(), el thread de _worker() no la va a ver, y en cuanto el gate
esté conectado (PRs anteriores), TODO run lanzado desde el dashboard va a
fallar con EgressBlocked("Sin política activa") -- sin importar que la
configuración sea correcta.

Tarea:
1. En orchestrator/background.py::_worker() (línea ~52), como una de las
   PRIMERAS sentencias dentro del try (antes de cualquier llamada que
   termine invocando un provider), construye y fija la EgressPolicy
   correspondiente al proyecto de este run: necesitas resolver ctx
   (ya se resuelve más abajo en el código actual si ctx es None, líneas
   69-74 -- puede que tengas que mover esa resolución más arriba) y desde
   ahí project.sensitivity, blocked_providers, allowed_providers, más el
   provider_clearance desde config. Llama a egress.set_policy(...) con eso
   ANTES de que decide_provider() o build_provider().complete() se invoquen
   dentro de este mismo worker.
2. Verifica que NO estás asumiendo que la política del thread padre (donde
   se llamó submit_run) se propaga -- no debe haber ningún código que
   dependa de eso.
3. Tests en un nuevo tests/test_background.py (o extiende el existente si
   ya hay uno para background.py): test_background_worker_sets_policy_inside_thread
   (arranca un run real vía submit_run con una policy que el thread padre
   fija en su propio ContextVar, y confirma que el worker de todos modos
   puede completar sin EgressBlocked porque fija SU PROPIA política),
   test_parent_thread_policy_does_not_silently_leak_to_worker (si el padre
   fija una política MÁS restrictiva que la que corresponde al proyecto real,
   confirma que el worker usa la política correcta del proyecto, no la
   heredada por accidente si en algún punto SÍ hubiera propagación parcial).
4. pytest tests/ -v verde.
```

#### PR 1.8 — Nunca reintentar una denegación de política (commit #10 — I13)

*Archivos:* `orchestrator/background.py`, línea 128-153 (el loop de retry con backoff).

*Hallazgo confirmado contra el código real:* el loop `for _attempt in range(_MAX_RETRIES): try: ... except Exception as exc: ... retry` (líneas 128-153) captura **cualquier** excepción, incluida una futura `EgressBlocked`, y la reintenta hasta 3 veces con backoff exponencial (`_RETRY_BASE ** _attempt`, hasta ~4 segundos de espera). Sin este fix, una denegación de política tarda ~3x más en fallar y dos reintentos completamente inútiles quedan en los logs como si hubieran sido timeouts transitorios.

*Prompt Codex:*
```
Contexto: orchestrator/background.py::_worker(), líneas ~128-153, tiene un
loop de reintentos con backoff exponencial (_MAX_RETRIES=3) que captura
`except Exception as exc` de forma genérica alrededor de la llamada a
provider.complete_stream()/complete(). Una vez que el gate de egress esté
conectado (PRs anteriores), una denegación de política (EgressBlocked) va
a caer en este except genérico y reintentarse 3 veces con backoff, como si
fuera un timeout de red transitorio. Eso es semánticamente incorrecto (una
denegación de política nunca cambia de resultado si se repite exactamente
igual) y agrega latencia inútil.

Tarea:
1. En el loop de la línea ~128, agrega un except EgressBlocked específico
   ANTES del except Exception genérico existente, que simplemente vuelva a
   levantar (raise) sin reintentar y sin esperar (nada de time.sleep).
   Importa EgressBlocked desde orchestrator.egress.
2. Verifica que el except Exception genérico que ya existe se mantiene
   intacto para todos los demás casos (timeouts reales, errores de red,
   etc.) -- este cambio es puramente agregar el caso específico antes del
   genérico, no tocar la lógica de retry existente para otros errores.
3. Tests: test_egress_blocked_is_not_retried (mockea provider.complete_stream
   para que levante EgressBlocked, confirma que se llama exactamente 1 vez,
   no 3, y que no hay ningún time.sleep de por medio -- puedes mockear
   time.sleep también y confirmar 0 llamadas), test_transient_error_is_still_retried
   (confirma que un error genérico, por ejemplo ConnectionError, sigue
   reintentándose hasta 3 veces como antes -- no rompas ese comportamiento).
4. pytest tests/ -v verde.
```

#### PR 1.9 — `egress_decisions`: log de decisión, nunca de payload (commit #11)

*Archivos:* `orchestrator/migrate.py` (nueva migración), `orchestrator/egress.py` (función de logging), `tests/test_egress.py`.

*Diseño (RFC-006 §6.2, campos exactos):*
```sql
CREATE TABLE IF NOT EXISTS egress_decisions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    project     TEXT NOT NULL,
    provider    TEXT NOT NULL,
    phase       TEXT NOT NULL,   -- router | provider | stream
    decision    TEXT NOT NULL,   -- allowed | blocked
    reason_code TEXT NOT NULL,
    sensitivity TEXT,
    clearance   TEXT,
    run_id      INTEGER REFERENCES runs(id)
);
CREATE INDEX IF NOT EXISTS idx_egress_project_ts ON egress_decisions(project, ts DESC);
CREATE INDEX IF NOT EXISTS idx_egress_decision ON egress_decisions(decision, phase);
```

Campos **permitidos**: `project`, `provider`, `phase`, `decision`, `reason_code`, `sensitivity`, `clearance`, `ts`. Campos **prohibidos, nunca**: prompt, system prompt, chunks RAG, texto de la tarea (RFC-006 §6.2, regla dura).

*Prompt Codex:*
```
Contexto: RFC-006 §6 (con una advertencia con fecha real: incidente de
LiteLLM del 18-03-2026 donde un guardrail logueó headers secretos en spans
de OpenTelemetry) establece una regla dura: el log de egress registra la
DECISIÓN, nunca el PAYLOAD. Hay que agregar una tabla mínima que registre
cada allow/block, sin nunca guardar el prompt ni contexto real.

Tarea:
1. En orchestrator/migrate.py, agrega una migración "create_egress_decisions_table"
   (mismo patrón que create_context_hits_table) con esta forma exacta:
   id, ts, project, provider, phase (router|provider|stream), decision
   (allowed|blocked), reason_code, sensitivity, clearance, run_id (FK a runs,
   nullable). Índices por (project, ts) y por (decision, phase).
2. En orchestrator/egress.py, agrega una función log_decision(project,
   provider, phase, decision, reason_code, sensitivity=None, clearance=None,
   run_id=None) que inserta una fila. Llámala desde check()/can_send() en
   los puntos donde se determina allowed o blocked -- decide si check()
   debe loguear siempre o solo cuando decision="blocked" (RFC-006 no lo
   especifica con ese detalle; loguear ambos casos es más útil para medir
   policy_evaluation_coverage, RFC-007 §10.1, así que preferí loguear ambos
   salvo que eso genere volumen inmanejable en el hot path -- usa buen
   juicio y documenta la decisión con un comentario de una línea).
3. REGLA DURA, no negociable: reason_code es SIEMPRE un código corto de una
   lista cerrada (por ejemplo "no_active_policy", "provider_blocked",
   "clearance_insufficient", "unknown_sensitivity", "secret_pattern_detected",
   "allowed"), NUNCA texto libre que pueda contener fragmentos de la tarea
   o del proyecto de forma no controlada.
4. Tests en tests/test_egress.py: test_egress_log_does_not_store_payload
   (pasa un prompt con contenido reconocible como argumento a check()/complete(),
   verifica que ninguna fila de egress_decisions ni ningún argumento de
   log_decision contiene ese contenido), test_blocked_decision_is_logged,
   test_allowed_decision_is_logged (o solo blocked, según lo que decidas en
   el punto 2 -- ajusta el test a lo que implementaste).
5. pytest tests/ -v verde.
```

#### PR 1.10 — `router-eval --offline` (commit #12)

*Archivos:* nuevo comando CLI, nuevo `orchestrator/eval.py` (o extender `router.py`).

*Diseño (RFC-006 §7.3, RFC-004 §5.3 — coincide en ambas rondas: no hace falta telemetría nueva):*

| Dato | Dónde | Estado |
|---|---|---|
| Provider elegido por el router LLM | `runs.provider` | existe |
| Razón del ruteo | `runs.routing_reason` | existe |
| Calidad, juzgada por humano | `runs.rating` ∈ `{useful, partial, wrong}` | existe |
| Costo del router externo | `router_cost_usd` en `runs` | existe |
| Filtro de elegibilidad preciso | `routing_source = 'llm_router'` | agregado en Fase 0 PR 0.3 |

*Prompt Codex:*
```
Contexto: con egress_decisions y decide_with_local_router() ya existentes,
hay suficiente para el primer análisis offline de acuerdo entre el router
LLM externo (histórico, en runs.provider) y lo que el router local habría
elegido recalculado ahora sobre esos mismos runs -- sin llamar a ningún
provider real. RFC-006 §7.3 y RFC-004 §5.3 son explícitos: no hay que
construir telemetría nueva, runs.provider, runs.routing_reason, runs.rating
y router_cost_usd ya existen.

Tarea:
1. Crea orchestrator/eval.py con una función offline_router_eval(config,
   project=None, limit=500) que:
   - selecciona runs de SQLite con status='done', task != '', y si
     routing_source ya existe (PR 0.3 de Fase 0) filtra
     routing_source='llm_router' -- si esa columna todavía no existe en
     el momento de ejecutar este PR, cae de vuelta a status='done' AND
     task != '' sin el filtro adicional (verifica primero con PRAGMA
     table_info(runs) si la columna está presente).
   - para cada run, recalcula local_choice = decide_with_local_router(
     row["task"], ctx_del_proyecto, config) SIN llamar a ningún provider
     real (decide_with_local_router ya no hace red).
   - agreement_rate = fracción donde local_choice.provider == row["provider"]
   - rating_coverage = fracción de esos runs con rating no nulo
   - external_router_spend_usd = SUM(router_cost_usd) sobre el mismo conjunto
   - devuelve todo junto, NUNCA agreement_rate solo sin rating_coverage al lado.
2. Agrega el comando `ai-orchestrator router-eval --offline [--project X]
   [--limit N]` en cli.py que llama a esto e imprime el reporte. Si el N
   elegible es menor a 200, imprime una advertencia explícita de que el
   resultado es direccional, no concluyente (RFC-006 §7.6 declara N >= 200
   como criterio mínimo).
3. IMPORTANTE: esta función NUNCA debe hacer una llamada de red -- ni al
   router LLM externo ni a ningún provider. Es un replay puro sobre datos
   ya existentes en SQLite.
4. Tests en un nuevo tests/test_eval.py: test_offline_eval_never_calls_network
   (mockea httpx a nivel global durante el test y confirma 0 llamadas),
   test_offline_eval_computes_agreement_and_coverage_together (verifica que
   el resultado siempre incluye ambos números, nunca uno sin el otro).
5. pytest tests/ -v verde.
```

**Salida de Fase 1:** los 12 commits de RFC-006 reconstruidos contra `production@4ae9497` real, con invariantes I1-I14 completas y verificadas en CI (§10.1 de v0.3, ahora sin huecos). H1a/H1b con evidencia pública completa por primera vez en la serie.

### 11.3 Fase 2 — Separación política/contexto (evolución de seguridad, no parte del gate validado)

Con Fase 1 completa, el router local ya es real (no "modo sombra" — decide de verdad en cascada cuando el externo está bloqueado). Lo único que RFC-007 v0.3 §8 proponía y que RFC-006 no implementó es separar `sensitivity`/`blocked_providers` de `context.yaml` a un `policy.yaml` propio, para que un agente con permiso de escritura sobre el repo no pueda rebajar su propia política vía prompt injection editando el mismo archivo que declara sus convenciones de código.

#### PR 2.1 — `policy.yaml` separado, con precedencia sobre `context.yaml`

*Prompt Codex:*
```
Contexto: desde Fase 1, sensitivity/blocked_providers/allowed_providers
viven en .orchestrator/context.yaml, el mismo archivo que stack/conventions/
routing_notes. RFC-007 v0.3 §8 señala el riesgo: un agente con permiso de
escritura sobre el repo (o una inyección de prompt vía contenido del propio
repo) podría editar ese archivo para rebajar su propia sensibilidad o
desbloquear un provider. Este PR mueve la política a un archivo separado.

Tarea:
1. Define .orchestrator/policy.yaml con el mismo shape de campos
   (sensitivity, blocked_providers, allowed_providers) que hoy están en
   context.yaml.
2. En orchestrator/egress.py o context.py, al construir la EgressPolicy de
   un proyecto: si existe policy.yaml, sus valores tienen PRECEDENCIA sobre
   cualquier campo equivalente que todavía esté en context.yaml (para no
   romper proyectos migrados a medias). Si policy.yaml no existe, cae de
   vuelta a los campos de context.yaml (compatibilidad hacia atrás).
3. Agrega un comando de migración `ai-orchestrator policy migrate --project X`
   que lee sensitivity/blocked_providers/allowed_providers de context.yaml,
   los escribe en policy.yaml, y los remueve de context.yaml (edición no
   destructiva del resto del archivo, sigue el patrón de
   context.py::save_skip_dirs).
4. Tests que verifiquen la precedencia (policy.yaml gana si ambos existen)
   y la compatibilidad hacia atrás (solo context.yaml sigue funcionando).
5. pytest tests/ -v verde.
```

### 11.4 Fase 3 — Ledger rico: explícitamente diferido

RFC-005 propuso `decision_events`/`context_lineage`/`outcome_events` con hash chaining. **RFC-006 §8 lo marca fuera de alcance de forma explícita hasta 500 runs gobernados reales**, y critica a RFC-005 por "scope creep con 0 runs" (RFC-006 Apéndice D). Este documento adopta esa misma disciplina: **no generar PRs para el ledger rico todavía.** La tabla lean `egress_decisions` (Fase 1, PR 1.9) es suficiente registro hasta que exista volumen real. Cuando `SELECT COUNT(*) FROM runs WHERE status='done'` supere ~500, retomar este documento y diseñar Fase 3 recién ahí, contra datos reales en vez de proyecciones.

### 11.5 Fase 4 — Canary (regla de decisión ya declarada, RFC-006 §7.5-7.6)

No requiere diseño nuevo — solo ejecutar lo que la serie ya definió con precisión:

```python
# RFC-005 §12.3 / RFC-006 §7.5
canary = stable_hash(project + task_hash) % 100 < canary_percentage   # hash determinístico, no aleatorio por sesión
```

Elegibilidad: proyectos `internal` únicamente (en `restricted` el router externo ya está bloqueado y no hay contrafactual observable); no `forced_model`; política y `policy_version` registradas.

Regla de decisión, declarada antes de mirar datos (RFC-006 §7.6, la versión más refinada de la serie):

```text
Fase A (offline, N >= 200, solo proyectos internal):
  agreement_rate >= 0.80 → pasar a canary.
  agreement_rate <  0.80 → inspeccionar divergencias a mano; si el local elige
                            sistemáticamente más barato sin peor rating donde
                            coincide, pasar a canary igual.

Fase B (canary, 20% de runs internal):
  local_quality >= external_quality (por rating) → borrar el router externo.
                                                     Se ahorra SUM(router_cost_usd).
  external_quality > local_quality de forma material → conservar cascada.
```

*PR único de esta fase (implementación técnica, la decisión estadística es un análisis posterior, no código):*

```
Prompt Codex:
Contexto: router-eval --offline (Fase 1 PR 1.10) y decide_with_local_router
(Fase 1 PR 1.4) ya existen. Falta la capacidad técnica de correr un canary
real: un porcentaje configurable de runs usan la decisión del router local
COMO DECISIÓN REAL en vez de solo comparación offline, seleccionados por
hash determinístico y reproducible.

Tarea:
1. Agrega canary_percentage: 0 (default) en la sección router de config.yaml.
2. En decide_provider() (orchestrator/router.py), solo para proyectos con
   sensitivity="internal" y sin forced_model: calcula
   stable_hash(project + task) % 100 < canary_percentage (usa hashlib.sha256,
   documenta la fórmula exacta en un comentario). Si cae dentro del canary,
   usa decide_with_local_router() como decisión REAL (routing_source=
   "local_router_canary") y NO llames al router LLM externo para ese run.
3. Si canary_percentage es 0 (default), el comportamiento debe ser
   bit a bit idéntico al de Fase 1 -- test obligatorio que lo confirme.
4. pytest tests/ -v verde.

No implementes el análisis estadístico de no-inferioridad -- eso es un
artefacto de análisis sobre datos reales, posterior a correr el canary,
no código de este PR.
```

### 11.6 WP-Net-1 — Dashboard con `--host` + token

(Sin cambios respecto de la revisión 1 de este documento — ver detalle completo más abajo, independiente de la serie RFC-001…006.)

*Archivos:* `orchestrator/server.py` (línea 1448 `ThreadedServer`, línea 1392/1415 CORS, dispatch de `do_POST` línea 546-570), `orchestrator/cli.py` (comando `serve`).

*Prompt Codex:*
```
Contexto: orchestrator/server.py expone el dashboard SOLO en 127.0.0.1
(línea ~1448), sin flag --host y sin autenticación en ninguna de las ~20
rutas POST del dispatch (líneas 546-570) ni en los GET. RFC-007 (WP-Net-1)
autoriza acceso multi-dispositivo SOLO si viene con autenticación
obligatoria.

Tarea:
1. Agrega un flag --host (default "127.0.0.1") al comando `serve` en cli.py.
   Warning explícito si el valor no es loopback.
2. Al arrancar, genera un token con secrets.token_urlsafe(32), imprímelo
   UNA VEZ en consola.
3. Al inicio de do_GET y do_POST: si el binding no es loopback, exige
   Authorization: Bearer <token> válido o 401, antes del dispatch existente.
   Si es loopback (default), el token es opcional -- no romper el uso local
   actual.
4. Tests en tests/test_dashboard.py: sin token contra no-loopback -> 401;
   con token -> pasa; loopback default sin --host -> sigue funcionando sin
   token.
5. pytest tests/ -v verde.
```

### 11.7 Fase 5-6 — Provenance completo y gobernanza multiagente

Sin cambios: dependen de RN-1 (threat model), RN-2 (ontología de agentes), EP-1 (pre-registro H2) — investigación no iniciada. No se generan PRs hasta que 500 runs gobernados existan (gatilla Fase 3) y esos RN/EP se cierren.

---

## 12. Trabajo diferido

RN-1 (threat model), RN-2 (ontología de agentes), RN-3 (estado del arte), EP-1 (pre-registro H2), RN-4 (métricas de fragmentación), RN-5 (modelo de degradación), RN-6 (planos formales).

## 13. Riesgos

- **Deriva entre este documento y el código real.** Cada PR cita líneas verificadas el 2026-07-12 contra `4ae9497`. Cada prompt Codex pide releer el archivo antes de editar, no asume el número de línea a ciegas.
- **El patch efímero de RFC-006 nunca se probó contra ESTE checkout exacto** — se probó contra un checkout del mismo commit, pero como parche aplicado localmente y descartado. Este documento reconstruye la misma lógica PR por PR contra el árbol real; es razonable esperar pequeñas fricciones de integración (nombres de función ligeramente distintos, por ejemplo) que RFC-006 no documenta porque nunca se mergeó. Cada PR de Fase 1 pide a Codex correr `pytest tests/ -v` como último paso — ahí aparecerán.
- **`routing_source` (Fase 0 PR 0.3) no es parte de RFC-006.** Es una adición de este documento. Si en algún punto entra en conflicto con el diseño de `router-eval --offline` de PR 1.10, PR 1.10 tiene precedencia (es lo validado) y `routing_source` se usa solo como filtro opcional, nunca como dependencia dura.

---

## Conclusión

La revisión 1 de este documento diseñó un gate propio sin saber que uno mejor ya existía, probado, en el disco del usuario. La revisión 2 no inventa nada: reconstruye contra el código real de `production@4ae9497` los 12 commits que la serie RFC-001→006 ya validó localmente (15 invariantes, `pytest tests/test_egress.py` → 15 passed, `pytest tests/` → 126 passed / 1 failed pre-existente), en el mismo orden, con las mismas invariantes, incluyendo el hallazgo más valioso de toda la serie — I14, el falso bloqueo que un test de seguridad anterior protegía por error.

La siguiente acción sigue sin ser un documento: es pegar el prompt de PR 0.1 en Codex.

---

## Apéndice A — Invariantes I1-I14 (RFC-006 §4.3, completas)

| # | Invariante | Origen |
|---|---|---|
| I1 | Sin política, ninguna llamada LLM con contexto sale por `BaseProvider` | RFC-001 |
| I2 | Proyecto `restricted` no llega a proveedor `public` | RFC-001 |
| I3 | Streaming no bypassea el gate | RFC-001 |
| I4 | Ningún provider sobreescribe el borde (inspección de fuente) | RFC-001 |
| I5 | Router degrada a router local, no filtra | RFC-001 |
| I6 | Falla cerrado **solo** si ningún proveedor pasa | RFC-001, reformulado |
| I7 | Typo en política falla cerrado | RFC-001 |
| I8 | `similar_runs` no cruza proyectos | RFC-001 |
| I9 | El borde es sellado en definición de clase (`__init_subclass__`) | RFC-002 |
| I10 | Secreto en el prompt escala a `secret` y bloquea | RFC-002 |
| I11 | El check de streaming es eager, no diferido | RFC-003 |
| I12 | La política no se filtra entre threads | RFC-003 |
| I13 | Una denegación de política nunca se reintenta | RFC-004 |
| **I14** | **Fallback bloqueado no aborta si existe otro proveedor seguro** | **RFC-006** |

I4′: I9 reemplaza funcionalmente a I4; I4 se conserva como red redundante. I15 vacía a propósito.

## Apéndice B — Vigencia documental

| Doc | Ruta | Rol | Vigencia |
|---|---|---|---|
| RFC-001 (ronda 0) | `archive/RFC-001-egress-gate.md` | Primer hallazgo del bug, primer diseño | Archivada, superseded por 002 |
| RFC-002 | `archive/RFC-002-egress-gate.md` | `__init_subclass__`, secret escalation | Archivada, superseded por 003 |
| RFC-003 | `archive/RFC-003-provider-safe-routing.md` | Streaming eager, threads, alcance de `model_discovery` | Archivada, superseded por 004 |
| RFC-004 | `archive/RFC-004-egress-gate.md` | I13, orden de commits | Archivada, superseded por 006 (005 en medio) |
| RFC-005 | `archive/RFC-005-governed-decision-provenance.md` | PGDP, prior art, ledger rico (diferido) | Archivada; vigente solo como referencia de posicionamiento (§0-5) y prior art (§4) — su modelo de datos (§7) diferido a Fase 3 |
| RFC-006 | `rfcs/RFC-006-provider-safe-routing.md` | Diseño final validado localmente, I1-I14 completas | **Vigente — fuente de verdad para la Parte II de este documento** |
| RFC-007 v0.3 | `archive/RFC-007-ai-control-plane-v0.3.md` | Documento rector, analítico | Archivada, superseded por esta versión |
| RFC-007 (esta) | `rfcs/RFC-007-ai-control-plane.md` | Documento rector + plan ejecutable, alineado con RFC-006 | Vigente |
| RFC-008 v0.1 | `rfcs/RFC-008-governed-mcp-access.md` | MCP gobernado, plan ejecutable propio | Vigente, en paralelo |

## Apéndice C — Recetas de acceso remoto soportadas hoy

```bash
ssh -L 8080:127.0.0.1:8080 usuario@host-A
```

MCP remoto: ver RFC-008 §11.4.

## Apéndice D — Orden de ejecución para Codex

```text
Fase 0   PR 0.1  CI corre pytest completo
         PR 0.2  Fix I8 (adelanta commit #7 de RFC-006, independiente)
         PR 0.3  Migración routing_source (hygiene, no bloqueante contra RFC-006)
Fase 1   PR 1.1  egress.py: ContextVar sin default, EgressBlocked, check()/can_send()   [commit #2 — I1,I2,I7]
         PR 1.2  Sellar BaseProvider vía __init_subclass__, 4 providers                  [commit #3 — I3,I4,I9,I11]
         PR 1.3  Sensitivity de proyecto + clearance de provider                         [commit #4]
         PR 1.4  decide_with_local_router()                                              [commit #5]
         PR 1.5  Cerrar pre-routing egress + fix del falso bloqueo                       [commit #6 — I5,I6,I14]
         PR 1.6  Escalación por secreto (_contains_secrets reutilizada)                  [commit #8 — I10]
         PR 1.7  Política dentro del worker thread                                       [commit #9 — I12]
         PR 1.8  Nunca reintentar EgressBlocked                                          [commit #10 — I13]
         PR 1.9  Tabla egress_decisions (decisión, nunca payload)                        [commit #11]
         PR 1.10 router-eval --offline                                                    [commit #12]
WP-Net-1 PR N.1  Dashboard --host + token                                                [elegible en paralelo desde Fase 1]
Fase 2   PR 2.1  policy.yaml separado de context.yaml, con precedencia
Fase 3   [diferida hasta 500 runs gobernados reales — no generar PRs todavía]
Fase 4   PR 4.1  Canary por hash determinístico [regla de decisión ya declarada, §11.5]
Fase 5-6 [sin PRs -- depende de RN-1/RN-2/EP-1]
```
