import { h } from "../core/dom.js";
import { toSearch } from "../core/router.js";

const STYLE_KEY = "executions";
const PATH_SEGMENT = /^[A-Za-z0-9_~-][A-Za-z0-9._~-]*$/;
const SOURCES = ["all", "router", "session", "commit"];

export function sourceLabel(source) {
  return { all: "Todas", router: "Router", session: "Sesión", commit: "Commit" }[source] ?? source;
}

export function formatUsd(value) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("es-CL", { style: "currency", currency: "USD" }).format(value);
}

export function stepHref(state, contextId, stepId) {
  if (!contextId || !stepId) return null;
  return toSearch({
    ...state,
    view: "trabajo",
    tab: "contextos",
    ctx: contextId,
    step: stepId,
    sel: null,
  });
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

function table(state, runs) {
  const body = runs.length
    ? runs.map((run) => h("tr", {},
      h("td", {}, h("button", {
        type: "button",
        class: ["execution-row", state.sel === `run:${run.id}` && "is-selected"],
        data: { sel: `run:${run.id}` },
        "aria-pressed": String(state.sel === `run:${run.id}`),
      }, `#${run.id}`)),
      h("td", {}, run.task_preview || "Sin descripción"),
      h("td", {}, sourceLabel(run.source)),
      h("td", {}, run.provider),
      h("td", {}, formatUsd(run.cost_usd)),
      h("td", {}, run.context_id
        ? h("a", {
          href: stepHref(state, run.context_id, run.step_id),
          data: { nav: "1", ctx: run.context_id, step: run.step_id },
        }, `Paso #${run.step_id}`)
        : "—"),
    ))
    : h("tr", {}, h("td", { colspan: 6 }, "No hay runs para este filtro."));
  return h("table", { class: "execution-table" },
    h("thead", {}, h("tr", {}, ["ID", "Tarea", "Fuente", "Proveedor", "Costo", "Paso"]
      .map((label) => h("th", {}, label)))),
    h("tbody", {}, body));
}

export async function mount(root, { api, state, signal, store }) {
  ensureStylesheet(root.ownerDocument);
  root.classList.add("executions-view");
  let current = state;
  let source = "all";
  let cursor = null;
  let rows = [];
  let pending = null;

  function render() {
    const filters = h("div", {
      class: "execution-filters",
      role: "group",
      "aria-label": "Filtrar por fuente",
    }, SOURCES.map((value) => h("button", {
      type: "button",
      class: ["execution-filter", source === value && "is-active"],
      data: { source: value },
      "aria-pressed": String(source === value),
    }, sourceLabel(value))));
    root.replaceChildren(
      h("header", { class: "executions-header" }, h("h2", {}, "Runs"), filters),
      table(current, rows),
      cursor ? h("button", { type: "button", data: { more: "1" } }, "Cargar más") : null,
    );
  }

  async function load(more = false) {
    pending?.abort();
    pending = null;
    if (!current.project) {
      root.replaceChildren(message("Elegí un proyecto", "Runs muestra las ejecuciones del proyecto seleccionado."));
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
    if (!more) root.replaceChildren(h("p", { role: "status" }, "Cargando…"));
    try {
      const data = await api.get(`/api/v1/projects/${current.project}/runs`, {
        params: { source, limit: 50, cursor: more ? cursor : null },
        signal: controller.signal,
      });
      if (controller.signal.aborted || pending !== controller) return;
      rows = more ? rows.concat(data.runs) : data.runs;
      cursor = data.next_cursor;
      render();
    } catch (error) {
      if (controller.signal.aborted) return;
      const suffix = error?.reason === "session_expired" ? " El servidor se reinició: recargá la página." : "";
      root.replaceChildren(message("No se pudieron cargar los runs", `${error?.message ?? error}.${suffix}`));
    } finally {
      signal.removeEventListener("abort", abort);
      if (pending === controller) pending = null;
    }
  }

  function onClick(event) {
    const target = event.target.closest?.("[data-source], [data-more], [data-sel], [data-nav]");
    if (!target || !root.contains(target)) return;
    if (target.dataset.source !== undefined) {
      source = target.dataset.source;
      cursor = null;
      rows = [];
      void load();
      return;
    }
    if (target.dataset.more !== undefined) {
      void load(true);
      return;
    }
    if (target.dataset.sel) {
      store.set({ sel: target.dataset.sel });
      return;
    }
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1) return;
    event.preventDefault();
    store.set({
      view: "trabajo",
      tab: "contextos",
      ctx: Number(target.dataset.ctx),
      step: Number(target.dataset.step),
      sel: null,
    });
  }

  root.addEventListener("click", onClick);
  await load();
  return {
    update(next) {
      const previous = current;
      const changedProject = next.project !== previous.project;
      current = next;
      if (changedProject) {
        cursor = null;
        rows = [];
        void load();
      } else if (next.sel !== previous.sel) {
        render();
      }
    },
    unmount() {
      root.removeEventListener("click", onClick);
      pending?.abort();
    },
  };
}
