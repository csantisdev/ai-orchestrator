// Vista Trabajo (spec §23.3): contextos del proyecto → un contexto con sus pasos → el Trace
// de un paso. La página sale de la URL (`ctx`, `step`); la selección (`sel`) abre el
// Inspector. Contrato de montaje en ../README.md.

import { h } from "../core/dom.js";
import { toSearch } from "../core/router.js";
import { facts, objectList, statusPill } from "../renderers/list.js";
import { renderTrace, selectable } from "../renderers/trace.js";
import { panel, progress, segmented } from "../core/ui.js";
import { citingSteps, layoutMap, renderMap, select as selectOnMap } from "../renderers/map.js";
import {
  agentLabel as consAgentLabel, layoutConstellation, renderConstellation, selectConstellation,
} from "../renderers/constellation.js";

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

export const CONTEXT_REPRESENTATIONS = Object.freeze([["list", "Lista"], ["constellation", "◇ Grafo · Labs"]]);
const CONS_MODES = [["global", "Global"], ["local", "Local"]];
const CONS_LENSES = [["agent", "Agente dominante"], ["project", "Proyecto"]];
const CONS_SCOPES = [["active", "Activos y conectados"], ["all", "Todos"]];
const CONS_DEPTHS = [["1", "1 salto"], ["2", "2 saltos"]];

