// Ejecuta switchTab del dashboard heredado con un DOM mínimo y reporta el resultado.
// Uso: node switch_tab_harness.mjs <core.js>
import { readFileSync } from "node:fs";
import vm from "node:vm";

const core = readFileSync(process.argv[2], "utf8");
const start = core.indexOf("function switchTab(");
const end = core.indexOf("\n}\n", start) + 3;
const flags = ["_proyectosLoaded", "_datosLoaded", "_configLoaded"];
const tabs = ["actividad", "flujos", "proyectos", "datos", "config"];

const elements = {};
const buttons = tabs.map((tab) => {
  const classes = new Set(tab === "actividad" ? ["tab-active"] : []);
  const button = { classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), has: (c) => classes.has(c) } };
  elements[`tab-btn-${tab}`] = button;
  elements[`tab-${tab}`] = { style: { display: tab === "actividad" ? "" : "none" } };
  return button;
});
const calls = [];
const context = {
  document: {
    getElementById: (id) => elements[id],
    querySelectorAll: (selector) => (selector === ".tab-btn" ? buttons : []),
  },
  loadProyectos: () => calls.push("loadProyectos"),
  loadDatos: () => calls.push("loadDatos"),
  loadConfig: () => calls.push("loadConfig"),
  _refreshContexts: () => calls.push("_refreshContexts"),
};
vm.createContext(context);
vm.runInContext(flags.map((f) => `var ${f} = false;`).join("\n") + "\n" + core.slice(start, end), context);

const steps = [];
for (const tab of [...tabs, "proyectos", "datos", "config", "flujos", "actividad"]) {
  calls.length = 0;
  context.switchTab(tab);
  steps.push({
    tab,
    visible: tabs.filter((t) => elements[`tab-${t}`].style.display !== "none"),
    active: tabs.filter((t) => elements[`tab-btn-${t}`].classList.has("tab-active")),
    calls: [...calls],
  });
}
console.log(JSON.stringify(steps));
