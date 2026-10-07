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
**Versión:** 0.3
**Fecha:** 2026-10-06
**Repo de referencia:** `csantisdev/ai-orchestrator@production` = `82a229c5cebc317af4342ed7734676bb65737102` (verificado 2026-10-06)
**Relación con la serie:** Es el prerrequisito de la ola 6 de la especificación del dashboard
(`docs/backlog/DASHBOARD_VISUALIZACION_ESPECIFICACION.md`, §24.5, retiro del legado), que en
"Diferido (después de D5)" pide **gobernanza de comandos desde la UI**: idempotencia,
`expected_version`, conflictos, límites de presupuesto y consistencia entre pestañas. Reutiliza
el modelo de RFC-008 (acceso MCP gobernado) y **lo enmienda** en un punto: agrega dos categorías
(`project_admin` y `maintenance`) que ningún perfil MCP incluye (§3.1); al aceptarse este RFC,
RFC-008 registra la enmienda en su metadata. Se apoya en RFC-009 (seguridad local del servidor
HTTP) sin cambiarlo.

*Todo ejemplo usa datos sintéticos (`mi-proyecto`, `mi-workspace`, `mi-frontend`, `mi-backend`).
Ver "Regla de anonimización" en `../README.md`.*

---

## Changelog

| Área | v0.1 | v0.2 |
|---|---|---|
| Fusión de proyectos | "Una sola transacción" sobre SQLite e índice YAML | Imposible: el YAML no entra en la transacción de SQLite. La identidad de proyectos pasa a SQLite; el YAML queda como registro de rutas, se reescribe con archivo temporal y `replace`, y una intención durable se reconcilia al arrancar (§3.4.3). Respaldo de base **e** índice (auditoría Codex, ronda 1, B1) |
| Reintentos | "Devuelve el resultado registrado" | El mecanismo de RFC-008 no guarda resultados, por privacidad. Un reintento devuelve un **recibo** (estado, IDs creados, versión y hashes), nunca el resultado completo. Cada tipo de trabajo define su reconciliación y cuándo es seguro reintentar (§3.3, B2) |
| Perfil de la UI | `workflow_operator` por defecto | `readonly` si no hay configuración explícita, como exige RFC-008. Las categorías nuevas se declaran como enmienda a RFC-008 (§3.1, B3) |
| Presupuesto | "Igual que la CLI" | La CLI solo avisa después del run (`costs.check_budget` no bloquea). Se agrega **admisión previa**: reserva estimada, rechazo si excede y conciliación con el costo real (§3.5, I15, B3) |
| Identidad por git | `git-common-dir` y remoto igual | Primero el límite de repositorio más específico; `git` sin shell y con tiempo límite; el remoto normalizado solo propone, nunca asigna; la identidad confirmada queda persistida (§3.4.2, I1-I3) |
| Mover contexto | Vista previa genérica | Todas las relaciones enumeradas: pasos, alineamientos, tool calls, runs vinculados y sus decisiones de egress, `parent_step_id` entre proyectos (permitido solo con confirmación). Las invocaciones MCP históricas no se mueven (§3.4.4, I4) |
| Invariantes | I1-I10 | Se agregan consistencia entre pestañas, TOCTOU en trabajos, exclusión por recurso, borrados confirmados contra la vista previa y admisión de presupuesto (I12-I16) |
| Estado del código | Operaciones largas "dentro de la request" | `/run` ya responde 202 y corre en un hilo con un run pendiente y SSE (`server.py:1722-1738`, `background.py:24-51`): parcial, no ausente (I2) |
| Plan | Sin transición de rutas heredadas | PR de transición: inventario de rutas heredadas con dueño, adaptador y criterio de retiro; test que impide rutas nuevas fuera del catálogo (§7, I2) |
| Precisión de §1.1 | Afirmaciones amplias | Corregidas: alcance de "cualquier alias", ejemplo de doble avance, `session_expired` se rechaza antes del despacho (m1) |

