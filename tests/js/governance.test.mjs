import { test } from "node:test";
import assert from "node:assert/strict";

import { h } from "../../orchestrator/static/dashboard/core/dom.js";
import { resolveSection } from "../../orchestrator/static/dashboard/core/sections.js";
import {
  MCP_FILTERS, REASONS, agentLabel, endpoints, formatInstant, mount, reasonText, tabFor,
} from "../../orchestrator/static/dashboard/views/governance.js";

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
  // Como el DOM real: `null` y los strings pasados a replaceChildren se vuelven texto.
  replaceChildren(...children) {
    this.childNodes = children.map((child) => (child !== null && typeof child === "object" ? child : { nodeType: 3, text: String(child) }));
  }
  get textContent() {
    return this.childNodes.map((c) => (c.nodeType === 3 ? c.text : c.textContent)).join("");
  }
}

function fakeDocument() {
  const doc = {
    createElement: (tag) => new FakeNode(doc, tag),
    createTextNode: (text) => ({ nodeType: 3, text }),
    head: { querySelector: () => ({}), append() {} },
  };
  return doc;
}

function findAll(node, predicate, found = []) {
  if (node && typeof node === "object" && node.nodeType !== 3) {
    if (predicate(node)) found.push(node);
    for (const child of node.childNodes ?? []) findAll(child, predicate, found);
  }
  return found;
}

function fakeRoot(doc) {
  const root = new FakeNode(doc, "div");
  root.classList = { add() {} };
  root.handlers = [];
  root.addEventListener = (_, handler) => root.handlers.push(handler);
  root.removeEventListener = (_, handler) => { root.handlers = root.handlers.filter((item) => item !== handler); };
  root.contains = () => true;
  return root;
}

function click(root, target) {
  const event = { target: { closest: () => target } };
  for (const handler of root.handlers) handler(event);
}

const BASE = { project: "mi-proyecto", view: "gobernanza", tab: "acceso", ctx: null, step: null, as: null, sel: null };
const SUMMARY = {
  project: "mi-proyecto", period: { key: "30d", from: "2026-05-16T12:00:00+00:00", to: "2026-06-15T12:00:00+00:00" },
  mcp: { invocations: 9, denied: 2, error: 1, in_progress: 0,
    by_reason: [{ key: "project_out_of_scope", count: 2 }], by_tool: [], by_agent: [{ key: "codex", count: 2 }] },
  egress: { total: 0, blocked: 0, by_reason: [] },
};

function item(id, extra = {}) {
  return {
    id, sel: `decision:mcp-${id}`, ts: "2026-06-14T12:00:00+00:00", agent: "codex", client_surface: "codex_cli",
    transport: "stdio", capability_profile: "readonly", tool_name: "advance_step", tool_category: "workflow_transition",
    status: "denied", is_error: false, reason_code: "capability_denied", error_code: null, duration_ms: 3,
    request_source: "generated", replay_safe: false, ...extra,
  };
}

test("las pestañas de Gobernanza montan la vista nueva", () => {
  assert.equal(resolveSection({ view: "gobernanza", project: null }).module, "./views/governance.js");
  assert.equal(resolveSection({ view: "gobernanza", tab: "egress", project: null }).module, "./views/governance.js");
  assert.deepEqual(resolveSection({ view: "gobernanza", tab: "egress", project: "p" }).crumbs, ["p", "Gobernanza", "Egress"]);
  assert.equal(tabFor({ tab: "egress" }), "egress");
  assert.equal(tabFor({ tab: null }), "acceso");
  assert.equal(tabFor({ tab: "otra" }), "acceso");
});

test("endpoints, motivos, agentes y fechas", () => {
  assert.deepEqual(endpoints("mi-proyecto"), {
    summary: "/api/v1/projects/mi-proyecto/governance/summary",
    mcp: "/api/v1/projects/mi-proyecto/mcp-invocations",
    egress: "/api/v1/projects/mi-proyecto/egress-decisions",
  });
  for (const bad of [null, "", "a b", "a/b", ".x", "x%2e"]) assert.equal(endpoints(bad), null, String(bad));
  assert.match(reasonText("project_out_of_scope"), /ORCHESTRATOR_MCP_PROJECTS/);
  assert.match(reasonText("desconocido"), /sin descripción/);
  assert.equal(reasonText(null), null);
  assert.ok(Object.keys(REASONS).includes("capability_denied"));
  assert.deepEqual(MCP_FILTERS.map(([key]) => key), ["problems", "denied", "error", "in_progress", "all"]);
  assert.equal(agentLabel("codex"), "Codex");
  assert.equal(formatInstant(null), "fecha ilegible");
  assert.match(formatInstant("2026-06-14T12:00:00+00:00", { timeZone: "UTC" }), /14.*jun.*12:00/);
});

