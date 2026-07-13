# RFC-002: Egress Gate para ai-orchestrator

**Estado:** implementado y verificado contra `csantisdev/ai-orchestrator@production` (HEAD 2026-07-08).
**Suite:** `121 passed, 1 failed` — el fallo es pre-existente (`test_rag_index_and_retrieve`, requiere chromadb). **Cero regresiones.**
**Patch:** `egress-gate.patch` (+377 / −28, 11 archivos).

**Cambios desde RFC-001:** el conflicto de §4 pasó de "sin resolver" a "probablemente mal planteado". Se agregaron dos invariantes (I9, I10) aportadas por revisión adversarial. La pregunta central cambió.

---

## 0. Qué se pide

Este RFC no pide validar una idea. El código existe, pasa tests y cierra una fuga reproducible.

Pide **atacar un experimento** (§5). Ese experimento decide si el router externo se conserva o se borra, y ninguna cantidad de arquitectura lo responde.

No sirve como respuesta:
- Reformular la tesis con mejor vocabulario.
- Citar prior art sin decir qué línea cambia.
- Proponer una capa nueva (memoria, grafo, bandit, taint semántico). Fuera de alcance, §7.

Sirve:
- Una ruta de fuga concreta, con archivo y línea, que los tests no cubren.
- Un ataque al diseño experimental de §5.
- Un contraejemplo ejecutable.

Formato en §8.

---

## 1. El bug (reproducido, no argumentado)

`router.py` implementa un router de dos capas: un modelo barato decide qué proveedor resuelve la tarea. Por defecto (`config.example.yaml:27`) ese router es **DeepSeek**.

El router recibe el contexto **antes** de que exista una decisión de proveedor. La política "este proyecto no usa free-tier" se evalúa después de que el dato ya salió.

Reproducción sin red, contra el código real:

```
$ python repro.py
Proyecto: restricted-project.example
Stack: PHP/Laravel 12 + MySQL
Descripción: Sistema interno con datos regulados de terceros.
Notas de ruteo del proyecto: Proyecto sensible: no usar proveedores free-tier.

Decisiones de ruteo previas en tareas similares:
- [restricted-project.example] → claude: "lógica de negocio sensible"
- [public-project-beta] → deepseek: "CRUD simple de recursos públicos"

Tarea a resolver:
"""Revisa el endpoint POST /resources/{id}/approve, filtra por identificador personal..."""

======================================================================
BYTES ENVIADOS AL ROUTER (deepseek por default): 752
  contiene 'restricted-project.example': True
  contiene 'identificador personal':                          True
  contiene 'public-project-beta':               True
  contiene 'sensible':                     True
```

**1.1 — Pre-routing egress.** El prompt enviado a DeepSeek contiene literalmente la política que prohíbe enviarlo a DeepSeek.

**1.2 — Fuga cross-project.** `_fetch_similar_runs(task, n=3)` (`router.py:124`) consulta el backend de similitud **global**. Ni `SimilarityBackend.query(text, n_results)` ni el fallback FTS5 aceptan `project`. Una tarea del proyecto A envía al router los nombres y razones de ruteo del proyecto B. Ocurre siempre, sin importar sensibilidad.

Severidad: **alta**. Vector: llamada al router. Alcance: nombre de proyecto, stack, descripción, convenciones, notas de ruteo, texto de la tarea, contexto activo, runs de otros proyectos.

---

## 2. Diseño

### 2.1 Fail-closed por construcción, no por disciplina

La política **no es un parámetro**. Un parámetro con default es lo que se olvida en el quinto call site.

```python
_POLICY: ContextVar[EgressPolicy] = ContextVar("egress_policy")   # sin default

def current_policy() -> EgressPolicy:
    try:
        return _POLICY.get()
    except LookupError as exc:
        raise EgressBlocked("Sin política activa, no sale nada.") from exc
```

No se puede olvidar pasarla. Solo se puede olvidar *establecerla*, y entonces nada sale.

