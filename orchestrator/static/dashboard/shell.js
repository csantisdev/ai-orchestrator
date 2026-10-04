// Shell del dashboard (spec §23.4): navegación, breadcrumb, Inspector y estado en vivo
// alrededor de las vistas heredadas. Todo el texto variable se escribe con textContent.

import { createStore } from "./core/store.js";
import { connectRouter } from "./core/router.js";
import { SECTIONS, describeSelection, resolveSection } from "./core/sections.js";

const $ = (id) => document.getElementById(id);
const store = createStore({});
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
  $("shell-title").textContent = resolved.tab ? `${resolved.section.label} · ${resolved.tab.label}` : resolved.section.label;
  document.title = `${resolved.crumbs.slice(1).join(" · ")} — Orchestrator`;
}

function renderTabs(resolved) {
  const tabs = $("shell-tabs");
  const panel = $("legacy-views");
  const own = resolved.section.tabs ?? [];
  tabs.hidden = own.length === 0;
  tabs.replaceChildren(...own.map((tab) => {
    const selected = tab === resolved.tab;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "shell-tab";
    button.id = `shell-tab-${tab.id}`;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", "legacy-views");
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

function renderContent(resolved) {
  const note = $("shell-note");
  note.hidden = !resolved.note;
  note.textContent = resolved.note ?? "";
  $("shell-empty").hidden = !resolved.empty;
  $("shell-empty-title").textContent = resolved.empty?.title ?? "";
  $("shell-empty-body").textContent = resolved.empty?.body ?? "";
  $("legacy-views").hidden = !resolved.legacy;
  if (resolved.legacy && typeof window.switchTab === "function") window.switchTab(resolved.legacy);
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
  renderNavigation(resolved);
  renderTabs(resolved);
  renderContent(resolved);
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

document.addEventListener("click", (event) => {
  const target = event.target.closest?.("[data-view], [data-action]");
  if (!target) return;
  if (target.dataset.action === "clear-selection") {
    store.set({ sel: null });
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
document.documentElement.dataset.shell = "ready";

export { SECTIONS, store };
