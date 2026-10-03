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
**Versión:** 0.1
**Fecha:** 2026-10-03
**Repo de referencia:** `csantisdev/ai-orchestrator@production` = `985b74970477e729eda97ee0728ab6575b523014` (verificado 2026-10-03)
**Relación con la serie:** Es la fase R0 de la especificación del dashboard
(`docs/backlog/DASHBOARD_VISUALIZACION_ESPECIFICACION.md`, §13, §24.4 y §24.5) y precede a la fase
D0, que lo implementa. Complementa a RFC-008, que gobierna el acceso por MCP: este documento cubre
solo el servidor HTTP del dashboard (`ai-orchestrator serve`). No cubre acceso remoto ni la
extensión de VS Code, descartada por ahora.

*Todo ejemplo usa datos sintéticos. Ver "Regla de anonimización" en `../README.md`.*

---

## 0. Resumen ejecutivo

El dashboard escucha en `127.0.0.1` y ejecuta acciones con efectos (borrar contextos, purgar
ChromaDB, lanzar runs con costo, ejecutar `doctor`/`fix`) sin autenticar quién las pide. Cualquier
página abierta en el navegador del usuario puede disparar varias de esas acciones, y un ataque de DNS
rebinding puede leer datos completos de runs. Este RFC propone cinco controles para D0: validación
de `Host` en toda petición, token de sesión obligatorio en toda petición con efectos, `Origin`
permitido, `Content-Type` exacto y eliminación de efectos en peticiones GET. Además agrega
cabeceras que impiden embeber el dashboard en otra página.

Lo que este documento **no** afirma: no protege contra otros procesos o usuarios con acceso al
sistema de archivos (pueden leer `runs.db` directamente), no agrega autenticación de usuarios ni
TLS, y no habilita el acceso desde otra máquina.

## 1. El problema

Verificado en `orchestrator/server.py` del baseline:

1. **`do_POST` no valida `Origin` ni `Host`** (`server.py:573`). La única barrera es
   `_require_json_ct` (`server.py:560`), que exige `application/json` como **subcadena** del
   `Content-Type`. Un `fetch` desde otra página con `Content-Type: text/plain; x=application/json`
   es una petición CORS simple (sin preflight, porque la esencia MIME es `text/plain`) y pasa el
   chequeo. El navegador envía la petición; la página atacante no puede leer la respuesta, pero el
   efecto ocurre.
2. **Hay peticiones GET con efectos**, que se disparan con un simple `<img src>` desde cualquier
   página:
   - `GET /pick-folder` lanza un proceso que abre un diálogo nativo de selección de carpeta.
   - `GET /rates` consulta la red y escribe el caché de tipos de cambio si el dato está viejo y hay
     credenciales (`rates.get_current_rate`).
   - `GET /pricing` puede consultar el catálogo remoto y escribir su caché (`catalog.resolve_pricing`).
3. **Hay GET con datos sensibles sin validar `Host`**: `/run/{id}` y `/export-csv` devuelven tareas
   y respuestas completas; `/context/{id}`, `/contexts-html`, `/inspect` y `/events` exponen el plan
   de trabajo y la actividad. Con DNS rebinding (un dominio del atacante que primero resuelve a su
   servidor y después a `127.0.0.1`) una página puede leerlos, porque el navegador la considera del
   mismo origen y el servidor no mira el `Host`.
4. **El dashboard se puede embeber** en otra página: no envía `X-Frame-Options` ni
   `frame-ancestors`, lo que habilita clickjacking sobre sus botones.

Severidad: alta para (1) y (2), porque hay acciones destructivas (`/delete-contexts`,
`/purge-chroma-*`) y con costo (`/run`). Media para (3) y (4).

## 2. Estado verificado del código

### 2.1 Inventario de endpoints

**POST con efectos** (25), todos con `_require_json_ct` como única barrera:

| Categoría | Endpoints |
|---|---|
| Destructivos | `/context/{id}/delete`, `/delete-contexts`, `/purge-chroma-docs`, `/purge-chroma-responses`, `/clean/unmapped`, `/clear-imports` |
| Mutan el tracking | `/create-context`, `/advance-step`, `/skip-step`, `/rate-run`, `/evaluate-run`, `/import-context` |
| Mutan la configuración | `/add-project`, `/project/rename`, `/config/bcentral` (credenciales) |
| Lanzan procesos o tareas largas | `/sync-cc`, `/sync-git`, `/sync-codex`, `/index-docs`, `/run-doctor`, `/run-fix` |
| Red o costo | `/run` (llama a un proveedor de IA), `/rates/refresh`, `/pricing/refresh`, `/models/refresh` |

