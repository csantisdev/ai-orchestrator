import { test } from "node:test";
import assert from "node:assert/strict";

import { h } from "../../orchestrator/static/dashboard/core/dom.js";
import { objectList, stateClass, statusPill, facts } from "../../orchestrator/static/dashboard/renderers/list.js";
import { renderTrace } from "../../orchestrator/static/dashboard/renderers/trace.js";
import {
  CONTEXT_STATUS, STEP_STATUS, agentLabel, endpointFor, formatInstant, formatUsd, hrefFor, pageFor, progressText,
} from "../../orchestrator/static/dashboard/views/work.js";

class FakeNode {
  constructor(doc, tag) {
    this.ownerDocument = doc;
    this.tagName = tag;
    this.attributes = {};
    this.dataset = {};
    this.className = "";
    this.childNodes = [];
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  appendChild(child) { this.childNodes.push(child); return child; }
  get textContent() { return this.childNodes.map((c) => (c.nodeType === 3 ? c.text : c.textContent)).join(""); }
}

function withDocument(fn) {
  const doc = { createElement: (tag) => new FakeNode(doc, tag), createTextNode: (text) => ({ nodeType: 3, text }) };
  h.document = doc;
  try {
    return fn();
  } finally {
    delete h.document;
  }
}

function findAll(node, predicate, found = []) {
  if (node && node.nodeType !== 3) {
    if (predicate(node)) found.push(node);
    for (const child of node.childNodes ?? []) findAll(child, predicate, found);
  }
  return found;
}

const BASE = { project: "mi-proyecto", view: "trabajo", tab: null, ctx: null, step: null, as: null, sel: null };

test("pageFor sigue la URL: proyecto, contexto y paso", () => {
  assert.equal(pageFor({ ...BASE, project: null }), "no-project");
  assert.equal(pageFor(BASE), "contexts");
  assert.equal(pageFor({ ...BASE, ctx: 21 }), "context");
  assert.equal(pageFor({ ...BASE, ctx: 21, step: 12 }), "step");
  assert.equal(pageFor({ ...BASE, step: 12 }), "step");
});

test("endpointFor arma la ruta de la API o devuelve null si el alias no cabe en ella", () => {
  assert.equal(endpointFor(BASE), "/api/v1/projects/mi-proyecto/contexts");
  assert.equal(endpointFor({ ...BASE, ctx: 21 }), "/api/v1/projects/mi-proyecto/contexts/21");
  assert.equal(endpointFor({ ...BASE, ctx: 21, step: 12 }), "/api/v1/projects/mi-proyecto/steps/12/trace");
  for (const project of ["mi proyecto", "a/b", ".oculto", "ñandú", "x%2e", null]) {
    assert.equal(endpointFor({ ...BASE, project }), null, String(project));
  }
});

test("hrefFor conserva el proyecto, fija la vista y limpia la selección", () => {
  const state = { ...BASE, tab: "contextos", sel: "run:4" };
  assert.equal(hrefFor(state, { ctx: 21, step: null }), "?project=mi-proyecto&view=trabajo&tab=contextos&ctx=21");
  assert.equal(hrefFor({ ...state, ctx: 21 }, { ctx: 21, step: 12 }),
    "?project=mi-proyecto&view=trabajo&tab=contextos&ctx=21&step=12");
  assert.equal(hrefFor({ ...state, project: "a&b=c" }, { ctx: null, step: null }), "?project=a%26b%3Dc&view=trabajo&tab=contextos");
});

test("formatos de fecha, costo, agente y progreso", () => {
  assert.equal(formatInstant(null), "—");
  assert.equal(formatInstant("no es fecha"), "—");
  assert.match(formatInstant("2026-05-10T15:30:00+00:00", { timeZone: "UTC" }), /10.*may.*2026.*15:30/);
  assert.equal(formatUsd(null), null);
  assert.match(formatUsd(0.5), /0,50/);
  assert.match(formatUsd(0.0012), /0,0012/);
  assert.equal(agentLabel("codex"), "Codex");
  assert.equal(agentLabel("sin agente"), "Sin agente");
  assert.equal(progressText({ total: 0 }), "Sin pasos");
  assert.equal(progressText({ total: 5, completed: 2, in_progress: 1, blocked: 0 }), "2/5 completados · 1 en curso");
  assert.equal(CONTEXT_STATUS.programado, "Programado");
  assert.equal(STEP_STATUS.in_progress, "En curso");
});

test("stateClass acepta solo tokens de estado", () => {
  assert.equal(stateClass("in_progress"), "state-in-progress");
  assert.equal(stateClass("active"), "state-active");
  for (const bad of ["x y", "<b>", "", null, "Active", "a".repeat(40)]) assert.equal(stateClass(bad), "state-other", String(bad));
});

test("listas, píldoras y hechos se arman como texto", () => withDocument(() => {
  assert.equal(objectList([], () => "x", { label: "L", empty: "Vacío" }).textContent, "Vacío");
  const list = objectList([{ t: "<b>uno</b>" }], (item) => item.t, { label: "L", empty: "" });
  assert.equal(list.tagName, "ul");
  assert.equal(list.attributes["aria-label"], "L");
  assert.equal(list.textContent, "<b>uno</b>");
  const pill = statusPill("<raro>", CONTEXT_STATUS);
  assert.equal(pill.textContent, "<raro>");
  assert.equal(pill.className, "pill state-other");
  assert.equal(facts([[0, "a", "as"]]), null);
  assert.equal(facts([[1, "desvío", "desvíos"], [2, "run", "runs"], [0, "x", "xs"]]).textContent, "1 desvío2 runs");
}));

const SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678";
const TRACE = {
  project: "mi-proyecto",
  context: { id: 21, title: "Contexto", status: "active" },
  step: { id: 12, idx: 1, title: "Paso", description: "", status: "completed", provider: "claude",
    started_at: null, completed_at: null, notes: "<img src=x onerror=alert(1)> hecho" },
  navigation: { previous: null, next: 13, total: 3 },
  references: {
    commits: [{ sha: SHA, run_id: 7, project: "mi-proyecto", ts: null, subject: "feat: <x>" }],
    unverified_shas: ["abc1234"], prs: [12], mentions_tests: true,
  },
  alignments: [{ id: 1, ts: null, agent: "codex", confirmed: false, checkpoint: "desvío", message: "msg" }],
  tool_calls: [{ id: 2, ts: null, tool_name: "pytest", status: "ok", duration_ms: 1500 }],
  runs: [{ id: 9, ts: null, provider: "claude", model: "opus", status: "done", cost_usd: 0.5, imported: true, routing_source: null }],
};

test("renderTrace muestra la evidencia como texto y los objetos como chips seleccionables", () => withDocument(() => {
  const helpers = { formatInstant: () => "—", formatUsd, agentLabel, selected: `run:9` };
  const trace = renderTrace(TRACE, helpers);
  const text = trace.textContent;
  assert.match(text, /<img src=x onerror=alert\(1\)> hecho/);
  assert.match(text, /referencia verificada/);
  assert.match(text, /abc1234sin commit importado/);
  assert.match(text, /PR #12sin verificar/);
  assert.match(text, /Las notas mencionan tests/);
  assert.match(text, /Desvío/);
  assert.match(text, /1\.5 s/);
  assert.match(text, /importado/);
  const chips = findAll(trace, (node) => node.dataset?.sel);
  assert.deepEqual(chips.map((chip) => chip.dataset.sel), [`commit:${SHA}`, "run:9"]);
  assert.deepEqual(chips.map((chip) => chip.attributes["aria-pressed"]), ["false", "true"]);
  assert.equal(findAll(trace, (node) => Object.keys(node.attributes ?? {}).some((name) => name.startsWith("on"))).length, 0);
}));

test("renderTrace explica las secciones vacías", () => withDocument(() => {
  const empty = {
    ...TRACE,
    step: { ...TRACE.step, notes: "  " },
    references: { commits: [], unverified_shas: [], prs: [], mentions_tests: false },
    alignments: [], tool_calls: [], runs: [],
  };
  const text = renderTrace(empty, { formatInstant: () => "—", formatUsd, agentLabel, selected: null }).textContent;
  for (const expected of ["El paso no tiene notas.", "Las notas no citan commits ni PRs.", "Sin alineamientos registrados.",
    "Sin tool calls registrados.", "Ningún run vinculado a este paso.", "Las invocaciones MCP no se asocian a un paso"]) {
    assert.ok(text.includes(expected), expected);
  }
}));
