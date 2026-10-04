import test from "node:test";
import assert from "node:assert/strict";
import { aliasNeedsEncoding, formatNumber, formatUsd, periodText, viewHref } from "../../orchestrator/static/dashboard/views/home.js";

test("formatos y período usan es-CL", () => {
  assert.equal(formatNumber(1234), "1.234");
  assert.match(formatUsd(12.5), /US\$|USD/);
  assert.equal(periodText("30d"), "Últimos 30 días");
});
test("links y aliases", () => {
  assert.equal(viewHref("mi-proyecto", { view: "trabajo", tab: null, params: {} }), "?project=mi-proyecto&view=trabajo");
  assert.equal(viewHref("mi proyecto", { view: "trabajo", tab: "x", params: { q: 1 } }), "?project=mi+proyecto&view=trabajo&tab=x&q=1");
  assert.equal(aliasNeedsEncoding("mi-proyecto"), false);
  assert.equal(aliasNeedsEncoding("mi proyecto"), true);
});
