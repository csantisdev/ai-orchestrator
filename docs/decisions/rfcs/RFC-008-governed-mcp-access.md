# RFC-008 — Acceso MCP gobernado y superficie remota del Local AI Control Plane

**Estado:** Draft para validación final  
**Versión:** 0.1  
**Fecha:** 2026-07-11  
**Repositorio de referencia:** `github.com/csantisdev/ai-orchestrator`  
**Fuente de verdad de código:** rama `production`, commit `e0189a3827f82524942cecaa3929a9c0ddd24487`  
**Documento base:** RFC-007 v0.3  
**Relación documental:** complementa RFC-005 y RFC-006; reemplaza y profundiza RFC-007 §6, y enmienda sus requisitos de red, roadmap y riesgos. No reemplaza el posicionamiento PGDP ni el diseño del Egress Gate.

**Navegación rápida:** estado verificado (§3) · decisiones (§4) · arquitectura (§5) · capabilities (§7) · provenance (§8) · consistencia (§9) · acceso y configuración (§11) · roadmap (§13) · pruebas (§15) · prompt para Claude (§19).

---

## Changelog de diseño respecto de RFC-007 v0.3

| Área | RFC-007 v0.3 | RFC-008 |
|---|---|---|
| Acceso MCP local | SSH-stdio como patrón principal | Se reconoce STDIO directo para ChatGPT Desktop, Codex CLI/IDE y Claude Code como vía inmediata y preferida en el mismo host |
| Acceso OpenAI remoto | Streamable HTTP como work package futuro | Se incorpora Secure MCP Tunnel como adaptador privado capaz de envolver el STDIO existente sin publicar un listener |
| Streamable HTTP | Presentado como evolución necesaria para MCP remoto | Se mantiene como opción futura de interoperabilidad; deja de ser requisito para una primera conexión remota con superficies OpenAI compatibles |
| Modelo de herramientas | Doce tools tratadas como conjunto uniforme | Clasificación normativa: lectura, append/auditoría, mutación de workflow e ingestión de memoria |
| Aprobaciones | Delegadas al cliente | Defensa dual: hints para el cliente + autorización obligatoria en el servidor |
| Provenance MCP | No modelado | Se incorpora identidad de cliente, transporte, actor, tool, hashes, política, correlación e idempotencia |
| SQLite | Riesgo de concurrencia descrito genéricamente | Se corrige el diagnóstico: WAL ya está habilitado; faltan `busy_timeout`, coordinación entre procesos, transacciones e idempotencia |
| Seguridad MCP | Autenticación solo para transporte de red | Se separan autenticación de transporte, autorización de capability y política de datos/proyecto |
| Implementación | WP-Net-2 amplio | Plan incremental que endurece primero el servidor STDIO actual y conserva `python -m orchestrator.mcp` |
| Validación | Métricas generales | Matriz de pruebas, criterios de aceptación y prompt final para revisión independiente con Claude |

---

## 0. Resumen ejecutivo

`ai-orchestrator` ya contiene un servidor MCP funcional, implementado manualmente sobre JSON-RPC y transporte STDIO. Puede ser lanzado hoy como subproceso local por clientes compatibles, sin abrir puertos ni convertirlo a HTTP.

La decisión central de este RFC es:

> **MCP no debe incorporarse como un bypass conveniente al Local AI Control Plane. Debe convertirse en una superficie gobernada del mismo control plane, con autorización por capability, aislamiento por proyecto, provenance de cada invocación e idempotencia para toda mutación.**

La ruta recomendada es:

1. Conectar y probar el STDIO actual en modo lectura.
2. Corregir metadata, validación, control de tools y auditoría.
3. Integrarlo con Policy Engine y Decision/Evidence Plane.
4. Usar SSH-stdio o Secure MCP Tunnel cuando se necesite acceso privado desde otro host o una superficie OpenAI remota compatible.
5. Implementar Streamable HTTP solo cuando exista una necesidad concreta de interoperabilidad o multiusuario que no cubran los adaptadores anteriores.

Este RFC **no autoriza** publicar el dashboard ni el servidor MCP en `0.0.0.0` sin autenticación. Tampoco afirma que exista todavía un runtime autónomo multiagente.

---

## 1. Lenguaje normativo

Los términos **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT** y **MAY** se usan en sentido normativo.

- **MUST / MUST NOT:** requisito bloqueante para declarar la capacidad segura.
- **SHOULD / SHOULD NOT:** recomendación fuerte; cualquier excepción exige justificación documentada.
- **MAY:** opción válida, no obligatoria.

---

## 2. Alcance

### 2.1 Incluido

- Conexión del MCP actual a ChatGPT Desktop, Codex y Claude Code mediante STDIO.
- Acceso cross-host mediante SSH-stdio.
- Acceso privado a superficies OpenAI compatibles mediante Secure MCP Tunnel.
- Requisitos para un futuro transporte Streamable HTTP.
- Clasificación y control de las doce tools existentes.
- Identidad, autorización, provenance, auditoría e idempotencia.
- Concurrencia SQLite y consistencia de workflow.
- Integración de MCP con PGDP, Policy Engine, RAG y Evidence Plane.
- Pruebas y criterios de aceptación.

### 2.2 Fuera de alcance

- Convertir MCP en protocolo agente-a-agente.
- Exponer un servidor público en Internet.
- Reemplazar el Egress Gate.
- Construir un sandbox general de shell, red, Git o navegador.
- Implementar una UI MCP App dentro de ChatGPT.
- Migrar obligatoriamente al SDK oficial de MCP en esta fase.
- Resolver autenticación empresarial completa antes del primer smoke test local.

---

## 3. Estado verificado de `production`

Verificación realizada contra `production@e0189a3` el 2026-07-11.

### 3.1 Servidor MCP

| Propiedad | Estado verificado |
|---|---|
| Entrada | `python -u -m orchestrator.mcp` |
| Transporte | STDIO puro; lee JSON-RPC línea a línea desde `stdin` y responde por `stdout` |
| Protocolos declarados | `2024-11-05`, `2025-03-26`, `2025-06-18` |
| Protocolo por defecto | `2025-06-18` |
| Capacidad declarada | `tools`, con `listChanged: false` |
| Tools | 12 |
| Listener de red | No existe |
| Autenticación propia | No existe |
| Identidad del cliente/actor | No se registra |
| Tool annotations | No existen |
| `outputSchema` | No existe |
| Validación JSON Schema server-side | No existe; el schema se anuncia, pero los handlers validan de forma manual e incompleta |
| Auditoría de invocación real | No existe; `record_tool_call` depende de que el agente decida llamarla |
| Idempotencia general | No existe; `import_agent_context` solo puede deduplicar cuando llega `session_id` |
| Control de tools por perfil | No existe |
| Filtro por proyecto impuesto por sesión | No existe |

