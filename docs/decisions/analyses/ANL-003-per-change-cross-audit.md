---
id: ANL-003
type: analysis
title: Auditoria cruzada por cambio en dos rondas
status: active
created: 2026-09-26
updated: 2026-09-26
related: [ANL-002]
---

# ANL-003 - Auditoria cruzada por cambio en dos rondas

## Objetivo

Describir la práctica que se usa en cada cambio no trivial de
`ai-orchestrator` desde el PR #18: un agente implementa, otro distinto audita en
modo solo lectura, se corrige y se audita de nuevo lo corregido antes del merge.

No reemplaza a ANL-002. ANL-002 es una auditoría puntual del repositorio
completo sobre un SHA fijo, con pasada ciega y refutación; esta práctica se
aplica a un diff concreto dentro de su PR.

## Roles

| Rol | Quién | Restricción |
|---|---|---|
| Implementador | Codex (delegado en un worktree) o Claude | Trabaja en una rama desde `production`, nunca en `production`. |
| Auditor de ronda 1 y 2 | Un agente distinto del implementador: Claude, Codex o Copilot CLI | Solo lectura; no modifica archivos ni ejecuta ANL-002. |
| Revisor del PR | Copilot (`copilot-pull-request-reviewer`), automático | Sus hilos deben quedar resueltos antes del merge. |
| Responsable | Usuario | Autoriza el merge. |

## Flujo

1. El trabajo se registra en el orquestador como un contexto con un paso por
   unidad de implementación y un paso final de auditoría y cierre. La
   especificación de cada paso vive en su descripción, no en el chat.
2. El implementador cierra sus pasos con `advance_step` y notas que citan
   commits y tests.
3. **Ronda 1:** el auditor revisa `git diff origin/production...<rama>` contra
   la especificación y el código real. Cada hallazgo cita archivo:línea y una
   reproducción mínima.
4. Cada hallazgo aceptado se corrige, con un test de regresión cuando aplica.
5. **Ronda 2:** el auditor revisa solo lo corregido y confirma que las
   correcciones no introducen defectos nuevos. Si aparecen, se repite el ciclo.
6. PR a `production`: CI verde, rama al día y todos los hilos resueltos. Antes
   de mergear se espera a que exista la review de Copilot (tarda unos minutos) y
   se leen sus hilos y el cuerpo de la review; el ruleset no bloquea hilos que
   todavía no existen.

## Invocación de auditores en solo lectura

- Codex: `codex exec --sandbox read-only --cd <repo> -o <salida> - < <prompt>`.
- Copilot CLI: modo no interactivo con `--deny-tool=write`, prompt por stdin.
- El prompt fija la rama o SHA auditado, pide la tabla de hallazgos de ANL-002
  y aclara que no se debe ejecutar el protocolo completo de ANL-002.

## Delegación a Codex en un worktree

En Windows, `codex exec --sandbox workspace-write` sobre un git worktree no
puede commitear (la metadata del worktree queda fuera del sandbox) y deja ACL
que bloquean escrituras posteriores. El agente que integra revisa el diff, hace
el commit y restablece permisos con `icacls . /reset /T /Q` antes de editar.
Para cambios de pocas líneas, implementar directo evita ese costo; la auditoría
de dos rondas se mantiene igual.

## Registro

El registro público es el PR: commits, hilos de revisión y su resolución. Las
notas de los pasos del orquestador guardan el detalle operativo en la base
local, que no se versiona. No se guardan payloads, prompts ni datos de proyectos
reales.

## Criterio de cierre

- Ronda 2 sin hallazgos abiertos.
- `python -m pytest tests/ -v` completo en verde, y los validadores que
  correspondan (`validate_decision_docs.py`, `validate_pricing_catalog.py`).
- CI verde, review de Copilot recibida y todos sus hilos resueltos.
- Merge autorizado por el responsable.
