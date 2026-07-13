# RFC-006: Provider-Safe Routing para `ai-orchestrator`

**Proyecto:** `csantisdev/ai-orchestrator`
**Fecha:** 2026-07-09
**Supersede:** RFC-001 … RFC-005
**Destino:** rama `feat/egress-gate`. **No** merge directo a `production`.

---

## Estado de la evidencia

RFC-004 declaró "implementado y verificado" bajo el encabezado `csantisdev/ai-orchestrator@production`. Eso se lee como *está en producción*. **No lo está.** RFC-005 lo señaló; es correcto y es la corrección más útil de la serie.

Estado real, verificado el 2026-07-09:

```
origin/production           = 4ae94970516d26a69e934cdd480e1634384ff5f1
orchestrator/egress.py      NO existe en el remoto público
ramas remotas con "egress"  ninguna
```

Lo que sigue es un **patch contra ese SHA**, ejecutado en un entorno local efímero.

| Nivel | Estado |
|---|---|
| Diseño validado | sí |
| Implementación local ejecutada | sí (`egress-gate.patch`, +512/−28) |
| Rama pública verificable | **no** |
| CI reproducible | **no** |
| Feature desplegada | **no** |

**Nada de este documento debe citarse como evidencia hasta que la rama esté publicada.** Primera acción: `git push -u origin feat/egress-gate`.

---

## 0. Qué se pide

El código existe, cierra una fuga reproducible y pasa 15 tests de invariante. Este RFC **no pide validar la idea**.

Pide dos cosas:

1. **Atacar el experimento de §7.** Decide si el router externo se conserva o se borra. Ninguna cantidad de arquitectura lo responde.
2. **Encontrar la invariante que falta.** Quince no bastan. Cada ronda encontró lo que la anterior no vio; la tabla del Apéndice D tiene una fila vacía a propósito.

**No sirve:** reformular la tesis, citar prior art sin señalar una línea de código, proponer una capa nueva (§8).
**Sirve:** una ruta de fuga con archivo y línea; un ataque al diseño experimental; un contraejemplo ejecutable.

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

**Regla central: el router también es una salida de datos.**

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

RFC-002 decía *"Sin política, ninguna llamada sale."* Falso — `model_discovery` sale.

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

Un provider nuevo que copie el patrón viejo **falla al definirse**, no en producción.

El router queda cubierto sin caso especial: **el router es un provider**.

### 3.3 `complete_stream()` no puede ser generator function

```python
# MAL: el cuerpo se difiere al primer next(). El caller no ve EgressBlocked.
def complete_stream(self, prompt, system=""):
    egress.check(...)
    result = yield from self._complete_stream(prompt, system)

# BIEN: check eager, retorna el generator.
def complete_stream(self, prompt, system=""):
    egress.check(...)
    return self._complete_stream(prompt, system)
```

**No era una fuga.** `_complete_stream` también es lazy y `check()` corre primero en el cuerpo. Cero HTTP antes del gate, verificado. Era un defecto de API: `try: gen = p.complete_stream(...) except EgressBlocked:` nunca capturaba.

Lección incómoda: el test original (I3) usaba `list(...)`, que fuerza iteración. **Pasaba probando algo distinto de lo que su nombre decía.** I11 sella la propiedad real con `inspect.isgeneratorfunction()`.

### 3.4 `ContextVar` no propaga a threads

`background.py:45` lanza `threading.Thread`. `ContextVar` no se copia a un thread nuevo. Probado:

```
=== ¿ContextVar propaga a threading.Thread? ===
  worker: NO propagó -> EgressBlocked
```

Sin arreglo, **todo run en background moría**. Fix: `_set_worker_policy(ctx, config)` como primera sentencia del worker (I12).

### 3.5 Una denegación de política nunca es transitoria

Al arreglar 3.4 apareció esto en `background.py:145`:

```python
except Exception as exc:        # captura EgressBlocked
    _last_exc = exc
    retry con backoff exponencial
```

**Una denegación de política se reintentaba 3 veces como si fuera un timeout de API.** No filtra, pero es semánticamente falso, contamina logs y triplica la latencia del fallo.

