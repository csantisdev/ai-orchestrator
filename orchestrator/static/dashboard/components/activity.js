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
  const key = (action) => `${item.id}|${action}`;
  return h("li", { class: ["act-event", `family-${FAMILY[filter]}`, selected && sel === selected && "is-selected"] },
    h("time", { class: "act-event-time", datetime: item.ts }, formatActivityTime(item.ts)),
    h("span", { class: "act-event-dot", "aria-hidden": "true" }),
    h("span", { class: "act-event-text" }, activityText(item)),
    h("span", { class: "act-event-actions" },
      sel ? h("button", { type: "button", class: "act-link", data: { actSel: sel, actKey: key("ver") },
        "aria-pressed": String(sel === selected) }, "Ver") : null,
      trace ? h("button", { type: "button", class: "act-link", data: { actTrace: JSON.stringify(trace), actKey: key("trace") } }, "Trace") : null,
      h("button", { type: "button", class: "act-link", data: { actFilter: filter, actKey: key("filter") },
        title: "Mostrar solo este tipo de evento" }, "Filtrar")));
}

// Identidad estable de un control para devolverle el foco después de redibujar.
function controlKey(element) {
  const data = element?.dataset;
  if (!data) return null;
  if (data.actKey) return `[data-act-key="${CSS_ESCAPE(data.actKey)}"]`;
  if (data.actKind !== undefined) return `[data-act-kind="${CSS_ESCAPE(data.actKind)}"]`;
  if (data.actMore) return "[data-act-more]";
  return null;
}

const CSS_ESCAPE = (value) => String(value).replace(/["\\]/g, "\\$&");

// Une la primera página recién pedida con lo ya cargado: lo nuevo arriba y, si el usuario ya
// pidió más páginas y la página nueva empalma con ellas, se conservan (y su cursor). Si ahora
// todo cabe en una página, o hay un hueco entre ambas, manda la página nueva.
export function mergeFirstPage(items, cursor, page, pages) {
  if (pages <= 1 || !page.next_cursor) return { items: page.items, cursor: page.next_cursor, reset: true };
  const fresh = new Set(page.items.map((item) => item.id));
  if (!items.some((item) => fresh.has(item.id))) return { items: page.items, cursor: page.next_cursor, reset: true };
  return { items: [...page.items, ...items.filter((item) => !fresh.has(item.id))], cursor, reset: false };
}

// Monta la Activity del proyecto. `refresh()` vuelve a pedir la primera página (lo llama el
// shell ante `db_changed` o al cambiar de proyecto); `select()` marca lo seleccionado. Las
// peticiones van en cola: un refresco nunca cancela un "Cargar más" ni pisa su resultado, y los
// refrescos que esperan en la cola se juntan en uno. Uno pedido mientras otro ya está en vuelo
// corre después: los datos pueden haber cambiado cuando el primero ya había salido.
export function mountActivity({ root, summary, api, store }) {
  let project = null;
  let items = [];
  let cursor = null;
  let pages = 0;
  let filter = "";
  let failed = false;
  let stale = false;
  let loaded = null;
  let queue = Promise.resolve();
  let refreshQueued = null;

  function enqueue(task) {
    queue = queue.then(task, task);
    return queue;
  }

  function writeSummary() {
    if (!summary) return;
    summary.textContent = stale ? "actividad no disponible" : activitySummary(items[0] ?? null) ?? "sin eventos";
  }

  function draw() {
    const doc = root.ownerDocument;
    const focused = doc?.activeElement && root.contains?.(doc.activeElement) ? controlKey(doc.activeElement) : null;
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
    if (focused) root.querySelector?.(focused)?.focus?.();
  }

  async function load(after) {
    const params = { limit: PAGE };
    if (after) params.cursor = after;
    return api.get(`/api/v1/projects/${project}/activity`, { params });
  }

  async function doRefresh() {
    project = store.get().project;
    if (!project || !PROJECT.test(project)) {
      root.replaceChildren(h("p", { class: "act-empty" }, "Elegí un proyecto para ver su actividad."));
      return;
    }
    // Lo cargado de otro proyecto no se mezcla con este.
    if (loaded !== project) {
      items = [];
      cursor = null;
      pages = 0;
      loaded = project;
    }
    try {
      const page = await load(null);
      const merged = mergeFirstPage(items, cursor, page, pages);
      items = merged.items;
      cursor = merged.cursor;
      pages = merged.reset ? 1 : pages;
      failed = false;
      stale = false;
    } catch (error) {
      console.warn("No se pudo cargar la actividad:", error);
      failed = !items.length;
      stale = true;
    }
    writeSummary();
    draw();
  }

  function refresh() {
    if (!refreshQueued) {
      refreshQueued = enqueue(async () => {
        refreshQueued = null;
        await doRefresh();
      });
    }
    return refreshQueued;
  }

  function more() {
    return enqueue(async () => {
      if (!cursor) return;
      try {
        const page = await load(cursor);
        const seen = new Set(items.map((item) => item.id));
        items = [...items, ...page.items.filter((item) => !seen.has(item.id))];
        cursor = page.next_cursor;
        pages += 1;
      } catch (error) {
        console.warn("No se pudo cargar más actividad:", error);
      }
      draw();
    });
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
