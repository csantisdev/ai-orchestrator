import { test } from "node:test";
import assert from "node:assert/strict";

import { createStore } from "../../orchestrator/static/dashboard/core/store.js";
import { DEFAULT_VIEW, connectRouter, parseLocation, toSearch } from "../../orchestrator/static/dashboard/core/router.js";

const SHA = "5be88d0c41a7e9f2b3c4d5e6f708192a3b4c5d6e";

test("parseLocation lee el estado completo de §23.3", () => {
  const state = parseLocation(`?project=mi-proyecto&view=trabajo&ctx=21&step=12&as=map&sel=commit:${SHA}`);

  assert.deepEqual(state, {
    project: "mi-proyecto", view: "trabajo", tab: null, ctx: 21, step: 12, as: "map", sel: `commit:${SHA}`,
  });
});

test("parseLocation descarta valores inválidos", () => {
  const state = parseLocation("?view=otra&ctx=0&step=-3&as=grafo&sel=commit:x;alert(1)&tab=A B&project=%0a");

  assert.deepEqual(state, {
    project: null, view: DEFAULT_VIEW, tab: null, ctx: null, step: null, as: null, sel: null,
  });
});

test("toSearch es canónico: orden fijo y sin valores por defecto", () => {
  assert.equal(toSearch({ sel: "run:7", view: "inicio", project: "mi proyecto", ctx: null }), "?project=mi+proyecto&sel=run%3A7");
  assert.equal(toSearch({ view: DEFAULT_VIEW }), "");
});

test("parseLocation y toSearch son inversas para estados válidos", () => {
  const state = { project: "mi-proyecto", view: "ejecuciones", tab: "costos", ctx: null, step: null, as: null, sel: "run:42" };

  assert.deepEqual(parseLocation(toSearch(state)), state);
});

function fakeBrowser(search) {
  const location = { pathname: "/", search };
  const entries = [search];
  let popstate = null;
  const history = {
    pushState(_s, _t, url) { location.search = url.slice(1); entries.push(location.search); },
    replaceState(_s, _t, url) { location.search = url.slice(1); entries[entries.length - 1] = location.search; },
  };
  return {
    location, history, entries,
    addEventListener: (name, fn) => { if (name === "popstate") popstate = fn; },
    back(to) { entries.pop(); location.search = to; popstate(); },
  };
}

test("connectRouter canonicaliza la URL inicial sin agregar entradas", () => {
  const browser = fakeBrowser("?sel=run:7&view=trabajo&ctx=abc");
  const store = createStore({});

  connectRouter({ store, ...browser });

  assert.equal(browser.location.search, "?view=trabajo&sel=run%3A7");
  assert.equal(browser.entries.length, 1);
  assert.equal(store.get().view, "trabajo");
});

test("un cambio de estado agrega una entrada y Atrás lo restaura", () => {
  const browser = fakeBrowser("?view=trabajo");
  const store = createStore({});
  connectRouter({ store, ...browser });

  store.set({ view: "ejecuciones", tab: "costos" });
  assert.deepEqual(browser.entries, ["?view=trabajo", "?view=ejecuciones&tab=costos"]);

  browser.back("?view=trabajo");
  assert.equal(store.get().view, "trabajo");
  assert.equal(store.get().tab, null);
  assert.deepEqual(browser.entries, ["?view=trabajo"]);
});