```python
except EgressBlocked:
    raise          # nunca es transitoria
except Exception as exc:
    ...
```

Ningún RFC anterior lo vio. Apareció al implementar, no al diseñar (I13).

### 3.6 `check()` bloquea, `can_send()` consulta

- `check()` es la red de seguridad. Levanta. Nadie la puede olvidar.
- `can_send()` permite degradación elegante: el router elige otra ruta en vez de crashear.

### 3.7 Router local determinístico

Sin LLM, sin red, sin egress. Se usa cuando el router externo no tiene clearance, y como brazo de comparación en `router-eval --offline`.

```python
def decide_with_local_router(task, ctx, config) -> RoutingDecision:
    permitted = [p for p in PROVIDERS if egress.can_send(p)]
    if not permitted:
        raise EgressBlocked(f"Ningún proveedor pasa la política de egress para '{ctx.name}'.")

    # 1. keyword_hints del proyecto, por peso descendente
    for sig in sorted(_calculate_keyword_signals(task, ctx), key=lambda s: -s.get("weight", 1)):
        if sig.get("provider") in permitted:
            return RoutingDecision(provider=sig["provider"], used_fallback=True, ...)

    # 2. default del proyecto, si pasa política
    # 3. default global, si pasa política
    # 4. el permitido más barato, por precio de input del catálogo
```

**Nunca devuelve un proveedor bloqueado.** Si ninguno pasa, levanta.

### 3.8 El falso bloqueo que el test protegía

Al conectar 3.7 apareció:

```python
if not egress.can_send(fallback):
    raise EgressBlocked(...)   # abortaba aunque Claude estuviera permitido
```

Para `restricted-project` (restricted), el único proveedor permitido es Claude. Con `fallback: gemini` bloqueado, el sistema **abortaba teniendo una salida segura**.

Y peor: **el test I6 afirmaba que ese aborto era correcto.** Un test de seguridad protegiendo un bug de usabilidad.

Corregido: `decide_with_local_router()` es quien levanta, y solo cuando **ningún** proveedor pasa. I6 reformulado; **I14** es la regresión.

Este es el modo de fallo que mata productos de seguridad: bloquear de más hasta que el usuario desactiva el gate. Es una clase de bug, no un caso.

### 3.9 Higiene de secretos en el payload

`_contains_secrets()` **ya existía** (`rag.py:166`), usado solo al indexar. Se reutiliza en el borde:

```python
if payload and _has_secret(payload):
    policy = replace(policy, sensitivity="secret")   # ningún clearance la alcanza
```

No es taint semántico. Es higiene. **El log nunca guarda el payload** (ver §6.3).

### 3.10 Nivel desconocido = bloqueo

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

Con `conftest.py` estableciendo política explícita:

```
pytest tests/ -q              →  126 passed, 1 failed
pytest tests/test_egress.py   →   15 passed
```

El único fallo es `test_rag_index_and_retrieve`, pre-existente, requiere chromadb. **Cero regresiones.**

### 4.2 PoC (criterio bloqueante de RFC-004 §8.2, ahora cumplido)

```
ai-orchestrator                internal    → openai    (default del proyecto)
restricted-project.example   restricted  → claude    (único permitido)
secreto                        secret      → BLOQUEADO (ningún proveedor pasa)
```

Cero bytes a DeepSeek, ni como router ni como proveedor final.

### 4.3 Invariantes (`tests/test_egress.py`, 15 passed)

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
| I4′ | *(I9 lo reemplaza funcionalmente; I4 se conserva como red redundante)* | — |

---

## 5. Posicionamiento, corregido contra la competencia real

RFC-005 afirmó que LiteLLM *"no cubre explícitamente como núcleo: el router externo como sink gobernado"*. **Su propia cita lo desmiente:** el guardrail `sensitive_data_routing` corre en modo `pre_call`, **antes de la selección de modelo**. Eso *es* gatear el router.

Las diferencias reales son otras dos.

### 5.1 Detección vs declaración

