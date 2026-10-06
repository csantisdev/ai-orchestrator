// Refresco por cambios entre procesos (spec §19.4 O5): el servidor publica `db_changed` por SSE
// cuando cambia algo relevante en la base (lo que hacen los agentes vía MCP desde otro proceso).
// El aviso no dice qué cambió, así que se refresca solo lo visible:
//
// - el primer aviso espera `delay` para agrupar la ráfaga;
// - nunca hay dos refrescos a la vez, y entre el inicio de uno y el siguiente pasan al menos
//   `minInterval` ms: los avisos que llegan mientras tanto se juntan en un solo refresco final;
// - con la pestaña oculta no se pide nada: queda pendiente hasta que vuelva a verse.

export function watchChanges({
  events, onChange, doc, delay = 500, minInterval = 2500, timers = globalThis, clock = () => Date.now(),
}) {
  if (!events) return { stop() {} };
  let timer = null;
  let pending = false;
  let running = false;
  let last = -Infinity;
  let stopped = false;

  function schedule() {
    pending = true;
    if (stopped || timer !== null || running) return;
    timer = timers.setTimeout(fire, Math.max(delay, last + minInterval - clock()));
  }

  async function fire() {
    timer = null;
    if (doc?.hidden) return;
    pending = false;
    running = true;
    last = clock();
    try {
      await onChange();
    } catch (error) {
      console.error("Falló el refresco por cambios:", error);
    } finally {
      running = false;
      if (pending) schedule();
    }
  }

  function visible() {
    if (pending && !doc.hidden) schedule();
  }

  events.addEventListener("db_changed", schedule);
  doc?.addEventListener("visibilitychange", visible);
  return {
    stop() {
      stopped = true;
      if (timer !== null) timers.clearTimeout(timer);
      events.removeEventListener("db_changed", schedule);
      doc?.removeEventListener("visibilitychange", visible);
    },
  };
}
