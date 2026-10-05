import { test } from "node:test";
import assert from "node:assert/strict";

import { h } from "../../orchestrator/static/dashboard/core/dom.js";
import { dataTable, familyClass, metricCard, noticeList, panel, progress, segmented } from "../../orchestrator/static/dashboard/core/ui.js";
import { metricSub } from "../../orchestrator/static/dashboard/views/home.js";
import { costDays } from "../../orchestrator/static/dashboard/views/costs.js";

class Node {
  constructor(doc, tag) { Object.assign(this, { ownerDocument: doc, tagName: tag, attributes: {}, dataset: {}, className: "", childNodes: [] }); }
  setAttribute(name, value) { this.attributes[name] = value; }
  appendChild(child) { this.childNodes.push(child); return child; }
  get textContent() { return this.childNodes.map((c) => (c.nodeType === 3 ? c.text : c.textContent)).join(""); }
}

function withDoc(fn) {
  const doc = { createElement: (tag) => new Node(doc, tag), createTextNode: (text) => ({ nodeType: 3, text }) };
  h.document = doc;
  try { return fn(); } finally { delete h.document; }
}

const all = (node, tag, found = []) => {
  if (node && node.nodeType !== 3) {
    if (node.tagName === tag) found.push(node);
    for (const child of node.childNodes ?? []) all(child, tag, found);
  }
  return found;
};

test("familyClass acepta solo las familias de §4.3", () => {
  assert.equal(familyClass("governance"), "family-governance");
  assert.equal(familyClass("<x>"), "family-neutral");
  assert.equal(familyClass(undefined), "family-neutral");
});

test("metricCard: enlace con familia, tono y dato corto", () => withDoc(() => {
  const card = metricCard({ family: "decision", label: "Pasos estancados", value: "1", sub: "paso 31", href: "?view=trabajo",
    data: { view: "trabajo" }, tone: "warn", title: "origen" });
  assert.equal(card.tagName, "a");
  assert.equal(card.className, "metric-card family-decision is-warn");
  assert.equal(card.attributes.href, "?view=trabajo");
  assert.equal(card.attributes.title, "origen");
  assert.equal(card.dataset.view, "trabajo");
  assert.equal(card.textContent, "Pasos estancados1paso 31");
  const plain = metricCard({ family: "work", label: "L", value: "2" });
  assert.equal(plain.tagName, "div");
  assert.equal(plain.textContent, "L2");
}));

test("segmented marca la opción elegida y usa el atributo de la vista", () => withDoc(() => {
  const group = segmented({ label: "Período", options: [["7d", "7 días"], ["30d", "30 días"]], current: "30d", attribute: "period" });
  assert.equal(group.attributes.role, "group");
  const buttons = all(group, "button");
  assert.deepEqual(buttons.map((b) => [b.dataset.period, b.attributes["aria-pressed"]]), [["7d", "false"], ["30d", "true"]]);
}));

test("dataTable, panel, progress y noticeList", () => withDoc(() => {
  assert.equal(dataTable({ label: "T", columns: [], rows: [], empty: "Vacío" }).textContent, "Vacío");
  const table = dataTable({ label: "T", columns: [{ label: "A" }, { label: "N", numeric: true }],
    rows: [{ cells: ["<b>x</b>", "3"], selected: true }], empty: "" });
  assert.equal(all(table, "td")[1].className, "is-numeric");
  assert.equal(all(table, "tr")[1].className, "is-selected");
  assert.equal(all(table, "td")[0].textContent, "<b>x</b>");
  assert.equal(panel("Por motivo", "x").textContent, "Por motivox");
  const bar = progress({ value: 12, max: 10, label: "L" });
  assert.deepEqual([bar.attributes.max, bar.attributes.value], ["10", "10"]);
  assert.equal(progress({ value: 1, max: 0, label: "L" }).attributes.max, "1");
  assert.equal(noticeList([], "Nada").textContent, "Nada");
  assert.equal(noticeList([{ family: "decision", title: "T", hint: "H" }], "").textContent, "!TH");
}));

test("Inicio y Costos: datos cortos", () => {
  assert.equal(metricSub({ id: "cost_period", detail: [{ label: "runs", value: 124 }, { label: "runs atribuidos a un paso", value: 35 }] }),
    "124 runs · 35 atribuidos a pasos");
  assert.equal(metricSub({ id: "agent_activity_24h", detail: [{ label: "claude", value: 2 }, { label: "codex", value: 1 }] }), "Claude 2 · Codex 1");
  assert.equal(metricSub({ id: "active_contexts", detail: [] }), null);
  const days = costDays([{ date: "2026-06-01", cost_usd: 0 }, { date: "2026-06-02", cost_usd: 2 }, { date: "2026-06-03", cost_usd: 1 }]);
  assert.deepEqual(days.withCost.map((d) => [d.date, d.max]), [["2026-06-02", 2], ["2026-06-03", 2]]);
  assert.equal(days.empty, 1);
});
