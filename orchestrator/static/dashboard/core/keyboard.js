// Teclado del shell (spec §8): todo funciona sin mouse y cada atajo tiene una alternativa
// visible (la navegación, la barra de Activity, el menú Acciones › Atajos de teclado). La lista
// de abajo es la única fuente: de ahí salen el manejo de teclas, el diálogo de ayuda y los
// `aria-keyshortcuts`. Sin acceso global al DOM, para `node --test`.

import { h } from "./dom.js";

export const SHORTCUTS = Object.freeze([
  { key: "1", label: "Ir a Inicio", view: "inicio" },
  { key: "2", label: "Ir a Trabajo", view: "trabajo" },
  { key: "3", label: "Ir a Ejecuciones", view: "ejecuciones" },
  { key: "4", label: "Ir a Gobernanza", view: "gobernanza" },
  { key: "a", label: "Abrir o cerrar Activity", command: "toggle-activity" },
  { key: "?", label: "Ver estos atajos", command: "help" },
  { key: "Escape", label: "Cerrar el diálogo, el menú o Activity; si no hay nada abierto, limpiar la selección", command: "escape" },
]);

const TYPING = /^(input|select|textarea)$/i;

export function isTyping(target) {
  return Boolean(target) && (TYPING.test(target.tagName ?? "") || target.isContentEditable === true);
}

// Atajo de una tecla, o null si no corresponde: con modificadores, mientras se escribe en un
// campo o si otro manejador ya la usó. Con el diálogo de atajos abierto solo cuenta Escape.
export function shortcutFor(event, { dialogOpen = false } = {}) {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return null;
  if (isTyping(event.target)) return null;
  if (dialogOpen && event.key !== "Escape") return null;
  return SHORTCUTS.find((shortcut) => shortcut.key === event.key) ?? null;
}

// Qué cierra Escape: lo último que se abrió primero; la selección solo si no hay nada abierto.
// El diálogo se cierra acá también: Chromium no siempre cancela un modal abierto por un atajo.
export function escapeTarget({ dialogOpen = false, menuOpen = false, activityOpen = false, selection = null } = {}) {
  if (dialogOpen) return "dialog";
  if (menuOpen) return "menu";
  if (activityOpen) return "activity";
  if (selection) return "selection";
  return null;
}

export function keyLabel(key) {
  return key === "Escape" ? "Esc" : key.toUpperCase();
}

// Diálogo con los atajos (Acciones › Atajos de teclado o `?`). Se crea una vez y se reutiliza;
// el <dialog> nativo atrapa el foco y se cierra con Escape.
export function shortcutsDialog(doc) {
  const existing = doc.getElementById("shell-shortcuts");
  if (existing) return existing;
  const dialog = h("dialog", { id: "shell-shortcuts", class: "shell-dialog", "aria-labelledby": "shell-shortcuts-title" },
    h("h2", { id: "shell-shortcuts-title", class: "shell-dialog-title" }, "Atajos de teclado"),
    h("p", { class: "shell-dialog-note" }, "No se activan mientras escribís en un campo. Tab y Mayús+Tab recorren todo; Enter y Espacio activan."),
    h("dl", { class: "shell-shortcuts" }, SHORTCUTS.map((shortcut) => [
      h("dt", {}, h("kbd", {}, keyLabel(shortcut.key))),
      h("dd", {}, shortcut.label),
    ])),
    h("form", { method: "dialog" }, h("button", { type: "submit", class: "shell-button", autofocus: true }, "Cerrar")));
  doc.body.append(dialog);
  return dialog;
}

export function openShortcuts(doc) {
  const dialog = shortcutsDialog(doc);
  if (!dialog.open) dialog.showModal?.();
  return dialog;
}