| Área | v0.2 | v0.3 |
|---|---|---|
| Fusión y plano RAG | Cuatro tablas en la vista previa | Se suma `chunks` (`migrate.py:343-355`) y ChromaDB, que guarda el alias en IDs y metadatos (`rag.py:235-240`) y filtra por él (`rag.py:384-390`): intención durable propia para migrar o reconstruir, consultas que incluyen los alias equivalentes mientras tanto y estado "degradado" visible (§3.4.3, I8; auditoría Codex, ronda 2) |
| Recibos y auditoría | Recibo solo terminal; "exactamente una fila" por comando | Un **registro lógico** por `request_id` (único, como en `mcp_invocations`) y una **auditoría de intentos** aparte, solo de agregar. Reintento según estado: `queued`/`running` → `accepted` con `job_id`; `interrupted` → recibo `interrupted`; terminal → recibo terminal (§3.2, I2, I3) |
| Perfiles y categorías nuevas | Sin mapeo normativo | Solo `admin` concede `project_admin` y `maintenance` tras la enmienda; `workflow_operator` no; probado con I4 (§3.1) |
| `busy` | Sin estado de reintento | Estado `not_admitted`: no es terminal ni consume el `request_id`; reenviarlo vuelve a evaluar la admisión (§3.2, I2, I14; ronda focal) |
| Colección de respuestas | Fuera de la fusión | La intención RAG cubre las dos colecciones de ChromaDB, documentos (`rag.py:235-240`, `384-390`) y respuestas históricas (`rag.py:404`, `588`) (§3.4.3, I8; ronda focal) |

---

## 0. Resumen ejecutivo

Las escrituras del dashboard (crear o avanzar contextos, enviar tareas, registrar o renombrar
proyectos, purgar índices, importar sesiones) pasan hoy por 27 rutas POST que no tienen las
garantías que el servidor MCP ya da a los agentes: no son idempotentes, no quedan auditadas, no
respetan un alcance de proyectos configurado y no detectan que un agente cambió el mismo objeto
desde otro proceso. Este RFC propone:

1. **un único camino de comandos** para la UI (`POST /api/v1/commands/{name}`), con el catálogo
   de categorías de RFC-008, `request_id` obligatorio y durable, recibos (no resultados) para los
   reintentos, `expected_version` en lo que muta un objeto existente, admisión de presupuesto
   previa a cualquier llamada a un proveedor y auditoría equivalente a `mcp_invocations`;
2. **operaciones largas como trabajos** con etapas (spec §7), exclusión por recurso y un
   protocolo de reconciliación por tipo;
3. **identidad de proyectos** en SQLite: alias canónicos, identidades confirmadas para worktrees,
   clones y carpetas renombradas, fusión recuperable y movimiento de contextos, porque el uso real
   mostró que sin eso los datos se fragmentan y no hay forma segura de juntarlos.

Lo que este documento **no** afirma:

- no reemplaza el MCP: los agentes siguen usando RFC-008, que solo recibe la enmienda de
  categorías de §3.1;
- no abre el dashboard a la red ni agrega usuarios: sigue siendo local y de una persona (RFC-009);
- no decide la vista de varios proyectos a la vez (§15 de la especificación la deja fuera);
- no implementa el Event Log durable (§11, requiere su propio RFC), aunque el registro de
  comandos es compatible con él;
- no migra todavía ninguna vista heredada: eso lo hacen los PR de la ola 6 sobre este contrato.

## 1. El problema

### 1.1 Escrituras sin garantías

El handler de POST de `orchestrator/server.py` (desde la línea 834; tabla de rutas en 855-881)
despacha 27 rutas con efectos: 26 estáticas más `/context/{id}/delete`. Entre ellas
`/delete-contexts`, `/clear-imports`, `/advance-step`, `/skip-step`, `/create-context`,
`/project/rename`, `/add-project`, `/purge-chroma-docs`, `/sync-cc`, `/index-docs` y `/run` (que
llama a un proveedor de IA). RFC-009 las protegió contra CSRF (token, Origin, Host), pero:

| Falta | Consecuencia |
|---|---|
| Idempotencia | Un doble envío o un reintento tras un corte repite la escritura: por ejemplo, dos contextos creados con el mismo contenido. Las transiciones con precondición (`advance_step` exige `in_progress`) fallan en el segundo intento, pero la UI no sabe si el primero se aplicó. |
| Auditoría | Nada registra qué hizo la UI; Gobernanza solo ve lo que pasó por MCP. |
| Alcance de proyectos | Las rutas que reciben un proyecto validan, como mucho, que esté registrado; no hay un alcance configurable equivalente a `ORCHESTRATOR_MCP_PROJECTS`. |
| Control de concurrencia | Si un agente avanza un paso vía MCP mientras la persona lo mira, un comando de la UI actúa sobre un estado que ya no es el que vio. |
| Operaciones largas | `/sync-cc`, `/index-docs` o `/run-fix` corren dentro de la request. `/run` ya es asíncrono (202 + hilo + run pendiente), pero no tiene etapas ni reconciliación tras un reinicio. |
| Resultado incierto | `session_expired` se rechaza antes del despacho (`server.py:209-218`), así que ese caso es seguro. La incertidumbre aparece con un corte de red o un reinicio **después** de despachar: la UI no puede saber si la escritura ocurrió. |
| Presupuesto | `costs.check_budget` (`costs.py:94-106`) devuelve una advertencia y la CLI la muestra después del run (`cli.py:317-323`); nada impide una llamada que excede el límite. |

