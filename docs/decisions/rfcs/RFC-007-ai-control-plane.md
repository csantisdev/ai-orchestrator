# RFC-007 — Local AI Control Plane: Plan de Implementación Definitivo

**Estado:** Draft para ejecución (Codex)
**Versión:** 0.9 (revisión 3)
**Fecha:** 2026-07-13
**Baseline de código auditado:** `4ae94970516d26a69e934cdd480e1634384ff5f1` — todas las citas de archivo:línea de la Parte II están verificadas contra este commit, y el código de `orchestrator/`, `tests/`, `pyproject.toml` y `.github/` no cambió desde entonces (verificado: cero diffs en esos paths entre `4ae9497` y `production` hoy).
**Fuente documental:** este archivo, tal como está en `production` (`git log -1 -- docs/decisions/rfcs/RFC-007-ai-control-plane.md` da el commit exacto — no se fija un SHA fijo acá adentro, porque editar esta misma línea generaría un SHA nuevo cada vez).
**Rama de implementación:** `feat/egress-gate`, creada desde `production`. Todo el código va acá, nunca directo a `production` (RFC-006 §0). Sin commits propios ni upstream remoto todavía — el primer push y el Draft PR se abren junto con el Commit 0.1 (ver §11.0, corrige un defecto de diseño real: sin un PR abierto, los pushes a esta rama no disparan el workflow de CI que crea ese mismo commit).
**Relación con la serie:** sucede a RFC-007 v0.3. No cubre MCP — eso es RFC-008 v0.1. **Incorpora el hallazgo de la serie RFC-001…006** (`archive/RFC-001-egress-gate.md`, `archive/RFC-002…005-*.md`, `rfcs/RFC-006-provider-safe-routing.md`), aportada por el usuario después de la primera redacción de este documento — ver Changelog. **Incorpora además tres pasadas de verificación de Codex** (solo lectura, contra este mismo checkout) que encontraron desajustes materiales, preguntas bloqueantes, un error aritmético propio y un defecto de diseño en el flujo de CI/PR — todo resuelto en esta revisión, ver Changelog.
**Destinatario de ejecución:** extensión Codex de VS Code, commit por commit, en el orden de la Parte II. **"Commit N.M" = un commit dentro de `feat/egress-gate`, no un Pull Request de GitHub** — hay un único PR real (Draft, abierto tras el Commit 0.1). Ver §11.0.

---

## Changelog

### v0.3 → v0.9 (revisión 1, primera redacción de este documento)

Convirtió el roadmap de 6 fases de v0.3 en un plan ejecutable commit-por-commit, verificado contra código real. En ese momento **RFC-006 no era accesible**: la Parte II de la revisión 1 diseñaba un `EgressPolicy`/`gateway.governed_complete()` propio, sin saber que ya existía un diseño distinto, más maduro y validado localmente (15 tests, patch +512/−28) en la serie RFC-001…006.

