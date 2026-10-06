import { h } from "../core/dom.js";
import { metricCard, metricGrid, noticeList, panel, segmented, stateNotice } from "../core/ui.js";
import { ApiError } from "../core/api.js";
import { layoutConstellation, renderConstellation } from "../renderers/constellation.js";

const SAFE_ALIAS = /^[A-Za-z0-9._~-]+$/;
const AGENT_LABELS = {
  claude: "Claude",
  codex: "Codex",
  copilot: "Copilot",
  otros: "Otros",
  "sin agente": "Sin agente",
};
export const formatNumber = (value) => new Intl.NumberFormat("es-CL").format(value ?? 0);
export const formatUsd = (value) => new Intl.NumberFormat(
  "es-CL",
  { style: "currency", currency: "USD" },
).format(value ?? 0);
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
    head.append(h("link", {
      rel: "stylesheet",
      href: new URL("./home.css", import.meta.url).href,
      data: { viewCss: "home" },
    }));
  }
}

// Familia (§4.3) y tono de cada métrica en su tarjeta (maqueta v5).
const METRIC_STYLE = {
  active_contexts: { family: "knowledge" },
  steps_in_progress: { family: "work" },
  stale_steps: { family: "decision", warnWhenPositive: true },
  agent_activity_24h: { family: "execution" },
  mcp_denied_or_error: { family: "governance", tone: "gov" },
  cost_period: { family: "execution" },
};

// Dato corto bajo el valor: el detalle de la métrica, o nada si no tiene.
export function metricSub(metric) {
  if (metric.id === "cost_period") {
    const runs = metric.detail.find((item) => item.label === "runs")?.value ?? 0;
    const attributed = metric.detail.find((item) => item.label !== "runs")?.value ?? 0;
    return `${formatNumber(runs)} runs · ${formatNumber(attributed)} atribuidos a pasos`;
  }
  if (!metric.detail.length) return null;
  return metric.detail.map((item) => `${detailLabel(item.label)} ${formatNumber(item.value)}`).join(" · ");
}

function metricTile(project, metric) {
  const style = METRIC_STYLE[metric.id] ?? { family: "neutral" };
  const tone = style.warnWhenPositive && metric.value > 0 ? "warn" : (style.tone ?? null);
  return metricCard({
    family: style.family,
    label: metric.label,
    value: metric.unit === "usd" ? formatUsd(metric.value) : formatNumber(metric.value),
    sub: metricSub(metric),
    title: metric.source,
    href: viewHref(project, metric.link),
    data: { view: metric.link.view, tab: metric.link.tab },
    tone: metric.value > 0 ? tone : null,
  });
}

function sources(metrics) {
  return h("details", { class: "home-sources" },
    h("summary", {}, "¿De dónde salen estos números?"),
    h("dl", {}, metrics.map((metric) => [h("dt", {}, metric.label), h("dd", {}, metric.source)])));
}

// Vista previa de la constelación (§22.4): solo activos y lo conectado a ellos, sin foco.
export function constellationPreview(project, constellation) {
  if (!constellation) return null;
  const layout = layoutConstellation(constellation, { scope: "active" });
  const href = `?project=${encodeURIComponent(project)}&view=trabajo&tab=contextos&as=constellation`;
  return panel("Constelación · Labs",
    layout.suns.length
      ? h("a", { class: "constellation-wrap is-preview-link", href, "aria-label": "Abrir el grafo de contextos" },
        renderConstellation(layout, { interactive: false }))
      : h("p", { class: "home-muted" }, "Sin contextos activos ni conectados para dibujar."),
    h("p", { class: "home-muted" }, `${layout.suns.length} contextos visibles · ${layout.bridges.length} puentes · `,
      h("a", { class: "cons-open", href }, "Abrir el grafo →")));
}

function renderOverview(root, data, project, period, constellation = null) {
  const cards = data.metrics.filter((metric) => metric.id !== "tracking_health");
  const health = data.metrics.find((metric) => metric.id === "tracking_health");
  const stale = data.tracking_health.warnings.filter((warning) => warning.code === "stale_in_progress_step");
  const alerts = data.alerts.filter((warning) => warning.code !== "stale_in_progress_step");
  const quality = data.tracking_health.data_quality;
  const notices = [
    ...stale.map((warning) => ({ family: "decision", icon: "!", title: warning.message, hint: warning.hint })),
    ...alerts.map((warning) => ({ family: "decision", icon: "·", title: warning.message, hint: warning.hint })),
  ];
  root.replaceChildren(h("section", { class: "home" },
    h("header", { class: "home-header" },
      h("p", { class: "home-muted" }, `${project} · ${periodText(period)}`),
      segmented({ label: "Período", options: [["7d", "7 días"], ["30d", "30 días"]], current: period, attribute: "period" })),
    metricGrid(cards.map((metric) => metricTile(project, metric))),
    constellationPreview(project, constellation),
    h("div", { class: "home-panels" },
      panel(`Salud del tracking · ${formatNumber(health?.value ?? notices.length)}`,
        noticeList(notices, "Sin advertencias: el tracking está al día.")),
      h("div", { class: "home-side" },
        panel("Calidad de datos",
          h("p", { class: "home-muted" },
            `Completados sin inicio: ${formatNumber(quality.completed_without_start)} · `
            + `Pasos omitidos: ${formatNumber(quality.skipped)}`)),
        panel("Egress",
          h("p", { class: "home-muted" }, data.egress.message),
          data.egress.count === undefined ? null
            : h("p", { class: "home-muted" }, `Decisiones: ${formatNumber(data.egress.count)}`)))),
    sources(data.metrics),
  ));
}

