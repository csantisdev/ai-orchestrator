# RFC: Egress Gate para ai-orchestrator

**Estado:** prototipo implementado y verificado contra el repo real (`csantisdev/ai-orchestrator`, rama `production`, HEAD 2026-07-08).
**Propósito de este documento:** revisión adversarial multi-agente sobre un **conflicto de diseño no resuelto**, no sobre una propuesta abstracta.

Todo lo que sigue está medido, no argumentado. El código está en `egress-gate.patch`.

---

## 0. Instrucciones para el revisor

Este RFC **no** pide validación de la idea. La idea ya está implementada y pasa los tests. Pide resolver el conflicto de la §4, que apareció al ejecutar el código y que ninguna ronda de diseño previa anticipó.

Lo que **no** sirve como respuesta:
- Reformular la tesis con mejor vocabulario.
- Citar prior art sin decir qué cambia en el código.
- Proponer una capa adicional (memoria, grafo, bandit). Están fuera de alcance.

Lo que **sí** sirve:
- Una respuesta a §4 con su costo estimado y su modo de fallo.
- Un ataque a las invariantes de §3 que muestre una ruta de fuga que los tests no cubren.
- Un contraejemplo ejecutable.

Formato pedido: ver §7.

---

## 1. El bug (reproducido, no hipotético)

`orchestrator/router.py` implementa un router de dos capas: un modelo barato decide qué proveedor resuelve la tarea. Por defecto (`config.example.yaml:27`) ese router es **DeepSeek**.

El problema: el router recibe el contexto **antes** de que exista una decisión de proveedor. La política "este proyecto no usa free-tier" se evalúa después de que el dato ya salió.

Reproducción sin red, contra el código real:

```
$ python repro.py
Proyecto: restricted-project.example
Stack: PHP/Laravel 12 + MySQL
Descripción: Sistema interno con datos regulados de terceros.
Convenciones: Repository pattern, No exponer identificadores personales en logs
Notas de ruteo del proyecto: Proyecto sensible: no usar proveedores free-tier.

Decisiones de ruteo previas en tareas similares:
- [restricted-project.example] → claude: "lógica de negocio sensible" [ÚTIL]
- [public-project-beta] → deepseek: "CRUD simple de recursos públicos"

Tarea a resolver:
"""Revisa el endpoint POST /resources/{id}/approve, filtra por identificador personal..."""

======================================================================
BYTES ENVIADOS AL ROUTER (deepseek por default): 752
  contiene 'restricted-project.example': True
  contiene 'identificador personal':                          True
  contiene 'approve':                      True
  contiene 'public-project-beta':               True
  contiene 'sensible':                     True
```

Dos hallazgos:

**1.1 — Pre-routing egress.** El prompt enviado a DeepSeek contiene literalmente la política que prohíbe enviarlo a DeepSeek.

**1.2 — Fuga cross-project.** `_fetch_similar_runs(task, n=3)` (router.py:124) consulta el backend de similitud **global**. Ni el protocolo `SimilarityBackend.query(text, n_results)` ni el fallback FTS5 aceptan `project`. Una tarea del proyecto A envía al router externo los nombres y razones de ruteo del proyecto B. Independiente de sensibilidad: ocurre siempre.

Severidad: **alta**. Vector: llamada al router. Alcance: nombre de proyecto, stack, descripción, convenciones, notas de ruteo, texto de la tarea, contexto activo, runs similares de otros proyectos. Trigger: cualquier run con router externo (default).

---

## 2. La corrección implementada

Cuatro cambios. `+332 / −28` líneas, 11 archivos.

### 2.1 Fail-closed por construcción, no por disciplina

La política **no es un parámetro**. Un parámetro con default es lo que se te olvida pasar en el quinto call site.

```python
_POLICY: ContextVar[EgressPolicy] = ContextVar("egress_policy")   # sin default

def current_policy() -> EgressPolicy:
    try:
        return _POLICY.get()
    except LookupError as exc:
        raise EgressBlocked("Sin política activa, no sale nada.") from exc
```

