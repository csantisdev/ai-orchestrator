import { test } from "node:test";
import assert from "node:assert/strict";

import { h } from "../../orchestrator/static/dashboard/core/dom.js";
import {
  constellationRelated, layoutConstellation, neighborhood, renderConstellation, selectConstellation, sunRadius,
} from "../../orchestrator/static/dashboard/renderers/constellation.js";
import { mount } from "../../orchestrator/static/dashboard/views/work.js";
import { constellationPreview } from "../../orchestrator/static/dashboard/views/home.js";

const C = (n) => `context:${n}`;

function context(n, state, agent, steps, extra = {}) {
  return { id: C(n), kind: "context", label: `Contexto ${n}`, state,
    attrs: { steps, in_progress: 0, deviations: 0, agent, connected: false, ...extra } };
}

// 1 (activo) ↔ 2 (cerrado) ↔ 3 (cerrado), 1 → portal; 4 aislado y cerrado.
function dto() {
  const bridge = (source, target, weight) => ({ source, target, weight, portal: target.startsWith("portal:"),
    commits: Array.from({ length: weight }, (_, i) => `commit:${String(i).repeat(40)}`) });
  return {
    nodes: [
      context(1, "active", "claude", 2, { connected: true, in_progress: 1 }),
      context(2, "completed", "codex", 1, { connected: true }),
      context(3, "completed", "codex", 0, { connected: true, deviations: 2 }),
      context(4, "completed", "sin agente", 0),
      { id: "step:10", kind: "step", label: "Paso 1", state: "completed", attrs: { context: C(1), lane: "claude" } },
      { id: "step:11", kind: "step", label: "Paso 2", state: "in_progress", attrs: { context: C(1), lane: "codex" } },
      { id: "step:20", kind: "step", label: "Paso 1", state: "completed", attrs: { context: C(2), lane: "codex" } },
      { id: "portal:otro-proyecto", kind: "portal", label: "otro-proyecto", attrs: { commits: 1 } },
    ],
    edges: [],
    metadata: { project: "mi-proyecto", generated_at: "2026-06-01T00:00:00+00:00" },
    constellation: {
      bridges: [bridge(C(1), C(2), 3), bridge(C(1), "portal:otro-proyecto", 1), bridge(C(2), C(3), 1)],
      positions: { [C(1)]: { x: 300, y: 300 }, [C(2)]: { x: 500, y: 300 }, [C(3)]: { x: 700, y: 300 },
        "portal:otro-proyecto": { x: 300, y: 100 }, [C(4)]: { x: 60, y: 660 } },
      isolated: [C(4)], size: { width: 1000, height: 750 }, layout_version: "fr-1",
    },
  };
}

class FakeNode {
  constructor(doc, tag) {
    this.ownerDocument = doc;
    this.tagName = tag;
    this.attributes = {};
    this.dataset = {};
    this.className = "";
    this.childNodes = [];
    this.classes = new Set();
    this.classList = { toggle: (name, on) => (on ? this.classes.add(name) : this.classes.delete(name)), add() {} };
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name] ?? null; }
  appendChild(child) { this.childNodes.push(child); return child; }
  querySelectorAll() {
    const found = [];
    const walk = (item) => {
      if (!item || item.nodeType === 3) return;
      if (item !== this && ("data-node" in item.attributes || "data-from" in item.attributes)) found.push(item);
      item.childNodes.forEach(walk);
    };
    walk(this);
    return found;
  }
  get textContent() { return this.childNodes.map((c) => (c.nodeType === 3 ? c.text : c.textContent)).join(""); }
}

function withDocument(fn) {
  const doc = {
    createElement: (tag) => new FakeNode(doc, tag), createElementNS: (_, tag) => new FakeNode(doc, tag),
    createTextNode: (text) => ({ nodeType: 3, text }), head: { querySelector: () => ({}), append() {} },
  };
  h.document = doc;
  return Promise.resolve().then(() => fn(doc)).finally(() => { delete h.document; });
}

function findAll(node, predicate, found = []) {
  if (node && node.nodeType !== 3) {
    if (predicate(node)) found.push(node);
    for (const child of node.childNodes ?? []) findAll(child, predicate, found);
  }
  return found;
}

test("sunRadius crece con la raíz de los pasos y neighborhood sigue los saltos", () => {
  assert.equal(sunRadius(0), 14);
  assert.equal(sunRadius(4), 22);
  const { bridges } = dto().constellation;
  assert.deepEqual([...neighborhood(bridges, C(1), 1)].sort(), [C(1), C(2), "portal:otro-proyecto"].sort());
  assert.ok(neighborhood(bridges, C(1), 2).has(C(3)));
});