### v0.9 revisión 1 → v0.9 revisión 2

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
| Orden de commits | PRs agrupados por fase de alto nivel | **Mapeado contra el orden de commits de RFC-006 §10**: Fase 0 (3 commits, incluye el commit #7/I8 adelantado por ser independiente) + Fase 1 (10 commits, mapeados 1:1 contra los commits #2-#6 y #8-#12 de RFC-006 §10 -- sin duplicar el #1 (documental) ni el #7 (I8, adelantado a Fase 0)), ya probado localmente en ese orden exacto (`git apply egress-gate.patch` → `126 passed, 1 failed` pre-existente de RAG) |

**Lección para este documento y para cualquier sesión futura:** antes de diseñar una implementación "definitiva", preguntar explícitamente si existe una ronda de diseño previa no commiteada. La serie RFC-001…006 vivía en el disco del usuario, fuera de este repo hasta este momento, y el documento anterior (rev. 1) hizo trabajo redundante — y en algunos puntos (el choque de diseño del punto de sellado) peor — por no saberlo.

### v0.9 revisión 2 → v0.9 revisión 3 (esta versión)

Codex ejecutó una pasada de verificación de solo lectura (sin escribir código) contra `production@4ae9497`, pidiéndole confirmar cada cita de archivo:línea de la Parte II y las 14 invariantes del Apéndice A. Encontró:

- **5 desajustes materiales** en el texto: Commit 1.2 usaba `CompletionResult.to_stream_result()`, que no existe (ahora el commit lo agrega explícitamente); Commit 1.4 pedía precio numérico de `catalog.get_model_profiles()`, que no lo expone (corregido a `get_effective_pricing()`); Commit 1.6 daba un ejemplo de secreto (`API_KEY=...`) que el regex real no reconoce (corregido); Commit 0.3 subcontaba los caminos reales de `decide_provider()` (4 → 6, con enum explícito); la Invariante I10 sobreafirmaba detección universal de secretos (acotada a "patrón reconocido").
- **12 preguntas bloqueantes**, todas resueltas en esta revisión: estrategia de rama (docs a `production`, código a `feat/egress-gate`), extra de CI (`.[all]`), diseño del filtro de Commit 0.2 (sobre-consulta + post-filtro, no filtro nativo), ciclo de vida de la política en tests (`Token` + marker `no_default_policy`), función canónica `policy_for_project()` compartida entre Commit 1.3 y Commit 1.7, elección del provider más barato (API real de pricing), alcance real de I10, resolución fail-closed refinada para `ctx=None` en el worker (distingue proyecto nuevo de `context.yaml` corrupto), y alcance del log de `egress_decisions` (allowed+blocked, logueado solo desde `check()`).
- **1 invariante nueva, I15** (política se limpia por operación, no se filtra entre threads/tests) — la fila que RFC-006 dejó vacía a propósito.
- **7 mejoras no bloqueantes**, adoptadas: separar `except EgressBlocked` de `except Exception` explícitamente en Commit 1.5 sin leakear `str(exc)`, cubrir ambos momentos de excepción en un generador (Commit 1.8), no loguear desde `can_send()` (Commit 1.9), entre otras.

Nada de esto cambia el diseño de fondo de RFC-006 — son correcciones de precisión sobre cómo ese diseño se reconstruye contra el código real, encontradas por tener a alguien más leyendo el mismo código con otros ojos antes de ejecutar.

**Segunda pasada de Codex (sobre Commit 0.1 y el estado de git):** el prompt de Commit 0.1 seguía dejando una decisión sin resolver ("preguntá antes de decidir un mecanismo") — un prompt "ya resuelto" no puede delegar una decisión al ejecutor. Se verificó empíricamente (`.venv` de este checkout, `pytest tests/ -v`) en vez de asumir: **`112 passed, 0 failed`**, sin ningún fallo que aislar. Commit 0.1 quedó corregido a exigir 100% verde sin excepciones — no hizo falta ningún mecanismo de `--deselect`/`continue-on-error`, la pregunta desapareció al verificar el hecho en vez de discutir el mecanismo.

**Tercera pasada de Codex (aritmética `112` vs `126`):** la primera explicación que este documento daba de la diferencia (revisión 3 original: "la suite evolucionó, ADR-002 agregó tests") **era falsa** — verificado con `git merge-base --is-ancestor`: `tests/test_validate_pricing_catalog.py` ya existía en el commit `42f02cc`, que es ancestro de `4ae9497`, el mismo baseline que audita RFC-006. No hubo ningún test agregado entre RFC-006 y hoy. La explicación correcta, con la aritmética exacta de RFC-006 §4.1 (`111 passed, 1 failed` antes del patch efímero; `126 passed, 1 failed` después de agregar los 15 tests de `test_egress.py` del patch): **`112` = `111+1` = exactamente la misma cuenta total que el baseline pre-patch de RFC-006, con la única diferencia de que el test de RAG ahora pasa en vez de fallar** (chromadb disponible). El `126/1` de RFC-006 no es un baseline comparable con el checkout actual — es evidencia histórica de un patch efímero que incluía 15 tests (`test_egress.py`) que **todavía no existen** en este repo. Se corrigió la redacción en §11.1 Commit 0.1, Apéndice D y la Conclusión para no mezclar ambos números como si fueran la misma medición.

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

Fase 0 tiene 3 commits (incluye el commit #7/I8 de RFC-006 adelantado por ser independiente del resto del gate) y Fase 1 tiene 10 commits, cada uno mapeado **1:1** contra los commits **#2-#6 y #8-#12** de RFC-006 §10 — **excepto el #7**, ejecutado antes como Commit 0.2 (el #1 es documental, no genera commit propio; reproducidos aquí con archivos y líneas reales de `production@4ae9497`, que RFC-006 no tenía porque trabajaba sobre un patch efímero, no sobre este checkout). Ejecutar en orden — cada commit asume que todos los anteriores están **aplicados y verificados** (no "mergeados": es una sola rama, no hay merges intermedios). El orden importa por una razón concreta y ya verificada: el commit que corrige el router (Fase 1, Commit 1.5) invoca al router local (Commit 1.4); si se invierte, no compila.

**Modelo de ramas (decisión explícita, no asumir):** "Commit N.M" en este documento significa **un commit dentro de `feat/egress-gate`**, no un Pull Request de GitHub. Los 13 commits de Fase 0+1 se implementan secuencialmente en la misma rama — mismo patrón que usó RFC-006 con su patch efímero (un solo `git apply`, no 13 ramas). Hay un **único PR de GitHub real**, en modo Draft.

**Flujo exacto** (corrige un defecto real: el workflow de CI que crea el Commit 0.1 solo dispara en `push` a `production` o en `pull_request` — un `push` a `feat/egress-gate` sin PR abierto no ejecuta nada, y entonces los 12 commits siguientes avanzarían sin que CI los valide nunca):

```text
Commit 0.1 (crea .github/workflows/tests.yml)
    ↓
git push -u origin feat/egress-gate
    ↓
gh pr create --draft --base production --head feat/egress-gate
    ↓                                    (dispara CI por primera vez, vía pull_request)
Commits 0.2 … 1.10, un push por commit
    ↓                                    (cada push re-dispara CI vía pull_request synchronize)
CI verde en cada uno — si no, parar y arreglar antes de seguir
    ↓
`gh pr ready` (saca el Draft) cuando Fase 1 esté completa
```

La revisión incremental durante el desarrollo se hace por commit (`git log`, `git diff <commit>~1..<commit>`) dentro de ese único PR — no se abren ni cierran 13 PRs.

**Checklist de cierre por commit** (ninguno de los 13 se considera terminado solo porque compila):

```text
diff acotado al alcance declarado del commit
+ test nuevo que demuestra la propiedad que el commit agrega
+ pytest tests/ -v verde en local
+ CI verde en el Draft PR (push ya hecho, no solo "debería pasar")
+ invariante(s) de la Parte I trazada(s) explícitamente (¿cuál I1-I15 cubre?)
+ sin cambios fuera del alcance declarado en "Archivos:" del commit
```

Suite de tests: `pytest tests/`. Bajo el gate, sin política declarada, ~21 tests existentes van a fallar con `EgressBlocked: Sin política activa` — RFC-006 §4.1 documenta que **eso es el hallazgo, no el daño**: enumera cada ruta de egress no gobernada de la suite actual. Se agrega un `conftest.py` que fija una política permisiva por defecto para no bloquear la suite existente (Commit 1.1).

### 11.1 Fase 0 — Publicar y detener el decaimiento (bloqueante)

#### Commit 0.1 — CI que corre la suite completa

*Archivos:* nuevo `.github/workflows/tests.yml`. (Hoy solo existe `pricing-catalog.yml`, acotado a paths de pricing — no hay CI genérico corriendo `pytest`.)

*Baseline real, verificado empíricamente (no asumido) el 2026-07-13 contra `.venv` de este mismo checkout:*

```
./.venv/Scripts/python.exe -m pytest tests/ -v
112 passed in 5.79s
```

**Explicación correcta del `112` vs el `126/1` de RFC-006 §4.1 (dos dimensiones distintas, no confundir):**

- El `126 passed, 1 failed` de RFC-006 **no es un baseline pre-gate comparable con este checkout** — es el resultado de aplicar el patch efímero completo, que agregaba `tests/test_egress.py` (15 tests nuevos, todos passing). RFC-006 §4.1 da la aritmética exacta: `111 passed, 1 failed` **antes** del patch, `126 passed, 1 failed` **después** de sumar los 15 tests del gate (`111 + 15 = 126`). Ese patch nunca se mergeó — `test_egress.py` no existe en este repo todavía (lo crea Commit 1.1).
- El baseline pre-gate comparable es el `111 passed, 1 failed` (112 tests totales) que RFC-006 mismo documenta. **Verificado: coincide exactamente en cantidad con los `112 passed, 0 failed` de este checkout** (confirmado además que ningún test se agregó entre `4ae9497` y hoy: `tests/test_validate_pricing_catalog.py`, el único candidato a "test nuevo" que se había mencionado en una versión anterior de este párrafo, ya existía en el commit `42f02cc`, ancestro de `4ae9497` — esa explicación previa era incorrecta y quedó corregida).
- La única diferencia real entre ambas mediciones: el test de RAG, que fallaba en el baseline de RFC-006, pasa en este `.venv`. Es **consistente con que el entorno de RFC-006 no tenía `chromadb` instalado** — este `.venv` sí (`chromadb==1.5.9`) — pero esto es una inferencia razonable, no un hecho demostrado: no se conservó el traceback original, el `pip freeze`, ni el patch descartado para confirmar la causa exacta.

No hay ningún fallo pre-existente que aceptar hoy: **criterio de éxito de CI es 100% verde, sin excepciones, sin `--deselect`, sin `continue-on-error`.** Si algún test falla en el entorno limpio de CI (que puede diferir de este `.venv` local — ver tabla más abajo), es una regresión real a investigar, no algo a tolerar en este commit.

*Diferencias conocidas entre este `.venv` local y el CI propuesto (no bloquean el commit, pero explican por qué el resultado de CI podría diferir):*

| Dimensión | Local verificado | CI propuesto |
|---|---|---|
| OS | Windows | Ubuntu (`actions/setup-python`) |
| Python | 3.13.0 | 3.12 |
| chromadb | 1.5.9 (rango abierto `>=0.4.0` en `pyproject.toml`) | versión que resuelva pip en ese momento |
| pytest | 9.1.1 (rango abierto `>=8.0.0`) | versión que resuelva pip en ese momento |

El job debe imprimir `python --version` y `pip freeze` antes de correr la suite — no hace falta guardarlo como artefacto separado, con que quede en el log del job alcanza para diagnosticar una futura discrepancia entre este `.venv` y CI.

*Prompt Codex:*
```
Crea .github/workflows/tests.yml: se dispara en push a production y en todo
pull_request, instala Python 3.12 y el extra "all" del proyecto (pip install
-e ".[all]" -- revisa pyproject.toml para confirmar el nombre exacto del
extra; "all" incluye chromadb). Antes de correr los tests, agrega un step
que imprima `python --version` y `pip freeze` en el log (sin guardarlo como
artefacto aparte, alcanza con que quede en el log del job). Después corre
`pytest tests/ -v`.

Verificado el 2026-07-13 contra el .venv de este mismo checkout: la suite
completa da 112 passed, 0 failed con chromadb instalado -- NO hay ningún
test que deba tratarse como fallo conocido/aceptado. El "126 passed, 1
failed" de RFC-006 §4.1 NO es comparable con este número -- son mediciones
de dos cosas distintas: RFC-006 midió 111 passed + 1 failed ANTES de su
patch efímero, y 126 passed + 1 failed DESPUÉS de agregarle 15 tests nuevos
(tests/test_egress.py, que todavía no existe en este repo -- lo crea un commit
posterior). El baseline pre-gate real de RFC-006 (111+1=112) coincide en
cantidad exacta con los 112 tests de hoy; la única diferencia es que el test
de RAG ahora pasa (probablemente porque este entorno sí tiene chromadb
instalado, a diferencia del de RFC-006). Si en el entorno de CI (que puede
diferir del .venv local en versión de Python, SO, etc. -- ver la tabla de
diferencias conocidas más arriba en este documento) algún test falla, es
una regresión real que hay que investigar y resolver -- NO lo excluyas con
--deselect, NO lo marques xfail, NO seas tolerante con ningún fallo. El
criterio de este job es 100% verde, sin excepciones.

No toques .github/workflows/pricing-catalog.yml.
```

*Después de que Codex termine este commit (paso manual, no es tarea de Codex — es git/GitHub):*
```bash
git add .github/workflows/tests.yml
git commit -m "feat(ci): agregar workflow de tests para feat/egress-gate"
git push -u origin feat/egress-gate
gh pr create --draft --base production --head feat/egress-gate \
  --title "Egress gate: reconstrucción de RFC-006 contra production" \
  --body "Draft — 13 commits (Fase 0 + Fase 1 de RFC-007 §11). Se abre temprano para que CI corra en cada push. Ver docs/decisions/rfcs/RFC-007-ai-control-plane.md."
```
Sin este paso, el workflow que este commit acaba de crear **no corre nunca** durante los 12 commits siguientes — `push` a una rama sin PR abierto no dispara `pull_request`, y el trigger de `push` está acotado a `production`.

#### Commit 0.2 — Fix I8: scope de proyecto en `_fetch_similar_runs`

Corresponde al commit #7 de RFC-006 (`fix: restrict router similar-runs to current project`). Se adelanta a Fase 0 porque es independiente del resto del gate — no requiere `egress.py` ni el borde sellado para tener sentido, es un bug fix de scope aislado.

*Archivos:* `orchestrator/router.py` (`_fetch_similar_runs`, línea 124; call site línea 241), `tests/test_router.py`.

*Decisión de diseño verificada contra `orchestrator/similarity.py`:* `SimilarityBackend` es un `Protocol` (`ChromaBackend`/`FTS5Backend`) cuyo `query(text, n_results)` **no acepta ningún filtro de proyecto** — ni Chroma ni el fallback FTS5 lo soportan hoy, y `upsert(run_id, text)` tampoco guarda `project` como metadata. Filtrar nativo en el backend (V2: Chroma `where={"project": ...}`, FTS5 `WHERE runs.project=?`) exige cambiar también todos los call sites de `upsert()` para que empiecen a persistir `project`, más reindexar lo ya existente — alcance mayor al de un fix de Fase 0. **V1, la que va en este commit:** sobre-consultar (`n_results=20` en vez de 3) y post-filtrar en Python por `row["project"] == project`, devolviendo los primeros `n`. Limitación conocida y aceptada: si ninguno de los 20 resultados globales más similares pertenece al proyecto, el resultado es `[]` aunque existan runs similares del proyecto más abajo en el ranking global — mismo criterio que RFC-006 §8.3 ("V1 no bloquea merge; V2 queda como mejora").

*Prompt Codex:*
```
Contexto: en orchestrator/router.py, _fetch_similar_runs(task, n=3) (línea ~124)
consulta orchestrator.similarity.get_backend().query() sin acotar por proyecto.
Sus resultados entran al prompt del router LLM externo de CUALQUIER proyecto,
no solo el que originó la tarea. RFC-006 lo documenta como invariante I8.

Verificado: ni ChromaBackend ni FTS5Backend (orchestrator/similarity.py)
soportan un filtro de proyecto en query(), y upsert() tampoco guarda project
como metadata. Un filtro nativo en el backend es un cambio más grande (tocar
upsert() y reindexar) -- NO lo hagas en este commit.

Tarea:
1. Cambia la firma a _fetch_similar_runs(task, project, n=3).
2. Llama a backend.query(task, n_results=20) (sobre-consulta, no 3), filtra
   los resultados en Python por row["project"] == project, y devolvé como
   máximo los primeros n ya filtrados. Documenta con un comentario de una
   línea que esto es V1 (post-filtro) y que puede devolver menos resultados
   de los que existirían con un filtro nativo -- ver RFC-007 §11.1 Commit 0.2
   para el razonamiento completo.
3. Actualiza el call site en decide_provider() (línea ~241): pasa ctx.name.
4. Agrega en tests/test_router.py, con estos nombres exactos (los usa la
   tabla de trazabilidad de evidence/RFC-007/README.md, no los cambies):
   test_fetch_similar_runs_filters_by_project (indexa runs de dos proyectos
   distintos, confirma que _fetch_similar_runs solo devuelve los del
   proyecto pedido), test_router_prompt_excludes_other_projects (confirma
   que el prompt final de decide_provider nunca contiene contenido de otro
   proyecto), test_fetch_similar_runs_overqueries_before_filtering (confirma
   que se pide n_results=20 al backend -- mock de query, assert del
   argumento -- y no 3).
5. pytest tests/test_router.py -v verde.
No implementes el gate todavía.
```

#### Commit 0.3 — Migración `routing_source` (hygiene, no bloqueante contra RFC-006)

RFC-006/RFC-004 confirman que `router-eval --offline` (Commit 1.10) **no necesita telemetría nueva** — usa `runs.provider`, `runs.routing_reason`, `runs.rating`, `RoutingDecision.router_cost_usd`, todos existentes. `routing_source` no es requisito de RFC-006; es una mejora de precisión propia de este documento (RFC-007 v0.3 §5): sin ella, la elegibilidad de runs para el offline replay se decide parseando `routing_reason` como texto libre en vez de un valor filtrable, contaminando el N si se mezclan runs con provider forzado por step/agente.

*Archivos:* `orchestrator/migrate.py` (nueva migración, mismo patrón que `add_rating_to_runs`), `orchestrator/router.py` (`RoutingDecision`), `orchestrator/history.py`, `orchestrator/db.py`, `orchestrator/cli.py`, `orchestrator/background.py` (propagar el campo hasta la persistencia), `tests/test_router.py`.

*Enum verificado contra el código real (`decide_provider()`/`force_provider()`, `router.py:234-343`) — no son "al menos 4 caminos", son 6 distintos:*

| Valor | Camino real | Línea |
|---|---|---|
| `forced_step` | provider fijado en el step activo | `router.py:256-261` |
| `agent_preset` | provider del agent preset del step | `router.py:264-272` |
| `llm_router` | router LLM externo respondió OK | `router.py:324-329` |
| `fallback_no_api_key` | router eligió un provider sin API key configurada | `router.py:307-311` |
| `fallback_router_error` | excepción genérica del router (red, parsing) | `router.py:332-336` |
| `forced_cli` | `--model` explícito, vía `force_provider()` | `router.py:339-343` |

**Nota para Fase 1:** Commit 1.5 reemplaza los dos caminos de fallback por `decide_with_local_router()`. `fallback_no_api_key`/`fallback_router_error` quedan reservados para cuando el fallo es de configuración/red (no de política); se agrega `local_router` para cuando la razón real es una decisión de egress (router externo bloqueado por política). No colapsar ambos casos en un solo valor — son causas distintas y useful para depurar el sistema después.

*Prompt Codex:*
```
Contexto: decide_provider() en orchestrator/router.py retorna por 6 caminos
reales (no 4): step forzado (línea ~256), agent preset (línea ~264), router
LLM exitoso (línea ~324), fallback por API key ausente (línea ~307), fallback
por excepción genérica del router (línea ~332), y force_provider() para
--model explícito (línea ~339). Hoy esa distinción solo vive como texto libre
en routing_reason, no filtrable. Esto no es parte del gate de egress
(RFC-006) -- es una mejora de precisión para que el futuro router-eval
--offline (Commit 1.10) pueda excluir runs cuyo provider no lo decidió el router
LLM, en vez de parsear texto.

Tarea:
1. En orchestrator/migrate.py agrega una migración "add_routing_source_to_runs"
   (mismo patrón que add_rating_to_runs: ALTER TABLE en try/except, dentro de
   _write_lock, _mark_applied, commit). Columna: routing_source TEXT.
2. Agrega routing_source: str = "unknown" a RoutingDecision (router.py).
3. Setea el valor en cada uno de los 6 caminos reales listados arriba, usando
   EXACTAMENTE estos valores: "forced_step", "agent_preset", "llm_router",
   "fallback_no_api_key", "fallback_router_error", "forced_cli". No los
   colapses en un único "fallback" -- son causas distintas (config/red vs
   selección normal) y la Fase 1 va a necesitar distinguirlos.
4. Propaga el campo hasta la función que persiste el run en SQLite (revisa
   orchestrator/history.py y orchestrator/db.py) y desde ahí a cli.py y
   background.py.
5. Tests en tests/test_router.py verificando routing_source correcto para
   cada uno de los 6 caminos (mockea el provider del router LLM para forzar
   tanto el éxito como cada tipo de fallo). pytest tests/ -v verde.
```

### 11.2 Fase 1 — Gate mínimo fail-closed (commits #2-#6 y #8-#12 de RFC-006 §10; el #7 se ejecutó antes, como Commit 0.2)

Cada commit de esta fase corresponde exactamente a un commit ya validado. Cita el texto de RFC-006 directamente: no hay diseño que inventar, hay que **reconstruirlo contra el checkout actual**, que difiere del patch efímero solo en que ahora hay líneas reales verificables.

#### Commit 1.1 — `egress.py`: política fail-closed por construcción (commit #2 — I1, I2, I7)

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

def set_policy(policy: EgressPolicy):   # -> contextvars.Token, para reset explícito (I15)
    if policy.sensitivity not in SENSITIVITY_RANK:
        raise EgressBlocked(f"Nivel de sensibilidad desconocido: {policy.sensitivity!r}")
    return _POLICY.set(policy)

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

*`conftest.py` — ciclo de vida de la política (resuelve una contradicción real: un fixture autouse que siempre fija política chocaría con `test_no_policy_blocks_provider_complete`, que necesita probar la AUSENCIA de política):*
- `set_policy()` devuelve el `Token` de `_POLICY.set(policy)` (ver diseño arriba).
- Fixture `_default_egress_policy` (autouse) fija `EgressPolicy(project="test", sensitivity="internal")` **salvo que el test tenga el marker `@pytest.mark.no_default_policy`**, guarda el token, y en el teardown (después del `yield`) llama `_POLICY.reset(token)` — así ningún test deja política filtrada al siguiente (motiva la invariante I15, Apéndice A).
- `test_no_policy_blocks_provider_complete` lleva `@pytest.mark.no_default_policy` para que el fixture no le fije nada.

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
     no debe degradar a permisivo), luego hace _POLICY.set(policy) y
     RETORNA el Token que devuelve ContextVar.set() -- lo necesitan tests
     y el worker de background.py (Commit 1.7) para poder hacer
     _POLICY.reset(token) y no dejar la política filtrada entre operaciones.
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
   (marcado con @pytest.mark.no_default_policy -- ver punto 3 -- llama
   check() o can_send() sin haber llamado set_policy() -> EgressBlocked),
   test_restricted_project_blocks_public_provider,
   test_blocked_provider_overrides_clearance,
   test_allowed_providers_restricts_even_with_clearance,
   test_unknown_project_sensitivity_fails_closed (set_policy con
   sensitivity="confidencial" -> EgressBlocked),
   test_unknown_provider_clearance_fails_closed,
   test_policy_reset_restores_previous_policy (I15: set_policy(A), guardar
   token, set_policy(B), _POLICY.reset(token), confirmar que current_policy()
   vuelve a ser A, no queda en B ni en "sin política"),
   test_policy_does_not_leak_between_operations (I15: simula dos "operaciones"
   secuenciales en el mismo thread -- set_policy+reset de la primera, después
   current_policy() de la segunda sin haber seteado nada -- debe levantar
   EgressBlocked, no heredar la política de la operación anterior).
3. Busca si ya existe un conftest.py en tests/; si no, créalo. Agrega un
   fixture autouse que:
   - Si el test NO tiene el marker no_default_policy (registralo en
     pyproject.toml o pytest.ini para que no tire warning), llama
     egress.set_policy(EgressPolicy(project="test", sensitivity="internal")),
     guarda el token devuelto, hace yield, y después del yield llama
     _POLICY.reset(token). Esto evita que la política de un test contamine
     al siguiente en el mismo proceso (I15).
   - Si el test SÍ tiene el marker, no fija nada -- solo hace yield.
   Documenta con un comentario de una línea por qué existe (referencia a
   RFC-006 §4.1: sin esto, ~21 tests que llegan a un provider real fallarían
   con "sin política activa" en cuanto el borde quede sellado en Commit 1.2).
4. pytest tests/test_egress.py -v verde. pytest tests/ -v sigue sin
   regresiones (el fixture autouse cubre los tests existentes).

No toques orchestrator/providers/ ni orchestrator/router.py todavía -- eso
es el commit siguiente. Este commit es solo el módulo de política y sus tests,
aislado del resto del sistema.
```

#### Commit 1.2 — Sellar el borde de `BaseProvider` (commit #3 — I3, I4, I9, I11)

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
        return result.to_stream_result()   # nuevo método simétrico, ver nota abajo
```

**Corrección verificada:** `CompletionResult.to_stream_result()` no existe hoy en `providers/base.py`. Solo existe la conversión inversa, `StreamResult.to_completion_result()` (línea 33). Este commit agrega el método simétrico en `CompletionResult` (mismos campos, mapeo directo) para que el `_complete_stream()` default de arriba no tenga que construir un `StreamResult` campo por campo inline.

Cada provider renombra su `complete` → `_complete` y su `complete_stream` → `_complete_stream` (que sigue siendo generador, ahí sí corresponde).

*Tests:* `test_provider_cannot_override_complete`, `test_provider_cannot_override_complete_stream` (definir una subclase de prueba que sobreescriba `complete()` directamente y verificar `TypeError` al definirse, no al ejecutarse), `test_complete_invokes_check_before__complete`, `test_complete_stream_check_is_eager_not_deferred` (verificar con `inspect.isgeneratorfunction(BaseProvider.complete_stream)` que es `False` — esta es la prueba real de I11, no `list(...)` que RFC-006 §3.3 señala como el test que "pasaba probando otra cosa"), `test_streaming_http_not_reached_when_blocked` (mockear `httpx.stream` a nivel de módulo, política que bloquea, confirmar que nunca se invoca).

*Prompt Codex:*
```
Contexto: orchestrator/egress.py ya existe (commit anterior). Ahora hay que
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
   e. Agrega un método to_stream_result() a CompletionResult (dataclass en
      el mismo archivo) simétrico al StreamResult.to_completion_result() que
      ya existe (línea ~33) -- mismos campos, mapeo directo, construye y
      retorna un StreamResult.
   f. Agrega _complete_stream() con un default razonable si no existe ya
      uno: envuelve _complete(), yieldea result.text, y en el return usa
      el nuevo result.to_stream_result() del punto e (NO uses
      result.to_stream_result() antes de haberlo creado -- ese método no
      existe todavía en el código actual, es parte de este mismo commit).
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
   commit anterior ya tiene el fixture autouse de política permisiva, no
   deberían fallar; si alguno falla de todos modos, es una ruta de egress
   que el fixture no cubre -- repórtala, no la silencies agregando un
   try/except.

No toques orchestrator/router.py ni orchestrator/background.py todavía.
```

#### Commit 1.3 — Sensibilidad de proyecto y clearance de provider (commit #4)

*Archivos:* `orchestrator/context.py` (`ProjectContext`), `orchestrator/config.py`, `orchestrator/egress.py` (`policy_for_project()`), `config.example.yaml`, `tests/test_egress.py`.

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

*Función canónica (resuelve una duplicación real: sin esto, Commit 1.3 construye la `EgressPolicy` en sus tests y Commit 1.7 la construye de nuevo dentro del worker, con riesgo de que ambas versiones diverjan):* este commit agrega `orchestrator.egress.policy_for_project(ctx: ProjectContext, config: dict) -> EgressPolicy`, la **única** función que combina `ctx.sensitivity`/`ctx.blocked_providers`/`ctx.allowed_providers` con el `clearance` de cada provider (leído de `config.get_provider_config(config, provider).get("clearance", "internal")` para cada provider en `orchestrator.paths.PROVIDERS`). Todo el resto del sistema (tests de este commit, el worker de Commit 1.7) la reusa — nadie más construye una `EgressPolicy` a mano fuera de este punto.

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
4. En orchestrator/egress.py, agrega policy_for_project(ctx, config) ->
   EgressPolicy: construye la EgressPolicy leyendo ctx.sensitivity,
   ctx.blocked_providers, ctx.allowed_providers, y arma provider_clearance
   iterando sobre orchestrator.paths.PROVIDERS y llamando
   config.get_provider_config(config, provider).get("clearance", "internal")
   para cada uno (envolvé en try/except ConfigError por si un provider de
   PROVIDERS no está en config.yaml, y usá "internal" como default en ese
   caso también). Esta es la ÚNICA función que debe construir una
   EgressPolicy desde un ProjectContext -- ni los tests de este commit ni el
   worker de background.py (Commit 1.7, más adelante) deben repetir esta lógica
   a mano.
5. NO agregues un archivo policy.yaml separado en este commit -- sensitivity
   y blocked_providers/allowed_providers viven en el mismo context.yaml
   que ya existe. Esa separación es una mejora de seguridad de Fase 2,
   documentada pero fuera de alcance aquí.
6. Agrega tests en tests/test_egress.py que llamen policy_for_project()
   con un ProjectContext y una config con clearances reales (no valores
   hardcodeados aparte) y verifiquen el resultado de can_send() para el
   caso del PoC: proyecto sensitivity=restricted,
   blocked_providers=[deepseek, gemini], provider deepseek -> bloqueado;
   provider claude (clearance restricted) -> permitido.
7. pytest tests/ -v verde.

No conectes esto todavía con decide_provider() -- eso es el commit siguiente,
que primero necesita el router local (Commit 1.4).
```

#### Commit 1.4 — Router local determinístico (commit #5, va antes del #6)

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

**Corrección verificada:** `catalog.get_model_profiles()` (Decision 0002 / ADR-002) **no expone precio numérico** — solo un flag `has_price: bool`, pensado para el prompt del router LLM, no para comparar costos programáticamente. La API correcta es `catalog.get_effective_pricing(config)`, que devuelve `{model_id: {input, output, ...}}` (la forma legacy que ya usa `calculate_cost`). Para el paso 4: por cada provider en `permitted`, resolver su `model` configurado vía `config.get_provider_config(config, provider)["model"]`, buscar ese `model` en `get_effective_pricing(config)`, y comparar `.get("input")`. Si un provider permitido no tiene precio en el catálogo, tratarlo como el más caro (no como gratis) para no sesgar la elección hacia modelos sin dato de precio.

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
   f. Si no, elige el provider de permitted con el precio de input más bajo.
      NO uses catalog.get_model_profiles() para esto -- no expone precio
      numérico, solo un flag has_price. Usa
      orchestrator.catalog.get_effective_pricing(config), que devuelve
      {model_id: {input, output, ...}}. Para cada provider en permitted,
      resuelve su modelo configurado con
      orchestrator.config.get_provider_config(config, provider)["model"],
      buscá ese modelo en get_effective_pricing(config), y comparalo por
      .get("input"). Si un provider permitido no tiene precio en el
      catálogo, tratalo como el más caro de la comparación (no como gratis),
      para no sesgar la elección hacia modelos sin dato de precio.
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

No conectes esto todavía a decide_provider() -- ese es el commit siguiente,
que sí depende de que este ya exista y esté probado.
```

#### Commit 1.5 — Cerrar el pre-routing egress (commit #6 — I5, I6, I14)

Este es el commit que cierra el bug original de §1. **I14 es el hallazgo más importante de toda la serie (RFC-006 §3.8)**: en una iteración anterior, el sistema abortaba con `EgressBlocked` cuando el `fallback_provider` configurado estaba bloqueado, *aunque existiera otro provider permitido* — y un test de seguridad (`I6` en RFC-002/003/004) afirmaba que ese aborto era correcto. Es la clase de bug que mata productos de seguridad: bloquear de más hasta que el usuario desactiva el gate.

*Archivos:* `orchestrator/router.py` (`decide_provider`, líneas 234-336, específicamente la llamada al router LLM en 288-290 y el manejo de excepción en 331-336), `tests/test_router.py`.

*Diseño (RFC-006 §3.6, §3.8; pseudocódigo más explícito en RFC-003 §6.2):*
```python
def decide_provider(task: str, ctx: ProjectContext, config: dict) -> RoutingDecision:
    router_cfg = get_router_config(config)
    router_provider_name = router_cfg.get("provider", "deepseek")

    # ... (lógica de step forzado / agent preset se mantiene igual, ya se evalúa
    #      antes de llegar acá; falta agregarle su propio egress.check en un
    #      commit posterior si se decide gobernar también esos caminos)

    if not egress.can_send(router_provider_name):
        # NO construir el prompt full-context: el router local no necesita verlo igual
        decision = decide_with_local_router(task, ctx, config)
        decision.routing_source = "local_router"
    else:
        try:
            # ... construir prompt, llamar router LLM (esto ya pasa por
            #     BaseProvider.complete() sellado en Commit 1.2, así que el check
            #     de phase="provider" corre igual, pero acá se evita incluso
            #     construir el prompt si ya sabíamos que iba a fallar)
            decision = <llamada actual al router LLM>
        except EgressBlocked:
            # excepción específica, va ANTES de la genérica -- una denegación
            # de política nunca se confunde con una falla de red (ver I13, Commit 1.8)
            decision = decide_with_local_router(task, ctx, config)
            decision.routing_source = "local_router"
        except Exception:
            # error de red/parsing del router externo -- NO anexar str(exc)
            # crudo a decision.reason, puede contener datos no previstos;
            # usar un reason_code fijo
            decision = decide_with_local_router(task, ctx, config)
            decision.routing_source = "fallback_router_error"
            decision.reason += " (router externo falló: error de red o parsing)"

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
Contexto: este es el commit que cierra el bug original documentado en RFC-006 §1
y §3 (pre-routing egress: el router LLM recibe el contexto completo de la
tarea antes de que exista ninguna política). orchestrator/egress.py,
BaseProvider sellado y decide_with_local_router() ya existen de los commits
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
   (ya pasa por BaseProvider.complete() sellado, Commit 1.2). Envuelve esa
   llamada en DOS except separados, en este orden -- primero el específico,
   después el genérico (I13 depende de este orden, no lo colapses en uno solo):
   - except EgressBlocked: cae a decide_with_local_router(),
     routing_source="local_router" (fue una decisión de política).
   - except Exception (red, parsing, cualquier otra falla del router
     externo): cae a decide_with_local_router() también, pero
     routing_source="fallback_router_error" (NO fue una decisión de
     política, fue un fallo técnico -- son causas distintas, no las
     mezcles en el mismo valor). NO anexes str(exc) crudo a
     decision.reason -- puede contener datos no previstos del error;
     agregá un texto fijo tipo "router externo falló: error de red o parsing".
   Ninguno de los dos casos cae a un fallback_provider fijo de config.yaml.
4. CRÍTICO (esto es I14): en ningún punto de esta función debe levantarse
   EgressBlocked solo porque el fallback_provider configurado en config.yaml
   esté bloqueado. decide_with_local_router() ya se encarga de elegir entre
   TODOS los providers permitidos, no solo el fallback_provider preconfigurado.
   Solo debe levantarse EgressBlocked cuando decide_with_local_router() en sí
   mismo determina que NINGÚN provider está permitido (eso ya lo hace el commit
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
Commit siguiente.
```

#### Commit 1.6 — Escalación por secreto en el payload (commit #8 — I10)

*Archivos:* `orchestrator/egress.py` (extender `check`), `orchestrator/rag.py` (reutilizar `_contains_secrets`, ya existe en línea 166 — confirmado, no reescribir), `orchestrator/providers/base.py` (pasar `prompt`/`system` al check desde `complete()`/`complete_stream()`), `tests/test_egress.py`.

*Alcance real, verificado contra `rag.py:60-68` (`_SECRET_PATTERN`):* NO es detección universal de secretos. El regex solo reconoce formatos específicos y conocidos: claves Anthropic (`sk-ant-*`), OpenAI (`sk-*`), MercadoPago (`APP_USR-*`), `token=<hex>`, bloques de llave privada (`-----BEGIN ... PRIVATE KEY`), AWS access key ID (`AKIA*`) y `aws_secret_access_key=...`. Un `API_KEY=lo-que-sea` genérico **no matchea nada de esto** — no lo uses como ejemplo de prueba, es un falso ejemplo. Ver la corrección de la Invariante I10 en el Apéndice A: "patrón reconocido", no "cualquier secreto".

*Prompt Codex:*
```
Contexto: orchestrator/rag.py ya tiene _contains_secrets(text) (línea 166),
usado hoy solo al indexar contenido para RAG. RFC-006 §3.9 reutiliza esta
misma función en el borde de egress: si el prompt o system prompt que se
va a enviar a un provider contiene un patrón de secreto RECONOCIDO (no
cualquier secreto -- ver la lista exacta abajo), la sensibilidad efectiva
de ESE envío escala a "secret" -- nivel que ningún clearance configurado
normalmente alcanza, así que el envío se bloquea.

_SECRET_PATTERN (rag.py:60-68) reconoce: claves Anthropic "sk-ant-*", claves
OpenAI "sk-*", claves MercadoPago "APP_USR-*", "token=<hex>", bloques
"-----BEGIN ... PRIVATE KEY", AWS access key "AKIA*" (16 chars), y
"aws_secret_access_key=...". NO reconoce un "API_KEY=valor" genérico -- no
uses eso como ejemplo en los tests, usa un valor que sí matchee, por ejemplo
un string "AKIA" + 16 caracteres alfanuméricos.

Tarea:
1. En orchestrator/egress.py, agrega una función check_payload(provider,
   prompt, system, phase) (o extiende check() con parámetros opcionales
   prompt/system) que: si prompt o system contienen un secreto según
   rag._contains_secrets() (impórtala, no la dupliques), evalúa can_send()
   como si policy.sensitivity fuera "secret" en vez del valor real de la
   política, sin mutar la policy real en el ContextVar (usa
   dataclasses.replace sobre una copia local).
2. Conecta esto en BaseProvider.complete()/complete_stream() (Commit 1.2): en
   vez de solo egress.check(self.name, phase=...), pasa también prompt y
   system para que la escalación por secreto se evalúe en cada llamada real.
3. IMPORTANTE: el mensaje de la excepción EgressBlocked en este caso NO debe
   incluir el prompt, el system, ni ningún fragmento del secreto detectado
   -- solo un reason_code fijo como "secret_pattern_detected".
4. Tests en tests/test_egress.py: test_secret_in_prompt_escalates_to_secret_and_blocks
   (payload con un valor que matchee _SECRET_PATTERN de verdad -- por ejemplo
   un "AKIA" + 16 caracteres alfanuméricos, NO un "API_KEY=..." genérico que
   el regex actual no reconoce -- sensitivity del proyecto "internal",
   provider con clearance "internal" -- debería pasar SIN el secreto y
   bloquearse CON él), test_generic_unrecognized_secret_does_not_escalate
   (un valor tipo "MY_PASSWORD=hunter2" que NO matchea ningún patrón conocido
   -- confirma que NO escala, documentando el límite real de esta invariante),
   test_egress_error_message_never_contains_payload (verifica con un string
   secreto conocido que ese string nunca aparece en str(exc) de EgressBlocked).
5. pytest tests/ -v verde.
```

#### Commit 1.7 — Política dentro del worker thread (commit #9 — I12)

*Archivos:* `orchestrator/background.py` (`_worker`, líneas 52-90; `submit_run`, líneas 22-49).

*Hallazgo confirmado contra el código real de este repo (no solo el patch efímero):* `submit_run()` (línea 43-48) crea `threading.Thread(target=_worker, ...)`. `ContextVar` no se copia automáticamente a un thread nuevo — si la política se fija en el thread que llama a `submit_run()` (por ejemplo en `server.py::_post_run`), `_worker()` corriendo en su propio thread jamás la ve, y **cualquier llamada a un provider dentro de `_worker()` levantaría `EgressBlocked` por "sin política activa"**, aunque el usuario sí tenga una política válida configurada. Sin el fix de este commit, todo run disparado desde el dashboard moriría en cuanto se conecte el gate.

*Resolución para `ctx=None` (decisión de seguridad, no solo de threading):* `_worker()` (líneas 69-74) hoy captura `except Exception: ctx = None` de forma indiscriminada y sigue con el provider default. Con el gate activo esto no puede seguir así — hay que distinguir dos casos:

- **Proyecto nunca configurado** (`context.ContextNotFoundError`, `context.py:13`, se levanta cuando no existe `.orchestrator/context.yaml`): tratarlo como proyecto nuevo, aplicar `EgressPolicy(project=project, sensitivity="internal")` (el mismo `DEFAULT_SENSITIVITY` que ya preserva el comportamiento actual). **No bloquea** — mantiene disponibilidad para proyectos recién creados.
- **`context.yaml` existe pero falla al cargar/parsear** (cualquier otra excepción — YAML corrupto, error inesperado): **fail closed**, `EgressBlocked`. Un archivo de política que existe pero no se puede confiar en su contenido es el "nivel desconocido" que I7 ya exige bloquear — dejarlo pasar en silencio enmascararía una política corrupta o alterada.

*Prompt Codex:*
```
Contexto: orchestrator/background.py::submit_run() (línea ~43) crea un
threading.Thread nuevo que ejecuta _worker(). Python's ContextVar NO se
propaga automáticamente a un thread creado con threading.Thread (sí se
propaga a asyncio tasks, pero no a threads del módulo threading). Esto
significa que aunque alguien fije una política de egress ANTES de llamar
submit_run(), el thread de _worker() no la va a ver, y en cuanto el gate
esté conectado (commits anteriores), TODO run lanzado desde el dashboard va a
fallar con EgressBlocked("Sin política activa") -- sin importar que la
configuración sea correcta.

orchestrator.egress.policy_for_project(ctx, config) ya existe (Commit 1.3) --
úsala acá, no reconstruyas la EgressPolicy a mano.

Tarea:
1. En orchestrator/background.py::_worker() (línea ~52), como una de las
   PRIMERAS sentencias dentro del try (antes de cualquier llamada que
   termine invocando un provider), resuelve ctx y fija la política:
   - Si context_module.load_context(project_path) tiene éxito: llama
     egress.set_policy(egress.policy_for_project(ctx, config)).
   - Si levanta context.ContextNotFoundError específicamente (revisa
     orchestrator/context.py:13): el proyecto nunca tuvo context.yaml.
     Trátalo como proyecto nuevo -- fija
     egress.set_policy(EgressPolicy(project=project, sensitivity="internal"))
     y segui con ctx=None como hace el código actual. NO bloquea.
   - Si levanta cualquier OTRA excepción (YAML corrupto, error inesperado):
     esto es distinto de "proyecto nuevo" -- es un context.yaml que existe
     pero no se puede confiar en su contenido. NO sigas con ctx=None como
     hace el código actual -- deja que la excepción se propague (o relanzá
     como EgressBlocked explícitamente) para que el run falle cerrado en
     vez de silenciosamente usar el provider default.
   Esto reemplaza el "except Exception: ctx = None" único que hay hoy en
   líneas 69-74 -- tenés que separar ContextNotFoundError del resto, no
   agregar un except más encima del genérico.
2. Verifica que NO estás asumiendo que la política del thread padre (donde
   se llamó submit_run) se propaga -- no debe haber ningún código que
   dependa de eso.
3. Usa el Token que devuelve set_policy() (Commit 1.1) para hacer
   _POLICY.reset(token) al final del worker (en un finally), consistente
   con el ciclo de vida ya establecido en conftest.py.
4. Tests en un nuevo tests/test_background.py (o extiende el existente si
   ya hay uno para background.py):
   test_background_worker_sets_policy_inside_thread (arranca un run real
   vía submit_run con una policy que el thread padre fija en su propio
   ContextVar, y confirma que el worker de todos modos puede completar sin
   EgressBlocked porque fija SU PROPIA política),
   test_parent_thread_policy_does_not_silently_leak_to_worker,
   test_missing_context_yaml_uses_internal_default_and_does_not_block
   (proyecto sin context.yaml -- ContextNotFoundError -- el run continúa),
   test_corrupted_context_yaml_fails_closed (context.yaml con YAML inválido
   -- el run falla, NO usa silenciosamente el provider default),
   test_worker_resets_policy_in_finally (I15: confirma que el Token de
   set_policy() se resetea en un finally al terminar el worker, incluso si
   el run falla con una excepción -- corré dos runs seguidos en el mismo
   proceso con policies distintas y confirmá que el segundo no hereda nada
   del primero).
5. pytest tests/ -v verde.
```

#### Commit 1.8 — Nunca reintentar una denegación de política (commit #10 — I13)

*Archivos:* `orchestrator/background.py`, línea 128-153 (el loop de retry con backoff).

*Hallazgo confirmado contra el código real:* el loop `for _attempt in range(_MAX_RETRIES): try: ... except Exception as exc: ... retry` (líneas 128-153) captura **cualquier** excepción, incluida una futura `EgressBlocked`, y la reintenta hasta 3 veces con backoff exponencial (`_RETRY_BASE ** _attempt`, hasta ~4 segundos de espera). Sin este fix, una denegación de política tarda ~3x más en fallar y dos reintentos completamente inútiles quedan en los logs como si hubieran sido timeouts transitorios.

*Prompt Codex:*
```
Contexto: orchestrator/background.py::_worker(), líneas ~128-153, tiene un
loop de reintentos con backoff exponencial (_MAX_RETRIES=3) que captura
`except Exception as exc` de forma genérica alrededor de la llamada a
provider.complete_stream()/complete(). Una vez que el gate de egress esté
conectado (commits anteriores), una denegación de política (EgressBlocked) va
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
3. Tests -- cubrí los DOS momentos donde EgressBlocked puede originarse
   dentro del try (son distintos en un generador: el check de Commit 1.2 es
   eager, así que hoy solo debería poder levantar en la línea que llama a
   provider.complete_stream(...) misma, pero un test que cubra también
   next(_gen) protege contra una futura regresión que vuelva el check
   diferido sin que nadie lo note):
   test_egress_blocked_at_call_is_not_retried (mockea provider.complete_stream
   para que la LLAMADA misma levante EgressBlocked, confirma que se invoca
   exactamente 1 vez, no 3, sin ningún time.sleep de por medio -- mockeá
   time.sleep también y confirmá 0 llamadas);
   test_egress_blocked_during_iteration_is_not_retried (mockea
   provider.complete_stream para que devuelva un generador que levanta
   EgressBlocked recién en el primer next(), confirma el mismo resultado:
   1 invocación, sin retry, sin sleep);
   test_transient_error_is_still_retried (confirma que un error genérico,
   por ejemplo ConnectionError, sigue reintentándose hasta 3 veces como
   antes -- no rompas ese comportamiento).
4. pytest tests/ -v verde.
```

#### Commit 1.9 — `egress_decisions`: log de decisión, nunca de payload (commit #11)

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

*Decisiones de diseño (resuelven ambigüedad del prompt original):*
- **Se loguean ambas decisiones, `allowed` y `blocked`** — es lo único que permite calcular `policy_evaluation_coverage = 100%` (RFC-007 §10.1). La fila es liviana (sin payload), el volumen no es un problema real.
- **La responsabilidad de loguear vive en `check()`, nunca en `can_send()`.** `can_send()` se queda como función de consulta pura, sin efectos secundarios — `decide_with_local_router()` (Commit 1.4) la llama repetidamente para filtrar `permitted`, y si logueara en cada llamada duplicaría filas sin que haya ocurrido una decisión real de envío.
- **`run_id` queda `NULL` en el momento del check.** No se hace threading de `run_id` a través de la firma de `BaseProvider.complete()/complete_stream()` — cambiaría una interfaz pública por poco beneficio. La correlación exacta con `runs.id` es mejora de Fase 3 (ledger rico, ya diferida hasta 500 runs reales).

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
   nullable -- queda NULL en este commit, no hagas threading de run_id a través
   de BaseProvider, es mejora de Fase 3). Índices por (project, ts) y por
   (decision, phase).
