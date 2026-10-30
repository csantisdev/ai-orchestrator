---
id: RFC-011
type: rfc
title: Políticas gobernadas de proyecto, invariantes de dominio y límites de desarrollo
status: draft
created: 2026-10-27
updated: 2026-10-29
supersedes: []
superseded_by: null
related: [RFC-007, RFC-008, RFC-009, RFC-010, RFC-012]
---

# RFC-011 — Políticas gobernadas de proyecto, invariantes de dominio y límites de desarrollo

**Estado:** Draft  
**Versión:** 0.4  
**Fecha:** 2026-10-29  
**Repo de referencia:** `csantisdev/ai-orchestrator@production` = `a9fc28edced0d5e3ee8e9bb3116bb6343a7c1171` (verificado 2026-10-29)  
**Relación con la serie:** Complementa RFC-007 (AI Control Plane), RFC-008 (acceso MCP gobernado), RFC-009 (seguridad local del dashboard) y RFC-010 (comandos gobernados desde la UI e identidad de proyectos). Si RFC-008 gobernó las capacidades de las herramientas y RFC-010 los comandos con efectos del dashboard, RFC-011 gobierna las **fronteras operativas del código y las reglas de dominio** sobre las cuales operan agentes y usuarios. No cambia ninguna decisión de RFC-008, RFC-009 ni RFC-010; la relación con cada uno está en §2.1.

*Todo ejemplo, PoC o fixture en este documento usa datos sintéticos (`mi-workspace`, `mi-frontend`, `mi-backend`, `/resources/{id}/approve`). Ver "Regla de anonimización" en `../README.md`.*

---

## Changelog

| Área | Antes | Ahora | Motivo |
|---|---|---|---|
| Evidencia de §1 (v0.2) | Ejemplos con rasgos operativos de un proyecto concreto | Ejemplos genéricos; YAML de §3.1 reemplazado por un servicio sintético | Regla de anonimización (repo público) |
| Estados de un paso (v0.2) | "Solo `pending`, `in_progress`, `completed`, `skipped`" | También `blocked` | Verificación contra `orchestrator/mcp.py:77` |
| Cierre automático (v0.2) | Solo `advance_step`, en `mcp.py:688-692` | `advance_step` (`mcp.py:899-908`) y `skip_step` (`mcp.py:697-706`) | Cita desactualizada y caso omitido |
| Relación con RFC-010 y el ctx #51 (v0.2) | "Complementa" | §2.1 delimita qué cubre cada uno | Evitar redefinir decisiones aceptadas |
| Aprobación de un gate (v0.3) | "Aprobación humana" por la UI de RFC-010 | "Confirmación registrada desde la UI local"; la atribución humana fuerte es la pregunta abierta P1 | RFC-009 establece que el token de sesión no autentica a clientes locales (auditoría Codex, ronda 1) |
| Alcance del gate (v0.3) | Solo `start_step` | Toda transición a `in_progress`: `start_step`, primer paso al crear un contexto, `advance_step` y `skip_step` (I4) | Ambas auditorías, ronda 1 |
| Modelo del gate (v0.3) | Booleano `requires_approval` sin vínculo con `release_gates` | Vínculo por nombre, aprobación atada a la versión del paso e invalidación al editarlo (§3.4) | Codex, ronda 1 |
| Herencia (v0.4) | El servidor recorre `parent_alias` y devuelve reglas o alias de ancestros | El proyecto declara en su propio `context.yaml` de qué proyectos toma reglas (`inherits_from`), que el agente lee del repositorio; ninguna respuesta MCP incluye `inherits_from` ni nada de otro proyecto, y el agente consulta cada alias por separado (§3.2, I3). Deja de depender del PR 5 de RFC-010 | RFC-008: "Contexto de otro proyecto MUST NOT entrar al payload ni a respuestas MCP"; una lista de ancestros también expone alias y relaciones (Codex, ronda 2) |
| I1 (v0.3) | Advertencia condicionada a que los pasos declaren archivos | I1 cubre la consulta de rutas protegidas con semántica definida; la advertencia al ejecutar queda en P3 | Un invariante no puede depender de una pregunta abierta (ambas auditorías) |
| Aprobación con evidencia (v0.3) | Confirmación manual con `preconditions` declarativas | RFC-011 define el gate y su bloqueo; cómo se aprueba (gates de entrada y salida, evidencia observada, modos `auto`/`manual`/`auto_then_manual`) pasa a RFC-012 | Decisión del dueño 2026-10-29: aprobar con evidencia empírica del flujo, no con análisis volátil |
| Contrato de aprobación (v0.4) | Aprobación atada solo a `step.id` y `step.version` | Contrato mínimo: `step_id`, `step_version`, `project`, `gate_name`, `policy_hash` y estado; se invalida si cambia cualquiera; validación y activación en la misma transacción (§3.4) | Un cambio de `release_gates` o un `move_context` dejaban viva una aprobación (Codex, ronda 2); permite aceptar RFC-011 sin RFC-012 |
| Forma (v0.3) | Tabla de §2 libre; §8 único; sin apéndice | Columnas de la plantilla, §8 separado y Apéndice A | `templates/RFC-TEMPLATE.md` |

