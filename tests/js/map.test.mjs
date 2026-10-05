import { test } from "node:test";
import assert from "node:assert/strict";

import { h, svg } from "../../orchestrator/static/dashboard/core/dom.js";
import { LAYOUT, layoutMap, relatedTo, renderMap, select } from "../../orchestrator/static/dashboard/renderers/map.js";

const SHA_A = "a".repeat(8) + "0123456789abcdef".repeat(2);
const SHA_B = "b".repeat(8) + "0123456789abcdef".repeat(2);

function step(id, idx, lane, state = "completed", extra = {}) {
  return {
    id: `step:${id}`, kind: "step", label: `Paso ${idx}`, state,
    attrs: { idx, order_idx: idx, lane, secondary: [], alignments: 0, deviations: 0, runs: 0, cost_usd: 0, prs: [],
      unverified_shas: 0, mentions_tests: false, ...extra },
  };
}

function dto({ steps, commits = [], cites = [], map = {} }) {
  return {
    nodes: [{ id: "context:1", kind: "context", label: "Contexto 1", state: "active" }, ...steps,
      ...commits.map((sha) => ({ id: `commit:${sha}`, kind: "commit", label: sha.slice(0, 7) }))],
    edges: cites.map(([source, target]) => ({ source, target, relation_type: "cites", origin: "verified_reference",
      confidence: 1, evidence_ref: "steps.notes" })),
    metadata: { project: "mi-proyecto", context_id: 1, generated_at: "2026-06-01T00:00:00+00:00" },
    map: { lanes: ["claude", "codex"], eligible: true, shared: [], placement: {}, groups: [], single_commits: {},
      more_commits: 0, hidden_edges: {}, max_columns: 30, ...map },
  };
}

test("layoutMap: x por orden, y por carril y commits bajo su primer paso", () => {
  const data = dto({
    steps: [step(10, 1, "claude"), step(11, 2, "codex", "in_progress", { secondary: ["claude"] }), step(12, 3, "claude", "completed", { secondary: ["copilot"] })],
    commits: [SHA_A, SHA_B],
    cites: [["step:10", `commit:${SHA_A}`], ["step:12", `commit:${SHA_A}`], ["step:11", `commit:${SHA_B}`]],
    map: {
      shared: [`commit:${SHA_A}`],
      placement: { [`commit:${SHA_A}`]: { column: 1, stack: 0 }, [`commit:${SHA_B}`]: { column: 2, stack: 0 } },
    },
  });
  const layout = layoutMap(data);
  const [first, second, third] = layout.nodes;
  assert.deepEqual([first.x, second.x, third.x], [LAYOUT.laneLabel, LAYOUT.laneLabel + LAYOUT.column, LAYOUT.laneLabel + 2 * LAYOUT.column]);
  assert.equal(first.y, layout.lanes[0].y);
  assert.equal(second.y, layout.lanes[1].y);
  // Segundo agente: fantasma si su carril existe; inicial si no.
  assert.deepEqual(second.ghosts.map((ghost) => ghost.agent), ["claude"]);
  assert.deepEqual(third.badges, ["C"]);
  assert.equal(layout.commits.find((c) => c.id === `commit:${SHA_A}`).x, first.x + LAYOUT.nodeWidth / 2);
  assert.equal(layout.edges.length, 3);
  // Las aristas bajan al canal bajo los carriles, sin cruzar nodos.
  for (const edge of layout.edges) assert.match(edge.d, new RegExp(`V ${layout.channel} H`));
  assert.equal(layout.edges.filter((edge) => edge.shared).length, 2);
});

test("grupos cerrados ocupan una columna y se abren en el cliente", () => {
  const steps = [1, 2, 3, 4].map((n) => step(n, n, "claude"));
  const group = { id: "group:1-3", from_idx: 1, to_idx: 3, count: 3, members: ["step:1", "step:2", "step:3"], lane: "claude", lanes: { claude: 3 } };
  const data = dto({ steps, map: { lanes: ["claude"], groups: [group] } });
  const closed = layoutMap(data);
  assert.deepEqual(closed.nodes.map((node) => node.kind), ["group", "step"]);
  assert.equal(closed.nodes[0].sub, "Claude 3");
  const open = layoutMap(data, { expanded: new Set(["group:1-3"]) });
  assert.deepEqual(open.nodes.map((node) => node.id), ["step:1", "step:2", "step:3", "step:4"]);
});

test("ventana de columnas: solo dibuja las del rango y lo informa", () => {
  const steps = [1, 2, 3, 4, 5].map((n) => step(n, n, "claude"));
  const layout = layoutMap(dto({ steps, map: { lanes: ["claude"], max_columns: 2 } }), { start: 2 });
  assert.deepEqual(layout.nodes.map((node) => node.idx), [3, 4]);
  assert.deepEqual(layout.columns, { first: 2, size: 2, total: 5 });
  const clamped = layoutMap(dto({ steps, map: { lanes: ["claude"], max_columns: 2 } }), { start: 99 });
  assert.deepEqual(clamped.nodes.map((node) => node.idx), [4, 5]);
});

