# RFC-004: Egress Gate + Provider-Safe Routing

**Repo:** `csantisdev/ai-orchestrator@production` (HEAD 2026-07-08)
**Supersede:** RFC-003, RFC-002, RFC-001
**Estado:** implementado y verificado. `pytest tests/ -q` → **125 passed, 1 failed** (`test_rag_index_and_retrieve`, pre-existente, requiere chromadb). **Cero regresiones.**
**Patch:** `egress-gate.patch` — +442 / −28, 12 archivos.
**Destino:** rama `feat/egress-gate`. No merge directo a `production`.

**Diferencia con RFC-003:** RFC-003 era una propuesta. Esto está corriendo. Los tres ajustes que RFC-003 exigía se implementaron, se probaron, y **uno de ellos destapó un bug que ningún RFC había visto** (§3.4).

---

## 0. Qué se pide

El código existe, cierra una fuga reproducible y pasa 14 tests de invariante. Este RFC **no pide validar la idea**.

Pide dos cosas:

1. **Atacar el experimento de §5.** Decide si el router externo se conserva o se borra. Ninguna cantidad de arquitectura lo responde.
2. **Encontrar la invariante que falta.** Trece no son suficientes. Cada RFC previo encontró una que el anterior no vio.

No sirve: reformular la tesis, citar prior art sin señalar una línea, proponer una capa nueva (§7).
Sirve: una ruta de fuga con archivo y línea; un ataque al diseño experimental; un contraejemplo ejecutable.

Formato en §9.

---

## 1. El bug

`router.py` usa un router de dos capas: un modelo barato decide qué proveedor resuelve la tarea. Por defecto (`config.example.yaml:27`) ese router es **DeepSeek**.

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

**1.1 — Pre-routing egress.** El prompt que sale a DeepSeek contiene literalmente la política que prohíbe enviarlo a DeepSeek.

**1.2 — Cross-project leak.** `_fetch_similar_runs(task, n=3)` (`router.py:124`) consulta el backend de similitud **global**. Ni `SimilarityBackend.query(text, n_results)` ni el fallback FTS5 aceptan `project`. Una tarea del proyecto A envía al router los nombres y razones de ruteo del proyecto B. Ocurre siempre, sin importar sensibilidad.

```
Severity: High
Tipo:     Sensitive context egress before policy enforcement
Vector:   router LLM call
Scope:    project metadata, task text, routing notes, active context, similar runs
Default:  router.provider = deepseek
```

No es `critical`: el PoC no demostró exfiltración de secretos reales. Pero el diseño permite egress sensible por defecto.

---

## 2. Alcance

### 2.1 Dentro

Egress de **prompt y contexto** hacia un LLM: prompts, system prompts, streaming, router prompts, bloques RAG, texto de la tarea, contexto de proyecto.

### 2.2 Fuera, pero auditado

`orchestrator/discovery/{anthropic,deepseek,gemini,openai}.py` hacen `httpx.get()` directo para listar modelos. **Verificado: no envían prompt ni contexto de proyecto.**

```
model_discovery = egress externo NO contextual
No bloquea este RFC.
Issue separado: audit: classify model discovery under non-contextual egress policy
```

### 2.3 Enunciado corregido de I1

RFC-002 decía: *"Sin política, ninguna llamada sale."* Falso — `model_discovery` sale.

Enunciado correcto:

> **Sin política activa, ninguna llamada LLM con prompt o contexto sale por `BaseProvider`.**

Cubrir todo egress externo requiere un segundo gate sobre `httpx.*` fuera de providers. Otro RFC.

---

## 3. Diseño

### 3.1 Fail-closed por construcción, no por disciplina

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

### 3.2 El borde sellado

`BaseProvider.complete()` y `complete_stream()` son template methods concretos. Los providers implementan `_complete()` / `_complete_stream()`.

Crítico: los cuatro providers implementaban `complete_stream()` **directamente** con `httpx.stream(...)`. Un gate solo en `complete()` habría dejado cuatro rutas abiertas, y `background.py:131` usa exactamente esa ruta.

Sellado en tiempo de definición de clase:

```python
def __init_subclass__(cls, **kw):
    for method in ("complete", "complete_stream"):
        if method in cls.__dict__:
            raise TypeError(f"{cls.__name__} no puede sobreescribir {method}(). "
                            f"Implementa _{method}(). El borde de egress es sellado.")
```

Un provider nuevo que copie el patrón viejo **no importa**. Falla al definirse, no en producción.

El router queda cubierto sin caso especial: **el router es un provider**.

### 3.3 `complete_stream()` no puede ser generator function

Aporte de RFC-003, verificado.

