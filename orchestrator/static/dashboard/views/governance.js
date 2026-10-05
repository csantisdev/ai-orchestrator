// Vista Gobernanza (spec §19.6, §23.3): ¿qué se denegó o falló, y por qué? Pestañas
// "Acceso MCP" (invocaciones denegadas, con error o en curso) y "Egress". Cada decisión se
// selecciona con `sel=decision:mcp-<id>` o `decision:egress-<id>` y muestra su detalle.
// Contrato de montaje en ../README.md.

import { h } from "../core/dom.js";
import { objectList, statusPill } from "../renderers/list.js";
import { metricCard, metricGrid, panel, segmented } from "../core/ui.js";

export const PERIODS = Object.freeze([["7d", "7 días"], ["30d", "30 días"], ["90d", "90 días"]]);
export const MCP_FILTERS = Object.freeze([
  ["problems", "Denegadas o con error"], ["denied", "Denegadas"], ["error", "Con error"],
  ["in_progress", "En curso"], ["all", "Todas"],
]);
const STATUS = { denied: "Denegada", error: "Con error", success: "Correcta", in_progress: "En curso" };
const EGRESS = { allowed: "Permitida", blocked: "Bloqueada" };
const AGENTS = { claude: "Claude", codex: "Codex", copilot: "Copilot", otros: "Otros", "sin agente": "Sin agente" };
// Qué significa cada motivo y qué hacer (§23.5: los textos de estado dicen qué pasó y qué hacer).
// Códigos de mcp_governance.py, mcp.py (StepTransitionError) y egress.py.
export const REASONS = Object.freeze({
  project_out_of_scope: "El proyecto no está en ORCHESTRATOR_MCP_PROJECTS del cliente MCP. Agregá el alias al bloque env de su configuración y reiniciá el cliente.",
  project_scope_required: "La llamada no identificó un proyecto. Pasá project, context_id o step_id.",
  capability_denied: "El perfil ORCHESTRATOR_MCP_PROFILE del cliente no permite esa herramienta. Configurá un perfil que la incluya (por ejemplo workflow_operator).",
  unknown_tool: "El cliente pidió una herramienta que el servidor no expone.",
  invalid_arguments: "La herramienta rechazó los argumentos de la llamada.",
  request_id_reused: "Se reutilizó un request_id con otros argumentos: es otra operación y necesita otra clave.",
  request_in_progress: "Ya hay una operación en curso con ese request_id.",
  execution_error: "La herramienta falló al ejecutarse. El detalle queda en el log del servidor MCP.",
  step_not_found: "El paso no existe (o es de otro proyecto).",
  step_not_pending: "Solo se puede iniciar un paso pendiente.",
  step_not_in_progress: "Solo se puede avanzar o devolver un paso en curso.",
  context_not_active: "El contexto no está activo: activalo antes de mover sus pasos.",
  context_has_in_progress: "El contexto ya tiene un paso en curso; cerralo o devolvelo a pendiente primero.",
  step_changed_concurrently: "Otro agente cambió el paso al mismo tiempo. Volvé a leerlo y reintentá.",
  provider_blocked: "El proveedor está en blocked_providers del contexto del proyecto. Usá otro proveedor o sacalo de esa lista si el bloqueo ya no corresponde.",
  not_in_allowlist: "El proyecto define allowed_providers y este proveedor no está. Usá uno de la lista o agregalo si corresponde.",
  unknown_clearance: "La clearance del proveedor en config.yaml no es un nivel conocido. Corregila (por ejemplo internal o restricted).",
  clearance_insufficient: "La clearance del proveedor es menor que la sensitivity del proyecto. Usá un proveedor con clearance suficiente o revisá la sensibilidad declarada.",
  secret_pattern_detected: "El contenido tenía un patrón de secreto y no se envió. Sacá el secreto del contexto (y rotalo si llegó a escribirse) antes de reintentar.",
});
const UNKNOWN_REASON = "Motivo sin descripción en el dashboard: buscalo en el código del servidor o en el log.";
const PATH_SEGMENT = /^[A-Za-z0-9_~-][A-Za-z0-9._~-]*$/;
const STYLE_KEY = "governance";

export function tabFor(state) {
  return state.tab === "egress" ? "egress" : "acceso";
}

export function endpoints(project) {
  if (!project || !PATH_SEGMENT.test(project)) return null;
  const base = `/api/v1/projects/${project}`;
  return { summary: `${base}/governance/summary`, mcp: `${base}/mcp-invocations`, egress: `${base}/egress-decisions` };
}

export function reasonText(code) {
  if (!code || code === "allowed") return null;
  return REASONS[code] ?? UNKNOWN_REASON;
}

// Estado visible: una invocación `success` marcada con `is_error` es un fallo.
export function displayStatus(item) {
  return item.is_error && item.status === "success" ? "error" : item.status;
}

export function agentLabel(agent) {
  return AGENTS[agent] ?? agent ?? "—";
}

export function formatInstant(iso, { timeZone } = {}) {
  if (!iso) return "fecha ilegible";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "fecha ilegible";
  return new Intl.DateTimeFormat("es-CL", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone,
  }).format(date);
}