### 1.2 Identidad de proyectos: lo que mostró el uso real

Cuatro problemas aparecieron trabajando con el orquestador, no en un diseño:

**a) Alias fragmentados.** `orchestrator/watcher.py:_cwd_to_alias` (líneas 177-193) asigna una
sesión importada al proyecto registrado cuya ruta contiene a la carpeta de trabajo (el más
largo), y si no encuentra ninguno usa **el nombre de la carpeta**. Un `git worktree` o un clon de
trabajo viven en carpetas hermanas (`mi-proyecto-wt-feature`, `mi-proyecto-clon`), así que cada
uno queda bajo un alias propio en los datos importados. En una base local real (evidencia
local, no publicable), un solo repositorio terminó repartido en decenas de alias derivados de
worktrees y clones, con sus runs y costos fuera del proyecto.

**b) No se pueden juntar.** `ai-orchestrator rename` y `POST /project/rename`
(`cli.py:128-144`, `server.py:1246-1269`) llaman a `index.rename_project` (`index.py:52-59`), que:

- solo acepta alias **registrados en el índice** (los derivados de carpetas no lo están);
- **rechaza el destino si ya existe** ("ya está en uso"): no puede fusionar dos alias;
- actualiza `runs` y `contexts` (`db.rename_project_in_db`, `db.py:350-361`) pero no
  `mcp_invocations` ni `egress_decisions`, que también tienen `project`;
- no es atómico entre índice (YAML) y base (SQLite);
- se deshace en los datos: el próximo `sync` vuelve a importar sesiones de esa carpeta con el
  nombre viejo.

**c) Contextos en el proyecto equivocado.** En un workspace con repos anidados (un proyecto
raíz `mi-workspace` que contiene `mi-frontend` y `mi-backend`, cada uno con su propio alias),
registrar el tracking en el alias equivocado ya causó errores reales, al punto de que las
instrucciones del workspace lo prohíben explícitamente. No existe ningún comando para mover un
contexto (con sus pasos y lo vinculado) a otro proyecto: la única salida es SQL a mano.

**d) Vinculación de sesiones a pasos.** `db.get_active_step_id` (`db.py:559-574`) vincula cada
sesión importada al paso en curso del contexto activo **más reciente** del alias. La propia
especificación (§24.6) espera varios contextos activos en paralelo, así que las sesiones se
vinculan al paso de otra unidad o a ninguno. Junto con (a), explica por qué solo una fracción
chica de los runs importados queda vinculada a un paso y el costo por unidad no se puede medir.

## 2. Estado verificado del código

| Componente | implementation_status | evidence_status | Detalle |
|---|---|---|---|
| Seguridad del POST (token, Origin, Host, Content-Type) | implemented | verifiable | RFC-009; validación previa al despacho en `server.py` |
| Categorías y perfiles de herramientas MCP | implemented | verifiable | `mcp_governance.py:TOOL_CATEGORIES`, `PROFILE_CAPABILITIES`; RFC-008 define el catálogo cerrado de cinco categorías y `readonly` por defecto |
| `request_id` durable y reclamo de mutaciones | implemented (solo MCP) | verifiable | `mcp_governance.py:mutation_request_id`, `claim_mutation`, `complete_mutation` sobre `mcp_invocations`; guarda estado y hashes, **no** el resultado (RFC-008) |
| Auditoría de invocaciones | implemented (solo MCP) | verifiable | `mcp_governance.py:audit_invocation`; Gobernanza la lee (`api_v1/governance.py`) |
| Escrituras de la UI | implemented sin gobernanza | verifiable | 27 rutas en `server.py` (handler de POST) |
| `expected_version` / control de concurrencia | absent | none | Ninguna tabla guarda versión; `contexts.updated_at` no se actualiza en todas las mutaciones y mezcla offsets (spec §20.2) |
| Trabajos con etapas | partial | verifiable | `/run`: 202, hilo y run pendiente con SSE (`server.py:1722-1738`, `background.py:24-51`); el resto de las operaciones largas corre dentro de la request |
| Admisión de presupuesto | absent | verifiable | `costs.check_budget` solo advierte (`costs.py:94-106`) |
| Respaldo | partial | verifiable | `db.backup_database` (`db.py:868-875`) copia solo SQLite; el índice YAML no se respalda |
| Identidad de proyectos | partial | verifiable | Índice YAML (`index.py`, escritura directa en `save_index`, `index.py:32-35`); `watcher._cwd_to_alias` cae al nombre de carpeta; `rename` no fusiona |
| Mover contexto entre proyectos | absent | none | Sin comando ni endpoint |
| Vinculación de sesiones a pasos | partial | verifiable | `db.get_active_step_id` elige el contexto activo más reciente |
| Detección de cambios entre procesos | implemented | verifiable | `change_watch.py` (D4): `db_changed` con generación, por SSE |