```python
# MAL: el cuerpo se difiere al primer next(). El caller no ve EgressBlocked.
def complete_stream(self, prompt, system=""):
    egress.check(...)
    result = yield from self._complete_stream(prompt, system)
    return result

# BIEN: check eager, retorna el generator.
def complete_stream(self, prompt, system=""):
    egress.check(...)
    return self._complete_stream(prompt, system)
```

**Matiz que RFC-003 no hace: no era una fuga.** `_complete_stream` también es lazy y `check()` corre primero en el cuerpo. Cero HTTP antes del gate, verificado. Era un defecto de API: `try: gen = p.complete_stream(...) except EgressBlocked:` nunca capturaba.

Lección: el test original (I3) usaba `list(...)`, que fuerza iteración. **Pasaba probando algo distinto de lo que su nombre decía.** I11 sella la propiedad real con `inspect.isgeneratorfunction()`.

### 3.4 `ContextVar` no propaga a threads — y el retry se comía la denegación

`background.py:45` lanza `threading.Thread`. `ContextVar` **no** se copia a un thread nuevo. Probado:

```
=== ¿ContextVar propaga a threading.Thread? ===
  worker: NO propagó -> EgressBlocked
```

Sin arreglo, **todo run en background moría**. Fix: `_set_worker_policy(ctx, config)` como primera sentencia del worker.

Y al arreglarlo apareció lo que ningún RFC vio. `background.py:145`:

```python
except Exception as exc:        # captura EgressBlocked
    _last_exc = exc
    retry con backoff exponencial
```

**Una denegación de política se reintentaba 3 veces como si fuera un timeout de API.** No filtra, pero es semánticamente falso, contamina logs y triplica la latencia del fallo. Fix:

```python
except EgressBlocked:
    raise          # una denegación de política nunca es transitoria
except Exception as exc:
    ...
```

### 3.5 `check()` bloquea, `can_send()` consulta

- `check()` es la red de seguridad. Levanta. Nadie la puede olvidar.
- `can_send()` permite degradación elegante: el router elige otra ruta en vez de crashear.

Nunca hay fallback a un proveedor que tampoco pasa política. Eso sería el mismo bug con otro nombre.

### 3.6 Higiene de secretos en el payload

El gate valida `proyecto → proveedor`. No mira el contenido. Un `.env` que llega al `system_prompt` vía RAG pasaría.

`_contains_secrets()` **ya existía** (`rag.py:166`), usado solo al indexar. Se reutiliza en el borde:

```python
if payload and _has_secret(payload):
    policy = replace(policy, sensitivity="secret")   # ningún clearance la alcanza
```

No es taint semántico. Es higiene. **El log nunca guarda el payload.**

### 3.7 Nivel desconocido = bloqueo

`sensitivity: confidencial` (typo, fuera del lattice) levanta `EgressBlocked`. Un error tipográfico en política de seguridad no debe degradar a permisivo.

---

## 4. Resultados medidos

### 4.1 El gate auditó la suite existente

Baseline antes del patch: `111 passed, 1 failed`.

Con el gate instalado, **sin** `conftest.py`:

```
22 failed, 90 passed
```

Los 22 fallos son el mismo error: `EgressBlocked: No hay política de egress activa`.

**21 tests alcanzaban un proveedor externo y ninguno declaraba política.** El gate no rompió los tests: los usó para enumerar las rutas de egress. Ese número es el hallazgo, no el daño.

Con `conftest.py` estableciendo política explícita: `125 passed, 1 failed`.

### 4.2 Invariantes (`tests/test_egress.py`, 14 passed)

| # | Invariante | Origen |
|---|---|---|
| I1 | Sin política, ninguna llamada LLM con contexto sale por `BaseProvider` | RFC-001 |
| I2 | Proyecto `restricted` no llega a proveedor `public` | RFC-001 |
| I3 | Streaming no bypassea el gate | RFC-001 |
| I4 | Ningún provider sobreescribe el borde (inspección de fuente) | RFC-001 |
| I5 | Router degrada, no filtra | RFC-001 |
| I6 | No hay fallback inseguro | RFC-001 |
| I7 | Typo en política falla cerrado | RFC-001 |
| I8 | `similar_runs` no cruza proyectos | RFC-001 |
| I9 | El borde es sellado en definición de clase (`__init_subclass__`) | RFC-002 |
| I10 | Secreto en el prompt escala a `secret` y bloquea | RFC-002 |
| **I11** | **El check de streaming es eager, no diferido** | **RFC-003** |
| **I12** | **La política no se filtra entre threads** | **RFC-003** |
| **I13** | **Una denegación de política nunca se reintenta** | **este RFC** |

I9 reemplaza funcionalmente a I4; I4 se conserva como red redundante.

---

## 5. El experimento (esto es lo que hay que atacar)