**GET con efectos** (3): `/pick-folder`, `/rates`, `/pricing`.

**GET con datos sensibles**: `/run/{id}`, `/export-csv`, `/context/{id}`, `/contexts-html`,
`/inspect`, `/metrics`, `/preview-index`, `/clean-preview`, `/events` (SSE) y `/` (HTML con los
últimos runs embebidos).

**GET públicos del propio dashboard**: `/static/*`, `/favicon.ico`, `/robots.txt`, `/docs`, `/mcp`,
`/security`, `/integrations/status`, `/models`, `/agents`.

### 2.2 Bind y CORS

El servidor escucha en `127.0.0.1:<puerto>` (`server.py:1518`). El SSE responde con
`Access-Control-Allow-Origin: http://127.0.0.1:<puerto>` (`server.py:1462`, `1485`). No hay
respuesta a `OPTIONS`, así que toda petición cross-origin que requiera preflight falla.

## 3. Diseño propuesto

### 3.1 Modelo de amenazas

| Id | Amenaza | En alcance |
|---|---|---|
| T1 | Página maliciosa en el navegador del usuario dispara un POST con efectos (CSRF) | Sí |
| T2 | Página maliciosa dispara un GET con efectos (`<img>`, `<iframe>`, navegación) | Sí |
| T3 | DNS rebinding para leer datos sensibles o usar el dashboard como si fuera la propia página | Sí |
| T4 | Clickjacking: el dashboard embebido en otra página | Sí |
| T5 | Otro puerto de `localhost` (otra app local comprometida) | Sí: cuenta como otro origen |
| T6 | Proceso local con acceso al sistema de archivos del usuario | No: puede leer `runs.db` y `config.yaml` |
| T7 | Atacante en la red | No: el servidor solo escucha en `127.0.0.1` |
| T8 | Extensión maliciosa del navegador | No |

### 3.2 Controles

**C1 · `Host` permitido en toda petición** (GET, POST y SSE). El `Host` debe ser exactamente
`127.0.0.1:<puerto>` o `localhost:<puerto>`. Si no, `421 Misdirected Request` sin ejecutar el
handler. Cubre T3: en un DNS rebinding el `Host` es el dominio del atacante.

**C2 · Token de sesión en toda petición con efectos.**

- Al iniciar, el servidor genera `secrets.token_urlsafe(32)` y lo guarda **solo en memoria**.
- El HTML de `/` lo incluye en `<meta name="orchestrator-session" content="…">`.
- El JS envía el token en la cabecera `X-Orchestrator-Session` en cada POST, a través de un único
  envoltorio de `fetch` en el código heredado (`dashboard_js.py`) y, después, en `core/api.js`.
- El servidor lo compara con `hmac.compare_digest`; si falta o no coincide, `403` sin efecto.
- Una cabecera propia obliga al navegador a hacer preflight en peticiones cross-origin, que el
  servidor no responde: una página ajena no puede ni siquiera enviar la petición.
- El token no aparece en URLs, logs, respuestas JSON ni en el SSE. Rota en cada reinicio: si el
  servidor se reinicia, una pestaña abierta recibe `403` y muestra "El servidor se reinició.
  Recargá la página para continuar."
- Se descarta una cookie `SameSite`: otro puerto de `localhost` cuenta como el mismo sitio, así que
  no cubre T5.

**C3 · `Origin` permitido en peticiones con efectos.** Si el navegador envía `Origin`, debe ser
`http://127.0.0.1:<puerto>` o `http://localhost:<puerto>`. Si envía `Sec-Fetch-Site`, debe ser
`same-origin`. Es defensa en profundidad sobre C2.

**C4 · `Content-Type` exacto.** Se compara la esencia MIME (`application/json`), sin parámetros ni
subcadenas. `text/plain; x=application/json` se rechaza con `415`.

**C5 · Sin efectos en GET.**

- `/pick-folder` pasa a `POST` con token. `GET /pick-folder` responde `405`.
- `GET /rates` y `GET /pricing` leen **solo el caché**. El refresco por red queda exclusivamente en
  los POST existentes `/rates/refresh` y `/pricing/refresh`.

**C6 · Cabeceras de respuesta.** En todas las respuestas: `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY` y `Content-Security-Policy: frame-ancestors 'none'` (cubre T4). En las
respuestas con datos (`/`, `/run/{id}`, `/export-csv`, `/context/{id}` y los JSON): `Cache-Control:
no-store`. El SSE conserva su `Access-Control-Allow-Origin` actual, nunca `*`.

