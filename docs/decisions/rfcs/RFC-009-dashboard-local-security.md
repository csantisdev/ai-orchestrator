---
id: RFC-009
type: rfc
title: Seguridad local del dashboard (token de sesión, Origin/Host y endpoints con efectos)
status: draft
created: 2026-10-03
updated: 2026-10-03
supersedes: []
superseded_by: null
related: [RFC-008]
---

# RFC-009 — Seguridad local del dashboard

**Estado:** Draft
**Versión:** 0.2
**Fecha:** 2026-10-03
**Repo de referencia:** `csantisdev/ai-orchestrator@production` = `985b74970477e729eda97ee0728ab6575b523014` (verificado 2026-10-03)
**Relación con la serie:** Es la fase R0 de la especificación del dashboard, propuesta en el PR #28
(`docs/backlog/DASHBOARD_VISUALIZACION_ESPECIFICACION.md`, §13, §24.4 y §24.5; ese archivo no existe
todavía en `production`). Precede a la fase D0, que lo implementa. Complementa a RFC-008, que
gobierna el acceso por MCP: este documento cubre solo el servidor HTTP del dashboard
(`ai-orchestrator serve`). No cubre acceso remoto ni la extensión de VS Code, descartada por ahora.

*Todo ejemplo usa datos sintéticos. Ver "Regla de anonimización" en `../README.md`.*

---

## Changelog

