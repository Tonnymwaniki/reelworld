/* Tests for the Phase-4 stories wiring.
 *
 * Run:  node frontend/stories.test.js
 *
 * Covers the pure story helpers via RWTEST on the real app.js, plus
 * static checks on the stories/builder/showcase views (ids present,
 * fake-data patterns absent, no MP4 promises).
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
    src + "\nreturn { player, stories, builder, showcase, RWTEST };"
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

  ok(typeof app.player.mount === "function", "player.mount exists");
  ok(typeof app.player.destroy === "function", "player.destroy exists");
  ["mount", "make", "load", "del"].forEach((m) =>
    ok(typeof app.stories[m] === "function", "stories." + m + " exists"));
  ["mount", "load", "save", "publish", "recordWebm", "downloadFile",
    "makeShorter", "collectScenes", "showStage",
  ].forEach((m) => ok(typeof app.builder[m] === "function", "builder." + m + " exists"));
  ["mount", "load", "open", "close"].forEach((m) =>
    ok(typeof app.showcase[m] === "function", "showcase." + m + " exists"));

  const T = app.RWTEST;

  // ---- storyTotals ----
  ok(JSON.stringify(T.storyTotals([{ seconds: 4 }, { seconds: 2.5 }])) ===
    JSON.stringify({ scenes: 2, seconds: 6.5 }), "totals add fractional seconds");
  ok(JSON.stringify(T.storyTotals([])) === JSON.stringify({ scenes: 0, seconds: 0 }),
    "empty totals are zero");

  // ---- chaptersWithPeople ----
  ok(JSON.stringify(T.chaptersWithPeople([
    { photo_id: "a", people: 0 }, { photo_id: "b", people: 2 }, { photo_id: "c" },
  ])) === JSON.stringify(["b"]), "people filter lists only b");

  // ---- buildStoryMarkdown ----
  const md = T.buildStoryMarkdown({ title: "Day out" }, [
    { photo_id: "market_018", heading: "Morning", caption: "Stalls open",
      text: "Stalls open early.", place: "City Market", collection: "world",
      credit: { author: "Queen Asali", license: "CC BY-SA 4.0" } },
    { photo_id: "x", heading: "", caption: "Cap", text: "Cap" },
  ]);
  ok(md.indexOf("# Day out") === 0, "markdown title first");
  ok(md.indexOf("2 scenes, 0 seconds") !== -1, "markdown totals line");
  ok(md.indexOf("## 1. Morning") !== -1 && md.indexOf("Stalls open") !== -1,
    "markdown scene heading + caption");
  ok(md.indexOf("Photo: Queen Asali · CC BY-SA 4.0") !== -1, "markdown credit line");
  ok(md.indexOf("## 2. Scene 2") !== -1, "markdown falls back to Scene N");
  ok(md.split("Cap").length - 1 === 1, "markdown skips text that repeats the caption");

  // ---- static view checks ----
  const read = (v) => fs.readFileSync(path.join(__dirname, "views", v + ".html"), "utf8");
  ["story-create-title", "story-create-prompt", "story-suggest", "story-tones",
    "story-sources", "story-targets", "story-make", "story-making",
    "story-make-error", "stories-grid", "stories-count", "stories-empty",
    "stories-error", "tpl-story-card",
  ].forEach((id) => ok(read("stories").indexOf('id="' + id + '"') !== -1, "stories.html has #" + id));
  ["bld-back", "bld-title", "bld-status", "bld-delete", "bld-loading", "bld-error",
    "bld-main", "bld-tabs", "bld-building", "bld-elapsed", "bld-trace",
    "stage-review", "stage-player", "stage-export", "bld-tones", "bld-scenes",
    "bld-shorter", "bld-save", "bld-save-status", "bld-player",
    "bld-webm-record", "bld-webm-cancel", "bld-webm-track", "bld-webm-bar",
    "bld-webm-status", "bld-webm-dl", "bld-md", "bld-json", "bld-link",
    "bld-link-status", "bld-publish", "bld-pub-note", "bld-faces",
    "bld-pub-status", "bld-showcase-link", "tpl-bld-scene",
  ].forEach((id) => ok(read("builder").indexOf('id="' + id + '"') !== -1, "builder.html has #" + id));
  ["sc-count", "sc-error", "sc-main", "sc-featured", "sc-f-img", "sc-f-title",
    "sc-f-meta", "sc-grid", "sc-empty", "sc-modal", "sc-title", "sc-player",
    "sc-credits", "sc-close", "sc-studio", "tpl-sc-card",
  ].forEach((id) => ok(read("showcase").indexOf('id="' + id + '"') !== -1, "showcase.html has #" + id));
  ["stories", "builder", "showcase"].forEach((v) => {
    const txt = read(v);
    ok(!/\sonclick\s*=/.test(txt), "no inline onclick handlers in " + v + ".html");
    const live = txt.replace(/<!--[\s\S]*?-->/g, "");
    ["lh3.googleusercontent", "cadastre.reelworld.org", "sha256", "v2.4",
      "MP4", "mp4", "NBO-0021"].forEach((s) =>
      ok(live.indexOf(s) === -1, v + ".html free of " + s));
  });

  console.log("stories.test.js: " + n + "/" + n + " checks passed");
}

main().catch((e) => { console.error("FAIL:", e.message); process.exit(1); });
