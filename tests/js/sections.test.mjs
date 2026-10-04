import { test } from "node:test";
import assert from "node:assert/strict";

import { GROUPS, SECTIONS, describeSelection, resolveSection } from "../../orchestrator/static/dashboard/core/sections.js";
import { VIEWS } from "../../orchestrator/static/dashboard/core/router.js";

test("las secciones son las 4 + 3 de §23.3, en el orden del router", () => {
  assert.deepEqual(SECTIONS.map((s) => s.id), [...VIEWS]);
  assert.deepEqual(SECTIONS.filter((s) => s.group === "proyecto").map((s) => s.label),
    ["Inicio", "Trabajo", "Ejecuciones", "Gobernanza"]);
  assert.deepEqual(SECTIONS.filter((s) => s.group === "control").map((s) => s.label),
    ["Proveedores", "Políticas", "Ajustes"]);
  assert.deepEqual(GROUPS.map((g) => g.id), ["proyecto", "control"]);
});

test("cada sección muestra una vista heredada o un estado vacío, nunca ambos ni ninguno", () => {
  const legacyTabs = new Set();
  for (const section of SECTIONS) {
    for (const tab of section.tabs ?? [{ legacy: section.legacy }]) {
      const resolved = resolveSection({ view: section.id, tab: tab.id ?? null, project: null });
      assert.equal(Boolean(resolved.legacy) !== Boolean(resolved.empty), true, section.id);
      if (resolved.legacy) legacyTabs.add(resolved.legacy);
    }
  }
  assert.deepEqual([...legacyTabs].sort(), ["actividad", "config", "datos", "flujos", "metrics", "proyectos"]);
});

test("resolveSection arma el breadcrumb y cae en valores válidos", () => {
  assert.deepEqual(resolveSection({ view: "trabajo", project: "mi-proyecto" }).crumbs, ["mi-proyecto", "Trabajo"]);
  assert.deepEqual(resolveSection({ view: "ajustes", tab: "datos", project: null }).crumbs,
    ["Todos los proyectos", "Ajustes", "Datos"]);
  const fallback = resolveSection({ view: "ajustes", tab: "otra", project: null });
  assert.equal(fallback.tab.id, "proyectos");
  assert.equal(fallback.legacy, "proyectos");
  assert.equal(resolveSection({ view: "nada", project: null }).section.id, "inicio");
});

test("describeSelection da una etiqueta corta y el id completo", () => {
  const sha = "5be88d0c41a7e9f2b3c4d5e6f708192a3b4c5d6e";
  assert.deepEqual(describeSelection(`commit:${sha}`), { label: "Commit", id: "5be88d0", full: sha });
  assert.deepEqual(describeSelection("run:42"), { label: "Run", id: "#42", full: "42" });
  assert.deepEqual(describeSelection("decision:mcp-881"), { label: "Decisión", id: "mcp #881", full: "mcp-881" });
  assert.equal(describeSelection(null), null);
});