2. En orchestrator/egress.py, agrega una función log_decision(project,
   provider, phase, decision, reason_code, sensitivity=None, clearance=None,
   run_id=None) que inserta una fila. Llámala EXCLUSIVAMENTE desde check()
   -- can_send() se queda como función de consulta pura, sin efectos
   secundarios, porque decide_with_local_router() (Commit 1.4) la llama
   repetidamente en un loop para filtrar providers permitidos, y si
   logueara ahí duplicaría filas por cada consulta en vez de por cada
   decisión real de envío. check() debe loguear TANTO "allowed" como
   "blocked" (no solo blocked) -- es el único dato que permite calcular
   policy_evaluation_coverage=100% más adelante.
3. REGLA DURA, no negociable: reason_code es SIEMPRE un código corto de una
   lista cerrada (por ejemplo "no_active_policy", "provider_blocked",
   "clearance_insufficient", "unknown_sensitivity", "secret_pattern_detected",
   "allowed"), NUNCA texto libre que pueda contener fragmentos de la tarea
   o del proyecto de forma no controlada.
4. Tests en tests/test_egress.py: test_egress_log_does_not_store_payload
   (pasa un prompt con contenido reconocible como argumento a check()/complete(),
   verifica que ninguna fila de egress_decisions ni ningún argumento de
   log_decision contiene ese contenido), test_blocked_decision_is_logged,
   test_allowed_decision_is_logged, test_can_send_does_not_log
   (llama can_send() varias veces seguidas, confirma 0 filas nuevas en
   egress_decisions -- solo check() loguea).
