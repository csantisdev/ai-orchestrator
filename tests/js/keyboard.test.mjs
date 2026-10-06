import { test } from "node:test";
import assert from "node:assert/strict";

import { h } from "../../orchestrator/static/dashboard/core/dom.js";
import {
  SHORTCUTS, escapeTarget, isTyping, keyLabel, openShortcuts, shortcutFor, shortcutsDialog,
} from "../../orchestrator/static/dashboard/core/keyboard.js";
import { ACTIONS } from "../../orchestrator/static/dashboard/core/actions.js";

const key = (value, extra = {}) => ({ key: value, target: { tagName: "BODY" }, ...extra });

test("shortcutFor: teclas del catálogo, sin modificadores ni mientras se escribe", () => {
  assert.equal(shortcutFor(key("2")).view, "trabajo");
  assert.equal(shortcutFor(key("a")).command, "toggle-activity");
  assert.equal(shortcutFor(key("?")).command, "help");
  assert.equal(shortcutFor(key("Escape")).command, "escape");
  assert.equal(shortcutFor(key("x")), null);
  for (const modifier of ["ctrlKey", "metaKey", "altKey", "defaultPrevented"]) {
    assert.equal(shortcutFor(key("1", { [modifier]: true })), null, modifier);
  }
  for (const tagName of ["INPUT", "select", "TEXTAREA"]) {
    assert.equal(shortcutFor(key("1", { target: { tagName } })), null, tagName);
  }
  assert.equal(shortcutFor(key("a", { target: { tagName: "DIV", isContentEditable: true } })), null);
  assert.equal(isTyping(null), false);
  // Con el diálogo abierto, solo Escape.
  assert.equal(shortcutFor(key("2"), { dialogOpen: true }), null);
  assert.equal(shortcutFor(key("Escape"), { dialogOpen: true }).command, "escape");
});

test("las secciones del catálogo son las cuatro del proyecto y no se repiten teclas", () => {
  assert.deepEqual(SHORTCUTS.filter((item) => item.view).map((item) => [item.key, item.view]),
    [["1", "inicio"], ["2", "trabajo"], ["3", "ejecuciones"], ["4", "gobernanza"]]);
  const keys = SHORTCUTS.map((item) => item.key);
  assert.equal(new Set(keys).size, keys.length);
  assert.ok(SHORTCUTS.every((item) => item.label && (item.view || item.command)));
});

test("escapeTarget cierra lo último abierto y la selección solo al final", () => {
  assert.equal(escapeTarget({ dialogOpen: true, menuOpen: true, selection: "run:1" }), "dialog");
  assert.equal(escapeTarget({ menuOpen: true, activityOpen: true, selection: "run:1" }), "menu");
  assert.equal(escapeTarget({ activityOpen: true, selection: "run:1" }), "activity");
  assert.equal(escapeTarget({ selection: "run:1" }), "selection");
  assert.equal(escapeTarget({}), null);
  assert.equal(keyLabel("Escape"), "Esc");
  assert.equal(keyLabel("a"), "A");
});

class FakeNode {
  constructor(doc, tag) {
    this.ownerDocument = doc;
    this.tagName = tag;
    this.attributes = {};
    this.dataset = {};
    this.childNodes = [];
    this.open = false;
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  appendChild(child) { this.childNodes.push(child); return child; }
  append(child) { this.childNodes.push(child); }
  showModal() { this.open = true; }
  get textContent() { return this.childNodes.map((c) => (c.nodeType === 3 ? c.text : c.textContent)).join(""); }
}

function fakeDocument() {
  const byId = new Map();
  const doc = {
    createElement: (tag) => new FakeNode(doc, tag),
    createTextNode: (text) => ({ nodeType: 3, text }),
    getElementById: (id) => byId.get(id) ?? null,
  };
  doc.body = new FakeNode(doc, "body");
  doc.body.append = (child) => { doc.body.childNodes.push(child); byId.set(child.attributes.id, child); };
  return doc;
}

test("el diálogo de atajos sale del catálogo, se crea una vez y lo abre la acción del menú", () => {
  const doc = fakeDocument();
  h.document = doc;
  try {
    const dialog = shortcutsDialog(doc);
    for (const shortcut of SHORTCUTS) assert.match(dialog.textContent, new RegExp(shortcut.label.replace(/[?()]/g, "\\$&")));
    assert.match(dialog.textContent, /Esc/);
    assert.equal(shortcutsDialog(doc), dialog);
    assert.equal(doc.body.childNodes.length, 1);
    ACTIONS.shortcuts({ doc, store: { set() {} } });
    assert.equal(dialog.open, true);
    assert.equal(openShortcuts(doc), dialog);
  } finally {
    delete h.document;
  }
});