### 3.3 Orden de validación

Antes de despachar cualquier handler: C1 (`Host`). En POST, además y en este orden: C3 (`Origin`),
C2 (token) y C4 (`Content-Type`). La validación está centralizada en un solo punto de
`do_GET`/`do_POST`, no en cada handler.

## 4. Invariantes / Requisitos falsables

| Id | Invariante | Prueba |
|---|---|---|
| I1 | Ningún POST sin token válido produce efectos | Test HTTP por cada uno de los 25 POST: sin token, con token inválido y con token válido; la base y los archivos no cambian en los dos primeros casos |
| I2 | Ninguna ruta responde con `Host` no permitido | Test con `Host: atacante.example` en GET, POST y SSE → `421` |
| I3 | El bypass por subcadena ya no funciona | POST con `Content-Type: text/plain; x=application/json` y token válido → `415` |
| I4 | `GET /pick-folder` no lanza procesos | `GET` → `405`; `subprocess` no se invoca (mock) |
| I5 | `GET /rates` y `GET /pricing` no usan la red | Con caché viejo y credenciales configuradas, la función de red no se llama (mock) |
| I6 | El token no se filtra | No aparece en logs, en respuestas JSON ni en el SSE; solo en el `<meta>` de `/` |
| I7 | El dashboard sigue funcionando | Test que recorre las acciones del dashboard con el token del HTML; prueba manual de cada botón |
| I8 | `Origin` ajeno se rechaza | POST con token válido y `Origin: http://localhost:9999` → `403` |
| I9 | El dashboard no se puede embeber | Cabeceras `X-Frame-Options: DENY` y `frame-ancestors 'none'` presentes en `/` |

## 5. Alcance

**Dentro:** `orchestrator/server.py`, `orchestrator/dashboard.py`, `orchestrator/dashboard_js.py`
(envoltorio de `fetch` y `<meta>`), `orchestrator/rates.py` y `orchestrator/catalog.py` (separar
lectura de caché y refresco), y `tests/test_server_security.py`.

**Fuera:** autenticación de usuarios, TLS, acceso remoto, la extensión de VS Code y el acceso por
MCP (RFC-008).

## 6. Riesgos

| Riesgo | Mitigación |
|---|---|
| Pestañas abiertas fallan tras reiniciar el servidor | Mensaje explícito para recargar; el token no se persiste a propósito |
| Algún botón del dashboard actual no pasa por el envoltorio de `fetch` | El test de I7 recorre las acciones; búsqueda de `fetch(` con método POST en `dashboard_js.py` sin el envoltorio |
| Herramientas que hoy llaman al dashboard por HTTP | Ninguna en el repo (verificado: la CLI y el MCP no usan el servidor HTTP); scripts externos del usuario necesitarían el token, que solo existe en memoria |
| `GET /rates` deja de refrescar solo | El dashboard llama a `POST /rates/refresh` cuando el dato está viejo, de forma explícita |

## 7. Plan de implementación

Fase D0 de la especificación, implementada por Codex CLI en un worktree, con auditoría de Copilot
CLI (ronda 1) y Claude (ronda 2) (§24.5). Un solo PR con los archivos de §5. Criterio de salida:
I1 a I9 en verde y la suite completa sin regresiones.

## 8. Criterios de merge

- Este RFC pasa a `accepted` cuando el usuario firma la lista de verificación de abajo.
- Auditoría cruzada de dos rondas (ANL-003) sobre este documento.

**Lista de verificación para el usuario:**

- [ ] El modelo de amenazas de §3.1 (en alcance y fuera de alcance) es el correcto.
- [ ] El token de sesión vive solo en memoria y rota en cada reinicio, aceptando que las pestañas
      abiertas tengan que recargarse.
- [ ] `GET /rates` y `GET /pricing` dejan de refrescar por red; el refresco es explícito.
- [ ] `/pick-folder` pasa a POST.
- [ ] El dashboard no se podrá embeber en ninguna otra página.
- [ ] Las invariantes I1 a I9 son el criterio de aceptación de D0.

## Apéndice A — Referencias

- `docs/backlog/DASHBOARD_VISUALIZACION_ESPECIFICACION.md` §13 (estado y objetivo), §24.4 (token en
  el frontend) y §24.5 (unidad D0).
- RFC-008: acceso MCP gobernado.
- ANL-003: auditoría cruzada por cambio.
- Especificación Fetch, cabeceras con lista segura para CORS (esencia MIME de `Content-Type`).
