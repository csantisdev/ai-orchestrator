import { test } from "node:test";
import assert from "node:assert/strict";

import { h } from "../../orchestrator/static/dashboard/core/dom.js";
import { watchChanges } from "../../orchestrator/static/dashboard/core/live.js";
import { createViewHost } from "../../orchestrator/static/dashboard/core/mount.js";
import {
  activityActions, activityFilter, activitySummary, activityText, formatActivityTime, mountActivity,
} from "../../orchestrator/static/dashboard/components/activity.js";

const item = (kind, id, extra = {}) => ({
  id: `${kind}:${id}`, kind, ts: "2026-06-05T14:32:00+00:00", state: null, attrs: {},
  refs: { context: null, step: null, run: null }, ...extra,
});

test("activityText arma una línea solo con campos estructurados", () => {
  assert.equal(activityText(item("run", 146, { state: "completed", attrs: { provider: "claude" } })), "Run #146 · claude · completado");
  assert.equal(activityText(item("step_completed", 9, { refs: { context: "context:4", step: "step:9", run: null } })),
    "Paso #9 completado · contexto #4");
  assert.equal(activityText(item("alignment", 3, { attrs: { agent: "codex", confirmed: false }, refs: { context: "context:4", step: "step:9", run: null } })),
    "Desvío registrado · codex · paso #9");
  assert.equal(activityText(item("mcp", 7, { state: "denied", attrs: { tool_name: "advance_step", reason_code: "capability_denied" } })),
    "MCP advance_step · denegado · capability_denied");
  assert.equal(activityText(item("mcp", 8, { attrs: { tool_name: "start_step", is_error: true } })), "MCP start_step · error");
  assert.equal(activityText(item("egress", 2, { attrs: { decision: "deny", provider: "gemini", reason_code: "clearance_insufficient" } })),
    "Egress denegado · gemini · clearance_insufficient");
  assert.equal(activityFilter(item("tool_call", 1)), "agent");
  assert.equal(activityFilter(item("step_started", 1)), "step");
});

test("activityActions: Ver abre el objeto del Inspector y Trace necesita contexto y paso", () => {
  assert.deepEqual(activityActions(item("mcp", 7)), { sel: "decision:mcp-7", trace: null });
  assert.deepEqual(activityActions(item("egress", 2)), { sel: "decision:egress-2", trace: null });
  assert.deepEqual(activityActions(item("run", 5, { refs: { context: "context:4", step: "step:9", run: "run:5" } })),
    { sel: "run:5", trace: { view: "trabajo", tab: null, ctx: 4, step: 9, as: null } });
  assert.deepEqual(activityActions(item("alignment", 3, { refs: { context: "context:4", step: null, run: null } })),
    { sel: "context:4", trace: null });
});

test("formatActivityTime muestra la hora si es hoy y la fecha si no", () => {
  const now = new Date("2026-06-05T20:00:00Z");
  assert.equal(formatActivityTime("2026-06-05T14:32:00+00:00", { now, timeZone: "UTC" }), "14:32");
  assert.match(formatActivityTime("2026-06-01T09:05:00+00:00", { now, timeZone: "UTC" }), /^01.*jun.*09:05$/);
  assert.equal(formatActivityTime("no es fecha"), "");
  assert.equal(activitySummary(null), null);
});

