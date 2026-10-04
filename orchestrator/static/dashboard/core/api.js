// Cliente de la API JSON del dashboard (`/api/v1/`, spec §24.3.2). Las vistas no llaman a
// `fetch` directo: este módulo agrega la cabecera de sesión en los POST (RFC-009 C2) y
// convierte las respuestas de error en `ApiError` con el status y el motivo del servidor.

export const API_PREFIX = "/api/v1/";

export class ApiError extends Error {
  constructor(status, message, payload = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
    // `session_expired`: el servidor se reinició y hay que recargar la página.
    this.reason = payload?.reason ?? null;
  }
}

// Solo la ruta: segmentos no vacíos de caracteres no reservados que no empiezan con punto.
// Sin `%` (nada que el navegador decodifique a `..` o `/`), sin `\`, `?` ni `#`: la query
// sale únicamente de `params`.
const API_PATH = /^\/api\/v1\/(?:[A-Za-z0-9_~-][A-Za-z0-9._~-]*\/?)*$/;

function buildUrl(path, params) {
  if (typeof path !== "string" || !API_PATH.test(path)) {
    throw new TypeError(`ruta fuera de ${API_PREFIX}: ${String(path)}`);
  }
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === null || value === undefined || value === "") continue;
    query.set(key, String(value));
  }
  const search = query.toString();
  return search ? `${path}?${search}` : path;
}

export function createApi({ fetch, sessionToken }) {
  async function request(method, path, { params, body, signal } = {}) {
    const headers = { Accept: "application/json" };
    if (method === "POST") {
      headers["Content-Type"] = "application/json";
      headers["X-Orchestrator-Session"] = sessionToken();
    }
    const response = await fetch(buildUrl(path, params), {
      method,
      headers,
      body: method === "POST" ? JSON.stringify(body ?? {}) : undefined,
      credentials: "same-origin",
      signal,
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const message = payload?.error ?? payload?.reason ?? `HTTP ${response.status}`;
      throw new ApiError(response.status, message, payload);
    }
    return payload;
  }

  return {
    get: (path, options = {}) => request("GET", path, options),
    post: (path, body = {}, options = {}) => request("POST", path, { ...options, body }),
  };
}