test("layoutConstellation: alcance activo, todos y modo local", () => {
  const active = layoutConstellation(dto());
  assert.deepEqual(active.suns.map((sun) => sun.id), [C(1), C(2)]);
  assert.equal(active.hiddenContexts, 2);
  assert.deepEqual(active.bridges.map((b) => [b.source, b.target]), [[C(1), C(2)], [C(1), "portal:otro-proyecto"]]);
  assert.ok(active.bridges[0].width > active.bridges[1].width);
  assert.equal(active.suns[0].satellites.length, 2);
  assert.equal(active.suns[0].tone, "claude");
  assert.equal(layoutConstellation(dto(), { lens: "project" }).suns[0].tone, "project");
  const all = layoutConstellation(dto(), { scope: "all" });
  assert.equal(all.suns.length, 4);
  assert.ok(all.suns.find((sun) => sun.id === C(4)).isolated);
  const local = layoutConstellation(dto(), { mode: "local", focus: C(3), depth: 1 });
  assert.deepEqual(local.suns.map((sun) => sun.id), [C(2), C(3)]);
  assert.deepEqual(local.portals, []);
  // Sin foco válido el modo local cae al alcance.
  assert.equal(layoutConstellation(dto(), { mode: "local", focus: "context:99" }).suns.length, 2);
});

test("renderConstellation y selectConstellation: foco, etiquetas en español y atenuación", () => withDocument(() => {
  const layout = layoutConstellation(dto(), { scope: "all" });
  assert.deepEqual([...constellationRelated(layout, C(2))].sort(), [C(1), C(2), C(3)].sort());
  const root = renderConstellation(layout);
  const suns = findAll(root, (node) => node.attributes["data-sel"]);
  assert.equal(suns.length, 4);
  assert.equal(String(suns[0].attributes.tabindex), "0");
  assert.match(suns[0].attributes["aria-label"], /Contexto 1, activo, 2 pasos, agente dominante Claude, 1 en curso/);
  selectConstellation(root, layout, C(3));
  const byId = (id) => findAll(root, (node) => node.attributes["data-node"] === id)[0];
  assert.ok(byId(C(3)).classes.has("is-selected"));
  assert.equal(byId(C(3)).attributes["aria-pressed"], "true");
  assert.ok(byId(C(1)).classes.has("is-dim"));
  assert.ok(!byId(C(2)).classes.has("is-dim"));
  selectConstellation(root, layout, null);
  assert.ok(!byId(C(1)).classes.has("is-dim"));
  const preview = renderConstellation(layout, { interactive: false });
  assert.equal(findAll(preview, (node) => "tabindex" in node.attributes).length, 0);
  assert.equal(preview.attributes.role, "img");
}));

test("vista previa de Inicio: enlace al grafo y nada si la constelación falta", () => withDocument(() => {
  assert.equal(constellationPreview("mi-proyecto", null), null);
  const panel = constellationPreview("mi-proyecto", dto());
  const links = findAll(panel, (node) => node.tagName === "a").map((node) => node.attributes.href);
  assert.ok(links.length >= 2);
  assert.ok(links.every((href) => href === "?project=mi-proyecto&view=trabajo&tab=contextos&as=constellation"));
  assert.match(panel.textContent, /2 contextos visibles · 2 puentes/);
}));

