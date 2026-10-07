---
id: RFC-010
type: rfc
title: Comandos gobernados desde la UI e identidad de proyectos
status: draft
created: 2026-10-06
updated: 2026-10-06
supersedes: []
superseded_by: null
related: [RFC-008, RFC-009]
---

# RFC-010 — Comandos gobernados desde la UI e identidad de proyectos

**Estado:** Draft
**Versión:** 0.1
**Fecha:** 2026-10-06
**Repo de referencia:** `csantisdev/ai-orchestrator@production` = `82a229c5cebc317af4342ed7734676bb65737102` (verificado 2026-10-06)
**Relación con la serie:** Es el prerrequisito de la ola 6 de la especificación del dashboard
(`docs/backlog/DASHBOARD_VISUALIZACION_ESPECIFICACION.md`, §24.5, retiro del legado), que en
"Diferido (después de D5)" pide **gobernanza de comandos desde la UI**: idempotencia,
`expected_version`, conflictos, límites de presupuesto y consistencia entre pestañas. Reutiliza
el modelo de RFC-008 (acceso MCP gobernado: categorías, perfiles, `request_id` durable y
auditoría) y se apoya en RFC-009 (seguridad local del servidor HTTP: token de sesión, Origin y
Host). No cambia ninguno de los dos.

*Todo ejemplo usa datos sintéticos (`mi-proyecto`, `mi-workspace`, `mi-frontend`, `mi-backend`).
Ver "Regla de anonimización" en `../README.md`.*

---

## 0. Resumen ejecutivo

Las escrituras del dashboard (crear o avanzar contextos, enviar tareas, registrar o renombrar
proyectos, purgar índices, importar sesiones) pasan hoy por 27 rutas POST que no tienen ninguna
de las garantías que el servidor MCP ya da a los agentes: no son idempotentes, no quedan
auditadas, no respetan un alcance por proyecto y no detectan que un agente cambió el mismo objeto
desde otro proceso. Este RFC propone **un único camino de comandos** para la UI:

1. un endpoint de comandos (`POST /api/v1/commands/{name}`) con el mismo catálogo de categorías
   que el MCP, `request_id` obligatorio y durable, `expected_version` en lo que muta un objeto
   existente, y un registro de auditoría equivalente al de `mcp_invocations`;
2. **operaciones largas como trabajos** con etapas (spec §7), en lugar de requests que bloquean;
3. **identidad de proyectos** explícita: alias canónicos, alias equivalentes (worktrees, clones,
   carpetas renombradas) y fusión gobernada, porque el uso real mostró que sin eso los datos se
   fragmentan y no hay forma segura de juntarlos.

Lo que este documento **no** afirma:

- no reemplaza el MCP ni cambia su política: los agentes siguen usando RFC-008;
- no abre el dashboard a la red ni agrega usuarios: sigue siendo local y de una persona (RFC-009);
- no decide la vista de varios proyectos a la vez (§15 de la especificación la deja fuera);
- no implementa el Event Log durable (§11, requiere su propio RFC), aunque el registro de
  comandos es compatible con él;
- no migra todavía ninguna vista heredada: eso lo hacen los PR de la ola 6 sobre este contrato.

## 1. El problema

### 1.1 Escrituras sin garantías

`orchestrator/server.py` (handler de POST, líneas ~850-881) despacha 27 rutas con efectos, entre
ellas `/delete-contexts`, `/context/{id}/delete`, `/clear-imports`, `/advance-step`,
`/skip-step`, `/create-context`, `/project/rename`, `/add-project`, `/purge-chroma-docs`,
`/sync-cc`, `/index-docs` y `/run` (esta última llama a un proveedor de IA). RFC-009 las protegió
contra CSRF (token, Origin, Host), pero cada una:

| Falta | Consecuencia reproducible |
|---|---|
| Idempotencia | Un doble clic o un reintento tras un corte repite la escritura (dos contextos creados, un paso avanzado dos veces). |
| Auditoría | Nada registra qué hizo la UI; Gobernanza solo ve lo que pasó por MCP. |
| Alcance por proyecto | Cualquier ruta acepta cualquier alias; no hay equivalente a `ORCHESTRATOR_MCP_PROJECTS`. |
| Control de concurrencia | Si un agente avanza un paso vía MCP mientras la persona lo mira, un `advance` desde la UI actúa sobre un estado que ya no es el que vio. |
| Operaciones largas | `/sync-cc`, `/index-docs` o `/run-fix` bloquean la request; si el servidor se reinicia, el resultado se pierde y la UI no sabe si terminó. |
| Sesión expirada | Tras reiniciar el servidor, la UI recibe `session_expired` y la persona no sabe si la escritura ocurrió. |