LiteLLM detecta **contenido** sensible: `prebuilt_patterns` (`us_ssn`, `credit_card`, `email`), `regex_patterns`, `keywords` (`confidential`, `internal only`).

Un controller de Laravel de `restricted-project` no contiene SSN, ni tarjeta, ni la palabra "confidential". **LiteLLM lo enruta a la nube.**

Tu gate no mira el contenido. Declara sensibilidad **por proyecto**. La detección falla en silencio; la declaración no falla. Es la diferencia entre un clasificador y una política.

### 5.2 Reroute vs block

LiteLLM redirige a `on_premise_model` — explícitamente *sin* bloquear ni redactar; el prompt sale íntegro hacia otro destino, y con `sticky_session` la sesión queda fijada on-prem.

**Tú no tienes modelo on-prem.** Sin destino alternativo, redirigir no existe como opción. Bloquear es la única acción correcta, y ese guardrail no la ofrece.

### 5.3 Tesis, en una línea

> **Política declarativa por proyecto, fail-closed, aplicada antes de cualquier salida — incluida la del router.**

No "governed decision provenance". No "AI gateway". No "IFC original". Esas tres cosas ya existen y las hacen mejor.

### 5.4 Lo que NO se afirma

- IFC no es una técnica nueva (FIDES, CaMeL).
- Sensitive data routing no es original (LiteLLM, Cloudflare).
- Una regex no equivale a DLP.
- El router local no es mejor antes de medirlo (§7).
- SQLite no es un diferenciador.

---

## 6. Advertencia con fecha: telemetría de gobernanza

**LiteLLM, reporte de incidente del 18 de marzo de 2026.** El logging de guardrails exponía headers secretos en spend logs y trazas de OpenTelemetry: las respuestas de guardrail se escribían como atributos de span sin sanitizar. Credenciales en texto plano para cualquiera con acceso a los sistemas de observabilidad. La mitigación incluyó **rotar credenciales**.

RFC-005 propone, en su paso 15, *"export governance attributes via OpenTelemetry"*, y lista los atributos en su Apéndice C. Cita a LiteLLM como prior art y **no cita el incidente**.

### 6.1 La lección

> El sistema que registra las decisiones de seguridad es él mismo una superficie de egress.

Un guardrail que devuelve el payload completo para "trazabilidad" convierte el log en el vector.

### 6.2 Regla dura

```
El log de egress registra la DECISIÓN, nunca el PAYLOAD.
```

Campos permitidos: `project`, `provider`, `phase`, `decision`, `reason_code`, `sensitivity`, `clearance`, `ts`.
Campos prohibidos: prompt, system prompt, chunks RAG, headers, argumentos de tool, texto de la tarea.

### 6.3 Estado actual

`egress._log()` registra solo los campos permitidos. `reason` es texto generado por el sistema, no contenido del usuario. **Antes de exportar a OTel, esta propiedad debe tener un test**, no una convención.

### 6.4 Riesgo abierto

`reason` incluye el nombre del proyecto. En un log local es aceptable. En un exportador remoto, no. Si se implementa OTel: `reason_code` enumerado, no texto libre.

---

## 7. El experimento (esto es lo que hay que atacar)

### 7.1 El conflicto

```
ai-orchestrator                sens=internal    → router deepseek: BLOQUEADO
restricted-project.example   sens=restricted  → router deepseek: BLOQUEADO
```

**El gate mata el modelo de costos.** El router de dos capas existe para que un modelo barato (`$0.14/M`) decida el ruteo. Con `deepseek.clearance = public` y proyectos en `internal`, DeepSeek queda inhabilitado como router para **todos** los proyectos.

> El router debe ver el contexto para decidir bien.
> El contexto es lo que no queremos que vea.
> El router es barato precisamente porque es el proveedor de menor confianza.

### 7.2 Hipótesis: el conflicto puede no existir

Si `decide_with_local_router()` acierta tanto como DeepSeek, el router externo pasa de *activo a proteger* a **pasivo que cuesta plata y filtra contexto**. Se borra, y §7.1 desaparece.

