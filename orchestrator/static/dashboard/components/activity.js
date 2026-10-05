// Activity del proyecto (spec §6.4 y §10.4): eventos recientes de la proyección
// `/api/v1/projects/{p}/activity` en la barra inferior, con acciones Ver, Trace y Filtrar.
// La barra heredada conserva sus operaciones locales (doctor, fix, sync, index) en
// `#activity-live`; esto dibuja la parte del proyecto en `#activity-feed`. Todo el texto
// variable va como textContent (core/dom.js).

import { h } from "../core/dom.js";
import { segmented } from "../core/ui.js";

const PAGE = 30;
const PROJECT = /^[A-Za-z0-9_~-][A-Za-z0-9._~-]*$/;

// Familias de la Activity (§4.3) y el filtro que agrupa sus tipos.
const KIND_FILTER = {
  run: "run", step_started: "step", step_completed: "step",
  alignment: "agent", tool_call: "agent", mcp: "agent", egress: "egress",
};
export const ACTIVITY_FILTERS = Object.freeze([
  ["", "Todo"], ["run", "Ejecuciones"], ["step", "Pasos"], ["agent", "Agentes"], ["egress", "Egress"],
]);
const FAMILY = { run: "execution", step: "work", agent: "governance", egress: "decision" };
const STATES = {
  completed: "completado", done: "completado", ok: "completado", success: "completado",
  failed: "falló", error: "falló", running: "en curso", in_progress: "en curso",
  pending: "pendiente", denied: "denegado", allowed: "permitido", allow: "permitido", deny: "denegado",
};

const number = (ref) => (typeof ref === "string" && ref.includes(":") ? ref.slice(ref.indexOf(":") + 1) : null);
const word = (value) => (value === null || value === undefined || value === "" ? null : String(value));
const stateText = (value) => (value ? STATES[value] ?? String(value).replace(/_/g, " ") : null);
const join = (...parts) => parts.filter(Boolean).join(" · ");

export function activityFilter(item) {
  return KIND_FILTER[item.kind] ?? "agent";
}

// Texto de una línea para cada tipo de evento, solo con campos estructurados.
export function activityText(item) {
  const a = item.attrs ?? {};
  const step = number(item.refs?.step);
  const context = number(item.refs?.context);
  const where = step ? `paso #${step}` : context ? `contexto #${context}` : null;
  switch (item.kind) {
    case "run":
      return join(`Run #${number(item.id)}`, word(a.provider), stateText(item.state));
    case "step_started":
      return join(`Paso #${step ?? number(item.id)} iniciado`, context && `contexto #${context}`);
    case "step_completed":
      return join(`Paso #${step ?? number(item.id)} completado`, context && `contexto #${context}`);
    case "alignment":
      return join(a.confirmed === false ? "Desvío registrado" : "Alineamiento confirmado", word(a.agent), where);
    case "tool_call":
      return join(`Tool call ${word(a.tool_name) ?? ""}`.trim(), stateText(item.state), where);
    case "egress":
      return join(`Egress ${stateText(a.decision) ?? ""}`.trim(), word(a.provider), word(a.reason_code));
    case "mcp":
      return join(`MCP ${word(a.tool_name) ?? ""}`.trim(), a.is_error ? "error" : stateText(item.state), word(a.reason_code));
    default:
      return join(String(item.kind ?? "Evento"), stateText(item.state));
  }
}

// Objeto que abre "Ver" en el Inspector (`sel`, §23.3) y destino de "Trace" (paso de un contexto).
export function activityActions(item) {
  const run = number(item.refs?.run);
  const step = number(item.refs?.step);
  const context = number(item.refs?.context);
  const own = number(item.id);
  let sel = null;
  if (item.kind === "mcp" && own) sel = `decision:mcp-${own}`;
  else if (item.kind === "egress" && own) sel = `decision:egress-${own}`;
  else if (item.kind === "run" && own) sel = `run:${own}`;
  else if (run) sel = `run:${run}`;
  else if (step) sel = `step:${step}`;
  else if (context) sel = `context:${context}`;
  const trace = step && context ? { view: "trabajo", tab: null, ctx: Number(context), step: Number(step), as: null } : null;
  return { sel, trace };
}

export function formatActivityTime(iso, { now = new Date(), timeZone } = {}) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const day = (value) => new Intl.DateTimeFormat("es-CL", { year: "numeric", month: "2-digit", day: "2-digit", timeZone }).format(value);
  const time = new Intl.DateTimeFormat("es-CL", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone }).format(date);
  if (day(date) === day(now)) return time;
  const short = new Intl.DateTimeFormat("es-CL", { day: "2-digit", month: "short", timeZone }).format(date);
  return `${short} ${time}`;
}