test("mount pide resumen y lista, filtra, pagina y muestra el detalle de la selección", async () => {
  const doc = fakeDocument();
  h.document = doc;
  try {
    const root = fakeRoot(doc);
    const calls = [];
    const api = {
      get: async (path, { params, signal }) => {
        calls.push({ path, params });
        assert.equal(signal.aborted, false);
        if (path.endsWith("/summary")) return SUMMARY;
        if (params.cursor === "x|9") return { items: [item(3)], next_cursor: null };
        return { items: [item(9), item(8, { status: "error", reason_code: null, error_code: "invalid_arguments" })], next_cursor: "x|9" };
      },
    };
    const sets = [];
    const controller = new AbortController();
    const handle = await mount(root, { api, state: BASE, signal: controller.signal, store: { set: (patch) => sets.push(patch) } });
    assert.deepEqual(calls.map((call) => call.path), [
      "/api/v1/projects/mi-proyecto/mcp-invocations", "/api/v1/projects/mi-proyecto/governance/summary",
    ]);
    assert.deepEqual(calls[0].params, { cursor: null, status: "problems" });
    assert.deepEqual(calls[1].params, { period: "30d" });
    assert.match(root.textContent, /2 denegadas/);
    assert.match(root.textContent, /project_out_of_scope/);

    click(root, { dataset: { more: "1" } });
    await new Promise((r) => setImmediate(r));
    assert.deepEqual(calls.at(-1), { path: "/api/v1/projects/mi-proyecto/mcp-invocations", params: { cursor: "x|9", status: "problems" } });
    assert.equal(findAll(root, (node) => node.dataset?.sel).length, 3);
    assert.equal(findAll(root, (node) => node.dataset?.more).length, 0);

    click(root, { dataset: { sel: "decision:mcp-9" } });
    assert.deepEqual(sets, [{ sel: "decision:mcp-9" }]);
    handle.update({ ...BASE, sel: "decision:mcp-9" });
    assert.match(root.textContent, /ORCHESTRATOR_MCP_PROFILE/);
    const pressed = findAll(root, (node) => node.dataset?.sel === "decision:mcp-9")[0];
    assert.equal(pressed.attributes["aria-pressed"], "true");

    click(root, { dataset: { filter: "denied" } });
    await new Promise((r) => setImmediate(r));
    assert.deepEqual(calls.at(-2).params, { cursor: null, status: "denied" });

    handle.unmount();
    assert.equal(root.handlers.length, 0);
  } finally {
    delete h.document;
  }
});

test("egress vacío explica por qué y sin proyecto pide elegir uno", async () => {
  const doc = fakeDocument();
  h.document = doc;
  try {
    const api = { get: async (path) => (path.endsWith("/summary") ? SUMMARY : { items: [], next_cursor: null }) };
    const egressRoot = fakeRoot(doc);
    await mount(egressRoot, { api, state: { ...BASE, tab: "egress" }, signal: new AbortController().signal, store: { set() {} } });
    assert.match(egressRoot.textContent, /no pasan por el gate/);
    assert.doesNotMatch(egressRoot.textContent, /null|undefined/);
    const emptyRoot = fakeRoot(doc);
    await mount(emptyRoot, { api, state: { ...BASE, project: null }, signal: new AbortController().signal, store: { set() {} } });
    assert.match(emptyRoot.textContent, /Elegí un proyecto/);
  } finally {
    delete h.document;
  }
});

import { displayStatus } from "../../orchestrator/static/dashboard/views/governance.js";

test("una invocación success con is_error se muestra como error y los motivos desconocidos se explican", () => {
  assert.equal(displayStatus(item(1, { status: "success", is_error: true })), "error");
  assert.equal(displayStatus(item(1, { status: "success", is_error: false })), "success");
  assert.equal(displayStatus(item(1, { status: "denied", is_error: true })), "denied");
  assert.match(reasonText("motivo_nuevo"), /sin descripción/);
  assert.equal(reasonText("allowed"), null);
  for (const code of ["execution_error", "step_changed_concurrently", "clearance_insufficient", "secret_pattern_detected"]) {
    assert.ok(REASONS[code], code);
  }
});

test("una página de 'Cargar más' que llega después de cambiar el filtro se descarta", async () => {
  const doc = fakeDocument();
  h.document = doc;
  try {
    const root = fakeRoot(doc);
    let releaseMore;
    const api = {
      get: (path, { params, signal }) => {
        if (path.endsWith("/summary")) return Promise.resolve(SUMMARY);
        if (params.cursor === "x|9") {
          return new Promise((resolve, reject) => {
            releaseMore = () => resolve({ items: [item(3)], next_cursor: null });
            signal.addEventListener("abort", () => reject(new DOMException("abortado", "AbortError")));
          });
        }
        if (params.status === "denied") return Promise.resolve({ items: [item(7)], next_cursor: null });
        return Promise.resolve({ items: [item(9)], next_cursor: "x|9" });
      },
    };
    const signal = new AbortController().signal;
    await mount(root, { api, state: BASE, signal, store: { set() {} } });
    click(root, { dataset: { more: "1" } });
    click(root, { dataset: { filter: "denied" } });
    await new Promise((r) => setImmediate(r));
    releaseMore?.();
    await new Promise((r) => setImmediate(r));
    const sels = findAll(root, (node) => node.dataset?.sel).map((node) => node.dataset.sel);
    assert.deepEqual(sels, ["decision:mcp-7"]);
  } finally {
    delete h.document;
  }
});

test("el detalle de una invocación success con is_error lo dice", async () => {
  const doc = fakeDocument();
  h.document = doc;
  try {
    const root = fakeRoot(doc);
    const api = {
      get: async (path) => (path.endsWith("/summary") ? SUMMARY
        : { items: [item(5, { status: "success", is_error: true, reason_code: null, error_code: "execution_error" })], next_cursor: null }),
    };
    const handle = await mount(root, { api, state: BASE, signal: new AbortController().signal, store: { set() {} } });
    assert.match(root.textContent, /Con error/);
    assert.doesNotMatch(root.textContent, /Correcta/);
    handle.update({ ...BASE, sel: "decision:mcp-5" });
    assert.match(root.textContent, /success \(con error\)/);
    assert.match(root.textContent, /falló al ejecutarse/);
  } finally {
    delete h.document;
  }
});