test("Trabajo · Grafo: carga la constelación, controles locales, selección y lista equivalente", () => withDocument(async (doc) => {
  const row = (id, title, status) => ({ id, title, status, steps: { total: 0, completed: 0 }, current_step: null, updated_at: null });
  const contexts = { contexts: [row(1, "Uno", "active"), row(2, "Dos", "completed"), row(3, "Tres", "completed"), row(4, "Cuatro", "completed")] };
  const paths = [];
  const api = { get: async (path) => { paths.push(path); return path.endsWith("/constellation") ? dto() : contexts; } };
  const root = new FakeNode(doc, "div");
  const listeners = [];
  root.addEventListener = (_, handler) => listeners.push(handler);
  root.removeEventListener = () => {};
  root.replaceChildren = (...children) => { root.childNodes = children; };
  root.contains = () => true;
  const click = (target) => listeners.forEach((handler) => handler({ target: { closest: () => target }, preventDefault() {} }));
  const sets = [];
  const state = { project: "mi-proyecto", view: "trabajo", tab: "contextos", ctx: null, step: null, as: "constellation", sel: null };
  const handle = await mount(root, { api, store: { set: (patch) => sets.push(patch) }, state, signal: new AbortController().signal });
  assert.ok(paths.includes("/api/v1/projects/mi-proyecto/constellation"));
  assert.match(root.textContent, /Lista equivalente/);
  assert.match(root.textContent, /Uno/);
  assert.match(root.textContent, /Comparte commits con #2 \(3\), otro-proyecto \(otro proyecto\) \(1\)/);
  assert.match(root.textContent, /2 contextos sin actividad/);
  click({ dataset: { consScope: "all" } });
  assert.match(root.textContent, /Cuatro/);
  // Local sin foco pide seleccionar; con foco muestra solo el vecindario.
  click({ dataset: { consMode: "local" } });
  assert.match(root.textContent, /seleccioná un contexto/);
  handle.update({ ...state, sel: C(3) });
  assert.doesNotMatch(root.textContent, /Uno/);
  assert.match(root.textContent, /Dos/);
  click({ dataset: { consDepth: "2" } });
  assert.match(root.textContent, /Uno/);
  const pressed = findAll(root, (node) => node.attributes?.["data-node"] === C(3))[0];
  assert.equal(pressed.attributes["aria-pressed"], "true");
  // Elegir y soltar un commit no mueve el foco local.
  const commit = `commit:${"0".repeat(40)}`;
  handle.update({ ...state, sel: commit });
  handle.update({ ...state, sel: null });
  assert.match(root.textContent, /Tres/);
  assert.doesNotMatch(root.textContent, /seleccioná un contexto/);
  // Al volver a la Lista, la selección (contexto o commit) se conserva (§23.2).
  handle.update({ ...state, sel: C(3) });
  click({ dataset: { as: "list" } });
  assert.deepEqual(sets.at(-1), { as: null, sel: C(3) });
  handle.update({ ...state, sel: commit });
  click({ dataset: { as: "list" } });
  assert.deepEqual(sets.at(-1), { as: null, sel: commit });
  // Soltar el contexto que fija el foco lo limpia.
  handle.update({ ...state, sel: C(3) });
  handle.update({ ...state, sel: null });
  assert.match(root.textContent, /seleccioná un contexto/);
  // El foco no sobrevive al cambio de proyecto.
  handle.update({ ...state, sel: C(3) });
  handle.update({ ...state, project: "otro", sel: null });
  await new Promise((resolve) => setImmediate(resolve));
  assert.match(root.textContent, /seleccioná un contexto/);
}));

test("Trabajo · Grafo: puentes con commits seleccionables y portal informativo", () => withDocument(async (doc) => {
  const contexts = { contexts: [1, 2, 3, 4].map((id) => ({ id, title: `T${id}`, status: "active", steps: { total: 0, completed: 0 } })) };
  const api = { get: async (path) => (path.endsWith("/constellation") ? dto() : contexts) };
  const root = new FakeNode(doc, "div");
  root.addEventListener = () => {};
  root.replaceChildren = (...children) => { root.childNodes = children; };
  const state = { project: "mi-proyecto", view: "trabajo", tab: "contextos", ctx: null, step: null, as: "constellation", sel: null };
  const handle = await mount(root, { api, store: { set() {} }, state, signal: new AbortController().signal });
  assert.match(root.textContent, /Puentes/);
  assert.match(root.textContent, /↗ otro-proyecto \(otro proyecto\)/);
  const commit = `commit:${"0".repeat(40)}`;
  const chips = findAll(root, (node) => node.dataset?.sel === commit);
  assert.equal(chips.length, 2);
  assert.ok(chips.every((chip) => chip.tagName === "button"));
  const portal = findAll(root, (node) => node.attributes?.["data-node"] === "portal:otro-proyecto")[0];
  assert.equal(portal.attributes.tabindex, undefined);
  assert.equal(portal.attributes.role, "img");
  // Un commit compartido resalta los extremos de sus puentes y atenúa el resto.
  handle.update({ ...state, sel: `commit:${"1".repeat(40)}` });
  const node = (id) => findAll(root, (item) => item.attributes?.["data-node"] === id)[0];
  assert.ok(!node(C(1)).classes.has("is-dim"));
  assert.ok(!node(C(2)).classes.has("is-dim"));
  assert.ok(node("portal:otro-proyecto").classes.has("is-dim"));
}));

test("Trabajo · Grafo: si la constelación falla, se avisa y la lista de contextos sigue disponible", () => withDocument(async (doc) => {
  const api = { get: async (path) => {
    if (path.endsWith("/constellation")) throw Object.assign(new Error("falló"), { status: 500 });
    return { contexts: [] };
  } };
  const root = new FakeNode(doc, "div");
  root.addEventListener = () => {};
  root.replaceChildren = (...children) => { root.childNodes = children; };
  const warn = console.warn;
  console.warn = () => {};
  try {
    await mount(root, { api, store: { set() {} }, signal: new AbortController().signal,
      state: { project: "mi-proyecto", view: "trabajo", tab: "contextos", ctx: null, step: null, as: "constellation", sel: null } });
  } finally {
    console.warn = warn;
  }
  assert.match(root.textContent, /no está disponible/);
  assert.match(root.textContent, /◇ Grafo · Labs/);
}));

test("layoutConstellation: los aislados visibles se compactan en la grilla sin huecos", () => {
  const data = dto();
  data.nodes.push(context(5, "active", "claude", 1));
  data.constellation.isolated.push(C(5));
  data.constellation.positions[C(5)] = { x: 157.78, y: 660 };
  const active = layoutConstellation(data);
  assert.deepEqual(active.suns.filter((sun) => sun.isolated).map((sun) => [sun.id, sun.x, sun.y]), [[C(5), 60, 660]]);
  const all = layoutConstellation(data, { scope: "all" });
  assert.deepEqual(all.suns.find((sun) => sun.id === C(5)), { ...all.suns.find((sun) => sun.id === C(5)), x: 157.78, y: 660 });
});
