// Representación Lista (spec §23.2): la representación por defecto y la equivalente
// accesible de cualquier colección. Cada objeto aporta su fila (§23.1); este módulo solo
// arma la lista, el estado vacío y las etiquetas de estado.

import { h } from "../core/dom.js";

const STATE_CLASS = /^[a-z][a-z0-9_]{0,31}$/;

// Clase CSS del estado: solo tokens conocidos; cualquier otro valor cae en `other`.
export function stateClass(status) {
  return typeof status === "string" && STATE_CLASS.test(status) ? `state-${status.replace(/_/g, "-")}` : "state-other";
}

export function statusPill(status, labels) {
  return h("span", { class: ["pill", stateClass(status)] }, labels[status] ?? (status || "—"));
}

// Lista de objetos; `renderRow(item)` devuelve el contenido de la fila.
export function objectList(items, renderRow, { label, empty }) {
  if (!items.length) return h("p", { class: "object-list-empty" }, empty);
  return h("ul", { class: "object-list", "aria-label": label },
    items.map((item) => h("li", { class: "object-row" }, renderRow(item))));
}

// Fila de métricas cortas ("3 alineamientos", "1 desvío"): omite las que valen cero.
export function facts(entries) {
  const visible = entries.filter(([count]) => count > 0);
  if (!visible.length) return null;
  return h("span", { class: "object-facts" },
    visible.map(([count, singular, plural]) => h("span", { class: "object-fact" }, `${count} ${count === 1 ? singular : plural}`)));
}
