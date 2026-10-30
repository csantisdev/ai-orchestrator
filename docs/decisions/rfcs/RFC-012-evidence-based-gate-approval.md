---
id: RFC-012
type: rfc
title: Aprobación de gates con evidencia observada del flujo
status: draft
created: 2026-10-30
updated: 2026-10-30
supersedes: []
superseded_by: null
related: [RFC-006, RFC-008, RFC-009, RFC-010, RFC-011]
---

# RFC-012 — Aprobación de gates con evidencia observada del flujo

**Estado:** Draft  
**Versión:** 0.4  
**Fecha:** 2026-10-30  
**Repo de referencia:** `csantisdev/ai-orchestrator@production` = `5e5d1e79d9e9bf5fefb28ac87a3f47db99d10fa3` (verificado 2026-10-30)  
**Relación con la serie:** RFC-011 definió qué es un release gate, dónde bloquea y el contrato mínimo de una aprobación (§3.4), y dejó a este RFC **cómo** se aprueba. RFC-012 define la evidencia que cuenta, quién la produce, los gates de entrada y de salida de un paso, los modos `auto`, `manual` y `auto_then_manual`, y extiende el contrato de aprobación. Usa los comandos y trabajos de RFC-010, las categorías de RFC-008, el modelo de amenazas de RFC-009 y el Egress Gate de RFC-006. Las enmiendas que propone a documentos aceptados están en §3.9.

*Todo ejemplo, PoC o fixture en este documento usa datos sintéticos (`mi-backend`, `tests/test_invoice_rounding.py`). Ver "Regla de anonimización" en `../README.md`.*

---

## Changelog

| Área | v0.1 | v0.2 | Motivo |
|---|---|---|---|
| `runs.verification_result` (§1) | "Nadie lo completa" | Etiqueta declarada desde el dashboard (`/evaluate-run`), vacía en la práctica | Codex, ronda 1: `server.py:1056`, `legacy_routes.py:72` |
| Vigencia de salida (§3.5) | `spec_hash` + `head_sha`, sin mirar el repositorio al consumir | Al emitir y al completar se verifica que la ruta confirmada esté en `head_sha` con árbol limpio, o que un `pr_state` aprobado fije lo entregado; carrera residual con git declarada | Se podía recolectar en A, mover a B y completar con la aprobación de A (Codex) |
| `skip_step` y cierre de contexto (§3.5) | `skip_step` permitido sobre un paso con salida | Saltar un paso con gate, o cerrar un contexto con pasos con gate abiertos, solo desde la UI (`skip_gated_step`, `close_context`) | `skip_step` activa el siguiente y puede cerrar el contexto (`mcp.py:680-704`); `update_context` cierra con pasos abiertos (`mcp.py:756`) (Codex) |
| E13 (§4) | "Solo `ci_checks`, `pr_state` y `audit` hacen red" | Garantía limitada al evaluador; un `command` puede hacer red y el RFC no lo impide | `argv` sin shell no implica sin red (Codex) |
| `auto_then_manual` (§3.6) | `auto_passed` sin modelo | Tabla `gate_evaluations` separada de `gate_approvals`; la confirmación revalida toda la evidencia | `status` de RFC-011 solo admite `valid` e `invalidated` (Codex) |
| Invalidación (§3.5, E7) | "En la misma transacción" para todo cambio | Cambios en SQLite (paso, contexto, proyecto): en su transacción; cambios en `context.yaml`: al evaluar y al transicionar, dentro de esa transacción; `context_id` en el contrato | Un archivo no cambia dentro de una transacción SQLite (Codex) |
| Enmiendas (§3.9) | Forma de `release_gates` "ilustrativa" | Enmiendas explícitas a RFC-011 §3.1 y §3.4 y a RFC-008, registradas al aceptar | Cambia un esquema ya aceptado (Codex) |
| Recolección por CLI (§3.8) | `ai-orchestrator evidence collect` | Solo por el comando `collect_evidence` de RFC-010; la CLI queda fuera (P7) | La CLI llama a las funciones de dominio sin el protocolo de comandos (`cli.py:595`, `:607`) (Codex) |
| Detalle (§3.2-§3.7, E1-E4, E9) | — | Árbol limpio definido, FK de `request_id`, E4 con un solo SHA igual al de la aprobación, tabla de confirmaciones de política con su arranque, objeto que certifican CI y PR | Sugerencias de Codex |
| §2 | Viñetas | Tabla de la plantilla | Forma |
| Política sin confirmar (v0.3, §3.6, E9, E16) | Solo suspendía `auto` | Ninguna transición de un paso con ese gate, en ningún modo; `steps.gate` de un paso abierto solo cambia desde la UI | Quitar `exit` del `context.yaml` con un paso en curso eludía el gate de salida (Codex, ronda 2) |
| `target` de `ci_checks` (v0.3, §3.3, §3.4, E4) | `merge_result` solo en prosa | Valores cerrados `head` y `merge_result`, columna `subject_sha`, dependencia obligatoria de un `pr_state` en la misma fase | E4 no era implementable (Codex, ronda 2) |
| Gate congelado al activar (v0.4, §3.5, E16) | `steps.gate` de un paso abierto cambiaba desde la UI; una política confirmada sin `exit` liberaba un paso en curso | Al activar se fija `steps.gate_policy_hash`; un paso `in_progress` solo se completa contra esa política, en todas las superficies; una política nueva rige recién tras `reset_step` o `skip_gated_step` | Codex, confirmación de la ronda 2 |
| Selección por `base_sha` (v0.4, §3.6) | Sin `base_sha` | El predicado exige el `base_sha` actual del paso | Evidencia de `diff_scope` contra otra base (Codex) |
| Selección de evidencia y archivos ignorados (v0.3, §3.2, §3.6) | Implícitos | Predicado de selección explícito; las políticas no deben depender de rutas ignoradas | Sugerencias de Codex, ronda 2 |

---

## 0. Resumen ejecutivo

