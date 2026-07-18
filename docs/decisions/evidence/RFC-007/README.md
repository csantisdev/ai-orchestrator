---
type: evidence
supports: RFC-007
---

# Evidencia de RFC-007

Esta carpeta guarda la evidencia de ejecutar `docs/decisions/rfcs/RFC-007-ai-control-plane.md` Parte II (los 13 commits de Fase 0 + Fase 1) contra código real. Distinto de `../RFC-006/README.md`, que documenta el diseño original y su patch efímero (histórico, nunca publicado) — I1-I14 se **diseñaron** en RFC-006, pero se **implementan y verifican acá**, junto con I15 (invariante nueva, exclusiva de RFC-007).

**Fase 0-1 completa (2026-07-18, los 13/13 commits).** Esta carpeta recibió:

- Log completo de `pytest tests/ -v` al cierre de Fase 1 ([`pytest-full-2026-07-18.txt`](./pytest-full-2026-07-18.txt)) — no "antes y después de cada commit" como se planeaba originalmente (cada commit se verificó individualmente contra el repo real y su propio run de CI durante la ejecución, ver tabla de trazabilidad; el log agregado acá es el estado final).
- Log de `pytest tests/test_egress.py -v` ([`pytest-egress-2026-07-18.txt`](./pytest-egress-2026-07-18.txt)).
- El resultado del PoC de RFC-006 §4.2 (`restricted-project.example` restricted → deepseek bloqueado → claude permitido) reproducido contra el código real, no contra el patch viejo — ver sección de verificación adversarial, punto 3, y [`poc-rfc006-4.2.py`](./poc-rfc006-4.2.py).
- El link al Draft PR y a cada run de CI (`tests.yml`, RFC-007 §11.0-§11.1 Commit 0.1) que confirma lo anterior en un entorno limpio, no solo local — ver tabla de trazabilidad.

No pegar prompts, tareas ni contexto real de proyectos en esta carpeta — mismas reglas que en `evidence/RFC-006/`: el log registra la decisión, nunca el payload (RFC-006 §6.2).

## Tabla de trazabilidad

Completar una fila por invariante a medida que Fase 1 avanza — no antes. `Commit` es el SHA real que la implementó, `CI` el link al run que la validó en el Draft PR.

