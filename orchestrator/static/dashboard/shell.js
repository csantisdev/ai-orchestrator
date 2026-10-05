// Shell del dashboard (spec §23.4): navegación, breadcrumb, Inspector y estado en vivo
// alrededor de las vistas heredadas. Todo el texto variable se escribe con textContent.

import { createStore } from "./core/store.js";
import { connectRouter } from "./core/router.js";
import { SECTIONS, describeSelection, panelFor, resolveSection } from "./core/sections.js";
import { createApi } from "./core/api.js";
import { createViewHost } from "./core/mount.js";

const $ = (id) => document.getElementById(id);
const store = createStore({});
const api = createApi({
  fetch: window.fetch.bind(window),
  sessionToken: () => document.querySelector('meta[name="orchestrator-session"]')?.content ?? "",
});
// Vistas migradas (core/mount.js): se cargan bajo demanda, relativas a este módulo.
const views = createViewHost({
  root: $("view-root"),
  load: (path) => import(new URL(path, import.meta.url).href),
  onError: showViewError,
});
// Título que fija la vista montada con `page.set` (contrato en README.md): vale solo mientras
// esa vista siga en pantalla; al cambiar de vista vuelve el título de la sección.
let currentViewKey = null;
let pageTitle = null;
let lastResolved = null;

function viewKey(resolved) {
  if (!resolved.module) return null;
  return resolved.tab ? `${resolved.section.id}:${resolved.tab.id}` : resolved.section.id;
}

function pageFor(key) {
  return {
    set({ title = null, subtitle = null } = {}) {
      if (key !== currentViewKey) return;
      pageTitle = { key, title, subtitle };
      if (lastResolved) renderTitle(lastResolved);
    },
  };
}

function renderTitle(resolved) {
  const own = pageTitle && pageTitle.key === currentViewKey ? pageTitle : null;
  const fallback = resolved.tab ? `${resolved.section.label} · ${resolved.tab.label}` : resolved.section.label;
  $("shell-title").textContent = own?.title || fallback;
  const subtitle = own?.subtitle ?? resolved.section.question ?? "";
  $("shell-subtitle").textContent = subtitle;
  $("shell-subtitle").hidden = !subtitle;
}

// 768–1279 px: Inspector y Activity se superponen al contenido; nunca los dos abiertos.
const overlayLayout = window.matchMedia("(max-width: 1279px)");
let inspectorDismissed = false;
let lastActivityClick = 0;

function activityOpen() {
  const log = $("activity-log");
  return Boolean(log) && getComputedStyle(log).display !== "none";
}

function closeActivity() {
  if (activityOpen() && typeof window.toggleActivity === "function") window.toggleActivity();
}