// Constelación de los contextos (§22.4): controles, leyenda, SVG y lista equivalente.
function constellationSection(state, data, cons, view) {
  if (!cons) {
    return [panel("Grafo · Labs", h("p", { class: "empty-note" },
      "La constelación no está disponible ahora; la pestaña Lista sigue funcionando."))];
  }
  // El foco del modo local es el último contexto seleccionado; elegir o soltar un commit no lo
  // cambia (deseleccionar el contexto lo limpia en `update`).
  if (state.sel?.startsWith("context:")) view.focus = state.sel;
  const focus = view.focus;
  const layout = layoutConstellation(cons, { scope: view.scope, mode: view.mode, focus, depth: view.depth, lens: view.lens });
  const graphic = renderConstellation(layout);
  view.layout = layout;
  view.svg = graphic;
  if (state.sel) selectConstellation(graphic, layout, state.sel);
  const titles = new Map(data.contexts.map((item) => [`context:${item.id}`, item.title || "Sin título"]));
  const links = new Map();
  for (const bridge of layout.bridges) {
    for (const [from, to] of [[bridge.source, bridge.target], [bridge.target, bridge.source]]) {
      if (!links.has(from)) links.set(from, []);
      links.get(from).push({ to, weight: bridge.weight });
    }
  }
  const controls = h("div", { class: "cons-controls" },
    h("span", { class: "control-label" }, "Modo"),
    segmented({ label: "Modo", options: CONS_MODES, current: view.mode, attribute: "consMode" }),
    view.mode === "local" ? segmented({ label: "Profundidad", options: CONS_DEPTHS, current: String(view.depth), attribute: "consDepth" }) : null,
    h("span", { class: "control-label" }, "Color por"),
    segmented({ label: "Color por", options: CONS_LENSES, current: view.lens, attribute: "consLens" }),
    view.mode === "global"
      ? [h("span", { class: "control-label" }, "Alcance"),
        segmented({ label: "Alcance", options: CONS_SCOPES, current: view.scope, attribute: "consScope" })]
      : null);
  const legend = h("ul", { class: "cons-legend", "aria-label": "Leyenda de la constelación" },
    view.lens === "agent"
      ? ["claude", "codex", "copilot", "otros", "sin agente"].map((agent) =>
        h("li", { class: `tone-${agent.replace(/\s+/g, "-")}` }, h("span", { class: "swatch" }), consAgentLabel(agent)))
      : h("li", {}, "Todos los contextos del proyecto con el mismo color; los portales llevan a otros proyectos"),
    h("li", {}, "línea = commits compartidos (grosor = cantidad) · ↗ portal = otro proyecto"),
    h("li", {}, "halo = paso en curso · borde punteado = con desvíos · puntos = pasos"));
  const hint = view.mode === "local" && !focus
    ? h("p", { class: "empty-note" }, "Modo local: seleccioná un contexto (en el grafo o en la lista) para ver su vecindario.")
    : null;
  const hidden = layout.hiddenContexts && view.mode === "global" && view.scope === "active"
    ? h("p", { class: "empty-note" }, `${layout.hiddenContexts} contextos sin actividad ni conexiones con los activos quedan fuera; "Todos" los muestra.`)
    : null;
  const listed = [...layout.suns].sort((a, b) => Number(b.connected) - Number(a.connected) || a.id.localeCompare(b.id));
  const list = objectList(listed, (sun) => [
    h("div", { class: "object-main" },
      h("button", { type: "button", class: "cell-button", data: { sel: sun.id }, "aria-pressed": String(state.sel === sun.id) },
        `#${sun.id.split(":")[1]}`),
      navLink(state, { ctx: Number(sun.id.split(":")[1]), step: null }, titles.get(sun.id) ?? sun.label),
      statusPill(sun.state, CONTEXT_STATUS)),
    h("div", { class: "object-meta" },
      h("span", {}, `${sun.steps} pasos · ${consAgentLabel(sun.agent)}`),
      (links.get(sun.id) ?? []).length
        ? h("span", {}, "Comparte commits con ", (links.get(sun.id) ?? []).map((link, index) => [
          index ? ", " : "",
          link.to.startsWith("portal:") ? `${link.to.slice(7)} (otro proyecto)` : `#${link.to.split(":")[1]}`,
          ` (${link.weight})`,
        ]))
        : h("span", {}, "Sin commits compartidos")),
  ], { label: "Contextos del grafo", empty: "No hay contextos para mostrar con este alcance." });
  // Puentes (§22.4): extremos y commits compartidos, todos seleccionables con teclado.
  const end = (id) => (id.startsWith("portal:")
    ? h("span", { class: "cons-portal-name" }, `↗ ${id.slice(7)} (otro proyecto)`)
    : selectable(id, `#${id.split(":")[1]}`, titles.get(id), state.sel));
  const bridgeList = objectList(layout.bridges, (bridge) => [
    h("div", { class: "object-main" }, end(bridge.source), h("span", { "aria-hidden": "true" }, "↔"), end(bridge.target),
      h("span", { class: "object-meta" }, `${bridge.weight} ${bridge.weight === 1 ? "commit compartido" : "commits compartidos"}`)),
    h("div", { class: "trace-chips" }, bridge.commits.map((commit) => selectable(commit, commit.slice(7, 14), null, state.sel))),
  ], { label: "Puentes del grafo", empty: "Ningún contexto visible comparte commits." });
  return [
    panel("Grafo · Labs", controls, legend, hint, hidden, h("div", { class: "constellation-wrap" }, graphic)),
    panel("Lista equivalente", list),
    panel("Puentes", bridgeList),
  ];
}

function contextsPage(state, data, filter, cons = null, view = null) {
  const representation = segmented({
    label: "Representación", options: CONTEXT_REPRESENTATIONS,
    current: state.as === "constellation" ? "constellation" : "list", attribute: "as",
  });
  if (state.as === "constellation") {
    return [header(undefined, null, representation), ...constellationSection(state, data, cons, view)];
  }
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
  return [header(undefined, null, h("div", { class: "work-representation" }, representation, filters)), list];
}

export const REPRESENTATIONS = Object.freeze([["list", "Pasos"], ["map", "◇ Mapa"]]);
const MAP_NOT_APPLICABLE = "Un solo carril de agente y ningún commit compartido: el mapa no agrega relaciones a la lista.";