---

## 0. Resumen ejecutivo

Hoy `ai-orchestrator` guarda en `context.yaml` convenciones de alto nivel (`conventions: list[str]`), preferencias de ruteo (`preferred_models`, `keyword_hints`), presupuesto (`daily_budget_usd`), parámetros del Egress Gate (`sensitivity`, `allowed_providers`, `blocked_providers`) y exclusiones RAG (`skip_dirs`); el estado de ejecución vive en SQLite (`runs.db`). Las **reglas de negocio**, los **límites de desarrollo ("no tocar")** y las **puertas de despliegue ("release gates")** dependen de que los agentes lean y respeten instrucciones de texto (`CLAUDE.md`, `AGENTS.md` o especificaciones de tarea por repositorio).

Delegar estas fronteras solo a la atención del modelo expone a:
1. Ediciones no autorizadas de archivos sensibles (secretos, configuración de despliegue).
2. Divergencia de terminología y reglas de dominio entre frontend y backend de un mismo workspace.
3. Pérdida de visibilidad de directivas vivas cuando un contexto se cierra solo al terminar su último paso.
4. Ausencia de un punto de detención formal antes de pasos de alto impacto (despliegues o migraciones).

Este RFC propone incorporar al Local AI Control Plane:
1. **Rutas protegidas (`protected_paths`)** y reglas de desarrollo, consultables vía MCP.
2. **Catálogo de invariantes de dominio y terminología**, consultable vía MCP (`get_domain_rules`).
3. **Políticas desacopladas del ciclo de vida de los contextos**, visibles aunque no haya contexto activo.
4. **Release gates en pasos**: un paso con gate no se activa hasta que tenga una aprobación vigente. Cómo se aprueba, con qué evidencia y en qué modo lo define RFC-012.

**Lo que este documento NO afirma:**
- No implementa un motor de ejecución de reglas de negocio dentro de las aplicaciones.
- No reemplaza las especificaciones de tarea que cada repositorio mantenga; las respalda con consultas al control plane.
- No introduce llamadas de red externas; toda evaluación de políticas es local y determinística.
- No autentica personas. Un gate frena a un agente que avanza por inercia (el MCP le responde `approval_required`); una aprobación manual por la UI no prueba que la registró una persona (RFC-009 §0). La atribución humana fuerte es la pregunta abierta P1.

---

## 1. El problema

La operación multiagente en workspaces con repositorios desacoplados muestra cinco brechas.