### 3.2 Tools existentes

| Tool | Efecto actual | Clasificación propuesta | Riesgo |
|---|---|---|---|
| `get_context` | Lee contexto activo | `read` | Bajo, condicionado por aislamiento de proyecto |
| `list_steps` | Lee pasos | `read` | Bajo |
| `list_agents` | Lee presets globales | `read` | Bajo/medio; expone configuración lógica |
| `confirm_alignment` | Inserta checkpoint | `append` | Medio; genera evidencia atribuida a un agente |
| `record_tool_call` | Inserta tool call declarado | `append` | Medio; puede falsificar telemetría si no se distingue de invocación observada |
| `create_context` | Crea contexto y pasos | `workflow_mutation` | Alto |
| `add_step` | Agrega paso | `workflow_mutation` | Medio/alto |
| `update_context` | Modifica título, descripción o estado | `workflow_mutation` | Alto |
| `update_step` | Modifica contenido/asignación | `workflow_mutation` | Alto |
| `advance_step` | Completa paso y activa el siguiente | `workflow_transition` | Alto; requiere atomicidad e idempotencia |
| `skip_step` | Omite paso y puede activar otro | `workflow_transition` | Alto; semánticamente destructiva |
| `import_agent_context` | Inserta run e indexa respuesta en RAG | `memory_ingest` | Crítico; puede contaminar memoria y provenance |

### 3.3 Persistencia SQLite

El diagnóstico correcto es:

- `PRAGMA journal_mode=WAL` **ya está habilitado**.
- `PRAGMA foreign_keys=ON` ya está habilitado.
- Existe un `threading.Lock`, pero es **solo intra-proceso**.
- Cada proceso obtiene su propia conexión y su propio lock.
- No existe `PRAGMA busy_timeout` explícito.
- No existe idempotencia transversal para mutaciones.
- Algunas transiciones hacen read-modify-write y requieren garantías de atomicidad frente a clientes concurrentes.

Por tanto, WAL no cierra por sí solo el riesgo de:

- `database is locked` bajo presión;
- dos clientes avanzando el mismo step;
- reintentos que repiten una mutación;
- estados incompatibles entre `steps` y `contexts`;
- una escritura en SQLite completada mientras la indexación Chroma falla silenciosamente.

### 3.4 Dashboard

- Continúa ligado a `127.0.0.1`.
- No tiene autenticación.
- Puede exportar prompts y respuestas completas.
- Posee múltiples endpoints POST destructivos o mutables.
- Su binding a loopback es actualmente el control de seguridad principal.

### 3.5 Deudas críticas previas que permanecen bloqueantes

- `routing_source` no existe en `runs`.
- `_fetch_similar_runs()` recupera runs similares sin scope obligatorio de proyecto.
- El router LLM externo sigue siendo egress previo al gate.
- El Egress Gate y Provider Gateway sellado continúan sin evidencia pública en `production`.

MCP no debe utilizarse para ocultar ni posponer estas deudas.

---

## 4. Correcciones y decisiones respecto de RFC-007

### D1 — STDIO directo es la vía preferida en el mismo host

ChatGPT Desktop, Codex CLI/IDE y Claude Code pueden lanzar servidores MCP STDIO como procesos locales. Por tanto, el servidor actual puede conectarse sin cambios de transporte.

**Decisión:** documentar STDIO directo como patrón soportado de desarrollo local.

### D2 — SSH-stdio sigue siendo válido cross-host

Un cliente MCP capaz de lanzar procesos puede ejecutar `ssh host-A <comando-mcp>` y usar el canal como stdin/stdout.

**Decisión:** mantener SSH-stdio como patrón soportado para otro equipo bajo control del usuario.

### D3 — Secure MCP Tunnel reduce la urgencia de Streamable HTTP

Secure MCP Tunnel puede ejecutar o alcanzar un servidor privado por STDIO/HTTP desde dentro de la red, usando solo salida HTTPS hacia OpenAI.

**Decisión:** incorporarlo como opción de acceso privado a superficies OpenAI compatibles. Su disponibilidad depende de cuenta, organización, workspace y permisos; no debe asumirse universal.

### D4 — Streamable HTTP es evolución, no prerrequisito

Streamable HTTP sigue siendo útil para interoperabilidad, multiusuario y despliegues independientes, pero no es necesario para el primer uso local ni para un túnel que envuelva STDIO.

**Decisión:** implementar WP-MCP-HTTP únicamente después de Policy Engine, autorización y ledger MCP.

### D5 — Hints del cliente no equivalen a autorización

`readOnlyHint`, `destructiveHint` e indicadores similares ayudan al cliente a decidir aprobaciones, pero son metadata no confiable y no impiden llamadas directas.

**Decisión:** aplicar defensa dual:

1. **Tool discovery filtering:** no mostrar una tool no autorizada.
2. **Invocation enforcement:** volver a autorizar en cada `tools/call`.

### D6 — Una tool MCP no se audita llamando otra tool MCP

`record_tool_call` es un evento declarado por el agente; no es evidencia de que el servidor observó una invocación real.

**Decisión:** cada `tools/call` MUST generar automáticamente un evento independiente en `mcp_invocations`.

### D7 — La memoria RAG es una superficie de escritura privilegiada

`import_agent_context` no es una importación inocua: altera el corpus que influirá en respuestas futuras.

**Decisión:** clasificarla como `memory_ingest`, exigir autorización explícita, provenance de origen, deduplicación y policy evaluation.

---

## 5. Arquitectura objetivo

