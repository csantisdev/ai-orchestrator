// Store único del dashboard (spec §23.7): estado inmutable y suscripción.
// Sin acceso al DOM, para probarlo con `node --test`.

function shallowEqual(a, b) {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const key of keys) {
    if (a[key] !== b[key]) return false;
  }
  return true;
}

export function createStore(initial = {}) {
  let state = Object.freeze({ ...initial });
  const listeners = new Set();

  return {
    get() {
      return state;
    },
    // Aplica un cambio parcial; solo notifica si algo cambió.
    set(patch) {
      const next = Object.freeze({ ...state, ...patch });
      if (shallowEqual(state, next)) return false;
      const previous = state;
      state = next;
      for (const listener of [...listeners]) listener(state, previous);
      return true;
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