### 1.1 Brecha 1: Archivos protegidos ("no tocar")
Las instrucciones de una tarea suelen listar archivos que no deben modificarse (por ejemplo, `.env.*` con secretos o configuración de despliegue). Sin soporte en `ai-orchestrator`, el límite depende de que el agente lea la instrucción y la respete en cada sesión; un error solo se detecta después, al revisar el diff.

### 1.2 Brecha 2: Terminología e invariantes divergentes entre repositorios hermanos
En un workspace con frontend y backend independientes (`mi-frontend` y `mi-backend`), una decisión de dominio acordada en el backend (por ejemplo, que una entidad se llama `account` en la API y "cliente" en la UI, o que los registros archivados cuentan como inactivos en los reportes) queda aislada en ese repositorio. Una sesión que abre el frontend no tiene dónde consultar las reglas vigentes del ecosistema.

### 1.3 Brecha 3: Directivas perdidas por el cierre automático de contextos
`advance_step` (`orchestrator/mcp.py:899-908`) y `skip_step` (`orchestrator/mcp.py:697-706`) marcan `contexts.status='completed'` cuando no queda ningún paso `pending` ni `in_progress`. Como `get_context(project=...)` solo busca contextos `active` (`orchestrator/mcp.py:391`), una advertencia de freeze o una directiva de sesión guardada en la descripción del contexto deja de verse en la sesión siguiente.

### 1.4 Brecha 4: Políticas entre subproyectos de un workspace
Cuando un workspace raíz agrupa subproyectos, las reglas de dominio comunes viven en uno solo de ellos. RFC-010 ya cubre la identidad y el aviso al registrar tracking en el padre (§2.1); lo que queda para este RFC es cómo se heredan las **reglas de dominio** entre padre e hijo.

### 1.5 Brecha 5: Sin punto de detención para operaciones críticas (release gates)
Migraciones de base de datos, despliegues a producción o scripts de despliegue exigen autorización explícita del usuario. Hoy un paso pasa de `pending` a `in_progress` sin ninguna condición, ya sea con `start_step` o automáticamente al crear el contexto o al cerrar el paso anterior.

---

## 2. Estado verificado del código

Verificación contra `production@a9fc28edced0d5e3ee8e9bb3116bb6343a7c1171`:

