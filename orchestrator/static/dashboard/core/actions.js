// Acciones del menú del header (§23.4). Las del dashboard heredado viven en sus pestañas
// (Ejecuciones › Actividad y Trabajo › Flujos), que el shell oculta fuera de ellas: primero
// se navega y después se abre el formulario. Sin acceso global al DOM, para `node --test`.

import { openShortcuts } from "./keyboard.js";

export const ACTIONS = Object.freeze({
  "clear-selection": ({ store }) => store.set({ sel: null }),
  shortcuts: ({ doc }) => openShortcuts(doc),
  "new-task": ({ store, doc }) => {
    store.set({ view: "ejecuciones", tab: "actividad" });
    const panel = doc.getElementById("senderPanel");
    panel?.classList.add("open");
    panel?.scrollIntoView?.({ block: "start" });
    doc.getElementById("senderTask")?.focus();
  },
  "new-flow": ({ store, doc }) => {
    store.set({ view: "trabajo", tab: "flujos" });
    const title = doc.getElementById("ctxTitle");
    title?.scrollIntoView?.({ block: "center" });
    title?.focus();
  },
});

// Ejecuta la acción `name` y cierra el menú; devuelve false si no existe.
export function runAction(name, { store, doc }) {
  const action = ACTIONS[name];
  if (!action) return false;
  const menu = doc.getElementById("shell-menu");
  if (menu) menu.open = false;
  action({ store, doc });
  return true;
}

// Navegación por `data-view`/`data-tab` (enlaces de la navegación, pestañas, tarjetas de las
// vistas): el estado que el shell pone en el store, o null si el clic no navega acá.
export function navigationFor(dataset, event = {}) {
  if (!dataset?.view) return null;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1) return null;
  return { view: dataset.view, tab: dataset.tab ?? null };
}
