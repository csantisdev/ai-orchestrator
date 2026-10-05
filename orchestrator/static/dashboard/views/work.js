// Vista Trabajo (spec §23.3): contextos del proyecto → un contexto con sus pasos → el Trace
// de un paso. La página sale de la URL (`ctx`, `step`); la selección (`sel`) abre el
// Inspector. Contrato de montaje en ../README.md.

import { h } from "../core/dom.js";
import { toSearch } from "../core/router.js";
import { facts, objectList, statusPill } from "../renderers/list.js";
import { renderTrace } from "../renderers/trace.js";
import { progress, segmented } from "../core/ui.js";

export const CONTEXT_STATUS = Object.freeze({
  active: "Activo", programado: "Programado", completed: "Completado", abandoned: "Abandonado",
});
export const STEP_STATUS = Object.freeze({
  pending: "Pendiente", in_progress: "En curso", completed: "Completado", blocked: "Bloqueado", skipped: "Omitido",
});
const AGENTS = { claude: "Claude", codex: "Codex", copilot: "Copilot", otros: "Otros", "sin agente": "Sin agente" };
const FILTERS = [["", "Todos"], ...Object.entries(CONTEXT_STATUS)];
// Un alias que necesitaría `%` en la ruta no pasa la validación de core/api.js.
const PATH_SEGMENT = /^[A-Za-z0-9_~-][A-Za-z0-9._~-]*$/;
const STYLE_KEY = "work";

export function pageFor(state) {
  if (!state.project) return "no-project";
  if (state.step) return "step";
  if (state.ctx) return "context";
  return "contexts";
}

// Ruta de la API para la página actual, o null si el alias no se puede usar en la ruta.
export function endpointFor(state) {
  if (!state.project || !PATH_SEGMENT.test(state.project)) return null;
  const base = `/api/v1/projects/${state.project}`;
  if (state.step) return `${base}/steps/${state.step}/trace`;
  if (state.ctx) return `${base}/contexts/${state.ctx}`;
  return `${base}/contexts`;
}

export function hrefFor(state, patch) {
  return toSearch({ ...state, view: "trabajo", sel: null, ...patch }) || "?";
}

export function formatInstant(iso, { timeZone } = {}) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("es-CL", {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone,
  }).format(date);
}

export function formatUsd(value) {
  if (value === null || value === undefined) return null;
  return new Intl.NumberFormat("es-CL", {
    style: "currency", currency: "USD", minimumFractionDigits: value > 0 && value < 0.01 ? 4 : 2,
  }).format(value);
}

export function agentLabel(agent) {
  return AGENTS[agent] ?? agent ?? "—";
}

export function progressText(counts) {
  if (!counts.total) return "Sin pasos";
  const parts = [`${counts.completed}/${counts.total} completados`];
  if (counts.in_progress) parts.push(`${counts.in_progress} en curso`);
  if (counts.blocked) parts.push(`${counts.blocked} bloqueados`);
  return parts.join(" · ");
}

function ensureStylesheet(doc) {
  if (doc.head.querySelector(`link[data-view-css="${STYLE_KEY}"]`)) return;
  doc.head.append(h("link", {
    rel: "stylesheet", href: new URL("./work.css", import.meta.url).href, data: { viewCss: STYLE_KEY },
  }));
}

// Enlace interno: href completo (abrir en otra pestaña, copiar) y `data-ctx`/`data-step`
// para navegar sin recargar.
function navLink(state, patch, children, className = "work-link") {
  return h("a", {
    class: className,
    href: hrefFor(state, patch),
    data: { nav: "1", ctx: patch.ctx ?? "", step: patch.step ?? "" },
  }, children);
}

// El título de la página lo pone el shell (`page.set`); acá queda la fila de estado y acciones.
function header(status, labels, extra) {
  return h("header", { class: "work-header" },
    status === undefined ? null : h("div", { class: "work-header-title" }, statusPill(status, labels)),
    extra);
}

function count(value, singular, plural) {
  return `${value} ${value === 1 ? singular : plural}`;
}