## 3. Diseño propuesto

### 3.1 Endpoint, catálogo y perfil

```
POST /api/v1/commands/{name}
Headers: token de sesión, Origin, Content-Type (RFC-009)
Body: { "request_id": "<uuid generado por la UI>",
        "project": "mi-proyecto",
        "expected_version": <versión vista, si el comando muta un objeto existente>,
        "confirmation": "<hash de la vista previa, si el comando es destructivo>",
        "args": { ... según el esquema del comando ... } }
```

- **Catálogo único.** Cada comando declara nombre, categoría, esquema JSON de argumentos, si es
  un trabajo, si llama a un proveedor, si es destructivo y qué recursos toma (§3.3). Las
  categorías son las cinco de RFC-008 (`read`, `append`, `workflow_mutation`,
  `workflow_transition`, `memory_ingest`) más dos que este RFC agrega como **enmienda a RFC-008**:
  `project_admin` (identidad de proyectos, registro, fusión, mover contextos) y `maintenance`
  (purgas, reindexado, importaciones, reparación de datos).
- **Perfiles.** La UI usa los mismos perfiles que RFC-008. Tras la enmienda, **solo `admin`**
  concede `project_admin` y `maintenance` (en `PROFILE_CAPABILITIES`, `admin` deriva hoy de
  todas las categorías: `mcp_governance.py:36-41`); `readonly`, `observability`,
  `workflow_operator` y `memory_curator` no las conceden. Un agente MCP con `admin` también
  podría usarlas, con la misma auditoría.
- **Una implementación por operación.** Las herramientas MCP y los comandos son adaptadores de la
  misma función de dominio; no hay dos implementaciones de `advance_step`.
- **Perfil de la UI.** Fail-closed como RFC-008: sin configuración explícita, la UI es
  `readonly` (solo lee y muestra los comandos deshabilitados con el motivo). La persona habilita
  escrituras con un perfil y un alcance de proyectos declarados en la configuración local
  (`ai-orchestrator fix --ui-profile workflow_operator --ui-projects mi-proyecto`, por analogía con
  el bloque `env` del MCP). `project_admin` y `maintenance` además piden confirmación en la UI.
- **Respuesta.** `{ "status": "ok" | "denied" | "conflict" | "busy" | "error" | "accepted",
  "reason_code", "hint", "receipt", "job_id", "version" }`, con los mismos `reason_code` que el
  MCP cuando aplica (`capability_denied`, `project_out_of_scope`, ...) y nuevos para la UI
  (`version_conflict`, `resource_busy`, `budget_exceeded`, `confirmation_stale`).

### 3.2 Idempotencia, recibos y auditoría

- `request_id` es obligatorio y abre un **registro lógico** único del comando (mismo mecanismo
  que `claim_mutation`, cuyo `request_id` es único: `db.py:123-146`). Repetir el mismo
  `request_id` con los mismos argumentos **no repite el efecto**; la respuesta depende del estado
  del registro:

  | Estado del registro | Respuesta al reintento |
  |---|---|
  | `not_admitted` (recurso ocupado: `busy`) | se vuelve a evaluar la admisión: puede ejecutarse ahora o responder `busy` otra vez. `busy` no es terminal ni consume el `request_id` |
  | `queued` o `running` (trabajo) | `accepted` con el mismo `job_id` |
  | `interrupted` | recibo con estado `interrupted` (§3.3 dice si es seguro reintentar con otro `request_id`) |
  | terminal (`ok`, `denied`, `conflict`, `error`) | el recibo terminal registrado |

  Con argumentos distintos, `409 request_id_reused`.
- El **recibo** contiene estado terminal, IDs creados o afectados, versión resultante, conteos y
  hashes del resultado. Nunca el resultado completo ni texto libre: RFC-008 no guarda resultados
  por privacidad y este RFC mantiene esa regla. La UI vuelve a leer por la API lo que necesite
  mostrar.