```text
                         CLIENT SURFACE
 ChatGPT Desktop · Codex · Claude Code · Remote OpenAI Surface
                                │
                                ▼
                       TRANSPORT ADAPTER
       stdio · ssh-stdio · secure tunnel · streamable HTTP
                                │
                                ▼
                    MCP SESSION BOUNDARY
 protocol version · server instance · client metadata · correlation
                                │
                                ▼
                  AUTHENTICATION / IDENTITY
 local env · SSH principal · tunnel/workspace · OAuth/bearer
                                │
                                ▼
                       TOOL POLICY ENGINE
 profile · capability · project scope · sensitivity · approval evidence
                  │                         │
          discovery filtering       invocation enforcement
                  └──────────────┬──────────┘
                                 ▼
                         TOOL HANDLERS
 read · append · workflow mutation · transition · memory ingest
                                 │
                ┌────────────────┼────────────────┐
                ▼                ▼                ▼
             SQLite           ChromaDB       Provider Gateway
                │                │                │
                └────────────────┼────────────────┘
                                 ▼
                         EVIDENCE PLANE
 mcp_invocations · decision events · costs · outcomes · lineage
```

### 5.1 Separación de responsabilidades

| Componente | Responsabilidad | No debe hacer |
|---|---|---|
| Transporte | Entregar JSON-RPC | Decidir permisos de negocio |
| Identidad | Resolver actor/surface | Confiar en un string enviado por la tool |
| Tool Policy | Autorizar capability y scope | Delegar la decisión solo al prompt del modelo |
| Handler | Ejecutar operación validada | Inventar identidad o saltarse auditoría |
| Provider Gateway | Gobernar egress LLM | Confiar en que MCP ya aplicó seguridad de proveedor |
| Evidence Plane | Registrar hechos observados | Confundir declaraciones del agente con eventos observados |

---

## 6. Modelo de confianza y amenazas mínimas

### 6.1 Actores

- Usuario legítimo operando un cliente local.
- Cliente MCP legítimo mal configurado.
- Modelo que selecciona una tool incorrecta.
- Prompt injection proveniente del repositorio, RAG o respuesta importada.
- Otro proceso local con capacidad de lanzar el servidor.
- Host de la LAN no autorizado.
- Cliente remoto con credenciales válidas pero permisos excesivos.
- Reintento legítimo que repite una mutación.
- Servidor MCP o dependencia comprometida.

### 6.2 Activos

- Prompts, respuestas y código por proyecto.
- Contextos, steps y decisiones.
- Política y sensibilidad del proyecto.
- Historial y métricas de costo.
- Corpus RAG.
- API keys y credenciales.
- Integridad del ledger.
- Disponibilidad y consistencia de SQLite/Chroma.

### 6.3 Amenazas prioritarias

| ID | Amenaza | Mitigación requerida |
|---|---|---|
| T1 | Tool no autorizada visible al modelo | Filtrado en `tools/list` |
| T2 | Invocación directa de tool oculta | Reautorización en `_dispatch` |
| T3 | Cliente finge identidad usando argumento `agent` | Identidad resuelta fuera de argumentos de tool |
| T4 | Dos clientes avanzan el mismo step | Transacción condicional + idempotency key |
| T5 | Reintento duplica contexto o importación | Request ID único + tabla de resultados idempotentes |
| T6 | Prompt injection llama `import_agent_context` | Aprobación, scope, policy y sanitización de metadata |
| T7 | Cross-project read/write | Project scope obligatorio derivado de sesión/política |
| T8 | MCP remoto sin auth | Prohibición normativa y fail-closed |
| T9 | Dashboard en LAN sin auth | Mantener loopback o implementar WP-Net-1 completo |
| T10 | Logs rompen STDIO o filtran secretos | Solo JSON-RPC en stdout; logs a stderr con redacción |
| T11 | Tool annotations falsas o incompletas | Cliente las trata como hints; servidor impone policy real |
| T12 | SQLite/Chroma divergen | Estado explícito de indexación, retry controlado y evento de degradación |

---

## 7. Modelo de capabilities y perfiles

### 7.1 Categorías normativas

```text
read
append
workflow_mutation
workflow_transition
memory_ingest
```

### 7.2 Perfiles mínimos

| Perfil | Capabilities | Uso |
|---|---|---|
| `readonly` | `read` | Primer smoke test, consultas y diagnóstico |
| `observability` | `read`, `append` | Lectura más checkpoints/tool telemetry no destructiva |
| `workflow_operator` | `read`, `append`, `workflow_mutation`, `workflow_transition` | Operación supervisada del workflow |
| `memory_curator` | `read`, `memory_ingest` | Importación explícita y gobernada de conocimiento |
| `admin` | Todas | Solo entorno controlado; no es default |

### 7.3 Reglas

- El perfil por defecto MUST ser `readonly` cuando no exista configuración explícita.
- Toda tool MUST declarar una categoría.
- Una categoría desconocida MUST fallar cerrada.
- El servidor MUST filtrar `tools/list` según el perfil efectivo.
- El servidor MUST repetir la autorización antes de ejecutar `_dispatch`.
- `memory_ingest` MUST NOT quedar incluido implícitamente en `workflow_operator`.
- El proyecto efectivo MUST provenir de la sesión o de una allowlist; no solo del argumento enviado por el modelo.
- El cliente MAY aplicar aprobaciones adicionales, pero nunca reemplaza la policy del servidor.

### 7.4 Metadata MCP recomendada

Ejemplo conceptual para una tool de lectura:

```json
{
  "name": "get_context",
  "title": "Get project context",
  "description": "Returns the active context for an authorized project.",
  "inputSchema": {"type": "object"},
  "annotations": {
    "readOnlyHint": true,
    "destructiveHint": false,
    "idempotentHint": true,
    "openWorldHint": false
  }
}
```

Ejemplo conceptual para `skip_step`:

```json
{
  "name": "skip_step",
  "annotations": {
    "readOnlyHint": false,
    "destructiveHint": true,
    "idempotentHint": false,
    "openWorldHint": false
  }
}
```

Las annotations MUST ser coherentes con el comportamiento, pero MUST NOT considerarse un control de seguridad.

---

## 8. Identidad y provenance MCP

### 8.1 Identidad efectiva

El servidor MUST construir `ExecutionIdentity` desde metadata del proceso/transporte:

```text
client_surface:
  chatgpt_desktop | codex_cli | codex_ide | claude_code |
  chatgpt_web | responses_api | ssh_client | other

transport:
  stdio | ssh_stdio | secure_mcp_tunnel | streamable_http

actor_id:
  identificador local o remoto verificable cuando exista

server_instance_id:
  UUID generado al iniciar el proceso

project_scope:
  lista explícita o proyecto único autorizado

capability_profile:
  readonly | observability | workflow_operator | memory_curator | admin
```