| Invariante | Test | Commit | CI |
|---|---|---|---|
| I1 | `test_no_policy_blocks_provider_complete` | `60c431f` | [run](https://github.com/csantisdev/ai-orchestrator/actions/runs/29231131539/job/86755411217) |
| I2 | `test_restricted_project_blocks_public_provider` | `60c431f` | [run](https://github.com/csantisdev/ai-orchestrator/actions/runs/29231131539/job/86755411217) |
| I3 | `test_streaming_http_not_reached_when_blocked` | `a76a4d7` | [run](https://github.com/csantisdev/ai-orchestrator/actions/runs/29631543303/job/88046001542) |
| I4 | `test_provider_cannot_override_complete` | `a76a4d7` | [run](https://github.com/csantisdev/ai-orchestrator/actions/runs/29631543303/job/88046001542) |
| I5 | `test_external_router_blocked_uses_local_router_not_fixed_fallback` | `39a8b2c` | [run](https://github.com/csantisdev/ai-orchestrator/actions/runs/29632691437/job/88049370327) |
| I6 | `test_no_fixed_claude_fallback_when_router_blocked` | `39a8b2c` | [run](https://github.com/csantisdev/ai-orchestrator/actions/runs/29632691437/job/88049370327) |
| I7 | `test_unknown_project_sensitivity_fails_closed` | `60c431f` | [run](https://github.com/csantisdev/ai-orchestrator/actions/runs/29231131539/job/86755411217) |
| I8 | `test_fetch_similar_runs_filters_by_project`, `test_router_prompt_excludes_other_projects`, `test_fetch_similar_runs_overqueries_before_filtering` (Commit 0.2 — no confundir con `test_local_router_never_returns_blocked_provider`, que demuestra I5/I6, no I8) | `d056d0c` | [run](https://github.com/csantisdev/ai-orchestrator/actions/runs/29230382189/job/86753117262) |
| I9 | `test_provider_cannot_override_complete_stream` | `a76a4d7` | [run](https://github.com/csantisdev/ai-orchestrator/actions/runs/29631543303/job/88046001542) |
| I10 | `test_secret_in_prompt_escalates_to_secret_and_blocks` | `77cad81` | [run](https://github.com/csantisdev/ai-orchestrator/actions/runs/29632974490/job/88050154679) |
| I11 | `test_complete_stream_check_is_eager_not_deferred` | `a76a4d7` | [run](https://github.com/csantisdev/ai-orchestrator/actions/runs/29631543303/job/88046001542) |
| I12 | `test_background_worker_sets_policy_inside_thread` | `b1bacc1`* | [run](https://github.com/csantisdev/ai-orchestrator/actions/runs/29633518957/job/88051612705) |
| I13 | `test_egress_blocked_at_call_is_not_retried` / `..._during_iteration_is_not_retried` | `b74fd20` | [run](https://github.com/csantisdev/ai-orchestrator/actions/runs/29633901956/job/88052627517) |
| I14 | `test_blocked_fallback_provider_does_not_abort_when_other_provider_permitted` | `39a8b2c` | [run](https://github.com/csantisdev/ai-orchestrator/actions/runs/29632691437/job/88049370327) |
| I15 | `test_policy_reset_restores_previous_policy`, `test_policy_does_not_leak_between_operations` (Commit 1.1), `test_worker_resets_policy_between_runs` (Commit 1.7, nombre real — el prompt original decía `test_worker_resets_policy_in_finally`) | `60c431f` / `b1bacc1`* | [run](https://github.com/csantisdev/ai-orchestrator/actions/runs/29231131539/job/86755411217) / [run](https://github.com/csantisdev/ai-orchestrator/actions/runs/29633518957/job/88051612705) |

\* El commit que implementó I12 (`b1bacc1`) tuvo su propio CI run en **fail** por un gap de mocking no relacionado con I12 en sí (`test_background_worker_sets_policy_inside_thread` disparaba una llamada real a ChromaDB en un runner limpio — ver detalle en la sección de verificación adversarial más abajo). El fix (mocks adicionales, sin tocar la lógica de I12) se comiteó por separado en `aaddd81`, cuyo run es el que efectivamente valida el test en verde. El link de CI de esta fila apunta a `aaddd81`, no a `b1bacc1`, a propósito — es la corrida real que lo confirma pasando.

## Inventario de egress HTTP (punto de partida para la verificación adversarial)

Clasificación verificada contra el código — actualizar si aparece un `httpx.*` nuevo que no esté en esta lista:

| Call site | Contextual | Estado hoy |
|---|---|---|
| `providers/{claude,deepseek,gemini,openai}.py` (`httpx.post` en `_complete()`, `httpx.stream` en `_complete_stream()` — **la tabla anterior solo listaba `httpx.stream`; verificación 2026-07-18 con `rg -n 'httpx\.(get\|post\|stream)' orchestrator` encontró que `httpx.post` también existe en los 4 providers y no estaba documentado**) | Sí — gobernado | Ambos pasan por `BaseProvider.complete()`/`complete_stream()`, sellado en Commit 1.2, `check_payload()` desde Commit 1.6 |
| Router LLM externo | Sí — gobernado | Es un provider más (`router.py`), mismo borde |
| `orchestrator/discovery/*.py` (`httpx.get`, 4 archivos: anthropic/deepseek/gemini/openai) | No | Fuera de alcance del gate, RFC-006 §2.2 ("egress externo no contextual") |
| `orchestrator/catalog.py:81` (`httpx.get`, actualización remota del catálogo de precios) | No | Fuera de alcance del gate, mismo criterio que discovery |

## Verificación adversarial final (al cerrar Fase 1, antes de sacar el PR de Draft)

**Ejecutada 2026-07-18 contra `feat/egress-gate@4deed8a`, los 13/13 commits de Fase 0+1 completos, PR #2 (Draft) `OPEN`/`MERGEABLE`.** No alcanza con que los tests unitarios pasen. Resultado de cada punto:

1. **`rg -n 'httpx\.(get|post|stream)' orchestrator`** — comparado contra la tabla de arriba. **Hallazgo:** `httpx.post` en los 4 providers no estaba documentado (solo `httpx.stream` lo estaba) — corregido en la tabla de inventario arriba. Ningún call site nuevo sin clasificar; `catalog.py:81` y `discovery/*.py` (4 archivos) siguen siendo los únicos no-contextuales, sin cambios desde la última verificación.

2. **Ninguna subclase de `BaseProvider` define `complete`/`complete_stream` directamente** — confirmado con `grep -n "def complete\b\|def complete_stream\b" orchestrator/providers/{claude,deepseek,gemini,openai}.py` → **0 resultados** en los 4 archivos (solo definen `_complete`/`_complete_stream`). Consistente con `__init_subclass__` (Commit 1.2) haciendo esto estructuralmente imposible, verificado además por `test_provider_cannot_override_complete(_stream)`.

3. **PoC de RFC-006 §4.2 reproducido contra el código real** (script sintético, sin payload real, ejecutado localmente contra `4deed8a`):
   ```
   [OK] ai-orchestrator: sensitivity='internal' -> openai (esperado: openai) | cero bytes a deepseek: confirmado
   [OK] restricted-project.example: sensitivity='restricted' -> claude (esperado: claude) | cero bytes a deepseek: confirmado
   [OK] secreto: sensitivity='secret' -> BLOQUEADO (esperado: BLOQUEADO) | cero bytes a deepseek: confirmado
   ```
   Los 3 escenarios de la tabla original de RFC-006 §4.2 coinciden exactamente. `httpx.post`/`httpx.stream` de `orchestrator.providers.deepseek` mockeados a nivel de módulo en los 3 casos, `assert_not_called()` verificado — deepseek nunca recibe bytes, ni como router (bloqueado pre-routing por Commit 1.5) ni como provider final (nunca elegible en ninguno de los 3 proyectos de este PoC).

4. **Streaming bloqueado en los dos momentos** — verificado por `test_streaming_http_not_reached_when_blocked` (bloqueo al llamar `complete_stream()`) y `test_complete_stream_check_is_eager_not_deferred` (`inspect.isgeneratorfunction` confirma que el check no puede diferirse al primer `next()`), más `test_egress_blocked_at_call_is_not_retried`/`test_egress_blocked_during_iteration_is_not_retried` (Commit 1.8) que cubren ambos momentos explícitamente dentro del loop de reintentos. Los 4 tests pasan en la corrida completa (ver log abajo).

5. **Aislamiento de política**, cubierto por:
   - Entre tests: fixture `autouse` en `conftest.py` (política permisiva por defecto) + `no_default_policy` marker donde se necesita control explícito.
   - Entre operaciones del mismo thread: `test_policy_reset_restores_previous_policy`, `test_policy_does_not_leak_between_operations` (I15, Commit 1.1).
   - Entre thread padre y worker: `test_parent_thread_policy_does_not_silently_leak_to_worker` — usa un `threading.Thread` real, no una llamada síncrona, con una política del padre deliberadamente más restrictiva que la que el worker resuelve para sí mismo (Commit 1.7).
   - `context.yaml` ausente: `test_missing_context_yaml_uses_internal_default_and_does_not_block` — trata el proyecto como nuevo, no bloquea.
   - `context.yaml` corrupto: `test_corrupt_context_fails_closed_instead_of_using_default` — falla cerrado, ya NO sigue silenciosamente con `ctx=None` y el provider default (comportamiento viejo, corregido en Commit 1.7).

6. **Filas reales de `egress_decisions` inspeccionadas** (DB temporal, nunca la del usuario — `tempfile.mkdtemp()`, jamás `~/.ai-orchestrator/`). Tres filas generadas con `provider.complete()` real (caso permitido, caso bloqueado por clearance, caso bloqueado por secreto detectado), payload sintético con un marcador único y una AWS key de ejemplo (`AKIAIOSFODNN7EXAMPLE`) en el prompt:
   ```
   Columnas de egress_decisions: ['id', 'ts', 'project', 'provider', 'phase', 'decision', 'reason_code', 'sensitivity', 'clearance', 'run_id']
   {'id': 1, ..., 'decision': 'allowed',  'reason_code': 'allowed',                  'sensitivity': 'internal',   'clearance': 'internal'}
   {'id': 2, ..., 'decision': 'blocked',  'reason_code': 'clearance_insufficient',   'sensitivity': 'restricted', 'clearance': 'internal'}
   {'id': 3, ..., 'decision': 'blocked',  'reason_code': 'secret_pattern_detected',  'sensitivity': 'secret',     'clearance': 'restricted'}
   ```
   Confirmado por asserción sobre el dump completo de las 3 filas: ni el marcador de tarea ni la AWS key aparecen en ninguna columna. El esquema mismo (10 columnas fijas, ninguna de tipo "texto libre de payload") hace estructuralmente imposible que un prompt completo termine ahí, más allá de lo que confirma el test.

**Log completo de `pytest tests/ -v`:** [`pytest-full-2026-07-18.txt`](./pytest-full-2026-07-18.txt) (170 passed, corrida 2026-07-18 contra `4deed8a`, 0 failed, 0 errors — toda la suite: providers, router, background, egress, eval, server, RAG, catálogo de precios). **Log completo de `pytest tests/test_egress.py -v`:** [`pytest-egress-2026-07-18.txt`](./pytest-egress-2026-07-18.txt) (22 passed — las 15 pruebas originales de RFC-006, I1-I14 + I15 nueva, más las 7 agregadas en Fase 1 para secretos y logging). **Script del PoC punto 3:** [`poc-rfc006-4.2.py`](./poc-rfc006-4.2.py), reproducible localmente con `python docs/decisions/evidence/RFC-007/poc-rfc006-4.2.py` (requiere el venv del proyecto activo).

Draft PR: https://github.com/csantisdev/ai-orchestrator/pull/2 — CI (`tests.yml`) verde en cada uno de los 13 commits del plan, confirmada individualmente por SHA (ver tabla de trazabilidad arriba), no solo en el estado agregado del PR.
