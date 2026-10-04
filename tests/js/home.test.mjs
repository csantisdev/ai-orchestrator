import test from "node:test";
import assert from "node:assert/strict";
import { aliasNeedsEncoding, detailLabel, formatNumber, formatUsd, periodText, viewHref } from "../../orchestrator/static/dashboard/views/home.js";

test("formatos y período usan es-CL", () => {
  assert.equal(formatNumber(1234), "1.234");
  assert.match(formatUsd(12.5), /US\$|USD/);
  assert.match(formatUsd(0.01), /0,01/);
  assert.equal(periodText("30d"), "Últimos 30 días");
});
test("links y aliases", () => {
  assert.equal(viewHref("mi-proyecto", { view: "trabajo", tab: null, params: {} }), "?project=mi-proyecto&view=trabajo");
  assert.equal(viewHref("mi proyecto", { view: "trabajo", tab: "x", params: { q: 1 } }), "?project=mi+proyecto&view=trabajo&tab=x&q=1");
  assert.equal(aliasNeedsEncoding("mi-proyecto"), false);
  assert.equal(aliasNeedsEncoding("mi proyecto"), true);
  assert.equal(detailLabel("codex"), "Codex");
  assert.equal(detailLabel("sin agente"), "Sin agente");
  assert.equal(detailLabel("runs atribuidos a un paso"), "runs atribuidos a un paso");
});


import { activityText, projectFacts, projectGroups } from "../../orchestrator/static/dashboard/views/home.js";

test("selector de proyecto: registrados aparte, hechos y actividad legibles", () => {
  const groups = projectGroups([
    { alias: "a", registered: true }, { alias: "x", registered: false }, { alias: "b", registered: true },
  ]);
  assert.deepEqual(groups.registered.map((item) => item.alias), ["a", "b"]);
  assert.deepEqual(groups.detected.map((item) => item.alias), ["x"]);
  assert.equal(projectFacts({ active_contexts: 1, contexts: 3, runs: 1200 }), "1 contexto activo · 3 contextos · 1.200 runs");
  assert.equal(projectFacts({ active_contexts: 0, contexts: 0, runs: 0 }), "Sin actividad registrada");
  assert.equal(activityText(null), "Sin actividad");
  assert.match(activityText("2026-06-05T00:00:00+00:00", { timeZone: "UTC" }), /^Última actividad: 05.*jun.*2026$/);
});

import { h } from "../../orchestrator/static/dashboard/core/dom.js";
import { mount } from "../../orchestrator/static/dashboard/views/home.js";

test("sin proyecto, los enlaces de proyecto recargan con ?project= y no los intercepta el shell", async () => {
  class Node {
    constructor(doc, tag) { Object.assign(this, { ownerDocument: doc, tagName: tag, attributes: {}, dataset: {}, className: "", childNodes: [] }); }
    setAttribute(name, value) { this.attributes[name] = value; }
    appendChild(child) { this.childNodes.push(child); return child; }
    replaceChildren(...children) {
      this.childNodes = children.map((child) => (child !== null && typeof child === "object" ? child : { nodeType: 3, text: String(child) }));
    }
    get textContent() { return this.childNodes.map((c) => (c.nodeType === 3 ? c.text : c.textContent)).join(""); }
  }
  const doc = { createElement: (tag) => new Node(doc, tag), createTextNode: (text) => ({ nodeType: 3, text }),
    head: { querySelector: () => ({}), append() {} } };
  h.document = doc;
  try {
    const root = new Node(doc, "div");
    root.addEventListener = () => {};
    root.removeEventListener = () => {};
    const api = { get: async () => ({ projects: [
      { alias: "mi-proyecto", registered: true, has_runs: true, runs: 3, contexts: 1, active_contexts: 1, last_activity: null },
      { alias: "carpeta-suelta", registered: false, has_runs: true, runs: 1, contexts: 0, active_contexts: 0, last_activity: null },
    ] }) };
    await mount(root, { api, state: { project: null }, signal: new AbortController().signal, store: { set() {} } });
    const links = [];
    const walk = (node) => {
      if (!node || node.nodeType === 3) return;
      if (node.tagName === "a") links.push(node);
      for (const child of node.childNodes ?? []) walk(child);
    };
    walk(root);
    assert.deepEqual(links.map((link) => link.attributes.href), ["?project=mi-proyecto&view=inicio", "?project=carpeta-suelta&view=inicio"]);
    assert.ok(links.every((link) => link.dataset.view === undefined));
    assert.match(root.textContent, /Otros alias detectados \(1\)/);
    assert.doesNotMatch(root.textContent, /null|undefined/);
  } finally {
    delete h.document;
  }
});