### 8.2 Fuentes por transporte

| Transporte | Identidad mínima |
|---|---|
| STDIO local | Variables de entorno definidas por configuración del cliente + identidad del proceso local |
| SSH-stdio | Usuario SSH y host remoto inyectados por wrapper controlado |
| Secure MCP Tunnel | Identificador de túnel/workspace disponible + identidad de aplicación si el producto la entrega |
| Streamable HTTP | Subject autenticado mediante OAuth/bearer/mTLS, audience validada y scopes |

Un argumento como `agent="claude-code"` MUST tratarse como **etiqueta declarada**, no como identidad autenticada.

### 8.3 Tabla propuesta `mcp_invocations`

```sql
CREATE TABLE mcp_invocations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                  TEXT NOT NULL,
    request_id          TEXT NOT NULL UNIQUE,
    correlation_id      TEXT,
    server_instance_id  TEXT NOT NULL,
    client_surface      TEXT NOT NULL,
    transport           TEXT NOT NULL,
    actor_id             TEXT,
    capability_profile  TEXT NOT NULL,
    tool_name            TEXT NOT NULL,
    tool_category        TEXT NOT NULL,
    project              TEXT,
    context_id           INTEGER,
    step_id              INTEGER,
    input_hash           TEXT NOT NULL,
    redacted_input_json  TEXT,
    output_hash          TEXT,
    status               TEXT NOT NULL,
    policy_hash          TEXT,
    reason_code          TEXT,
    duration_ms          INTEGER,
    error_code           TEXT,
    created_at           TEXT NOT NULL
);

CREATE INDEX idx_mcp_invocations_project_ts
    ON mcp_invocations(project, ts DESC);

CREATE INDEX idx_mcp_invocations_tool_ts
    ON mcp_invocations(tool_name, ts DESC);
```

### 8.4 Reglas de almacenamiento

- API keys, tokens y secretos MUST NOT persistirse.
- El input completo SHOULD permanecer desactivado por defecto.
- `input_hash` y `output_hash` MUST calcularse sobre una representación canónica.
- Cuando se persista input, MUST pasar por redacción estructurada.
- Denegaciones MUST registrarse sin ejecutar el handler.
- Errores de auditoría en modo `strict` MUST bloquear mutaciones.
- Errores de auditoría en modo `best_effort` MAY permitir lecturas, dejando evidencia de degradación cuando sea posible.

---

## 9. Idempotencia y consistencia

### 9.1 Request ID

Toda invocación mutable MUST recibir o derivar un `request_id` estable.

Prioridad:

1. ID de invocación entregado por el transporte/cliente, si es estable.
2. `client_session_id + JSON-RPC id + tool_name`.
3. UUID generado por wrapper; no sirve para deduplicar reintentos externos y debe marcarse como `non_replay_safe`.

### 9.2 Contrato de idempotencia

- Si llega un `request_id` ya completado, el servidor MUST devolver el resultado almacenado.
- Si está `in_progress`, MUST devolver conflicto/retryable sin volver a ejecutar.
- Si falló antes de mutar, MAY reintentarse.
- Si el estado de mutación es incierto, MUST requerir reconciliación; no repetir a ciegas.

### 9.3 Transiciones de workflow

`advance_step` y `skip_step` MUST ejecutarse en una única transacción con actualización condicional:

```sql
UPDATE steps
SET status = 'completed', completed_at = ?, notes = ?
WHERE id = ? AND status = 'in_progress';
```

La operación MUST verificar `rowcount = 1`. Si es 0, debe responder conflicto de estado y no activar otro paso.

La selección y activación del siguiente step MUST ocurrir dentro de la misma transacción.

### 9.4 SQLite

Agregar por conexión:

```sql
PRAGMA busy_timeout = 5000;
```

Además:

- retries acotados solo para `SQLITE_BUSY`;
- jitter pequeño;
- no reintentar errores lógicos;
- métricas de lock;
- tests multi-proceso, no solo multi-thread;
- `_write_lock` se mantiene como optimización intra-proceso, no como garantía global.

### 9.5 SQLite + ChromaDB

`import_agent_context` actualmente inserta en SQLite y luego intenta indexar en Chroma, absorbiendo cualquier excepción.

Contrato propuesto:

```text
run persisted       = true/false
rag_index_status    = pending | indexed | failed
rag_error_code      = nullable
```

La pérdida de indexación MUST quedar visible. Un retry de indexación MUST ser idempotente por `run_id`.

---

## 10. Integración con Policy Engine y PGDP

### 10.1 MCP como cliente del control plane

MCP no es el Policy Engine. Es una superficie cliente que solicita operaciones.

Toda invocación debe construir:

```text
PolicyInput {
  project,
  actor,
  client_surface,
  transport,
  capability,
  tool,
  declared_sensitivity,
  detected_sensitivity,
  operation_class,
  payload_hash
}
```

Y producir:

```text
PolicyDecision {
  allowed,
  reason_code,
  policy_version,
  policy_hash,
  effective_scope,
  required_approval
}
```

### 10.2 Relación con egress

- Una tool MCP de lectura local no es por sí misma egress a un proveedor.
- Una tool que dispare una ejecución LLM MUST pasar por Provider Gateway y Egress Gate.
- El router externo continúa siendo destino de egress.
- Un MCP de terceros con red propia queda fuera del sandbox de `ai-orchestrator`, salvo que se integre expresamente al control plane.

### 10.3 Memory ingestion policy

`import_agent_context` MUST evaluar:

- proyecto autorizado;
- identidad/origen;
- clasificación de sensibilidad;
- tamaño máximo;
- session/source ID;
- duplicado semántico o exacto;
- contenido potencialmente malicioso;
- permiso `memory_ingest`;
- lineage hacia la sesión externa original.

El contenido importado SHOULD quedar marcado como `external_untrusted` hasta revisión o evaluación automática definida.

---

## 11. Opciones de acceso soportadas

### 11.1 Matriz de decisión