function ensureStylesheet(doc) {
  if (doc.head.querySelector(`link[data-view-css="${STYLE_KEY}"]`)) return;
  doc.head.append(h("link", {
    rel: "stylesheet", href: new URL("./governance.css", import.meta.url).href, data: { viewCss: STYLE_KEY },
  }));
}

function ranking(title, items, label = (key) => key) {
  return panel(title, items.length
    ? h("ol", { class: "gov-ranking" }, items.map((item) => h("li", {},
      h("span", {}, label(item.key)), h("span", { class: "gov-count" }, String(item.count)))))
    : h("p", { class: "empty-note" }, "Nada en el período."));
}

function summaryBlock(summary, tab) {
  if (tab === "egress") {
    const egress = summary.egress;
    return h("div", { class: "gov-summary" },
      metricGrid([
        metricCard({ family: "governance", label: "Decisiones", value: String(egress.total) }),
        metricCard({ family: "error", label: "Bloqueadas", value: String(egress.blocked), tone: egress.blocked ? "warn" : null }),
      ]),
      ranking("Motivos de bloqueo", egress.by_reason));
  }
  const mcp = summary.mcp;
  return h("div", { class: "gov-summary" },
    metricGrid([
      metricCard({ family: "governance", label: "Denegadas", value: String(mcp.denied), tone: mcp.denied ? "gov" : null,
        sub: `de ${mcp.invocations} invocaciones` }),
      metricCard({ family: "error", label: "Con error", value: String(mcp.error), sub: "sin contar denegadas" }),
      metricCard({ family: "decision", label: "En curso", value: String(mcp.in_progress), tone: mcp.in_progress ? "warn" : null,
        sub: "mutaciones sin cerrar" }),
    ]),
    h("div", { class: "gov-rankings" },
      ranking("Por motivo", mcp.by_reason),
      ranking("Por herramienta", mcp.by_tool),
      ranking("Por agente", mcp.by_agent, agentLabel)));
}

function detail(entries) {
  return h("dl", { class: "gov-detail" }, entries.filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([term, value]) => [h("dt", {}, term), h("dd", {}, String(value))]));
}

function mcpRow(item, selected) {
  const isSelected = item.sel === selected;
  const reason = item.reason_code || item.error_code;
  return [
    h("button", {
      type: "button", class: ["gov-row", isSelected && "is-selected"], data: { sel: item.sel },
      "aria-pressed": String(isSelected), "aria-expanded": String(isSelected),
    },
    h("span", { class: "gov-row-main" },
      h("span", { class: "gov-tool" }, item.tool_name || "—"),
      statusPill(displayStatus(item), STATUS),
      reason ? h("code", { class: "gov-reason" }, reason) : null),
    h("span", { class: "gov-row-meta" },
      h("span", {}, agentLabel(item.agent)),
      h("time", { datetime: item.ts ?? undefined }, formatInstant(item.ts)))),
    isSelected ? h("div", { class: "gov-expanded" },
      reasonText(reason) ? h("p", { class: "gov-hint" }, reasonText(reason)) : null,
      detail([
        ["Invocación", `#${item.id}`], ["Estado registrado", item.is_error ? `${item.status} (con error)` : item.status],
        ["Cliente", item.client_surface], ["Transporte", item.transport],
        ["Perfil", item.capability_profile], ["Categoría", item.tool_category], ["Motivo", item.reason_code],
        ["Código de error", item.error_code], ["Duración", item.duration_ms === null ? null : `${item.duration_ms} ms`],
        ["Clave de la petición", item.request_source === "client" ? "del cliente (reintento seguro)" : "generada"],
      ])) : null,
  ];
}

function egressRow(item, selected) {
  const isSelected = item.sel === selected;
  return [
    h("button", {
      type: "button", class: ["gov-row", isSelected && "is-selected"], data: { sel: item.sel },
      "aria-pressed": String(isSelected), "aria-expanded": String(isSelected),
    },
    h("span", { class: "gov-row-main" },
      h("span", { class: "gov-tool" }, item.provider || "—"),
      statusPill(item.decision, EGRESS),
      h("code", { class: "gov-reason" }, item.reason_code || "—")),
    h("span", { class: "gov-row-meta" },
      h("span", {}, item.phase),
      h("time", { datetime: item.ts ?? undefined }, formatInstant(item.ts)))),
    isSelected ? h("div", { class: "gov-expanded" },
      reasonText(item.reason_code) ? h("p", { class: "gov-hint" }, reasonText(item.reason_code)) : null,
      detail([
        ["Decisión", `#${item.id}`], ["Fase", item.phase], ["Sensibilidad", item.sensitivity],
        ["Habilitación", item.clearance], ["Run", item.run_id === null ? null : `#${item.run_id}`],
      ])) : null,
  ];
}

function message(title, body) {
  return h("section", { class: "shell-empty" }, h("h2", {}, title), body ? h("p", {}, body) : null);
}

