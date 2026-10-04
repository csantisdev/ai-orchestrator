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
// recibe los cambios de estado del router mientras la sección sigue visible; los que llegan
// durante el montaje se combinan y se entrega solo el más reciente.
//
// `show` nunca rechaza: un fallo de la vista vigente (carga, `mount` o `update`) la desmonta
// y llama a `onError(error, root)` para que el shell dibuje el aviso. Los fallos de montajes
// ya reemplazados y los de `unmount` solo se registran, para no pisar la vista actual.

const MODULE_PATH = /^\.\/views\/[a-z][a-z0-9-]*\.js$/;

function quietly(fn) {
  try {
    fn();
  } catch (error) {
    console.error("Falló el desmontaje de una vista:", error);
  }
}

export function createViewHost({ root, load, onError = (error) => console.error(error) }) {
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
    if (previous) {
      previous.controller.abort();
      quietly(() => previous.handle.unmount?.());
    }
    root.replaceChildren();
  }

  function fail(error) {
    teardown();
    onError(error, root);
  }

  async function show(id, modulePath, context) {
    if (!MODULE_PATH.test(modulePath)) {
      fail(new TypeError(`módulo de vista inválido: ${modulePath}`));
      return;
    }
    if (current && current.id === id) {
      try {
        current.handle.update?.(context.state);
      } catch (error) {
        fail(error);
      }
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
      if (stale()) console.error("Falló una vista ya reemplazada:", error);
      else fail(error);
      return;
    }
    if (stale()) {
      controller.abort();
      quietly(() => handle.unmount?.());
      return;
    }
    const latest = pending.state;
    pending = null;
    current = { id, controller, handle };
    if (latest === context.state) return;
    try {
      handle.update?.(latest);
    } catch (error) {
      fail(error);
    }
  }

  return {
    show,
    hide: teardown,
    get current() {
      return current?.id ?? null;
    },
  };
}