5. pytest tests/ -v verde.
```

#### Commit 1.10 — `router-eval --offline` (commit #12)

*Archivos:* nuevo `orchestrator/eval.py` (o extender `router.py`), `orchestrator/cli.py` (comando `router-eval --offline`), nuevo `tests/test_eval.py`.

*Diseño (RFC-006 §7.3, RFC-004 §5.3 — coincide en ambas rondas: no hace falta telemetría nueva):*

| Dato | Dónde | Estado |
|---|---|---|
| Provider elegido por el router LLM | `runs.provider` | existe |
| Razón del ruteo | `runs.routing_reason` | existe |
| Calidad, juzgada por humano | `runs.rating` ∈ `{useful, partial, wrong}` | existe |
| Costo del router externo | `router_cost_usd` en `runs` | existe |
| Filtro de elegibilidad preciso | `routing_source = 'llm_router'` | agregado en Fase 0 Commit 0.3 |

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
     routing_source ya existe (Commit 0.3 de Fase 0) filtra
     routing_source='llm_router' -- si esa columna todavía no existe en
     el momento de ejecutar este commit, cae de vuelta a status='done' AND
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

**Salida de Fase 1:** los 10 commits mapeados contra los commits #2-#6 y #8-#12 de RFC-006 (el #7 se ejecutó antes, como Commit 0.2) reconstruidos contra `production@4ae9497` real, con invariantes I1-I15 completas y verificadas en CI (§10.1 de v0.3, ahora sin huecos). H1a/H1b con evidencia pública completa por primera vez en la serie. Antes de sacar el PR de Draft: completar la tabla de trazabilidad y correr la verificación adversarial de `docs/decisions/evidence/RFC-007/README.md` — un commit que compila y pasa su test no es lo mismo que un gate verificado end-to-end.

### 11.3 Fase 2 — Separación política/contexto (evolución de seguridad, no parte del gate validado)

Con Fase 1 completa, el router local ya es real (no "modo sombra" — decide de verdad en cascada cuando el externo está bloqueado). Lo único que RFC-007 v0.3 §8 proponía y que RFC-006 no implementó es separar `sensitivity`/`blocked_providers` de `context.yaml` a un `policy.yaml` propio, para que un agente con permiso de escritura sobre el repo no pueda rebajar su propia política vía prompt injection editando el mismo archivo que declara sus convenciones de código.

#### Commit 2.1 — `policy.yaml` separado, con precedencia sobre `context.yaml`

*Prompt Codex:*
```
Contexto: desde Fase 1, sensitivity/blocked_providers/allowed_providers
viven en .orchestrator/context.yaml, el mismo archivo que stack/conventions/
routing_notes. RFC-007 v0.3 §8 señala el riesgo: un agente con permiso de
escritura sobre el repo (o una inyección de prompt vía contenido del propio
repo) podría editar ese archivo para rebajar su propia sensibilidad o
desbloquear un provider. Este commit mueve la política a un archivo separado.

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

