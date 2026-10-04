import { test } from "node:test";
import assert from "node:assert/strict";

import { h } from "../../orchestrator/static/dashboard/core/dom.js";
import { formatUsd, sourceLabel, stepHref } from "../../orchestrator/static/dashboard/views/runs.js";
import { meterSeries } from "../../orchestrator/static/dashboard/views/costs.js";

class FakeNode {
  constructor(doc, tag) {
    this.ownerDocument = doc;
    this.tagName = tag;
    this.dataset = {};
    this.attributes = {};
    this.childNodes = [];
    this.classList = { add() {}, toggle() {} };
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  appendChild(child) { this.childNodes.push(child); return child; }
  get textContent() { return this.childNodes.map((child) => child.text ?? child.textContent ?? "").join(""); }
}

function root() {
  const doc = {
    createElement: (tag) => new FakeNode(doc, tag),
    createTextNode: (text) => ({ text }),
    head: { querySelector: () => ({}), append() {} },
  };
  const value = new FakeNode(doc, "div");
  value.listeners = 0;
  value.addEventListener = () => { value.listeners += 1; };
  value.removeEventListener = () => { value.listeners -= 1; };
  // Como el DOM real, convierte argumentos nulos en nodos de texto.
  value.replaceChildren = (...items) => {
    value.childNodes = items.map((item) => item ?? { text: String(item) });
  };
  value.contains = () => true;
  return value;
}

test("helpers de Ejecuciones producen etiquetas, enlaces y escala de meter", () => {
  assert.equal(sourceLabel("session"), "Sesión");
  assert.equal(sourceLabel("x"), "x");
  assert.match(formatUsd(1.5), /1,50/);
  assert.equal(formatUsd(null), "—");
  assert.equal(stepHref({ project: "mi-proyecto" }, 2, 3),
    "?project=mi-proyecto&view=trabajo&tab=contextos&ctx=2&step=3");
  assert.equal(stepHref({}, null, 3), null);
  assert.deepEqual(meterSeries([{ date: "2026-01-01", cost_usd: 0 }, { date: "2026-01-02", cost_usd: 2 }])
    .map((item) => item.max), [2, 2]);
});

test("mount no deja listeners y los cambios de filtro reinician la lista", async () => {
  const target = root();
  h.document = target.ownerDocument;
  try {
    const controller = new AbortController();
    let signalListeners = 0;
    const add = controller.signal.addEventListener.bind(controller.signal);
    const remove = controller.signal.removeEventListener.bind(controller.signal);
    controller.signal.addEventListener = (...args) => { signalListeners += 1; add(...args); };
    controller.signal.removeEventListener = (...args) => { signalListeners -= 1; remove(...args); };
    const requests = [];
    const api = { get: (_, options) => {
      requests.push(options.params);
      return Promise.resolve({ runs: [{ id: requests.length, ts: "2026-05-10T13:00:00Z", task_preview: "x", source: "router", status: "ok", provider: "p", model: "m" }], next_cursor: null });
    } };
    const handle = await (await import("../../orchestrator/static/dashboard/views/runs.js")).mount(target, {
      api,
      state: { project: "mi-proyecto", sel: null },
      signal: controller.signal,
      store: { set() {} },
    });
    assert.equal(signalListeners, 0);
    assert.equal(requests.length, 1);
    assert.doesNotMatch(target.textContent, /null|undefined/);
    handle.unmount();
    assert.equal(target.listeners, 0);
  } finally {
    delete h.document;
  }
});

test("Costos enlaza el contexto, sin seleccionar un paso fijo", async () => {
  const target = root();
  h.document = target.ownerDocument;
  try {
    const sets = [];
    const { mount } = await import("../../orchestrator/static/dashboard/views/costs.js");
    const handle = await mount(target, {
      api: { get: () => Promise.resolve({
        totals: { cost_usd: 0, runs: 0, attributed_runs: 0, attributed_cost_usd: 0 }, daily: [],
        by_context: [{ context_id: 42, title: "Contexto", runs: 1, cost_usd: 1 }],
        by_agent: [{ agent: "claude", runs: 1, cost_usd: 1 }, { agent: "git", runs: 1, cost_usd: 1 }, { agent: "", runs: 1, cost_usd: 0 }],
      }) },
      state: { project: "mi-proyecto", sel: "run:9" }, signal: new AbortController().signal,
      store: { set: (value) => sets.push(value) },
    });
    const descendants = (node) => (node?.childNodes ?? []).flatMap((child) => [child, ...descendants(child)]);
    const contextLink = descendants(target).find((node) => node?.tagName === "a");
    assert.match(contextLink.attributes.href, /ctx=42/);
    assert.doesNotMatch(contextLink.attributes.href, /step=/);
    assert.match(target.textContent, /7 días/);
    assert.match(target.textContent, /Commits de git/);
    assert.match(target.textContent, /Sin agente/);
    handle.unmount();
    assert.deepEqual(sets, []);
  } finally {
    delete h.document;
  }
});