class FakeNode {
  constructor(doc, tag) {
    this.ownerDocument = doc;
    this.tagName = tag;
    this.attributes = {};
    this.dataset = {};
    this.childNodes = [];
    this.listeners = [];
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  appendChild(child) { this.childNodes.push(child); return child; }
  replaceChildren(...children) { this.childNodes = children.filter((c) => c !== null && c !== undefined); }
  addEventListener(_, handler) { this.listeners.push(handler); }
  get textContent() { return this.childNodes.map((c) => (c.nodeType === 3 ? c.text : c.textContent)).join(""); }
  set textContent(value) { this.childNodes = [{ nodeType: 3, text: value }]; }
}

function withDocument(fn) {
  const doc = { createElement: (tag) => new FakeNode(doc, tag), createTextNode: (text) => ({ nodeType: 3, text }) };
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

function fakeStore(initial) {
  let state = initial;
  return { get: () => state, set: (patch) => { state = { ...state, ...patch }; } };
}

test("mountActivity: lista, filtro, Ver, Trace, Cargar más y resumen", () => withDocument(async (doc) => {
  const pages = {
    first: { items: [
      item("run", 5, { state: "completed", attrs: { provider: "claude" }, refs: { context: "context:4", step: "step:9", run: "run:5" } }),
      item("mcp", 7, { state: "ok", attrs: { tool_name: "advance_step" } }),
    ], next_cursor: "c1" },
    second: { items: [item("step_started", 9, { refs: { context: "context:4", step: "step:9", run: null } }),
      item("mcp", 7, { attrs: { tool_name: "advance_step" } })], next_cursor: null },
  };
  const calls = [];
  const api = { get: async (path, { params }) => { calls.push([path, params]); return params.cursor ? pages.second : pages.first; } };
  const root = new FakeNode(doc, "section");
  const summary = new FakeNode(doc, "span");
  const store = fakeStore({ project: "mi-proyecto", sel: null });
  const activity = mountActivity({ root, summary, api, store });
  await activity.refresh();
  assert.deepEqual(calls[0], ["/api/v1/projects/mi-proyecto/activity", { limit: 30 }]);
  assert.match(root.textContent, /Run #5 · claude · completado/);
  assert.match(summary.textContent, /^Run #5 · claude · completado · /);
  const click = (target) => root.listeners.forEach((handler) => handler({ target: { closest: () => target } }));
  click({ dataset: { actSel: "run:5" } });
  assert.equal(store.get().sel, "run:5");
  click({ dataset: { actTrace: JSON.stringify({ view: "trabajo", tab: null, ctx: 4, step: 9, as: null }) } });
  assert.deepEqual([store.get().ctx, store.get().step, store.get().sel], [4, 9, null]);
  click({ dataset: { actMore: "1" } });
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(calls[1][1], { limit: 30, cursor: "c1" });
  // El duplicado de la segunda página no se repite y ya no hay más páginas.
  assert.equal(findAll(root, (node) => node.tagName === "li").length, 3);
  assert.equal(findAll(root, (node) => node.dataset?.actMore).length, 0);
  click({ dataset: { actFilter: "step" } });
  assert.equal(findAll(root, (node) => node.tagName === "li").length, 1);
  click({ dataset: { actFilter: "step" } });
  assert.equal(findAll(root, (node) => node.tagName === "li").length, 3);
}));

test("mountActivity: sin proyecto pide elegir uno y un fallo se informa sin romper", () => withDocument(async (doc) => {
  const root = new FakeNode(doc, "section");
  await mountActivity({ root, api: { get: async () => ({}) }, store: fakeStore({ project: null }) }).refresh();
  assert.match(root.textContent, /Elegí un proyecto/);
  const warn = console.warn;
  console.warn = () => {};
  try {
    await mountActivity({ root, api: { get: async () => { throw new Error("falló"); } }, store: fakeStore({ project: "mi-proyecto" }) }).refresh();
  } finally {
    console.warn = warn;
  }
  assert.match(root.textContent, /No se pudo cargar la actividad/);
}));

function fakeTimers() {
  const queue = new Map();
  let next = 1;
  return {
    setTimeout: (fn) => { queue.set(next, fn); return next++; },
    clearTimeout: (id) => queue.delete(id),
    flush() { const fns = [...queue.values()]; queue.clear(); fns.forEach((fn) => fn()); },
    get size() { return queue.size; },
  };
}

function fakeTarget() {
  const handlers = {};
  return {
    hidden: false,
    addEventListener: (type, fn) => { (handlers[type] ??= []).push(fn); },
    removeEventListener: (type, fn) => { handlers[type] = (handlers[type] ?? []).filter((item) => item !== fn); },
    emit: (type) => (handlers[type] ?? []).forEach((fn) => fn()),
    count: (type) => (handlers[type] ?? []).length,
  };
}

test("watchChanges agrupa ráfagas y espera a que la pestaña sea visible", () => {
  const events = fakeTarget();
  const doc = fakeTarget();
  const timers = fakeTimers();
  let calls = 0;
  const watch = watchChanges({ events, doc, timers, onChange: () => { calls += 1; } });
  events.emit("db_changed");
  events.emit("db_changed");
  events.emit("db_changed");
  assert.equal(timers.size, 1);
  timers.flush();
  assert.equal(calls, 1);
  doc.hidden = true;
  events.emit("db_changed");
  timers.flush();
  assert.equal(calls, 1);
  doc.hidden = false;
  doc.emit("visibilitychange");
  timers.flush();
  assert.equal(calls, 2);
  watch.stop();
  assert.equal(events.count("db_changed"), 0);
  assert.equal(doc.count("visibilitychange"), 0);
  assert.doesNotThrow(() => watchChanges({ events: null, onChange() {} }).stop());
});

test("createViewHost.refresh usa refresh de la vista o la vuelve a montar con el último estado", async () => {
  const doc = { createElement: () => ({ dataset: {} }) };
  const root = { ownerDocument: doc, replaceChildren() {} };
  const mounts = [];
  let refreshed = 0;
  const modules = {
    "./views/a.js": { mount: async () => ({ refresh: async () => { refreshed += 1; } }) },
    "./views/b.js": { mount: async (_, context) => { mounts.push(context.state); return {}; } },
  };
  const host = createViewHost({ root, load: async (path) => modules[path] });
  await host.show("a", "./views/a.js", { state: { n: 1 } });
  await host.refresh();
  assert.equal(refreshed, 1);
  await host.show("b", "./views/b.js", { state: { n: 1 } });
  await host.show("b", "./views/b.js", { state: { n: 2 } });
  await host.refresh();
  assert.deepEqual(mounts, [{ n: 1 }, { n: 2 }]);
  assert.equal(host.current, "b");
});