export function activitySummary(item, options) {
  return item ? `${activityText(item)} · ${formatActivityTime(item.ts, options)}` : null;
}

function row(item, selected) {
  const filter = activityFilter(item);
  const { sel, trace } = activityActions(item);
  return h("li", { class: ["act-event", `family-${FAMILY[filter]}`, selected && sel === selected && "is-selected"] },
    h("time", { class: "act-event-time", datetime: item.ts }, formatActivityTime(item.ts)),
    h("span", { class: "act-event-dot", "aria-hidden": "true" }),
    h("span", { class: "act-event-text" }, activityText(item)),
    h("span", { class: "act-event-actions" },
      sel ? h("button", { type: "button", class: "act-link", data: { actSel: sel }, "aria-pressed": String(sel === selected) }, "Ver") : null,
      trace ? h("button", { type: "button", class: "act-link", data: { actTrace: JSON.stringify(trace) } }, "Trace") : null,
      h("button", { type: "button", class: "act-link", data: { actFilter: filter }, title: "Mostrar solo este tipo de evento" }, "Filtrar")));
}

// Monta la Activity del proyecto. `refresh()` vuelve a pedir la primera página (lo llama el
// shell ante `db_changed` o al cambiar de proyecto); `select(sel)` marca lo seleccionado.
export function mountActivity({ root, summary, api, store }) {
  let project = null;
  let items = [];
  let cursor = null;
  let filter = "";
  let failed = false;
  let controller = null;
  let latest = null;

  function draw() {
    const selected = store.get().sel;
    const visible = filter ? items.filter((item) => activityFilter(item) === filter) : items;
    const list = visible.length
      ? h("ol", { class: "act-events", "aria-label": "Eventos recientes del proyecto" }, visible.map((item) => row(item, selected)))
      : h("p", { class: "act-empty" }, failed ? "No se pudo cargar la actividad del proyecto."
        : filter ? "No hay eventos de este tipo en lo cargado." : "Sin eventos registrados para este proyecto.");
    root.replaceChildren(
      h("div", { class: "act-feed-head" },
        h("span", { class: "act-feed-title" }, project ? `Proyecto ${project}` : "Proyecto"),
        segmented({ label: "Filtrar la actividad", options: ACTIVITY_FILTERS, current: filter, attribute: "actKind" })),
      list,
      cursor ? h("button", { type: "button", class: "act-more", data: { actMore: "1" } }, "Cargar más") : null,
    );
    if (summary && latest) summary.textContent = activitySummary(latest);
  }

  async function fetchPage(after) {
    controller?.abort();
    const mine = new AbortController();
    controller = mine;
    const params = { limit: PAGE };
    if (after) params.cursor = after;
    const data = await api.get(`/api/v1/projects/${project}/activity`, { params, signal: mine.signal });
    return controller === mine ? data : null;
  }

  async function refresh() {
    project = store.get().project;
    if (!project || !PROJECT.test(project)) {
      root.replaceChildren(h("p", { class: "act-empty" }, "Elegí un proyecto para ver su actividad."));
      return;
    }
    try {
      const data = await fetchPage(null);
      if (!data) return;
      items = data.items;
      cursor = data.next_cursor;
      failed = false;
      latest = items[0] ?? null;
    } catch (error) {
      if (error.name === "AbortError") return;
      console.warn("No se pudo cargar la actividad:", error);
      failed = true;
    }
    draw();
  }

  async function more() {
    if (!cursor) return;
    try {
      const data = await fetchPage(cursor);
      if (!data) return;
      const seen = new Set(items.map((item) => item.id));
      items = [...items, ...data.items.filter((item) => !seen.has(item.id))];
      cursor = data.next_cursor;
    } catch (error) {
      if (error.name !== "AbortError") console.warn("No se pudo cargar más actividad:", error);
    }
    draw();
  }

  root.addEventListener("click", (event) => {
    const target = event.target.closest?.("[data-act-sel], [data-act-trace], [data-act-filter], [data-act-kind], [data-act-more]");
    if (!target) return;
    const data = target.dataset;
    if (data.actSel) store.set({ sel: store.get().sel === data.actSel ? null : data.actSel });
    else if (data.actTrace) store.set({ ...JSON.parse(data.actTrace), sel: null });
    else if (data.actFilter !== undefined || data.actKind !== undefined) {
      const next = data.actFilter ?? data.actKind;
      filter = filter === next && data.actFilter !== undefined ? "" : next;
      draw();
    } else if (data.actMore) more();
  });

  return {
    refresh,
    select() {
      if (items.length) draw();
    },
  };
}