No se puede olvidar pasarlo. Solo se puede olvidar *establecerlo*, y entonces nada sale.

### 2.2 El borde, no el call site

`BaseProvider.complete()` y `complete_stream()` pasan de abstractos a **template methods concretos** que llaman al gate. Los cuatro providers renombran a `_complete()` / `_complete_stream()`.

Esto importa porque los cuatro providers implementaban `complete_stream()` **directamente** con `httpx.stream(...)`. Un gate solo en `complete()` habría dejado cuatro rutas de streaming abiertas, y `background.py:131` usa exactamente esa ruta.

El router queda cubierto sin caso especial: **el router es un provider**.

### 2.3 `check()` bloquea, `can_send()` consulta

Dos funciones, un lugar de decisión.

- `check()` es la red de seguridad. Levanta. Nadie la puede olvidar.
- `can_send()` permite degradación elegante: el router elige otra ruta en vez de crashear.

Nunca hay fallback a un proveedor que tampoco pasa política. Eso sería el mismo bug con otro nombre.

### 2.4 Nivel desconocido = bloqueo

`sensitivity: confidencial` (typo, no está en el lattice) levanta `EgressBlocked`. Un error tipográfico en política de seguridad no debe degradar a permisivo.

---

## 3. Resultados medidos

### 3.1 El gate auditó la suite existente

Baseline antes del patch: `111 passed, 1 failed` (fallo pre-existente de RAG, requiere chromadb).

Inmediatamente después de instalar el gate, **sin** conftest:

```
22 failed, 90 passed
```

Los 22 fallos son el mismo error:

```
EgressBlocked: No hay política de egress activa.
```

**21 tests alcanzaban un proveedor externo y ninguno declaraba política.** El gate no rompió los tests: los usó para enumerar las rutas de egress. Ese número es el hallazgo, no el daño.

Con `conftest.py` estableciendo política explícita: `119 passed, 1 failed` (el mismo fallo de RAG). **Cero regresiones.**

### 3.2 Invariantes verificadas (`tests/test_egress.py`, 8 passed)

| # | Invariante | Verifica |
|---|---|---|
| I1 | Sin política, ninguna llamada sale | `LookupError → EgressBlocked` |
| I2 | Proyecto `restricted` no llega a proveedor `public` | comparación de clearance |
| I3 | **Streaming no puede bypassear el gate** | `_complete_stream` nunca se invoca |
| I4 | Ningún provider sobreescribe el borde | inspección de fuente; sobrevive a un 5º provider en 2027 |
| I5 | Router degrada, no filtra | `used_fallback=True`, razón explícita |
| I6 | No hay fallback inseguro | `EgressBlocked` si router **y** fallback están bloqueados |
| I7 | Typo en política falla cerrado | `sensitivity: confidencial` → bloqueo |
| I8 | `similar_runs` no cruza proyectos | firma cambiada a `(task, project, n)` |

---

## 4. El conflicto no resuelto (esto es lo que hay que atacar)

Al ejecutar el PoC end-to-end apareció esto:

```
ai-orchestrator                sens=internal    → router deepseek: BLOQUEADO
                               → degradó a 'claude'
restricted-project.example   sens=restricted  → router deepseek: BLOQUEADO
                               → degradó a 'claude'
```

**El gate destruye el modelo de costos.**

El router de dos capas existe para que un modelo barato (`$0.14/M tokens`) decida el ruteo. Si `deepseek.clearance = public` y el default de proyecto es `internal`, DeepSeek queda inhabilitado como router **para todos los proyectos**, no solo los sensibles. Cada run paga Claude para decidir a quién llamar. El ahorro que justifica el orquestador desaparece.

La tensión es estructural:

> El router debe ver el contexto para decidir bien.
> El contexto es lo que no queremos que vea.
> El router es barato precisamente porque es el proveedor de menor confianza.

Tres salidas, ninguna obviamente correcta:

**(a) Clearance por tier, no por proveedor.** `deepseek_free: public`, `deepseek_paid: internal`. Reconoce que el riesgo está en los términos de retención, no en la marca. Costo: reescribir el registry de proveedores; el nombre deja de ser la clave.