### 7.3 Fase 1 — offline replay (sin red, sin costo, sin riesgo)

```bash
ai-orchestrator router-eval --offline --limit 500
```

Para cada run histórico: recalcular qué habría elegido el router local y comparar contra `runs.provider`.

**Instrumentación ya existente. No hay telemetría que construir:**

| Dato | Dónde | Estado |
|---|---|---|
| Proveedor elegido por el router LLM | `runs.provider` | existe |
| Razón del ruteo | `runs.routing_reason` | existe |
| Calidad, juzgada por humano | `runs.rating` ∈ `{useful, partial, wrong}` | existe (migración `add_rating_to_runs`) |
| Costo del router externo | `RoutingDecision.router_cost_usd` | existe (`router.py:67`) |

### 7.4 El límite del método

> **En las divergencias, la calidad del router local no es observable.**

Si el externo eligió Claude y el local habría elegido OpenAI, `rating` solo evalúa a Claude. El contrafactual no existe.

Consecuencia: el offline replay mide **acuerdo** y **costo**, no calidad en divergencia. Declarar esto evita concluir de más.

### 7.5 Fase 2 — canary

El router local decide de verdad, en un porcentaje de runs, solo en proyectos `internal`.

Asignación: hash determinístico de `run_id`, no aleatorio por sesión. Evita que el usuario aprenda a evitar el brazo que no le gusta.

### 7.6 Regla de decisión (declarada antes de mirar los datos)

```
Fase 1 (offline, N ≥ 200, solo proyectos internal):

  agreement_rate >= 0.80
      → pasar a canary. La divergencia es rara.

  agreement_rate < 0.80
      → inspeccionar divergencias a mano.
        Si el local elige sistemáticamente más barato sin peor rating
        en los runs donde coincide, pasar a canary igual.

Fase 2 (canary, 20% de runs internal):

  local_quality >= external_quality  (por rating)
      → borrar el router externo. Se ahorra SUM(router_cost_usd).

  external_quality > local_quality de forma material
      → conservar cascada. Recién ahí evaluar router metadata-only.
```

### 7.7 Errores a evitar

- **`agreement_rate` mide acuerdo, no calidad.** Dos routers pueden coincidir y equivocarse los dos. El árbitro es `rating`.
- **`cost_saved_by_local_router_usd` no es medible** sin contrafactual. Pero `SUM(router_cost_usd)` sí, y es exactamente lo que se ahorra al borrar el router externo. No inventar métricas cuando la real ya se escribe.
- **`rating` está sesgado:** solo se puntúan los runs que el usuario mira. Reportar `rating_coverage` junto a **toda** conclusión.
- **Solo proyectos `internal`.** En `restricted` el router externo está bloqueado y no hay contrafactual observable.

---

## 8. Fuera de alcance

memoria semántica · promotion gates · evidence lattice · memoria negativa · bandits · reward diferido · router metadata-only en producción · provider profiles por tier · taint tracking semántico · declassification humana · `decision_events` / `context_lineage` / `outcome_events` · exportación OTel · políticas enterprise / SOC 2 · multi-tenant

**Ninguno antes de 500 runs gobernados reales.** RFC-005 propuso tres tablas nuevas, OTel y canary mientras `decide_with_local_router()` seguía sin escribirse; su propio §17 advertía contra eso y dos tercios del documento lo hacían igual.

Prior art: FIDES (arXiv:2505.23643), CaMeL (arXiv:2503.18813), NeuroTaint (arXiv:2604.23374), RL Developer Memory (arXiv:2605.01567). **Ninguno ataca §7**, que es economía de ruteo, no seguridad.

---

## 9. Riesgos residuales