test("relatedTo: un paso trae sus commits y los otros pasos que los citan", () => {
  const data = dto({
    steps: [step(1, 1, "claude"), step(2, 2, "codex"), step(3, 3, "claude")],
    commits: [SHA_A],
    cites: [["step:1", `commit:${SHA_A}`], ["step:2", `commit:${SHA_A}`]],
    map: { shared: [`commit:${SHA_A}`], placement: { [`commit:${SHA_A}`]: { column: 1, stack: 0 } } },
  });
  const layout = layoutMap(data);
  assert.deepEqual([...relatedTo(layout, "step:1")].sort(), ["commit:" + SHA_A, "step:1", "step:2"].sort());
  assert.equal(relatedTo(layout, "step:3").size, 1);
  assert.equal(relatedTo(layout, null), null);
});

class SvgNode {
  constructor(doc, tag, ns = null) {
    Object.assign(this, { ownerDocument: doc, tagName: tag, namespaceURI: ns, attributes: {}, childNodes: [] });
    this.classes = new Set();
    this.classList = { toggle: (name, on) => (on ? this.classes.add(name) : this.classes.delete(name)) };
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  appendChild(child) { this.childNodes.push(child); return child; }
  get textContent() { return this.childNodes.map((c) => (c.nodeType === 3 ? c.text : c.textContent)).join(""); }
  querySelectorAll() {
    const found = [];
    const walk = (node) => {
      if (!node || node.nodeType === 3) return;
      if (node !== this && ("data-node" in node.attributes || "data-from" in node.attributes || "data-owner" in node.attributes)) found.push(node);
      node.childNodes.forEach(walk);
    };
    walk(this);
    return found;
  }
}

function withSvgDoc(fn) {
  const doc = {
    createElement: (tag) => new SvgNode(doc, tag),
    createElementNS: (ns, tag) => new SvgNode(doc, tag, ns),
    createTextNode: (text) => ({ nodeType: 3, text }),
  };
  h.document = doc;
  try { return fn(); } finally { delete h.document; }
}

test("svg(): espacio de nombres SVG, clases y data-* como atributos, sin handlers ni style", () => withSvgDoc(() => {
  const node = svg("g", { class: ["map-node", null, "is-x"], data: { sel: "step:1", fromStep: 2 }, tabindex: 0 }, "Paso 1");
  assert.equal(node.namespaceURI, "http://www.w3.org/2000/svg");
  assert.equal(node.attributes.class, "map-node is-x");
  assert.equal(node.attributes["data-sel"], "step:1");
  assert.equal(node.attributes["data-from-step"], "2");
  assert.equal(node.textContent, "Paso 1");
  for (const props of [{ onclick: "x" }, { style: "fill:red" }, { data: { "bad-key": 1 } }, { href: "javascript:x" }]) {
    assert.throws(() => svg("a", props), TypeError, JSON.stringify(props));
  }
}));

test("renderMap y select: nodos enfocables con nombre accesible y atenuado por clases", () => withSvgDoc(() => {
  const data = dto({
    steps: [step(1, 1, "claude", "completed", { alignments: 2, deviations: 1 }), step(2, 2, "codex"), step(3, 3, "claude")],
    commits: [SHA_A],
    cites: [["step:1", `commit:${SHA_A}`], ["step:2", `commit:${SHA_A}`]],
    map: { shared: [`commit:${SHA_A}`], placement: { [`commit:${SHA_A}`]: { column: 1, stack: 0 } } },
  });
  const layout = layoutMap(data);
  const root = renderMap(layout);
  assert.equal(root.attributes.role, "group");
  const nodes = root.querySelectorAll().filter((node) => node.attributes.role === "button");
  assert.equal(nodes.length, 4);
  assert.ok(nodes.every((node) => node.attributes.tabindex === "0" && node.attributes["aria-label"]));
  assert.match(nodes[0].attributes["aria-label"], /Paso 1, completado, carril Claude, 2 alineamientos, 1 desvíos/);
  select(root, layout, "step:3");
  const byId = (id) => root.querySelectorAll().find((node) => node.attributes["data-node"] === id);
  assert.ok(byId("step:3").classes.has("is-selected"));
  assert.ok(byId("step:1").classes.has("is-dim"));
  assert.equal(byId("step:3").attributes["aria-pressed"], "true");
  select(root, layout, "step:1");
  assert.ok(!byId("step:2").classes.has("is-dim"));
  assert.ok(byId("step:3").classes.has("is-dim"));
  select(root, layout, null);
  assert.ok(root.querySelectorAll().every((node) => !node.classes.has("is-dim")));
}));