Un gate se aprueba solo con **evidencia observada**: un resultado que el orquestador obtuvo ejecutando o consultando algo él mismo, que registró él mismo y que lleva su procedencia (qué se ejecutó, sobre qué commit, cuándo y con qué definición). Lo que un agente declara (notas, alineamientos, `record_tool_call`, un resumen de "los tests pasaron") nunca aprueba nada.

- Un paso puede tener un **gate de entrada** (¿hace falta este trabajo?, antes de `in_progress`; es el gate de RFC-011) y un **gate de salida** (¿la respuesta es satisfactoria?, antes de `completed`; nuevo en este RFC).
- Cada gate declara **chequeos** en `release_gates` del `context.yaml`. Cada chequeo usa un **recolector** de un catálogo cerrado definido en el código: ejecutar un comando, consultar el CI, comparar el diff con las rutas protegidas, verificar el paso previo.
- Los **modos** deciden quién emite la aprobación una vez que todos los chequeos requeridos tienen evidencia aprobatoria: el evaluador (`auto`), una confirmación desde la UI local (`manual`) o ambos en ese orden (`auto_then_manual`). Ningún modo aprueba con un chequeo requerido fallido, faltante o no concluyente.

**Qué NO afirma este RFC:**
- Que la aprobación manual pruebe que la registró una persona: por RFC-009 §0 y la decisión P1 de RFC-011, prueba que pasó por la UI local.
- Que defienda contra un proceso local que escribe en SQLite o reemplaza binarios: eso está fuera del modelo de amenazas de RFC-009.
- Que un test verde pruebe que el cambio es correcto: prueba que ese comando, sobre ese commit, terminó con el código esperado. Qué tan buenos son los chequeos lo decide quien escribe la política.
- Que el veredicto de un auditor LLM sea evidencia empírica del cambio: es evidencia observada de que la auditoría corrió y de lo que dijo (§3.3, P2).

---

## 1. El problema