### 1.2 Identidad de proyectos: lo que mostró el uso real

Tres problemas aparecieron trabajando con el orquestador, no en un diseño:

**a) Alias fragmentados.** `orchestrator/watcher.py:_cwd_to_alias` (líneas 177-193) asigna una
sesión importada al proyecto registrado cuya ruta contiene a la carpeta de trabajo, y si no
encuentra ninguno usa **el nombre de la carpeta**. Un `git worktree` o un clon de trabajo viven
en carpetas hermanas (`mi-proyecto-wt-feature`, `mi-proyecto-clon`), así que cada uno crea un
alias propio. En una base local real, un solo repositorio terminó repartido en 28 alias
derivados de worktrees y clones, con sus runs y costos fuera del proyecto.

**b) No se pueden juntar.** `ai-orchestrator rename` y `POST /project/rename`
(`cli.py:128-144`, `server.py:1246-1269`) llaman a `index.rename_project`, que:

- solo acepta alias **registrados en el índice** (los derivados de carpetas no lo están);
- **rechaza el destino si ya existe** ("ya está en uso"): no puede fusionar dos alias;
- actualiza `runs` y `contexts` (`db.rename_project_in_db`, `db.py:350-361`) pero no
  `mcp_invocations` ni `egress_decisions`, que también tienen `project`;
- no es atómico entre índice (YAML) y base (SQLite);
- se deshace solo: el próximo `sync` vuelve a crear el alias viejo desde la carpeta.

**c) Contextos en el proyecto equivocado.** En un workspace con repos anidados (un proyecto
raíz `mi-workspace` que contiene `mi-frontend` y `mi-backend`, cada uno con su propio alias),
registrar el tracking en el alias equivocado ya causó errores reales, al punto de que las
instrucciones del workspace lo prohíben explícitamente. No existe ningún comando para mover un
contexto (con sus pasos) a otro proyecto: la única salida es SQL a mano.

**d) Vinculación de sesiones a pasos.** `db.get_active_step_id` (`db.py:559-574`) vincula cada
sesión importada al paso en curso del contexto activo **más reciente** del alias. La propia
especificación (§24.6) espera varios contextos activos en paralelo, así que las sesiones se
vinculan al paso de otra unidad o a ninguno. Junto con (a), explica por qué solo una fracción
chica de los runs importados queda vinculada a un paso y el costo por unidad no se puede medir.

## 2. Estado verificado del código

| Componente | implementation_status | evidence_status | Detalle |
|---|---|---|---|
| Seguridad del POST (token, Origin, Host, Content-Type) | implemented | verifiable | RFC-009, `server.py` (`_require_json_ct`, validación previa al despacho) |
| Categorías y perfiles de herramientas MCP | implemented | verifiable | `mcp_governance.py:TOOL_CATEGORIES`, `PROFILE_CAPABILITIES` |
| `request_id` durable y reclamo de mutaciones | implemented (solo MCP) | verifiable | `mcp_governance.py:mutation_request_id`, `claim_mutation`, `complete_mutation` sobre `mcp_invocations` |
| Auditoría de invocaciones | implemented (solo MCP) | verifiable | `mcp_governance.py:audit_invocation`; Gobernanza la lee (`api_v1/governance.py`) |
| Escrituras de la UI | implemented sin gobernanza | verifiable | 27 rutas en `server.py` (handler de POST) |
| `expected_version` / control de concurrencia | absent | none | Ninguna tabla guarda versión; `contexts.updated_at` existe pero no se compara |
| Trabajos con etapas | absent | none | Las operaciones largas corren dentro de la request |
| Alias equivalentes y fusión | absent | none | `watcher._cwd_to_alias` cae al nombre de carpeta; `rename` no fusiona |
| Mover contexto entre proyectos | absent | none | Sin comando ni endpoint |
| Vinculación de sesiones a pasos | partial | verifiable | `db.get_active_step_id` elige el contexto activo más reciente |
| Detección de cambios entre procesos | implemented | verifiable | `change_watch.py` (D4): `db_changed` por SSE con huella de relevancia |