export async function mount(root, { api, state, signal, store }) {
  ensureStylesheet(root.ownerDocument);
  root.classList.add("gov-view");
  const tab = tabFor(state);
  let current = state;
  let period = "30d";
  let filter = "problems";
  let summary = null;
  let items = [];
  let nextCursor = null;
  let appended = false;
  let pending = null;
  let failure = null;

  const summarySlot = h("div", { class: "gov-summary-slot" });
  const listSlot = h("div", { class: "gov-list-slot" });

  function renderList() {
    const rows = tab === "egress"
      ? objectList(items, (item) => egressRow(item, current.sel), {
        label: "Decisiones de egress",
        empty: "Sin decisiones de egress: los runs importados (sesiones y commits) no pasan por el gate. Aparecen cuando un run pasa por el router.",
      })
      : objectList(items, (item) => mcpRow(item, current.sel), {
        label: "Invocaciones MCP",
        empty: filter === "problems" ? "Ninguna invocación denegada ni con error." : "Ninguna invocación con ese filtro.",
      });
    // `replaceChildren` escribe `null` como texto: solo nodos.
    listSlot.replaceChildren(...[
      failure ? message("No se pudo cargar la lista", failure) : rows,
      nextCursor ? h("button", { type: "button", class: "ui-button", data: { more: "1" } }, "Cargar más") : null,
    ].filter(Boolean));
  }

  function render() {
    const controls = [segmented({ label: "Período", options: PERIODS, current: period, attribute: "period" })];
    if (tab === "acceso") controls.push(segmented({ label: "Estado", options: MCP_FILTERS, current: filter, attribute: "filter" }));
    root.replaceChildren(
      h("header", { class: "gov-header" },
        h("p", { class: "gov-muted" }, tab === "egress"
          ? "Decisiones del gate de egress antes de enviar contexto a un proveedor."
          : "Llamadas de los agentes al servidor MCP que la política denegó o que fallaron."),
        controls),
      summarySlot, listSlot);
  }

  async function request(work, { quiet = false } = {}) {
    pending?.abort();
    const controller = new AbortController();
    pending = controller;
    const abort = () => controller.abort();
    signal.addEventListener("abort", abort, { once: true });
    try {
      await work(controller.signal);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (quiet) return console.warn("No se pudo refrescar Gobernanza:", error);
      const reload = error?.reason === "session_expired" ? " El servidor se reinició: recargá la página." : "";
      failure = `${error?.message ?? error}.${reload}`;
      renderList();
    } finally {
      signal.removeEventListener("abort", abort);
      if (pending === controller) pending = null;
    }
  }

  async function load({ append = false, quiet = false } = {}) {
    const paths = endpoints(current.project);
    if (!paths) {
      root.replaceChildren(current.project
        ? message("Este proyecto no se puede consultar desde la vista nueva", "Su alias tiene caracteres que la API no acepta en la ruta.")
        : message("Elegí un proyecto", "Gobernanza muestra las decisiones de un proyecto: elegilo en el selector de arriba."));
      return;
    }
    if (!append && !quiet) {
      render();
      listSlot.replaceChildren(h("p", { class: "gov-muted", role: "status" }, "Cargando…"));
    }
    await request(async (requestSignal) => {
      const listPath = tab === "egress" ? paths.egress : paths.mcp;
      const params = { cursor: append ? nextCursor : null, status: tab === "egress" ? null : filter };
      const [page, summaryData] = await Promise.all([
        api.get(listPath, { params, signal: requestSignal }),
        append ? Promise.resolve(summary) : api.get(paths.summary, { params: { period }, signal: requestSignal }),
      ]);
      if (requestSignal.aborted) return;
      failure = null;
      summary = summaryData;
      items = append ? [...items, ...page.items] : page.items;
      appended = append;
      nextCursor = page.next_cursor;
      summarySlot.replaceChildren(summaryBlock(summary, tab));
      renderList();
    }, { quiet });
  }

  function onClick(event) {
    const target = event.target.closest?.("[data-sel], [data-period], [data-filter], [data-more]");
    if (!target || !root.contains(target)) return;
    if (target.dataset.sel) {
      store.set({ sel: current.sel === target.dataset.sel ? null : target.dataset.sel });
    } else if (target.dataset.period) {
      period = target.dataset.period;
      load();
    } else if (target.dataset.filter) {
      filter = target.dataset.filter;
      load();
    } else if (target.dataset.more) {
      load({ append: true });
    }
  }

  root.addEventListener("click", onClick);
  await load();
  return {
    // `refresh` (db_changed, §19.4 O5): recarga sin aviso de carga y sin pisar lo visible si falla.
    // Con más de una página cargada no se refresca: se perdería lo que la persona ya pidió.
    refresh: () => (appended ? undefined : load({ quiet: true })),
    update(next) {
      const previous = current;
      current = next;
      if (next.project !== previous.project) {
        load();
      } else if (next.sel !== previous.sel && summary) {
        renderList();
      }
    },
    unmount() {
      root.removeEventListener("click", onClick);
      pending?.abort();
    },
  };
}
