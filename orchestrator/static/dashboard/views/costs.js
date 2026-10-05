import { h } from "../core/dom.js";
import { toSearch } from "../core/router.js";
import { formatUsd } from "./runs.js";
import { dataTable, metricCard, metricGrid, panel, segmented } from "../core/ui.js";

const STYLE_KEY = "executions";
const PATH_SEGMENT = /^[A-Za-z0-9_~-][A-Za-z0-9._~-]*$/;
const PERIODS = ["7d", "30d", "90d"];
const PERIOD_LABELS = { "7d": "7 días", "30d": "30 días", "90d": "90 días" };
const AGENT_LABELS = {
  claude: "Claude", codex: "Codex", copilot: "Copilot", otros: "Otros", git: "Commits de git", "": "Sin agente", "sin agente": "Sin agente",
};

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

// Días con costo, para no listar 90 filas en cero; el resto se resume en una línea.
export function costDays(daily) {
  const series = meterSeries(daily);
  return { withCost: series.filter((item) => item.cost_usd > 0), empty: series.filter((item) => !(item.cost_usd > 0)).length };
}

function formatDay(iso) {
  const date = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("es-CL", { day: "2-digit", month: "short", timeZone: "UTC" }).format(date);
}

function render(root, state, period, data) {
  const totals = data.totals;
  const share = totals.cost_usd > 0 ? Math.round((totals.attributed_cost_usd / totals.cost_usd) * 100) : 0;
  const { withCost, empty } = costDays(data.daily);
  const contextHref = (id) => toSearch({ ...state, view: "trabajo", tab: "contextos", ctx: id, step: null, sel: null });
  root.replaceChildren(
    h("header", { class: "executions-header" },
      segmented({ label: "Período", options: PERIODS.map((key) => [key, PERIOD_LABELS[key]]), current: period, attribute: "period" })),
    metricGrid([
      metricCard({ family: "execution", label: `Costo · ${PERIOD_LABELS[period]}`, value: formatUsd(totals.cost_usd),
        sub: `${totals.runs} runs · ${totals.runs_with_cost} con costo` }),
      metricCard({ family: "work", label: "Atribuido a pasos", value: `${share} %`,
        sub: `${totals.attributed_runs} runs · ${formatUsd(totals.attributed_cost_usd)}`,
        title: "Costo de los runs vinculados a un paso de un contexto de este proyecto sobre el costo total del período." }),
      metricCard({ family: "neutral", label: "Sin atribuir", value: formatUsd(Math.max(totals.cost_usd - totals.attributed_cost_usd, 0)),
        sub: `${Math.max(totals.runs - totals.attributed_runs, 0)} runs sin paso` }),
    ]),
    panel("Costo diario (UTC)",
      withCost.length
        ? h("ul", { class: "cost-days" }, withCost.map((item) => h("li", {},
          h("span", { class: "cost-day" }, formatDay(item.date)),
          h("meter", { class: "progress", min: 0, max: item.max, value: item.cost_usd, "aria-label": `Costo del ${item.date}` }),
          h("span", { class: "cost-amount" }, formatUsd(item.cost_usd)))))
        : h("p", { class: "empty-note" }, "Sin costo en el período."),
      empty && withCost.length ? h("p", { class: "empty-note" }, `${empty} días sin costo.`) : null),
    h("div", { class: "executions-panels" },
      panel("Por contexto", dataTable({
        label: "Costo por contexto",
        columns: [{ label: "Contexto" }, { label: "Runs", numeric: true }, { label: "Costo", numeric: true }],
        empty: "Sin runs en el período.",
        rows: data.by_context.map((item) => ({ cells: [
          item.context_id
            ? h("a", { class: "cell-link", href: contextHref(item.context_id), data: { nav: "1", ctx: item.context_id } },
              h("span", { class: "cell-text" }, item.title))
            : item.title,
          String(item.runs),
          formatUsd(item.cost_usd),
        ] })),
      })),
      panel("Por agente", dataTable({
        label: "Costo por agente",
        columns: [{ label: "Agente" }, { label: "Runs", numeric: true }, { label: "Costo", numeric: true }],
        empty: "Sin runs en el período.",
        rows: data.by_agent.map((item) => ({ cells: [AGENT_LABELS[item.agent] ?? item.agent, String(item.runs), formatUsd(item.cost_usd)] })),
      }))),
  );
}

export async function mount(root, { api, state, signal, store }) {
  ensureStylesheet(root.ownerDocument);
  root.classList.add("executions-view");
  let current = state;
  let period = "30d";
  let pending = null;

  async function load({ quiet = false } = {}) {
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
    if (!quiet) root.replaceChildren(h("p", { role: "status" }, "Cargando…"));
    try {
      const data = await api.get(`/api/v1/projects/${current.project}/costs`, {
        params: { period }, signal: controller.signal,
      });
      if (!controller.signal.aborted && pending === controller) render(root, current, period, data);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (quiet) return console.warn("No se pudieron refrescar los costos:", error);
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
    // `refresh` (db_changed, §19.4 O5): recarga sin aviso de carga y sin pisar lo visible si falla;
    // si hay una carga en curso (de la persona), no la cancela: el próximo aviso la retoma.
    refresh: () => (pending ? undefined : load({ quiet: true })),
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
