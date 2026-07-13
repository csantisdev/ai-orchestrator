# Evidencia de RFC-006

RFC-006 (`../../rfcs/RFC-006-provider-safe-routing.md`) afirma resultados medidos localmente: `pytest tests/test_egress.py` → 15 passed, `pytest tests/` → 126 passed / 1 failed pre-existente, PoC de cero bytes a DeepSeek en un proyecto `restricted`. Ese patch (`egress-gate.patch`, +512/−28) fue efímero: se aplicó, se probó y se descartó sin publicar rama ni guardar el patch ni el script `repro.py` en este repo. No hay artefactos que archivar todavía.

Cuando RFC-007 Parte II (Fase 0-1) se ejecute contra este checkout, esta carpeta debe recibir:

- Log completo de `pytest tests/ -v` antes y después de cada commit de Fase 1.
- Log de `pytest tests/test_egress.py -v` una vez completa la Fase 1.
- El resultado del PoC de RFC-006 §4.2 (`restricted-project.example` restricted → deepseek bloqueado → claude permitido) reproducido contra el código real, no contra el patch viejo.
- El link al Draft PR / run de CI (`tests.yml`, RFC-007 §11.0-§11.1 Commit 0.1) que confirma lo anterior en un entorno limpio, no solo local.

No pegar prompts, tareas ni contexto real de proyectos en esta carpeta — es evidencia pública del repo, y las mismas reglas de "el log registra la decisión, nunca el payload" (RFC-006 §6.2) aplican acá.

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
| I8 | `test_local_router_never_returns_blocked_provider` (router) / test de `_fetch_similar_runs` (Fase 0) | | |
| I9 | `test_provider_cannot_override_complete_stream` | | |
| I10 | `test_secret_in_prompt_escalates_to_secret_and_blocks` | | |
| I11 | `test_complete_stream_check_is_eager_not_deferred` | | |
| I12 | `test_background_worker_sets_policy_inside_thread` | | |
| I13 | `test_egress_blocked_at_call_is_not_retried` / `..._during_iteration_is_not_retried` | | |
| I14 | `test_blocked_fallback_provider_does_not_abort_when_other_provider_permitted` | | |
| I15 | (fixture autouse + reset por `Token` en `conftest.py`, sin test dedicado propio — verificar ausencia de fuga entre tests) | | |

## Verificación adversarial final (al cerrar Fase 1, antes de sacar el PR de Draft)

No alcanza con que los tests unitarios pasen. Antes de pedir revisión:

1. `grep -rn "httpx\.\(get\|post\|stream\)" orchestrator/` — clasificar cada resultado como contextual (debe pasar por `BaseProvider`) o no contextual (`model_discovery`, ya fuera de alcance por RFC-006 §2.2).
2. Confirmar que ninguna subclase de `BaseProvider` define `complete`/`complete_stream` directamente (debería ser imposible por `__init_subclass__`, pero verificar leyendo los 4 archivos).
3. Reproducir el PoC de RFC-006 §4.2 contra el código real: proyecto `restricted`, router externo bloqueado, provider final permitido, **cero llamadas HTTP** al provider bloqueado (mock a nivel de módulo, `assert_not_called()`).
4. Streaming bloqueado en los dos momentos: al llamar `complete_stream()` y durante `next()` del generador.
5. Aislamiento de política: entre tests, entre operaciones del mismo thread, entre thread padre y worker, con `context.yaml` ausente, con `context.yaml` corrupto.
6. Inspeccionar filas reales de `egress_decisions` y confirmar que ninguna contiene prompt, system prompt, texto de tarea, chunks RAG, secretos ni headers — solo los campos permitidos (RFC-006 §6.2).
