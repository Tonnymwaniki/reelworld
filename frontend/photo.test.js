/* Tests for the Phase-2 photo dossier + attribution kit wiring.
 *
 * Run:  node frontend/photo.test.js
 *
 * Covers the pure kit builders (license family/summary, citations) via
 * RWTEST on the real app.js, plus static checks on views/photo.html
 * (kit ids present, fake-data patterns absent).
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
    src + "\nreturn { photo, RWTEST };"
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

  ok(typeof app.photo.mount === "function", "photo.mount exists");
  ok(typeof app.photo.paintKit === "function", "photo.paintKit exists");
  ok(typeof app.photo.sendKitFlag === "function", "photo.sendKitFlag exists");

  const T = app.RWTEST;

  // ---- licenseFamily ----
  ok(T.licenseFamily("CC BY-SA 4.0") === "by-sa", "BY-SA family");
  ok(T.licenseFamily("CC BY-SA 2.0") === "by-sa", "BY-SA 2.0 family");
  ok(T.licenseFamily("CC BY 4.0") === "by", "BY family");
  ok(T.licenseFamily("CC BY 2.0") === "by", "BY 2.0 family");
  ok(T.licenseFamily("CC0") === "zero", "CC0 family");
  ok(T.licenseFamily("Public domain") === "zero", "public domain family");
  ok(T.licenseFamily("License unknown") === "unknown", "unknown family");
  ok(T.licenseFamily("") === "unknown", "empty family");

  // ---- licenseSummary ----
  const sa = T.licenseSummary("CC BY-SA 4.0");
  ok(sa.terms.length === 4 && /same license/.test(sa.sentence), "BY-SA: 4 terms + share-alike sentence");
  ok(sa.terms[3].label === "ShareAlike Required" && sa.terms[3].required === true, "BY-SA: ShareAlike term required");
  const by = T.licenseSummary("CC BY 4.0");
  ok(by.terms.length === 3 && by.terms.every((t) => t.label !== "ShareAlike Required"), "BY: 3 terms, no ShareAlike");
  const zero = T.licenseSummary("CC0");
  ok(zero.terms.length === 2 && /no conditions/i.test(zero.sentence), "CC0: 2 terms, no-conditions sentence");
  ok(zero.terms.every((t) => t.required === false), "CC0: nothing required");
  const unk = T.licenseSummary("License unknown");
  ok(unk.terms.length === 0 && /not recorded/.test(unk.sentence), "unknown: no terms, honest sentence");

  // ---- kitCitation ----
  const f = { author: "Queen Asali", license: "CC BY-SA 4.0", caption: "City Market",
    photoId: "market_018", pageUrl: "http://x/#/photo/market_018",
    imgUrl: "http://x/photos/market_018.jpg" };
  const plain = T.kitCitation("plain", f);
  ok(plain.indexOf("Queen Asali") !== -1 && plain.indexOf("CC BY-SA 4.0") !== -1 &&
    plain.indexOf("#/photo/market_018") !== -1, "plain citation carries author/license/url: " + plain);
  const html = T.kitCitation("html", f);
  ok(html.indexOf("<figure>") === 0 &&
    html.indexOf("creativecommons.org/licenses/by-sa/4.0/") !== -1, "html citation links the deed");
  ok(html.indexOf("cadastre.reelworld.org") === -1, "html citation has no fake domain");
  const bib = T.kitCitation("bib", f);
  ok(bib.indexOf("@misc{queen_asali_market_018,") === 0, "bib key from author+id: " + bib.split("\n")[0]);
  ok(bib.indexOf("year") === -1, "bib invents no year");

  // ---- static view checks ----
  const view = fs.readFileSync(path.join(__dirname, "views", "photo.html"), "utf8");
  ["kit-section", "kit-private", "kit-grid", "kit-photo-id", "kit-open-full",
    "kit-thumb", "kit-reg", "kit-title", "kit-caption", "kit-photographer",
    "kit-license-badge", "kit-license-name", "kit-subject", "kit-source",
    "kit-note", "kit-flag-reason", "kit-flag-note", "kit-flag-send",
    "kit-flag-status", "kit-tabs", "kit-citation", "kit-copy", "kit-copy-label",
    "kit-copy-icon", "kit-canonical", "kit-license-sentence", "kit-matrix",
    "kit-disclaimer", "kit-json", "kit-status", "kit-status-license",
  ].forEach((id) => ok(view.indexOf('id="' + id + '"') !== -1, "photo.html has #" + id));
  ok(!/\sonclick\s*=/.test(view), "no inline onclick handlers in photo.html");
  const live = view.replace(/<!--[\s\S]*?-->/g, "");  // comments may document removals
  ["lh3.googleusercontent", "cadastre.reelworld.org", "sha256", "Zero-Face",
    "v2.4", "NBO-0021"].forEach((s) => ok(live.indexOf(s) === -1, "photo.html free of " + s));

  console.log("photo.test.js: " + n + "/" + n + " checks passed");
}

main().catch((e) => { console.error("FAIL:", e.message); process.exit(1); });