## 3. Diseño propuesto

### 3.1 Endpoint de comandos

```
POST /api/v1/commands/{name}
Headers: token de sesión, Origin, Content-Type (RFC-009)
Body: { "request_id": "<uuid generado por la UI>",
        "project": "mi-proyecto",
        "expected_version": "<versión vista, si el comando muta un objeto existente>",
        "args": { ... según el esquema del comando ... } }
```

- **Catálogo único.** Cada comando declara nombre, categoría (las de RFC-008: `read`, `append`,
  `workflow_mutation`, `workflow_transition`, `memory_ingest`, más dos nuevas para la UI:
  `project_admin` y `maintenance`), esquema JSON de argumentos, si es largo (trabajo) y si llama a
  un proveedor. Las herramientas MCP equivalentes y los comandos comparten la misma función de
  dominio: no hay dos implementaciones de `advance_step`.
- **Perfil de la UI.** La UI corre con un perfil declarado en la configuración local
  (predeterminado `workflow_operator`, como el que hoy usan los agentes de confianza) y un
  alcance de proyectos (predeterminado: los registrados). `project_admin` y `maintenance` piden
  confirmación explícita en la UI y quedan fuera del perfil predeterminado.
- **Idempotencia.** `request_id` es obligatorio. Se reclama antes de ejecutar (mismo mecanismo
  que `claim_mutation`): repetir el mismo `request_id` con los mismos argumentos devuelve el
  resultado registrado sin repetir el efecto; con argumentos distintos, `409 request_id_reused`.
- **Auditoría.** Cada comando deja una fila en una tabla de auditoría con el mismo formato que
  `mcp_invocations` (hash de argumentos y resultado, no el contenido), con `client_surface =
  "dashboard"`. Gobernanza la muestra junto a las invocaciones MCP.
- **Respuesta.** `{ "status": "ok" | "denied" | "conflict" | "error" | "accepted", "reason_code",
  "hint", "result" | "job_id", "version" }`, con los mismos `reason_code` que el MCP cuando aplica.

### 3.2 Versiones y conflictos

- Cada contexto y cada paso tienen una **versión** que cambia en cada mutación, venga de la UI,
  del MCP o de la CLI. Se propone una columna entera `version` (incremento en la misma
  transacción que la mutación), en lugar de comparar `updated_at`, porque los timestamps
  mezclan offsets (§20.2) y no todas las mutaciones lo actualizan hoy.
- Los comandos que mutan un objeto existente exigen `expected_version`. Si no coincide, responden
  `conflict` con la versión y el estado actuales; la UI muestra qué cambió y ofrece reintentar.
- Las lecturas de la API (Trabajo, Trace) devuelven la versión, así la UI siempre manda la que
  mostró.

### 3.3 Trabajos (operaciones largas)

- Los comandos marcados como largos (`sync-*`, `index-docs`, `run-fix`, `purge-*`, `run`)
  responden `accepted` con un `job_id` y corren en un único ejecutor del servidor, uno por tipo a
  la vez (el candado de sincronización actual se generaliza).
