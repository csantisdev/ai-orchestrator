# Contexto para Codex — ai-orchestrator

> Archivo de referencia para derivar trabajo de documentación o extensiones al agente Codex.
> Última actualización: 2026-06-26.

---

## Estado actual del proyecto

- **Versión:** v0.4.0
- **MCP protocol:** `2025-06-18` (soporta también `2024-11-05`, `2025-03-26`)
- **Tools MCP:** 11 (`get_context`, `list_steps`, `create_context`, `add_step`, `update_context`, `update_step`, `advance_step`, `skip_step`, `confirm_alignment`, `record_tool_call`, `import_agent_context`)
- **Proveedores:** Claude (Anthropic), OpenAI, DeepSeek
- **Base de datos:** SQLite WAL en `~/.ai-orchestrator/runs.db`
- **Índice vectorial:** ChromaDB en `~/.ai-orchestrator/chroma/` — colecciones `docs` y `responses`

---

## Archivos fuente de verdad

| Archivo | Contenido autoritativo |
|---|---|
| `orchestrator/cli.py` | Todos los comandos CLI y endpoints HTTP del servidor dashboard |
| `orchestrator/mcp.py` | Definición de tools MCP (`TOOLS` list), versiones de protocolo (`SUPPORTED_PROTOCOL_VERSIONS`), handlers |
| `orchestrator/rag.py` | Constantes RAG (`_CHUNK_SIZE`, `_DISTANCE_THRESHOLD`, etc.), funciones de indexación y recuperación |
| `orchestrator/costs.py` | Tabla de precios por modelo (`DEFAULT_PRICING`), función `calculate_cost` |
| `orchestrator/background.py` | Flujo completo de un run: Router → RAG → API → DB → SSE → index_response |
| `orchestrator/codex_watcher.py` | Importador de sesiones Codex CLI desde `~/.codex/state_N.sqlite` |
| `orchestrator/db.py` | Schema SQLite, migraciones, funciones de acceso |

---

## Cambios recientes (2026-06-26)

### Correcciones de bugs
- **SyntaxError JS** (commit `b392a95`): `\'` dentro de triple-quoted string Python se consumía, generando strings adyacentes `''` en los onclick de renombrar proyecto. Fix: usar `\\'` para emitir `\'` en JS.
- **Activity bar re-apertura** (commit post `b392a95`): Añadido flag `_actUserClosed` — el panel de actividad ya no se reabre automáticamente si el usuario lo colapsa manualmente.
- **Formato moneda USD** (commit `ca5139a`): Todos los montos USD ahora usan locale chileno (`1.234,5678 USD`) con helper centralizado `_fmtUsd(v, dec)` en JS y `_fmt_cost()` en Python. El símbolo `$` era del peso chileno y no debía usarse para USD.

### Mejoras RAG y ChromaDB
- **Threshold L2** (commit `9c65447`): `1.4` → `0.9` (equivale a cosine_sim ≥ 0.60). Antes era tan permisivo (cosine_sim ≈ 0.02) que prácticamente todo pasaba el filtro.
- **Guard `count > 0` eliminado**: En `/run-fix` y `doctor --index`, se verificaba si el proyecto ya tenía chunks para no re-indexar. Esto dejaba índices desactualizados tras cambios de código. El upsert por ID determinístico (`proyecto::ruta::chunk_idx`) garantiza idempotencia — re-indexar siempre es seguro.
- **Colección `runs` eliminada de `chroma_stats`**: Era dead code — nunca se escribía en ella.

### Nuevo módulo
- **`codex_watcher.py`**: Importa sesiones de OpenAI Codex CLI desde `~/.codex/state_N.sqlite`. Lee threads, extrae respuestas del JSONL de rollout, calcula costos, inserta en `runs` e indexa en RAG. Accesible vía `ai-orchestrator sync-codex`.

---

## Decisiones de diseño documentadas

