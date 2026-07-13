---
type: evidence
supports: RFC-007
---

# Evidencia de RFC-007

Esta carpeta guarda la evidencia de ejecutar `docs/decisions/rfcs/RFC-007-ai-control-plane.md` Parte II (los 13 commits de Fase 0 + Fase 1) contra código real. Distinto de `../RFC-006/README.md`, que documenta el diseño original y su patch efímero (histórico, nunca publicado) — I1-I14 se **diseñaron** en RFC-006, pero se **implementan y verifican acá**, junto con I15 (invariante nueva, exclusiva de RFC-007).

Cuando Fase 0-1 se ejecute, esta carpeta debe recibir:

- Log completo de `pytest tests/ -v` antes y después de cada commit de Fase 1.
- Log de `pytest tests/test_egress.py -v` una vez completa la Fase 1.
- El resultado del PoC de RFC-006 §4.2 (`restricted-project.example` restricted → deepseek bloqueado → claude permitido) reproducido contra el código real, no contra el patch viejo.
- El link al Draft PR y a cada run de CI (`tests.yml`, RFC-007 §11.0-§11.1 Commit 0.1) que confirma lo anterior en un entorno limpio, no solo local.

No pegar prompts, tareas ni contexto real de proyectos en esta carpeta — mismas reglas que en `evidence/RFC-006/`: el log registra la decisión, nunca el payload (RFC-006 §6.2).

## Tabla de trazabilidad

Completar una fila por invariante a medida que Fase 1 avanza — no antes. `Commit` es el SHA real que la implementó, `CI` el link al run que la validó en el Draft PR.

| Invariante | Test | Commit | CI |
|---|---|---|---|
| I1 | `test_no_policy_blocks_provider_complete` | | |
| I2 | `test_restricted_project_blocks_public_provider` | | |
| I3 | `test_streaming_http_not_reached_when_blocked` | | |
| I4 | `test_provider_cannot_override_complete` | | |
| I5 | `test_external_router_blocked_uses_local_router_not_fixed_fallback` | | |
| I6 | `test_no_fixed_claude_fallback_when_router_blocked` | | |
| I7 | `test_unknown_project_sensitivity_fails_closed` | | |
| I8 | `test_fetch_similar_runs_filters_by_project`, `test_router_prompt_excludes_other_projects`, `test_fetch_similar_runs_overqueries_before_filtering` (Commit 0.2 — no confundir con `test_local_router_never_returns_blocked_provider`, que demuestra I5/I6, no I8) | | |
| I9 | `test_provider_cannot_override_complete_stream` | | |
| I10 | `test_secret_in_prompt_escalates_to_secret_and_blocks` | | |
| I11 | `test_complete_stream_check_is_eager_not_deferred` | | |
| I12 | `test_background_worker_sets_policy_inside_thread` | | |
| I13 | `test_egress_blocked_at_call_is_not_retried` / `..._during_iteration_is_not_retried` | | |
| I14 | `test_blocked_fallback_provider_does_not_abort_when_other_provider_permitted` | | |
| I15 | `test_policy_reset_restores_previous_policy`, `test_policy_does_not_leak_between_operations` (Commit 1.1), `test_worker_resets_policy_in_finally` (Commit 1.7) | | |

## Inventario de egress HTTP (punto de partida para la verificación adversarial)

Clasificación verificada contra el código — actualizar si aparece un `httpx.*` nuevo que no esté en esta lista:

| Call site | Contextual | Estado hoy |
|---|---|---|
| `providers/{claude,deepseek,gemini,openai}.py` (`httpx.stream`) | Sí — gobernado | Pasa por `BaseProvider`, sellado en Commit 1.2 |
| Router LLM externo | Sí — gobernado | Es un provider más (`router.py`), mismo borde |
| `orchestrator/discovery/*.py` (`httpx.get`) | No | Fuera de alcance del gate, RFC-006 §2.2 ("egress externo no contextual") |
| `orchestrator/catalog.py:81` (`httpx.get`, actualización remota del catálogo de precios) | No | Fuera de alcance del gate, mismo criterio que discovery — **no estaba clasificado explícitamente en RFC-006/RFC-007 hasta esta verificación** |

## Verificación adversarial final (al cerrar Fase 1, antes de sacar el PR de Draft)

No alcanza con que los tests unitarios pasen. Antes de pedir revisión:

1. `rg -n 'httpx\.(get|post|stream)' orchestrator` — comparar contra la tabla de arriba; cualquier call site nuevo que no esté ahí es un hallazgo a clasificar, no a ignorar.
2. Confirmar que ninguna subclase de `BaseProvider` define `complete`/`complete_stream` directamente (debería ser imposible por `__init_subclass__`, pero verificar leyendo los 4 archivos).
3. Reproducir el PoC de RFC-006 §4.2 contra el código real: proyecto `restricted`, router externo bloqueado, provider final permitido, **cero llamadas HTTP** al provider bloqueado (mock a nivel de módulo, `assert_not_called()`).
4. Streaming bloqueado en los dos momentos: al llamar `complete_stream()` y durante `next()` del generador.
5. Aislamiento de política: entre tests, entre operaciones del mismo thread, entre thread padre y worker, con `context.yaml` ausente, con `context.yaml` corrupto.
6. Inspeccionar filas reales de `egress_decisions` y confirmar que ninguna contiene prompt, system prompt, texto de tarea, chunks RAG, secretos ni headers — solo los campos permitidos (RFC-006 §6.2).