| Área | v0.1 | v0.2 |
|---|---|---|
| GET con efectos | `/pick-folder`, `/rates`, `/pricing` | `/pick-folder`, `/rates`, `/inspect`, `/metrics`, `/integrations/status` y `/clean-preview`; `/inspect` y `/clean-preview` además lanzan un subproceso de ChromaDB (review del PR #30). `/pricing` no tiene efectos: usa `refresh=False` (auditoría Codex H-01, H-02) |
| Inventario de GET | Lista general de datos sensibles | Clasificación ruta por ruta, con efectos, datos y caché (H-03) |
| `/integrations/status` | Sin cambios | Deja de devolver el usuario de las credenciales del Banco Central (H-03) |
| Validación de `Host` | "Exactamente" `127.0.0.1` o `localhost` | Parser canónico: un solo `Host`, puerto igual al del servidor, minúsculas; ausente o duplicado se rechaza; sin puerto equivale al 80 (review del PR #30); `[::1]` se rechaza mientras el bind sea IPv4 (H-05) |
| Métodos | Solo GET y POST | Validación previa al despacho en todos los métodos; HEAD, PUT, DELETE, PATCH y OPTIONS responden `405` (H-04) |
| Cabeceras de seguridad | En respuestas exitosas | En todas las respuestas, incluidos errores y archivos, desde un único punto (H-04, H-08) |
| `Origin` ausente | No definido | Se permite solo si pasan token y `Content-Type` (H-06) |
| Llamadas POST del JS | "Un envoltorio de `fetch`" | Hoy: 26 llamadas para 25 endpoints. Tras D0: 29 llamadas para 27 endpoints (se suman las dos llamadas existentes a `/pick-folder`, `dashboard_js.py:1529` y `1574`, y una a `/chroma-stats/refresh`), todas a través del helper `postJson` y con un test estático (H-07, review del PR #30) |
| Token viejo | Mensaje de recarga | Respuesta `403` con `reason: session_expired`, incluida la página restaurada desde el bfcache del navegador (H-08) |
| Invariantes | I1–I9 | I1–I15 (H-09; I14–I15 por XSS); I9 incluye `404` y `/static/*` (ronda 2); I1 cubre 27 POST (más `/pick-folder` y `/chroma-stats/refresh`) e I2/I10 cualquier verbo (review del PR #30) |
| Alcance del token | "Otros procesos con acceso al sistema de archivos" | Cualquier cliente que pueda conectarse a loopback queda fuera de alcance: el token protege del navegador, no autentica clientes locales (review del PR #30) |
| Resumen | "Cinco controles" | Siete controles: seis (H-10) más C7, serialización segura contra XSS (review del PR #30) |
| XSS | No contemplado | Problema 6 (XSS almacenado y reflejado en `/`, reproducido), amenaza T9, control C7 e invariantes I14–I15 (review del PR #30) |
| `Origin` en el puerto 80 | Puerto literal | Puerto efectivo; un origen sin puerto equivale al 80 (review del PR #30) |
| Referencias | Ruta local de la especificación | PR #28, porque el archivo no existe en esta rama (H-11) |

---

## 0. Resumen ejecutivo

El dashboard escucha en `127.0.0.1` y ejecuta acciones con efectos (borrar contextos, purgar
ChromaDB, lanzar runs con costo, ejecutar `doctor`/`fix`) sin autenticar quién las pide. Cualquier
página abierta en el navegador del usuario puede disparar varias de esas acciones, y un ataque de DNS
rebinding puede leer datos completos de runs. Además, el HTML del dashboard tiene **XSS almacenado y
reflejado**: un texto con `</script>` (en un mensaje de commit importado, en un prompt de una sesión o
en el parámetro `?project=` de un enlace) se ejecuta como JavaScript en el origen del dashboard.
Este RFC propone **siete controles** para D0: serialización segura de todo dato que se inserta en
HTML o en scripts (requisito de los demás, porque un XSS puede leer el token), validación de `Host`
antes de despachar cualquier método, token de sesión obligatorio en toda petición con efectos,
`Origin` permitido, `Content-Type` exacto, eliminación de efectos en peticiones GET y cabeceras de
seguridad centralizadas.

Lo que este documento **no** afirma: el token **no autentica clientes locales**. Protege contra
páginas web abiertas en el navegador (CSRF, DNS rebinding, clickjacking). Cualquier proceso o usuario
que pueda conectarse a `127.0.0.1` puede pedir `/`, leer el token del HTML y usarlo; eso queda fuera
de alcance, igual que el acceso directo a `runs.db`. Tampoco agrega autenticación de usuarios ni TLS,
ni habilita el acceso desde otra máquina.

## 1. El problema

Verificado en `orchestrator/server.py` del baseline:

1. **`do_POST` no valida `Origin` ni `Host`** (`server.py:573`). La única barrera es
   `_require_json_ct` (`server.py:560`), que exige `application/json` como **subcadena** del
   `Content-Type`. Un `fetch` desde otra página con `Content-Type: text/plain; x=application/json`
   es una petición CORS simple (sin preflight, porque la esencia MIME es `text/plain`) y pasa el
   chequeo. La página atacante no puede leer la respuesta, pero el efecto ocurre.
2. **Hay peticiones GET con efectos**, que se disparan con un simple `<img src>` desde cualquier
   página:
   - `GET /pick-folder` lanza un proceso que abre un diálogo nativo de selección de carpeta
     (`server.py:167`).
   - `GET /rates`, `GET /inspect`, `GET /metrics` y `GET /integrations/status` llaman a
     `rates.get_current_rate` (`server.py:229`, `281`, `489`, `505`), que, si el dato está viejo y
     hay credenciales, consulta la red y escribe el caché en SQLite (`rates.py:129-132`).
   - `GET /inspect` y `GET /clean-preview` calculan las estadísticas de ChromaDB con
     `rag.chroma_stats_isolated` (`server.py:215`, `466`), que lanza un subproceso de Python en cada
     petición (`rag.py:488`). Una página puede repetir la petición y crear procesos sin token.
3. **Hay GET con datos sensibles sin validar `Host`** (§2.1). Con DNS rebinding (un dominio del
   atacante que primero resuelve a su servidor y después a `127.0.0.1`), una página puede leerlos,
   porque el navegador la considera del mismo origen y el servidor no mira el `Host`.
   `/integrations/status` además devuelve el usuario de las credenciales del Banco Central
   (`server.py:491-495`).
4. **El dashboard se puede embeber** en otra página: no envía `X-Frame-Options` ni
   `frame-ancestors`, lo que habilita clickjacking sobre sus botones.
5. **Los métodos distintos de GET y POST** caen en la respuesta `501` por defecto de
   `BaseHTTPRequestHandler`, sin validación ni cabeceras propias.
6. **XSS almacenado y reflejado en `/`.** `build_html` inserta datos con `json.dumps` dentro de
   bloques `<script>` (`dashboard.py:341-350` y `661-663` para los runs, `676` para el proyecto
   seleccionado). `json.dumps` no escapa `</script>`, así que el texto cierra el bloque y lo que sigue
   se ejecuta. Reproducido en un navegador headless contra el baseline:
   - **almacenado:** un run cuyo `task_preview` contiene
     `x</script><script>window.__xss=document.title.length</script>` ejecuta el script al abrir el
     dashboard. Ese texto llega desde mensajes de commit importados (`git_scanner.py`) y prompts de
     sesiones importadas (`watcher.py`, `codex_watcher.py`);
   - **reflejado:** `GET /?project=x</script><script>…</script>` ejecuta el script, porque el
     parámetro llega a `_runsFilterProject` (`dashboard.py:676`). Alcanza con un enlace.

   Un script en el origen del dashboard puede llamar a cualquier endpoint, leer el token de sesión de
   C2 y enviar datos afuera. Ningún otro control de este RFC lo detiene.

Severidad: **crítica para (6)**, porque anula los demás controles. Alta para (1) y (2), porque hay
acciones destructivas (`/delete-contexts`, `/purge-chroma-*`), con costo (`/run`) y con red. Media
para (3), (4) y (5).

## 2. Estado verificado del código

Resumen por control, contra el baseline (`server.py` y `dashboard.py` de `production@985b749`); el
detalle por ruta está en §2.1 y §2.2.

| Componente | implementation_status | evidence_status | Detalle |
|---|---|---|---|
| Validación de `Host` (C1) | absent | verifiable | `do_GET` (`server.py:77`) y `do_POST` (`server.py:573`) despachan sin leer `Host` |
| Token de sesión (C2) | absent | verifiable | Ninguna ruta lee una cabecera propia; el HTML de `/` no incluye token |
| `Origin` / `Sec-Fetch-Site` (C3) | absent | verifiable | `do_POST` no lee `Origin`; `Access-Control-Allow-Origin` fijo en el SSE (`server.py:1462`) y en toda respuesta JSON (`_json`, `server.py:1485`) |
| `Content-Type` exacto (C4) | partial | verifiable | Exige `application/json` como subcadena (`server.py:562`) |
| GET sin efectos (C5) | absent | verifiable | `/pick-folder` lanza el diálogo (`server.py:167-202`); `/rates`, `/inspect`, `/metrics`, `/integrations/status`, `/clean-preview` con efectos (§2.2) |
| Cabeceras de seguridad (C6) | partial | verifiable | Solo `Cache-Control: no-store` en `/` (`server.py:552`); sin `X-Frame-Options`, CSP ni `X-Content-Type-Options`; los errores salen sin cabeceras propias |
| Serialización segura (C7) | partial | verifiable | `_escape` cubre HTML (`dashboard.py:50`); `json.dumps` dentro de `<script>` (`dashboard.py:341`, `676`) y datos en handlers en línea (X01–X05). El arreglo inmediato (PR #31) cubre X01–X05 |

### 2.1 Inventario de endpoints

**POST con efectos** (25 endpoints, llamados desde 26 lugares de `dashboard_js.py`; `_syncOne`
reutiliza una misma llamada para varias rutas; `/evaluate-run`, `/pricing/refresh` y `/models/refresh` no tienen llamada en el JS actual, pero quedan igualmente protegidos):

| Categoría | Endpoints |
|---|---|
| Destructivos | `/context/{id}/delete`, `/delete-contexts`, `/purge-chroma-docs`, `/purge-chroma-responses`, `/clean/unmapped`, `/clear-imports` |
| Mutan el tracking | `/create-context`, `/advance-step`, `/skip-step`, `/rate-run`, `/evaluate-run`, `/import-context` |
| Mutan la configuración | `/add-project`, `/project/rename`, `/config/bcentral` (credenciales) |
| Lanzan procesos o tareas largas | `/sync-cc`, `/sync-git`, `/sync-codex`, `/index-docs`, `/run-doctor`, `/run-fix` |
| Red o costo | `/run` (llama a un proveedor de IA), `/rates/refresh`, `/pricing/refresh`, `/models/refresh` |

**GET, ruta por ruta:**

| Ruta | Efectos hoy | Datos | Tras D0 |
|---|---|---|---|
| `/` | — | Últimos runs (preview de la tarea), proyectos | `no-store` |
| `/run/{id}` | — | Tarea y respuesta completas | `no-store` |
| `/export-csv` | — | Tareas y respuestas completas | `no-store` |
| `/context/{id}`, `/contexts-html` | — | Plan de trabajo | `no-store` |
| `/inspect` | Red y escritura (tipo de cambio); **lanza un subproceso** (estadísticas de ChromaDB) | Estadísticas de base y ChromaDB, proyectos y rutas registradas | Solo caché, sin subprocesos; `no-store` |
| `/metrics` | Red y escritura (tipo de cambio) | Costos agregados por proyecto y modelo | Solo caché; `no-store` |
| `/integrations/status` | Red y escritura (tipo de cambio) | Proveedores configurados y **usuario** de credenciales | Solo caché; sin el usuario, solo `configured`; `no-store` |
| `/rates` | Red y escritura (tipo de cambio) | Tipo de cambio | Solo caché; `no-store` |
| `/pricing` | — (usa `refresh=False`) | Catálogo de precios | `no-store` |
| `/models`, `/agents` | — | Modelos disponibles, presets de agentes | `no-store` |
| `/clean-preview` | **Lanza un subproceso** (estadísticas de ChromaDB) | Conteos de datos de los proyectos | Sin subprocesos; `no-store` |
| `/preview-index` | — (recorre el disco del proyecto: lectura costosa, sin escritura) | Archivos de los proyectos | `no-store`; costo aceptado (§6) |
| `/events` (SSE) | — | Actividad en vivo | `no-store` |
| `/pick-folder` | **Lanza un proceso** | — | Pasa a POST con token; GET → `405` |
| `/static/*`, `/favicon.ico`, `/robots.txt`, `/docs`, `/mcp`, `/security` | — | Públicos | Caché permitida |

### 2.2 Bind y CORS

El servidor escucha solo en IPv4 `127.0.0.1:<puerto>` (`server.py:1518`). El SSE responde con
`Access-Control-Allow-Origin: http://127.0.0.1:<puerto>` (`server.py:1462`, `1485`). No hay
respuesta a `OPTIONS`, así que toda petición cross-origin que requiera preflight falla. La CLI y el
MCP no consumen este servidor HTTP.

## 3. Diseño propuesto

### 3.1 Modelo de amenazas

| Id | Amenaza | En alcance |
|---|---|---|
| T1 | Página maliciosa en el navegador del usuario dispara un POST con efectos (CSRF), incluido un formulario con navegación de nivel superior | Sí |
| T2 | Página maliciosa dispara un GET con efectos (`<img>`, `<iframe>`, navegación) | Sí |
| T3 | DNS rebinding para leer datos sensibles o usar el dashboard como si fuera la propia página | Sí |
| T4 | Clickjacking: el dashboard embebido en otra página | Sí |
| T5 | Otro puerto de `localhost` (otra app local comprometida) | Sí: cuenta como otro origen |
| T6 | Cualquier proceso o usuario que pueda conectarse a `127.0.0.1` (con o sin acceso al sistema de archivos) | No: puede leer el token del HTML de `/` sin autenticarse, y también `runs.db` y `config.yaml` si tiene acceso a disco. El token es una defensa contra páginas web del navegador, no autenticación de clientes locales |
| T7 | Atacante en la red | No: el servidor solo escucha en `127.0.0.1` |
| T8 | Extensión maliciosa del navegador | No |
| T9 | Texto controlado por terceros que el dashboard muestra (mensajes de commit de repos escaneados, prompts de sesiones importadas, parámetros de la URL) inyecta scripts (XSS) | Sí |

### 3.2 Controles

**C1 · `Host` canónico, antes de despachar cualquier método.**

- Debe haber exactamente un encabezado `Host`.
- Se pasa a minúsculas y se separa en host y puerto. El host debe ser `127.0.0.1` o `localhost`; el
  puerto, numérico e igual al del servidor. Un `Host` sin puerto equivale al puerto 80, que es como
  los clientes HTTP serializan el puerto por defecto: se acepta solo si el servidor escucha en el 80
  (`ai-orchestrator serve --port 80`).
- Se rechaza con `421` si falta, si está duplicado o si host o puerto no coinciden. `[::1]` se
  rechaza mientras el servidor escuche solo en IPv4.
- La validación corre antes del despacho en **cualquier verbo**. `BaseHTTPRequestHandler` despacha
  por nombre (`do_<VERBO>`) y responde `501` a los que no conoce, así que la validación va en un hook
  genérico previo al despacho (por ejemplo, sobrescribiendo `handle_one_request` después de
  `parse_request`), no en métodos `do_*` sueltos. GET y POST siguen al despacho; **todo otro verbo**
  (HEAD, PUT, DELETE, PATCH, OPTIONS, TRACE, CONNECT o uno desconocido) responde `405` después de
  validar el `Host` (OPTIONS no habilita CORS).

**C2 · Token de sesión en toda petición con efectos.**

- Al iniciar, el servidor genera `secrets.token_urlsafe(32)` y lo guarda **solo en memoria**.
- El HTML de `/` lo incluye en `<meta name="orchestrator-session" content="…">`.
- El JS envía el token en la cabecera `X-Orchestrator-Session` a través de un helper explícito
  (`postJson`) que reemplaza las 26 llamadas POST actuales (y lo usan también las dos llamadas a
  `/pick-folder` y la nueva a `/chroma-stats/refresh`: 29 en total) y conserva las cabeceras que cada una ya
  envía. Un test estático falla si aparece un `fetch` con método POST fuera del helper.
- El servidor lo compara con `hmac.compare_digest`. Si falta o no coincide responde `403` con
  `{"reason": "session_expired"}` y no ejecuta el handler.
- Una cabecera propia obliga al navegador a hacer preflight en peticiones cross-origin, que el
  servidor no responde: una página ajena no puede enviar la petición. Un formulario HTML no puede
  agregar la cabecera, así que la navegación de nivel superior también queda bloqueada.
- El token no aparece en URLs, logs, respuestas JSON ni en el SSE. Rota en cada reinicio. Cuando el
  JS recibe `session_expired` (incluida una página restaurada desde el bfcache del navegador con el
  token anterior) muestra "El servidor se reinició. Recargá la página para continuar."
- Se descarta una cookie `SameSite`: otro puerto de `localhost` cuenta como el mismo sitio, así que
  no cubre T5.

**C3 · `Origin` y `Sec-Fetch-Site` en peticiones con efectos.** Si el navegador envía `Origin`, se
parsea y debe tener esquema `http`, host `127.0.0.1` o `localhost` y **puerto efectivo** igual al del
servidor, tratando un origen sin puerto como puerto 80 (los navegadores serializan
`http://localhost` sin `:80`). Si envía `Sec-Fetch-Site`, debe ser `same-origin`. Si faltan (clientes que no son navegadores, o navegadores viejos), la petición se
acepta **solo si pasan C2 y C4**. Es defensa en profundidad sobre C2.

**C4 · `Content-Type` exacto.** Se compara la esencia MIME (`application/json`) sin parámetros ni
subcadenas. `text/plain; x=application/json` y `application/x-www-form-urlencoded` se rechazan con
`415`.

**C5 · Sin efectos en GET.**

- `/pick-folder` pasa a `POST` con token; `GET /pick-folder` responde `405`.
- `rates.py` expone una lectura **solo de caché** que usan `GET /rates`, `/inspect`, `/metrics` e
  `/integrations/status`. El refresco por red queda exclusivamente en `POST /rates/refresh`; el
  dashboard lo pide de forma explícita cuando el dato está viejo.
- Las estadísticas de ChromaDB dejan de calcularse en los GET. El servidor guarda el último
  resultado con su fecha; se recalcula al iniciar y con el endpoint nuevo `POST /chroma-stats/refresh`, con token (botón "Actualizar" de
  la sección Datos). `GET /inspect` y `GET /clean-preview` devuelven ese valor y su antigüedad, sin
  lanzar procesos.
- `/integrations/status` devuelve solo `configured` para el Banco Central, sin el usuario.
- `GET /pricing` mantiene su comportamiento actual (caché o catálogo estático).

**C6 · Cabeceras de seguridad centralizadas.** Un único punto de envío de cabeceras (por ejemplo,
`end_headers` sobrescrito) agrega en **todas** las respuestas, también en `4xx`, `5xx` y archivos:
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` y
`Content-Security-Policy: frame-ancestors 'none'`. Toda respuesta dinámica (HTML, fragmentos HTML,
JSON, CSV y SSE) lleva además `Cache-Control: no-store`. Los archivos de `/static/*` pueden
cachearse. El SSE conserva su `Access-Control-Allow-Origin` actual, nunca `*`.

**C7 · Serialización segura en HTML y scripts (requisito de los demás controles).**

- Todo dato insertado dentro de un `<script>` pasa por un único helper que serializa a JSON y escapa
  `<`, `>`, `&`, U+2028 y U+2029 como secuencias `\uXXXX`, de modo que ningún texto pueda cerrar el
  bloque. Reemplaza los `json.dumps` de `dashboard.py:341` y `676`.
- Todo dato insertado en HTML pasa por el escape de HTML existente (`_escape`); en el JS, todo
  `innerHTML` construido con datos usa el helper de escape (§23.7 de la especificación).
- **Ningún dato va dentro de un handler en línea** (`onclick`, `onkeydown`…). El escape HTML no
  protege una cadena JavaScript dentro de un atributo, porque el navegador decodifica la entidad
  antes de ejecutar el handler. Los datos van en atributos `data-*` (escapados como HTML) y el
  handler los lee con `dataset`, o se usa delegación de eventos.
- Inventario de sumideros del baseline (auditoría de Codex), que D0 cierra:

  | Id | Ubicación | Sumidero | Dato | Severidad | Codificación esperada |
  |---|---|---|---|---|---|
  | X01 | `dashboard.py:341-350`, `661-663` | JSON en `<script>` | `task_preview` y demás campos de runs | Crítica | Helper de JSON para `<script>` |
  | X02 | `dashboard.py:676` | JSON en `<script>` | Parámetro `?project=` | Crítica | Helper de JSON para `<script>` y validación contra proyectos conocidos |
  | X03 | `dashboard.py:235` | `onclick` con el título del contexto | Título de contexto | Alta | Atributo `data-*` escapado como HTML, leído con `dataset` |
  | X04 | `server.py:325-338` y `dashboard_js.py:253-257` | `/contexts-html` interpretado con `innerHTML` | Hereda X03 | Alta | Se cierra con X03 |
  | X05 | `dashboard_js.py:1915-1919` | `onclick`/`onkeydown` con el alias entre comillas simples | Alias de proyecto (sin validar en `/add-project` y `/project/rename`) | Alta | Atributos `data-*` y listeners delegados |
  | X06 | `dashboard.py:199-200`, `246`; `dashboard_js.py:92`, `513-522` | IDs en `onclick`, `data-*` y selectores | IDs de run, contexto y paso (enteros de SQLite) | Baja | Convertir con `Number()` (JS) o `int()` (Python) antes de interpolar; sin handlers en línea |
  | X07 | `dashboard_js.py:271-305`, `423-525` | `innerHTML` de detalle de contexto y de run | IDs, índices, duraciones y fechas de `/context/{id}` y `/run/{id}` | Baja | `escHtml` en todo campo, también los estructurales |
  | X08 | `dashboard_js.py:728-733` | `innerHTML` de eventos SSE | Fecha formateada de `d.ts` (`/events`) | Baja | `escHtml` sobre la fecha formateada |
  | X09 | `dashboard_js.py:1120-1129` | HTML de estados, con respaldo `STATUS_LABELS[s] \|\| s` | Estado de contexto desde SQLite | Baja | `escHtml` sobre el respaldo `s` |
  | X10 | `dashboard_js.py:1689-1703` | `innerHTML` de la vista previa de indexación | `f.file_count` de `/preview-index` | Baja | `escHtml(String(...))` o `Number()` |
  | X11 | `dashboard.py:669-672` | `insertAdjacentHTML` del error de JavaScript | `e.message` y `e.stack` | Media | `textContent` en lugar de HTML |

  Los X01–X05 entran en el arreglo inmediato; los X06–X11 se corrigen en D0, con un test cada uno
  (I15). Las líneas son del baseline y se reubican al implementar.
- El parámetro `project` de la URL se valida contra los alias registrados antes de usarse.
- Una política `Content-Security-Policy` con `script-src` basada en nonce queda para D1, cuando los
  scripts salgan del HTML en línea (§23.7); hasta entonces, C7 es la defensa.

### 3.3 Orden de validación

En todos los métodos, primero C1. En GET, después el despacho. En POST, en este orden: C3, C2, C4 y
el despacho. Las cabeceras de C6 se agregan en todos los casos, incluidas las respuestas de rechazo.
La ruta `/context/{id}/delete`, que hoy se resuelve en una rama aparte antes del diccionario de
rutas (`server.py:574-578`), pasa por el mismo pipeline: la validación va antes de cualquier rama.

## 4. Invariantes / Requisitos falsables

| Id | Invariante | Prueba |
|---|---|---|
| I1 | Ningún POST sin token válido produce efectos | Test HTTP por cada uno de los **27** POST de D0 (los 25 actuales más `/pick-folder` y `/chroma-stats/refresh`): sin token, con token inválido y con token válido; la base y los archivos no cambian en los dos primeros casos, y en `/pick-folder` no se abre el selector en los dos casos rechazados: se mockea el punto de entrada de cada plataforma (`subprocess.run` en Windows, `tkinter.filedialog.askdirectory` en Linux y macOS, `server.py:167-202`) o un helper `_pick_folder()` extraído en D0 |
| I2 | Ninguna petición con `Host` no permitido llega al despacho | Para GET, POST, SSE, HEAD, PUT, DELETE, PATCH, OPTIONS, TRACE, CONNECT y un verbo inventado: `Host` ajeno, ausente, duplicado, sin puerto con el servidor en 8080 (→ `421`), sin puerto con el servidor en 80 (se acepta), con otro puerto, en mayúsculas válidas (se acepta) y `[::1]` → `421` salvo los casos válidos |
| I3 | El bypass por subcadena ya no funciona | POST con token válido y `Content-Type: text/plain; x=application/json` o `application/x-www-form-urlencoded` → `415` |
| I4 | `GET /pick-folder` no lanza procesos ni abre el selector | `GET` → `405`; ni `subprocess.run` ni `tkinter.filedialog.askdirectory` (o el helper `_pick_folder()`) se invocan (mocks), de modo que el test no es vacío en el CI de Linux |
| I5 | Ningún GET usa la red, escribe ni lanza procesos | Con caché viejo y credenciales configuradas, `GET /rates`, `/inspect`, `/metrics`, `/integrations/status` y `/pricing` no llaman a la red ni escriben; `GET /inspect` y `/clean-preview` no invocan `subprocess` (mocks) |
| I6 | El token no se filtra | No aparece en logs, respuestas JSON ni en el SSE; solo en el `<meta>` de `/` |
| I7 | El dashboard sigue funcionando | Test que recorre las acciones con el token del HTML; prueba manual de cada botón |
| I8 | `Origin` y `Sec-Fetch-Site` se aplican | POST con token válido y `Origin` ajeno → `403`; `Sec-Fetch-Site: cross-site` → `403`; sin ambos y con token válido → aceptado; con el servidor en el puerto 80, `Origin: http://localhost` y `Origin: http://127.0.0.1` (sin `:80`) → aceptados, y `Origin: http://localhost:8080` o `http://atacante.example` → `403` |
| I9 | Las cabeceras de seguridad están en toda respuesta | `X-Frame-Options`, `frame-ancestors` y `nosniff` presentes en `200`, `403`, `404` (POST a ruta desconocida), `405`, `415`, `421` y `500`, y en un archivo de `/static/*`; `no-store` en toda respuesta dinámica |
| I10 | Los métodos no soportados no exponen nada | HEAD, PUT, DELETE, PATCH, OPTIONS, TRACE, CONNECT y un verbo inventado (con `Host` válido) → `405` con las cabeceras de C6, nunca `501` |
| I11 | Un token viejo se trata como sesión vencida | Tras reiniciar el servidor, un POST con el token anterior → `403 session_expired`; el JS muestra el mensaje de recarga |
| I12 | No se exponen identificadores de credenciales | `/integrations/status` no incluye el usuario del Banco Central |
| I13 | Todas las llamadas POST envían el token | Test estático: ningún `fetch` con método POST fuera de `postJson` en el JS del dashboard |
| I14 | Ningún dato rompe un bloque `<script>` | Test con un run cuyo `task_preview` contiene `</script><script>…</script>`, `<!--` y U+2028, y con `?project=` malicioso: el HTML no contiene `</script>` fuera de los cierres propios, y en un navegador headless el script inyectado no se ejecuta |
| I15 | Los sumideros de HTML escapan los datos según su contexto | Un test por cada sumidero del inventario de C7 que recibe datos de runs, contextos, pasos, alias o URL; un título de contexto y un alias con `'` y `);alert(1);//` no ejecutan código; ningún handler en línea recibe datos |

## 5. Alcance

**Dentro:** `orchestrator/server.py`, `orchestrator/dashboard.py`, `orchestrator/dashboard_js.py`
(helper `postJson` y `<meta>`), `orchestrator/rates.py` (lectura solo de caché) y
`tests/test_server_security.py`.

**Fuera:** autenticación de usuarios, TLS, acceso remoto, la extensión de VS Code y el acceso por
MCP (RFC-008).

## 6. Riesgos

| Riesgo | Severidad | Estado/Mitigación |
|---|---|---|
| Pestañas abiertas fallan tras reiniciar el servidor | Baja | Aceptado: `session_expired` con mensaje de recarga; el token no se persiste a propósito |
| Alguna llamada POST queda fuera del helper | Media | Mitigado por I13 (test estático) e I7 (recorrido de acciones) |
| Un proceso local lee el token del HTML y lo usa | Media | Aceptado y fuera de alcance (T6): el token no es autenticación de clientes locales |
| Herramientas externas que hoy llaman al dashboard por HTTP | Baja | Verificado: ninguna en el repo; un script externo del usuario tendría que leer el token de `/` |
| El tipo de cambio deja de refrescarse solo | Baja | Mitigado: el dashboard llama a `POST /rates/refresh` cuando el dato está viejo |
| Las estadísticas de ChromaDB se muestran desactualizadas | Baja | Mitigado: se muestran con su antigüedad y se recalculan al iniciar y con el botón "Actualizar" |
| Una página dispara `GET /preview-index` repetidamente (recorrido de disco) | Baja | Aceptado: sin efectos persistentes y sin lectura posible de la respuesta desde otra página (C1) |

## 7. Plan de implementación

Fase D0 de la especificación, implementada por Codex CLI en un worktree, con auditoría de Copilot
CLI (ronda 1) y Claude (ronda 2). Un solo PR con los archivos de §5. Criterio de salida: I1 a I15 en
verde y la suite completa sin regresiones.

## 8. Criterios de merge

- Este RFC pasa a `accepted` cuando el usuario firma la lista de verificación de abajo.
- Auditoría cruzada de dos rondas (ANL-003) sobre este documento.

**Lista de verificación para el usuario:**

- [ ] El modelo de amenazas de §3.1 (en alcance y fuera de alcance) es el correcto.
- [ ] El token protege contra páginas web del navegador, no contra procesos o usuarios que puedan
      conectarse a `127.0.0.1` (pueden leerlo del HTML); eso queda aceptado fuera de alcance.
- [ ] El token de sesión vive solo en memoria y rota en cada reinicio, aceptando que las pestañas
      abiertas tengan que recargarse.
- [ ] Ningún GET refresca por red; el refresco del tipo de cambio pasa a ser explícito.
- [ ] `/pick-folder` pasa a POST.
- [ ] `/integrations/status` deja de mostrar el usuario de las credenciales.
- [ ] El dashboard no se podrá embeber en ninguna otra página.
- [ ] El XSS del dashboard actual se corrige: primero con un arreglo inmediato fuera de D0 (por su
      severidad) y después con el inventario completo de C7 en D0.
- [ ] Las invariantes I1 a I15 son el criterio de aceptación de D0.

## Apéndice A — Referencias

- PR #28, `docs/backlog/DASHBOARD_VISUALIZACION_ESPECIFICACION.md` §13 (estado y objetivo), §24.4
  (token en el frontend) y §24.5 (unidad D0).
- RFC-008: acceso MCP gobernado.
- ANL-003: auditoría cruzada por cambio.
- Especificación Fetch: cabeceras con lista segura para CORS (esencia MIME de `Content-Type`).
