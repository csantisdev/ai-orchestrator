// Construcción de DOM para las vistas nuevas (spec §23.7, RFC-009 C7).
// Las vistas arman sus elementos con `h()`: el texto entra siempre como nodo de texto,
// nunca como HTML, y no se aceptan handlers en línea, estilos en línea ni URLs
// `javascript:`. Los eventos van por delegación con atributos `data-*`.

const FORBIDDEN_ATTRIBUTE = /^(on|style$|srcdoc$)/i;
const URL_ATTRIBUTES = new Set(["href", "src", "action", "formaction", "xlink:href"]);
// Rutas relativas al mismo origen (sin `//` ni `/\`, que el navegador lee como otro host),
// anclas y http(s). Todo lo demás (javascript:, data:, vbscript:…) se rechaza.
// Los controles (tab, CR, LF…) y `\` se rechazan en cualquier posición: el navegador los
// descarta o los lee como `/`, y `/\t/host` terminaría siendo `//host`.
const SAFE_URL = /^(?:\/(?!\/)|\.{1,2}\/|\?|#|https?:\/\/)/i;
const UNSAFE_CHARACTER = /[\u0000-\u001f\u007f\\]/;

export function safeUrl(value) {
  const raw = String(value);
  if (UNSAFE_CHARACTER.test(raw)) return null;
  const text = raw.trim();
  return SAFE_URL.test(text) ? text : null;
}

function setAttribute(element, name, value) {
  if (FORBIDDEN_ATTRIBUTE.test(name)) throw new TypeError(`atributo no permitido: ${name}`);
  if (value === null || value === undefined || value === false) return;
  if (URL_ATTRIBUTES.has(name.toLowerCase())) {
    const url = safeUrl(value);
    if (url === null) throw new TypeError(`URL no permitida en ${name}`);
    element.setAttribute(name, url);
    return;
  }
  element.setAttribute(name, value === true ? "" : String(value));
}

function append(element, child) {
  if (child === null || child === undefined || child === false) return;
  if (Array.isArray(child)) {
    for (const item of child) append(element, item);
    return;
  }
  if (typeof child === "string" || typeof child === "number") {
    element.appendChild(element.ownerDocument.createTextNode(String(child)));
    return;
  }
  element.appendChild(child);
}

// h("a", { class: "row", href: "/?view=trabajo", data: { id: 7 } }, "Contexto ", name)
export function h(tag, props = {}, ...children) {
  const doc = h.document ?? globalThis.document;
  const element = doc.createElement(tag);
  for (const [name, value] of Object.entries(props ?? {})) {
    if (name === "data") {
      for (const [key, item] of Object.entries(value ?? {})) {
        if (!/^[a-z][a-zA-Z0-9]*$/.test(key)) throw new TypeError(`data-* inválido: ${key}`);
        if (item !== null && item !== undefined) element.dataset[key] = String(item);
      }
    } else if (name === "class") {
      if (value) element.className = Array.isArray(value) ? value.filter(Boolean).join(" ") : String(value);
    } else {
      setAttribute(element, name, value);
    }
  }
  append(element, children);
  return element;
}

const SVG_NS = "http://www.w3.org/2000/svg";
const DATA_KEY = /^[a-z][a-zA-Z0-9]*$/;

function dataAttribute(key) {
  if (!DATA_KEY.test(key)) throw new TypeError(`data-* inválido: ${key}`);
  return `data-${key.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}`;
}

// Elementos SVG (mapa y grafos) con las mismas reglas que `h()`: sin handlers en línea ni
// `style`, URLs seguras y texto como nodo de texto. `class` y `data-*` van como atributos
// (en SVG `className` no es un string).
// svg("rect", { x: 10, y: 4, width: 90, height: 36, class: "map-step" })
export function svg(tag, props = {}, ...children) {
  const doc = h.document ?? globalThis.document;
  const element = doc.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(props ?? {})) {
    if (name === "data") {
      for (const [key, item] of Object.entries(value ?? {})) {
        const attribute = dataAttribute(key);
        if (item !== null && item !== undefined) element.setAttribute(attribute, String(item));
      }
    } else if (name === "class") {
      const text = Array.isArray(value) ? value.filter(Boolean).join(" ") : value;
      if (text) element.setAttribute("class", String(text));
    } else {
      setAttribute(element, name, value);
    }
  }
  append(element, children);
  return element;
}