- **Auditoría en dos niveles.** El registro lógico guarda el estado y los hashes del comando
  (formato de `mcp_invocations`, `client_surface = "dashboard"`); una tabla aparte, solo de
  agregar, guarda **cada intento** (fecha, estado devuelto, `reason_code`), incluidos los
  reintentos y los `409`. Gobernanza muestra ambos junto a las invocaciones MCP.

### 3.3 Trabajos, recursos y reconciliación

- Los comandos largos (`sync-*`, `index-docs`, `run-fix`, `purge-*`, `run`) responden
  `accepted` con un `job_id`. `/run` migra a este modelo en lugar de mantener su hilo propio.
- **Exclusión por recurso, no por tipo.** Cada comando declara los recursos que toma
  (`project:mi-proyecto:rag`, `project:mi-proyecto:workflow`, `imports`, `config`). Un comando que
  pide un recurso tomado por un trabajo en curso responde `busy` con el `job_id` que lo tiene.
- **TOCTOU.** La versión esperada y el alcance se comprueban al encolar **y** de nuevo al empezar
  la ejecución; si cambiaron, el trabajo termina en `conflict` sin efectos.
- **Etapas.** Cada trabajo publica sus etapas (spec §7) por SSE y deja su recibo al terminar.
- **Reinicio.** Al arrancar, todo trabajo `running` pasa a `interrupted`. Cada tipo de trabajo
  declara su **reconciliación**:

  | Tipo | Punto de commit | Tras `interrupted` |
  |---|---|---|
  | Mutaciones de workflow | Una transacción SQLite | Atómicas: se aplicaron o no; la UI relee y el recibo lo dice |
  | `sync-*` (importaciones) | Por sesión importada (`session_id` único) | Seguro reintentar: lo ya importado se saltea |
  | `index-docs`, `purge-*` | Por colección de ChromaDB | Reintentar reconstruye; la UI muestra el estado del índice antes de ofrecerlo |
  | `run` (proveedor) | Run pendiente → respuesta guardada | **No** se reintenta solo: puede haber costo y efecto externo. La UI muestra el run como interrumpido y la persona decide |

### 3.4 Identidad de proyectos

#### 3.4.1 Modelo

La identidad pasa a SQLite (tabla de proyectos e identidades), y el índice YAML queda como
registro de rutas que la persona edita con `add`/`remove`, sincronizado desde la base. Cada
identidad tiene: alias canónico, tipo (`registered`, `worktree`, `clone`, `folder`), evidencia
(ruta resuelta, directorio git común, remoto normalizado) y estado (`confirmed` o `proposed`).

#### 3.4.2 Resolución al importar

En orden, y deteniéndose en la primera coincidencia confirmada:

1. **límite del repositorio más específico** que contiene la carpeta (para que un repo anidado
   no caiga en el workspace padre);
2. identidad **confirmada** cuya ruta o directorio git común coincide;
3. ruta registrada que contiene a la carpeta;
4. si nada coincide, el nombre de la carpeta como identidad `folder`, y además se **proponen**
   candidatos: mismo directorio git común (worktree) o mismo remoto normalizado (clon). Un remoto
   igual **nunca asigna solo**: dos repositorios distintos pueden compartir remoto. La persona
   confirma en la UI y la confirmación queda persistida.

`git` se ejecuta con `subprocess` sin shell, rutas resueltas, tiempo límite y caché por ruta; si
falla o no hay remoto, se sigue con el paso siguiente. Symlinks se resuelven antes de comparar.

#### 3.4.3 Fusión recuperable (`project_admin`)

`merge_projects(source, target)`:

1. **Vista previa** con conteos por tabla (`runs`, `contexts`, `mcp_invocations`,
   `egress_decisions`, `chunks`), documentos de ChromaDB del alias origen y conflictos (por
   ejemplo, el mismo `session_id` en ambos). La vista
   previa tiene un hash; la ejecución lo exige en `confirmation` y falla con
   `confirmation_stale` si los datos cambiaron.
2. **Respaldo** de la base (`db.backup_database`) y del índice YAML.
3. **Una transacción SQLite** que actualiza todas las tablas con `project`, registra el origen
   como identidad confirmada del destino y deja una **intención durable** de actualización del
   índice.
4. Reescritura del YAML con archivo temporal y `replace`; al terminar, la intención se marca
   cumplida. Si el proceso cae entre 3 y 4, al arrancar se reconcilia: la intención pendiente se
   vuelve a aplicar (es idempotente).
