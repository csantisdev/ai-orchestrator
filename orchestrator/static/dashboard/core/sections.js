// Secciones del shell (spec §23.3): cuatro de trabajo y tres de control.
// Mientras cada vista se migra (olas 3 a 6), las secciones muestran la pestaña heredada que
// mejor las cubre; las que todavía no tienen contenido muestran un estado vacío.
// Puro: sin DOM, para probarlo con `node --test`.

export const SECTIONS = Object.freeze([
  {
    id: "inicio", group: "proyecto", label: "Inicio", legacy: "metrics",
    note: "Vista provisoria con las métricas actuales; el resumen de Inicio llega en la ola 3.",
  },
  { id: "trabajo", group: "proyecto", label: "Trabajo", legacy: "flujos" },
  { id: "ejecuciones", group: "proyecto", label: "Ejecuciones", legacy: "actividad" },
  {
    id: "gobernanza", group: "proyecto", label: "Gobernanza",
    empty: {
      title: "Gobernanza todavía no tiene vista",
      body: "Las denegaciones de acceso MCP y las decisiones de egress se mostrarán acá en la ola 3. Mientras tanto, el comando ai-orchestrator doctor resume la configuración.",
    },
  },
  { id: "proveedores", group: "control", label: "Proveedores", legacy: "config" },
  {
    id: "politicas", group: "control", label: "Políticas",
    empty: {
      title: "Las políticas todavía se editan por archivo",
      body: "La política de egress de cada proyecto vive en su configuración. Esta vista llega después de Gobernanza.",
    },
  },
  {
    id: "ajustes", group: "control", label: "Ajustes",
    tabs: [
      { id: "proyectos", label: "Proyectos", legacy: "proyectos" },
      { id: "datos", label: "Datos", legacy: "datos" },
    ],
  },
]);

export const GROUPS = Object.freeze([
  { id: "proyecto", label: "Proyecto" },
  { id: "control", label: "Control" },
]);

// Qué mostrar para un estado del router: sección, pestaña, vista heredada o estado vacío,
// y el breadcrumb (§23.3). Una sección o pestaña desconocida cae en la primera válida.
export function resolveSection(state) {
  const section = SECTIONS.find((s) => s.id === state.view) ?? SECTIONS[0];
  const tab = section.tabs ? (section.tabs.find((t) => t.id === state.tab) ?? section.tabs[0]) : null;
  const crumbs = [state.project ?? "Todos los proyectos", section.label];
  if (tab) crumbs.push(tab.label);
  return {
    section,
    tab,
    legacy: tab ? tab.legacy : (section.legacy ?? null),
    empty: section.empty ?? null,
    note: section.note ?? null,
    crumbs,
  };
}

// Etiqueta legible de una selección `tipo:id` para el Inspector.
const KINDS = { context: "Contexto", step: "Paso", run: "Run", commit: "Commit", decision: "Decisión" };

export function describeSelection(sel) {
  if (!sel) return null;
  const [kind, id] = [sel.slice(0, sel.indexOf(":")), sel.slice(sel.indexOf(":") + 1)];
  const label = KINDS[kind] ?? kind;
  if (kind === "commit") return { label, id: id.slice(0, 7), full: id };
  if (kind === "decision") return { label, id: id.replace("-", " #"), full: id };
  return { label, id: `#${id}`, full: id };
}