| Opción | Código nuevo | Inbound público | Auth principal | Estado recomendado |
|---|---:|---:|---|---|
| STDIO local | No | No | Confianza del host + config del cliente | **Usar ahora, inicialmente read-only** |
| SSH-stdio | No | SSH existente | SSH | **Usar cross-host controlado** |
| Secure MCP Tunnel | No en MCP; sí setup operativo | No | API key/túnel + workspace/product controls | **Evaluar cuando la cuenta lo soporte** |
| Streamable HTTP localhost | Sí | No | Opcional local, pero policy obligatoria | Solo desarrollo futuro |
| Streamable HTTP LAN/Internet | Sí | Sí/privado | OAuth/bearer/mTLS + TLS + Origin | Después del gate y ledger |
| Dashboard por SSH tunnel | No | No | SSH | Soportado hoy |
| Dashboard `0.0.0.0` sin auth | Trivial | Sí | Ninguna | **Prohibido** |
| Segunda instalación para “acceso remoto” | No | N/A | N/A | **Prohibido por split-brain** |

### 11.2 STDIO local — ChatGPT Desktop / Codex

Configuración conservadora para Windows:

```toml
[mcp_servers.ai_orchestrator]
command = "C:\\Fuentes\\ai-orchestrator\\.venv\\Scripts\\python.exe"
args = ["-u", "-m", "orchestrator.mcp"]
cwd = "C:\\Fuentes\\ai-orchestrator"
enabled = true
required = true
startup_timeout_sec = 15
tool_timeout_sec = 60

# Mientras el servidor no publique annotations correctas:
default_tools_approval_mode = "prompt"

# Primera conexión: solo lectura.
enabled_tools = ["get_context", "list_steps", "list_agents"]

[mcp_servers.ai_orchestrator.env]
# Metadata propuesta para Fases 2-3; production@e0189a3 aún no la consume.
ORCHESTRATOR_MCP_PROFILE = "readonly"
ORCHESTRATOR_MCP_CLIENT_SURFACE = "chatgpt_desktop"
ORCHESTRATOR_MCP_TRANSPORT = "stdio"
```

**Control efectivo disponible hoy:** `enabled_tools` y la aprobación del cliente. Las variables `ORCHESTRATOR_MCP_*` son parte del contrato propuesto y no aplican autorización server-side en `production@e0189a3`.

Después de implementar annotations y policy server-side, el cliente MAY usar:

```toml
default_tools_approval_mode = "writes"
```

### 11.3 STDIO local — Claude Code

CLI:

```powershell
claude mcp add --transport stdio --scope local ai-orchestrator -- `
  C:\Fuentes\ai-orchestrator\.venv\Scripts\python.exe `
  -u -m orchestrator.mcp
```

Ejemplo `.mcp.json` de proyecto:

```json
{
  "mcpServers": {
    "ai-orchestrator": {
      "type": "stdio",
      "command": "C:\\Fuentes\\ai-orchestrator\\.venv\\Scripts\\python.exe",
      "args": ["-u", "-m", "orchestrator.mcp"],
      "env": {
        "ORCHESTRATOR_MCP_PROFILE": "readonly",
        "ORCHESTRATOR_MCP_CLIENT_SURFACE": "claude_code",
        "ORCHESTRATOR_MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

El archivo compartido MUST NOT contener secretos. En el estado actual, Claude Code puede lanzar el servidor, pero las variables de perfil son solo metadata futura: el servidor todavía expondrá las doce tools y la autorización dependerá del cliente hasta completar la Fase 2.

### 11.4 SSH-stdio

```json
{
  "mcpServers": {
    "ai-orchestrator-remote": {
      "type": "stdio",
      "command": "ssh",
      "args": [
        "usuario@host-A",
        "/ruta/absoluta/venv/bin/python -u -m orchestrator.mcp"
      ],
      "env": {
        "ORCHESTRATOR_MCP_PROFILE": "readonly",
        "ORCHESTRATOR_MCP_CLIENT_SURFACE": "ssh_client",
        "ORCHESTRATOR_MCP_TRANSPORT": "ssh_stdio"
      }
    }
  }
}
```

Caveats:

- usar ruta absoluta al Python remoto;
- evitar prompts interactivos;
- restringir la clave SSH;
- idealmente usar wrapper remoto con comando forzado;
- registrar actor SSH mediante variable confiable del wrapper, no desde argumentos de tool.

### 11.5 Secure MCP Tunnel

Ejemplo conceptual en PowerShell:

```powershell
$env:CONTROL_PLANE_API_KEY = "<runtime-key-no-guardar-en-repo>"

tunnel-client init `
  --sample sample_mcp_stdio_local `
  --profile ai-orchestrator-local `
  --tunnel-id tunnel_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx `
  --mcp-command 'C:\Fuentes\ai-orchestrator\.venv\Scripts\python.exe -u -m orchestrator.mcp'

