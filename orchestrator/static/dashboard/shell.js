// Shell del dashboard (spec §23.4): navegación, breadcrumb, Inspector y estado en vivo
// alrededor de las vistas heredadas. Todo el texto variable se escribe con textContent.

import { createStore } from "./core/store.js";
import { connectRouter } from "./core/router.js";
import { SECTIONS, describeSelection, resolveSection } from "./core/sections.js";

const $ = (id) => document.getElementById(id);
const store = createStore({});

function renderNavigation(resolved) {
  for (const link of document.querySelectorAll(".shell-nav [data-view]")) {
    if (link.dataset.view === resolved.section.id) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  const breadcrumb = $("shell-breadcrumb");
  breadcrumb.replaceChildren(...resolved.crumbs.map((text, index) => {
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
  const own = resolved.section.tabs ?? [];
  tabs.hidden = own.length === 0;
  tabs.replaceChildren(...own.map((tab) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "shell-tab";
    button.setAttribute("role", "tab");
    button.dataset.view = resolved.section.id;
    button.dataset.tab = tab.id;
    button.textContent = tab.label;
    button.setAttribute("aria-selected", String(tab === resolved.tab));
    return button;
  }));
}

function renderContent(resolved) {
  const note = $("shell-note");
  note.hidden = !resolved.note;
  note.textContent = resolved.note ?? "";
  const empty = $("shell-empty");
  empty.hidden = !resolved.empty;
  $("shell-empty-title").textContent = resolved.empty?.title ?? "";
  $("shell-empty-body").textContent = resolved.empty?.body ?? "";
  const legacyViews = $("legacy-views");
  legacyViews.hidden = !resolved.legacy;
  if (resolved.legacy && typeof window.switchTab === "function") window.switchTab(resolved.legacy);
}

function renderInspector(state) {
  const selection = describeSelection(state.sel);
  $("inspector-empty").hidden = Boolean(selection);
  $("inspector-selection").hidden = !selection;
  $("shell-inspector").dataset.open = String(Boolean(selection));
  if (selection) {
    $("inspector-kind").textContent = selection.label;
    $("inspector-id").textContent = selection.id;
    $("inspector-id").title = selection.full;
  }
}

function render(state) {
  const resolved = resolveSection(state);
  renderNavigation(resolved);
  renderTabs(resolved);
  renderContent(resolved);
  renderInspector(state);
  // El selector de proyecto recarga la página con ?project=; conserva la sección.
  $("shell-view-input").value = resolved.section.id;
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

connectRouter({
  store,
  history: window.history,
  location: window.location,
  addEventListener: window.addEventListener.bind(window),
});
store.subscribe(render);
render(store.get());
watchConnection();
document.documentElement.dataset.shell = "ready";

export { SECTIONS, store };
