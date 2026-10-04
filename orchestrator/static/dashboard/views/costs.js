import { h } from "../core/dom.js";
import { toSearch } from "../core/router.js";
import { formatUsd } from "./runs.js";

const STYLE_KEY = "executions";
const PATH_SEGMENT = /^[A-Za-z0-9_~-][A-Za-z0-9._~-]*$/;
const PERIODS = ["7d", "30d", "90d"];
const PERIOD_LABELS = { "7d": "7 días", "30d": "30 días", "90d": "90 días" };
const AGENT_LABELS = { claude: "Claude", git: "Commits de git", "": "Sin agente", "sin agente": "Sin agente" };

export function meterSeries(daily) {
  const max = Math.max(0, ...daily.map((item) => item.cost_usd));
  return daily.map((item) => ({ ...item, max: max || 1 }));
}

function ensureStylesheet(document) {
  if (document.head.querySelector(`link[data-view-css="${STYLE_KEY}"]`)) return;
  document.head.append(h("link", {
    rel: "stylesheet",
    href: new URL("./executions.css", import.meta.url).href,
    data: { viewCss: STYLE_KEY },
  }));
}

function message(title, body) {
  return h("section", { class: "shell-empty" }, h("h2", {}, title), h("p", {}, body));
}

function render(root, state, period, data) {
  const totals = data.totals;
  const buttons = PERIODS.map((key) => h("button", {
    type: "button",
    class: ["execution-filter", period === key && "is-active"],
    data: { period: key },
    "aria-pressed": String(period === key),
  }, PERIOD_LABELS[key]));
  root.replaceChildren(
    h("header", { class: "executions-header" },
      h("p", { class: "execution-muted" }, "Costos agregados de las ejecuciones del proyecto seleccionado."),
      h("div", { class: "execution-filters", role: "group", "aria-label": "Período" }, buttons),
      h("p", {}, `Costo: ${formatUsd(totals.cost_usd)} · ${totals.runs} runs. `
        + `Cobertura de atribución: ${totals.attributed_runs} runs y `
        + `${formatUsd(totals.attributed_cost_usd)} vinculados a pasos del proyecto.`),
    ),
    h("section", { class: "execution-series", "aria-label": "Costo diario" },
      meterSeries(data.daily).map((item) => h("label", {}, item.date,
        h("meter", { min: 0, max: item.max, value: item.cost_usd }, formatUsd(item.cost_usd))))),
    h("h3", {}, "Por contexto"),
    h("div", { class: "execution-table-scroll" }, h("table", { class: "execution-table" },
      h("thead", {}, h("tr", {}, ["Contexto", "Runs", "Costo"].map((label) => h("th", {}, label)))),
      h("tbody", {}, data.by_context.map((item) => h("tr", {},
      h("td", {}, item.context_id
        ? h("a", { class: "execution-link",
          href: toSearch({ ...state, view: "trabajo", tab: "contextos", ctx: item.context_id, step: null, sel: null }),
          data: { nav: "1", ctx: item.context_id },
        }, item.title)
        : item.title),
      h("td", { class: "execution-data" }, item.runs),
      h("td", { class: "execution-data" }, formatUsd(item.cost_usd)),
    ))))),
    h("h3", {}, "Por agente"),
    h("div", { class: "execution-table-scroll" }, h("table", { class: "execution-table" },
      h("thead", {}, h("tr", {}, ["Agente", "Runs", "Costo"].map((label) => h("th", {}, label)))),
      h("tbody", {}, data.by_agent.map((item) => h("tr", {},
      h("td", {}, AGENT_LABELS[item.agent] ?? item.agent), h("td", { class: "execution-data" }, item.runs), h("td", { class: "execution-data" }, formatUsd(item.cost_usd)),
    ))))),
  );
}

export async function mount(root, { api, state, signal, store }) {
  ensureStylesheet(root.ownerDocument);
  root.classList.add("executions-view");
  let current = state;
  let period = "30d";
  let pending = null;

  async function load() {
    pending?.abort();
    pending = null;
    if (!current.project) {
      root.replaceChildren(message("Elegí un proyecto", "Costos muestra los agregados del proyecto seleccionado."));
      return;
    }
    if (!PATH_SEGMENT.test(current.project)) {
      root.replaceChildren(message(
        "Este proyecto no se puede consultar desde la vista nueva",
        "Su alias tiene caracteres que la API no acepta en la ruta.",
      ));
      return;
    }
    const controller = new AbortController();
    const abort = () => controller.abort();
    pending = controller;
    signal.addEventListener("abort", abort, { once: true });
    root.replaceChildren(h("p", { role: "status" }, "Cargando…"));
    try {
      const data = await api.get(`/api/v1/projects/${current.project}/costs`, {
        params: { period }, signal: controller.signal,
      });
      if (!controller.signal.aborted && pending === controller) render(root, current, period, data);
    } catch (error) {
      if (controller.signal.aborted) return;
      const suffix = error?.reason === "session_expired" ? " El servidor se reinició: recargá la página." : "";
      root.replaceChildren(message("No se pudieron cargar los costos", `${error?.message ?? error}.${suffix}`));
    } finally {
      signal.removeEventListener("abort", abort);
      if (pending === controller) pending = null;
    }
  }

  function onClick(event) {
    const target = event.target.closest?.("[data-period], [data-nav]");
    if (!target || !root.contains(target)) return;
    if (target.dataset.period !== undefined) {
      period = target.dataset.period;
      void load();
      return;
    }
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1) return;
    event.preventDefault();
    store.set({ view: "trabajo", tab: "contextos", ctx: Number(target.dataset.ctx), step: null, sel: null });
  }

  root.addEventListener("click", onClick);
  await load();
  return {
    update(next) {
      const changedProject = next.project !== current.project;
      current = next;
      if (changedProject) void load();
    },
    unmount() {
      root.removeEventListener("click", onClick);
      pending?.abort();
    },
  };
}
