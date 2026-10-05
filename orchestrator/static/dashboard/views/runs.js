import { h } from "../core/dom.js";
import { toSearch } from "../core/router.js";
import { dataTable, segmented } from "../core/ui.js";
import { statusPill } from "../renderers/list.js";

const STYLE_KEY = "executions";
const PATH_SEGMENT = /^[A-Za-z0-9_~-][A-Za-z0-9._~-]*$/;
const SOURCES = ["all", "router", "session", "commit"];
const RUN_STATUS = { done: "Hecho", error: "Error", running: "En curso", pending: "Pendiente" };

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

function formatRunTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("es-CL", {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).format(date);
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

const COLUMNS = [
  { label: "Run" }, { label: "Fecha" }, { label: "Tarea" }, { label: "Fuente" }, { label: "Estado" },
  { label: "Proveedor" }, { label: "Modelo" }, { label: "Costo", numeric: true }, { label: "Paso" },
];

function table(state, runs) {
  return dataTable({
    label: "Runs",
    columns: COLUMNS,
    empty: "No hay runs para este filtro.",
    rows: runs.map((run) => {
      const sel = `run:${run.id}`;
      return {
        selected: state.sel === sel,
        cells: [
          h("button", { type: "button", class: "cell-button", data: { sel }, "aria-pressed": String(state.sel === sel) }, `#${run.id}`),
          run.ts ? h("time", { class: "cell-data", datetime: run.ts }, formatRunTime(run.ts)) : "—",
          h("span", { class: "cell-text", title: run.task_preview || undefined }, run.task_preview || "Sin descripción"),
          sourceLabel(run.source),
          statusPill(run.status, RUN_STATUS),
          run.provider || "—",
          run.model || "—",
          formatUsd(run.cost_usd),
          run.context_id
            ? h("a", {
              class: "cell-link",
              href: stepHref(state, run.context_id, run.step_id),
              data: { nav: "1", ctx: run.context_id, step: run.step_id },
            }, `Paso #${run.step_id}`)
            : "—",
        ],
      };
    }),
  });
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
    const filters = segmented({
      label: "Filtrar por fuente",
      options: SOURCES.map((value) => [value, sourceLabel(value)]),
      current: source,
      attribute: "source",
    });
    root.replaceChildren(...[
      h("header", { class: "executions-header" }, filters),
      table(current, rows),
      cursor ? h("button", { type: "button", class: "ui-button", data: { more: "1" } }, "Cargar más") : null,
    ].filter(Boolean));
  }

  async function load(more = false, quiet = false) {
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
    if (!more && !quiet) root.replaceChildren(h("p", { role: "status" }, "Cargando…"));
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
      if (quiet) return console.warn("No se pudieron refrescar los runs:", error);
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
    // `refresh` (db_changed, §19.4 O5): recarga sin aviso de carga y sin pisar lo visible si falla.
    // Con más de una página cargada no se refresca: se perdería lo que la persona ya pidió.
    refresh: () => (rows.length > 50 ? undefined : load(false, true)),
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