- Cada trabajo publica sus **etapas** (spec §7: "Resolviendo relaciones ✓ · Aplicando política ✓
  · Ejecutando ●") por SSE y queda registrado con su resultado; la UI lo muestra en Activity.
- Si el servidor se reinicia, los trabajos en curso quedan como `interrupted` al arrancar (nunca
  "en curso" para siempre), y la UI puede reintentar con un `request_id` nuevo.

### 3.4 Identidad de proyectos

- **Alias canónico y equivalentes.** El índice pasa a tener, por proyecto, su alias canónico, la
  ruta y una lista de **equivalentes**: rutas o patrones de carpeta (`mi-proyecto-wt-*`) y
  remotos git que pertenecen al mismo proyecto. `_cwd_to_alias` resuelve en este orden: ruta
  registrada que contiene a la carpeta → equivalente declarado → **repositorio git común**
  (`git rev-parse --git-common-dir` para worktrees; remoto `origin` igual al del proyecto para
  clones) → recién entonces el nombre de la carpeta, marcado como `detected`.
- **Fusión gobernada** (`project_admin`). `merge_projects(source, target)`:
  1. vista previa con conteos por tabla (`runs`, `contexts`, `mcp_invocations`,
     `egress_decisions`) y conflictos (por ejemplo, el mismo `session_id` en ambos);
  2. ejecución en **una sola transacción** sobre todas las tablas con `project`;
  3. registro del origen como equivalente del destino, para que el próximo `sync` no lo recree;
  4. auditoría con los conteos.

  `rename` pasa a ser un caso particular (destino inexistente) del mismo comando.
- **Mover un contexto** (`project_admin`). `move_context(context_id, target_project)` con
  `expected_version`, vista previa (pasos, alineamientos, tool calls y runs vinculados) y
  auditoría. Sirve para corregir el tracking registrado en el alias equivocado.
- **Vinculación de sesiones.** Al importar, si el alias tiene varios contextos activos, la
  sesión se vincula al paso en curso cuyo contexto coincide con la rama o el worktree de la
  sesión cuando hay forma de saberlo; si no, queda **sin vincular y marcada como ambigua** en vez
  de caer en el contexto más reciente. La UI ofrece vincularla a mano (`append`).
- **Workspaces con repos anidados.** Se modela la relación padre-hijo (`mi-workspace` contiene a
  `mi-frontend` y `mi-backend`) solo como metadato del índice, para avisar en la UI y en el MCP
  cuando se registra tracking en el padre desde una carpeta que pertenece a un hijo. No se agrega
  una vista combinada (§15).

### 3.5 Lo que falta además, según el uso real

Cosas que el uso mostró y que entran como comandos del mismo catálogo, sin diseño propio:

- **Cerrar o abandonar contextos activos huérfanos** (`workflow_transition`), con la advertencia
  `multiple_active_contexts` como entrada.
- **Reparación de datos** acotada: corregir títulos o notas dañados de pasos y contextos con
  `expected_version` (`workflow_mutation`), en lugar de SQL a mano.
- **Reintento seguro tras reiniciar el servidor:** como el `request_id` es durable, la UI vuelve
  a enviar el mismo comando con la sesión nueva y obtiene el resultado original si ya se aplicó.

## 4. Invariantes / Requisitos falsables

- **I1.** Ninguna escritura de la UI ocurre fuera de `POST /api/v1/commands/{name}` una vez
  migrada su vista; un test estático lista las rutas POST del servidor y falla si aparece una
  nueva fuera del catálogo o de la lista de heredadas pendientes.
- **I2.** Repetir un comando con el mismo `request_id` y los mismos argumentos no repite el
  efecto y devuelve el mismo resultado; con argumentos distintos responde `409`.
- **I3.** Todo comando ejecutado o denegado deja exactamente una fila de auditoría sin el
  contenido de argumentos ni resultados (solo hashes y metadatos).
- **I4.** Un comando sobre un proyecto fuera del alcance de la UI responde `denied` con
  `reason_code = project_out_of_scope`, sin efectos.
- **I5.** Un comando con `expected_version` distinta de la actual responde `conflict` sin
  efectos; cualquier mutación (UI, MCP o CLI) incrementa la versión del objeto.
- **I6.** Un trabajo nunca queda `running` después de reiniciar el servidor: queda `done`,
  `failed` o `interrupted`.
- **I7.** `merge_projects` es atómico: o se actualizan todas las tablas con `project` y el
  índice, o ninguna; tras la fusión, importar una sesión desde una carpeta del alias origen la
  asigna al destino.
- **I8.** Una sesión importada desde un worktree o un clon del mismo repositorio que un proyecto
  registrado se asigna a ese proyecto, no al nombre de la carpeta.
- **I9.** Con varios contextos activos en un alias, una sesión sin forma de desambiguar queda sin
  vincular y marcada como ambigua; nunca se vincula a un paso de otro contexto por recencia.
- **I10.** Los comandos que llaman a un proveedor pasan por el gate de egress y el presupuesto
  igual que la CLI (RFC-006/007); la UI no tiene un camino propio hacia los proveedores.

## 5. Alcance

**Dentro:** endpoint y catálogo de comandos, auditoría, idempotencia, versiones, trabajos con
etapas, identidad de proyectos (equivalentes, resolución por repositorio git, fusión, mover
contexto, vinculación de sesiones), comandos de mantenimiento de contextos listados en §3.5.

**Fuera pero cubierto por otro documento:** Event Log durable (§11 de la especificación, RFC
propio); seguridad del servidor HTTP (RFC-009); política MCP (RFC-008).

**Fuera de esta ronda:** acceso remoto o multiusuario; vista de varios proyectos a la vez;
deshacer comandos (se evalúa con el Event Log); migración de datos históricos más allá de la
fusión explícita que pida la persona.

## 6. Riesgos

| Riesgo | Severidad | Mitigación |
|---|---|---|
| Doble implementación MCP/UI de la misma operación | Alta | Una función de dominio por operación; MCP y comandos son adaptadores. Test que verifica que cada comando con equivalente MCP llama a la misma función. |
| Fusión de proyectos errónea (irreversible sin backup) | Alta | Vista previa obligatoria, confirmación explícita, respaldo automático de la base antes de ejecutar con `db.backup_database` (`db.py:868`, el mismo que usa el recálculo de costos en `cli.py:2045`) y auditoría con conteos. |
| Migración de esquema (`version`, tabla de auditoría, tabla de trabajos) | Media | PR propio con prueba de upgrade desde una base de la versión anterior (spec §24.4). |
| Resolución por git lenta o fallida al importar | Media | Caché por ruta y tiempo límite; si falla, cae al comportamiento actual marcado como `detected`. |
| Falsos positivos al asignar clones por remoto | Media | Solo si el remoto coincide exactamente con el de un proyecto registrado; el resto queda `detected` y la UI propone la fusión. |
| Conflictos frecuentes con agentes trabajando | Baja | La UI muestra el estado actual y reintenta con un clic; `db_changed` (D4) ya refresca la vista. |

## 7. Plan de implementación (tentativo, sujeto a la validación del RFC)

Cada PR con auditoría cruzada ANL-003 en dos rondas.

1. **Esquema.** Columna `version` en `contexts` y `steps`; tablas de auditoría de comandos y de
   trabajos; prueba de upgrade. Las mutaciones existentes (MCP y CLI) empiezan a incrementar la
   versión.
2. **Núcleo de comandos.** `orchestrator/commands/` (catálogo, despacho, idempotencia,
   auditoría, alcance) + `api_v1/commands.py`; primeros comandos sin riesgo: `confirm_alignment`,
   `update_step` (notas) y cerrar contexto. Tests de I1-I5.
3. **Trabajos.** Ejecutor con etapas por SSE; `sync-*` e `index-docs` como trabajos. Tests de I6.
4. **Identidad de proyectos.** Equivalentes en el índice, resolución por git en la importación,
   vinculación ambigua, `merge_projects` y `move_context` con vista previa. Tests de I7-I9 con
   repositorios git sintéticos (worktree y clon) creados en el test.
5. **Ola 6 por vista.** Trabajo › Flujos, Ejecuciones › Actividad (envío de tareas, con I10),
   Ajustes › Proyectos, Datos y Configuración: cada vista migra a comandos y baja su línea base de
   literales; al llegar a cero se borra el ensamblador heredado.

## 8. Criterios de merge

**De este RFC a `accepted`:**

- [ ] Auditoría cruzada (Codex) en dos rondas sin hallazgos bloqueantes.
- [ ] La persona responsable valida el alcance de §3.4 y §3.5 y el perfil predeterminado de la UI.

**De cada PR de implementación:** sus invariantes con tests en verde, suite completa, y para los
PR con migración, la prueba de upgrade.

**Para afirmar valor de producto:** tras el PR 4, una fusión real de alias fragmentados ejecutada
por la persona sobre su base, con los conteos de la vista previa registrados como evidencia
local (sin nombres) en el tracking.

---

## Apéndice A — Referencias

- Especificación del dashboard: `docs/backlog/DASHBOARD_VISUALIZACION_ESPECIFICACION.md` (§7,
  §11, §15, §20.2, §24.4-§24.6 y "Diferido (después de D5)"), verificada en el commit de
  referencia.
- RFC-008 (`RFC-008-governed-mcp-access.md`) y RFC-009 (`RFC-009-dashboard-local-security.md`).
- Código citado: `orchestrator/server.py`, `orchestrator/mcp_governance.py`,
  `orchestrator/watcher.py`, `orchestrator/db.py`, `orchestrator/index.py`,
  `orchestrator/cli.py`, `orchestrator/change_watch.py`, en el commit de referencia.