El dueño pidió (2026-10-29, ctx #148) que la aprobación de un gate, manual o automática, se base en "evidencia empírica dentro del flujo de contexto" y no en "análisis volátil". Hoy el tracking no tiene evidencia de ese tipo. Medido sobre la base local el 2026-10-30, en solo lectura:

| Fuente | Filas | Quién la produce | Clase |
|---|---|---|---|
| `steps.notes` | 647 pasos con notas de 692 | El agente, con texto libre | Declarada |
| `alignments` | 289 | El agente, vía `confirm_alignment` | Declarada |
| `tool_calls` | 29 | El agente, vía `record_tool_call` | Declarada |
| `runs.verification_result` | 0 de 2233 runs con valor | Una persona o un proceso, con `POST /evaluate-run` del dashboard (`server.py:1056`) | Declarada |
| `runs` con `provider = 'git'` | 1421 | `git_scanner` importa commits | Observada (qué se commiteó, no si funciona) |
| `mcp_invocations` | 1751 desde 2026-09-25 | El servidor MCP | Observada (qué se llamó, no el resultado del trabajo) |
| `ui_commands`, `jobs` | 0 | Comandos de RFC-010 | Observada, todavía sin uso |

Consecuencias:

1. **Nada observado dice si el trabajo de un paso funciona.** Los tests, el CI y las auditorías corren fuera del orquestador; lo único que llega al tracking es lo que el agente escribe en las notas.
2. **Ninguna transición exige nada.** `_tool_advance_step` (`orchestrator/mcp.py:862`) marca `completed` y activa el siguiente con solo el `step_id`; `_tool_skip_step` (`mcp.py:662`) hace lo mismo con `skipped` y puede cerrar el contexto (`mcp.py:704`); `update_context` cierra un contexto con pasos abiertos (`mcp.py:756`). La CLI (`cli.py:595`, `:607`) llama a las mismas funciones.
3. **`steps.version` no sirve para atar evidencia de salida.** El trigger `trg_steps_version` (`orchestrator/migrate.py:229`) sube la versión con cualquier `UPDATE`, incluido agregar notas o el propio cambio de estado; atar la evidencia de salida a la versión la invalidaría cada vez que el agente anota algo.
4. **El vínculo commit↔paso es heurístico.** `suggest_step_commits` (`orchestrator/step_suggestions.py:34`) sugiere candidatos por texto del mensaje; no es procedencia.

---

## 2. Estado verificado del código

| Componente | implementation_status | evidence_status | Detalle |
|---|---|---|---|
| Transiciones de pasos | implemented | verifiable | `start_step` (`orchestrator/db.py:702`), primer paso al crear un contexto (`db.py:751`, `:766`), `advance_step` (`mcp.py:862`, `completed` en `:877`, cierre en `:906`), `skip_step` (`mcp.py:662`, cierre en `:704`), `update_context` (`mcp.py:756`); CLI `step` (`cli.py:595`, `:607`) |
| Versión de pasos | implemented | verifiable | Trigger `trg_steps_version` (`migrate.py:229`): sube de a uno con cualquier `UPDATE` |
| Comandos y trabajos de RFC-010 | implemented | verifiable | `ui_commands` (`migrate.py:262`), `jobs` (`migrate.py:298`), catálogo en `orchestrator/commands/catalog.py:176`; ningún comando ejecuta tests ni consulta el CI |
| Identidad de proyectos | implemented | verifiable | `project_identities` (`migrate.py:247`), rutas `confirmed` o `proposed` por alias |
| Categorías MCP | implemented | verifiable | `TOOL_CATEGORIES` y `ADMIN_ONLY_CATEGORIES` (`orchestrator/mcp_governance.py:15`, `:37`) |
| Auditoría MCP | implemented | local-only | `mcp_invocations` (`db.py:123`), hashes sin payloads |
| Evaluación de runs | implemented | local-only | `runs.verification_result` (`migrate.py:687`), escrito por `record_run_evaluation` (`db.py:262`) desde `POST /evaluate-run` (`server.py:1056`, `legacy_routes.py:72`); vacío en la base local |
| Gates de RFC-011 | designed | none | `steps.gate` y tabla de aprobaciones: fase 3 de RFC-011, sin implementar |
| Evidencia, recolectores, gate de salida | absent | none | Objeto de este RFC |

---

## 3. Diseño propuesto

```text
 release_gates (context.yaml)          catálogo de recolectores (código)
   gate.entry / gate.exit                command · ci_checks · pr_state
   chequeos: nombre, recolector,         diff_scope · predecessor · audit
   argumentos, required/advisory
              │                                      │
              └──────────────┬───────────────────────┘
                             ▼
        recolección (trabajo del comando `collect_evidence`, RFC-010)
                             │  filas solo de agregar, con procedencia
                             ▼
                     tabla `evidence`
                             │
                             ▼
        evaluador: ¿todos los requeridos tienen evidencia aprobatoria,
                   vigente y coherente (mismo commit)?
                             │
          auto ──────────────┼────────────── manual / auto_then_manual
          aprobación emitida │               comando `approve_gate` en la UI
          por el evaluador   ▼
                     tabla `gate_approvals` (contrato de RFC-011 §3.4 + §3.7)
                             │
                             ▼
        toda transición de un paso con gate verifica en su transacción
```

### 3.1 Qué es evidencia observada

Una fila de evidencia es observada si cumple las tres condiciones:

1. **La produjo un recolector del catálogo** (§3.3), ejecutado por el orquestador dentro del trabajo de un comando `collect_evidence` de RFC-010. Quién **dispara** el comando (una persona en la UI, un proceso local que llama al endpoint de comandos) no importa: el resultado lo obtiene y lo registra el orquestador, no quien lo pidió.
2. **Lleva procedencia completa:** proyecto, paso, fase, nombre del chequeo, `check_hash` (hash canónico de su definición), recolector y su versión, commit evaluado (`head_sha`), estado del árbol de trabajo, resultado, momento y `request_id` del trabajo.
3. **No se puede editar:** la tabla es solo de agregar, con triggers como los de `ui_command_attempts`. Repetir un chequeo agrega una fila; la vigente es la más reciente para ese chequeo y ese commit.

No son evidencia y no se convierten en evidencia: `steps.notes`, `alignments`, `tool_calls`, el texto de una respuesta MCP, el contenido de un archivo que el agente escribió con el resultado de un comando, ni `runs.verification_result` (P6).

### 3.2 Modelo de datos

**`evidence`** (solo de agregar):

| Campo | Contenido |
|---|---|
| `id`, `created_at` | Identificador y momento de registro |
| `project`, `context_id`, `step_id`, `phase` | `phase` es `entry` o `exit` |
| `gate_name`, `check_name`, `check_hash` | Definición exacta del chequeo evaluado |
| `collector`, `collector_version` | Recolector del catálogo y versión del código que lo implementa |
| `head_sha`, `base_sha`, `tree_clean` | Commit evaluado, base del paso (§3.5) y si el árbol estaba limpio antes y después |
| `result` | `passed`, `failed` o `inconclusive` |
| `exit_code`, `duration_ms` | Para recolectores que ejecutan algo |
| `subject_sha` | SHA que certifica la fila: igual a `head_sha`, salvo en `ci_checks` con `target: merge_result`, donde es el SHA resultante del merge; en `pr_state` guarda ese SHA resultante |
| `detail_hash` | Hash de la salida completa; la salida misma no se guarda en SQLite |
| `request_id` | Clave foránea a `jobs(request_id)`: el trabajo que la produjo |

**Árbol limpio** significa, en la ruta `confirmed` del proyecto: `git status --porcelain=v1 --untracked-files=all --ignore-submodules=none` vacío (índice, archivos rastreados, no rastreados que no estén ignorados y submódulos) y el mismo HEAD antes y después. Los archivos ignorados por `.gitignore` no se controlan: una política no debe declarar comandos que ejecuten o lean código de rutas ignoradas, y el orquestador no lo verifica; ese margen se declara en §6.

La salida de un comando se guarda, si se guarda, en un archivo local bajo `~/.ai-orchestrator/evidence/` cuyo hash es `detail_hash`; ninguna respuesta MCP la incluye (E10). Su retención es la pregunta P5.

**`gate_evaluations`** (solo de agregar): resultado de cada evaluación del evaluador, con `project`, `context_id`, `step_id`, `phase`, `gate_name`, `policy_hash`, `head_sha`, `evidence_set_hash`, `outcome` (`complete`, `incomplete`) y momento. En modo `auto_then_manual`, la última evaluación `complete` vigente es lo que la UI muestra para confirmar; no es una aprobación.

**`gate_approvals`**: contrato de RFC-011 §3.4 más los campos de §3.7. Nunca se borra; la única actualización permitida es pasar `status` de `valid` a `invalidated` completando, en la misma sentencia, `invalidated_at` e `invalidation_reason`.

**`gate_policy_acks`** (solo de agregar): `project`, `gate_name`, `policy_hash`, `request_id` del comando `ack_gate_policy` y momento. Arranque: un gate sin ninguna confirmación registrada se trata como política sin confirmar (E9), así que antes de usar cada gate por primera vez hay que confirmar su política.

### 3.3 Catálogo de recolectores

El catálogo está en el código, igual que el catálogo de comandos de RFC-010: la política elige recolectores y les pasa argumentos, pero no puede definir uno nuevo.

| Recolector | Qué hace | `passed` si | `inconclusive` si |
|---|---|---|---|
| `command` | Ejecuta `argv` (lista, sin shell) en la ruta `confirmed` del proyecto en `project_identities`, con `timeout_s` y variables de entorno mínimas | El código de salida coincide con `expect` (`success` = 0, `failure` ≠ 0) | Árbol sucio antes o después, timeout, ruta no confirmada, binario inexistente |
| `diff_scope` | `git diff --name-only base_sha..head_sha` contra `protected_paths` de RFC-011 (semántica de su §3.1) | Ninguna ruta cambiada coincide con un patrón protegido, salvo las listadas en `allow` del chequeo | Falta `base_sha` o algún commit no existe |
| `predecessor` | Lee el paso anterior del contexto (o el indicado por `step_ref`) | Está `completed` con una aprobación de salida vigente | — |
| `ci_checks` | Consulta los check runs de `head_sha` en el remoto del proyecto (`gh api`, solo lectura) | Todos los checks listados en `required_checks` terminaron en `success` sobre ese SHA exacto | Sin red, sin autenticación, checks pendientes o ausentes |
| `pr_state` | Consulta el PR cuyo head es `head_sha` y cuya base es `base_ref` (argumento del chequeo, por ejemplo `production`) | El PR está mergeado, su último head es `head_sha`, su base es `base_ref` y el commit resultante del merge es alcanzable desde `base_ref` en el remoto. Registra el método (merge, squash o rebase) y el SHA resultante | Sin red, sin PR, o más de un PR candidato |
| `audit` | Ejecuta un auditor como trabajo, con el Egress Gate de RFC-006, y lee la última línea de su salida | La última línea es exactamente `VEREDICTO: APROBADO` | Cualquier otra última línea, error o egress denegado. Sujeto a P2 |

Reglas comunes:
- **Sin efectos en el repositorio:** `command` exige árbol limpio (§3.2) antes y lo verifica después; si el árbol cambió o el HEAD se movió, el resultado es `inconclusive` y la evidencia no cuenta (E12).
- **Red:** `ci_checks` y `pr_state` envían a GitHub el remoto, el SHA y la rama base, nada más; `audit` envía código y por eso pasa por el Egress Gate. Un `command` puede hacer red (un test que descarga dependencias, por ejemplo): este RFC no lo impide ni lo sandboxea, y lo declara en §6. La **evaluación** de un gate solo lee SQLite, el `context.yaml` y el estado local de git, sin red (E13, mantiene I6 de RFC-011).
- **Qué certifican CI y PR:** `ci_checks` certifica el SHA del head, no el commit que resulta del merge; con squash o rebase ese commit es otro y no está cubierto por el CI del head. Si el gate necesita certificar lo que quedó en la rama base, declara un `ci_checks` adicional con `target: merge_result` (P8):
  - `target` admite solo `head` (por defecto) y `merge_result`.
  - Un gate con un `ci_checks` de `target: merge_result` debe tener un `pr_state` en la misma fase; si no, la política es inválida y `doctor` lo reporta.
  - El recolector toma el SHA resultante (`subject_sha`) de la evidencia `pr_state` `passed` más reciente para el mismo paso, fase y `head_sha`; si no existe, el resultado es `inconclusive`.
  - La fila resultante tiene `head_sha` igual al del paso y `subject_sha` igual a ese SHA resultante.
- **`failed` y `inconclusive` son distintos:** un test que falla es `failed`; un timeout o la falta de red es `inconclusive`. Ninguno de los dos aprueba; la diferencia queda registrada para diagnóstico.

### 3.4 Chequeos en la política

`release_gates` de RFC-011 §3.1 se estructura por fase. Esto **enmienda** RFC-011 §3.1 (§3.9): la forma con `approval` y una lista de nombres (`checks: ["tests_passed", "ci_green"]`) deja de ser válida y `doctor` la reporta. No hay datos que migrar: la fase 1 de RFC-011 no está implementada.

```yaml
release_gates:
  invoice_fix:
    entry:
      approval: manual
      checks:
        - name: reproducer_fails
          collector: command
          argv: ["python", "-m", "pytest", "tests/test_invoice_rounding.py"]
          expect: failure          # el problema existe en la base
          timeout_s: 300
    exit:
      approval: auto_then_manual
      checks:
        - name: reproducer_passes
          collector: command
          argv: ["python", "-m", "pytest", "tests/test_invoice_rounding.py"]
          timeout_s: 300
        - name: tests_passed
          collector: command
          argv: ["python", "-m", "pytest", "tests/"]
          timeout_s: 1200
        - name: protected_paths_untouched
          collector: diff_scope
        - name: ci_green
          collector: ci_checks
          required_checks: ["tests", "validate"]
        - name: previous_step_approved
          collector: predecessor
          advisory: true           # se muestra, no bloquea
```

- `name` es único dentro de la fase. `advisory: true` hace que el chequeo se muestre sin bloquear; por defecto todos son requeridos.
- Argumentos por recolector: `command` (`argv`, `expect`, `timeout_s`), `diff_scope` (`allow`), `predecessor` (`step_ref`), `ci_checks` (`required_checks`, `target`), `pr_state` (`base_ref`). Un argumento desconocido invalida la política.
- `check_hash` es el hash del objeto del chequeo en JSON canónico; `policy_hash` (RFC-011 §3.4) es el hash de la definición completa del gate.
- Un gate puede tener solo `entry`, solo `exit` o las dos. Un gate sin ninguna es inválido.

### 3.5 Gates de entrada y de salida

**Entrada (necesidad):** es el gate de activación de RFC-011, sin cambios en dónde bloquea (I4 de RFC-011). Este RFC agrega cómo se aprueba: con los chequeos de `entry`. Ejemplos de necesidad observable: un reproductor que falla en la base (`command` con `expect: failure`), el paso previo terminado y aprobado (`predecessor`). Al activarse el paso, el orquestador guarda en `steps.gate_policy_hash` el `policy_hash` vigente y confirmado del gate, y en `steps.base_sha` el `head_sha` de la aprobación de entrada; si el paso no tiene gate de entrada, guarda el HEAD de la ruta `confirmed` del proyecto en ese momento. Un `reset_step` devuelve el paso a `pending`; como cambia su versión, la aprobación de entrada consumida ya no vale y hace falta otra (RFC-011 §3.4).

**Salida (respuesta satisfactoria):** nuevo. Un paso con `exit` no pasa a `completed` sin una aprobación de salida vigente:
- `advance_step` responde `denied` con `reason_code: "approval_required"`, `phase: "exit"` y la lista de chequeos sin evidencia aprobatoria (solo nombres y resultados); el paso sigue `in_progress` y no se activa ningún otro.
- La misma regla vale para toda vía que complete un paso, desde MCP, CLI o dashboard (E6).

**Saltar o cerrar sin aprobación:** `skip_step` activa el siguiente paso y puede cerrar el contexto (`mcp.py:680-704`), y `update_context` cierra un contexto con pasos abiertos (`mcp.py:756`). Para que eso no eluda un gate:
- `skip_step` sobre un paso con gate (de entrada o de salida) responde `denied` con `reason_code: "approval_required"` por MCP y por CLI. Solo se salta desde la UI, con el comando `skip_gated_step` (categoría `gate_approval`), que registra el `request_id` y un motivo de una lista cerrada (`replaced`, `discarded`).
- Cambiar un contexto a `completed` o `abandoned` mientras tenga un paso con gate en `pending` o `in_progress` responde `denied` por MCP y por CLI. Desde la UI, `close_context` admite `abandoned` en ese caso y rechaza `completed`.
- Un paso `skipped` nunca satisface un chequeo `predecessor`.

**Gate congelado mientras el paso está en curso:** un paso `in_progress` cuyo gate, en la política congelada, tiene fase `exit` solo pasa a `completed` con una aprobación de salida cuyo `policy_hash` es `steps.gate_policy_hash`, y solo si el `context.yaml` vigente tiene ese mismo `policy_hash`. Si la política cambió después de activar el paso (aunque se haya confirmado), el paso no se completa: queda `in_progress` hasta que la política vuelva a ese hash, se lo devuelva a `pending` con `reset_step` (la próxima activación toma la política nueva y, si tiene entrada, exige otra aprobación) o se lo salte con `skip_gated_step`. `steps.gate` y `steps.gate_policy_hash` de un paso `in_progress` no cambian por ninguna vía, incluida la UI (E16).

**Vigencia de la aprobación de salida:** se ata a `step_id`, `context_id`, `spec_hash`, `project`, `gate_name`, `policy_hash`, `head_sha` y `base_sha`. `spec_hash` es el hash de `title`, `description` y `gate` del paso: cambia si cambia qué se pidió, no si el agente agrega notas (§1, punto 3).
- **Cambios en SQLite** (título, descripción o gate del paso, `move_context`, contexto o proyecto): invalidan las aprobaciones de salida del paso en la misma transacción que el cambio.
- **Cambios en `context.yaml`** (definición del gate o de un chequeo): el archivo cambia fuera de SQLite, así que la invalidación es perezosa. Al evaluar y en cada transición, el orquestador lee el archivo, calcula `policy_hash` y los `check_hash` y, dentro de la transacción de la transición, invalida y rechaza si no coinciden con los de la aprobación. Con el archivo ilegible, la transición se rechaza (I8 de RFC-011).

**Lo entregado coincide con lo aprobado:** al emitir una aprobación de salida y al consumirla en la transición a `completed`, el orquestador verifica una de dos condiciones:
1. La ruta `confirmed` del proyecto tiene HEAD en `head_sha` y árbol limpio (§3.2); o
2. La aprobación incluye un `pr_state` `passed` para `head_sha`: lo entregado quedó fijado por el merge, aunque la ruta local ya esté en otro commit.

Si no se cumple ninguna, la respuesta es `denied` con `reason_code: "evidence_stale"`. Git no participa de la transacción de SQLite: entre leer el HEAD y confirmar la transacción hay una ventana en la que el repositorio puede cambiar. Esa carrera residual se declara en §6; la condición 2 no la tiene.

**Coherencia:** todas las evidencias requeridas de una aprobación de salida que dependen del commit del paso refieren exactamente al mismo `head_sha`, que es el de la aprobación, y `diff_scope` usa ese `head_sha` contra el `base_sha` del paso (E4). Un `ci_checks` con `target: merge_result` tiene ese mismo `head_sha` y su `subject_sha` es el SHA resultante que registró el `pr_state` incluido en la misma aprobación.

### 3.6 Modos de aprobación

En los tres modos, la condición necesaria es la misma: cada chequeo requerido de la fase tiene, para el commit evaluado, una evidencia `passed` vigente (mismo `check_hash` que la definición actual) y se cumplen la coherencia y la condición de entrega de §3.5.

| Modo | Quién emite la aprobación | Cuándo |
|---|---|---|
| `auto` | El evaluador | Al terminar una recolección que completa el conjunto, si la política está confirmada (E9) |
| `manual` | Comando `approve_gate` desde la UI local (RFC-010) | Cuando alguien lo confirma viendo los chequeos, sus resultados, commits y momentos |
| `auto_then_manual` | `approve_gate`, sobre una `gate_evaluations` `complete` vigente | El evaluador registra la evaluación; la UI la confirma |

- **Revalidación al confirmar:** `approve_gate` no confía en lo que mostró la pantalla. En la transacción del comando vuelve a evaluar el conjunto completo con la política vigente (incluida la condición de entrega de §3.5) y solo emite la aprobación si el `evidence_set_hash` coincide con el que se mostró; si no, responde `conflict` y la UI vuelve a leer.
- **Sin excepciones:** una confirmación manual no reemplaza un chequeo requerido `failed`, faltante o `inconclusive` (P1). Para avanzar sin ese chequeo hay que cambiar la política, lo que cambia `policy_hash` y queda a la vista.
- **Política sin confirmar, gate cerrado:** cuando el `policy_hash` vigente de un gate no tiene una fila en `gate_policy_acks`, ningún paso con ese gate se activa, completa ni salta, en ningún modo, y el evaluador no emite aprobaciones ni registra evaluaciones `complete`; la respuesta es `denied` con `reason_code: "policy_unconfirmed"` hasta que se confirme la política con `ack_gate_policy` desde la UI (E9). Un agente que edita `context.yaml` para aflojar un chequeo, cambiar el modo o quitar la fase `exit` deja el gate cerrado, no abierto.
- **Gate de un paso abierto:** asignar, cambiar o quitar `steps.gate` de un paso `pending` solo se hace desde la UI con un comando `gate_approval`; por MCP o CLI responde `denied`. En un paso `in_progress` no cambia por ninguna vía (§3.5, E16).
- **Selección de evidencia:** el evaluador solo considera filas de `evidence` con el mismo `project`, `context_id`, `step_id`, `phase`, `gate_name`, `check_name` y `check_hash` vigente, `result = passed`, el `head_sha` de la evaluación, el `base_sha` actual del paso (y el `subject_sha` que corresponda según `target`); entre las que cumplen, la más reciente por chequeo.
- **Canal:** `approve_gate`, `ack_gate_policy` y `skip_gated_step` son comandos de la UI de categoría nueva `gate_approval` (§3.9). No hay tool MCP ni comando de CLI que apruebe.

### 3.7 Contrato de aprobación extendido

Los campos de RFC-011 §3.4 (`step_id`, `step_version`, `project`, `gate_name`, `policy_hash`, `status`) se mantienen. Se agregan:

| Campo | Contenido |
|---|---|
| `context_id` | Contexto del paso al aprobar; un `move_context` la invalida aunque el proyecto no cambie |
| `phase` | `entry` o `exit` |
| `mode` | `auto`, `manual` o `auto_then_manual` |
| `spec_hash` | Solo en `exit` (§3.5); en `entry` la vigencia sigue atada a `step_version` según RFC-011 (P3) |
| `head_sha`, `base_sha` | Commit evaluado y base del paso |
| `evidence_set_hash` | Hash de la lista ordenada de pares (`evidence.id`, `detail_hash`) que fundamentan la aprobación |
| `emitted_by` | `evaluator` o el `request_id` del comando `approve_gate` |
| `created_at`, `invalidated_at`, `invalidation_reason` | Trazabilidad |

Verificación y transición ocurren en la misma transacción, como exige RFC-011 §3.4 para la entrada; este RFC extiende esa atomicidad a la salida.

### 3.8 Superficies

- **Recolectar:** solo el comando `collect_evidence` de RFC-010 (categoría `maintenance`, trabajo con recurso `project:<alias>:evidence`), desde la UI o el endpoint de comandos. Así toda evidencia tiene un `request_id` y un trabajo, con la idempotencia y la auditoría de RFC-010. La CLI no recolecta: hoy llama a las funciones de dominio sin ese protocolo (`cli.py:595`, `:607`); darle un camino gobernado es P7. Ninguna tool MCP recolecta: ejecutar los comandos de la política desde MCP sería ejecución de código por MCP, que RFC-008 no habilita.
- **Consultar:** tool MCP `get_gate_status(step_id)`, categoría `read`: por fase, el modo, cada chequeo con `result`, `head_sha`, `collected_at` y si está vigente, y el estado de la aprobación. Sin salidas, diffs ni datos de otro proyecto.
- **Aprobar, confirmar política y saltar:** solo `approve_gate`, `ack_gate_policy` y `skip_gated_step` desde la UI (§3.6).

### 3.9 Enmiendas a documentos aceptados

Al aceptar este RFC, cada documento enmendado registra la enmienda en su metadata (front matter `related` y una línea en su encabezado), sin reescribir su contenido normativo (regla de inmutabilidad de `../README.md`):

- **RFC-011 §3.1:** forma de `release_gates` por fase (§3.4 de este RFC); la forma con `approval` y lista de nombres deja de ser válida.
- **RFC-011 §3.4:** el contrato de aprobación suma los campos de §3.7; la salida se ata a `spec_hash`. Si P3 se acepta, la entrada también.
- **RFC-011 I4 y §3.4 "Activación":** `skip_step` y el cierre de un contexto con pasos con gate abiertos quedan restringidos según §3.5.
- **RFC-008:** categoría `gate_approval`, que se agrega a `ADMIN_ONLY_CATEGORIES`, la concede solo el perfil `admin` y no se asigna a ninguna tool MCP, en la misma forma que RFC-010 §3.1 agregó `project_admin` y `maintenance`.

---

## 4. Invariantes falsables

- **E1 (Solo evidencia observada):** toda fila de `evidence` la crea un recolector del catálogo dentro del trabajo de un comando `collect_evidence`; ningún camino crea evidencia a partir de `steps.notes`, `alignments`, `tool_calls`, `runs.verification_result`, argumentos de una tool MCP o un archivo escrito por un agente.
- **E2 (Procedencia completa):** toda fila de `evidence` tiene `collector`, `collector_version`, `check_hash`, `result`, `created_at` y un `request_id` que existe en `jobs`, y las de recolectores que dependen de un commit tienen `head_sha` y `tree_clean`.
- **E3 (Solo de agregar):** un `UPDATE` o `DELETE` sobre `evidence`, `gate_evaluations` o `gate_policy_acks` aborta; sobre `gate_approvals`, el único `UPDATE` permitido cambia `status` de `valid` a `invalidated` y completa `invalidated_at` e `invalidation_reason` en la misma sentencia.
- **E4 (Coherencia de commit):** en toda aprobación de salida, las evidencias requeridas que dependen del commit del paso tienen exactamente un `head_sha`, igual al `head_sha` de la aprobación; las de `ci_checks` con `target: merge_result` tienen un `subject_sha` igual al `subject_sha` del `pr_state` incluido en la misma aprobación.
- **E5 (Sin aprobación incompleta):** en ningún modo se emite una aprobación si algún chequeo requerido de la fase no tiene evidencia `passed` con el `check_hash` vigente.
- **E6 (Salida bloqueante):** ningún paso con gate de salida pasa a `completed` sin una aprobación de salida vigente, verificada en la misma transacción, por ninguna vía (MCP, CLI, dashboard).
- **E7 (Invalidación):** un cambio de título, descripción o gate del paso, de su contexto o de su proyecto invalida sus aprobaciones de salida en la misma transacción; un `policy_hash` o `check_hash` que ya no coincide con el `context.yaml` hace que la transición se rechace e invalide la aprobación dentro de la transacción de esa transición. Las de entrada siguen RFC-011 §3.4.
- **E8 (Canal manual):** ninguna tool MCP ni comando de CLI emite, confirma o revoca una aprobación, confirma una política ni salta un paso con gate; un intento por MCP responde `denied`.
- **E9 (Política sin confirmar, gate cerrado):** si no hay fila en `gate_policy_acks` para el `(project, gate_name, policy_hash)` vigente, ningún paso con ese gate se activa, completa ni salta por ninguna vía, y el evaluador no emite aprobaciones ni registra evaluaciones `complete` para ese gate.
- **E10 (Sin payloads):** `evidence`, `gate_evaluations` y `gate_approvals` no guardan salidas, diffs ni texto libre; `get_gate_status` solo devuelve nombres, resultados, hashes, commits y momentos del proyecto consultado.
- **E11 (Compatibilidad):** con pasos sin gate, `start_step`, `advance_step`, `skip_step` y `update_context` se comportan como hoy y no aparece `approval_required`.
- **E12 (Recolección sin efectos):** un recolector `command` que encuentra el árbol sucio antes, o lo deja sucio o con otro HEAD después (§3.2), produce `inconclusive`, y esa fila no cuenta para ninguna aprobación.
- **E13 (Evaluación local):** la evaluación de un gate y la verificación en una transición no hacen llamadas de red. Este invariante no cubre lo que haga el proceso de un recolector `command`.
- **E14 (Sin salto ni cierre por MCP o CLI):** `skip_step` sobre un paso con gate, y el cambio de un contexto a `completed` o `abandoned` con un paso con gate en `pending` o `in_progress`, responden `denied` por MCP y por CLI.
- **E16 (Gate congelado):** `steps.gate` de un paso `pending` no cambia por MCP ni por CLI; `steps.gate` y `steps.gate_policy_hash` de un paso `in_progress` no cambian por ninguna vía; y un paso `in_progress` cuyo gate congelado tiene fase `exit` no pasa a `completed` si el `policy_hash` vigente de su gate difiere de `steps.gate_policy_hash`.
- **E15 (Entrega):** ninguna aprobación de salida se emite ni se consume si la ruta `confirmed` no está en `head_sha` con árbol limpio y la aprobación no incluye un `pr_state` `passed` para `head_sha`.

---

## 5. Alcance

### 5.1 Incluido
- Tablas `evidence`, `gate_evaluations`, `gate_approvals` y `gate_policy_acks`, columnas `steps.base_sha` y `steps.gate_policy_hash`.
- Catálogo de recolectores (§3.3) y forma de `release_gates` por fase (§3.4).
- Evaluador y modos (§3.6); bloqueo de salida en toda vía que complete un paso, y de salto y cierre por MCP y CLI (§3.5).
- Comandos de UI `collect_evidence`, `approve_gate`, `ack_gate_policy` y `skip_gated_step`; tool MCP `get_gate_status`.
- Enmiendas de §3.9 a RFC-011 y RFC-008.

### 5.2 Fuera de alcance
- Autenticación fuerte de personas (P1 de RFC-011).
- Defensa contra procesos locales que escriben SQLite o la configuración del orquestador (RFC-009 §0).
- Sandbox de los comandos de un chequeo más allá de `argv` sin shell, ruta confirmada, timeout y entorno mínimo; en particular, impedir que hagan red.
- Recolección desde la CLI (P7).
- Completar `runs.verification_result` (P6).
- Juzgar la calidad de los tests que declara una política.

---

## 6. Riesgos y mitigaciones

| Riesgo | Severidad | Mitigación |
|---|---|---|
| El agente salta el paso o cierra el contexto para eludir el gate | Alta | E14: solo desde la UI, con motivo registrado. |
| El agente debilita los tests en el mismo commit que dice arreglar | Alta | `diff_scope` contra `protected_paths` (por ejemplo `tests/**` en pasos que no deberían tocarlos); el modo `manual` muestra qué cambió; auditoría (P2). |
| El agente afloja o quita la política en `context.yaml` | Alta | E9: un `policy_hash` sin confirmar cierra el gate en todos los modos hasta `ack_gate_policy` desde la UI; E16: un paso en curso solo se completa contra la política con que se activó, aunque la nueva se confirme; las aprobaciones previas se invalidan al evaluar o transicionar (E7). |
| Un proceso local usa la UI para confirmar una política aflojada, reiniciar o saltar un paso | Media | Residual aceptado en P1 de RFC-011: la UI local no autentica personas. Queda registrado (`request_id`, motivo) y un paso saltado nunca cuenta como `completed`. |
| Un chequeo `command` ejecuta código arbitrario | Media | Es el mismo código que el dueño correría a mano, declarado en la política de su proyecto; `argv` sin shell, ruta `confirmed`, timeout y entorno mínimo; E12. |
| Un `command` hace red o egress | Media | No se impide (§3.3, E13); la política es del dueño y E9 exige confirmarla antes de usarla en `auto`. |
| Un `command` usa archivos ignorados por git que el agente dejó | Media | El árbol limpio no controla archivos ignorados (§3.2); el modo `manual` y una política que no ejecute rutas ignoradas lo reducen; queda como residual. |
| El repositorio cambia entre leer el HEAD y confirmar la transición | Baja | Git no es transaccional con SQLite; la ventana es corta y la condición de entrega por `pr_state` no la tiene (§3.5). |
| Tests intermitentes | Media | Cada repetición agrega una fila; vale la más reciente para ese commit y chequeo; no hay "mejor de N". |
| Sin red o sin `gh` autenticado | Baja | `inconclusive`, nunca `passed`; el gate queda cerrado y la respuesta dice por qué. |
| El veredicto de un auditor LLM no es reproducible | Media | Se registra como lo que es (corrió, sobre qué commit, qué dijo); P2 decide si alcanza en `auto`. |
| Fricción en flujos chicos | Media | Todo es opcional: solo aplica a pasos con gate (E11). |

---

## 7. Plan de implementación (tentativo, sujeto a la validación del RFC)

Requiere la fase 3 de RFC-011 (`steps.gate`, tabla de aprobaciones y verificación en las activaciones).

1. **Evidencia y recolectores locales:** tablas, `steps.base_sha`, recolectores `command`, `diff_scope` y `predecessor`, comando `collect_evidence` con su trabajo (E1-E3, E12).
2. **Evaluador y salida:** forma de `release_gates` por fase, evaluador, bloqueo de salida, salto y cierre en todas las vías, invalidación, condición de entrega, tool `get_gate_status` (E4-E7, E9, E10, E11, E13-E16).
3. **Modos con confirmación:** comandos `approve_gate`, `ack_gate_policy` y `skip_gated_step`, categoría `gate_approval` (E8). Hasta esta fase ningún paso con gate avanza, porque ninguna política está confirmada (E9). Va con la ola 6 del dashboard.
4. **Recolectores con red:** `ci_checks` y `pr_state`.
5. **Recolector `audit`:** según la decisión P2.

Cada fase es un PR con la auditoría de ANL-003 y tests de sus invariantes.

---

## 8. Criterios de merge

**De este RFC a `accepted`:**
- [ ] Front matter validado por `scripts/validate_decision_docs.py`.
- [ ] Regla de anonimización verificada en el documento y en los ejemplos.
- [ ] Auditoría de ANL-003 en dos rondas sin hallazgos abiertos: ronda 1 con Codex (`codex exec --sandbox read-only -c model_reasoning_effort=high`) y Gemini (`agy --mode plan --model gemini-3.8-flash-high`) por ser un RFC. En la v0.2 Gemini no corrió (cuota agotada, 429, 2026-10-30); su ronda 1 queda pendiente o el dueño la dispensa.
- [ ] Enmiendas de §3.9 registradas en la metadata de RFC-011 y RFC-008.
- [ ] Preguntas de §9 resueltas o diferidas explícitamente por el dueño.

**De cada PR de implementación:**
- [ ] Tests de los invariantes que cubre la fase.
- [ ] Tests de pureza STDIO en `tests/test_mcp.py` para `get_gate_status`.
- [ ] `python -m pytest tests/` completo en verde y validadores que correspondan.

---

## 9. Preguntas abiertas

- **P1. Excepción manual sobre un chequeo fallido.** ¿Puede `approve_gate` aprobar con un chequeo requerido `failed` o `inconclusive` si se registra un motivo? Propuesta base: no; se cambia la política, lo que suspende `auto` y deja rastro (E9).
- **P2. Recolector `audit`.** (a) El orquestador ejecuta el auditor como trabajo, con el Egress Gate, y lee el veredicto de la última línea; (b) la auditoría queda fuera de los chequeos y el dueño la considera al confirmar en modo `manual`. Propuesta base: (b) hasta la fase 5; con (a), un chequeo `audit` solo se admite en gates `manual` o `auto_then_manual`.
- **P3. Vigencia de la entrada por `spec_hash`.** RFC-011 ata la aprobación de entrada a `step_version`, que sube también al agregar notas a un paso `pending`. ¿Se enmienda RFC-011 §3.4 para usar `spec_hash` también en la entrada? Propuesta base: sí, como enmienda acotada al aceptar este RFC.
- **P4. Motivos de `skip_gated_step`.** La v0.2 restringe el salto a la UI (§3.5, E14) con motivo `replaced` o `discarded`. ¿Alcanzan esos dos motivos? Propuesta base: sí.
- **P5. Retención de las salidas locales.** Propuesta base: 30 días en `~/.ai-orchestrator/evidence/`, fuera de SQLite; el `detail_hash` queda para siempre.
- **P6. `runs.verification_result`.** Propuesta base: no se completa desde `evidence` ni cuenta como evidencia; los runs son ejecuciones de modelos y la evidencia es de pasos. Se reevalúa si el router por API se reactiva.
- **P7. Recolección desde la CLI.** Un `ai-orchestrator evidence collect` que pase por el protocolo de comandos de RFC-010 (registro en `ui_commands`, trabajo, recibo) sin el dashboard levantado. Propuesta base: diferirlo; mientras tanto, recolectar requiere el dashboard.
- **P8. Certificar el commit resultante del merge.** Con squash o rebase, el CI del head no cubre el commit que queda en la rama base. ¿`ci_checks` con `target: merge_result` debe ser obligatorio cuando el gate incluye `pr_state`? Propuesta base: opcional, decidido por la política de cada proyecto.

---

## Apéndice A — Referencias

Verificadas contra `production@5e5d1e79d9e9bf5fefb28ac87a3f47db99d10fa3` el 2026-10-30:

- `orchestrator/mcp.py:662`, `:704` — `skip_step` y cierre automático.
- `orchestrator/mcp.py:862`, `:877`, `:906` — `advance_step`: `completed` y cierre automático.
- `orchestrator/db.py:702`, `:751`, `:766` — `start_step` y activación del primer paso.
- `orchestrator/db.py:123` — `mcp_invocations`.
- `orchestrator/db.py:265` y `orchestrator/migrate.py:687` — `runs.verification_result`.
- `orchestrator/migrate.py:229` — trigger `trg_steps_version`.
- `orchestrator/migrate.py:247`, `:262`, `:298` — `project_identities`, `ui_commands`, `jobs`.
- `orchestrator/commands/catalog.py:176` — catálogo de comandos de la UI.
- `orchestrator/mcp_governance.py:15`, `:37` — `TOOL_CATEGORIES` y `ADMIN_ONLY_CATEGORIES`.
- `orchestrator/step_suggestions.py:34` — `suggest_step_commits`.
- `docs/decisions/rfcs/RFC-011-governed-project-policies.md` §3.1, §3.4, I4, I6, §9 P1.
- `docs/decisions/rfcs/RFC-010-governed-ui-commands.md` §3.1-§3.3.
- `docs/decisions/rfcs/RFC-009-dashboard-local-security.md` §0.
- `docs/decisions/rfcs/RFC-008-governed-mcp-access.md` — categorías y §10.2 (egress).
- `docs/decisions/rfcs/RFC-006-provider-safe-routing.md` — Egress Gate.
- `docs/decisions/analyses/ANL-003-per-change-cross-audit.md` — protocolo de auditoría.
