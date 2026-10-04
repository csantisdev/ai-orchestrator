// Montaje de vistas nuevas en el shell (spec §23.7: migración por verticales).
//
// Una sección con `module` en core/sections.js se dibuja con un módulo ES de
// `static/dashboard/views/` que exporta:
//
//   export async function mount(root, { store, api, state, signal }) {
//     ...dibuja dentro de root (con core/dom.js)...
//     return { update(state) { ... }, unmount() { ... } };   // ambos opcionales
//   }
//
// `signal` se aborta al salir de la sección: los fetch pendientes deben usarlo. `update`
// recibe cada cambio de estado del router mientras la sección sigue visible.

const MODULE_PATH = /^\.\/views\/[a-z][a-z0-9-]*\.js$/;

export function createViewHost({ root, load }) {
  let current = null;
  // Montaje en curso: { id, controller, state } mientras `load`/`mount` esperan.
  let pending = null;
  let generation = 0;

  // Síncrono a propósito: `show` toma su generación y registra `pending` antes del primer
  // `await`, así dos llamadas seguidas nunca comparten generación.
  function teardown() {
    generation += 1;
    if (pending) pending.controller.abort();
    pending = null;
    const previous = current;
    current = null;
    if (!previous) return;
    previous.controller.abort();
    try {
      previous.handle.unmount?.();
    } finally {
      root.replaceChildren();
    }
  }

  async function show(id, modulePath, context) {
    if (!MODULE_PATH.test(modulePath)) throw new TypeError(`módulo de vista inválido: ${modulePath}`);
    if (current && current.id === id) {
      current.handle.update?.(context.state);
      return;
    }
    // La misma vista ya se está montando: guarda el estado más reciente para entregarlo
    // con `update` al terminar, en lugar de reiniciar la carga.
    if (pending && pending.id === id) {
      pending.state = context.state;
      return;
    }
    teardown();
    const mine = generation;
    const controller = new AbortController();
    pending = { id, controller, state: context.state };
    const stale = () => mine !== generation;
    let handle;
    try {
      const module = await load(modulePath);
      if (stale()) return;
      if (typeof module?.mount !== "function") throw new TypeError(`${modulePath} no exporta mount()`);
      // Cada montaje dibuja en su propio contenedor: si otra sección lo reemplaza mientras
      // este todavía carga datos, lo que dibuje después queda en un nodo desconectado.
      const container = root.ownerDocument.createElement("div");
      container.className = "shell-view";
      container.dataset.view = id;
      root.replaceChildren(container);
      handle = (await module.mount(container, { ...context, signal: controller.signal })) ?? {};
    } catch (error) {
      // Un error de una vista que ya se reemplazó no le corresponde a la vista actual.
      if (stale()) return;
      pending = null;
      root.replaceChildren();
      throw error;
    }
    if (stale()) {
      controller.abort();
      handle.unmount?.();
      return;
    }
    const latest = pending.state;
    pending = null;
    current = { id, controller, handle };
    if (latest !== context.state) handle.update?.(latest);
  }

  return {
    show,
    hide: async () => teardown(),
    get current() {
      return current?.id ?? null;
    },
  };
}