// Mapa del contexto (§21.3): disposición, controles de ventana y aviso si no es elegible.
function mapSection(state, map, view) {
  if (!map) return null;
  if (!map.map.eligible && !view.force) {
    return panel("Mapa",
      h("p", { class: "empty-note" }, `${MAP_NOT_APPLICABLE} La lista de pasos lo muestra igual.`),
      h("button", { type: "button", class: "ui-button", data: { forceMap: "1" } }, "Ver el mapa igual"));
  }
  const layout = layoutMap(map, { expanded: view.expanded, start: view.start });
  const graphic = renderMap(layout);
  view.layout = layout;
  view.svg = graphic;
  const { first, size, total } = layout.columns;
  const windowControls = total > size
    ? h("div", { class: "map-window" },
      h("button", { type: "button", class: "ui-button", data: { mapWindow: String(Math.max(0, first - size)) }, disabled: first === 0 },
        "← Pasos anteriores"),
      h("span", { class: "empty-note" }, `Columnas ${first + 1}–${Math.min(first + size, total)} de ${total}`),
      h("button", { type: "button", class: "ui-button", data: { mapWindow: String(first + size) }, disabled: first + size >= total },
        "Pasos siguientes →"))
    : null;
  if (state.sel) selectOnMap(graphic, layout, state.sel);
  return panel("Mapa",
    h("ul", { class: "map-legend", "aria-label": "Leyenda del mapa" },
      h("li", {}, "✓ completado · ● en curso · ○ pendiente · ⤼ omitido"),
      h("li", {}, "◇ commit citado; trazo grueso = compartido por varios pasos"),
      h("li", {}, "recuadro punteado = segundo agente en ese carril"),
      h("li", {}, "Na = alineamientos · Nr = runs · ◇n = commits citados por un solo paso")),
    windowControls,
    h("div", { class: "map-wrap" }, graphic),
    layout.moreCommits
      ? h("button", { type: "button", class: "ui-button", data: { stepFilter: "more-commits" }, "aria-pressed": String(view.stepFilter === "more-commits") },
        `+${layout.moreCommits} commits compartidos: ver los pasos que los citan`)
      : null);
}

