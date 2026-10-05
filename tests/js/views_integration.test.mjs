import { test } from "node:test";
import assert from "node:assert/strict";

import { h } from "../../orchestrator/static/dashboard/core/dom.js";
import { mount as mountHome } from "../../orchestrator/static/dashboard/views/home.js";
import { mount as mountRuns } from "../../orchestrator/static/dashboard/views/runs.js";
import { mount as mountCosts } from "../../orchestrator/static/dashboard/views/costs.js";
import { navigationFor } from "../../orchestrator/static/dashboard/core/actions.js";

class Node {
  constructor(doc, tag) {
    Object.assign(this, { ownerDocument: doc, tagName: tag, attributes: {}, dataset: {}, className: "", childNodes: [] });
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  appendChild(child) { this.childNodes.push(child); return child; }
  // Como el DOM real: `null` y los strings pasados a replaceChildren se vuelven texto.
  replaceChildren(...children) {
    this.childNodes = children.map((child) => (child !== null && typeof child === "object" ? child : { nodeType: 3, text: String(child) }));
  }
  get textContent() { return this.childNodes.map((c) => (c.nodeType === 3 ? c.text : c.textContent)).join(""); }
}

function setup() {
  const doc = {
    createElement: (tag) => new Node(doc, tag),
    createTextNode: (text) => ({ nodeType: 3, text }),
    head: { querySelector: () => ({}), append() {} },
  };
  h.document = doc;
  const root = new Node(doc, "div");
  root.classList = { add() {} };
  root.handlers = [];
  root.addEventListener = (_, handler) => root.handlers.push(handler);
  root.removeEventListener = (_, handler) => { root.handlers = root.handlers.filter((item) => item !== handler); };
  root.contains = () => true;
  return root;
}

function find(node, predicate, found = []) {
  if (node && node.nodeType !== 3) {
    if (predicate(node)) found.push(node);
    for (const child of node.childNodes ?? []) find(child, predicate, found);
  }
  return found;
}

function click(root, target) {
  const event = { target: { closest: () => target }, prevented: false, preventDefault() { this.prevented = true; } };
  for (const handler of root.handlers) handler(event);
  return event;
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

const OVERVIEW = {
  project: "mi-proyecto",
  generated_at: "2026-06-15T12:00:00+00:00",
  period: { key: "7d", from: "2026-06-08T12:00:00+00:00", to: "2026-06-15T12:00:00+00:00" },
  metrics: [
    { id: "active_contexts", label: "Contextos activos", value: 2, unit: "count", detail: [], source: "Cuenta.",
      link: { view: "trabajo", tab: null, params: {} } },
    { id: "stale_steps", label: "Pasos estancados", value: 1, unit: "count", detail: [], source: "Cuenta.",
      link: { view: "trabajo", tab: null, params: {} } },
    { id: "cost_period", label: "Costo del período", value: 1.5, unit: "usd",
      detail: [{ label: "runs", value: 3 }, { label: "runs atribuidos a un paso", value: 1 }], source: "Suma.",
      link: { view: "ejecuciones", tab: "costos", params: {} } },
    { id: "tracking_health", label: "Salud del tracking", value: 1, unit: "count", detail: [], source: "Cuenta.",
      link: { view: "trabajo", tab: null, params: {} } },
  ],
  alerts: [],
  tracking_health: {
    warning_count: 1,
    warnings: [{ code: "stale_in_progress_step", message: "paso #3 sin actividad", hint: "Retomalo." }],
    data_quality: { completed_without_start: 0, skipped: 0 },
  },
  egress: { state: "empty", message: "Sin decisiones." },
};

test("Inicio: tarjetas con navegación por data-view, Salud del tracking como panel y cambio de período", async () => {
  const root = setup();
  try {
    const calls = [];
    // La vista previa de la constelación es opcional: si falla, Inicio se dibuja igual.
    const api = { get: async (path, { params }) => {
      if (path.endsWith("/constellation")) throw Object.assign(new Error("falló"), { status: 500 });
      calls.push(params?.period);
      return OVERVIEW;
    } };
    await mountHome(root, { api, state: { project: "mi-proyecto" }, signal: new AbortController().signal, store: { set() {} } });
    const cards = find(root, (node) => typeof node.className === "string" && node.className.startsWith("metric-card"));
    assert.equal(cards.length, 3);
    assert.deepEqual(cards.map((card) => [card.dataset.view, card.dataset.tab]),
      [["trabajo", undefined], ["trabajo", undefined], ["ejecuciones", "costos"]]);
    assert.equal(cards[2].attributes.href, "?project=mi-proyecto&view=ejecuciones&tab=costos");
    assert.match(cards[1].className, /is-warn/);
    // El clic en una tarjeta lo resuelve la regla de navegación del shell.
    assert.deepEqual(navigationFor(cards[2].dataset), { view: "ejecuciones", tab: "costos" });
    assert.deepEqual(navigationFor(cards[0].dataset), { view: "trabajo", tab: null });
    assert.equal(navigationFor(cards[2].dataset, { ctrlKey: true }), null);
    assert.equal(navigationFor({}), null);
    assert.match(root.textContent, /Salud del tracking · 1/);
    assert.match(root.textContent, /3 runs · 1 atribuidos a pasos/);
    click(root, { dataset: { period: "30d" } });
    await tick();
    assert.deepEqual(calls, ["7d", "30d"]);
    assert.doesNotMatch(root.textContent, /\bnull\b|undefined/);
  } finally {
    delete h.document;
  }
});

test("Runs: Cargar más, selección, enlace al paso y filtro por fuente", async () => {
  const root = setup();
  try {
    const calls = [];
    const run = (id, extra = {}) => ({
      id, ts: "2026-06-14T12:00:00+00:00", source: "session", provider: "claude", model: "opus",
      status: "done", task_preview: "t", cost_usd: 0.5, context_id: null, step_id: null, ...extra,
    });
    const api = {
      get: async (path, { params }) => {
        calls.push({ ...params });
        return params.cursor
          ? { runs: [run(1)], next_cursor: null }
          : { runs: [run(3, { context_id: 7, step_id: 9 }), run(2)], next_cursor: "x|2" };
      },
    };
    const sets = [];
    const state = { project: "mi-proyecto", view: "ejecuciones", tab: "runs", sel: null };
    const handle = await mountRuns(root, { api, state, signal: new AbortController().signal, store: { set: (patch) => sets.push(patch) } });
    click(root, { dataset: { more: "1" } });
    await tick();
    assert.deepEqual(find(root, (node) => node.dataset?.sel).map((node) => node.dataset.sel), ["run:3", "run:2", "run:1"]);
    click(root, { dataset: { sel: "run:2" } });
    assert.deepEqual(sets.at(-1), { sel: "run:2" });
    handle.update({ ...state, sel: "run:2" });
    assert.equal(find(root, (node) => node.dataset?.sel === "run:2")[0].attributes["aria-pressed"], "true");
    const event = click(root, { dataset: { nav: "1", ctx: "7", step: "9" } });
    assert.equal(event.prevented, true);
    assert.deepEqual(sets.at(-1), { view: "trabajo", tab: "contextos", ctx: 7, step: 9, sel: null });
    click(root, { dataset: { source: "commit" } });
    await tick();
    assert.deepEqual(calls.at(-1), { source: "commit", limit: 50, cursor: null });
    handle.unmount();
    assert.equal(root.handlers.length, 0);
  } finally {
    delete h.document;
  }
});

test("Costos: tarjetas, días con costo, período y enlace al contexto", async () => {
  const root = setup();
  try {
    const periods = [];
    const data = {
      project: "mi-proyecto",
      period: { key: "30d", from: "a", to: "b" },
      totals: { cost_usd: 10, runs: 4, runs_with_cost: 3, attributed_runs: 1, attributed_cost_usd: 2.5 },
      daily: [{ date: "2026-06-01", cost_usd: 0 }, { date: "2026-06-02", cost_usd: 10 }],
      by_context: [
        { context_id: 7, title: "Contexto", cost_usd: 2.5, runs: 1 },
        { context_id: null, title: "Sin paso", cost_usd: 7.5, runs: 3 },
      ],
      by_agent: [{ agent: "git", cost_usd: 0, runs: 2 }],
    };
    const api = { get: async (path, { params }) => { periods.push(params.period); return data; } };
    const sets = [];
    await mountCosts(root, {
      api, state: { project: "mi-proyecto", view: "ejecuciones", tab: "costos" },
      signal: new AbortController().signal, store: { set: (patch) => sets.push(patch) },
    });
    const text = root.textContent;
    assert.match(text, /25 %/);
    assert.match(text, /3 runs sin paso/);
    assert.match(text, /1 días sin costo/);
    assert.match(text, /Commits de git/);
    click(root, { dataset: { period: "7d" } });
    await tick();
    assert.deepEqual(periods, ["30d", "7d"]);
    click(root, { dataset: { nav: "1", ctx: "7" } });
    assert.deepEqual(sets.at(-1), { view: "trabajo", tab: "contextos", ctx: 7, step: null, sel: null });
    assert.doesNotMatch(root.textContent, /\bnull\b|undefined/);
  } finally {
    delete h.document;
  }
});
