/* Tests for the Phase-5 library/browse/place wiring.
 *
 * Run:  node frontend/library.test.js
 *
 * Covers the pure helpers via RWTEST on the real app.js, plus static
 * checks on the three views (ids present, fake-data patterns absent,
 * no invented formats or telemetry).
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
    src + "\nreturn { library, browse, place, RWTEST };"
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

  ["mount", "destroy", "load", "paintAlbums", "openAlbum", "openBurst",
    "paintBurst", "burstFrame", "burstSetCover", "burstCompare", "addFiles",
    "pump", "pollQueue", "correct", "del", "delAll",
  ].forEach((m) => ok(typeof app.library[m] === "function", "library." + m + " exists"));
  ["mount", "search", "paintFacets", "surprise", "toggleGaps"].forEach((m) =>
    ok(typeof app.browse[m] === "function", "browse." + m + " exists"));
  ["mount", "load", "render"].forEach((m) =>
    ok(typeof app.place[m] === "function", "place." + m + " exists"));

  const T = app.RWTEST;

  // ---- fmtBytes ----
  ok(T.fmtBytes(0) === "0 B", "0 bytes");
  ok(T.fmtBytes(512) === "512 B", "bytes");
  ok(T.fmtBytes(2048) === "2 KB", "kilobytes");
  ok(T.fmtBytes(5242880) === "5.0 MB", "megabytes");
  ok(T.fmtBytes(null) === "—", "null size");

  // ---- gapText ----
  ok(T.gapText({ count: 0 }) === "No photos yet — yours could be the first.", "empty gap");
  ok(T.gapText({ count: 3, missing: ["elevated", "interior"] }) ===
    "No elevated view · No interior view.", "missing viewpoints");
  ok(T.gapText({ count: 1, missing: [] }) === "Only one photo.", "single record");
  ok(T.gapText({ count: 5, missing: [] }) === "Covered from every angle.", "covered");

  // ---- static view checks ----
  const read = (v) => fs.readFileSync(path.join(__dirname, "views", v + ".html"), "utf8");
  ["lib-sub", "lib-tabs", "lib-loading", "lib-error", "lib-main", "lib-albums",
    "lib-album-cards", "lib-places-wrap", "lib-places", "lib-bursts-wrap",
    "lib-bursts", "lib-empty", "lib-empty-add", "lib-detail", "lib-back",
    "lib-detail-title", "lib-detail-grid", "lib-burst", "burst-back",
    "burst-title", "burst-main", "burst-tag", "burst-play", "burst-cover",
    "burst-dossier", "burst-strip", "burst-a", "burst-b", "burst-compare",
    "burst-compare-out", "lib-queue", "lib-drop", "lib-choose", "lib-files",
    "lib-pause", "lib-clear", "lib-cancel", "lib-queue-count", "lib-queue-list",
    "lib-manage", "lib-mgr-select", "lib-mgr-dossier", "lib-cor-cap",
    "lib-cor-key", "lib-cor-name", "lib-cor-note", "lib-cor-send",
    "lib-cor-status", "lib-del-btn", "lib-del-status", "lib-export",
    "lib-delall-note", "lib-delall-btn", "lib-delall-status", "tpl-lib-album",
    "tpl-lib-tile", "tpl-queue-row",
  ].forEach((id) => ok(read("library").indexOf('id="' + id + '"') !== -1, "library.html has #" + id));
  ["br-stats", "br-surprise", "br-q", "br-place", "br-themes", "br-vps",
    "br-people", "br-reset", "br-gaps-toggle", "br-gaps", "br-error", "br-count",
    "br-grid", "br-empty", "br-more", "tpl-br-card",
  ].forEach((id) => ok(read("browse").indexOf('id="' + id + '"') !== -1, "browse.html has #" + id));
  ["pl-crumbs", "pl-name", "pl-meta", "pl-coll", "pl-add", "pl-connected",
    "pl-loading", "pl-error", "pl-main", "pl-sections", "pl-signs-wrap",
    "pl-signs", "pl-credits-wrap", "pl-credits", "pl-rel-wrap", "pl-related",
    "pl-empty", "pl-empty-text", "pl-empty-add", "tpl-pl-section", "tpl-pl-plate",
  ].forEach((id) => ok(read("place").indexOf('id="' + id + '"') !== -1, "place.html has #" + id));
  ["library", "browse", "place"].forEach((v) => {
    const txt = read(v);
    ok(!/\sonclick\s*=/.test(txt), "no inline onclick handlers in " + v + ".html");
    const live = txt.replace(/<!--[\s\S]*?-->/g, "");
    ["lh3.googleusercontent", "cadastre.reelworld.org", "sha256", "v2.4",
      "32ms", "Nairobi Edge", "NRB-", "TIFF", "DNG", "16-Bit", "99.2%",
      "f/5.6", "24mm", "NBO-0021"].forEach((s) =>
      ok(live.indexOf(s) === -1, v + ".html free of " + s));
  });

  console.log("library.test.js: " + n + "/" + n + " checks passed");
}

main().catch((e) => { console.error("FAIL:", e.message); process.exit(1); });
