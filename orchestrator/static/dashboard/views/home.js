import { h } from "../core/dom.js";
import { ApiError } from "../core/api.js";

const SAFE_ALIAS = /^[A-Za-z0-9._~-]+$/;
export const formatNumber = (value) => new Intl.NumberFormat("es-CL").format(value ?? 0);
export const formatUsd = (value) => new Intl.NumberFormat("es-CL", { style: "currency", currency: "USD" }).format(value ?? 0);
export const periodText = (period) => period === "30d" ? "Últimos 30 días" : "Últimos 7 días";
export function viewHref(project, link) {
  const query = new URLSearchParams({ project, view: link.view });
  if (link.tab) query.set("tab", link.tab);
  for (const [key, value] of Object.entries(link.params ?? {})) query.set(key, String(value));
  return `?${query}`;
}
export const aliasNeedsEncoding = (alias) => !SAFE_ALIAS.test(alias ?? "");

function stylesheet() {
  if (!document.head.querySelector('link[data-view-style="home"]')) document.head.append(h("link", { rel: "stylesheet", href: new URL("./home.css", import.meta.url).href, data: { viewStyle: "home" } }));
}
function warningList(title, warnings) {
  return h("section", { class: "home-panel" }, h("h2", {}, title), warnings.length ? h("ul", { class: "home-warnings" }, warnings.map((warning) => h("li", {}, h("strong", {}, warning.message), h("span", {}, warning.hint)))) : h("p", { class: "home-muted" }, "Sin advertencias."));
}
function renderOverview(root, data, project, period) {
  const cards = data.metrics.map((metric) => h("a", { class: "home-metric", href: viewHref(project, metric.link), data: { view: metric.link.view, tab: metric.link.tab } }, h("span", { class: "home-metric-label" }, metric.label), h("strong", { class: "home-metric-value" }, metric.unit === "usd" ? formatUsd(metric.value) : formatNumber(metric.value)), h("span", { class: "home-source" }, metric.source), metric.detail.length ? h("ul", { class: "home-detail" }, metric.detail.map((detail) => h("li", {}, `${detail.label}: ${formatNumber(detail.value)}`))) : null));
  root.replaceChildren(h("section", { class: "home" }, h("header", { class: "home-header" }, h("div", {}, h("h1", {}, "Inicio"), h("p", { class: "home-muted" }, `${project} · ${periodText(period)}`)), h("div", { class: "home-period", role: "group", "aria-label": "Período" }, ["7d", "30d"].map((key) => h("button", { type: "button", class: key === period ? "home-period-selected" : "", data: { period: key }, "aria-pressed": String(key === period) }, key === "7d" ? "7 d" : "30 d")))), h("div", { class: "home-grid" }, cards), warningList("Salud del tracking", data.tracking_health.warnings), h("section", { class: "home-panel" }, h("h2", {}, "Calidad de datos"), h("p", {}, `Completados sin inicio: ${formatNumber(data.tracking_health.data_quality.completed_without_start)} · Pasos skipped: ${formatNumber(data.tracking_health.data_quality.skipped)}`)), warningList("Alertas", data.alerts), h("section", { class: "home-panel" }, h("h2", {}, "Egress"), h("p", {}, data.egress.message), data.egress.count === undefined ? null : h("p", { class: "home-muted" }, `Decisiones: ${formatNumber(data.egress.count)}`))));
}
async function projects(root, api, signal) {
  root.replaceChildren(h("p", { class: "home-muted" }, "Cargando proyectos…"));
  const data = await api.get("/api/v1/meta/projects", { signal });
  root.replaceChildren(h("section", { class: "home" }, h("h1", {}, "Elegí un proyecto"), data.projects.length ? h("ul", { class: "home-projects" }, data.projects.map((item) => h("li", {}, h("a", { href: viewHref(item.alias, { view: "inicio", params: {} }), data: { view: "inicio" } }, item.alias)))) : h("p", { class: "home-muted" }, "Todavía no hay proyectos registrados ni runs.")));
}
export async function mount(root, { api, state, signal }) {
  stylesheet(); let controller; let currentProject = state.project; let period = "7d";
  const load = async () => {
    controller?.abort(); controller = new AbortController(); signal?.addEventListener("abort", () => controller.abort(), { once: true });
    if (!currentProject) return projects(root, api, controller.signal);
    if (aliasNeedsEncoding(currentProject)) { root.replaceChildren(h("p", { class: "home-error" }, "Este alias requiere codificación y no puede consultarse desde esta versión del dashboard.")); return; }
    root.replaceChildren(h("p", { class: "home-muted" }, "Cargando inicio…"));
    try { renderOverview(root, await api.get(`/api/v1/projects/${currentProject}/overview`, { params: { period }, signal: controller.signal }), currentProject, period); }
    catch (error) { if (error.name === "AbortError") return; const message = error instanceof ApiError && error.reason === "session_expired" ? "La sesión expiró; recargá la página." : error.message; root.replaceChildren(h("p", { class: "home-error" }, message)); }
  };
  const click = (event) => { const button = event.target.closest?.("[data-period]"); if (!button) return; period = button.dataset.period; load(); };
  root.addEventListener("click", click); await load();
  return { update(next) { if (next.project !== currentProject) { currentProject = next.project; load(); } }, unmount() { root.removeEventListener("click", click); controller?.abort(); } };
}
