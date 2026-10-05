import { test } from "node:test";
import assert from "node:assert/strict";

import { createPageTitles, deniedText, navCounts } from "../../orchestrator/static/dashboard/core/page.js";

test("page.set vale solo para el montaje vigente de la vista", () => {
  let changes = 0;
  const titles = createPageTitles(() => { changes += 1; });
  titles.enter("trabajo:contextos");
  const first = titles.pageFor("trabajo:contextos");
  first.set({ title: "Contexto #1", subtitle: "x" });
  assert.deepEqual(titles.current, { title: "Contexto #1", subtitle: "x" });
  // Salir y volver a la misma vista: el montaje anterior ya no puede tocar el título.
  titles.enter("inicio");
  assert.equal(titles.current, null);
  titles.enter("trabajo:contextos");
  const second = titles.pageFor("trabajo:contextos");
  first.set({ title: "tarde" });
  assert.equal(titles.current, null);
  second.set({ title: "Contexto #2" });
  assert.deepEqual(titles.current, { title: "Contexto #2", subtitle: null });
  // Otra clave tampoco.
  titles.pageFor("gobernanza:acceso").set({ title: "ajeno" });
  assert.equal(titles.current.title, "Contexto #2");
  // Misma clave sin salir: el montaje sigue vigente.
  titles.enter("trabajo:contextos");
  second.set({});
  assert.deepEqual(titles.current, { title: null, subtitle: null });
  assert.equal(changes, 3);
});

test("contadores y aviso del header", () => {
  const projects = [{ alias: "mi-proyecto", active_contexts: 0, runs: 12 }];
  assert.deepEqual(navCounts(projects, "mi-proyecto"), { trabajo: 0, ejecuciones: 12 });
  assert.deepEqual(navCounts(projects, "otro"), { trabajo: null, ejecuciones: null });
  assert.equal(deniedText({ mcp: { denied: 0, error: 0 } }), null);
  assert.equal(deniedText({ mcp: { denied: 1, error: 0 } }), "1 denegada o con error · 7 d");
  assert.equal(deniedText({ mcp: { denied: 2, error: 3 } }), "5 denegadas o con error · 7 d");
  assert.equal(deniedText(null), null);
});

test("si la vista falla y se vuelve a montar con la misma clave, el montaje fallido no toca el título", () => {
  const titles = createPageTitles();
  titles.enter("trabajo:contextos");
  const failed = titles.pageFor("trabajo:contextos");
  titles.restart();
  const next = titles.pageFor("trabajo:contextos");
  failed.set({ title: "tarde" });
  assert.equal(titles.current, null);
  next.set({ title: "nuevo" });
  assert.equal(titles.current.title, "nuevo");
});

import { ACTIONS, runAction } from "../../orchestrator/static/dashboard/core/actions.js";

function fakeDoc() {
  const focused = [];
  const element = (id) => ({ id, classList: { added: [], add(name) { this.added.push(name); } }, scrollIntoView() {}, focus() { focused.push(id); } });
  const nodes = { senderPanel: element("senderPanel"), senderTask: element("senderTask"), ctxTitle: element("ctxTitle"), "shell-menu": { open: true } };
  return { doc: { getElementById: (id) => nodes[id] ?? null }, nodes, focused };
}

test("acciones del menú: navegan a la pestaña heredada, abren el formulario y cierran el menú", () => {
  const sets = [];
  const store = { set: (patch) => sets.push(patch) };
  const task = fakeDoc();
  assert.equal(runAction("new-task", { store, doc: task.doc }), true);
  assert.deepEqual(sets.at(-1), { view: "ejecuciones", tab: "actividad" });
  assert.deepEqual(task.nodes.senderPanel.classList.added, ["open"]);
  assert.deepEqual(task.focused, ["senderTask"]);
  assert.equal(task.nodes["shell-menu"].open, false);
  const flow = fakeDoc();
  runAction("new-flow", { store, doc: flow.doc });
  assert.deepEqual(sets.at(-1), { view: "trabajo", tab: "flujos" });
  assert.deepEqual(flow.focused, ["ctxTitle"]);
  runAction("clear-selection", { store, doc: flow.doc });
  assert.deepEqual(sets.at(-1), { sel: null });
  assert.equal(runAction("desconocida", { store, doc: flow.doc }), false);
  // Sin los paneles heredados en la página, no falla.
  runAction("new-task", { store, doc: { getElementById: () => null } });
  assert.deepEqual(Object.keys(ACTIONS), ["clear-selection", "new-task", "new-flow"]);
});