| Decisión | Razón |
|---|---|
| Upsert idempotente por ID determinístico en ChromaDB | Permite re-indexar sin acumular duplicados. El ID `proyecto::ruta::chunk_idx` identifica cada chunk unívocamente. |
| Threshold L2=0.9 (no configurable desde CLI) | Balance entre precisión y recall. Con pocos documentos indexados, un threshold muy bajo dejaría el RAG vacío. Ajustable en `rag.py:_DISTANCE_THRESHOLD`. |
| MCP sobre stdio (no HTTP) | Protocolo estándar MCP para compatibilidad nativa con Claude Desktop, Claude Code y Codex. ChatGPT requiere HTTP/OpenAPI — protocolo distinto. |
| Panel actividad respeta colapso manual | `_actUserClosed=true` al colapsar, `false` al abrir manualmente. Las trazas entrantes no re-abren el panel si el usuario lo cerró. |
| Formato USD en locale chileno | En Chile, `.` es separador de miles y `,` decimal. El `$` es el símbolo del peso chileno — usarlo para USD es confuso. |
| Colección `responses` separada de `docs` | Permite recuperar respuestas históricas sin contaminar el índice de documentación. Distintos pesos semánticos. |

---

## Tareas pendientes identificadas

- [ ] Verificar que `/docs`, `/security` en el servidor HTTP tengan contenido útil (actualmente son endpoints pero los archivos HTML pueden estar desactualizados)
- [ ] Los paths en `mcp.html` (ej. `C:\ruta\ai-orchestrator`) son específicos de Windows — considerar nota para usuarios Linux/macOS
- [ ] `docs/api-keys.md` y `docs/context-schema.md` son referenciados en `README.md` pero pueden no existir — verificar o eliminar referencias
- [ ] Considerar exponer `_DISTANCE_THRESHOLD` como parámetro configurable en `config.yaml` sin requerir editar `rag.py`
- [ ] `codex_watcher.py`: el mapeo `cwd → alias` usa prefix matching — puede fallar si múltiples proyectos comparten un path padre

---

## Estructura de comandos CLI

```
ai-orchestrator
├── add <alias> --path <ruta> [--stack] [--description] [--default-provider]
├── list
├── remove <alias>
├── rename <old> <new>
├── run --project <alias> --task <texto> [--model] [--research] [--task-file]
├── serve [--port N] [--project] [--open/--no-open]
├── index-docs <alias> [--exclude <carpetas>] [--save]
├── history [--project] [--last N]
├── create-context <alias> <title> [--description] [--step <title:provider>]...
├── list-contexts [--project]
├── import-context <alias> [--agent] [--model] [--task] [--response] [--no-index]
├── clear-imports <alias> [--provider] [--confirm]
├── sync-cc [--quiet]
├── sync-codex [--quiet]
├── sync-git [--quiet]
├── doctor [--project] [--verbose]
└── fix [--global-mcp] [--sync] [--index] [--all]
```

---

## Flujo de un run (background.py)

```
submit_run(project, task, config, model=None)
  │
  ├─ insert_run(status='pending') → run_id
  ├─ BUS.publish("run_started")
  └─ Thread → _worker()
       │
       ├─ load_context(project_path)          # context.yaml
       ├─ router.decide_provider(task, ctx)   # DeepSeek Flash → {provider, reason}
       ├─ retrieve_docs(task, project)         # ChromaDB docs, n=4, L2<0.9
       ├─ retrieve_responses(task, project)    # ChromaDB responses, n=2, L2<0.9
       ├─ build_context_block(docs, responses) # → system_prompt
       ├─ provider.complete(task, system)      # API call
       ├─ calculate_cost(result, pricing)      # tokens × price/1M
       ├─ update_run(result, cost, duration)
       ├─ persist_context_hits(run_id, chunks)
       ├─ index_response(run_id, project, task, response)  # → ChromaDB responses
       └─ BUS.publish("run_done" | "run_failed")
```
