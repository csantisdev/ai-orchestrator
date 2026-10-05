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