### 2.2 El borde sellado, no el call site

`BaseProvider.complete()` y `complete_stream()` pasan de abstractos a **template methods concretos** que llaman al gate. Los providers implementan `_complete()` / `_complete_stream()`.

Crítico: los cuatro providers implementaban `complete_stream()` **directamente** con `httpx.stream(...)`. Un gate solo en `complete()` habría dejado cuatro rutas abiertas, y `background.py:131` usa exactamente esa ruta.

El borde se sella en tiempo de definición de clase:

```python
def __init_subclass__(cls, **kw):
    for method in ("complete", "complete_stream"):
        if method in cls.__dict__:
            raise TypeError(f"{cls.__name__} no puede sobreescribir {method}(). "
                            f"Implementa _{method}(). El borde de egress es sellado.")
```

Un provider nuevo que copie el patrón viejo **no importa**. Falla al definirse, no en producción.

El router queda cubierto sin caso especial: **el router es un provider**.

### 2.3 `check()` bloquea, `can_send()` consulta

- `check()` es la red de seguridad. Levanta. Nadie la puede olvidar.
- `can_send()` permite degradación elegante: el router elige otra ruta en vez de crashear.

Nunca hay fallback a un proveedor que tampoco pasa política. Eso sería el mismo bug con otro nombre.

### 2.4 Higiene de secretos en el payload

El gate valida `proyecto → proveedor`. No mira el contenido. Un `.env` que llega al `system_prompt` vía RAG pasaría.

`_contains_secrets()` **ya existía** (`rag.py:166`), usado solo al indexar. Se reutiliza en el borde:

```python
if payload and _has_secret(payload):
    policy = replace(policy, sensitivity="secret")   # ningún clearance la alcanza
```

No es taint semántico. Es higiene. Un secreto en el prompt eleva la sensibilidad efectiva del run.

### 2.5 Nivel desconocido = bloqueo

`sensitivity: confidencial` (typo, fuera del lattice) levanta `EgressBlocked`. Un error tipográfico en política de seguridad no debe degradar a permisivo.

---

## 3. Resultados medidos

### 3.1 El gate auditó la suite existente

Baseline antes del patch: `111 passed, 1 failed`.

Con el gate instalado, **sin** `conftest.py`:

```
22 failed, 90 passed
```

Los 22 fallos son el mismo error: `EgressBlocked: No hay política de egress activa`.

**21 tests alcanzaban un proveedor externo y ninguno declaraba política.** El gate no rompió los tests: los usó para enumerar las rutas de egress. Ese número es el hallazgo, no el daño.

Con `conftest.py` estableciendo política explícita: `121 passed, 1 failed` (el mismo de RAG).

### 3.2 Invariantes (`tests/test_egress.py`, 10 passed)

| # | Invariante | Verifica |
|---|---|---|
| I1 | Sin política, ninguna llamada sale | `LookupError → EgressBlocked` |
| I2 | Proyecto `restricted` no llega a proveedor `public` | comparación de clearance |
| I3 | **Streaming no bypassea el gate** | `_complete_stream` nunca se invoca |
| I4 | Ningún provider sobreescribe el borde | inspección de fuente |
| I5 | Router degrada, no filtra | `used_fallback=True`, razón explícita |
| I6 | No hay fallback inseguro | `EgressBlocked` si router **y** fallback bloqueados |
| I7 | Typo en política falla cerrado | `sensitivity: confidencial` → bloqueo |
| I8 | `similar_runs` no cruza proyectos | firma `(task, project, n)` |
| I9 | **El borde es sellado en definición de clase** | `__init_subclass__` → `TypeError` |
| I10 | **Secreto en el prompt escala a `secret` y bloquea** | reutiliza `_contains_secrets()` |

I9 e I10 provienen de revisión adversarial. I9 reemplaza funcionalmente a I4 (I4 se conserva como red redundante).

---

## 4. El conflicto de RFC-001, reformulado