5. **Plano RAG.** ChromaDB tiene dos colecciones con el alias: documentos del proyecto, que lo
   guardan en IDs y metadatos (`rag.py:235-240`) y se consultan filtrando por él
   (`rag.py:384-390`), y respuestas históricas de runs, indexadas y recuperadas por proyecto
   (`rag.py:588`, `rag.py:404`); las dos se inyectan en el contexto de ejecución. La misma
   transacción del paso 3 deja una **segunda intención durable**, de RAG, que un trabajo
   (`maintenance`, recurso `project:<destino>:rag`) cumple en **las dos colecciones**, migrando IDs
   y metadatos de forma idempotente, o reconstruyendo documentos y reindexando las respuestas de
   los runs del destino si la migración falla. Mientras esa intención esté pendiente, las
   consultas de documentos y de respuestas del destino incluyen también los alias equivalentes y
   la UI muestra el estado degradado (§7 de la especificación). Al arrancar, una intención RAG
   pendiente vuelve a encolarse.
6. Auditoría con los conteos.

`rename` pasa a ser el caso particular con destino inexistente.

#### 3.4.4 Mover un contexto (`project_admin`)

`move_context(context_id, target_project)` con `expected_version`, vista previa y confirmación:

- mueve el contexto y sus pasos, alineamientos y tool calls;
- mueve los runs vinculados a sus pasos (`runs.step_id`) y las decisiones de egress de esos runs
  (`egress_decisions.run_id`), para que `project` quede coherente;
- `parent_step_id` hacia o desde otro proyecto se muestra en la vista previa y solo se permite con
  confirmación explícita (la relación entre unidades de §24.6 puede cruzar proyectos a propósito);
- las invocaciones MCP históricas **no** se mueven: no tienen un vínculo verificable con el
  contexto, y reescribirlas falsearía la auditoría.

#### 3.4.5 Vinculación de sesiones a pasos

Al importar, si el alias tiene varios contextos activos, la sesión se vincula al paso en curso
del contexto que coincide con la rama o el worktree de la sesión cuando hay evidencia; si no,
queda **sin vincular y marcada como ambigua**, nunca en el contexto más reciente. La UI ofrece
vincularla a mano (`append`).

#### 3.4.6 Workspaces con repos anidados

La relación padre-hijo (`mi-workspace` contiene a `mi-frontend` y `mi-backend`) se guarda como
metadato de identidad. Al registrar tracking en el padre desde una carpeta que pertenece a un
hijo, la UI y el MCP avisan con un `hint`. No se agrega una vista combinada (§15).

### 3.5 Presupuesto y proveedores

Los comandos que llaman a un proveedor (`run`, y cualquier futuro) pasan por:

1. **admisión**: el costo estimado (modelo y tokens previstos según el catálogo de precios) se
   **reserva** contra el presupuesto del período; si la reserva lo excede, `denied` con
   `budget_exceeded` antes de crear el trabajo;
2. el **gate de egress** de RFC-006/007, igual que la CLI;
3. **conciliación**: al terminar, la reserva se reemplaza por el costo real del run.

### 3.6 Consistencia entre pestañas

Cada respuesta de la API lleva la **generación** de datos (`change_watch.current_generation()`,
D4) y la UI descarta una respuesta con generación menor que la última que ya mostró. Tras un
comando, la UI relee con la versión del recibo; `db_changed` refresca las demás pestañas.

### 3.7 Lo que falta además, según el uso real

Comandos del mismo catálogo, sin diseño propio:

- **cerrar o abandonar contextos activos huérfanos** (`workflow_transition`), con la advertencia
  `multiple_active_contexts` como entrada;
- **reparación de datos** acotada: corregir títulos o notas dañados de pasos y contextos con
  `expected_version` (`maintenance`), en lugar de SQL a mano;
- **reintento tras un corte**: como el `request_id` es durable, la UI reenvía el mismo comando
  (con la sesión nueva si el servidor se reinició) y obtiene el recibo si ya se aplicó.

## 4. Invariantes / Requisitos falsables

- **I1.** Una vez migrada su vista, ninguna escritura de la UI ocurre fuera de
  `POST /api/v1/commands/{name}`. Un test estático lista las rutas POST del servidor y falla si
  aparece una ruta que no está en el catálogo ni en el inventario de heredadas pendientes (§7).
