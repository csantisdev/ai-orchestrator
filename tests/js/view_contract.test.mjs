import { test } from "node:test";
import assert from "node:assert/strict";

import { ApiError, createApi } from "../../orchestrator/static/dashboard/core/api.js";
import { h, safeUrl } from "../../orchestrator/static/dashboard/core/dom.js";
import { createViewHost } from "../../orchestrator/static/dashboard/core/mount.js";
import { resolveSection } from "../../orchestrator/static/dashboard/core/sections.js";

// Documento mínimo: suficiente para h() y createViewHost sin un DOM real.
class FakeNode {
  constructor(doc, tag) {
    this.ownerDocument = doc;
    this.tagName = tag;
    this.attributes = {};
    this.dataset = {};
    this.className = "";
    this.childNodes = [];
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  appendChild(child) { this.childNodes.push(child); return child; }
  replaceChildren(...children) { this.childNodes = children; }
}

function fakeDocument() {
  const doc = {
    createElement: (tag) => new FakeNode(doc, tag),
    createTextNode: (text) => ({ nodeType: 3, text }),
  };
  return doc;
}

function fakeFetch(status, payload) {
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url, init });
    return { ok: status >= 200 && status < 300, status, json: async () => payload };
  };
  return { fetch, calls };
}

test("api.get arma la URL con parámetros y no manda la cabecera de sesión", async () => {
  const { fetch, calls } = fakeFetch(200, { ok: true });
  const api = createApi({ fetch, sessionToken: () => "tok" });
  assert.deepEqual(await api.get("/api/v1/work", { params: { project: "mi proyecto", ctx: 7, empty: "", none: null } }), { ok: true });
  assert.equal(calls[0].url, "/api/v1/work?project=mi+proyecto&ctx=7");
  assert.equal(calls[0].init.method, "GET");
  assert.equal(calls[0].init.body, undefined);
  assert.equal(calls[0].init.headers["X-Orchestrator-Session"], undefined);
  assert.equal(calls[0].init.credentials, "same-origin");
});

test("api.post manda JSON con la cabecera de sesión vigente", async () => {
  const { fetch, calls } = fakeFetch(200, {});
  let token = "uno";
  const api = createApi({ fetch, sessionToken: () => token });
  token = "dos";
  await api.post("/api/v1/x", { a: 1 });
  assert.equal(calls[0].init.headers["X-Orchestrator-Session"], "dos");
  assert.equal(calls[0].init.headers["Content-Type"], "application/json");
  assert.equal(calls[0].init.body, '{"a":1}');
});

test("api rechaza rutas fuera de /api/v1/", async () => {
  const api = createApi({ fetch: fakeFetch(200, {}).fetch, sessionToken: () => "" });
  for (const path of ["/run-doctor", "/api/v1/../events", "/api/v1//x", "https://evil.example/api/v1/", 7]) {
    await assert.rejects(api.get(path), TypeError, String(path));
  }
});

test("api convierte errores en ApiError con status y motivo", async () => {
  const api = createApi({ fetch: fakeFetch(403, { error: "sesión vencida", reason: "session_expired" }).fetch, sessionToken: () => "" });
  const error = await api.post("/api/v1/x").catch((e) => e);
  assert.ok(error instanceof ApiError);
  assert.equal(error.status, 403);
  assert.equal(error.message, "sesión vencida");
  assert.equal(error.reason, "session_expired");
  const broken = createApi({
    fetch: async () => ({ ok: false, status: 502, json: async () => { throw new SyntaxError("no JSON"); } }),
    sessionToken: () => "",
  });
  const fallback = await broken.get("/api/v1/x").catch((e) => e);
  assert.equal(fallback.message, "HTTP 502");
  assert.equal(fallback.payload, null);
});

test("h escribe texto como nodo de texto y valida atributos", () => {
  h.document = fakeDocument();
  try {
    const node = h("a", { class: ["row", null, "on"], href: "/?view=trabajo", data: { id: 7 }, hidden: true, title: false },
      "<b>x</b>", 3, null, ["y"]);
    assert.equal(node.className, "row on");
    assert.equal(node.attributes.href, "/?view=trabajo");
    assert.equal(node.attributes.hidden, "");
    assert.equal("title" in node.attributes, false);
    assert.deepEqual(node.dataset, { id: "7" });
    assert.deepEqual(node.childNodes.map((c) => c.text), ["<b>x</b>", "3", "y"]);
    for (const props of [{ onclick: "x" }, { ONLOAD: "x" }, { style: "color:red" }, { srcdoc: "x" },
      { href: "javascript:alert(1)" }, { src: " data:text/html,x" }, { href: "//evil.example" }, { data: { "bad-key": 1 } }]) {
      assert.throws(() => h("a", props), TypeError, JSON.stringify(props));
    }
  } finally {
    delete h.document;
  }
});