| Componente | implementation_status | evidence_status | Detalle |
|---|---|---|---|
| Esquema `context.yaml` | partial | verifiable | `orchestrator/context.py:34-47`: `conventions` (lista plana), `keyword_hints`, `daily_budget_usd`, `sensitivity`, `blocked_providers`, `allowed_providers`, `skip_dirs`; `default_provider` y `routing_notes` se derivan de `preferred_models.default` y `.notes` (`orchestrator/context.py:89`). Sin rutas protegidas ni reglas de dominio. `load_context` no valida que cada convención sea texto (ctx #149). |
| Validación de rutas en MCP | absent | verifiable | Ninguna tool de `orchestrator/mcp.py` recibe ni valida las rutas que un paso pretende tocar; los pasos no declaran archivos. |
| Cierre automático de contexto | implemented | verifiable | `advance_step` (`orchestrator/mcp.py:899-908`) y `skip_step` (`orchestrator/mcp.py:697-706`) cierran el contexto si no quedan pasos `pending` ni `in_progress`. |
| Cierre manual con pasos abiertos | implemented | verifiable | `update_context` (`orchestrator/mcp.py:756`) acepta `completed`/`abandoned` sin verificar pasos abiertos. Es el X5 del ctx #51, distinto de la Brecha 3. |
| Visibilidad de contextos | implemented | verifiable | `get_context(project)` solo devuelve `active` (`orchestrator/mcp.py:391`); con `context_id` lee el contexto en cualquier estado. Estados: `active`, `programado`, `completed`, `abandoned`. |
| Activación de pasos | implemented | verifiable | Un paso pasa a `in_progress` en cuatro lugares: `start_step` (`orchestrator/db.py:702`), primer paso al crear un contexto (`orchestrator/db.py:751`, `:766`), `advance_step` con `activate_next` (`orchestrator/mcp.py:883`, `:893`) y `skip_step` con `activate_next` (`orchestrator/mcp.py:686`, `:693`). |
| Versión de pasos | implemented | verifiable | `steps.version` avanza de a uno por trigger en cada `UPDATE` (`orchestrator/migrate.py:224-231`, RFC-010). |
| Jerarquía | partial | verifiable | `contexts.parent_step_id` (`orchestrator/migrate.py:554-565`) relaciona contextos con pasos; `projects.parent_alias` (`orchestrator/migrate.py:238-243`) relaciona proyectos y se puebla en el PR 5 de RFC-010. |
| Estados de un paso | partial | verifiable | `pending`, `in_progress`, `completed`, `blocked`, `skipped` (`orchestrator/mcp.py:77`, `:536`). Sin atributo de gate ni registro de aprobación. |
| Catálogo de dominio | absent | verifiable | No existe modelo ni tabla para terminología o invariantes de negocio. |

### 2.1 Relación con RFC-008, RFC-009, RFC-010 y el contexto #51

- **RFC-010 §3.4.6 e I10** definen la relación padre-hijo (`projects.parent_alias`), asignan un repo anidado a su propio alias **si está registrado o confirmado** y avisan con un `hint` cuando se registra tracking en el padre desde una carpeta del hijo. RFC-011 no redefine nada de eso.
- **RFC-010 §3.4.4 (`move_context`)** permite `parent_step_id` entre proyectos con confirmación explícita. RFC-011 **no** restringe ese vínculo: sus reglas aplican a las políticas, no a la relación entre contextos.
- **RFC-009 §0**: el token de sesión del dashboard protege contra páginas web abiertas en el navegador (CSRF, DNS rebinding, clickjacking) y **no autentica a clientes locales**: cualquier proceso que pueda conectarse a `127.0.0.1` puede leerlo del HTML y usarlo. Por eso una aprobación manual por la UI se trata como "registrada desde la UI local", no como "aprobación humana".
- **RFC-010 (comandos gobernados)** aporta lo que un gate necesita además de la autenticación: vista previa, versión esperada, idempotencia y auditoría. Es el canal de la aprobación manual (§3.4, RFC-012).
- **RFC-008**: el scope MCP se autoriza por proyecto y "contexto de otro proyecto MUST NOT entrar al payload ni a respuestas MCP". Ninguna tool de este RFC devuelve datos de un proyecto distinto del consultado, ni siquiera su alias o su relación con el consultado (§3.2, I3).
- **El X5 del ctx #51** (cierre manual de contextos con pasos abiertos vía `update_context`) es un defecto distinto de la Brecha 3 y queda fuera de este RFC.
- **Orden respecto del PR 5 de RFC-010**: ninguno de los dos depende del otro. La herencia de reglas se declara en el `context.yaml` del proyecto (`inherits_from`), no se deriva de `projects.parent_alias`. Un `move_context` sí afecta a los gates: invalida las aprobaciones de los pasos movidos (§3.4).

---

## 3. Diseño propuesto

```text
                           PROJECT REPOSITORY
                     .orchestrator/context.yaml
                                 │
           ┌─────────────────────┼─────────────────────┐
           ▼                     ▼                     ▼
    development_rules      domain_rules          release_gates
  ├── protected_paths    ├── terminology       ├── approval (RFC-012)
  └── prohibited_mods    └── invariants        └── checks (RFC-012)
           │                     │                     │
           └─────────────────────┼─────────────────────┘
                                 ▼
                    ORCHESTRATOR CONTROL PLANE
                                 │
        ┌────────────────────────┴────────────────────────┐
        ▼                                                 ▼
   MCP (read)                                     Aprobación (RFC-012)
├── get_project_policies()                      ├── evaluador de evidencia (auto)
└── get_domain_rules()                          └── comando de la UI (manual, RFC-010)
```

### 3.1 Extensión de `.orchestrator/context.yaml`

Secciones nuevas, todas opcionales:

```yaml
name: mi-backend
stack: Python/FastAPI
description: Servicio sintético de facturación.

development_rules:
  protected_paths:
    - pattern: ".env.*"
      reason: "Contiene secretos de entorno; requiere autorización explícita."
    - pattern: "deploy/**"
      reason: "Configuración de despliegue; no se modifica desde una tarea de desarrollo."
  prohibited_modifications:
    - "No instalar dependencias sin confirmación previa."
    - "No refactorizar fuera del alcance de la tarea."

domain_rules:
  inherits_from: ["mi-workspace"]   # lo lee el agente del repositorio; nunca se devuelve por MCP
  terminology:
    - term: "account"
      alias_in_ui: "cliente"
      notes: "En API y base de datos siempre 'account'; en la UI siempre 'cliente'."
  invariants:
    - name: "archived_reporting"
      rule: "Los registros archivados se informan como inactivos; nunca se omiten de los reportes."

release_gates:
  production_deploy:
    approval: auto_then_manual      # semántica en RFC-012
    checks:                         # chequeos con evidencia observada, RFC-012
      - "tests_passed"
      - "ci_green"
```

Semántica de `protected_paths.pattern`: glob relativo a la raíz del proyecto, con `/` como separador, `**` para cualquier profundidad y comparación sensible a mayúsculas; las rutas se normalizan (sin `.` ni `..`) antes de comparar y los enlaces simbólicos no se resuelven.

### 3.2 Tools MCP de consulta (categoría `read`)

1. **`get_project_policies(project)`**: `development_rules`, `release_gates` y `conventions` del proyecto, leídas del `context.yaml` en el momento de la llamada (P4). Responde siempre que el proyecto esté en `ORCHESTRATOR_MCP_PROJECTS`, haya o no contexto activo.
2. **`get_domain_rules(project, category?)`**: `terminology` e `invariants` **del proyecto consultado**, tal como están en su `context.yaml`. La respuesta nunca incluye `inherits_from` ni ningún alias, regla o relación de otro proyecto (RFC-008 §14, "Datos y egress"). Para heredar, el agente lee `inherits_from` del `context.yaml` de su repositorio y llama a `get_domain_rules` por cada alias; cada llamada se autoriza por separado según `ORCHESTRATOR_MCP_PROJECTS`, y las que caen fuera de scope responden `denied` como cualquier otra.

Solo `domain_rules` se hereda, y solo por declaración explícita. `protected_paths`, `prohibited_modifications` y `release_gates` son locales a cada proyecto: un hijo que quiera las mismas reglas las declara.

Ambas tools son de solo lectura, sin efectos ni llamadas de red, y se registran en `TOOL_CATEGORIES` de `orchestrator/mcp_governance.py` como `read`.

### 3.3 Políticas visibles aunque el contexto se cierre

Las políticas viven en `context.yaml`, no en la descripción de un contexto, así que `get_project_policies` no depende del estado de ningún contexto. El cierre automático de `advance_step` y `skip_step` se mantiene (P2, propuesta base). Esto no resuelve el X5 del ctx #51.

### 3.4 Release gates en pasos

RFC-011 define **qué** es un gate y **dónde** bloquea; **cómo** se aprueba lo define RFC-012 (aprobación basada en evidencia observada del flujo, gates de entrada y de salida, modos `auto`, `manual` y `auto_then_manual`).

- **Vínculo:** un paso declara el gate por nombre (`steps.gate`, que referencia una clave de `release_gates` del proyecto del contexto). Un nombre que no existe en `release_gates` se rechaza al asignarlo.
- **Activación:** ningún camino activa un paso con gate sin una aprobación vigente: `start_step` responde `denied` con `reason_code: "approval_required"`; al crear un contexto, `advance_step` y `skip_step`, el paso con gate queda `pending` y la respuesta lo indica con `approval_required`, sin activar otro paso en su lugar (I4).
- **Contrato mínimo de una aprobación** (independiente de cómo se obtenga, que define RFC-012): `step_id`, `step_version`, `project` del contexto, `gate_name`, `policy_hash` (hash de la definición del gate en `release_gates` al aprobar) y `status` (`valid` o `invalidated`). Una aprobación es vigente solo si los cinco primeros coinciden con el estado actual: un cambio que incremente la `version` del paso, un `move_context` (RFC-010 §3.4.4) o un cambio de la definición del gate la invalidan.
- **Atomicidad:** la verificación de la aprobación vigente y el cambio a `in_progress` ocurren en la misma transacción de SQLite; si la aprobación deja de ser vigente entre la lectura y la escritura, el paso no se activa.
- **Sin productor, sin activación:** hasta que exista un mecanismo que emita aprobaciones con este contrato (RFC-012), un paso con gate no se activa por ningún camino.
- **Canal:** ninguna tool MCP registra ni revoca aprobaciones (I5). Una aprobación automática la emite el evaluador del orquestador a partir de evidencia observada, nunca el agente; una manual se registra desde la UI con un comando de RFC-010. Por RFC-009 §0, la manual prueba que pasó por la UI local, no que la registró una persona (P1).

---

## 4. Invariantes falsables

- **I1 (Rutas protegidas consultables):** `get_project_policies(project)` devuelve cada entrada de `development_rules.protected_paths` con su `pattern` y su `reason`, y una ruta coincide con un patrón exactamente según la semántica de §3.1 (glob relativo a la raíz, `/`, `**`, normalización, sin resolver enlaces). La advertencia al registrar o ejecutar un paso queda sujeta a P3.
- **I2 (Políticas siempre disponibles, condicional a P4):** con la propuesta base de P4 (`context.yaml` como fuente de verdad), `get_project_policies(project)` devuelve el contenido actual de `context.yaml` aunque todos los contextos del proyecto estén `completed`, `abandoned` o `programado`, o no exista ninguno. Si P4 se resuelve de otra forma, I2 se reescribe antes de implementar la fase 2.
- **I3 (Herencia declarada, sin datos de otro proyecto):** la respuesta de `get_domain_rules(project)` contiene solo `terminology` e `invariants` del `context.yaml` de `project`; nunca contiene `inherits_from` ni reglas, alias o relaciones de otro proyecto. La precedencia documentada para el agente es: ante un `term` o un `name` de invariante repetido, gana la regla del proyecto consultado sobre la heredada y, entre heredadas, la del primer alias de `inherits_from`. Esto resuelve solo colisiones de nombre; dos invariantes con nombres distintos y contenido incompatible no se detectan.
- **I4 (Gate bloqueante en toda activación):** ningún paso con gate pasa a `in_progress` sin una aprobación vigente según el contrato de §3.4 (paso, versión, proyecto, gate y `policy_hash`), verificada en la misma transacción que la activación, sea por `start_step`, al crear el contexto, por `advance_step` o por `skip_step`, desde MCP, CLI o dashboard.
- **I5 (Aprobación fuera de MCP):** ninguna tool MCP registra ni revoca la aprobación de un gate; un intento responde `denied`.
- **I6 (Determinismo local):** la carga y evaluación de políticas usa solo archivos locales y SQLite, sin llamadas de red.
- **I7 (Compatibilidad):** con un `context.yaml` sin las secciones nuevas y pasos sin gate, las tools MCP existentes devuelven los mismos campos y las mismas transiciones de estado que hoy, `load_context` carga los mismos valores y ninguna llamada responde `approval_required`. El perfil MCP (RFC-008) sigue gobernando qué tools se pueden llamar.

---

## 5. Alcance

### 5.1 Incluido
- Esquema ampliado de `context.yaml` (`development_rules`, `domain_rules`, `release_gates`) y su validación en `orchestrator/context.py`.
- Tools MCP de solo lectura `get_project_policies` y `get_domain_rules`.
- Columna `steps.gate` y verificación en las cuatro activaciones (I4), consumiendo las aprobaciones de RFC-012.
- Comprobaciones en `ai-orchestrator doctor` para políticas mal formadas y gates inexistentes.

### 5.2 Fuera de alcance
- Hooks de git o intercepción de escrituras a nivel del sistema de archivos.
- Cómo se aprueba un gate: evidencia, evaluadores, gate de salida y modos de aprobación (RFC-012).
- Autenticación de personas (P1).
- Motor de inferencia sobre reglas de negocio.
- Cambios al Egress Gate (RFC-006) o a la relación `parent_step_id` entre proyectos (RFC-010 §3.4.4).
- El X5 del ctx #51.

---

## 6. Riesgos y mitigaciones

| Riesgo | Severidad | Mitigación |
|---|---|---|
| Sobrecarga de configuración en `context.yaml` | Media | Todas las secciones nuevas son opcionales (I7). |
| Clientes MCP anteriores | Baja | Tools nuevas puramente aditivas; `get_context` mantiene su esquema. |
| Gates que traban flujos ágiles | Media | Solo aplican a pasos declarados con gate. |
| Falsa sensación de protección por rutas | Media | I1 es una consulta, no un bloqueo de escrituras; la documentación lo dice. |
| Aprobación registrada por un proceso local | Alta | I5 cierra el canal MCP; RFC-012 exige evidencia observada; el riesgo restante de la aprobación manual (un proceso con acceso al dashboard) se declara en §0 y queda en P1. |
| Gate salteado por una activación automática | Alta | I4 cubre las cuatro vías de activación. |
| Fuga de datos de otro proyecto | Media | Las respuestas solo traen lo declarado en el `context.yaml` del proyecto consultado; la herencia se resuelve con llamadas separadas, cada una autorizada por scope (§3.2, I3). |
| Aprobación que sobrevive a un cambio | Alta | Contrato de §3.4: se invalida si cambia la versión del paso, el proyecto o la definición del gate, y se verifica en la misma transacción que la activación. |

---

## 7. Plan de implementación (tentativo, sujeto a la validación del RFC)

1. **Esquema y parser:** extender `ProjectContext` y validar las secciones nuevas, en un `tests/test_context.py` nuevo (hoy no existe; los tests de `context.py` están repartidos en otros archivos).
2. **Tools MCP de políticas:** `get_project_policies` (I1, I2) y `get_domain_rules` (I3).
3. **Release gates:** migración de `steps.gate` y de la tabla de aprobaciones con el contrato de §3.4, invalidación ante cambio de versión, proyecto o `policy_hash`, verificación atómica en las cuatro activaciones (I4) y rechazo por MCP (I5). Se puede implementar antes de RFC-012: sin un productor de aprobaciones, los pasos con gate no se activan.
4. **Diagnóstico:** comprobaciones en `ai-orchestrator doctor`.

Cada fase es un PR con la auditoría de ANL-003 y sus invariantes con tests.

---

## 8. Criterios de merge

**De este RFC a `accepted`:**
- [ ] Front matter validado por `scripts/validate_decision_docs.py`.
- [ ] Regla de anonimización verificada: ningún identificador, dominio ni combinación de rasgos de un proyecto real, en el documento ni en fixtures.
- [ ] Auditoría de ANL-003 en dos rondas sin hallazgos abiertos.
- [ ] Preguntas abiertas de §9 resueltas o diferidas explícitamente por el dueño.

**De cada PR de implementación:**
- [ ] Tests de los invariantes que cubre la fase (I1-I7).
- [ ] Tests de pureza STDIO en `tests/test_mcp.py` para las tools nuevas.
- [ ] `python -m pytest tests/` completo en verde y validadores que correspondan.

---

## 9. Preguntas abiertas

- **P1. Atribución humana de la aprobación manual.** Con el modelo actual (RFC-008 y RFC-009), ningún canal local acredita que quien confirma es una persona: un perfil MCP lo fija quien lanza el proceso, el token del dashboard lo puede leer cualquier proceso local y la CLI la puede correr un agente con terminal. Opciones: (a) aceptar "aprobación registrada desde la UI local" como garantía suficiente, apoyada en la evidencia observada de RFC-012 (frena al agente que avanza por inercia, no a uno que arma pedidos al dashboard); (b) agregar un factor que un agente no tenga (un secreto que solo tipea la persona, o un factor fuera de la máquina), con su propio RFC. Propuesta base: (a), dejando (b) para cuando se pida atribución fuerte.
- **P2. Cierre automático.** Opciones: (a) mantenerlo, ya que las políticas dejan de depender del contexto (§3.3); (b) un estado nuevo (`idle`), que afecta al dashboard, a las proyecciones y a `tracking_health`; (c) un aviso en `workflow_state`. Propuesta base: (a).
- **P3. Declaración de archivos de un paso.** Para advertir al registrar o ejecutar un paso que toca rutas protegidas, el paso tiene que declarar sus rutas (campo nuevo o parte de su especificación) y una tool tiene que evaluarlas. Hasta decidirlo, I1 cubre solo la consulta.
- **P4. Fuente de verdad de las políticas.** Propuesta base: `context.yaml` leído en cada llamada (I2). Un reflejo en SQLite para consultas entre proyectos queda para cuando haga falta. Nota: en este repo `.orchestrator/` está en `.gitignore`, así que sus políticas no se versionan.
- **P5. Herencia implícita por jerarquía.** Derivar la herencia de `projects.parent_alias` en el servidor exige devolver datos de otro proyecto y, por lo tanto, una enmienda explícita a RFC-008. Lo mismo vale para devolver `inherits_from` por MCP. Propuesta base: no hacerlo; la herencia se declara en `inherits_from` y el agente la lee del repositorio.

---

## Apéndice A — Referencias

Verificadas contra `production@a9fc28edced0d5e3ee8e9bb3116bb6343a7c1171` el 2026-10-29:

- `orchestrator/context.py:34-47`, `:89` — campos de `ProjectContext` y derivación de `preferred_models`.
- `orchestrator/mcp.py:77`, `:536` — estados de un paso.
- `orchestrator/mcp.py:391` — `get_context(project)` solo devuelve contextos `active`.
- `orchestrator/mcp.py:686`, `:693`, `:697-706` — `skip_step`: activación del siguiente y cierre automático.
- `orchestrator/mcp.py:756` — `update_context` sin verificación de pasos abiertos (X5 del ctx #51).
- `orchestrator/mcp.py:883`, `:893`, `:899-908` — `advance_step`: activación del siguiente y cierre automático.
- `orchestrator/db.py:702`, `:751`, `:766` — `start_step` y `activate_first_step`.
- `orchestrator/migrate.py:224-231` — versión de `steps` por trigger.
- `orchestrator/migrate.py:238-243` — tabla `projects` con `parent_alias`.
- `orchestrator/migrate.py:554-565` — columna `contexts.parent_step_id`.
- `orchestrator/mcp_governance.py` — `TOOL_CATEGORIES` y categorías solo para administración.
- `docs/decisions/rfcs/RFC-009-dashboard-local-security.md` §0 — el token no autentica clientes locales.
- `docs/decisions/rfcs/RFC-010-governed-ui-commands.md` §3.4.4, §3.4.6, I10, I16.
- `docs/decisions/rfcs/RFC-008-governed-mcp-access.md` — scope por proyecto y categorías.
- `docs/decisions/analyses/ANL-003-per-change-cross-audit.md` — protocolo de auditoría.