// Título y subtítulo de cada página para el encabezado del shell (§23.3: el título es el objeto).
export function pageTitle(page, data) {
  if (page === "step") {
    return {
      title: `Paso ${data.step.idx} de ${data.navigation.total} · ${data.step.title || "Sin título"}`,
      subtitle: `Contexto #${data.context.id} · ${data.context.title || "Sin título"}`,
    };
  }
  if (page === "context") {
    const done = data.steps.filter((step) => step.status === "completed").length;
    return {
      title: `Contexto #${data.context.id} · ${data.context.title || "Sin título"}`,
      subtitle: `${done} de ${count(data.steps.length, "paso completado", "pasos completados")}`,
    };
  }
  const active = data.contexts.filter((item) => item.status === "active").length;
  return {
    title: "Trabajo",
    subtitle: `${count(data.contexts.length, "contexto", "contextos")} · ${count(active, "activo", "activos")}`,
  };
}

function contextsPage(state, data, filter) {
  const filters = segmented({ label: "Filtrar por estado", options: FILTERS, current: filter, attribute: "filter" });
  const list = objectList(data.contexts, (item) => [
    h("div", { class: "object-main" },
      navLink(state, { ctx: item.id, step: null }, [h("span", { class: "object-id" }, `#${item.id}`), item.title || "Sin título"]),
      statusPill(item.status, CONTEXT_STATUS)),
    item.steps.total ? progress({ value: item.steps.completed, max: item.steps.total, label: progressText(item.steps) }) : null,
    h("div", { class: "object-meta" },
      h("span", {}, progressText(item.steps)),
      item.current_step ? h("span", {}, "En curso: ",
        navLink(state, { ctx: item.id, step: item.current_step.id }, item.current_step.title || `Paso #${item.current_step.id}`)) : null,
      h("time", { datetime: item.updated_at ?? undefined }, `Actualizado ${formatInstant(item.updated_at)}`)),
  ], { label: "Contextos", empty: filter ? "No hay contextos con ese estado." : "El proyecto no tiene contextos." });
  return [header(undefined, null, filters), list];
}

function contextPage(state, data) {
  const { context, steps } = data;
  const parent = context.parent
    ? h("p", { class: "work-subtle" }, "Creado desde ",
      navLink(state, { ctx: context.parent.context_id, step: context.parent.step_id }, `el paso #${context.parent.step_id} del contexto #${context.parent.context_id}`))
    : null;
  const list = objectList(steps, (step) => [
    h("div", { class: "object-main" },
      navLink(state, { ctx: context.id, step: step.id }, [h("span", { class: "object-id" }, `Paso ${step.idx}`), step.title || "Sin título"]),
      statusPill(step.status, STEP_STATUS)),
    h("div", { class: "object-meta" },
      h("span", {}, agentLabel(step.lane), step.secondary.length ? ` + ${step.secondary.map(agentLabel).join(", ")}` : ""),
      facts([
        [step.alignments, "alineamiento", "alineamientos"],
        [step.deviations, "desvío", "desvíos"],
        [step.tool_calls, "tool call", "tool calls"],
        [step.runs, "run", "runs"],
        [step.verified_commits, "commit verificado", "commits verificados"],
        [step.prs.length, "PR", "PRs"],
      ]),
      // Un paso cerrado sin notas no deja evidencia (§20.2); en los abiertos es lo esperable.
      step.has_notes || step.status !== "completed" ? null : h("span", { class: "work-warning" }, "cerrado sin notas"),
      step.children.length ? h("span", {}, "Contextos derivados: ",
        step.children.map((child) => navLink(state, { ctx: child, step: null }, `#${child}`))) : null),
  ], { label: "Pasos", empty: "El contexto no tiene pasos." });
  return [
    h("nav", { class: "work-back" }, navLink(state, { ctx: null, step: null }, "← Contextos")),
    header(context.status, CONTEXT_STATUS),
    context.description ? h("p", { class: "work-description" }, context.description) : null,
    parent,
    list,
  ];
}