- **I2.** Repetir un comando con el mismo `request_id` y los mismos argumentos no repite el
  efecto y responde según el estado del registro (§3.2): `accepted` con el mismo `job_id` si
  sigue en curso, o el mismo recibo si terminó o se interrumpió; con argumentos distintos
  responde `409`.
- **I3.** Cada `request_id` tiene exactamente un registro lógico y cada intento HTTP exactamente
  una fila de intento; ninguno guarda argumentos ni resultados en claro (solo hashes y
  metadatos), y ningún recibo contiene texto libre.
- **I4.** Sin configuración explícita de la UI, todo comando que no sea `read` responde `denied`
  (`capability_denied`), sin efectos; con perfil `workflow_operator`, los comandos
  `project_admin` y `maintenance` también responden `denied`; solo `admin` los permite.
- **I5.** Un comando sobre un proyecto fuera del alcance de la UI responde `denied` con
  `project_out_of_scope`, sin efectos.
- **I6.** Un comando con `expected_version` distinta de la actual responde `conflict` sin
  efectos; cualquier mutación de contextos o pasos (UI, MCP o CLI) incrementa su versión.
- **I7.** Un trabajo nunca queda `running` después de reiniciar el servidor: queda `done`,
  `failed`, `conflict` o `interrupted`; un `run` interrumpido no se reintenta sin acción de la
  persona.
- **I8.** `merge_projects` es recuperable: si el proceso cae en cualquier punto, tras el
  siguiente arranque la base y el índice quedan ambos con la fusión aplicada o ambos sin ella, y
  una intención RAG pendiente se vuelve a encolar; mientras está pendiente, las consultas RAG del
  destino (documentos y respuestas) devuelven también los del origen; y tras la fusión, importar
  una sesión desde
  una carpeta del alias origen la asigna al destino.
- **I9.** Una sesión importada desde un worktree de un proyecto registrado se asigna a ese
  proyecto; una sesión desde un clon con el mismo remoto queda como `folder` con una propuesta,
  nunca asignada sin confirmación.
- **I10.** Un repositorio anidado dentro de un workspace registrado se asigna a su propio alias
  si está registrado o confirmado, no al del workspace.
- **I11.** Con varios contextos activos en un alias, una sesión sin evidencia para desambiguar
  queda sin vincular y marcada como ambigua.
- **I12.** `move_context` deja `project` coherente en el contexto, sus pasos, los runs
  vinculados y sus decisiones de egress, y no modifica `mcp_invocations`.
- **I13.** Un trabajo comprueba versión y alcance al empezar a ejecutar; si cambiaron desde que se
  encoló, termina en `conflict` sin efectos.
- **I14.** Dos comandos que piden el mismo recurso no corren a la vez: el segundo responde `busy`,
  queda `not_admitted` y, reenviado con el mismo `request_id` cuando el recurso se libera, se
  ejecuta una sola vez.
- **I15.** Un comando que llama a un proveedor y cuya reserva excede el presupuesto responde
  `denied` (`budget_exceeded`) antes de cualquier llamada de red; todo comando que llama a un
  proveedor pasa por el gate de egress.
- **I16.** Un comando destructivo (borrados, purgas, fusión, mover) exige el hash de su vista
  previa y responde `confirmation_stale` si los datos cambiaron desde esa vista previa.

## 5. Alcance

**Dentro:** endpoint y catálogo de comandos, enmienda de categorías a RFC-008, recibos,
auditoría, idempotencia, versiones, trabajos con recursos y reconciliación, admisión de
presupuesto, consistencia entre pestañas, identidad de proyectos (modelo en SQLite, resolución
por repositorio, fusión recuperable, mover contexto, vinculación de sesiones, repos anidados) y
los comandos de mantenimiento de §3.7.

**Fuera pero cubierto por otro documento:** Event Log durable (§11 de la especificación, RFC
propio); seguridad del servidor HTTP (RFC-009); política MCP (RFC-008, salvo la enmienda de
§3.1).

**Fuera de esta ronda:** acceso remoto o multiusuario; vista de varios proyectos a la vez;
deshacer comandos (se evalúa con el Event Log); reatribuir invocaciones MCP históricas.

## 6. Riesgos

