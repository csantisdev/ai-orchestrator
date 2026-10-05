// Representación Trace de un paso (spec §6.2): una cadena vertical, de las notas (la
// evidencia principal, §20.2) a los commits y PRs citados, los alineamientos, los tool
// calls y los runs vinculados por FK. Los objetos con panel propio (commit, run) se
// muestran como chips que lo seleccionan en el Inspector (`data-sel`, §23.3).

import { h } from "../core/dom.js";

function section(title, count, body) {
  return h("section", { class: "trace-section" },
    h("h3", { class: "trace-heading" }, title, count === null ? null : h("span", { class: "trace-count" }, String(count))),
    body);
}

function empty(text) {
  return h("p", { class: "trace-empty" }, text);
}

export function selectable(sel, label, extra, selected) {
  return h("button", {
    type: "button",
    class: ["ref-chip", selected === sel && "is-selected"],
    data: { sel },
    "aria-pressed": String(selected === sel),
  }, label, extra ? h("span", { class: "ref-chip-detail" }, extra) : null);
}

function notes(text) {
  return text.trim()
    ? h("p", { class: "trace-notes" }, text)
    : empty("El paso no tiene notas.");
}

function references(refs, { formatInstant, selected }) {
  const items = [];
  for (const commit of refs.commits) {
    const detail = [commit.subject, commit.ts ? formatInstant(commit.ts) : null].filter(Boolean).join(" · ");
    items.push(h("li", { class: "trace-ref is-verified" },
      selectable(`commit:${commit.sha}`, commit.sha.slice(0, 7), detail, selected),
      h("span", { class: "trace-ref-kind" }, "referencia verificada")));
  }
  for (const sha of refs.unverified_shas) {
    items.push(h("li", { class: "trace-ref" }, h("code", {}, sha),
      h("span", { class: "trace-ref-kind" }, "sin commit importado")));
  }
  for (const pr of refs.prs) {
    items.push(h("li", { class: "trace-ref" }, `PR #${pr}`, h("span", { class: "trace-ref-kind" }, "sin verificar")));
  }
  const body = items.length ? h("ul", { class: "trace-list" }, items) : empty("Las notas no citan commits ni PRs.");
  return section("Commits y PRs citados", refs.commits.length + refs.unverified_shas.length + refs.prs.length,
    [body, refs.mentions_tests ? h("p", { class: "trace-hint" }, "Las notas mencionan tests.") : null]);
}

function alignments(list, { formatInstant, agentLabel }) {
  if (!list.length) return section("Alineamientos", 0, empty("Sin alineamientos registrados."));
  return section("Alineamientos", list.length, h("ol", { class: "trace-list" }, list.map((item) =>
    h("li", { class: ["trace-event", !item.confirmed && "is-deviation"] },
      h("span", { class: "trace-event-head" },
        h("span", { class: "trace-event-title" }, item.confirmed ? "Alineado" : "Desvío"),
        item.checkpoint ? h("span", { class: "trace-event-meta" }, item.checkpoint) : null,
        h("span", { class: "trace-event-meta" }, agentLabel(item.agent)),
        h("time", { class: "trace-event-meta", datetime: item.ts ?? undefined }, formatInstant(item.ts))),
      item.message ? h("p", { class: "trace-event-body" }, item.message) : null))));
}

function toolCalls(list, { formatInstant }) {
  if (!list.length) return section("Tool calls", 0, empty("Sin tool calls registrados."));
  return section("Tool calls", list.length, h("ol", { class: "trace-list" }, list.map((item) =>
    h("li", { class: "trace-event" },
      h("span", { class: "trace-event-head" },
        h("span", { class: "trace-event-title" }, item.tool_name || "—"),
        h("span", { class: "trace-event-meta" }, item.status || "—"),
        item.duration_ms === null ? null : h("span", { class: "trace-event-meta" }, `${(item.duration_ms / 1000).toFixed(1)} s`),
        h("time", { class: "trace-event-meta", datetime: item.ts ?? undefined }, formatInstant(item.ts)))))));
}

function runs(list, { formatInstant, formatUsd, selected }) {
  if (!list.length) return section("Runs vinculados", 0, empty("Ningún run vinculado a este paso."));
  return section("Runs vinculados", list.length, h("ul", { class: "trace-chips" }, list.map((run) => {
    const origin = run.imported ? "importado" : (run.routing_source ? `router: ${run.routing_source}` : "sin routing");
    const detail = [[run.provider, run.model].filter(Boolean).join(" / "), formatUsd(run.cost_usd), origin, formatInstant(run.ts)]
      .filter(Boolean).join(" · ");
    return h("li", {}, selectable(`run:${run.id}`, `Run #${run.id}`, detail, selected));
  })));
}

// `helpers`: { formatInstant, formatUsd, agentLabel, selected } (formatos de la vista y `sel`).
export function renderTrace(trace, helpers) {
  return h("div", { class: "trace" },
    section("Notas del paso", null, notes(trace.step.notes)),
    references(trace.references, helpers),
    alignments(trace.alignments, helpers),
    toolCalls(trace.tool_calls, helpers),
    runs(trace.runs, helpers),
    h("p", { class: "trace-hint" },
      "Las invocaciones MCP no se asocian a un paso: se ven en la Activity del proyecto."));
}