test("safeUrl acepta rutas relativas y http(s), nada más", () => {
  for (const ok of ["/x", "./x", "../x", "?a=1", "#id", "https://example.org", "HTTP://example.org"]) assert.equal(safeUrl(ok), ok);
  for (const bad of ["javascript:x", "data:x", "vbscript:x", "//host", "/\\host", "x"]) assert.equal(safeUrl(bad), null);
});

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function makeView(log, name) {
  return {
    mount: async (root, { state, signal }) => {
      log.push(`mount ${name} ${state.n}`);
      signal.addEventListener("abort", () => log.push(`abort ${name}`));
      root.replaceChildren(name);
      return { update: (s) => log.push(`update ${name} ${s.n}`), unmount: () => log.push(`unmount ${name}`) };
    },
  };
}

function makeRoot() {
  return new FakeNode(fakeDocument(), "div");
}

test("el host monta, actualiza y desmonta vistas en su propio contenedor", async () => {
  const log = [];
  const root = makeRoot();
  const host = createViewHost({ root, load: async (path) => makeView(log, path.slice(8, -3)) });
  await host.show("trabajo", "./views/work.js", { state: { n: 1 } });
  assert.equal(host.current, "trabajo");
  assert.equal(root.childNodes[0].dataset.view, "trabajo");
  assert.equal(root.childNodes[0].className, "shell-view");
  await host.show("trabajo", "./views/work.js", { state: { n: 2 } });
  await host.show("inicio", "./views/home.js", { state: { n: 3 } });
  await host.hide();
  assert.equal(host.current, null);
  assert.deepEqual(root.childNodes, []);
  assert.deepEqual(log, ["mount work 1", "update work 2", "abort work", "unmount work", "mount home 3", "abort home", "unmount home"]);
});

test("el host rechaza rutas de módulo fuera de ./views/", async () => {
  const host = createViewHost({ root: makeRoot(), load: async () => ({}) });
  for (const path of ["../x.js", "./views/../x.js", "https://evil.example/x.js", "./views/X.js", "./views/a/b.js"]) {
    await assert.rejects(host.show("x", path, { state: {} }), TypeError, path);
  }
  await assert.rejects(host.show("x", "./views/x.js", { state: {} }), /no exporta mount/);
});

test("una carga superada no se monta y su error no pisa la vista nueva", async () => {
  const log = [];
  const root = makeRoot();
  const slow = deferred();
  const host = createViewHost({
    root,
    load: (path) => (path === "./views/slow.js" ? slow.promise : Promise.resolve(makeView(log, "fast"))),
  });
  const first = host.show("lenta", "./views/slow.js", { state: { n: 1 } });
  await host.show("rapida", "./views/fast.js", { state: { n: 2 } });
  slow.reject(new Error("red caída"));
  await first;
  assert.equal(host.current, "rapida");
  assert.equal(root.childNodes[0].dataset.view, "rapida");
  assert.deepEqual(log, ["mount fast 2"]);
});

test("un mount que termina tarde se desmonta y aborta si la vista ya cambió", async () => {
  const log = [];
  const gate = deferred();
  let firstSignal;
  const host = createViewHost({
    root: makeRoot(),
    load: async (path) => (path === "./views/slow.js"
      ? { mount: async (root, { signal }) => { firstSignal = signal; await gate.promise; return { unmount: () => log.push("unmount slow") }; } }
      : makeView(log, "fast")),
  });
  const first = host.show("lenta", "./views/slow.js", { state: { n: 1 } });
  await new Promise((r) => setImmediate(r));
  await host.show("rapida", "./views/fast.js", { state: { n: 2 } });
  assert.equal(firstSignal.aborted, true);
  gate.resolve();
  await first;
  assert.equal(host.current, "rapida");
  assert.deepEqual(log, ["mount fast 2", "unmount slow"]);
});

test("cambios de estado durante el montaje llegan con update, sin recargar", async () => {
  const log = [];
  const gate = deferred();
  let loads = 0;
  const host = createViewHost({ root: makeRoot(), load: async () => { loads += 1; await gate.promise; return makeView(log, "work"); } });
  const first = host.show("trabajo", "./views/work.js", { state: { n: 1 } });
  await host.show("trabajo", "./views/work.js", { state: { n: 2 } });
  gate.resolve();
  await first;
  assert.equal(loads, 1);
  assert.deepEqual(log, ["mount work 1", "update work 2"]);
});

test("un error de la vista vigente se propaga y deja la raíz limpia", async () => {
  const root = makeRoot();
  const host = createViewHost({ root, load: async () => ({ mount: async () => { throw new Error("falló"); } }) });
  await assert.rejects(host.show("x", "./views/x.js", { state: {} }), /falló/);
  assert.equal(host.current, null);
  assert.deepEqual(root.childNodes, []);
});

test("resolveSection prioriza `module` sobre la vista heredada", () => {
  const resolved = resolveSection({ view: "inicio", project: null });
  assert.equal(resolved.module, null);
  assert.equal(resolved.legacy, "metrics");
});
