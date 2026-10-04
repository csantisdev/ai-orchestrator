import { h } from "../core/dom.js";
import { ApiError } from "../core/api.js";

const SAFE_ALIAS = /^[A-Za-z0-9._~-]+$/;
const AGENT_LABELS = { claude: "Claude", codex: "Codex", copilot: "Copilot", otros: "Otros", "sin agente": "Sin agente" };
export const formatNumber = (value) => new Intl.NumberFormat("es-CL").format(value ?? 0);
export const formatUsd = (value) => new Intl.NumberFormat("es-CL", { style: "currency", currency: "USD" }).format(value ?? 0);
export const periodText = (period) => period === "30d" ? "Últimos 30 días" : "Últimos 7 días";
export const aliasNeedsEncoding = (alias) => !SAFE_ALIAS.test(alias ?? "");
export const detailLabel = (label) => AGENT_LABELS[label] ?? label;

export function viewHref(project, link) {
  const query = new URLSearchParams({ project, view: link.view });
  if (link.tab) query.set("tab", link.tab);
  for (const [key, value] of Object.entries(link.params ?? {})) query.set(key, String(value));
  return `?${query}`;
}

function stylesheet(root) {
  const head = root.ownerDocument.head;
  if (!head.querySelector('link[data-view-css="home"]')) {
    head.append(h("link", { rel: "stylesheet", href: new URL("./home.css", import.meta.url).href, data: { viewCss: "home" } }));
  }
}

function warningList(title, warnings) {
  return h("section", { class: "home-panel" }, h("h2", {}, title), warnings.length
    ? h("ul", { class: "home-warnings" }, warnings.map((warning) => h("li", {}, h("strong", {}, warning.message), h("span", {}, warning.hint))))
    : h("p", { class: "home-muted" }, "Sin advertencias."));
}

function metricCard(project, metric) {
  return h("a", { class: "home-metric", href: viewHref(project, metric.link), data: { view: metric.link.view, tab: metric.link.tab } },
    h("span", { class: "home-metric-label" }, metric.label),
    h("strong", { class: "home-metric-value" }, metric.unit === "usd" ? formatUsd(metric.value) : formatNumber(metric.value)),
    h("span", { class: "home-source" }, metric.source), metric.detail.length
      ? h("ul", { class: "home-detail" }, metric.detail.map((detail) => h("li", {}, `${detailLabel(detail.label)}: ${formatNumber(detail.value)}`))) : null);
}

function renderOverview(root, data, project, period) {
  const stale = data.tracking_health.warnings.filter((warning) => warning.code === "stale_in_progress_step");
  const alerts = data.alerts.filter((warning) => warning.code !== "stale_in_progress_step");
  const quality = data.tracking_health.data_quality;
  root.replaceChildren(h("section", { class: "home" },
    h("header", { class: "home-header" }, h("p", { class: "home-muted" }, `${project} · ${periodText(period)}`),
      h("div", { class: "home-period", role: "group", "aria-label": "Período" }, ["7d", "30d"].map((key) => h("button", { type: "button", class: key === period ? "home-period-selected" : "", data: { period: key }, "aria-pressed": String(key === period) }, key === "7d" ? "7 d" : "30 d")))),
    h("div", { class: "home-grid" }, data.metrics.map((metric) => metricCard(project, metric))), warningList("Salud del tracking", stale),
    h("section", { class: "home-panel" }, h("h2", {}, "Calidad de datos"), h("p", {}, `Completados sin inicio: ${formatNumber(quality.completed_without_start)} · Pasos omitidos: ${formatNumber(quality.skipped)}`)),
    warningList("Alertas", alerts), h("section", { class: "home-panel" }, h("h2", {}, "Egress"), h("p", {}, data.egress.message), data.egress.count === undefined ? null : h("p", { class: "home-muted" }, `Decisiones: ${formatNumber(data.egress.count)}`))));
}

async function projects(root, api, signal) {
  root.replaceChildren(h("p", { class: "home-muted" }, "Cargando proyectos…"));
  const data = await api.get("/api/v1/meta/projects", { signal });
  if (signal.aborted) return;
  root.replaceChildren(h("section", { class: "home" }, h("p", { class: "home-muted" }, "Elegí un proyecto"), data.projects.length
    ? h("ul", { class: "home-projects" }, data.projects.map((item) => h("li", {}, h("a", { href: viewHref(item.alias, { view: "inicio", params: {} }), data: { view: "inicio" } }, item.alias))))
    : h("p", { class: "home-muted" }, "Todavía no hay proyectos registrados ni runs.")));
}

function errorMessage(error) {
  return error instanceof ApiError && error.reason === "session_expired" ? "La sesión expiró; recargá la página." : error.message;
}

export async function mount(root, { api, state, signal }) {
  stylesheet(root);
  let controller;
  let currentProject = state.project;
  let period = "7d";
  const load = async () => {
    controller?.abort();
    controller = new AbortController();
    const current = controller;
    const abort = () => current.abort();
    signal?.addEventListener("abort", abort, { once: true });
    try {
      if (!currentProject) return await projects(root, api, current.signal);
      if (aliasNeedsEncoding(currentProject)) {
        root.replaceChildren(h("p", { class: "home-error" }, "Este alias requiere codificación y no puede consultarse desde esta versión del dashboard."));
        return;
      }
      root.replaceChildren(h("p", { class: "home-muted" }, "Cargando inicio…"));
      const data = await api.get(`/api/v1/projects/${currentProject}/overview`, { params: { period }, signal: current.signal });
      if (!current.signal.aborted && current === controller) renderOverview(root, data, currentProject, period);
    } catch (error) {
      if (!current.signal.aborted && error.name !== "AbortError" && current === controller) root.replaceChildren(h("p", { class: "home-error" }, errorMessage(error)));
    } finally {
      signal?.removeEventListener("abort", abort);
    }
  };
  const click = (event) => {
    const button = event.target.closest?.("[data-period]");
    if (!button) return;
    period = button.dataset.period;
    void load();
  };
  root.addEventListener("click", click);
  await load();
  return { update(next) { if (next.project !== currentProject) { currentProject = next.project; void load(); } }, unmount() { root.removeEventListener("click", click); controller?.abort(); } };
}