Al ejecutar el PoC end-to-end apareció esto:

```
ai-orchestrator                sens=internal    → router deepseek: BLOQUEADO → 'claude'
restricted-project.example   sens=restricted  → router deepseek: BLOQUEADO → 'claude'
```

**El gate mata el modelo de costos.** El router de dos capas existe para que un modelo barato (`$0.14/M tokens`) decida el ruteo. Con `deepseek.clearance = public` y proyectos en `internal`, DeepSeek queda inhabilitado como router **para todos los proyectos**. Cada run paga Claude para decidir a quién llamar.

Tensión estructural:

> El router debe ver el contexto para decidir bien.
> El contexto es lo que no queremos que vea.
> El router es barato precisamente porque es el proveedor de menor confianza.

RFC-001 ofrecía tres salidas: (a) clearance por tier, (b) rutear sobre metadata, (c) router local. Revisión adversarial propuso (d): **cascada** — externo si pasa política, local si no, metadata en sombra.

La cascada es correcta en forma. **Pero el conflicto puede no existir.**

---

## 5. El experimento (esto es lo que hay que atacar)

Si el **router local determinístico** coincide con DeepSeek la mayoría de las veces, no necesitas DeepSeek como router **en ningún proyecto**. El conflicto no se resuelve: se disuelve. El router externo pasa de activo a proteger a **pasivo que cuesta plata y filtra contexto**.

La propuesta de "shadow del router metadata contra el router local" compara **dos cosas que no existen**. No produce datos.

El experimento correcto usa lo que ya está corriendo:

> **Ejecutar el router local en sombra contra el router externo, en proyectos no sensibles, sobre runs que ya se están pagando.**

Costo incremental: **cero**. Riesgo: **cero** (el local no decide nada). Ground truth: **ya se está recolectando**.

### 5.1 Instrumentación disponible hoy

| Dato | Dónde | Estado |
|---|---|---|
| Proveedor elegido por el router LLM | `runs.provider` | existe |
| Razón del ruteo | `runs.routing_reason` | existe |
| **Calidad del run, juzgada por humano** | `runs.rating` ∈ `{useful, partial, wrong}` | existe (migración `add_rating_to_runs`; botones en el dashboard) |
| **Costo del router externo** | `RoutingDecision.router_cost_usd` | existe (`router.py:67`) |

No hay que construir telemetría. Hay que leerla.

### 5.2 Diseño

1. En `decide_provider()`, tras obtener la decisión del router externo, calcular también `decide_with_local_router()` y **loguearla sin usarla**.
2. Correr N ≥ 200 runs en proyectos `internal`.
3. Medir:

```
agreement_rate    = local_choice == external_choice
local_quality     = rating de runs donde ambos coincidieron
divergence_cost   = rating de runs donde divergieron, por rama
external_router_spend = SUM(router_cost_usd)
```

### 5.3 Regla de decisión (declarada antes de mirar los datos)

```
si agreement_rate >= 0.80 y no hay diferencia de rating significativa:
    borrar el router externo. §4 desaparece. Se ahorra external_router_spend.

si agreement_rate < 0.80 pero local_quality >= external_quality:
    borrar el router externo igual. Coincidir no es la métrica; acertar sí.

si external_quality > local_quality de forma material:
    conservar cascada (d). Recién ahí evaluar router metadata.
```

### 5.4 Errores a evitar

- **`agreement_rate` mide acuerdo, no calidad.** Dos routers pueden coincidir y equivocarse los dos. El árbitro es `rating`, no el otro router.
- **`cost_saved_by_local_router_usd` no es medible** sin contrafactual. Pero `SUM(router_cost_usd)` sí, y es exactamente el dinero que se ahorra al borrar el router externo. No inventar métricas cuando la real ya se escribe.
- **Solo proyectos `internal`.** En `restricted` el router externo está bloqueado y no hay contrafactual que observar.

---

## 6. Orden de commits

