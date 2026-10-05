// Encabezado de página que fija la vista montada (`page.set`, contrato en ../README.md).
// Cada entrada a una vista, y cada vez que la vista falla y se desmonta, abre una época nueva:
// un `page.set` de un montaje anterior (una carga que terminó tarde, aunque sea de la misma
// vista) se ignora. Puro, para `node --test`.

export function createPageTitles(onChange = () => {}) {
  let key = null;
  let epoch = 0;
  let value = null;
  return {
    // Vista visible (clave de core/mount.js) o null si la sección no tiene módulo.
    enter(nextKey) {
      if (nextKey === key) return;
      key = nextKey;
      epoch += 1;
      value = null;
    },
    // La vista vigente falló y el host la desmontó (core/mount.js): el próximo montaje de la
    // misma clave es otra instancia y el anterior ya no puede tocar el título.
    restart() {
      epoch += 1;
      value = null;
    },
    pageFor(forKey) {
      const mine = epoch;
      return {
        set({ title = null, subtitle = null } = {}) {
          if (forKey !== key || mine !== epoch) return;
          value = { title: title || null, subtitle: subtitle ?? null };
          onChange();
        },
      };
    },
    get current() {
      return value;
    },
  };
}

// Contadores de la navegación para un proyecto: el 0 se muestra; sin dato, vacío.
export function navCounts(projects, project) {
  const own = projects.find((item) => item.alias === project);
  if (!own) return { trabajo: null, ejecuciones: null };
  return { trabajo: own.active_contexts ?? null, ejecuciones: own.runs ?? null };
}

// Texto de la píldora del header, o null si no hay nada que avisar.
export function deniedText(summary) {
  const problems = (summary?.mcp?.denied ?? 0) + (summary?.mcp?.error ?? 0);
  if (!problems) return null;
  return `${problems} ${problems === 1 ? "denegada o con error" : "denegadas o con error"} · 7 d`;
}
