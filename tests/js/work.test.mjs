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

import { mount } from "../../orchestrator/static/dashboard/views/work.js";

function fakeRoot() {
  const doc = { createElement: (tag) => new FakeNode(doc, tag), createTextNode: (text) => ({ nodeType: 3, text }),
    head: { querySelector: () => ({}), append() {} } };
  const root = new FakeNode(doc, "div");
  root.classList = { add() {} };
  root.listeners = 0;
  root.addEventListener = () => { root.listeners += 1; };
  root.removeEventListener = () => { root.listeners -= 1; };
  root.replaceChildren = (...children) => { root.childNodes = children; };
  root.querySelectorAll = () => [];
  return root;
}

function countingSignal() {
  const controller = new AbortController();
  let active = 0;
  const add = controller.signal.addEventListener.bind(controller.signal);
  const remove = controller.signal.removeEventListener.bind(controller.signal);
  controller.signal.addEventListener = (...args) => { active += 1; add(...args); };
  controller.signal.removeEventListener = (...args) => { active -= 1; remove(...args); };
  return { controller, active: () => active };
}

test("mount no deja listeners en el signal y una carga superada no dibuja", async () => {
  const doc = fakeRoot().ownerDocument;
  h.document = doc;
  try {
    const root = fakeRoot();
    const { controller, active } = countingSignal();
    const calls = [];
    const gates = [];
    const api = {
      get: (path, { signal }) => new Promise((resolve, reject) => {
        calls.push(path);
        gates.push(() => resolve(path.endsWith("/map")
          ? { nodes: [], edges: [], metadata: {}, map: { lanes: [], eligible: false, shared: [], placement: {}, groups: [],
            single_commits: {}, more_commits: 0, more_commit_steps: [], hidden_edges: {}, max_columns: 30 } }
          : { contexts: [], context: { id: 21, title: "C", description: "", status: "active", parent: null }, steps: [] }));
        signal.addEventListener("abort", () => reject(new DOMException("abortado", "AbortError")));
      }),
    };
    const store = { set() {} };
    const titles = [];
    const page = { set: (value) => titles.push(value) };
    const first = mount(root, { api, store, page, state: { ...BASE, project: null }, signal: controller.signal });
    const handle = await first;
    assert.equal(active(), 0);
    assert.equal(calls.length, 0);
    handle.update({ ...BASE });
    handle.update({ ...BASE, ctx: 21 });
    // La página del contexto pide también el mapa, para saber si la pestaña aplica.
    assert.deepEqual(calls, ["/api/v1/projects/mi-proyecto/contexts", "/api/v1/projects/mi-proyecto/contexts/21",
      "/api/v1/projects/mi-proyecto/contexts/21/map"]);
    gates[1]();
    gates[2]();
    await new Promise((r) => setImmediate(r));
    assert.equal(active(), 0);
    assert.match(root.textContent, /El contexto no tiene pasos/);
    assert.deepEqual(titles.at(-1), { title: "Contexto #21 · C", subtitle: "0 de 0 pasos completados" });
    handle.update({ ...BASE, project: null });
    assert.equal(active(), 0);
    handle.unmount();
    assert.equal(root.listeners, 0);
  } finally {
    delete h.document;
  }
});

import { pageTitle } from "../../orchestrator/static/dashboard/views/work.js";

test("pageTitle: el encabezado nombra el objeto de cada página", () => {
  assert.deepEqual(pageTitle("contexts", { contexts: [{ status: "active" }, { status: "completed" }] }),
    { title: "Trabajo", subtitle: "2 contextos · 1 activo" });
  assert.deepEqual(pageTitle("context", {
    context: { id: 21, title: "Migrar" }, steps: [{ status: "completed" }, { status: "pending" }],
  }), { title: "Contexto #21 · Migrar", subtitle: "1 de 2 pasos completados" });
  assert.deepEqual(pageTitle("step", {
    step: { idx: 3, title: "" }, navigation: { total: 5 }, context: { id: 21, title: "Migrar" },
  }), { title: "Paso 3 de 5 · Sin título", subtitle: "Contexto #21 · Migrar" });
});


test("contexto con mapa: pestaña 'no aplica', lista resaltada por commit y filtro de compartidos sin dibujar", async () => {
  const doc = fakeRoot().ownerDocument;
  h.document = doc;
  try {
    const sha = "a".repeat(8) + "0123456789abcdef".repeat(2);
    const context = { id: 21, title: "C", description: "", status: "active", parent: null };
    const stepRow = (id, idx) => ({ id, idx, title: `P${idx}`, status: "completed", provider: "claude", lane: "claude", secondary: [],
      started_at: null, completed_at: null, has_notes: true, alignments: 0, deviations: 0, tool_calls: 0, runs: 0, cost_usd: 0,
      verified_commits: 0, prs: [], children: [] });
    const steps = [stepRow(1, 1), stepRow(2, 2), stepRow(3, 3)];
    let eligible = false;
    const mapDto = () => ({
      nodes: [], metadata: {},
      edges: [{ source: "step:1", target: `commit:${sha}`, relation_type: "cites" }, { source: "step:3", target: `commit:${sha}`, relation_type: "cites" }],
      map: { lanes: ["claude"], eligible, shared: [], placement: {}, groups: [], single_commits: {}, more_commits: 1,
        more_commit_steps: ["step:2"], hidden_edges: {}, max_columns: 30 },
    });
    const api = { get: async (path) => (path.endsWith("/map") ? mapDto() : { context, steps }) };
    const root = fakeRoot();
    const listeners = [];
    root.addEventListener = (_, handler) => { root.listeners += 1; listeners.push(handler); };
    const click = (target) => listeners.forEach((handler) => handler({ target: { closest: () => target }, preventDefault() {} }));
    const contains = root.contains;
    root.contains = () => true;
    const state = { ...BASE, ctx: 21 };
    const handle = await mount(root, { api, store: { set() {} }, state, signal: new AbortController().signal });
    assert.match(root.textContent, /◇ Mapa \(no aplica\)/);
    eligible = true;
    handle.update({ ...state, as: "map" });
    await new Promise((r) => setImmediate(r));
    handle.update({ ...state, as: "map", sel: `commit:${sha}` });
    assert.equal((root.textContent.match(/cita el commit seleccionado/g) ?? []).length, 2);
    click({ dataset: { stepFilter: "more-commits" } });
    assert.match(root.textContent, /Mostrando solo los pasos que citan commits compartidos sin dibujar/);
    assert.doesNotMatch(root.textContent, /P1|P3/);
    assert.match(root.textContent, /P2/);
    click({ dataset: { stepFilter: "" } });
    assert.match(root.textContent, /P1/);
    root.contains = contains;
  } finally {
    delete h.document;
  }
});
