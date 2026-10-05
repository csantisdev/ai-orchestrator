// Refresco por cambios entre procesos (spec §19.4 O5): el servidor publica `db_changed` por SSE
// cuando la base cambia (lo que hacen los agentes vía MCP desde otro proceso). El aviso no dice
// qué cambió, así que se refresca solo lo visible, con debounce para agrupar ráfagas. Con la
// pestaña oculta no se pide nada: el refresco queda pendiente hasta que vuelva a verse.

export function watchChanges({ events, onChange, doc, delay = 800, timers = globalThis }) {
  if (!events) return { stop() {} };
  let timer = null;
  let pending = false;

  function fire() {
    timer = null;
    if (doc?.hidden) {
      pending = true;
      return;
    }
    pending = false;
    onChange();
  }

  function schedule() {
    if (timer !== null) timers.clearTimeout(timer);
    timer = timers.setTimeout(fire, delay);
  }

  function visible() {
    if (pending && !doc.hidden) schedule();
  }

  events.addEventListener("db_changed", schedule);
  doc?.addEventListener("visibilitychange", visible);
  return {
    stop() {
      if (timer !== null) timers.clearTimeout(timer);
      events.removeEventListener("db_changed", schedule);
      doc?.removeEventListener("visibilitychange", visible);
    },
  };
}