RFC-005 propuso `decision_events`/`context_lineage`/`outcome_events` con hash chaining. **RFC-006 §8 lo marca fuera de alcance de forma explícita hasta 500 runs gobernados reales**, y critica a RFC-005 por "scope creep con 0 runs" (RFC-006 Apéndice D). Este documento adopta esa misma disciplina: **no generar commits para el ledger rico todavía.** La tabla lean `egress_decisions` (Fase 1, Commit 1.9) es suficiente registro hasta que exista volumen real. Cuando `SELECT COUNT(*) FROM runs WHERE status='done'` supere ~500, retomar este documento y diseñar Fase 3 recién ahí, contra datos reales en vez de proyecciones.

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

*Commit único de esta fase (implementación técnica, la decisión estadística es un análisis posterior, no código):*

```
Prompt Codex:
Contexto: router-eval --offline (Fase 1 Commit 1.10) y decide_with_local_router
(Fase 1 Commit 1.4) ya existen. Falta la capacidad técnica de correr un canary
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
no código de este commit.
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

Sin cambios: dependen de RN-1 (threat model), RN-2 (ontología de agentes), EP-1 (pre-registro H2) — investigación no iniciada. No se generan commits hasta que 500 runs gobernados existan (gatilla Fase 3) y esos RN/EP se cierren.

---

## 12. Trabajo diferido

RN-1 (threat model), RN-2 (ontología de agentes), RN-3 (estado del arte), EP-1 (pre-registro H2), RN-4 (métricas de fragmentación), RN-5 (modelo de degradación), RN-6 (planos formales).

## 13. Riesgos

- **Deriva entre este documento y el código real.** Cada commit cita líneas verificadas el 2026-07-12 contra `4ae9497`. Cada prompt Codex pide releer el archivo antes de editar, no asume el número de línea a ciegas.
- **El patch efímero de RFC-006 nunca se probó contra ESTE checkout exacto** — se probó contra un checkout del mismo commit, pero como parche aplicado localmente y descartado. Este documento reconstruye la misma lógica commit por commit contra el árbol real; es razonable esperar pequeñas fricciones de integración (nombres de función ligeramente distintos, por ejemplo) que RFC-006 no documenta porque nunca se mergeó. Cada commit de Fase 1 pide a Codex correr `pytest tests/ -v` como último paso — ahí aparecerán.
- **`routing_source` (Fase 0 Commit 0.3) no es parte de RFC-006.** Es una adición de este documento. Si en algún punto entra en conflicto con el diseño de `router-eval --offline` de Commit 1.10, Commit 1.10 tiene precedencia (es lo validado) y `routing_source` se usa solo como filtro opcional, nunca como dependencia dura.

---

## Conclusión

La revisión 1 de este documento diseñó un gate propio sin saber que uno mejor ya existía, probado, en el disco del usuario. La revisión 2 no inventa nada: reconstruye contra el código real de `production@4ae9497` los commits #2-#6, #8-#12 (y el #7 como Commit 0.2 de Fase 0) que la serie RFC-001→006 ya validó localmente — **14 invariantes (I1-I14) mediante 15 tests** (`pytest tests/test_egress.py` → 15 passed, `pytest tests/` → 126 passed / 1 failed, resultado histórico de un patch efímero que nunca se mergeó, no un baseline comparable con este checkout hoy) — en el mismo orden, con las mismas invariantes, incluyendo el hallazgo más valioso de toda la serie: I14, el falso bloqueo que un test de seguridad anterior protegía por error.

Dos pasadas de verificación posteriores, ambas con Codex contra este mismo checkout, encontraron y cerraron: 5 desajustes materiales y 12 preguntas bloqueantes en el plan (tercera pasada), y una explicación aritmética incorrecta sobre por qué el baseline actual (`112 passed, 0 failed`, verificado empíricamente) difiere del `126/1` histórico de RFC-006 (cuarta pasada — la diferencia real son los 15 tests de `test_egress.py` del patch descartado, no evolución de la suite). Se agregó además una invariante nueva, **I15** (aislamiento de política entre operaciones/threads), que ni RFC-006 ni las revisiones anteriores de este documento habían formalizado — **I15 queda pendiente de implementación y validación en Fase 1**, a diferencia de I1-I14 que ya tienen evidencia histórica (aunque no pública) de haber pasado.

La siguiente acción sigue sin ser un documento: es pegar el prompt de Commit 0.1 en Codex.

---

## Apéndice A — Invariantes I1-I15 (I1-I14 de RFC-006 §4.3; I15 agregada en la verificación de este documento)

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
| I10 | Un payload que coincide con un **patrón reconocido** por `_contains_secrets()` escala a `secret` y bloquea — no es detección universal de secretos, es una lista cerrada de patrones conocidos (Anthropic/OpenAI/MercadoPago/AWS/llaves privadas, ver `rag.py:60-68`) | RFC-002, **acotada** durante la verificación de este documento (2026-07-13): el enunciado original ("secreto en el prompt escala...") sobreafirmaba cobertura universal |
| I11 | El check de streaming es eager, no diferido | RFC-003 |
| I12 | La política no se filtra entre threads | RFC-003 |
| I13 | Una denegación de política nunca se reintenta | RFC-004 |
| **I14** | **Fallback bloqueado no aborta si existe otro proveedor seguro** | **RFC-006** |
| **I15** | **La política activa se establece y se limpia por operación; una política de una operación anterior en el mismo thread no puede filtrarse a la siguiente** | **Verificación de RFC-007 con Codex (2026-07-13), no parte del RFC-006 original — motiva que `set_policy()` devuelva un `contextvars.Token` (Commit 1.1) y que el worker haga `reset()` en un `finally` (Commit 1.7)** |

I4′: I9 reemplaza funcionalmente a I4; I4 se conserva como red redundante. RFC-006 dejó I15 vacía a propósito ("a formalizar cuando exista el código que las pruebe") — queda formalizada acá.

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
Fase 0   Commit 0.1  CI corre pytest completo (.[all], baseline actual verificado: 112/0, 100% verde)
         [push feat/egress-gate + abrir Draft PR acá — sin esto, CI no corre en los 12 commits siguientes]
         Commit 0.2  Fix I8: sobre-consulta n=20 + post-filtro (adelanta commit #7, independiente)
         Commit 0.3  Migración routing_source, enum de 6 valores (hygiene, no bloqueante contra RFC-006)
Fase 1   Commit 1.1  egress.py: ContextVar sin default, EgressBlocked, check()/can_send(),   [commit #2 — I1,I2,I7,I15]
                 set_policy() devuelve Token
         Commit 1.2  Sellar BaseProvider vía __init_subclass__, 4 providers,                 [commit #3 — I3,I4,I9,I11]
                 + CompletionResult.to_stream_result()
         Commit 1.3  Sensitivity de proyecto + clearance de provider + policy_for_project()   [commit #4]
         Commit 1.4  decide_with_local_router() (cheapest vía get_effective_pricing)          [commit #5]
         Commit 1.5  Cerrar pre-routing egress + fix del falso bloqueo                       [commit #6 — I5,I6,I14]
         Commit 1.6  Escalación por secreto reconocido (_contains_secrets reutilizada)        [commit #8 — I10]
         Commit 1.7  Política dentro del worker thread + fail-closed en context.yaml         [commit #9 — I12]
                 corrupto vs proyecto nuevo
         Commit 1.8  Nunca reintentar EgressBlocked (call y next())                          [commit #10 — I13]
         Commit 1.9  Tabla egress_decisions, allowed+blocked, logging solo en check()        [commit #11]
         Commit 1.10 router-eval --offline                                                    [commit #12]
WP-Net-1 Commit N.1  Dashboard --host + token                                                [elegible en paralelo desde Fase 1]
Fase 2   Commit 2.1  policy.yaml separado de context.yaml, con precedencia
Fase 3   [diferida hasta 500 runs gobernados reales — no generar commits todavía]
Fase 4   Commit 4.1  Canary por hash determinístico [regla de decisión ya declarada, §11.5]
Fase 5-6 [sin commits -- depende de RN-1/RN-2/EP-1]
```