tunnel-client doctor --profile ai-orchestrator-local --explain
tunnel-client run --profile ai-orchestrator-local
```

Requisitos:

- salida HTTPS hacia OpenAI;
- asociación correcta de organización/workspace;
- permisos de túnel;
- servidor MCP alcanzable localmente;
- perfil inicial `readonly`;
- no asumir disponibilidad para todos los planes o workspaces.

### 11.6 Futuro Streamable HTTP

Precondiciones obligatorias:

- Policy Engine operativo;
- autenticación real;
- autorización por capability y project scope;
- TLS para acceso no local;
- validación de `Origin`;
- rate limiting;
- body limits;
- timeouts;
- audit automático;
- protección anti-replay;
- session management;
- pruebas de DNS rebinding;
- ninguna ruta administrativa implícita.

---

## 12. Diseño de implementación incremental

Se preserva el entrypoint público:

```text
python -m orchestrator.mcp
```

No se recomienda convertir inmediatamente `orchestrator/mcp.py` en package porque rompería imports/configuraciones. La extracción puede hacerse en módulos adyacentes:

```text
orchestrator/
├── mcp.py                 # entrypoint y loop JSON-RPC compatible
├── mcp_registry.py        # definición única de tools, schemas, annotations y categorías
├── mcp_policy.py          # perfiles, scope y autorización dual
├── mcp_identity.py        # ExecutionIdentity por transporte/entorno
├── mcp_audit.py           # mcp_invocations e idempotencia
├── mcp_validation.py      # validación JSON Schema y normalización
├── mcp_service.py         # handlers de dominio
└── mcp_http.py            # futuro adaptador Streamable HTTP, no bloqueante
```

### Principios

- El transporte no contiene lógica de negocio.
- El registry es la única fuente para `TOOLS` y `_HANDLERS`.
- Ningún handler puede ejecutarse fuera del wrapper de policy/audit.
- Los handlers reciben `InvocationContext`, no leen identidad desde argumentos.
- Las tools desconocidas fallan cerradas.
- Los errores de negocio se devuelven como tool result con `isError: true`; los errores de protocolo usan JSON-RPC error.
- `stdout` se reserva exclusivamente para JSON-RPC válido.

---

## 13. Roadmap

### Fase 0 — Conexión controlada y documentación

- Documentar ChatGPT Desktop/Codex STDIO.
- Documentar Claude Code STDIO.
- Mantener SSH-stdio y dashboard por túnel SSH.
- Agregar configuración de ejemplo sin secretos.
- Ejecutar smoke test solo con `get_context`, `list_steps`, `list_agents`.
- No habilitar mutaciones en esta fase.

**Salida:** al menos dos clientes locales conectados y consultas read-only verificadas.

### Fase 1 — Registry, annotations y validación

- Centralizar definición de tools.
- Agregar `title`, annotations y `outputSchema` donde aporte valor.
- Validar argumentos server-side contra JSON Schema.
- Diferenciar protocol error de tool execution error.
- Test de pureza de stdout.
- Mantener compatibilidad con los tres protocol versions declarados o reducirlos explícitamente con tests.

**Salida:** contrato MCP consistente y testeado.

### Fase 2 — Tool Policy server-side

- Implementar perfiles y categorías.
- Filtrar `tools/list`.
- Autorizar de nuevo en `tools/call`.
- Resolver project scope fuera del modelo.
- Default fail-closed `readonly`.
- Agregar reason codes de denegación.

**Salida:** una tool no autorizada no es visible ni ejecutable.

### Fase 3 — Audit, identidad e idempotencia

- Crear `mcp_invocations`.
- Introducir `ExecutionIdentity`.
- Persistir inicio/fin/denegación.
- Implementar request IDs y replay seguro.
- `busy_timeout` y retries acotados.
- Atomicidad para `advance_step` y `skip_step`.
- Estado explícito de indexación Chroma.

**Salida:** provenance end-to-end de cada invocación y cero duplicaciones bajo retry conocido.

### Fase 4 — Integración con Policy Engine / Egress Gate

- Evaluar capability, proyecto y sensibilidad.
- Someter cualquier llamada LLM al Provider Gateway.
- Someter `memory_ingest` a política específica.
- Asociar `policy_hash` y `reason_code`.
- Cerrar I8 y agregar `routing_source` si aún no se ha hecho.

**Salida:** MCP no puede convertirse en bypass del control plane.

### Fase 5 — Acceso privado remoto

- Validar SSH-stdio con wrapper restringido.
- Evaluar Secure MCP Tunnel según disponibilidad real de cuenta/workspace.
- Mantener perfil remoto read-only hasta evidencia de autorización y audit.

**Salida:** acceso privado sin listener público y contra una única base del host.

### Fase 6 — Streamable HTTP opcional

Solo si existe caso de negocio no cubierto por STDIO/SSH/túnel:

- adoptar SDK/FastMCP o implementar adaptador fino sobre core existente;
- OAuth/bearer/mTLS;
- Origin validation;
- TLS, limits, rate limiting y tests;
- operación multiusuario.

**Salida:** endpoint remoto gobernado, no una exposición ad hoc.

### Fase 7 — Dashboard gobernado

- WP-Net-1 independiente.
- `--host` solo junto con auth.
- CSRF/origin/session controls.
- permisos read/write separados.
- auditoría de endpoints administrativos.

**Salida:** acceso multi-dispositivo sin degradar el modelo de amenaza.

---

## 14. Requisitos normativos consolidados

### Transporte

- El servidor MCP local MUST usar STDIO o loopback por defecto.
- Un transporte HTTP no local MUST usar autenticación y TLS.
- Streamable HTTP MUST validar `Origin`.
- Ningún transporte MUST confiar en CORS como autenticación.
- Secure MCP Tunnel MUST usar solo credenciales fuera del repo.
- SSH-stdio SHOULD usar comando forzado o wrapper restringido.

### Tools

- Cada tool MUST declarar categoría y schema.
- Cada input MUST validarse antes del handler.
- Tool discovery e invocation MUST aplicar la misma policy.
- Una tool desconocida o categoría desconocida MUST bloquearse.
- Mutaciones MUST ser idempotentes o declarar explícitamente que no lo son y requerir aprobación.
- `memory_ingest` MUST estar separado de workflow writes.

### Identidad y scope

- El actor MUST derivarse del transporte/configuración, no del prompt.
- El project scope MUST resolverse fuera del modelo.
- Un project scope vacío en una operación sensible MUST fallar cerrado.
- Una política de proyecto MUST NOT ampliar permisos globales.

### Evidencia

- Cada `tools/call` MUST producir un evento observado.
- `record_tool_call` MUST permanecer diferenciado como evento declarado.
- Denegaciones MUST registrar `reason_code` y `policy_hash` cuando exista.
- Secretos MUST NOT quedar en logs ni ledger.

### Datos y egress

- Toda llamada LLM gobernada MUST atravesar Provider Gateway.
- El router externo MUST tratarse como egress.
- Contexto de otro proyecto MUST NOT entrar al payload ni a respuestas MCP.
- Fallos de indexación RAG MUST quedar visibles.

### Dashboard

- El dashboard MUST NOT salir de loopback sin autenticación.
- Exportaciones con task/response MUST requerir permiso explícito cuando exista acceso remoto.
- POST destructivos MUST quedar auditados y autorizados.

---

## 15. Matriz de pruebas

### 15.1 Protocolo

| ID | Prueba | Resultado esperado |
|---|---|---|
| P1 | `initialize` con cada versión declarada | Negociación correcta |
| P2 | versión desconocida | Respuesta explícita conforme a política definida |
| P3 | `ping` | `{}` |
| P4 | `tools/list` | Solo tools autorizadas |
| P5 | stdout contiene log no JSON | Test falla |
| P6 | JSON inválido | Manejo definido sin contaminar stdout |
| P7 | method desconocido | `-32601` |
| P8 | tool inexistente | Error de protocolo/tool según contrato documentado |

### 15.2 Policy

| ID | Prueba | Resultado esperado |
|---|---|---|
| A1 | perfil `readonly` lista tools | Solo 3 tools read |
| A2 | llamada directa a `advance_step` en readonly | Denegada antes del handler |
| A3 | categoría desconocida | Fail-closed |
| A4 | proyecto fuera de scope | Denegada |
| A5 | cliente pide admin sin configuración confiable | Denegado |
| A6 | tool annotation dice read-only, registry dice mutation | Registry/policy prevalece |

### 15.3 Validación

| ID | Prueba | Resultado esperado |
|---|---|---|
| V1 | falta parámetro requerido | `isError: true`, sin mutación |
| V2 | tipo incorrecto | `isError: true` |
| V3 | campo inesperado bajo schema estricto | Rechazado o política explícita |
| V4 | strings/tamaños extremos | Límite aplicado |
| V5 | secreto en input | Redactado en ledger |

### 15.4 Concurrencia e idempotencia

| ID | Prueba | Resultado esperado |
|---|---|---|
| C1 | dos procesos avanzan mismo step | Uno gana; otro recibe conflicto |
| C2 | mismo `request_id` repetido | Mismo resultado, una mutación |
| C3 | `SQLITE_BUSY` transitorio | Retry acotado |
| C4 | `SQLITE_BUSY` persistente | Error visible, no loop infinito |
| C5 | inserción run OK, Chroma falla | `rag_index_status=failed` |
| C6 | retry de indexación | Un chunk lógico, sin duplicación |

### 15.5 Aislamiento

| ID | Prueba | Resultado esperado |
|---|---|---|
| I1 | `get_context` de proyecto no autorizado | Denegado |
| I2 | `list_steps` con context_id de otro proyecto | Denegado |
| I3 | `import_agent_context` a otro proyecto | Denegado |
| I4 | similar runs | Solo proyecto actual |
| I5 | export/response | Sin datos cross-project |

### 15.6 Transporte remoto

| ID | Prueba | Resultado esperado |
|---|---|---|
| N1 | MCP HTTP en `0.0.0.0` sin auth | Startup rechazado |
| N2 | Origin inválido | Rechazado |
| N3 | token sin scope | 403/denegación equivalente |
| N4 | token para proyecto A accede B | Denegado |
| N5 | Secure Tunnel | Sin puerto inbound público |
| N6 | SSH wrapper | Solo comando MCP permitido |

---

## 16. Métricas y criterios de aceptación

```text
mcp_invocation_audit_coverage                     = 100%
unauthorized_tools_visible_total                  = 0
unauthorized_tool_execution_total                 = 0
mcp_unknown_policy_allowed_total                  = 0
cross_project_mcp_leak_total                      = 0
mutable_invocations_with_stable_request_id        = 100%
duplicate_mutation_total                          = 0
workflow_transition_conflict_misclassified_total  = 0
mcp_secret_persistence_total                      = 0
rag_index_failure_without_evidence_total           = 0
stdout_non_json_message_total                     = 0
remote_unauthenticated_connection_total           = 0
```

### Gate de salida por fase

- **Fase 0:** smoke test read-only desde dos clientes.
- **Fase 1:** protocolo y schemas en CI.
- **Fase 2:** discovery y invocation enforcement con 100% de fixtures prohibidos bloqueados.
- **Fase 3:** tests multi-proceso e idempotencia verdes.
- **Fase 4:** policy hash/provenance y egress invariants verdes.
- **Fase 5:** evidencia de cero inbound público en patrón elegido.
- **Fase 6:** threat model y pentest mínimo antes de habilitar red no local.

---

## 17. Riesgos y decisiones pendientes

### R1 — Implementación MCP hand-rolled

**Riesgo:** divergencia de la spec y mayor costo de mantener transports/autorización.  
**Decisión provisional:** no migrar como requisito de conexión local. Evaluar SDK oficial antes de Streamable HTTP.

### R2 — Confianza excesiva en approvals del cliente

**Riesgo:** otro cliente puede llamar sin presentar aprobación.  
**Mitigación:** policy server-side obligatoria.

### R3 — Identidad débil en STDIO

**Riesgo:** variables de entorno pueden ser falsificadas por cualquier proceso que pueda lanzar el servidor.  
**Mitigación:** aceptar esto como trust boundary local; no equipararlo a identidad remota fuerte.

### R4 — Contaminación RAG

**Riesgo:** una respuesta importada condiciona decisiones futuras.  
**Mitigación:** capability separada, lineage, trust label y revisión.

### R5 — Compatibilidad de clientes

**Riesgo:** diferencias en annotations, approvals, roots y protocol versions.  
**Mitigación:** matriz de clientes y contrato mínimo común.

### R6 — Availability de Secure MCP Tunnel

**Riesgo:** dependencia de permisos/producto/workspace.  
**Mitigación:** tratarlo como opción condicionada, no como requisito del core.

### R7 — SQLite como límite de escala

**Riesgo:** múltiples procesos y escritura intensiva pueden superar el diseño local.  
**Mitigación:** medir lock/error rate antes de migrar. PostgreSQL no se introduce preventivamente.

### R8 — Inflación de alcance

**Riesgo:** convertir la conexión MCP en una reescritura completa.  
**Mitigación:** Fase 0 read-only, luego hardening incremental; Streamable HTTP al final.

---

## 18. Decisiones abiertas para validación externa

Claude debe responder, con evidencia contra código y documentación primaria:

1. ¿Es correcto declarar STDIO local como capacidad utilizable hoy sin cambios de código?
2. ¿La clasificación de las 12 tools refleja correctamente sus efectos reales?
3. ¿`record_tool_call` debe conservarse o renombrarse para evitar confusión con auditoría observada?
4. ¿Las annotations propuestas son compatibles con los clientes objetivo y suficientes como hints?
5. ¿El perfil default `readonly` es demasiado restrictivo para el valor inicial del producto?
6. ¿La defensa dual discovery + invocation es necesaria y está ubicada en el componente correcto?
7. ¿La tabla `mcp_invocations` duplica datos del ledger RFC-005 o representa una capa operacional legítima?
8. ¿Conviene extender `tool_calls` existente o crear una tabla separada?
9. ¿El modelo de idempotencia cubre reintentos reales de ChatGPT/Codex/Claude?
10. ¿`advance_step` y `skip_step` requieren optimistic locking adicional a un `UPDATE ... WHERE status=?`?
11. ¿`busy_timeout=5000` es una base razonable o debe ser configurable?
12. ¿La coordinación SQLite + Chroma necesita outbox transaccional?
13. ¿Secure MCP Tunnel debe entrar en el roadmap central o quedar solo como receta operativa?
14. ¿Existe una razón técnica para priorizar FastMCP/SDK oficial antes de Fase 1?
15. ¿Qué requisitos faltan para Streamable HTTP seguro según la spec vigente?
16. ¿MCP amplía de forma material el threat model del Egress Gate?
17. ¿`memory_ingest` necesita moderación, scanning o cuarentena antes de entrar al RAG?
18. ¿Qué partes de este RFC están por delante del código sin una hipótesis o test que las justifique?
19. ¿El roadmap respeta el circuit breaker “RFC = decisión vinculada a código”?
20. Veredicto final: **APPROVE**, **APPROVE WITH CHANGES** o **REJECT**, con cambios bloqueantes separados de mejoras posteriores.

---

## 19. Prompt listo para validación final con Claude

```text
Actúa como Principal Software Architect y Security Reviewer especializado en MCP,
sistemas agentic, SQLite concurrente, RAG y gobernanza de egress.