function contextPage(state, data, map = null, view = null) {
  const { context, steps } = data;
  const mapBlock = state.as === "map" ? mapSection(state, map, view) : null;
  const parent = context.parent
    ? h("p", { class: "work-subtle" }, "Creado desde ",
      navLink(state, { ctx: context.parent.context_id, step: context.parent.step_id }, `el paso #${context.parent.step_id} del contexto #${context.parent.context_id}`))
    : null;
  const citing = map ? citingSteps(map) : new Map();
  const relatedSteps = new Set(state.sel?.startsWith("commit:") ? (citing.get(state.sel) ?? []) : []);
  const filterSteps = view?.stepFilter === "more-commits" && view.layout
    ? new Set(view.layout.moreCommitSteps)
    : null;
  const visibleSteps = filterSteps ? steps.filter((step) => filterSteps.has(`step:${step.id}`)) : steps;
  const list = objectList(visibleSteps, (step) => [
    relatedSteps.has(`step:${step.id}`) ? h("span", { class: "work-related" }, "cita el commit seleccionado") : null,
    h("div", { class: "object-main" },
      // Con el mapa, la lista es su equivalente sincronizado: el número del paso lo selecciona.
      state.as === "map"
        ? h("button", {
          type: "button", class: "cell-button", data: { sel: `step:${step.id}` },
          "aria-pressed": String(state.sel === `step:${step.id}`),
        }, `Paso ${step.idx}`)
        : null,
      navLink(state, { ctx: context.id, step: step.id }, state.as === "map"
        ? (step.title || "Sin título")
        : [h("span", { class: "object-id" }, `Paso ${step.idx}`), step.title || "Sin título"]),
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
  const listNote = filterSteps
    ? h("p", { class: "empty-note" }, "Mostrando solo los pasos que citan commits compartidos sin dibujar. ",
      h("button", { type: "button", class: "ui-button", data: { stepFilter: "" } }, "Ver todos los pasos"))
    : null;
  // §23.2: si el mapa no aplica, su pestaña se muestra deshabilitada con el motivo y la
  // opción de verlo igual. Sin el mapa (la petición falló), la pestaña queda deshabilitada.
  const notApplicable = map ? !map.map.eligible && !view?.force : true;
  const reason = map ? MAP_NOT_APPLICABLE : "El mapa no está disponible ahora.";
  const showingMap = state.as === "map" && !notApplicable;
  const options = [
    REPRESENTATIONS[0],
    [REPRESENTATIONS[1][0], notApplicable ? "◇ Mapa (no aplica)" : REPRESENTATIONS[1][1], { disabled: notApplicable, reason: notApplicable ? reason : null }],
  ];
  const representation = h("div", { class: "work-representation" },
    segmented({ label: "Representación", options, current: showingMap ? "map" : "list", attribute: "as" }),
    map && notApplicable
      ? h("button", { type: "button", class: "ui-button", data: { forceMap: "1" } }, "Ver el mapa igual")
      : null);
  return [
    h("nav", { class: "work-back" }, navLink(state, { ctx: null, step: null }, "← Contextos")),
    header(context.status, CONTEXT_STATUS, representation),
    context.description ? h("p", { class: "work-description" }, context.description) : null,
    parent,
    mapBlock,
    listNote,
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
  let lastData = null;
  let lastMap = null;
  // Estado local del mapa: grupos abiertos, ventana de columnas y "ver el mapa igual".
  // Los grupos se expanden (no se seleccionan); `stepFilter` filtra la lista sincronizada.
  const freshMapView = () => ({ expanded: new Set(), start: 0, force: false, stepFilter: null, layout: null, svg: null });
  let mapView = freshMapView();
  // Estado local de la constelación: modo, lente, alcance y profundidad del modo local.
  const consView = { mode: "global", lens: "agent", scope: "active", depth: 1, focus: null, layout: null, svg: null };
  let lastConstellation = null;

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
      // El mapa se pide siempre en la página del contexto: la pestaña dice si aplica (§23.2).
      const wantsMap = page === "context";
      const wantsConstellation = page === "contexts" && current.as === "constellation";
      const [data, map, constellation] = await Promise.all([
        api.get(path, { params, signal: controller.signal }),
        // Si el mapa falla, la lista se muestra igual y la pestaña queda deshabilitada.
        wantsMap ? api.get(`${path}/map`, { signal: controller.signal }).catch((error) => {
          if (controller.signal.aborted) throw error;
          console.warn("No se pudo cargar el mapa del contexto:", error);
          return null;
        }) : Promise.resolve(null),
        // La constelación no impide mostrar la lista si falla.
        wantsConstellation ? api.get(`/api/v1/projects/${current.project}/constellation`, { signal: controller.signal }).catch((error) => {
          if (controller.signal.aborted) throw error;
          console.warn("No se pudo cargar la constelación:", error);
          return null;
        }) : Promise.resolve(null),
      ]);
      if (controller.signal.aborted) return;
      lastData = data;
      lastMap = map;
      lastConstellation = constellation;
      const content = page === "step" ? stepPage(current, data)
        : page === "context" ? contextPage(current, data, map, mapView)
          : contextsPage(current, data, filter, constellation, consView);
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

  // Vuelve a dibujar la lista de contextos con la constelación (modo, lente, alcance, foco).
  function redrawContexts() {
    if (!lastData || pageFor(current) !== "contexts") return;
    root.replaceChildren(...contextsPage(current, lastData, filter, lastConstellation, consView).filter(Boolean));
  }

  // Vuelve a dibujar la página del contexto con los mismos datos (grupos, ventana, forzar).
  function redrawContext() {
    if (!lastData || pageFor(current) !== "context") return;
    root.replaceChildren(...contextPage(current, lastData, lastMap, mapView).filter(Boolean));
  }

  const TARGETS = "[data-nav], [data-sel], [data-filter], [data-as], [data-group], [data-force-map], [data-map-window], "
    + "[data-step-filter], [data-cons-mode], [data-cons-lens], [data-cons-scope], [data-cons-depth]";

  function onClick(event) {
    const target = event.target.closest?.(TARGETS);
    if (!target || !root.contains(target)) return;
    if (target.dataset.as !== undefined) {
      const value = target.dataset.as;
      // Entre Lista y Grafo de contextos la selección se conserva (§23.2); el mapa la limpia.
      const keep = pageFor(current) === "contexts" && Boolean(current.sel);
      store.set({ as: value === "map" || value === "constellation" ? value : null, sel: keep ? current.sel : null });
      return;
    }
    for (const [key, field] of [["consMode", "mode"], ["consLens", "lens"], ["consScope", "scope"], ["consDepth", "depth"]]) {
      if (target.dataset[key] !== undefined) {
        consView[field] = field === "depth" ? Number(target.dataset[key]) || 1 : target.dataset[key];
        redrawContexts();
        return;
      }
    }
    if (target.dataset.group) {
      const id = target.dataset.group;
      if (mapView.expanded.has(id)) mapView.expanded.delete(id);
      else mapView.expanded.add(id);
      redrawContext();
      return;
    }
    if (target.dataset.forceMap !== undefined) {
      mapView.force = true;
      if (current.as === "map") redrawContext();
      else store.set({ as: "map", sel: null });
      return;
    }
    if (target.dataset.stepFilter !== undefined) {
      mapView.stepFilter = target.dataset.stepFilter || null;
      redrawContext();
      return;
    }
    if (target.dataset.mapWindow !== undefined) {
      mapView.start = Number(target.dataset.mapWindow) || 0;
      redrawContext();
      return;
    }
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

  // Teclado en el mapa (§21.6) y la constelación (§22.4): Enter o Espacio activan el nodo; las
  // flechas recorren los pasos y grupos en orden de columna, o los soles en orden de dibujo.
  function onKeyDown(event) {
    const node = event.target.closest?.("[data-node]");
    if (!node || !root.contains(node)) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onClick({ target: node, preventDefault() {} });
      return;
    }
    const inConstellation = Boolean(node.matches?.(".cons-sun"));
    const forward = event.key === "ArrowRight" || (inConstellation && event.key === "ArrowDown");
    const back = event.key === "ArrowLeft" || (inConstellation && event.key === "ArrowUp");
    if (!forward && !back) return;
    const order = [...root.querySelectorAll(inConstellation ? ".cons-sun" : ".map-step, .map-group")];
    const index = order.indexOf(node);
    if (index < 0) return;
    event.preventDefault();
    order[(index + (forward ? 1 : -1) + order.length) % order.length]?.focus();
  }

  root.addEventListener("click", onClick);
  root.addEventListener("keydown", onKeyDown);
  await load();
  return {
    update(next) {
      const previous = current;
      current = next;
      if (next.project !== previous.project || next.ctx !== previous.ctx || next.step !== previous.step) {
        mapView = freshMapView();
        load();
        return;
      }
      if (next.as !== previous.as) {
        if (lastData && pageFor(next) === "context") redrawContext();
        else load();
        return;
      }
      if (next.sel !== previous.sel && pageFor(next) === "contexts" && next.as === "constellation" && lastConstellation) {
        if (!next.sel && previous.sel === consView.focus) consView.focus = null;
        // En modo local la selección es el foco: cambia lo visible y se redibuja.
        if (consView.mode === "local") {
          redrawContexts();
          return;
        }
        if (consView.svg && consView.layout) selectConstellation(consView.svg, consView.layout, next.sel);
      }
      if (next.sel !== previous.sel && pageFor(next) === "context" && lastMap) {
        // La lista resalta los pasos del commit seleccionado; el mapa solo cambia clases.
        if (next.sel?.startsWith("commit:") || previous.sel?.startsWith("commit:")) {
          redrawContext();
          return;
        }
        if (mapView.svg && mapView.layout) selectOnMap(mapView.svg, mapView.layout, next.sel);
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
      root.removeEventListener("keydown", onKeyDown);
      pending?.abort();
    },
  };
}