### 5.1 El conflicto

```
ai-orchestrator                sens=internal    → router deepseek: BLOQUEADO
restricted-project.example   sens=restricted  → router deepseek: BLOQUEADO
```

**El gate mata el modelo de costos.** El router de dos capas existe para que un modelo barato (`$0.14/M`) decida el ruteo. Con `deepseek.clearance = public` y proyectos en `internal`, DeepSeek queda inhabilitado como router **para todos los proyectos**.

> El router debe ver el contexto para decidir bien.
> El contexto es lo que no queremos que vea.
> El router es barato precisamente porque es el proveedor de menor confianza.

### 5.2 Hipótesis: el conflicto puede no existir

Si el **router local determinístico** acierta tanto como DeepSeek, el router externo pasa de activo a proteger a **pasivo que cuesta plata y filtra contexto**. Se borra, y §5.1 desaparece.

### 5.3 Diseño del experimento (offline replay, corrección de RFC-003)

RFC-002 proponía shadow en vivo. RFC-003 corrigió: **empezar offline**. Sin red, sin costo, sin riesgo, sobre runs históricos.

```bash
ai-orchestrator router-eval --offline --limit 500
```

Para cada run histórico: recalcular qué habría elegido `decide_with_local_router()` y comparar contra `runs.provider`.

**Instrumentación ya existente. No hay telemetría que construir:**

| Dato | Dónde | Estado |
|---|---|---|
| Proveedor elegido por el router LLM | `runs.provider` | existe |
| Razón del ruteo | `runs.routing_reason` | existe |
| Calidad del run, juzgada por humano | `runs.rating` ∈ `{useful, partial, wrong}` | existe (migración `add_rating_to_runs`) |
| Costo del router externo | `RoutingDecision.router_cost_usd` | existe (`router.py:67`) |

### 5.4 El límite del método (aporte de RFC-003)

> **En las divergencias, la calidad del router local no es observable.**

Si el externo eligió Claude y el local habría elegido OpenAI, `rating` solo evalúa a Claude. El contrafactual no existe.

Consecuencia: el offline replay mide **acuerdo** y **costo**, no calidad en divergencia. Para calidad se necesita **canary controlado** — el local decide de verdad, en un % de runs, en proyectos no sensibles.

Esto es una restricción del diseño, no un defecto a arreglar. Declararla evita concluir de más.

### 5.5 Regla de decisión (declarada antes de mirar los datos)

```
Fase 1 — offline replay, N ≥ 200 runs, solo proyectos internal:

  si agreement_rate >= 0.80:
      pasar a canary. La divergencia es lo bastante rara como para arriesgarla.

  si agreement_rate < 0.80:
      inspeccionar las divergencias a mano antes de cualquier canary.
      Si el local elige sistemáticamente más barato sin señal de peor rating
      en los runs donde coincide, seguir a canary igual.

Fase 2 — canary, 20% de runs en proyectos internal, el local decide:

  si local_quality >= external_quality (por rating):
      borrar el router externo. Se ahorra SUM(router_cost_usd).

  si external_quality > local_quality de forma material:
      conservar cascada. Recién ahí evaluar router metadata-only.
```

### 5.6 Errores a evitar

- **`agreement_rate` mide acuerdo, no calidad.** Dos routers pueden coincidir y equivocarse los dos. El árbitro es `rating`.
- **`cost_saved_by_local_router_usd` no es medible** sin contrafactual. Pero `SUM(router_cost_usd)` sí, y es exactamente el dinero que se ahorra al borrar el router externo. No inventar métricas cuando la real ya se escribe.
- **`rating` está sesgado**: solo se puntúan los runs que el usuario mira. Reportar `rating_coverage` junto a cualquier conclusión.
- **Solo proyectos `internal`.** En `restricted` el router externo está bloqueado y no hay contrafactual observable.

---

## 6. Orden de commits

```
1. feat: add fail-closed egress policy                      (egress.py; I1 I2 I6 I7)
2. refactor: seal provider boundary via template methods     (I3 I4 I9 I11)
3. feat: add project sensitivity and provider clearance
4. feat: add local deterministic router                      ← antes del 5
5. fix: prevent router egress before policy evaluation       (I5)
6. fix: restrict router similar-runs to current project      (I8)
7. feat: escalate effective sensitivity on secret in payload (I10)
8. fix: set egress policy inside background worker thread    (I12)
9. fix: never retry a policy denial as a transient failure   (I13)
10. feat: router-eval --offline                              (§5)
```

**Corrección de orden:** el plan de RFC-003 ponía el router local *después* del fix del router, pero el fix lo invoca. El 5 no compila hasta el 4.