Debes realizar una validación adversarial y verificable del documento:
“RFC-008 — Acceso MCP gobernado y superficie remota del Local AI Control Plane”.

FUENTES DE VERDAD
1. Código público: https://github.com/csantisdev/ai-orchestrator
2. Rama: production
3. Commit esperado: e0189a3827f82524942cecaa3929a9c0ddd24487
4. Documento base: RFC-007 v0.3
5. Documento a revisar: RFC-008 v0.1
6. Especificación MCP 2025-06-18 y documentación oficial vigente de los clientes.

REGLAS
- No asumas que una afirmación documental está implementada.
- Verifica cada hallazgo importante contra archivo y línea.
- Distingue: implemented, partial, designed, absent.
- Distingue evidencia: public/verifiable, local-only, none.
- No propongas una reescritura por preferencia estética.
- Marca contradicciones entre RFC-007, RFC-008 y production.
- Verifica especialmente si WAL ya existe, si falta busy_timeout, si el lock es
  solo intra-proceso, cuántas tools existen y qué mutaciones realiza cada una.
- Verifica si el servidor realmente es STDIO puro, qué protocol versions declara,
  cómo maneja errores y si valida JSON Schema.
- Comprueba si ChatGPT Desktop/Codex y Claude Code soportan STDIO local actualmente.
- Comprueba la existencia y alcance real de Secure MCP Tunnel sin asumir que está
  disponible para cualquier plan o workspace.