```
1. feat: add fail-closed egress policy               (egress.py, I1/I2/I6/I7)
2. refactor: seal provider boundary via template methods  (I3/I4/I9)
3. feat: add project sensitivity and provider clearance
4. feat: add local deterministic router               ← antes que el 5
5. fix: prevent router egress before policy evaluation    (I5)
6. fix: restrict router similar-runs to current project   (I8)
7. feat: escalate effective sensitivity on secret in payload  (I10)
8. feat: log local-router shadow decisions            ← §5
```

**Corrección de orden:** el plan adversarial ponía el router local *después* del fix del router, pero el fix lo invoca. El 5 no compila hasta el 4. Invertidos.

El 2 hace que el 5 sea trivial. Al revés, el 5 parchea un agujero y deja cuatro rutas de streaming abiertas.

---

## 7. Fuera de alcance

No se implementa y no se discute en esta ronda:

- Memoria semántica, promotion gates, evidence lattice, memoria negativa
- Bandits, routing aprendido, recompensa diferida
- Router metadata-only en producción (solo tras §5)
- Provider profiles por tier (`deepseek_free` vs `deepseek_paid`)
- Propagación de sensibilidad por grafo de derivación
- Taint tracking semántico
- Declassification con revisión humana

Prior art relevante: FIDES (arXiv:2505.23643), NeuroTaint (arXiv:2604.23374), RL Developer Memory (arXiv:2605.01567). **Ninguno ataca §5**, que es economía de ruteo, no seguridad.

### 7.1 Riesgo conocido, no cerrado

`cli.py:~237` envuelve el bloque RAG en `except Exception: pass`. Hoy es disponibilidad. Si alguien mete política ahí adentro, se vuelve fail-open silencioso.

**Regla: el gate nunca dentro de un `try` sin `raise`.**

---

## 8. Formato de respuesta pedido

1. **Ruta de fuga que los tests no cubren.** Una, concreta, con archivo y línea. Si no encuentras ninguna, dilo.
2. **Ataque al experimento de §5.** ¿Está mal el diseño? ¿La regla de decisión de §5.3 es tramposa? ¿`rating` sirve como ground truth o está sesgado?
3. **Ataque a I1–I10.** ¿Cuál invariante es falsa o insuficiente? En particular: ¿es `ContextVar` la decisión correcta con threads y asyncio?
4. **Lo que quitarías.** Son +377 líneas, la mitad tests. ¿Cuántas sobran?
5. **Veredicto:** mergear a rama, iterar, o revertir.

No suavices. Si `ContextVar` no propaga a `threading.Thread` y `background.py` levanta threads, eso es un `EgressBlocked` en producción — di si eso es el fallo correcto o un bug.

---

## Apéndice A: aplicar

```bash
git checkout -b feat/egress-gate
git apply egress-gate.patch
pytest tests/ -q               # 121 passed, 1 failed (RAG, pre-existente)
pytest tests/test_egress.py -q # 10 passed
```

## Apéndice B: criterios de merge a `production`

1. Router bloqueado usa router local determinístico, no fallback fijo a Claude.
2. Streaming no bypassea el gate (I3).
3. Un provider nuevo no puede sobreescribir el borde (I9).
4. No hay fallback inseguro (I6).
5. `similar_runs` scoped por proyecto (I8).
6. `egress_decisions` registra `allowed`/`blocked` por `phase` ∈ `{router, provider, stream}`.
7. PoC `restricted-project` demuestra **cero bytes a DeepSeek**, ni como router ni como proveedor final.
8. `pytest tests/ -q` mantiene el único fallo pre-existente de RAG.

## Apéndice C: primera métrica viva

No es inteligencia. Es:

```
router_egress_blocked_total  > 0
fallback_inseguro            = 0
bytes_a_deepseek_en_restricted_project = 0
```

Si el primero es cero después de una semana, o no hay proyectos sensibles, o el gate no está corriendo. Ambas cosas merecen inspección.