// Registrados (los del índice) y alias detectados en runs o contextos sin registrar: estos
// suelen venir de sesiones importadas desde carpetas sueltas o worktrees.
export function projectGroups(projects) {
  return {
    registered: projects.filter((item) => item.registered),
    detected: projects.filter((item) => !item.registered),
  };
}

function plural(count, singular, pluralText) {
  return `${formatNumber(count)} ${count === 1 ? singular : pluralText}`;
}

export function projectFacts(item) {
  const parts = [];
  if (item.active_contexts) parts.push(plural(item.active_contexts, "contexto activo", "contextos activos"));
  if (item.contexts) parts.push(plural(item.contexts, "contexto", "contextos"));
  if (item.runs) parts.push(plural(item.runs, "run", "runs"));
  return parts.length ? parts.join(" · ") : "Sin actividad registrada";
}

export function activityText(iso, { timeZone } = {}) {
  if (!iso) return "Sin actividad";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Sin actividad";
  const day = new Intl.DateTimeFormat("es-CL", { day: "2-digit", month: "short", year: "numeric", timeZone })
    .format(date);
  return `Última actividad: ${day}`;
}

// Enlace de proyecto: cambiar de proyecto recarga la página con `?project=` (el header y el
// dashboard heredado dependen de eso), así que no lleva `data-view` para que el shell no lo
// intercepte.
function projectLink(item, className) {
  return h("a", { class: className, href: viewHref(item.alias, { view: "inicio", params: {} }) },
    h("span", { class: "home-project-alias" }, item.alias),
    h("span", { class: "home-project-facts" }, projectFacts(item)),
    h("span", { class: "home-project-activity" }, activityText(item.last_activity)));
}

async function projects(root, api, signal) {
  root.replaceChildren(h("p", { class: "home-muted" }, "Cargando proyectos…"));
  const data = await api.get("/api/v1/meta/projects", { signal });
  if (signal.aborted) return;
  const { registered, detected } = projectGroups(data.projects);
  const cards = registered.length
    ? h("div", { class: "home-project-grid" }, registered.map((item) => projectLink(item, "home-project")))
    : h("p", { class: "home-muted" }, "No hay proyectos registrados. Registrá uno con ai-orchestrator add.");
  const others = detected.length
    ? h("details", { class: "home-detected" },
      h("summary", {}, `Otros alias detectados (${formatNumber(detected.length)})`),
      h("p", { class: "home-muted" },
        "Aparecen en runs o contextos pero no están registrados en el índice; suelen venir de sesiones "
        + "importadas desde carpetas sueltas o worktrees."),
      h("div", { class: "home-detected-list" }, detected.map((item) => projectLink(item, "home-project is-detected"))))
    : null;
  // `replaceChildren` escribe `null` como texto: solo nodos.
  root.replaceChildren(h("section", { class: "home" }, ...[
    h("header", { class: "home-header" }, h("p", { class: "home-muted" }, "Elegí un proyecto para ver su resumen.")),
    cards,
    others,
  ].filter(Boolean)));
}

function errorMessage(error) {
  return error instanceof ApiError && error.reason === "session_expired"
    ? "La sesión expiró; recargá la página."
    : error.message;
}

export async function mount(root, { api, state, signal }) {
  stylesheet(root);
  let controller;
  let currentProject = state.project;
  let period = "7d";
  let loading = false;
  const load = async ({ quiet = false } = {}) => {
    controller?.abort();
    controller = new AbortController();
    const current = controller;
    loading = true;
    const abort = () => current.abort();
    signal?.addEventListener("abort", abort, { once: true });
    try {
      if (!currentProject) return await projects(root, api, current.signal);
      if (aliasNeedsEncoding(currentProject)) {
        root.replaceChildren(stateNotice("empty", "Este proyecto no se puede consultar desde la vista nueva",
          "Su alias requiere codificación y la API no lo acepta en la ruta."));
        return;
      }
      if (!quiet) root.replaceChildren(h("p", { class: "home-muted" }, "Cargando inicio…"));
      const [data, constellation] = await Promise.all([
        api.get(`/api/v1/projects/${currentProject}/overview`, { params: { period }, signal: current.signal }),
        // La vista previa es opcional: si falla, Inicio se muestra igual.
        api.get(`/api/v1/projects/${currentProject}/constellation`, { signal: current.signal }).catch((error) => {
          if (current.signal.aborted) throw error;
          return null;
        }),
      ]);
      if (!current.signal.aborted && current === controller) {
        renderOverview(root, data, currentProject, period, constellation);
      }
    } catch (error) {
      if (!current.signal.aborted && error.name !== "AbortError" && current === controller) {
        if (quiet) return console.warn("No se pudo refrescar Inicio:", error);
        root.replaceChildren(stateNotice("failure", "No se pudo cargar Inicio", errorMessage(error)));
      }
    } finally {
      signal?.removeEventListener("abort", abort);
      if (current === controller) loading = false;
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
  return {
    // `refresh` (db_changed, §19.4 O5): recarga sin aviso de carga y sin pisar lo visible si falla;
    // si hay una carga en curso (de la persona), no la cancela: el próximo aviso la retoma.
    refresh: () => (loading ? undefined : load({ quiet: true })),
    update(next) {
      if (next.project !== currentProject) {
        currentProject = next.project;
        void load();
      }
    },
    unmount() {
      root.removeEventListener("click", click);
      controller?.abort();
    },
  };
}
