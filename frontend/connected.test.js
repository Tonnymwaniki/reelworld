/* Tests for the Phase-3 connected view wiring.
 *
 * Run:  node frontend/connected.test.js
 *
 * Covers the pure ring/evidence helpers via RWTEST on the real app.js,
 * plus static checks on views/connected.html (ids present, fake-data
 * patterns absent, ring SVG intact).
 */
"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

function stubEl() {
  return {
    dataset: {},
    style: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {},
    appendChild() {},
    prepend() {},
    remove() {},
    querySelector() { return stubEl(); },
    querySelectorAll() { return []; },
    closest() { return stubEl(); },
    innerHTML: "",
    textContent: "",
    value: "",
  };
}

async function main() {
  let n = 0;
  const ok = (cond, msg) => { n++; assert.ok(cond, msg); };

  const src = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
  const factory = new Function(
    "fetch", "document", "window", "location",
    src + "\nreturn { connected, RWTEST };"
  );
  const documentStub = {
    querySelector: () => stubEl(),
    querySelectorAll: () => [],
    getElementById: () => stubEl(),
    createElement: () => stubEl(),
    addEventListener() {},
    body: stubEl(),
  };
  const fetchStub = async () => ({ ok: true, json: async () => ({}), text: async () => "" });
  const app = factory(fetchStub, documentStub, { addEventListener() {} }, { hash: "#/" });
  await new Promise((r) => setTimeout(r, 150));

  ["mount", "showTab", "load", "paintOverview", "selectAnchor", "paintStage",
    "paintRows", "selectLink", "runExplain", "explainPair",
  ].forEach((m) => ok(typeof app.connected[m] === "function", "connected." + m + " exists"));

  const T = app.RWTEST;

  // ---- ringLayout ----
  const solo = T.ringLayout(0, 0, 1);
  ok(solo.x === 250 && solo.y === 192, "R1 single node sits at the top: " + JSON.stringify(solo));
  let inBounds = true;
  for (let r = 0; r < 5; r++) {
    for (let i = 0; i < 8; i++) {
      const p = T.ringLayout(r, i, 8);
      if (p.x < 0 || p.x > 500 || p.y < 0 || p.y > 500) inBounds = false;
    }
  }
  ok(inBounds, "all 40 node slots stay inside the 500x500 viewBox");
  const outer = T.ringLayout(4, 2, 8);
  const dist = Math.hypot(outer.x - 250, outer.y - 250);
  ok(Math.abs(dist - 230) < 0.2, "R5 nodes sit on radius 230: " + dist);
  const inner = T.ringLayout(0, 3, 8);
  ok(Math.abs(Math.hypot(inner.x - 250, inner.y - 250) - 58) < 0.2, "R1 nodes sit on radius 58");

  // ---- ringLabel ----
  ok(T.ringLabel(0, 0) === "1A", "first label is 1A");
  ok(T.ringLabel(4, 7) === "5H", "last label is 5H");

  // ---- KIND_LABEL ----
  ok(Object.keys(T.KIND_LABEL).length === 6, "6 kind labels");

  // ---- evidenceRows ----
  const full = T.evidenceRows(
    { same_place: true, place_name: "City Hall", taken_cross: true,
      shared_landmarks: ["Tower"], shared_signs: ["city hall"], shared_entities: ["bus"] },
    "Ground level", "Elevated");
  const labels = full.map((r) => r.label);
  ok(labels.includes("Same place") && labels.includes("Different viewpoint") &&
    labels.includes("Where you stood") && labels.includes("Shared landmark") &&
    labels.includes("Shared sign text") && labels.includes("Same things visible"),
    "full facts yield 6 rows: " + labels.join(","));
  ok(full.every((r) => r.icon && r.text), "every row has icon + text");
  const none = T.evidenceRows({}, "Ground level", "Ground level");
  ok(none.length === 1 && none[0].label === "No shared evidence", "empty facts yield one honest row");

  // ---- static view checks ----
  const view = fs.readFileSync(path.join(__dirname, "views", "connected.html"), "utf8");
  ["connected-title", "connected-sub", "connected-refresh", "conn-tabs",
    "connected-grid", "conn-overview", "ov-captures", "ov-counterparts",
    "ov-places-n", "ov-gaps", "ov-legend", "ov-places", "ov-self", "ov-self-list",
    "conn-rings", "ring-count", "ring-search", "ring-captures", "ring-centre-label",
    "ring-back", "ring-history-count", "ring-stage", "ring-threads", "ring-nodes",
    "ring-centre-img", "ring-centre-tag", "ring-counts", "ring-rows",
    "ring-evidence", "ev-title", "ev-badge", "ev-close", "ev-explain", "ev-recentre",
    "conn-explain", "ex-a-list", "ex-b-list", "ex-b-hint", "ex-run", "ex-result",
    "ex-verdict", "ex-text", "ex-icon", "ex-chain", "ex-evidence", "ex-open-rings",
    "connected-loading", "connected-empty", "connected-error", "connected-error-text",
    "connected-retry", "tpl-capture", "tpl-ov-place", "tpl-self-pair", "tpl-ring-row",
    "tpl-ev-row", "tpl-ex-opt",
  ].forEach((id) => ok(view.indexOf('id="' + id + '"') !== -1, "connected.html has #" + id));
  ["a-img", "a-cap", "b-img", "b-cap", "rows"].forEach((s) =>
    ok(view.indexOf('data-ev="' + s + '"') !== -1, "evidence slot " + s));
  ["a-img", "b-img", "anchor", "credit"].forEach((s) =>
    ok(view.indexOf('data-ex="' + s + '"') !== -1, "explain slot " + s));
  ok(view.indexOf('viewBox="0 0 500 500"') !== -1, "ring SVG keeps the design viewBox");
  [58, 95, 140, 185, 230].forEach((r) =>
    ok(view.indexOf('r="' + r + '"') !== -1, "ring radius " + r + " present"));
  ok(!/\sonclick\s*=/.test(view), "no inline onclick handlers in connected.html");
  const live = view.replace(/<!--[\s\S]*?-->/g, "");
  ["lh3.googleusercontent", "cadastre.reelworld.org", "sha256", "v2.4",
    "NBO-0021", "18°", "+28m"].forEach((s) => ok(live.indexOf(s) === -1, "connected.html free of " + s));

  console.log("connected.test.js: " + n + "/" + n + " checks passed");
}

main().catch((e) => { console.error("FAIL:", e.message); process.exit(1); });