| Riesgo | Sev. | Estado |
|---|---|---|
| `model_discovery` fuera del gate | baja | clasificado, issue separado (§2.2) |
| Secreto no detectado por el regex | alta | mitigación parcial (I10). **El regex es una lista, no una prueba** |
| `except Exception: pass` en `cli.py:~237` (bloque RAG) | media | **abierto.** Hoy es disponibilidad. Con política adentro sería fail-open silencioso |
| Falso bloqueo → el usuario desactiva el gate | **alta** | I14 cubre un caso. La clase entera sigue abierta (§3.8) |
| `reason` filtra nombre de proyecto a un exportador | media | local hoy. Bloqueante para OTel (§6.4) |
| Post-filtro de `similar_runs` reduce recall | baja | aceptado; v2 con query scoped en el backend |
| Demasiados bloqueos elevan costo | media | es exactamente lo que mide §7 |

**Regla dura: el gate nunca dentro de un `try` sin `raise`.**

---

## 10. Orden de commits

```
 1. docs: add RFC-006 and correct implementation status
 2. feat: add fail-closed egress policy                       (egress.py; I1 I2 I7)
 3. refactor: seal provider boundary via template methods      (I3 I4 I9 I11)
 4. feat: add project sensitivity and provider clearance
 5. feat: add local deterministic router                       ← antes del 6
 6. fix: prevent router egress before policy evaluation        (I5 I6 I14)
 7. fix: restrict router similar-runs to current project       (I8)
 8. feat: escalate effective sensitivity on secret in payload  (I10)
 9. fix: set egress policy inside background worker thread     (I12)
10. fix: never retry a policy denial as a transient failure    (I13)
11. feat: egress_decisions logging (decision only, never payload)
12. feat: router-eval --offline
```

**El 5 va antes del 6:** el fix del router invoca al router local. RFC-003 y RFC-005 lo tenían al revés; el 6 no compila sin el 5.

**El 3 hace trivial al 6.** Al revés, el 6 parchea un agujero y deja cuatro rutas de streaming abiertas.

No implementar nada más allá del 12 hasta tener 500 runs.

---

## 11. Criterios de merge

### 11.1 A rama remota — **bloqueante, no cumplido**

- [ ] `git push -u origin feat/egress-gate`
- [ ] SHA del commit registrado en este RFC
- [ ] `orchestrator/egress.py` presente en el remoto
- [ ] `tests/test_egress.py` presente en el remoto
- [ ] Log de `pytest` adjunto o CI visible

### 11.2 A `production`

- [x] `pytest tests/ -q` → 126 passed, 1 failed (pre-existente)
- [x] `pytest tests/test_egress.py -q` → 15 passed
- [x] Borde sellado (`__init_subclass__`)
- [x] Streaming no bypassea, y el check es eager
- [x] Worker fija su propia política dentro del thread
- [x] Denegación de política no se reintenta
- [x] `similar_runs` scoped por proyecto
- [x] Router externo bloqueado usa router local determinístico
- [x] No hay fallback inseguro **ni falso bloqueo** (I6 + I14)
- [x] PoC `restricted-project`: cero bytes a DeepSeek
- [ ] `egress_decisions` con test que verifique **ausencia de payload**
- [ ] Alcance de `model_discovery` documentado en el repo
- [ ] Estado de este RFC coincide con el estado real del remoto

### 11.3 Para afirmar valor de producto

- [ ] ≥ 500 runs gobernados
- [ ] ≥ 1 bloqueo real reproducible
- [ ] `router-eval --offline` sobre ≥ 200 runs, o reporte de muestra insuficiente
- [ ] `rating_coverage` reportado junto a toda conclusión de calidad
- [ ] Costo comparado por modo de router

---

## 12. Formato de respuesta pedido

1. **Ruta de fuga que los 15 tests no cubren.** Una, con archivo y línea. Si no encuentras ninguna, dilo — es una respuesta válida y más útil que inventar una.
2. **Ataque al experimento (§7).** ¿La regla de §7.6 es tramposa? ¿`rating` sirve como ground truth con cobertura baja? ¿El hash de `run_id` basta contra el sesgo de selección?
3. **Ataque a I1–I14.** ¿Cuál es falsa o insuficiente? En particular: I10 depende de un regex; **¿qué secreto real lo evade?**
4. **Ataque a §3.8.** El falso bloqueo es una clase, no un caso. ¿Dónde está el siguiente?
5. **Lo que quitarías.** +512 líneas, 180 de tests. ¿Cuántas sobran?
6. **Veredicto:** mergear a rama, iterar, o revertir.

