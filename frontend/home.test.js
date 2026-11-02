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

const elRegistry = {};
function stubEl() {
  const el = {
    dataset: {},
    style: {},
    _ops: [],
    addEventListener() {},
    appendChild() {},
    prepend() {},
    remove() {},
    querySelector(sel) { return elRegistry[sel] || (elRegistry[sel] = stubEl()); },
    querySelectorAll() { return []; },
    closest() { return stubEl(); },
    innerHTML: "",
    textContent: "",
    value: "",
  };
  el.classList = {
    add(c) { el._ops.push("+" + c); },
    remove(c) { el._ops.push("-" + c); },
    toggle(c) { el._ops.push("~" + c); },
    contains() { return false; },
  };
  return el;
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

const cspec = { query: "q", collection: "world", constraints: [
  { attribute: "atmosphere", op: "is", values: ["misty_or_foggy"] },
  { attribute: "crowd", op: "is_not", values: ["many"] }] };
const cchips = T.specChips(cspec);
ok(cchips.length === 2 && cchips[0].label === "Mist" && cchips[1].label === "Not crowded", "constraint chips labelled");
const cspec1 = T.applyChipRemove(cspec, "constraints:0");
ok(cspec1.constraints.length === 1 && cspec1.constraints[0].op === "is_not", "constraint chip removed by index");
  ok(T.specChips({ query: "q", collection: "world", viewpoints: [], max_people: null,
    must_include: [], avoid_terms: [] }).length === 0, "default spec has no chips");
  ok(T.applyChipRemove(spec, "collection").collection === "world", "collection resets to world");
  ok(T.applyChipRemove(spec, "max_people").max_people === null, "max_people clears");
  ok(T.applyChipRemove(spec, "viewpoints:elevated").viewpoints.length === 0, "viewpoint removed");
  ok(T.applyChipRemove(spec, "must_include:tower").must_include.length === 0, "must_include removed");
  const kept = T.applyChipRemove(spec, "avoid_terms:cars");
  ok(kept.avoid_terms.length === 0 && kept.must_include.length === 1, "only the named term removed");
  const ownChips = T.specChips({ query: "q", collection: "personal", viewpoints: [],
    max_people: null, must_include: [], avoid_terms: [], owner_only: true });
  ok(ownChips.some((c) => c.label === "Photos of me"), "owner_only chip");
  ok(T.applyChipRemove({ owner_only: true }, "owner_only").owner_only === false,
    "owner_only clears");

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
  ["demo-full", "demo-slim", "demo-change"].forEach((id) =>
    ok(shell.indexOf('id="' + id + '"') >= 0, "shell has " + id));
  ok(shell.split('class="rw-logo').length - 1 >= 2, "logo beside header and footer wordmarks");
  ok(shell.indexOf('rel="icon"') !== -1, "shell has an svg favicon");
  const liveHome = fs.readFileSync(path.join(__dirname, "views/home.html"), "utf8")
    .replace(/<!--[\s\S]*?-->/g, "");
  ["v2.4", "NBO-", "Tesseract", "Public Works Gazette", "4096x2730", "242px",
    "94.6", "C. Karanja", "TIFF source", "Batch #"].forEach((s) => {
    ok(liveHome.indexOf(s) === -1, "home.html free of " + s);
  });
  ok(src.indexOf("You are in this photo") !== -1, "reel owner badge text present");
  ok(src.indexOf("row.owner_present === true") !== -1, "reel badge gated on owner_present");
  const homeHtml = fs.readFileSync(path.join(__dirname, "views/home.html"), "utf8");
  ok(homeHtml.indexOf('id="chats-sidebar"') !== -1 &&
    homeHtml.indexOf('id="chats-sidebar"') > homeHtml.indexOf('id="thread-wrap"'),
    "chats sidebar lives inside the chat page");
  ok(homeHtml.indexOf('id="chats-menu-landing"') !== -1, "landing has a chats menu button");
  ok(homeHtml.indexOf('id="chats-home"') !== -1, "sidebar has a home button");
  ok(homeHtml.indexOf('id="chats-clear"') !== -1 &&
    homeHtml.indexOf('id="chats-clear"') < homeHtml.indexOf('id="chats-list"'),
    "clear-all sits with the other chat actions");
  ok(homeHtml.indexOf('thread-xlist" class="contents"') === -1, "thread list is a real scroll box");
  ok(homeHtml.indexOf("rw-composer fixed") === -1, "composer is pinned, not floating");
  ["rw-step-label", "rw-step-detail", "rw-progress-stop"].forEach((id) =>
    ok(homeHtml.indexOf('id="' + id + '"') !== -1, "progress pill has " + id));
  ok(homeHtml.indexOf("rw-spin") !== -1, "progress pill has the spinning reel");
  ok(homeHtml.indexOf("Analyzing archival indices") === -1, "big loader text gone");
  ok(homeHtml.indexOf("Provisional Visual Mount") === -1, "skeleton mount gone");
  ok(src.indexOf("homeSeen") !== -1, "reel nav skips restore after first mount");
  ok(src.indexOf("openChat(id, background)") !== -1, "chat restore can run in the background");

  // ---- restore-in-background regression (landing stays on load) ----
  const chatCalls = [];
  const fetchStub2 = async (url) => {
    chatCalls.push(String(url));
    let body = {};
    if (String(url) === "/api/chats") body = { chats: [] };
    else if (String(url) === "/api/chats/chat_x") {
      body = { chat: { id: "chat_x", messages: [] } };
    }
    return { ok: true, json: async () => body, text: async () => "" };
  };
  const store = { "rw.activeChat": "chat_x" };
  global.localStorage = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
  };
  try {
    const opsBefore = ((elRegistry["#thread-wrap"] || {})._ops || []).length;
    const app2 = factory(fetchStub2, documentStub, { addEventListener() {} }, { hash: "#/" });
    await new Promise((r) => setTimeout(r, 150));
    ok(chatCalls.includes("/api/chats/chat_x"), "first mount background-restores the saved chat");
    ok(app2.home.chatId === "chat_x", "restored chat id kept in state");
    const wrapOps = ((elRegistry["#thread-wrap"] || {})._ops || []).slice(opsBefore).join(",");
    ok(wrapOps.indexOf("+block") === -1, "background restore never shows the thread");
    const countRestores = () => chatCalls.filter((u) => u === "/api/chats/chat_x").length;
    const before = countRestores();
    app2.home.mount(documentStub.querySelector("#view"));
    await new Promise((r) => setTimeout(r, 150));
    ok(countRestores() === before, "reel nav revisit does not re-restore");
  } finally {
    delete global.localStorage;
  }

  // ---- step 6 chatbot helpers ----
  const nowMs = Date.UTC(2026, 10, 1, 12, 0, 0);
  ok(T.chatDay("2026-11-01T08:00:00+00:00", nowMs) === "Today", "chat day today");
  ok(T.chatDay("2026-10-31T23:59:00+00:00", nowMs) === "Yesterday", "chat day yesterday");
  ok(T.chatDay("2026-10-28T12:00:00+00:00", nowMs) === "2026-10-28", "chat day older date");
  ok(T.chatDay("", nowMs) === "" && T.chatDay(null, nowMs) === "", "chat day empty");
  const mist = [{ attribute: "atmosphere", op: "is", values: ["misty_or_foggy"] }];
  ok(T.verdictMark({ verdict: "yes", reason: "soft layers" }, mist).label === "Mist",
    "verdict yes labels the condition");
  ok(T.verdictMark({ verdict: "no", reason: "haze only" }, mist).label === "No mist",
    "verdict no negates the condition");
  ok(T.verdictMark({ verdict: "unsure" }, mist).tone === "rw-v-unsure", "verdict unsure tone");
  ok(T.verdictMark(null, mist) === null && T.verdictMark({}, mist) === null,
    "verdict missing check -> null");
  const dry = [{ attribute: "water_visible", op: "is", values: [false] }];
  ok(T.verdictMark({ verdict: "yes" }, dry).label === "No water", "verdict water absent");
  ok(T.verdictMark({ verdict: "no" }, dry).label === "Water", "verdict water shown");
  const trace = [{ step: "searched", detail: "x" },
    { step: "checked", detail: "Looked at 12 photos to check for mist; kept 3." }];
  ok(T.checkedLine(trace) === "Looked at 12 photos to check for mist; kept 3.",
    "checked line from trace");
  ok(T.checkedLine([{ step: "checked", detail: "other" }]) === "", "checked line needs a look");
  ok(T.questionPart("Which one?\n\n- a\n- b") === "Which one?", "clarify question split");
  ok(T.dividerFor({ new: true, label: "markets" }, false).label === "markets", "divider label");
  ok(T.dividerFor({ new: true, label: "m" }, true) === null, "no divider on first turn");
  ok(T.dividerFor({ new: false }, false) === null, "no divider on refine");
  ok(T.dayGroup("Today") === "Today", "day group today");
  ok(T.dayGroup("Yesterday") === "Yesterday", "day group yesterday");
  ok(T.dayGroup("2026-10-01") === "Earlier", "day group earlier");

  console.log("home.test.js: " + n + "/" + n + " checks passed");
}

main().then(
  () => process.exit(0),
  (err) => { console.error("home.test.js FAILED:", err.message); process.exit(1); }
);