function renderNavigation(resolved) {
  for (const link of document.querySelectorAll(".shell-nav [data-view]")) {
    if (link.dataset.view === resolved.section.id) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  $("shell-breadcrumb").replaceChildren(...resolved.crumbs.map((text, index) => {
    const item = document.createElement("span");
    item.className = "shell-crumb";
    item.textContent = text;
    if (index === resolved.crumbs.length - 1) item.setAttribute("aria-current", "location");
    return item;
  }));
  renderTitle(resolved);
  document.title = `${resolved.crumbs.slice(1).join(" · ")} — Orchestrator`;
}

function renderTabs(resolved) {
  const tabs = $("shell-tabs");
  const panelId = resolved.module ? "view-root" : "legacy-views";
  const panel = $(panelId);
  const other = $(resolved.module ? "legacy-views" : "view-root");
  other.removeAttribute("role");
  other.removeAttribute("aria-labelledby");
  const own = resolved.section.tabs ?? [];
  tabs.hidden = own.length === 0;
  tabs.replaceChildren(...own.map((tab) => {
    const selected = tab === resolved.tab;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "shell-tab";
    button.id = `shell-tab-${tab.id}`;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", panelFor(resolved.section, tab));
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
    button.dataset.view = resolved.section.id;
    button.dataset.tab = tab.id;
    button.textContent = tab.label;
    return button;
  }));
  if (own.length) {
    panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", `shell-tab-${resolved.tab.id}`);
  } else {
    panel.removeAttribute("role");
    panel.removeAttribute("aria-labelledby");
  }
}

function showViewError(error, root) {
  console.error("No se pudo mostrar la vista:", error);
  const box = document.createElement("section");
  box.className = "shell-empty";
  const title = document.createElement("h2");
  title.textContent = "No se pudo cargar esta vista";
  const body = document.createElement("p");
  body.textContent = error?.message ?? String(error);
  box.append(title, body);
  root.replaceChildren(box);
}

function renderContent(resolved, state) {
  const note = $("shell-note");
  note.hidden = !resolved.note;
  note.textContent = resolved.note ?? "";
  $("shell-empty").hidden = !resolved.empty;
  $("shell-empty-title").textContent = resolved.empty?.title ?? "";
  $("shell-empty-body").textContent = resolved.empty?.body ?? "";
  $("legacy-views").hidden = !resolved.legacy;
  if (resolved.legacy && typeof window.switchTab === "function") window.switchTab(resolved.legacy);
  $("view-root").hidden = !resolved.module;
  if (resolved.module) {
    const key = viewKey(resolved);
    views.show(key, resolved.module, { store, api, state, page: pageFor(key) });
  } else {
    views.hide();
  }
}

function renderInspector(state) {
  const selection = describeSelection(state.sel);
  $("inspector-empty").hidden = Boolean(selection);
  $("inspector-selection").hidden = !selection;
  $("shell-inspector").dataset.open = String(Boolean(selection) && !inspectorDismissed);
  if (selection) {
    $("inspector-kind").textContent = selection.label;
    $("inspector-id").textContent = selection.id;
    $("inspector-id").title = selection.full;
  }
}

function render(state, previous = {}) {
  if (state.sel && state.sel !== previous.sel) {
    inspectorDismissed = false;
    if (overlayLayout.matches) closeActivity();
  }
  const resolved = resolveSection(state);
  const key = viewKey(resolved);
  if (key !== currentViewKey) pageTitle = null;
  currentViewKey = key;
  lastResolved = resolved;
  renderNavigation(resolved);
  renderTabs(resolved);
  renderContent(resolved, state);
  renderInspector(state);
  // El selector de proyecto recarga la página con ?project=; conserva la sección.
  $("shell-view-input").value = resolved.section.id;
}

// Activity abierta por el usuario oculta el Inspector superpuesto; abierta sola (por un
// evento) mientras el Inspector está abierto, se vuelve a cerrar.
function watchActivity() {
  const log = $("activity-log");
  if (!log) return;
  // Solo los controles que abren o cierran Activity cuentan como gesto del usuario; los
  // botones de acciones (doctor, fix, sync, index) de la misma barra no.
  document.querySelector(".activity-hdr")?.addEventListener("click", (event) => {
    if (event.target.closest?.(".act-left, #act-toggle")) lastActivityClick = Date.now();
  }, true);
  const inspectorOpen = () => $("shell-inspector").dataset.open === "true";
  new MutationObserver(() => {
    if (!overlayLayout.matches || !activityOpen() || !inspectorOpen()) return;
    if (Date.now() - lastActivityClick < 500) {
      inspectorDismissed = true;
      renderInspector(store.get());
    } else {
      closeActivity();
    }
  }).observe(log, { attributes: true, attributeFilter: ["style"] });
  // Al achicar la ventana a 768–1279 px con los dos abiertos, gana el Inspector.
  overlayLayout.addEventListener("change", () => {
    if (overlayLayout.matches && activityOpen() && inspectorOpen()) closeActivity();
  });
}

function watchConnection() {
  const status = $("shell-status");
  const events = window.__dashboardEvents;
  const set = (state, text) => {
    status.dataset.state = state;
    status.textContent = text;
  };
  if (!events) {
    set("offline", "Sin conexión");
    return;
  }
  set(events.readyState === 1 ? "live" : "connecting", events.readyState === 1 ? "En vivo" : "Conectando…");
  events.addEventListener("open", () => set("live", "En vivo"));
  events.addEventListener("error", () => set(events.readyState === 2 ? "offline" : "connecting",
    events.readyState === 2 ? "Sin conexión" : "Reconectando…"));
}

// Contadores de la navegación y aviso de denegadas del header (§23.4), del proyecto elegido.
async function loadHeaderCounts() {
  const project = store.get().project;
  if (!project) return;
  try {
    const { projects } = await api.get("/api/v1/meta/projects");
    const own = projects.find((item) => item.alias === project);
    const counts = { trabajo: own?.active_contexts, ejecuciones: own?.runs };
    for (const [view, value] of Object.entries(counts)) {
      const slot = document.querySelector(`.shell-nav-count[data-count="${view}"]`);
      if (slot) slot.textContent = value ? new Intl.NumberFormat("es-CL").format(value) : "";
    }
    // La API de proyectos limita la ruta a caracteres seguros; si el alias no cabe, no hay aviso.
    if (!/^[A-Za-z0-9_~-][A-Za-z0-9._~-]*$/.test(project)) return;
    const summary = await api.get(`/api/v1/projects/${project}/governance/summary`, { params: { period: "7d" } });
    const problems = summary.mcp.denied + summary.mcp.error;
    const pill = $("shell-denied");
    pill.hidden = problems === 0;
    pill.textContent = `${problems} ${problems === 1 ? "denegada o con error" : "denegadas o con error"} · 7 d`;
    pill.href = `/?${new URLSearchParams({ project, view: "gobernanza" })}`;
  } catch (error) {
    console.warn("No se pudieron cargar los contadores del header:", error);
  }
}

// Acciones del dashboard heredado: viven en sus pestañas (Ejecuciones › Actividad y Trabajo ›
// Flujos), así que primero se navega hasta ellas.
const ACTIONS = {
  "clear-selection": () => store.set({ sel: null }),
  "new-task": () => {
    store.set({ view: "ejecuciones", tab: "actividad" });
    const panel = $("senderPanel");
    panel?.classList.add("open");
    panel?.scrollIntoView({ block: "start" });
    $("senderTask")?.focus();
  },
  "new-flow": () => {
    store.set({ view: "trabajo", tab: "flujos" });
    $("ctxTitle")?.scrollIntoView({ block: "center" });
    $("ctxTitle")?.focus();
  },
};

$("shell-project").addEventListener("change", (event) => event.currentTarget.form.submit());
$("themeSelect")?.addEventListener("change", (event) => window.setTheme?.(event.currentTarget.value));

document.addEventListener("click", (event) => {
  const target = event.target.closest?.("[data-view], [data-action]");
  if (!target) return;
  const action = ACTIONS[target.dataset.action];
  if (action) {
    $("shell-menu").open = false;
    action();
    return;
  }
  if (!target.dataset.view) return;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1) return;
  event.preventDefault();
  store.set({ view: target.dataset.view, tab: target.dataset.tab ?? null });
});

// Pestañas de representación: flechas, Inicio y Fin mueven la selección (patrón ARIA tabs).
$("shell-tabs").addEventListener("keydown", (event) => {
  const tabs = [...event.currentTarget.querySelectorAll('[role="tab"]')];
  const index = tabs.indexOf(document.activeElement);
  if (index < 0) return;
  const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1 }[event.key];
  if (next === undefined) return;
  event.preventDefault();
  const tab = tabs[(next + tabs.length) % tabs.length];
  store.set({ view: tab.dataset.view, tab: tab.dataset.tab });
  $(`shell-tab-${tab.dataset.tab}`)?.focus();
});

connectRouter({
  store,
  history: window.history,
  location: window.location,
  addEventListener: window.addEventListener.bind(window),
});
store.subscribe(render);
render(store.get());
watchActivity();
watchConnection();
loadHeaderCounts();
document.documentElement.dataset.shell = "ready";

export { SECTIONS, store };
