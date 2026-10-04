import { test } from "node:test";
import assert from "node:assert/strict";

import { createStore } from "../../orchestrator/static/dashboard/core/store.js";

test("set notifica con el estado nuevo y el anterior", () => {
  const store = createStore({ view: "inicio", sel: null });
  const calls = [];
  store.subscribe((state, previous) => calls.push([state.view, previous.view]));

  assert.equal(store.set({ view: "trabajo" }), true);

  assert.deepEqual(calls, [["trabajo", "inicio"]]);
  assert.equal(store.get().view, "trabajo");
});

test("set sin cambios no notifica", () => {
  const store = createStore({ view: "inicio" });
  let calls = 0;
  store.subscribe(() => calls++);

  assert.equal(store.set({ view: "inicio" }), false);

  assert.equal(calls, 0);
});

test("el estado es inmutable para quien lo lee", () => {
  const store = createStore({ view: "inicio" });

  assert.throws(() => { "use strict"; store.get().view = "x"; }, TypeError);
});

test("subscribe devuelve la desuscripción", () => {
  const store = createStore({ n: 0 });
  let calls = 0;
  const off = store.subscribe(() => calls++);

  store.set({ n: 1 });
  off();
  store.set({ n: 2 });

  assert.equal(calls, 1);
});
