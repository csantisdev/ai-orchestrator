// Router del dashboard (spec §23.3, §23.7): el estado de navegación vive en la URL,
// así cualquier vista y selección se puede compartir o recargar.
// `parseLocation` y `toSearch` son puras; `connectRouter` las enlaza con history.

export const VIEWS = Object.freeze([
  "inicio", "trabajo", "ejecuciones", "gobernanza",
  "proveedores", "politicas", "ajustes",
]);
export const DEFAULT_VIEW = "inicio";
export const REPRESENTATIONS = Object.freeze(["list", "map", "constellation"]);
// `sel` identifica el objeto del Inspector con el formato `tipo:id` (§23.3).
const SELECTION = /^(context|step|run|commit|decision):[A-Za-z0-9_-]{1,64}$/;
const PROJECT = /^[^\u0000-\u001f]{1,200}$/;
const TAB = /^[a-z][a-z0-9-]{0,31}$/;
// Orden fijo de los parámetros: la misma navegación produce siempre la misma URL.
const KEYS = ["project", "view", "tab", "ctx", "step", "as", "sel"];

function positiveInt(value) {
  return /^[1-9][0-9]{0,9}$/.test(value ?? "") ? Number(value) : null;
}

export function parseLocation(search) {
  const params = new URLSearchParams(search);
  const view = params.get("view");
  const project = params.get("project");
  const tab = params.get("tab");
  const as = params.get("as");
  const sel = params.get("sel");
  return {
    project: project && PROJECT.test(project) ? project : null,
    view: VIEWS.includes(view) ? view : DEFAULT_VIEW,
    tab: tab && TAB.test(tab) ? tab : null,
    ctx: positiveInt(params.get("ctx")),
    step: positiveInt(params.get("step")),
    as: REPRESENTATIONS.includes(as) ? as : null,
    sel: sel && SELECTION.test(sel) ? sel : null,
  };
}

export function toSearch(state) {
  const params = new URLSearchParams();
  for (const key of KEYS) {
    const value = state[key];
    if (value === null || value === undefined || value === "") continue;
    if (key === "view" && value === DEFAULT_VIEW) continue;
    params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
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
