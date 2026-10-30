/* Tests for the Phase-1 Reel thread wiring (no framework needed).
 *
 * Run:  node frontend/home.test.js
 *
 * Covers the pure helpers the thread, credits and about views share
 * (SSE parsing, spec chips, citations, formatting) plus a boot smoke
 * test that loads the real app.js with stubbed browser globals and
 * checks the real boot/mount flow requests the right URLs.
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

  // ---- boot smoke: load the real app.js with stubs ----
  const calls = [];
  const fetchStub = async (url) => {
    calls.push(String(url));
    let body = {};
    if (String(url) === "/api/config") {
      body = { demo_mode: true, counts: { world: 132, personal: 16, places: 26, themes: 6 } };
    } else if (String(url).indexOf("/api/photo/") === 0) {
      body = { photo_id: "landmarks_003", collection: "world", caption: "tower",
        place: { name: "KICC", status: "confirmed", evidence: [{ detail: "e" }] },
        uncertainties: ["u"], credit: { author: "A", license: "L" } };
    }
    return { ok: true, json: async () => body, text: async () => "" };
  };
  const documentStub = {
    querySelector: () => stubEl(),
    querySelectorAll: () => [],
    getElementById: () => stubEl(),
    createElement: () => stubEl(),
    addEventListener() {},
    body: stubEl(),
  };
  const src = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
  const factory = new Function(
    "fetch", "document", "window", "location",
    src + "\nreturn { home, credits, about, RWTEST };"
  );
  const app = factory(fetchStub, documentStub, { addEventListener() {} }, { hash: "#/" });
  await new Promise((r) => setTimeout(r, 150));

  ok(typeof app.home.mount === "function", "home.mount exists");
  ok(typeof app.credits.mount === "function", "credits.mount exists");
  ok(typeof app.about.mount === "function", "about.mount exists");
  ok(calls.includes("/api/config"), "boot fetches /api/config, got: " + calls.join(","));
  ok(calls.includes("/views/home.html"), "boot loads the home view");
  ok(calls.includes("/api/photo/landmarks_003"), "landing fills the trust sample");

  const T = app.RWTEST;

  // ---- sseParseChunk ----
  let p = T.sseParseChunk('event: step\ndata: {"step":"understood"}\n\npartial');
  ok(p.events.length === 1 && p.events[0].event === "step", "one step event parsed");
  ok(p.events[0].data === '{"step":"understood"}', "event data intact");
  ok(p.rest === "partial", "incomplete tail carried over");
  p = T.sseParseChunk('data: hello\n\n');
  ok(p.events.length === 1 && p.events[0].event === "message" && p.events[0].data === "hello", "default event name");
  ok(p.rest === "", "buffer drains on trailing blank line");
  p = T.sseParseChunk('event: result\ndata: {"a":1}\n\n');
  ok(p.events.length === 1 && p.events[0].event === "result", "result event parsed");

  // ---- specChips + applyChipRemove ----
  const spec = { query: "q", collection: "both", viewpoints: ["elevated"], max_people: 0,
    must_include: ["tower"], avoid_terms: ["cars"] };
  const chips = T.specChips(spec);
  ok(chips.length === 5, "five chips from a full spec, got " + chips.length);
  ok(T.specChips({ query: "q", collection: "world", viewpoints: [], max_people: null,
    must_include: [], avoid_terms: [] }).length === 0, "default spec has no chips");
  ok(T.applyChipRemove(spec, "collection").collection === "world", "collection resets to world");
  ok(T.applyChipRemove(spec, "max_people").max_people === null, "max_people clears");
  ok(T.applyChipRemove(spec, "viewpoints:elevated").viewpoints.length === 0, "viewpoint removed");
  ok(T.applyChipRemove(spec, "must_include:tower").must_include.length === 0, "must_include removed");
  const kept = T.applyChipRemove(spec, "avoid_terms:cars");
  ok(kept.avoid_terms.length === 0 && kept.must_include.length === 1, "only the named term removed");

  // ---- suggestions ----
  const sug = T.buildSuggestions({ viewpoints: [], max_people: null, collection: "world" }, null);
  ok(sug.length === 3 && sug[0] === "From above", "default suggestions built");
  const sug2 = T.buildSuggestions({ viewpoints: ["elevated", "ground_level"], max_people: 0, collection: "personal" }, "KICC");
  ok(sug2.indexOf("No people") === -1, "active constraints are not re-suggested");

  // ---- text helpers ----
  ok(T.creditText({ author: "A", license: "L" }, "world") === "Photo: A · L", "credit line");
  ok(T.creditText({ author: "A", license: "L" }, "personal") === null, "personal photos show no credit");
  ok(T.creditText(null, "world") === null, "missing credit hides the line");
  ok(T.citeText("A", "L", "http://x/y") === "Photo: A / ReelWorld Open Cadastre (L) · http://x/y", "citation");
  ok(T.hostOf("https://commons.wikimedia.org/wiki/F") === "commons.wikimedia.org", "hostname");
  ok(T.hostOf("not a url") === null, "bad url -> null");
  ok(T.areaOfKey("kenya/nairobi/cbd/kicc") === "Nairobi / Cbd", "area from key");
  ok(T.areaOfKey("kenya") === "", "shallow key -> empty");
  ok(T.fmtScore(1.1017) === "1.10" && T.fmtScore(null) === "–", "scores format");
  ok(T.shortReasons(["a", "b", "c"]) === "a; b", "reasons trimmed to two");
  ok(T.shortReasons([]) === "close match", "empty reasons fall back");

  // ---- view hygiene regressions (mojibake + shell claims) ----
  const views = ["views/home.html", "views/credits.html", "views/about.html"];
  for (const v of views) {
    const t = fs.readFileSync(path.join(__dirname, v), "utf8");
    ok(/[\u00C3\u00C2\u00E2]/.test(t) === false, v + " has no mojibake markers");
  }
  const shell = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
  ok(/opsz,wght,FILL,GRAD@20\.\.48,100\.\.700,0\.\.1,-50\.\.200/.test(shell), "font URL has full axis spec");
  ok(shell.includes("v2.4") === false, "no invented model version in shell");
  ok(shell.includes("Encrypted locally") === false, "no false encryption claim in shell");

  console.log("home.test.js: " + n + "/" + n + " checks passed");
}

main().then(
  () => process.exit(0),
  (err) => { console.error("home.test.js FAILED:", err.message); process.exit(1); }
);