**(b) Rutear sobre metadata, no sobre contenido.** El router recibe solo `task_class`, `keyword_signals` y longitud — nunca el texto de la tarea ni el contexto del proyecto. Desacopla costo de sensibilidad. Costo: la calidad del ruteo cae, y no sabemos cuánto. Requiere medirlo.

**(c) Router local.** Sin LLM. `_calculate_keyword_signals()` ya existe (router.py:71) pero hoy solo alimenta el prompt; nunca decide por sí solo. Costo: peor ruteo, cero egress, cero costo de router.

**Nota sobre (b):** es la más interesante y la menos probada. Convierte el ruteo en un problema de clasificación sobre features no sensibles. Si funciona, resuelve el conflicto sin comprometer ni costo ni seguridad. Si no funciona, hay que saber por qué antes de descartarla.

**Pregunta al revisor:** elige una, o propone (d). Justifica con un modo de fallo concreto y un costo estimado, no con una preferencia arquitectónica.

---

## 5. Trampa de migración (documentada porque ya nos mordió)

Poner `deepseek.clearance: public` en `config.example.yaml` bloquea **todo run el primer día**. El usuario desactiva el gate en cinco minutos y el trabajo se pierde.

Defaults elegidos: `DEFAULT_SENSITIVITY = "internal"`, `DEFAULT_CLEARANCE = "internal"`. El comportamiento actual se preserva. Se opta por restringir, no por permitir:

```yaml
# .orchestrator/context.yaml
sensitivity: restricted
blocked_providers: [deepseek, gemini]

# config.yaml
providers:
  deepseek:
    clearance: public
```

Dos líneas. Un proyecto se rompe — el que debía romperse. **Pero ver §4: con esta config el router muere.**

---

## 6. Fuera de alcance (deliberadamente)

No se implementa, y no se quiere discutir en esta ronda:

- Memoria semántica, promotion gates, evidence lattice, memoria negativa
- Bandits, routing aprendido, recompensa diferida
- Redacción de secretos en el borde (`_is_sensitive_file()` existe en `rag.py:158` pero solo filtra indexación)
- Propagación de sensibilidad por grafo de derivación
- Taint tracking semántico

Todo eso tiene prior art sólido (FIDES arXiv:2505.23643, NeuroTaint arXiv:2604.23374, RL Developer Memory arXiv:2605.01567) y **ninguno de esos papers ataca §4**, que es un problema de economía de routing, no de seguridad.

Riesgo conocido: `cli.py:~237` envuelve el bloque RAG en `except Exception: pass`. Hoy es disponibilidad. Si alguien mete política ahí adentro, se vuelve fail-open silencioso. **El gate nunca dentro de un `try` sin `raise`.**

---

## 7. Formato de respuesta pedido

1. **Ruta de fuga que los tests no cubren.** Una, concreta, con el archivo y la línea. Si no encuentras ninguna, dilo.
2. **Resolución de §4.** Elige (a), (b), (c) o propone (d). Con costo y modo de fallo.
3. **Ataque a I1–I8.** ¿Cuál invariante es falsa o insuficiente?
4. **Lo que quitarías.** Este patch son 332 líneas. ¿Cuántas sobran?
5. **Veredicto:** mergear, iterar, o revertir.

No suavices. Si `ContextVar` es la decisión equivocada (threads, asyncio, tests), dilo en el punto 3 y desarróllalo.

---

## Apéndice: aplicar

```bash
git checkout -b feat/egress-gate
git apply egress-gate.patch
pytest tests/ -q          # esperado: 119 passed, 1 failed (RAG, pre-existente)
pytest tests/test_egress.py -q   # esperado: 8 passed
```

Orden de commits sugerido:

```
1. feat: add fail-closed egress policy (egress.py + tests)
2. refactor: enforce egress gate via provider template methods
3. fix: router leaks task context before policy evaluation
4. fix: restrict router similar-runs to current project
```

El 2 hace que el 3 sea trivial. Al revés, el 3 parchea un agujero y deja cuatro.