| Riesgo | Severidad | Mitigación |
|---|---|---|
| Doble implementación MCP/UI de la misma operación | Alta | Una función de dominio por operación; test que verifica que cada comando con equivalente MCP llama a la misma función |
| Fusión de proyectos errónea | Alta | Vista previa con hash obligatorio, respaldo de base e índice, transacción + intención durable + reconciliación, auditoría con conteos |
| Asignar sesiones a un proyecto equivocado por remoto compartido | Alta | El remoto solo propone; asigna únicamente la identidad confirmada o el directorio git común |
| Migraciones de esquema (`version`, identidades, auditoría, trabajos, reservas) | Media | PR propio con prueba de upgrade desde una base de la versión anterior y compatibilidad de lectura (spec §24.4) |
| `git` lento o ausente al importar | Media | Caché por ruta, tiempo límite y caída al comportamiento actual marcado como `folder` |
| Estimación de costo inexacta en la admisión | Media | La reserva usa el máximo de tokens previsto y se concilia con el costo real; el límite es configurable |
| Conflictos frecuentes con agentes trabajando | Baja | La UI muestra el estado actual y reintenta con un clic; `db_changed` (D4) ya refresca la vista |

## 7. Plan de implementación (tentativo, sujeto a la validación del RFC)

Cada PR con auditoría cruzada ANL-003 en dos rondas.

1. **Esquema.** `version` en `contexts` y `steps`; tablas de identidades de proyecto, auditoría
   de comandos, trabajos, intenciones y reservas de presupuesto; prueba de upgrade. Las
   mutaciones existentes (MCP y CLI) empiezan a incrementar la versión.
2. **Transición.** Inventario de las 27 rutas POST heredadas con dueño (vista), comando que la
   reemplaza y criterio de retiro; test de I1 que impide rutas nuevas fuera del catálogo; las
   heredadas siguen funcionando sin cambios de contrato hasta que su vista migre.
3. **Núcleo de comandos.** `orchestrator/commands/` (catálogo, despacho, perfil, alcance,
   idempotencia con recibos, auditoría) + `api_v1/commands.py` + configuración de la UI en
   `fix`/`doctor`; primeros comandos sin riesgo: `confirm_alignment`, notas de `update_step`,
   cerrar contexto. Tests de I2-I6.
4. **Trabajos y presupuesto.** Ejecutor con recursos, etapas por SSE y reconciliación al
   arrancar; `sync-*` e `index-docs` como trabajos; `run` migra con admisión de presupuesto. Tests
   de I7, I13-I15.
5. **Identidad de proyectos.** Resolución por repositorio, propuestas y confirmación,
   vinculación ambigua, `merge_projects` (incluida la intención RAG, que depende del ejecutor y
   la reconciliación del paso 4) y `move_context` con vista previa. Tests de I8-I12 e I16 con
   repositorios git sintéticos (worktree, clon y repo anidado) creados en el test, y prueba de
   caída en cada punto de la fusión.
6. **Ola 6 por vista.** Trabajo › Flujos, Ejecuciones › Actividad (envío de tareas), Ajustes ›
   Proyectos, Datos y Configuración: cada vista migra a comandos, retira sus rutas del inventario
   y baja su línea base de literales; al llegar a cero se borra el ensamblador heredado.

## 8. Criterios de merge

**De este RFC a `accepted`:**

- [ ] Auditoría cruzada (Codex) en dos rondas sin hallazgos bloqueantes.
- [ ] La persona responsable valida el alcance de §3.4 y §3.7, el perfil `readonly` por defecto y
      la enmienda de categorías a RFC-008.
- [ ] RFC-008 registra la enmienda en su metadata en el mismo PR que acepta este RFC.

**De cada PR de implementación:** sus invariantes con tests en verde, suite completa y, para los
PR con migración, la prueba de upgrade.

**Para afirmar valor de producto:** tras el PR 5, una fusión real de alias fragmentados ejecutada
por la persona sobre su base, con los conteos de la vista previa registrados como evidencia local
(sin nombres) en el tracking.

---

## Apéndice A — Referencias

- Especificación del dashboard: `docs/backlog/DASHBOARD_VISUALIZACION_ESPECIFICACION.md` (§7,
  §11, §15, §20.2, §24.4-§24.6 y "Diferido (después de D5)"), verificada en el commit de
  referencia.
- RFC-008 (`RFC-008-governed-mcp-access.md`: catálogo de categorías, perfil `readonly` por
  defecto, `request_id` sin resultados) y RFC-009 (`RFC-009-dashboard-local-security.md`).
- Código citado: `orchestrator/server.py`, `orchestrator/background.py`,
  `orchestrator/mcp_governance.py`, `orchestrator/watcher.py`, `orchestrator/db.py`,
  `orchestrator/index.py`, `orchestrator/costs.py`, `orchestrator/cli.py`,
  `orchestrator/change_watch.py`, `orchestrator/rag.py`, `orchestrator/migrate.py`, en el commit
  de referencia.