No suavices.

---

## Apéndice A — Aplicar

```bash
git checkout -b feat/egress-gate
git apply egress-gate.patch
pytest tests/ -q                  # 126 passed, 1 failed (RAG, pre-existente)
pytest tests/test_egress.py -q    # 15 passed
git push -u origin feat/egress-gate    # ← sin esto, nada de lo anterior es verificable
```

## Apéndice B — Primera métrica viva

No es inteligencia. Es:

```
router_egress_blocked_total        > 0
fallback_inseguro                  = 0
falso_bloqueo_reportado            = 0
bytes_a_deepseek_en_restricted_project    = 0
```

Si tras una semana `router_egress_blocked_total = 0`: o no hay proyectos sensibles, o la política no se carga, o el gate no corre, o los clearances son demasiado permisivos, o el flujo real no pasa por `ai-orchestrator`. Las cinco merecen inspección.

Si `falso_bloqueo_reportado > 0`, es más urgente que cualquier otra métrica: es el número que precede a que desactives el gate.

## Apéndice C — Config mínima

```yaml
# config.yaml
providers:
  deepseek:  { clearance: public,     model: deepseek-v4-flash }
  gemini:    { clearance: public,     model: gemini-2.5-flash }
  openai:    { clearance: internal,   model: gpt-4o }
  claude:    { clearance: restricted, model: claude-sonnet-4-6 }

router:
  provider: deepseek
  fallback_provider: claude
```

```yaml
# restricted-project/.orchestrator/context.yaml
name: restricted-project.example
sensitivity: restricted
blocked_providers: [deepseek, gemini]
```

**Defaults:** `DEFAULT_SENSITIVITY = "internal"`, `DEFAULT_CLEARANCE = "internal"`. Preservan el comportamiento actual. Se opta por restringir, no por permitir. Poner `deepseek.clearance: public` sin esos defaults bloquea todo run el primer día, y el gate se desactiva en cinco minutos.

## Apéndice D — Qué aprendió cada ronda

| RFC | Aportó | Lo que no vio |
|---|---|---|
| 001 | El bug; `ContextVar` sin default; borde en `BaseProvider` | I3 pasaba probando otra cosa |
| 002 | `__init_subclass__`; escalación por secreto | streaming diferido; threads |
| 003 | Check eager; threads; alcance de `model_discovery`; offline replay | el retry se comía `EgressBlocked` |
| 004 | I13; orden de commits 5↔6 | mezcló evidencia local con estado remoto |
| 005 | **La corrección epistémica**; separar diseño de implementación verificable | subestimó LiteLLM leyendo mal su cita; propuso OTel ignorando el incidente; scope creep con 0 runs |
| 006 | I14 y el falso bloqueo; detección vs declaración; el incidente de LiteLLM | **por definir** |

La última fila es el punto del ejercicio. Si tu respuesta no la llena, no aportó.

---

## Apéndice E — Referencias

Verificadas contra la fuente:

1. Costa et al. *Securing AI Agents with Information-Flow Control (FIDES)*. arXiv:2505.23643
2. Debenedetti et al. *Defeating Prompt Injections by Design (CaMeL)*. arXiv:2503.18813
3. Cai et al. *Ghost in the Agent: Redefining Information Flow Tracking for LLM Agents (NeuroTaint)*. arXiv:2604.23374
4. Iscan. *Feedback-Normalized Developer Memory for RL Coding Agents*. arXiv:2605.01567
5. LiteLLM. *Sensitive Data Routing (Built-in Guardrail)*. docs.litellm.ai
6. LiteLLM. *Incident Report: Guardrail logging exposed secret headers in spend logs and traces*. 2026-03-18

**No verificadas** — RFC-005 las cita; no las comprobé. No usar como respaldo hasta hacerlo:

- arXiv:2601.20727 (*Audit Trails for Accountability*)
- arXiv:2604.05119 (*Governance-Aware Agent Telemetry*)
- arXiv:2505.17716 (*AgentRR*)
