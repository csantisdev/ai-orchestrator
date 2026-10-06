// Componentes compartidos de las vistas (spec §23.5, maqueta v5): tarjeta de métrica,
// segmentado, panel, tabla y barra de progreso. Devuelven nodos armados con `h()`; los
// estilos viven en components.css. Ninguna vista define su propia versión de estos.

import { h } from "./dom.js";

// Familias de §4.3. Una familia desconocida cae en `neutral`.
export const FAMILIES = Object.freeze(["knowledge", "work", "decision", "execution", "governance", "error", "neutral"]);

export function familyClass(family) {
  return `family-${FAMILIES.includes(family) ? family : "neutral"}`;
}

// Tarjeta de métrica: etiqueta con el punto de su familia, valor grande y un dato corto.
// Con `href` es un enlace (y `data` para que el shell navegue sin recargar).
export function metricCard({ family, label, value, sub = null, title = null, href = null, data = null, tone = null }) {
  return h(href ? "a" : "div", {
    class: ["metric-card", familyClass(family), tone && `is-${tone}`],
    href: href ?? undefined,
    data: data ?? undefined,
    title: title ?? undefined,
  },
  h("span", { class: "metric-label" }, label),
  h("strong", { class: "metric-value" }, value),
  sub ? h("span", { class: "metric-sub" }, sub) : null);
}

export function metricGrid(cards) {
  return h("div", { class: "metric-grid" }, cards);
}

// Grupo de botones excluyentes; el elegido lleva `aria-pressed="true"`. `attribute` es la
// clave de `data-*` que la vista lee por delegación (p. ej. "period" → data-period). Una opción
// `[value, text, { disabled, reason }]` se muestra deshabilitada con el motivo como título.
export function segmented({ label, options, current, attribute }) {
  return h("div", { class: "segmented", role: "group", "aria-label": label },
    options.map(([value, text, extra = {}]) => h("button", {
      type: "button",
      data: { [attribute]: value },
      "aria-pressed": String(value === current),
      disabled: Boolean(extra.disabled),
      title: extra.reason ?? undefined,
      "aria-description": extra.reason ?? undefined,
    }, text)));
}

// Panel con etiqueta en mayúsculas (la `label` de la maqueta).
export function panel(label, ...children) {
  return h("section", { class: "panel" }, label ? h("h3", { class: "panel-label" }, label) : null, children);
}

// Tabla con encabezados de la maqueta y scroll horizontal propio en pantallas chicas.
// `columns`: [{ label, numeric }]; `rows`: [{ cells: [...], data, selected }].
export function dataTable({ label, columns, rows, empty }) {
  if (!rows.length) return h("p", { class: "empty-note" }, empty);
  return h("div", { class: "table-wrap" },
    h("table", { class: "data-table", "aria-label": label },
      h("thead", {}, h("tr", {}, columns.map((column) => h("th", { class: column.numeric ? "is-numeric" : null }, column.label)))),
      h("tbody", {}, rows.map((row) => h("tr", { class: row.selected ? "is-selected" : null, data: row.data ?? undefined },
        row.cells.map((cell, index) => h("td", { class: columns[index]?.numeric ? "is-numeric" : null }, cell)))))));
}

// Barra de progreso o proporción con `<meter>` (sin estilos en línea).
export function progress({ value, max, label }) {
  const safeMax = max > 0 ? max : 1;
  return h("meter", { class: "progress", min: 0, max: safeMax, value: Math.min(Math.max(value, 0), safeMax), "aria-label": label },
    `${value} de ${max}`);
}

// Lista con viñetas por estado ("✓", "!", "·") como la de Salud del tracking de la maqueta.
export function noticeList(items, empty) {
  if (!items.length) return h("p", { class: "empty-note" }, empty);
  return h("ul", { class: "notice-list" }, items.map((item) => h("li", { class: familyClass(item.family) },
    h("span", { class: "notice-icon", "aria-hidden": "true" }, item.icon ?? "!"),
    h("span", { class: "notice-body" }, h("strong", {}, item.title), item.hint ? h("span", {}, item.hint) : null))));
}

// Estados especiales (spec §7): cada uno con icono y texto, nunca solo color. `failure` es un
// error técnico (alerta); `blocked`, una decisión de política (escudo, no es error);
// `degraded` y `desync` avisan sin bloquear; `empty` explica qué falta y cómo seguir.
const STATE_NOTICES = Object.freeze({
  degraded: { icon: "◌", role: "status" },
  blocked: { icon: "⛨", role: null },
  failure: { icon: "!", role: "alert" },
  desync: { icon: "⟳", role: "status" },
  empty: { icon: "○", role: null },
});

export function stateNotice(kind, title, body = null, ...extra) {
  const known = STATE_NOTICES[kind] ? kind : "empty";
  const { icon, role } = STATE_NOTICES[known];
  return h("section", { class: ["state-notice", `is-${known}`], role: role ?? undefined },
    h("span", { class: "state-notice-icon", "aria-hidden": "true" }, icon),
    h("div", { class: "state-notice-body" },
      h("h2", { class: "state-notice-title" }, title),
      body ? h("p", {}, body) : null,
      extra));
}