- Evalúa tool annotations como hints y no como mecanismo de autorización.
- Trata import_agent_context como una escritura sobre memoria RAG y analiza su riesgo.
- Revisa race conditions concretas en advance_step, skip_step, create_context,
  add_step e import_agent_context.
- No implementes cambios todavía.

FORMATO DE SALIDA OBLIGATORIO

A. VEREDICTO EJECUTIVO
- APPROVE / APPROVE WITH CHANGES / REJECT
- 5 a 10 líneas con la razón principal.

B. MATRIZ DE AFIRMACIONES
Tabla:
| ID | Afirmación RFC-008 | Estado | Evidencia archivo:línea o fuente | Corrección |
Estados: CONFIRMED / PARTIALLY CONFIRMED / REFUTED / NOT VERIFIABLE.

C. HALLAZGOS BLOQUEANTES
Para cada uno:
- Severidad
- Evidencia
- Escenario de fallo
- Cambio mínimo requerido
- Test que demuestra el cierre

D. VALIDACIÓN DE ARQUITECTURA
- transporte local
- acceso remoto
- identidad
- tool policy
- provenance
- idempotencia
- SQLite/Chroma
- integración con Egress Gate

E. VALIDACIÓN TOOL-BY-TOOL
Revisa las 12 tools y confirma:
- read/write real
- destructive/non-destructive
- idempotent/non-idempotent
- project scope
- aprobación recomendada
- riesgo de prompt injection o memory poisoning

F. ROADMAP CORREGIDO
Mantén solo fases justificadas. Separa:
- bloqueante antes de usar writes
- necesario antes de acceso remoto
- mejora futura

G. PATCH DOCUMENTAL
Entrega texto exacto para reemplazar cualquier sección incorrecta del RFC-008.
No generes código productivo.

H. DECISIÓN FINAL
Lista:
- cambios obligatorios antes de aprobar
- cambios recomendados no bloqueantes
- preguntas sin evidencia suficiente
```

---

## 20. Referencias primarias

- Repositorio: [csantisdev/ai-orchestrator](https://github.com/csantisdev/ai-orchestrator)
- OpenAI, MCP en ChatGPT Desktop y Codex: [Model Context Protocol](https://developers.openai.com/codex/mcp)
- OpenAI, acceso privado: [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- OpenAI, apps MCP y developer mode: [Developer mode and MCP apps in ChatGPT](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)
- MCP 2025-06-18, transports: [Transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- MCP 2025-06-18, authorization: [Authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)
- MCP 2025-06-18, tools: [Tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- Anthropic, Claude Code MCP: [Connect Claude Code to tools via MCP](https://code.claude.com/docs/en/mcp)

---

## Conclusión

El servidor MCP actual ya es útil como integración local, pero todavía no constituye una superficie gobernada del Local AI Control Plane. La conexión no requiere esperar Streamable HTTP: puede validarse inmediatamente mediante STDIO en modo lectura.

El valor arquitectónico aparece cuando cada invocación deja de ser una llamada opaca y pasa a estar vinculada con identidad, transporte, capability, scope de proyecto, política, mutación, costo indirecto y outcome. Ese vínculo extiende PGDP desde la decisión de proveedor hacia la operación multi-tool sin inflar prematuramente la afirmación de multiagencia.

La siguiente acción no es publicar un puerto. Es ejecutar el smoke test read-only, verificar la compatibilidad real de clientes y endurecer el servidor actual mediante registry, policy dual, audit automático e idempotencia. Solo después corresponde habilitar escrituras y acceso remoto gobernado.