function stepPage(state, data) {
  const { context, step, navigation } = data;
  const sibling = (id, label) => (id ? navLink(state, { ctx: context.id, step: id }, label, "work-link work-sibling") : null);
  return [
    h("nav", { class: "work-back" },
      navLink(state, { ctx: context.id, step: null }, `← #${context.id} ${context.title || "Contexto"}`)),
    header(step.status, STEP_STATUS,
      h("div", { class: "work-siblings" }, sibling(navigation.previous, "← Anterior"), sibling(navigation.next, "Siguiente →"))),
    h("p", { class: "work-subtle" },
      [step.provider ? `Proveedor: ${step.provider}` : "Sin proveedor asignado",
        `Inicio: ${formatInstant(step.started_at)}`, `Cierre: ${formatInstant(step.completed_at)}`].join(" · ")),
    step.description ? h("p", { class: "work-description" }, step.description) : null,
    renderTrace(data, { formatInstant, formatUsd, agentLabel, selected: state.sel }),
  ];
}

function message(title, body) {
  return h("section", { class: "shell-empty" }, h("h2", {}, title), body ? h("p", {}, body) : null);
}

export async function mount(root, { api, state, signal, store, page: shellPage }) {
  ensureStylesheet(root.ownerDocument);
  root.classList.add("work-view");
  let current = state;
  let filter = "";
  let pending = null;

  async function load() {
    // Cualquier carga anterior queda superada, también por una página sin petición.
    pending?.abort();
    pending = null;
    const page = pageFor(current);
    shellPage?.set({});
    if (page === "no-project") {
      root.replaceChildren(message("Elegí un proyecto", "Trabajo muestra los contextos de un proyecto: elegilo en el selector de arriba."));
      return;
    }
    const path = endpointFor(current);
    if (!path) {
      root.replaceChildren(message("Este proyecto no se puede consultar desde la vista nueva",
        "Su alias tiene caracteres que la API no acepta en la ruta. La pestaña Flujos (heredado) lo sigue mostrando."));
      return;
    }
    const controller = new AbortController();
    pending = controller;
    const abort = () => controller.abort();
    signal.addEventListener("abort", abort, { once: true });
    root.replaceChildren(h("p", { class: "work-loading", role: "status" }, "Cargando…"));
    try {
      const params = page === "contexts" && filter ? { status: filter } : {};
      const data = await api.get(path, { params, signal: controller.signal });
      if (controller.signal.aborted) return;
      const content = page === "step" ? stepPage(current, data)
        : page === "context" ? contextPage(current, data)
          : contextsPage(current, data, filter);
      root.replaceChildren(...content.filter(Boolean));
      shellPage?.set(pageTitle(page, data));
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error?.status === 404) {
        root.replaceChildren(message(page === "step" ? "No existe ese paso en este proyecto" : "No existe ese contexto en este proyecto",
          "Puede ser de otro proyecto o haberse borrado."),
        h("p", {}, navLink(current, { ctx: null, step: null }, "Ver los contextos del proyecto")));
        return;
      }
      const reload = error?.reason === "session_expired" ? " El servidor se reinició: recargá la página." : "";
      root.replaceChildren(message("No se pudo cargar Trabajo", `${error?.message ?? error}.${reload}`));
    } finally {
      signal.removeEventListener("abort", abort);
      if (pending === controller) pending = null;
    }
  }

  function onClick(event) {
    const target = event.target.closest?.("[data-nav], [data-sel], [data-filter]");
    if (!target || !root.contains(target)) return;
    if (target.dataset.filter !== undefined) {
      filter = target.dataset.filter;
      load();
      return;
    }
    if (target.dataset.sel) {
      store.set({ sel: current.sel === target.dataset.sel ? null : target.dataset.sel });
      return;
    }
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1) return;
    event.preventDefault();
    const id = (value) => (value ? Number(value) : null);
    store.set({ ctx: id(target.dataset.ctx), step: id(target.dataset.step), sel: null });
  }

  root.addEventListener("click", onClick);
  await load();
  return {
    update(next) {
      const previous = current;
      current = next;
      if (next.project !== previous.project || next.ctx !== previous.ctx || next.step !== previous.step) {
        load();
        return;
      }
      if (next.sel !== previous.sel) {
        for (const chip of root.querySelectorAll("[data-sel]")) {
          const selected = chip.dataset.sel === next.sel;
          chip.classList.toggle("is-selected", selected);
          chip.setAttribute("aria-pressed", String(selected));
        }
      }
    },
    unmount() {
      root.removeEventListener("click", onClick);
      pending?.abort();
    },
  };
}