El 2 hace que el 5 sea trivial. Al revés, el 5 parchea un agujero y deja cuatro rutas de streaming abiertas.

---

## 7. Fuera de alcance

No se implementa ni se discute en esta ronda:

memoria semántica · promotion gates · evidence lattice · memoria negativa · bandits · reward diferido · router metadata-only en producción · provider profiles por tier · taint tracking semántico · declassification humana · políticas enterprise/SOC 2

Prior art: FIDES (arXiv:2505.23643), NeuroTaint (arXiv:2604.23374), RL Developer Memory (arXiv:2605.01567). **Ninguno ataca §5**, que es economía de ruteo, no seguridad.

### 7.1 Riesgos residuales

| Riesgo | Severidad | Estado |
|---|---|---|
| `model_discovery` fuera del gate | baja | clasificado, issue separado (§2.2) |
| secreto no detectado por el regex | alta | mitigación parcial (I10); el regex es una lista, no una prueba |
| `except Exception: pass` en `cli.py:~237` (bloque RAG) | media | **abierto.** Hoy es disponibilidad. Si alguien mete política ahí, es fail-open silencioso |
| post-filtro de `similar_runs` reduce recall | baja | aceptado; v2 con query scoped en el backend |
| `reason` en `egress_decisions` filtra nombres de proyecto | baja | log local; nunca guarda payload |
| demasiados bloqueos elevan costo | media | es exactamente lo que mide §5 |

**Regla dura: el gate nunca dentro de un `try` sin `raise`.**

---

## 8. Criterios de merge

### 8.1 A rama `feat/egress-gate` — cumplidos

- [x] `pytest tests/test_egress.py -q` → 14 passed
- [x] `pytest tests/ -q` → 125 passed, 1 failed (pre-existente)
- [x] Borde sellado (`__init_subclass__`)
- [x] Streaming no bypassea, y el check es eager
- [x] Router bloqueado no llama al proveedor externo
- [x] No hay fallback inseguro
- [x] `similar_runs` scoped por proyecto
- [x] `egress_decisions` registra `allowed`/`blocked` por `phase`, sin payload
- [x] Worker fija su propia política dentro del thread
- [x] Denegación de política no se reintenta

### 8.2 A `production` — pendientes

- [ ] PoC `restricted-project` demuestra **cero bytes a DeepSeek**, ni como router ni como proveedor final
- [ ] `decide_with_local_router()` implementado (hoy el fallback sigue siendo `ctx.default_provider`)
- [ ] `router-eval --offline` corre sobre ≥ 200 runs, o reporta muestra insuficiente
- [ ] `egress_decisions` muestra `phase=router decision=blocked` para el PoC
- [ ] Alcance de `model_discovery` documentado en el repo

---

## 9. Formato de respuesta pedido

1. **Ruta de fuga que los 14 tests no cubren.** Una, con archivo y línea. Si no encuentras ninguna, dilo — es una respuesta válida y más útil que inventar una.
2. **Ataque al experimento (§5).** ¿La regla de §5.5 es tramposa? ¿`rating` sirve como ground truth con `rating_coverage` bajo? ¿Cómo se elige el 20% del canary sin sesgo?
3. **Ataque a I1–I13.** ¿Cuál es falsa o insuficiente? En particular: I10 depende de un regex; ¿qué secreto real lo evade?
4. **Lo que quitarías.** +442 líneas, 167 de tests. ¿Cuántas sobran?
5. **Veredicto:** mergear a rama, iterar, o revertir.

No suavices.

---

## Apéndice A: aplicar

```bash
git checkout -b feat/egress-gate
git apply egress-gate.patch
pytest tests/ -q                  # 125 passed, 1 failed (RAG, pre-existente)
pytest tests/test_egress.py -q    # 14 passed
```

## Apéndice B: primera métrica viva

No es inteligencia. Es:

```
router_egress_blocked_total       > 0
fallback_inseguro                 = 0
bytes_a_deepseek_en_restricted_project   = 0
```

Si el primero sigue en cero tras una semana: o no hay proyectos sensibles, o el gate no corre, o la config no aplica `sensitivity`/`clearance`. Las tres merecen inspección.

## Apéndice C: qué aprendió cada ronda

| RFC | Aportó | Lo que no vio |
|---|---|---|
| 001 | El bug; `ContextVar` sin default; borde en `BaseProvider` | I3 pasaba probando otra cosa |
| 002 | `__init_subclass__`; escalación por secreto | streaming diferido; threads |
| 003 | Check eager; threads; alcance de `model_discovery`; offline replay | el retry se comía `EgressBlocked` |
| 004 | I13; el orden de commits 4↔5 | **por definir** |

La última fila es el punto del ejercicio. Si tu respuesta no la llena, no aportó.
