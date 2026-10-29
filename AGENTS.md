# AGENTS.md

Instrucciones para agentes de código (Claude Code, Codex, Copilot, Antigravity) que trabajan en este repositorio.

## Identidad en el orquestador

- Alias del proyecto: `ai-orchestrator`.
- Al iniciar una tarea no trivial, llamá `get_context(project="ai-orchestrator")` en el servidor MCP `ai-orchestrator`.
- Si `workflow_state.warnings` no está vacío (varios contextos activos, ningún paso `in_progress`), avisá al usuario antes de trabajar.
- Trabajá sobre el paso `in_progress` de `list_steps`. Usá `start_step` para activar un pending, `reset_step` para devolver trabajo abandonado a pending y `skip_step` solo para trabajo descartado o reemplazado. Usá `confirm_alignment` antes de cambios significativos y `advance_step` solo cuando la implementación esté hecha y verificada.
- Si una llamada MCP se deniega, reportá `reason_code` y `hint` y detenete; no sigas sin tracking.
- Creá un contexto nuevo solo si no existe uno activo adecuado. No saltes ni completes pasos solo para limpiar el tracking.

## Configuración MCP

El servidor se lanza con `python -u -m orchestrator.mcp` desde la raíz del repo. La autorización es server-side y fail-closed:

- `ORCHESTRATOR_MCP_PROFILE`: `readonly` (default si falta o es inválido), `workflow_operator`, etc. Ver `orchestrator/mcp_governance.py`.
- `ORCHESTRATOR_MCP_PROJECTS`: alias permitidos, separados por coma. Vacío = toda tool de proyecto denegada.
- `ORCHESTRATOR_MCP_CLIENT_SURFACE` y `ORCHESTRATOR_MCP_TRANSPORT`: identidad declarada del cliente.

Plantillas: `.mcp.json.example` y `.codex/config.toml.example`. `ai-orchestrator fix --mcp-profile/--mcp-projects` escribe el bloque `env` y `ai-orchestrator doctor` lo verifica. Los archivos reales (`.mcp.json`, `.codex/config.toml`, `.vscode/mcp.json`) son locales y están en `.gitignore`.

## Flujo de ramas y PRs

- Rama principal: `production`. Nunca se commitea directo: todo entra por PR.
- El ruleset exige CI verde, rama al día con `production` y todos los hilos de revisión resueltos. No hay review automático de Copilot: consume créditos del plan del dueño y se quitó del ruleset. Pedilo a mano (`gh pr edit <n> --add-reviewer "@copilot"`) solo en cambios de seguridad o si el dueño lo indica; si se pidió, leé el cuerpo completo de cada review (los hallazgos de "Previously missed" no crean hilos) antes de mergear.
- Commits en inglés con prefijo convencional: `feat:`, `fix:`, `docs:` (scope opcional, p. ej. `fix(ingest):`).
- Cambios no triviales: auditoría cruzada en dos rondas según `docs/decisions/analyses/ANL-003-per-change-cross-audit.md` (ANL-002 es la auditoría puntual del repositorio completo). Quién audita y con qué está en "Política de modelos".

## Política de modelos

El auditor siempre es distinto del implementador. La invocación completa de cada auditor está en ANL-003.

| Rol | Herramienta y configuración | Cuándo |
|---|---|---|
| Implementación y arquitectura | Claude Code | Por defecto |
| Auditor principal (rondas 1 y 2) | `codex exec --sandbox read-only -c model_reasoning_effort=high` | Todo cambio no trivial |
| Implementación delegada | `codex exec --sandbox workspace-write -c model_reasoning_effort=medium` | Cuando se delega; entonces audita Claude |
| Segundo auditor | Antigravity CLI: `agy --mode plan --model gemini-3.8-flash-high` | Ronda 1 de RFCs y de cambios de diseño o de seguridad; las dos rondas si reemplaza a Codex no disponible |
| Copilot CLI y review de Copilot en PR | `copilot` | Solo en cambios de seguridad o a pedido: consume créditos del plan del dueño |

- El implementador (Claude, o Codex cuando se le delega) registra su avance en el tracking; los auditores trabajan en solo lectura y nunca llaman tools MCP que escriban.
- Fijá siempre el modelo del segundo auditor: Antigravity también ofrece modelos de Claude y GPT, y sin `--model` dejaría de ser un auditor independiente. Gemini CLI ya no se usa: no admite la autenticación disponible.
- Si los auditores discrepan, el implementador verifica cada hallazgo contra el código; lo que siga en disputa lo decide el dueño.
- El router por API (`ai-orchestrator run`, con `preferred_models` y `keyword_hints` de `context.yaml`) no forma parte de este flujo y está inactivo desde 2026-06. Si se reactiva, actualizá antes sus modelos contra `docs/pricing/models.json`.

## Verificación antes de abrir un PR

```bash
python -m pip install -e ".[all]"
python -m pytest tests/ -v
python scripts/validate_decision_docs.py        # si tocaste docs/decisions/
python scripts/validate_pricing_catalog.py      # si tocaste docs/pricing/ o orchestrator/costs.py
```

## Documentos de decisión

`docs/decisions/` tiene reglas propias en `docs/decisions/README.md`: taxonomía (`rfcs/`, `adrs/`, `analyses/`, `evidence/`, `support/`, `archive/`), front matter obligatorio en documentos nuevos y regla de inmutabilidad (el contenido normativo no se reescribe; la metadata operativa sí se mantiene al día con el código).

## Privacidad (repositorio público)

- Nunca incluyas nombre, dominio, endpoint, descripción operativa ni combinación de rasgos que identifique un proyecto o cliente real, ni siquiera como ejemplo o en contenido pegado de otra sesión. Usá datos sintéticos (`mi-proyecto`, `restricted-project.example`). Detalle en "Regla de anonimización" de `docs/decisions/README.md`.
- No versiones `config.yaml`, `index.yaml`, `agents.yaml`, `.env`, bases `*.db` ni logs: contienen API keys, rutas locales o datos de runs.
