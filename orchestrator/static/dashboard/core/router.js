// Router del dashboard (spec §23.3, §23.7): el estado de navegación vive en la URL,
// así cualquier vista y selección se puede compartir o recargar.
// `parseLocation` y `toSearch` son puras; `connectRouter` las enlaza con history.

export const VIEWS = Object.freeze([
  "inicio", "trabajo", "ejecuciones", "gobernanza",
  "proveedores", "politicas", "ajustes",
]);
export const DEFAULT_VIEW = "inicio";
export const REPRESENTATIONS = Object.freeze(["list", "map", "constellation"]);
// `sel` identifica el objeto del Inspector con el formato `tipo:id` (§23.3), tipado:
// commits por SHA completo, decisiones por origen (mcp o egress) e id, y el resto por id.
const SELECTION = [
  /^(context|step|run):[1-9][0-9]{0,9}$/,
  /^commit:(?:[0-9a-f]{40}|[0-9a-f]{64})$/,
  /^decision:(?:mcp|egress)-[1-9][0-9]{0,9}$/,
];
// Alias de proyecto: el servidor ya valida `?project=` contra los proyectos conocidos y
// los alias no tienen restricción de caracteres, así que acá solo se descartan caracteres
// de control y longitudes absurdas. El shell lo usa siempre como texto (textContent o la
// propiedad `value`), nunca como HTML.
const PROJECT = /^[^\u0000-\u001f\u007f]{1,200}$/u;
const TAB = /^[a-z][a-z0-9-]{0,31}$/;
// Orden fijo de los parámetros: la misma navegación produce siempre la misma URL.
const KEYS = ["project", "view", "tab", "ctx", "step", "as", "sel"];

function positiveInt(value) {
  const text = value === null || value === undefined ? "" : String(value);
  return /^[1-9][0-9]{0,9}$/.test(text) ? Number(text) : null;
}

function text(value, pattern) {
  return typeof value === "string" && pattern.test(value) ? value : null;
}

// Valida y completa un estado; lo que no es válido queda en null o en su valor por defecto.
export function normalizeState(raw) {
  const sel = typeof raw.sel === "string" && SELECTION.some((rule) => rule.test(raw.sel)) ? raw.sel : null;
  return {
    project: text(raw.project, PROJECT),
    view: VIEWS.includes(raw.view) ? raw.view : DEFAULT_VIEW,
    tab: text(raw.tab, TAB),
    ctx: positiveInt(raw.ctx),
    step: positiveInt(raw.step),
    as: REPRESENTATIONS.includes(raw.as) ? raw.as : null,
    sel,
  };
}

export function parseLocation(search) {
  const params = new URLSearchParams(search);
  return normalizeState(Object.fromEntries(KEYS.map((key) => [key, params.get(key)])));
}

export function toSearch(state) {
  const valid = normalizeState(state);
  const params = new URLSearchParams();
  for (const key of KEYS) {
    const value = valid[key];
    if (value === null) continue;
    if (key === "view" && value === DEFAULT_VIEW) continue;
    params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

// Enlaza el store con la barra de direcciones: los cambios de estado agregan una entrada
// al historial y el botón Atrás restaura el estado anterior. Una URL no canónica (valores
// inválidos o en otro orden) se reemplaza por la canónica sin agregar entradas.
export function connectRouter({ store, history, location, addEventListener }) {
  let restoring = false;
  const canonicalize = () => {
    const search = toSearch(store.get());
    if (search !== location.search) history.replaceState(null, "", `${location.pathname}${search}`);
  };
  store.set(parseLocation(location.search));
  canonicalize();
  const unsubscribe = store.subscribe((state) => {
    if (restoring) return;
    const search = toSearch(state);
    if (search !== location.search) history.pushState(null, "", `${location.pathname}${search}`);
  });
  addEventListener("popstate", () => {
    restoring = true;
    try {
      store.set(parseLocation(location.search));
    } finally {
      restoring = false;
    }
    canonicalize();
  });
  return unsubscribe;
}
