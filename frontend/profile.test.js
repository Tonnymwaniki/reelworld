/* Tests for the owner profile + self-tagging UI.
 *
 * Run:  node frontend/profile.test.js
 *
 * Covers the pure helpers via RWTEST on the real app.js, module
 * existence, route order, and static checks on the profile/tag
 * views (ids present, exact privacy wording, no invented claims).
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
    src + "\nreturn { profile, tag, ownerAsk, add, RWTEST };"
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

  ["mount", "load", "paint", "save", "saveVoice", "destroy"].forEach((m) =>
    ok(typeof app.profile[m] === "function", "profile." + m + " exists"));
  ["mount", "load", "paint", "tile", "tagSome", "bulkYes", "saveName",
    "undo", "counts", "statePill"].forEach((m) =>
    ok(typeof app.tag[m] === "function", "tag." + m + " exists"));
  ["getProfile", "build"].forEach((m) =>
    ok(typeof app.ownerAsk[m] === "function", "ownerAsk." + m + " exists"));
  ok(typeof app.add.mountOwnerAsk === "function", "add.mountOwnerAsk exists");
  ok(typeof app.RWTEST.voiceExamples === "function", "RWTEST.voiceExamples exists");
  ok(typeof app.RWTEST.tagSort === "function", "RWTEST.tagSort exists");

  const ex = app.RWTEST.voiceExamples("Tonny");
  ok(ex.name.indexOf("Tonny") >= 0, "voice example uses the name");
  ok(ex.you.indexOf("You are among") >= 0, "voice you-example");
  ok(ex.i.indexOf("I am among") >= 0, "voice i-example");
  ok(app.RWTEST.voiceExamples("").name.indexOf("Your name") >= 0,
    "voice example falls back without a name");

  const sorted = app.RWTEST.tagSort([
    { photo_id: "p1", people: 0 },
    { photo_id: "p2", people: 3 },
    { photo_id: "p3", people: 1 },
    { photo_id: "p0", people: 3 },
  ]);
  ok(sorted.map((m) => m.photo_id).join(",") === "p0,p2,p3,p1",
    "tagSort puts people first, count desc, id tiebreak");
  ok(app.RWTEST.tagSort(null).length === 0, "tagSort tolerates null");

  const byId = { p1: { people: 0, owner_present: null },
                 p2: { people: 2, owner_present: null } };
  const entries = app.RWTEST.tagPhotos(byId);
  ok(entries.map((m) => m.photo_id).join(",") === "p2,p1", "tagPhotos sorts");
  byId.p2.owner_present = true;
  ok(entries[0].owner_present === true, "tagPhotos shares refs (tiles repaint)");

  const profileHtml = fs.readFileSync(path.join(__dirname, "views", "profile.html"), "utf8");
  ["pf-name", "pf-save", "pf-status", "pf-voice", "pf-ex-name", "pf-ex-you",
    "pf-ex-i", "pf-privacy", "pf-tag-link", "pf-export", "pf-del",
    "pf-del-confirm", "pf-del-yes", "pf-del-no", "pf-del-status",
  ].forEach((id) => ok(profileHtml.indexOf('id="' + id + '"') >= 0, "profile.html has " + id));
  ok(profileHtml.indexOf("Face matching only compares the reference photo you upload against your own photos, to suggest which ones you are in. " +
    "Nothing is tagged until you confirm it, no one else is ever identified, and your name is used only on photos you tag.") >= 0,
    "privacy wording exact");

  const tagHtml = fs.readFileSync(path.join(__dirname, "views", "tag.html"), "utf8");
  ["tg-grid", "tg-progress", "tg-bar", "tg-bulk", "tg-bulk-yes", "tg-bulk-clear",
    "tg-bulk-count", "tg-name-prompt", "tg-name", "tg-name-save", "tg-name-status",
    "tg-undo", "tg-status", "tg-error", "tg-loading", "tg-main",
    "tg-face", "tg-face-img", "tg-face-file", "tg-face-pick", "tg-face-scan",
    "tg-face-clear", "tg-face-status", "tg-face-list",
  ].forEach((id) => ok(tagHtml.indexOf('id="' + id + '"') >= 0, "tag.html has " + id));
  ok(tagHtml.indexOf("I'm in all selected") >= 0, "bulk button label");
  ok(tagHtml.indexOf("Suggestions never tag anything by themselves") >= 0,
     "face panel honesty note");

  const photoHtml = fs.readFileSync(path.join(__dirname, "views", "photo.html"), "utf8");
  ok(photoHtml.indexOf('id="owner-badge"') >= 0, "photo.html has owner-badge");

  ok(src.indexOf('"#/profile/tag"') >= 0, "router has tag route");
  ok(src.indexOf('hash === "#/profile/tag"') < src.indexOf('hash === "#/profile"'),
    "tag route is checked before the profile route");
  ok(src.indexOf('"people", "me", "look"') >= 0, "library paints the Me album");
  ok(src.indexOf("You are in this photo") >= 0, "badge text present");
  ok(src.indexOf("photo tag") >= 0, "delete reports removed tags");
  ok(src.indexOf('"/api/face-scan"') >= 0, "tag page scans for suggestions");
  ok(src.indexOf('"/api/face-reference"') >= 0, "tag page manages the reference");
  ok(src.indexOf("confirmFace") >= 0, "suggestions confirm through tagging");

  console.log(`profile.test.js: ${n} checks passed`);
}

main().catch((e) => {
  console.error("profile.test.js FAILED:", e.message);
  process.exit(1);
});
