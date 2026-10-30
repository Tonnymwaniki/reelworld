/* ReelWorld app: hash router + view wiring. Calls only our own API
   (relative URLs); no keys anywhere in the frontend. */
"use strict";

const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

/* ---------- session ---------- */
function sessionId() {
  let sid = null;
  try { sid = localStorage.getItem("rw.sid"); } catch (e) { /* private mode */ }
  if (!sid) {
    sid = "web-" + Math.random().toString(36).slice(2, 10);
    try { localStorage.setItem("rw.sid", sid); } catch (e) { /* private mode */ }
  }
  return sid;
}

/* ---------- api ---------- */
function demoCode() {
  try { return sessionStorage.getItem("rw.demoCode") || ""; } catch (e) { return ""; }
}

async function api(path, opts) {
  opts = opts || {};
  const code = demoCode();
  if (code) {
    opts.headers = Object.assign({}, opts.headers, { "X-Demo-Code": code });
  }
  const res = await fetch(path, opts);
  let body = null;
  try { body = await res.json(); } catch (e) { body = null; }
  if (!res.ok) {
    const msg = (body && (body.detail || body.Detail)) || ("Request failed (" + res.status + ")");
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return body;
}

function srcOf(row) {
  if (row.src) return row.src;
  const f = String(row.file || "").replace(/\\/g, "/");
  if (f.startsWith("/photos/")) return f;
  return "/photos/" + f.replace(/^data\/photos\//, "").replace(/^\/+/, "");
}

const detailCache = new Map();
async function photoDetail(id) {
  if (!detailCache.has(id)) {
    detailCache.set(id, api("/api/photo/" + encodeURIComponent(id)).catch(() => null));
  }
  return detailCache.get(id);
}

/* ---------- small dom helpers ---------- */
function show(el, flex) {
  if (!el) return;
  el.classList.remove("hidden");
  el.classList.add(flex || "flex");
}
function hide(el) {
  if (!el) return;
  el.classList.add("hidden");
  el.classList.remove("flex");
}

/* ---------- header/footer live bits ---------- */
let rwConfig = { demo_mode: true, counts: {} };

async function refreshShell() {
  let online = false;
  try {
    rwConfig = await api("/api/config");
    online = true;
  } catch (e) { rwConfig = { demo_mode: true, counts: {} }; }
  const dot = $("#api-status-dot"), txt = $("#api-status-text");
  if (dot) dot.className = "w-1.5 h-1.5 rounded-full " + (online ? "bg-secondary" : "bg-on-tertiary-container");
  if (txt) txt.textContent = online ? "API: Online" : "API: unreachable";
  paintDemo();
}

function paintDemo() {
  const banner = $("#demo-banner");
  if (!banner) return;
  if (!rwConfig.demo_mode) { banner.classList.add("hidden"); return; }
  banner.classList.remove("hidden");
  const t = $("#demo-text", banner);
  if (t) t.textContent = demoCode()
    ? "Demo mode: a demo code is saved for this visit — writes are unlocked if it matches."
    : "Demo mode: uploads, publishing and corrections need the demo code.";
}

function setActiveTab(tab) {
  if (tab === "world" || tab === "personal") tab = "reel"; // old views, until rebuilt
  $$(".js-tab").forEach((a) => a.setAttribute("data-active", String(a.dataset.tab === tab)));
  $$(".js-mtab").forEach((a) => a.setAttribute("data-active", String(a.dataset.tab === tab)));
}

/* ---------- home view ---------- */
const VP_LABEL = {
  ground_level: "Ground level", elevated: "Elevated view", aerial: "Aerial view",
  interior: "Interior", water_level: "Water level",
};
const VP_ICON = {
  ground_level: "landscape", elevated: "height", aerial: "flight",
  interior: "home", water_level: "water",
};
const ASPECTS = ["aspect-[4/5]", "aspect-[3/4]", "aspect-square", "aspect-[4/3]"];
const KIND_BADGE = {
  ok: "Semantic Model Synced",
  no_strong_match: "Closest matches shown",
  no_other_angle: "No other angle found",
  need_focus: "Needs a photo first",
  not_found: "Photo not found",
  question_answer: "Answer",
};

/* ---------- Phase 1: Reel thread (rebuilt home view) ---------- */
/* Verified landing content (offline picks, see build log): real ids, places, credits. */
const TRUST_SAMPLE_ID = "landmarks_003";
const EX_CARDS = [
  { prompt: "A busy street market with fresh vegetables", id: "market_018",
    src: "/photos/world/market/market_018.jpg", label: "City Market",
    alt: "Colorful mural-covered Nairobi City Market building viewed across a busy street with vehicles and pedestrians in bright daylight.",
    author: "Queen Asali", license: "CC BY-SA 4.0" },
  { prompt: "The city skyline from above", id: "cbd_020",
    src: "/photos/world/cbd/cbd_020.jpg", label: "Nairobi",
    alt: "Elevated wide view of a dense city skyline with high-rise towers, a foreground building with a large billboard, and a busy road along the right edge under hazy daylight.",
    author: "DEMOSH from Nairobi, Kenya", license: "CC BY 2.0" },
  { prompt: "The entrance of KICC", id: "landmarks_004",
    src: "/photos/world/landmarks/landmarks_004.jpg", label: "Kenyatta International Convention Centre",
    alt: "The stone entrance arch of the Kenyatta International Convention Centre with its cylindrical tower rising behind closed metal gates on a sunny day.",
    author: "Bahnfrend", license: "CC BY-SA 4.0" },
  { prompt: "A street in Nairobi with matatus", id: "street_022",
    src: "/photos/world/street/street_022.jpg", label: "Haile Selassie Avenue",
    alt: "A brightly painted orange bus covered in graffiti drives down a busy city street lined with multi-story buildings and pedestrians.",
    author: "Bahnfrend", license: "CC BY-SA 4.0" },
];
const EX_ABOUT = [
  { id: "cbd_002", src: "/photos/world/cbd/cbd_002.jpg", place: "CBK Pension Towers",
    alt: "A tall modern glass skyscraper with gold lattice crowns rises behind a beige clock tower under a clear blue sky." },
  { id: "hills_006", src: "/photos/world/hills/hills_006.jpg", place: "Ngong Hills",
    alt: "Wind turbines line green hills above a forested valley with scattered buildings and a waste pile under a hazy sky." },
];
const STEP_LABEL = { understood: "Understood", searched: "Searched", checked: "Checked",
  wrote: "Wrote", answered: "Answered", fallback: "Fallback", rejected: "Skipped rejected" };
const BRIDGE_LABELS = { same_place: "Same place", another_angle: "Another angle",
  taken_from_here: "Taken from here", similar_look: "Looks similar" };
const LIC_SHORT = { "cc-by-sa": "CC BY-SA", "cc-by": "CC BY", cc0: "Public Domain", other: "Other" };
const LIC_DOT = { "cc-by-sa": "bg-secondary", "cc-by": "bg-on-tertiary-container",
  cc0: "bg-primary-container", other: "bg-outline" };
const SIGN_Q = /sign|text|say|says|read|writ|inscri|board|label/i;

/* ---------- pure helpers (also unit-tested via RWTEST) ---------- */
function byText(root, selector, text) {
  const els = Array.from((root || document).querySelectorAll(selector));
  for (const el of els) {
    if ((el.textContent || "").indexOf(text) !== -1) return el;
  }
  return null;
}
function cloneTpl(view, id) {
  const t = document.getElementById(id) || (view ? view.querySelector("#" + id) : null);
  return t.content.firstElementChild.cloneNode(true);
}
function fmtScore(x) {
  if (x === null || x === undefined || isNaN(Number(x))) return "–";
  return Number(x).toFixed(2);
}
function shortReasons(reasons) {
  const r = reasons || [];
  return r.length ? r.slice(0, 2).join("; ") : "close match";
}
function creditText(credit, collection) {
  if (collection !== "world" || !credit || !credit.author) return null;
  return "Photo: " + credit.author + (credit.license ? " · " + credit.license : "");
}
function citeText(author, license, url) {
  return "Photo: " + (author || "Unknown") + " / ReelWorld Open Cadastre (" +
    (license || "Unknown") + ")" + (url ? " · " + url : "");
}
const LICENSE_DEEDS = {
  "CC BY-SA 4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
  "CC BY-SA 3.0": "https://creativecommons.org/licenses/by-sa/3.0/",
  "CC BY-SA 2.0": "https://creativecommons.org/licenses/by-sa/2.0/",
  "CC BY 4.0": "https://creativecommons.org/licenses/by/4.0/",
  "CC BY 2.0": "https://creativecommons.org/licenses/by/2.0/",
  "CC0": "https://creativecommons.org/publicdomain/zero/1.0/",
};
const LICENSE_NAMES = {
  "CC BY-SA 4.0": "Attribution-ShareAlike 4.0 International",
  "CC BY-SA 3.0": "Attribution-ShareAlike 3.0 Unported",
  "CC BY-SA 2.0": "Attribution-ShareAlike 2.0 Generic",
  "CC BY 4.0": "Attribution 4.0 International",
  "CC BY 2.0": "Attribution 2.0 Generic",
  "CC0": "CC0 1.0 Universal (public domain dedication)",
  "Public domain": "Public domain (no known copyright)",
};
function licenseFamily(lic) {
  const l = String(lic || "");
  if (l === "CC0" || l.toLowerCase() === "public domain") return "zero";
  if (/by-sa/i.test(l)) return "by-sa";
  if (/\bby\b/i.test(l)) return "by";
  return "unknown";
}
function licenseSummary(lic) {
  const fam = licenseFamily(lic);
  const share = { icon: "share", label: "Share", required: false,
    text: "You can copy and redistribute the material in any medium or format." };
  const adapt = { icon: "build", label: "Adapt", required: false,
    text: "You can remix, transform, and build upon the material for any purpose." };
  const attr = { icon: "attribution", label: "Attribution Required", required: true,
    text: "You must give appropriate credit, provide a link to the license, and indicate if changes were made." };
  const sa = { icon: "sync", label: "ShareAlike Required", required: true,
    text: "If you remix or transform the material, you must distribute your contributions under the same license." };
  if (fam === "by-sa") return {
    sentence: "You may reuse this photo if you credit the photographer and share any changes under the same license.",
    terms: [share, adapt, attr, sa],
    disclaimer: "This summary highlights key terms of " + lic + " in plain language. It is not legal advice." };
  if (fam === "by") return {
    sentence: "You may reuse this photo if you credit the photographer.",
    terms: [share, adapt, attr],
    disclaimer: "This summary highlights key terms of " + lic + " in plain language. It is not legal advice." };
  if (fam === "zero") return {
    sentence: "You may reuse this photo freely, no conditions. Crediting the photographer is appreciated but not required.",
    terms: [share, adapt],
    disclaimer: "This photo is free of known copyright under " + lic + ". It is not legal advice." };
  return {
    sentence: "The license for this photo is not recorded — check the source record before reuse.",
    terms: [],
    disclaimer: "No license summary is available." };
}
function kitCitation(fmt, f) {
  if (fmt === "html") {
    const deed = LICENSE_DEEDS[f.license];
    const lic = deed
      ? '(<a href="' + deed + '">' + f.license + "</a>)"
      : "(" + f.license + ")";
    const alt = String(f.caption || f.photoId).replace(/"/g, "&quot;");
    return "<figure>\n" +
      '  <img src="' + f.imgUrl + '" alt="' + alt + '" />\n' +
      "  <figcaption>Photo: " + f.author + " / ReelWorld Open Cadastre " + lic + "</figcaption>\n" +
      "</figure>";
  }
  if (fmt === "bib") {
    const key = (f.author + " " + f.photoId).toLowerCase()
      .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || f.photoId;
    return "@misc{" + key + ",\n" +
      "  author = {" + f.author + "},\n" +
      "  title = {" + (f.caption || f.photoId) + "},\n" +
      "  publisher = {ReelWorld Open Cadastre},\n" +
      "  url = {" + f.pageUrl + "},\n" +
      "  note = {" + f.license + "}\n}";
  }
  return citeText(f.author, f.license, f.pageUrl);
}
function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch (e) { return null; }
}
function areaOfKey(key) {
  const parts = String(key || "").split("/").filter(Boolean);
  if (parts.length < 3) return "";
  return parts.slice(1, -1).map((p) => p.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())).join(" / ");
}
function specChips(spec) {
  const out = [];
  if (!spec) return out;
  if (spec.collection && spec.collection !== "world") {
    out.push({ key: "collection", label: spec.collection === "personal" ? "Your photos" : String(spec.collection) });
  }
  for (const v of spec.viewpoints || []) {
    out.push({ key: "viewpoints:" + v, label: (typeof VP_LABEL !== "undefined" && VP_LABEL[v]) || v });
  }
  if (spec.max_people !== null && spec.max_people !== undefined) {
    out.push({ key: "max_people", label: spec.max_people === 0 ? "No people" : "At most " + spec.max_people + " people" });
  }
  for (const w of spec.must_include || []) out.push({ key: "must_include:" + w, label: "\u201C" + w + "\u201D" });
  for (const w of spec.avoid_terms || []) out.push({ key: "avoid_terms:" + w, label: "Not " + w });
  return out;
}
function applyChipRemove(spec, key) {
  const s = JSON.parse(JSON.stringify(spec || {}));
  if (key === "collection") { s.collection = "world"; return s; }
  if (key === "max_people") { s.max_people = null; return s; }
  const i = key.indexOf(":");
  const field = key.slice(0, i), val = key.slice(i + 1);
  s[field] = (s[field] || []).filter((x) => x !== val);
  return s;
}
function buildSuggestions(spec, focusPlace) {
  const out = [];
  const vps = (spec && spec.viewpoints) || [];
  if (vps.indexOf("elevated") === -1) out.push("From above");
  else if (vps.indexOf("ground_level") === -1) out.push("At ground level");
  if (!spec || spec.max_people === null || spec.max_people === undefined) out.push("No people");
  if (spec && spec.collection === "personal") out.push("Search the world too");
  else out.push("Include my photos");
  if (focusPlace && out.length < 3) out.push("More like this");
  return out.slice(0, 3);
}
function sseParseChunk(buf) {
  const events = [];
  const parts = String(buf).split("\n\n");
  const rest = parts.pop();
  for (const part of parts) {
    let event = "message";
    const data = [];
    for (const line of part.split("\n")) {
      const t = line.replace(/\r$/, "");
      if (t.indexOf("event:") === 0) event = t.slice(6).trim();
      else if (t.indexOf("data:") === 0) data.push(t.slice(5).trim());
    }
    if (data.length) events.push({ event: event, data: data.join("\n") });
  }
  return { events: events, rest: rest };
}
const RING_RADII = [58, 95, 140, 185, 230];
function ringLayout(ringIdx, slot, total) {
  const r = RING_RADII[ringIdx];
  const a = -Math.PI / 2 + (slot * 2 * Math.PI) / Math.max(1, total) + ringIdx * 0.42;
  return { x: Math.round((250 + r * Math.cos(a)) * 10) / 10,
    y: Math.round((250 + r * Math.sin(a)) * 10) / 10 };
}
function ringLabel(ringIdx, slot) {
  return (ringIdx + 1) + "ABCDEFGH"[slot];
}
function fmtBytes(b) {
  if (b == null) return "—";
  if (b < 1024) return b + " B";
  if (b < 1048576) return Math.round(b / 1024) + " KB";
  return (b / 1048576).toFixed(1) + " MB";
}
const GAP_VP_LABEL = { ground_level: "ground-level view", elevated: "elevated view",
  aerial: "aerial view", interior: "interior view" };
function gapText(g) {
  if (!g.count) return "No photos yet — yours could be the first.";
  const bits = (g.missing || []).filter((m) => m !== "all")
    .map((m) => "No " + (GAP_VP_LABEL[m] || m));
  if (g.count === 1) bits.push("Only one photo");
  return bits.length ? bits.join(" · ") + "." : "Covered from every angle.";
}
function storyTotals(chapters) {
  const list = chapters || [];
  return { scenes: list.length,
    seconds: list.reduce((t, c) => t + (Number(c.seconds) || 0), 0) };
}
function chaptersWithPeople(chapters) {
  return (chapters || []).filter((c) => (c.people || 0) > 0).map((c) => c.photo_id);
}
function buildStoryMarkdown(story, chapters) {
  const t = storyTotals(chapters);
  const out = ["# " + ((story && story.title) || "Untitled story"), "",
    "A ReelWorld photo story — " + t.scenes + " scenes, " + t.seconds + " seconds.", ""];
  (chapters || []).forEach((c, i) => {
    out.push("## " + (i + 1) + ". " + (c.heading || "Scene " + (i + 1)));
    if (c.caption) out.push("", c.caption);
    if (c.text && c.text !== c.caption) out.push("", c.text);
    const bits = [];
    if (c.place) bits.push(c.place);
    const ct = creditText(c.credit, c.collection);
    if (ct) bits.push(ct);
    if (c.photo_id) bits.push(c.photo_id);
    if (bits.length) out.push("", bits.join(" · "));
    out.push("");
  });
  return out.join("\n");
}
const KIND_LABEL = {
  same_place: "Same place", another_angle: "Another angle",
  where_stood: "Where you stood", shared_landmark: "Shared landmark",
  shared_sign: "Shared sign", similar: "Looks similar",
};
function evidenceRows(facts, nameA, nameB) {
  const f = facts || {};
  const rows = [];
  if (f.same_place) {
    rows.push({ icon: "pin_drop", label: "Same place",
      text: f.place_name || "Both photos share a place verdict." });
  }
  if (f.same_place && nameA && nameB && nameA !== nameB) {
    rows.push({ icon: "view_in_ar", label: "Different viewpoint",
      text: nameA + " vs " + nameB + "." });
  }
  if (f.taken_cross) {
    rows.push({ icon: "tripod", label: "Where you stood",
      text: "One photo shows the spot the other was taken from." });
  }
  (f.shared_landmarks || []).length && rows.push({ icon: "domain", label: "Shared landmark",
    text: f.shared_landmarks.join("; ") });
  (f.shared_signs || []).length && rows.push({ icon: "badge", label: "Shared sign text",
    text: f.shared_signs.map((s) => "\u201c" + s + "\u201d").join("; ") });
  (f.shared_entities || []).slice(0, 5).length && rows.push({ icon: "visibility",
    label: "Same things visible", text: f.shared_entities.slice(0, 5).join(", ") });
  if (!rows.length) {
    rows.push({ icon: "block", label: "No shared evidence",
      text: "Different places, signs and landmarks." });
  }
  return rows;
}
const RWTEST = { fmtScore: fmtScore, shortReasons: shortReasons, creditText: creditText,
  citeText: citeText, hostOf: hostOf, areaOfKey: areaOfKey, specChips: specChips,
  applyChipRemove: applyChipRemove, buildSuggestions: buildSuggestions,
  sseParseChunk: sseParseChunk, licenseFamily: licenseFamily,
  licenseSummary: licenseSummary, kitCitation: kitCitation,
  ringLayout: ringLayout, ringLabel: ringLabel, evidenceRows: evidenceRows,
  KIND_LABEL: KIND_LABEL, storyTotals: storyTotals,
  chaptersWithPeople: chaptersWithPeople, buildStoryMarkdown: buildStoryMarkdown,
  fmtBytes: fmtBytes, gapText: gapText };

const home = {
  view: null, xlist: null, loadingTimer: null, abort: null,
  sent: [], histIdx: -1, focusId: null, lastSpec: null, lastUserText: "",
  rowsById: {}, tourCache: {}, tourIdx: 1, tourWired: false,
  fileInput: null, replySeq: 0,

  mount(view) {
    this.view = view;
    this.xlist = $("#thread-xlist", view);
    this.rowsById = {};
    this.sent = [];
    this.histIdx = -1;
    this.focusId = null;
    this.lastSpec = null;
    this.tourCache = {};
    this.tourWired = false;
    this.replySeq = 0;
    const input = $("#archival-prompt-input", view);
    const go = () => { const q = input.value.trim(); if (q) this.send(q); };
    $("#submit-prompt-btn", view).addEventListener("click", go);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    $("#upload-evidence-btn", view).addEventListener("click", () => this.pickFile());
    $("#tour-modal-trigger", view).addEventListener("click", () => this.openTour(1));
    $$(".prompt-card", view).forEach((c) => {
      c.addEventListener("click", () => { if (c.dataset.prompt) this.send(c.dataset.prompt); });
    });
    const ti = $("#thread-input", view);
    $("#thread-send", view).addEventListener("click", () => {
      const q = ti.value.trim(); if (q) this.send(q);
    });
    ti.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { const q = ti.value.trim(); if (q) this.send(q); }
      else if (e.key === "ArrowUp" && this.sent.length) {
        e.preventDefault();
        this.histIdx = Math.max(0, this.histIdx - 1);
        ti.value = this.sent[this.histIdx] || "";
      } else if (e.key === "ArrowDown" && this.sent.length) {
        e.preventDefault();
        this.histIdx = Math.min(this.sent.length, this.histIdx + 1);
        ti.value = this.histIdx >= this.sent.length ? "" : this.sent[this.histIdx];
      }
    });
    $("#thread-add", view).addEventListener("click", () => this.pickFile());
    const tune = $("#thread-tune", view);
    if (tune) tune.style.display = "none"; // no designed panel; see deferred.md
    $("#thread-context-clear", view).addEventListener("click", () => this.clearContext());
    const pill = $("#thread-context", view);
    pill.style.cursor = "pointer";
    pill.addEventListener("click", (e) => {
      if (e.target.closest("#thread-context-clear")) return;
      if (this.focusId) location.hash = "#/photo/" + this.focusId;
    });
    this.xlist.addEventListener("click", (e) => {
      const f = e.target.closest("[data-flag]");
      if (f) { this.openFlag(f.dataset.target || "this reply"); return; }
      const mount = e.target.closest("[data-pid]");
      if (mount) this.photoClick(mount);
    });
    this.wireFlag(view);
    this.fileInput = document.createElement("input");
    this.fileInput.type = "file";
    this.fileInput.accept = "image/jpeg,image/png";
    this.fileInput.style.display = "none";
    this.fileInput.addEventListener("change", () => {
      const f = this.fileInput.files && this.fileInput.files[0];
      this.fileInput.value = "";
      if (f) this.addFlow(f);
    });
    view.appendChild(this.fileInput);
    this.fillLanding();
  },

  scrollBottom() {
    try { window.scrollTo(0, document.body.scrollHeight); } catch (e) { /* tests */ }
  },

  fillLanding() {
    const view = this.view;
    $$(".prompt-card", view).forEach((card) => {
      const ex = EX_CARDS.find((c) => c.prompt === card.dataset.prompt);
      if (!ex) return;
      const img = card.querySelector("img");
      if (img) { img.src = ex.src; img.setAttribute("data-alt", ex.alt); img.alt = ex.alt; }
      const foot = card.querySelector("div.mt-4");
      if (foot) {
        const spans = foot.querySelectorAll("span");
        if (spans[0]) spans[0].textContent = ex.label;
        if (spans[1]) spans[1].textContent = "Photo credit: " + ex.author + " · " + ex.license;
      }
    });
    const counts = (typeof rwConfig !== "undefined" && rwConfig.counts) || {};
    const setStat = (id, v) => {
      const el = document.getElementById(id) || view.querySelector("#" + id);
      if (el) el.textContent = (v === null || v === undefined) ? "–" : String(v);
    };
    setStat("stat-photos", counts.world);
    setStat("stat-places", counts.places);
    setStat("stat-themes", counts.themes);
    photoDetail(TRUST_SAMPLE_ID).then((d) => {
      if (!d || !d.photo_id) throw new Error("missing");
      const get = (id) => document.getElementById(id) || view.querySelector("#" + id);
      const set = (id, v) => { const el = get(id); if (el) el.textContent = v; };
      set("trust-logid", "AUDIT LOG #" + d.photo_id);
      const img = get("trust-img");
      if (img) { img.src = srcOf(d); img.setAttribute("data-alt", d.caption || d.photo_id); img.alt = d.caption || d.photo_id; }
      const place = d.place || {};
      set("trust-item", "Plate " + d.photo_id + ": " + (place.name || "no place verdict"));
      const st = get("trust-status");
      if (st) {
        st.textContent = place.status === "confirmed" ? "Confirmed" : "Candidate";
        st.className = place.status === "confirmed"
          ? "px-2 py-0.5 rounded bg-secondary-container text-on-secondary-fixed-variant font-label-sm text-label-sm"
          : "px-2 py-0.5 rounded bg-tertiary-fixed text-on-tertiary-fixed font-label-sm text-label-sm";
      }
      set("trust-subject", "Subject: " + (d.caption || d.photo_id));
      const ev = (place.evidence && place.evidence[0] && place.evidence[0].detail) || d.caption || "";
      const m = get("trust-matched");
      if (m && m.parentElement) {
        m.parentElement.textContent = "";
        const strong = document.createElement("strong");
        strong.className = "font-semibold text-primary";
        strong.textContent = "Matched:";
        m.parentElement.appendChild(strong);
        m.parentElement.appendChild(document.createTextNode(" " + ev));
      }
      const unc = (d.uncertainties && d.uncertainties[0]) || "Nothing flagged.";
      const u = get("trust-unverified");
      if (u && u.parentElement) {
        u.parentElement.textContent = "";
        const strong = document.createElement("strong");
        strong.className = "font-semibold text-on-tertiary-container";
        strong.textContent = "Unverified:";
        u.parentElement.appendChild(strong);
        u.parentElement.appendChild(document.createTextNode(" " + unc));
      }
    }).catch(() => {
      const img = view.querySelector("#trust-img");
      const col = img ? img.closest('[class*="lg:w-7/12"]') : null;
      if (col) hide(col);
    });
  },
  showThread() {
    hide($("#landing", this.view));
    show($("#thread-wrap", this.view), "block");
  },

  appendUser(text) {
    const node = cloneTpl(this.view, "tpl-user");
    const now = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    const meta = node.querySelectorAll("span");
    if (meta[2]) meta[2].textContent = now;
    const p = node.querySelector("p");
    if (p) p.textContent = text;
    this.xlist.appendChild(node);
    this.scrollBottom();
    return node;
  },

  async send(text) {
    this.showThread();
    if (this.abort) { try { this.abort.abort(); } catch (e) { /* superseded */ } }
    const ctl = new AbortController();
    this.abort = ctl;
    this.appendUser(text);
    this.sent.push(text);
    this.histIdx = this.sent.length;
    const ti = $("#thread-input", this.view);
    if (ti) ti.value = "";
    this.lastUserText = text;
    const prog = this.showProgress();
    try {
      const data = await this.runStream(text, ctl.signal, prog);
      this.stopProgress(prog);
      prog.remove();
      await this.renderResult(data, text);
    } catch (e) {
      this.stopProgress(prog);
      if (prog.parentElement) prog.remove();
      if (e && e.name === "AbortError") return;
      this.renderError("Request failed: " + ((e && e.message) || e));
    }
  },

  showProgress() {
    const node = cloneTpl(this.view, "tpl-progress");
    const est = byText(node, "span", "remaining");
    if (est) {
      const sep = est.previousElementSibling;
      if (sep) sep.remove();
      est.remove();
    }
    const stamp = node.querySelector("div.absolute.bottom-3");
    if (stamp) {
      const spans = stamp.querySelectorAll("span");
      if (spans[0]) spans[0].textContent = "ReelWorld contact sheet";
      if (spans[1]) spans[1].textContent = "";
    }
    const mono = node.querySelector(".font-mono");
    if (mono) mono.textContent = "Contact sheet";
    const priv = byText(node, "span", "local edge node");
    if (priv) priv.textContent = "Photo matches are verified against cataloged archives.";
    const box = node.querySelector("div.bg-surface-container.p-space-md");
    node._doneTpl = box.children[0].cloneNode(true);
    box.innerHTML = "";
    node._steps = box;
    node._t0 = Date.now();
    node._last = node._t0;
    const el = node.querySelector("#elapsed-counter");
    const tick = () => { if (el) el.textContent = ((Date.now() - node._t0) / 1000).toFixed(1) + "s"; };
    tick();
    node._timer = setInterval(tick, 100);
    this.loadingTimer = node._timer;
    const stop = byText(node, "button", "Stop generating");
    if (stop) stop.addEventListener("click", () => { if (this.abort) this.abort.abort(); });
    this.xlist.appendChild(node);
    this.scrollBottom();
    return node;
  },

  stopProgress(node) {
    if (node && node._timer) {
      clearInterval(node._timer);
      node._timer = null;
      if (this.loadingTimer) { clearInterval(this.loadingTimer); this.loadingTimer = null; }
    }
  },

  progressStep(node, name, detail) {
    if (!node || !node._steps) return;
    const now = Date.now();
    const dt = ((now - (node._last || now)) / 1000).toFixed(1) + "s";
    node._last = now;
    const row = node._doneTpl.cloneNode(true);
    const content = row.children[1];
    if (content) {
      const spans = content.querySelectorAll("span");
      if (spans[0]) spans[0].textContent = STEP_LABEL[name] || name;
      if (spans[1]) spans[1].textContent = dt + " · " + detail;
    }
    node._steps.appendChild(row);
    this.scrollBottom();
  },

  async runStream(text, signal, prog) {
    let code = "";
    try { code = sessionStorage.getItem("rw.demoCode") || ""; } catch (e) { /* private mode */ }
    const headers = { "Content-Type": "application/json" };
    if (code) headers["X-Demo-Code"] = code;
    const res = await fetch("/chat/stream", {
      method: "POST", headers: headers, signal: signal,
      body: JSON.stringify({ session_id: sessionId(), message: text }),
    });
    if (!res.ok) {
      let msg = "Request failed (" + res.status + ")";
      try { const b = await res.json(); if (b && b.detail) msg = b.detail; } catch (e) { /* keep */ }
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const out = await reader.read();
      if (out.done) break;
      buf += dec.decode(out.value, { stream: true });
      const parsed = sseParseChunk(buf);
      buf = parsed.rest;
      for (const ev of parsed.events) {
        if (ev.event === "step") {
          try {
            const s = JSON.parse(ev.data);
            this.progressStep(prog, s.step, s.detail);
          } catch (e) { /* ignore malformed step */ }
        } else if (ev.event === "result") {
          try { await reader.cancel(); } catch (e) { /* done */ }
          return JSON.parse(ev.data);
        } else if (ev.event === "error") {
          let msg = "search failed";
          try { msg = JSON.parse(ev.data).detail || msg; } catch (e) { /* keep */ }
          throw new Error(msg);
        }
      }
    }
    throw new Error("The stream ended without a result.");
  },
  async renderResult(data, userText) {
    data = data || {};
    const results = data.results || [];
    for (const r of results) {
      if (r && r.photo_id) this.rowsById[r.photo_id] = r;
    }
    if (data.focus_photo_id) this.focusId = data.focus_photo_id;
    if (data.spec) this.lastSpec = data.spec;
    this.paintContext();
    if (results.length) this.renderAssistant(data);
    else if (data.kind === "question_answer") await this.renderAnswer(data, userText);
    else this.renderText(data);
    if (!results.length && (data.kind === "ok" || data.kind === "no_strong_match")) {
      const node = cloneTpl(this.view, "tpl-nomatch");
      const btn = node.querySelector("button");
      if (btn) btn.addEventListener("click", () => this.pickFile());
      this.xlist.appendChild(node);
    }
    this.scrollBottom();
  },

  paintContext() {
    const pill = $("#thread-context", this.view);
    if (!pill) return;
    const row = (this.focusId && this.rowsById[this.focusId]) || null;
    if (!this.focusId || !row) { hide(pill); return; }
    const img = pill.querySelector("img");
    if (img) { img.src = srcOf(row); img.alt = row.caption || row.photo_id; }
    const label = pill.querySelector("span.font-label-sm");
    if (label) {
      label.textContent = "";
      label.appendChild(document.createTextNode("Asking about: "));
      const strong = document.createElement("strong");
      strong.className = "font-semibold text-primary";
      strong.textContent = row.photo_id;
      label.appendChild(strong);
      if (row.place_name) label.appendChild(document.createTextNode(" (" + row.place_name + ")"));
    }
    show(pill);
  },

  async clearContext() {
    try { await api("/sessions/" + encodeURIComponent(sessionId()) + "/reset", { method: "POST" }); } catch (e) { /* fresh anyway */ }
    this.focusId = null;
    this.lastSpec = null;
    hide($("#thread-context", this.view));
  },

  fillPhotoMount(mount, row, isHero, badgeTpl) {
    const img = mount.querySelector("img");
    if (img) {
      img.src = srcOf(row);
      img.setAttribute("data-alt", row.caption || row.photo_id);
      img.alt = row.caption || row.photo_id;
    }
    const plate = mount.querySelector(".absolute");
    if (plate && plate.tagName !== "BUTTON") {
      plate.textContent = (isHero ? "Plate " : "") + row.photo_id;
    }
    if (isHero) {
      const bottom = mount.children[1];
      if (bottom) {
        const matched = bottom.children[0];
        if (matched) {
          const ic = matched.querySelector("span");
          matched.textContent = "";
          if (ic) matched.appendChild(ic);
          matched.appendChild(document.createTextNode("matched: " + shortReasons(row.reasons)));
        }
        const cred = bottom.children[1];
        const ct = creditText(row.credit, row.collection);
        if (cred) { if (ct) cred.textContent = ct; else cred.remove(); }
      }
    } else {
      const box = mount.querySelector("div.mt-1");
      if (box) {
        const spans = box.querySelectorAll("span");
        if (spans[0]) spans[0].textContent = "matched: " + shortReasons(row.reasons);
        const ct = creditText(row.credit, row.collection);
        if (spans[1]) { if (ct) spans[1].textContent = ct; else spans[1].remove(); }
      }
    }
    mount.dataset.pid = row.photo_id;
    if (badgeTpl && !isHero) {
      const wrap = mount.querySelector(".relative");
      if (wrap) wrap.appendChild(badgeTpl.cloneNode(true));
    }
  },

  fillChips(node, spec) {
    const lab = byText(node, "span", "Active Constraints:");
    if (!lab) return;
    const box = lab.parentElement;
    const tpl = box.querySelector("button");
    box.querySelectorAll("button").forEach((b) => b.remove());
    const chips = specChips(spec);
    if (!chips.length) { hide(box); return; }
    show(box);
    for (const c of chips) {
      const b = tpl.cloneNode(true);
      if (b.children[0]) b.children[0].textContent = c.label;
      b.addEventListener("click", () => this.dropChip(c.key, c.label));
      box.appendChild(b);
    }
  },

  async dropChip(key, label) {
    if (!this.lastSpec) return;
    const spec = applyChipRemove(this.lastSpec, key);
    this.appendUser("Refine: drop \u201C" + label + "\u201D");
    const prog = this.showProgress();
    this.progressStep(prog, "searched", "Searching with updated filters…");
    try {
      const data = await api("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId(), spec: spec }),
      });
      this.stopProgress(prog);
      prog.remove();
      await this.renderResult(data, label);
    } catch (e) {
      this.stopProgress(prog);
      prog.remove();
      this.renderError("Refine failed: " + ((e && e.message) || e));
    }
  },

  fillSuggestions(node, focusPlace) {
    const lab = byText(node, "span", "Suggestions:");
    if (!lab) return;
    const box = lab.parentElement;
    const tpl = box.querySelector("button");
    box.querySelectorAll("button").forEach((b) => b.remove());
    const sug = buildSuggestions(this.lastSpec, focusPlace);
    if (!sug.length) { hide(box); return; }
    show(box);
    for (const s of sug) {
      const b = tpl.cloneNode(true);
      b.textContent = "\u201C" + s + "\u201D";
      b.addEventListener("click", () => this.send(s));
      box.appendChild(b);
    }
  },

  fillTrace(node, data) {
    const details = node.querySelector("details");
    if (!details) return;
    const trace = data.trace || [];
    if (!trace.length) { hide(details); return; }
    const summary = details.querySelector("summary");
    if (summary && summary.children[1]) {
      const results = data.results || [];
      summary.children[1].textContent = results.length
        ? "Top match " + fmtScore(results[0].score) + " · " + results.length + " photo" + (results.length === 1 ? "" : "s")
        : trace.length + " step" + (trace.length === 1 ? "" : "s");
    }
    const box = details.children[1];
    if (!box) return;
    const tpl = box.children[0].cloneNode(true);
    box.innerHTML = "";
    for (const t of trace) {
      const row = tpl.cloneNode(true);
      const spans = row.querySelectorAll("span");
      if (spans[0]) spans[0].textContent = (STEP_LABEL[t.step] || t.step) + ":";
      if (spans[1]) spans[1].textContent = t.detail || "";
      box.appendChild(row);
    }
  },

  wireActions(node, focusId) {
    const defs = [
      ["Another angle", () => this.send("Show another angle of " + focusId)],
      ["More like this", () => this.send("More like " + focusId)],
      ["Not this one", () => this.send("Not this one")],
      ["Compare", () => this.enterCompare(node)],
    ];
    for (const [label, fn] of defs) {
      const b = byText(node, "button", label);
      if (b) b.addEventListener("click", fn);
    }
  },

  renderAssistant(data) {
    const results = (data.results || []).slice(0, 5);
    const node = cloneTpl(this.view, "tpl-assistant");
    const header = node.children[0];
    const badgeDiv = header.querySelector("div.bg-surface-container-high");
    if (badgeDiv && badgeDiv.children[1]) {
      badgeDiv.children[1].textContent = (typeof KIND_BADGE !== "undefined" && KIND_BADGE[data.kind]) || "Reel";
    }
    if (header.children[1]) {
      header.children[1].textContent = results.length + " photo" + (results.length === 1 ? "" : "s");
    }
    const p = node.querySelector("p");
    if (p) p.textContent = data.text || "";
    this.fillChips(node, data.spec);
    const box = node.querySelector("div.w-full.bg-surface-container-low");
    const grid = box ? box.querySelector(".grid") : null;
    const hero = grid ? grid.children[0] : null;
    const subgrid = grid ? grid.children[1] : null;
    const subTpl = subgrid && subgrid.children[0] ? subgrid.children[0].cloneNode(true) : null;
    const wantBadge = data.kind === "no_other_angle" || data.kind === "no_strong_match";
    let badgeTpl = null;
    if (wantBadge) {
      try { badgeTpl = cloneTpl(this.view, "tpl-similarbadge"); } catch (e) { badgeTpl = null; }
    }
    if (hero && results[0]) this.fillPhotoMount(hero, results[0], true, null);
    if (subgrid) {
      subgrid.innerHTML = "";
      for (const r of results.slice(1)) {
        const m = subTpl.cloneNode(true);
        this.fillPhotoMount(m, r, false, badgeTpl);
        subgrid.appendChild(m);
      }
      if (!results.slice(1).length) {
        hide(subgrid);
        if (hero) { hero.classList.remove("md:col-span-7"); hero.classList.add("md:col-span-12"); }
      }
    }
    const focus = data.focus_photo_id || this.focusId;
    if (focus) this.wireActions(node, focus);
    else { const b = byText(node, "button", "Another angle"); if (b && b.parentElement) hide(b.parentElement); }
    this.fillSuggestions(node, (this.rowsById[focus] || {}).place_name || null);
    this.fillTrace(node, data);
    node.dataset.reply = String(++this.replySeq);
    this.xlist.appendChild(node);
    this.scrollBottom();
    return node;
  },

  async renderAnswer(data, userText) {
    const focus = data.focus_photo_id || this.focusId;
    const node = cloneTpl(this.view, "tpl-answer");
    const badge = node.querySelector("span.uppercase");
    if (badge) badge.textContent = "Answer";
    const flag = node.querySelector("[data-flag]");
    if (flag) flag.dataset.target = focus ? "answer about " + focus : "this answer";
    const tplA = document.getElementById("tpl-assistant") || this.view.querySelector("#tpl-assistant");
    const answerP = tplA.content.querySelector("p").cloneNode(true);
    answerP.textContent = data.text || "";
    const photoBlock = node.children[1];
    node.insertBefore(answerP, photoBlock);
    let detail = null;
    if (focus) {
      try { detail = await photoDetail(focus); } catch (e) { detail = null; }
    }
    const row = (focus && this.rowsById[focus]) || {};
    if (photoBlock && (detail || row.photo_id)) {
      const img = photoBlock.querySelector("img");
      if (img) {
        img.src = detail ? srcOf(detail) : srcOf(row);
        img.alt = (detail && detail.caption) || row.caption || focus;
      }
      const plate = photoBlock.querySelector(".absolute");
      if (plate) plate.textContent = focus;
      const banner = photoBlock.querySelector(".text-on-secondary-container");
      if (banner) hide(banner); // per-turn source is not verified; never claim a re-look
    } else if (photoBlock) {
      hide(photoBlock);
    }
    const ocr = node.querySelector("div.bg-surface-container-highest");
    const signs = (detail && detail.signs) || [];
    if (ocr && SIGN_Q.test(userText || "") && signs.length) {
      const s = signs[0];
      const conf = ocr.querySelector("span.px-space-xs");
      if (conf && conf.lastChild) {
        conf.lastChild.textContent = " " + (s.legibility || "Unrated") +
          ((s.confidence === null || s.confidence === undefined) ? "" : " (" + Math.round(s.confidence * 100) + "% confidence)");
      }
      const txt = ocr.querySelector("p");
      if (txt) txt.textContent = "\u201C" + (s.text || "") + "\u201D";
      const loc = ocr.querySelector("span.font-label-sm.text-on-surface-variant");
      if (loc) { if (s.where) loc.textContent = "Location: " + s.where; else loc.remove(); }
    } else if (ocr) {
      hide(ocr);
    }
    const det = node.querySelector("details");
    if (det) {
      const rows = det.querySelector("div.mt-space-xs");
      if (rows) {
        rows.innerHTML = "";
        for (const t of data.trace || []) {
          const pr = document.createElement("p");
          const st = document.createElement("strong");
          st.textContent = (STEP_LABEL[t.step] || t.step) + ":";
          pr.appendChild(st);
          pr.appendChild(document.createTextNode(" " + (t.detail || "")));
          rows.appendChild(pr);
        }
        if (!rows.children.length) hide(det);
      }
    }
    if (focus) this.wireActions(node, focus);
    node.dataset.reply = String(++this.replySeq);
    this.xlist.appendChild(node);
    this.scrollBottom();
    return node;
  },

  renderText(data) {
    const node = cloneTpl(this.view, "tpl-assistant");
    const header = node.children[0];
    const badgeDiv = header.querySelector("div.bg-surface-container-high");
    if (badgeDiv && badgeDiv.children[1]) {
      badgeDiv.children[1].textContent = (typeof KIND_BADGE !== "undefined" && KIND_BADGE[data.kind]) || "Reel";
    }
    if (header.children[1]) header.children[1].textContent = "No photos";
    const p = node.querySelector("p");
    if (p) p.textContent = data.text || "";
    this.fillChips(node, data.spec);
    const box = node.querySelector("div.w-full.bg-surface-container-low");
    if (box) hide(box);
    if (this.focusId) this.wireActions(node, this.focusId);
    else { const b = byText(node, "button", "Another angle"); if (b && b.parentElement) hide(b.parentElement); }
    this.fillSuggestions(node, (this.rowsById[this.focusId] || {}).place_name || null);
    this.fillTrace(node, data);
    node.dataset.reply = String(++this.replySeq);
    this.xlist.appendChild(node);
    this.scrollBottom();
    return node;
  },

  renderError(text) {
    const node = cloneTpl(this.view, "tpl-assistant");
    const header = node.children[0];
    const badgeDiv = header.querySelector("div.bg-surface-container-high");
    if (badgeDiv && badgeDiv.children[1]) badgeDiv.children[1].textContent = "Request failed";
    if (header.children[1]) header.children[1].textContent = "No photos";
    const p = node.querySelector("p");
    if (p) p.textContent = text;
    const box = node.querySelector("div.w-full.bg-surface-container-low");
    if (box) hide(box);
    const lab = byText(node, "span", "Active Constraints:");
    if (lab) hide(lab.parentElement);
    const sug = byText(node, "span", "Suggestions:");
    if (sug) hide(sug.parentElement);
    const act = byText(node, "button", "Another angle");
    if (act && act.parentElement) hide(act.parentElement);
    const det = node.querySelector("details");
    if (det) hide(det);
    this.xlist.appendChild(node);
    this.scrollBottom();
    return node;
  },
  photoClick(mount) {
    const pid = mount.dataset.pid;
    if (!pid) return;
    const reply = mount.closest("[data-reply]");
    const st = reply && reply._cmp;
    if (!st) {
      location.hash = "#/photo/" + pid;
      return;
    }
    const i = st.sel.indexOf(pid);
    if (i >= 0) {
      st.sel.splice(i, 1);
      const wrap = mount.querySelector(".relative");
      const badge = wrap ? wrap.querySelector("[data-cmpbadge]") : null;
      if (badge) badge.remove();
    } else {
      if (st.sel.length >= 2) return;
      st.sel.push(pid);
      const isThumb = !!mount.querySelector(".aspect-square");
      const tpl = cloneTpl(this.view, isThumb ? "tpl-cmpbadge-thumb" : "tpl-cmpbadge-hero");
      tpl.setAttribute("data-cmpbadge", "1");
      const wrap = mount.querySelector(".relative");
      if (wrap) wrap.appendChild(tpl);
    }
    this.paintCompareBar(reply, st);
  },

  enterCompare(replyNode) {
    if (replyNode._cmp) return;
    replyNode._cmp = { sel: [], bar: null };
  },

  paintCompareBar(replyNode, st) {
    if (st.bar) st.bar.remove();
    st.bar = null;
    if (!st.sel.length) return;
    const bar = cloneTpl(this.view, "tpl-comparebar");
    const title = bar.querySelector("span.font-label-md");
    if (title) title.textContent = st.sel.length + " Archival Plate" + (st.sel.length === 1 ? "" : "s") + " Selected";
    const names = bar.querySelector("span.font-body-sm");
    if (names) names.textContent = st.sel.join(" · ");
    const clear = byText(bar, "button", "Clear");
    if (clear) clear.addEventListener("click", () => this.exitCompare(replyNode));
    const go = byText(bar, "button", "Compare");
    if (go) {
      if (st.sel.length < 2) go.style.opacity = "0.5";
      go.addEventListener("click", () => {
        if (st.sel.length === 2) this.runCompare(replyNode, st.sel.slice());
      });
    }
    st.bar = bar;
    replyNode.after(bar);
    this.scrollBottom();
  },

  exitCompare(replyNode) {
    const st = replyNode._cmp;
    if (!st) return;
    if (st.bar) st.bar.remove();
    replyNode.querySelectorAll("[data-cmpbadge]").forEach((b) => b.remove());
    delete replyNode._cmp;
  },

  async runCompare(replyNode, sel) {
    const st = replyNode._cmp;
    const go = st && st.bar ? byText(st.bar, "button", "Compare") : null;
    if (go) go.style.opacity = "0.5";
    try {
      const data = await api("/api/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ photo_a: sel[0], photo_b: sel[1] }),
      });
      this.exitCompare(replyNode);
      await this.renderCompare(replyNode, data);
    } catch (e) {
      this.exitCompare(replyNode);
      this.renderError("Compare failed: " + ((e && e.message) || e));
    }
  },

  async renderCompare(replyNode, data) {
    const node = cloneTpl(this.view, "tpl-compare");
    const intro = node.querySelector("p.font-body-md");
    const getDetail = async (id) => {
      try { return await photoDetail(id); } catch (e) { return this.rowsById[id] || null; }
    };
    const [da, db] = [await getDetail(data.photo_a), await getDetail(data.photo_b)];
    const placeName = (d, id) => ((d && d.place && d.place.name) || (d && d.place_name) || id);
    if (intro) {
      intro.textContent = "Comparing " + data.photo_a + " (" + placeName(da, data.photo_a) + ") and " +
        data.photo_b + " (" + placeName(db, data.photo_b) + "):";
    }
    const grid = node.querySelector("div.grid");
    const frames = grid ? [grid.children[0], grid.children[1]] : [];
    const details = [da, db];
    const tags = ["A", "B"];
    for (let i = 0; i < 2; i++) {
      const fr = frames[i], d = details[i], id = i === 0 ? data.photo_a : data.photo_b;
      if (!fr) continue;
      const img = fr.querySelector("img");
      if (img && d) {
        img.src = srcOf(d);
        img.setAttribute("data-alt", d.caption || id);
        img.alt = d.caption || id;
      }
      const lab = fr.querySelector("div.absolute");
      if (lab) lab.textContent = "Plate " + tags[i] + ": " + placeName(d, id) + " (" + id + ")";
      const flag = fr.querySelector("[data-flag]");
      if (flag) flag.dataset.target = id;
      const meta = fr.querySelectorAll("div.flex.items-center.justify-between span");
      const ct = d ? creditText(d.credit, d.collection) : null;
      if (meta[0]) { if (ct) meta[0].textContent = ct; else meta[0].remove(); }
      if (meta[1] && d) meta[1].textContent = (typeof VP_LABEL !== "undefined" && VP_LABEL[d.viewpoint]) || d.viewpoint || "";
    }
    const head = node.querySelectorAll("thead th");
    if (head[1]) head[1].textContent = "Plate A (" + data.photo_a + ")";
    if (head[2]) head[2].textContent = "Plate B (" + data.photo_b + ")";
    const syn = node.querySelector("div.bg-surface-container-high.rounded-lg");
    if (syn) syn.textContent = data.answer || "";
    const tbody = node.querySelector("tbody");
    if (tbody) {
      const tpl = tbody.children[0].cloneNode(true);
      tbody.innerHTML = "";
      for (const d of data.differences || []) {
        const tr = tpl.cloneNode(true);
        const tds = tr.querySelectorAll("td");
        if (tds[0]) tds[0].textContent = d.aspect || "";
        if (tds[1]) tds[1].textContent = d.a || "";
        if (tds[2]) tds[2].textContent = d.b || "";
        tbody.appendChild(tr);
      }
      if (!tbody.children.length) {
        const tr = tpl.cloneNode(true);
        const tds = tr.querySelectorAll("td");
        if (tds[0]) tds[0].textContent = "Verdict";
        if (tds[1]) tds[1].textContent = "see above";
        if (tds[2]) tds[2].textContent = "see above";
        tbody.appendChild(tr);
      }
    }
    if (this.focusId) this.wireActions(node, this.focusId);
    node.dataset.reply = String(++this.replySeq);
    if (replyNode && replyNode.after) replyNode.after(node);
    else this.xlist.appendChild(node);
    this.scrollBottom();
    return node;
  },

  wireFlag(view) {
    const dlg = $("#flag-modal", view);
    if (!dlg || dlg._wired) return;
    dlg._wired = true;
    const closeBtn = dlg.querySelector("button.w-8.h-8");
    const cancel = byText(dlg, "button", "Cancel");
    const submit = byText(dlg, "button", "Submit Flag");
    const done = () => { try { dlg.close(); } catch (e) { /* already closed */ } };
    if (closeBtn) closeBtn.addEventListener("click", done);
    if (cancel) cancel.addEventListener("click", done);
    if (submit) submit.addEventListener("click", async () => {
      const checked = dlg.querySelector('input[name="live-flag-reason"]:checked');
      const reason = checked ? checked.value : "other";
      const noteEl = dlg.querySelector("textarea");
      const targetEl = dlg.querySelector("#flag-target-label");
      const target = (targetEl && targetEl.textContent) || "unknown";
      submit.style.opacity = "0.5";
      try {
        const out = await api("/api/flag", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target: target, reason: reason, note: (noteEl && noteEl.value) || "", route: location.hash || "#/" }),
        });
        submit.style.opacity = "";
        const label = submit.querySelector("span");
        const old = label ? label.textContent : "";
        if (label) label.textContent = "Recorded " + (out.id || "✓");
        if (noteEl) noteEl.value = "";
        setTimeout(() => { if (label) label.textContent = old || "Submit Flag"; done(); }, 1200);
      } catch (e) {
        submit.style.opacity = "";
        const label = submit.querySelector("span");
        if (label) label.textContent = "Failed — try again";
        setTimeout(() => { if (label) label.textContent = "Submit Flag"; }, 2000);
      }
    });
  },

  openFlag(target) {
    const dlg = $("#flag-modal", this.view);
    if (!dlg) return;
    const label = dlg.querySelector("#flag-target-label");
    if (label) label.textContent = target;
    try { dlg.showModal(); } catch (e) { /* already open */ }
  },

  pickFile() {
    if (this.fileInput) this.fileInput.click();
  },

  addFlow(file) {
    this.showThread();
    const node = cloneTpl(this.view, "tpl-addprogress");
    const pill = node.querySelector("div.rounded-full");
    const pillText = pill ? pill.children[1] : null;
    const t0 = Date.now();
    const tick = () => { if (pillText) pillText.textContent = ((Date.now() - t0) / 1000).toFixed(0) + "s elapsed"; };
    tick();
    const timer = setInterval(tick, 500);
    this.loadingTimer = timer;
    const grid = node.querySelector("div.grid");
    const steps = grid ? Array.from(grid.children) : [];
    const titles = ["Uploaded", "Looking at the photo", "Working out the place", "Connecting to the world"];
    const dones = ["received", "Described the photo", "Place verdict ready", "World links ready"];
    node._paintJob = (stageIdx, status, detailOverride) => {
      steps.forEach((st, i) => {
        const icon = st.children[0];
        const content = st.children[1];
        const titleEl = content ? content.querySelector("span.font-label-md") : null;
        const detEl = content ? content.querySelector("span.font-body-sm") : null;
        if (titleEl) titleEl.textContent = titles[i];
        if (i < stageIdx || status === "done") {
          st.classList.remove("opacity-60");
          if (icon) {
            icon.className = "w-6 h-6 rounded-full bg-secondary-container text-on-secondary-fixed flex items-center justify-center flex-shrink-0 mt-0.5";
            icon.innerHTML = "";
            const s = document.createElement("span");
            s.className = "material-symbols-outlined text-[16px]";
            s.textContent = "check";
            icon.appendChild(s);
          }
          if (detEl) detEl.textContent = i === 0 && detailOverride ? detailOverride : dones[i];
        } else if (i === stageIdx && status !== "done" && status !== "error") {
          st.classList.remove("opacity-60");
          if (icon) {
            icon.className = "w-6 h-6 rounded-full bg-secondary text-surface flex items-center justify-center flex-shrink-0 mt-0.5";
            icon.innerHTML = "";
            const s = document.createElement("span");
            s.className = "w-2 h-2 rounded-full bg-surface animate-pulse";
            icon.appendChild(s);
          }
          if (detEl) detEl.textContent = "Working…";
        } else {
          st.classList.add("opacity-60");
          if (icon) {
            icon.className = "w-6 h-6 rounded-full bg-surface-container-highest flex items-center justify-center text-on-surface-variant mt-0.5 flex-shrink-0";
            icon.innerHTML = "";
            const s = document.createElement("span");
            s.className = "w-2 h-2 rounded-full bg-outline-variant";
            icon.appendChild(s);
          }
          if (detEl) detEl.textContent = "Waiting";
        }
      });
    };
    node._paintJob(0, "running");
    this.xlist.appendChild(node);
    this.scrollBottom();
    this.runUpload(file, node, timer);
  },

  async runUpload(file, node, timer) {
    const stop = () => { clearInterval(timer); if (this.loadingTimer === timer) this.loadingTimer = null; };
    const fail = (msg) => {
      stop();
      node._paintJob(0, "error");
      const h = node.querySelector("h3");
      if (h) h.textContent = "Could not add this photo.";
      const pill = node.querySelector("div.rounded-full");
      if (pill && pill.children[1]) pill.children[1].textContent = msg;
    };
    if (file.size > 10 * 1024 * 1024) { fail("Photo is larger than 10 MB."); return; }
    const form = new FormData();
    form.append("photo", file, file.name || "upload.jpg");
    let job;
    try {
      job = await api("/api/upload", { method: "POST", body: form });
    } catch (e) {
      let msg = (e && e.message) || "upload failed";
      if (msg.indexOf("demo code") !== -1) msg += " Enter it in the header field.";
      fail(msg);
      return;
    }
    const kb = Math.max(1, Math.round(file.size / 1024)) + " KB received";
    const poll = async () => {
      let st;
      try {
        st = await api("/api/jobs/" + encodeURIComponent(job.job_id));
      } catch (e) {
        stop();
        fail("Lost track of the job: " + ((e && e.message) || e));
        return;
      }
      if (st.status === "error") { fail(st.error || "annotation failed"); return; }
      node._paintJob(st.stage_index === undefined ? 1 : st.stage_index, st.status, kb);
      if (st.status === "done") {
        stop();
        if (st.result) {
          const filled = this.renderAddPhoto(st.result);
          node.replaceWith(filled);
          this.scrollBottom();
        } else {
          fail("The job finished but returned no result.");
        }
        return;
      }
      setTimeout(poll, 1500);
    };
    setTimeout(poll, 1500);
  },

  renderAddPhoto(result) {
    const node = cloneTpl(this.view, "tpl-addphoto");
    const photo = result.photo || {};
    const identify = result.identify || {};
    const primary = identify.primary || null;
    if (photo.photo_id) {
      this.rowsById[photo.photo_id] = photo;
      this.focusId = photo.photo_id;
      this.paintContext();
    }
    const h = node.querySelector("h2");
    const badge = node.querySelector("div.inline-flex");
    const conf = node.querySelector("span.whitespace-nowrap");
    if (primary && primary.name) {
      if (h) h.textContent = "This looks like " + primary.name;
      const btxt = badge ? badge.querySelectorAll("span")[1] : null;
      if (badge && btxt) {
        btxt.textContent = primary.status === "confirmed" ? "Confirmed" : "Candidate";
        badge.className = primary.status === "confirmed"
          ? "inline-flex items-center gap-1 px-2.5 py-1 rounded bg-secondary text-surface font-label-sm text-label-sm uppercase tracking-wide"
          : "inline-flex items-center gap-1 px-2.5 py-1 rounded bg-tertiary-fixed text-on-tertiary-fixed font-label-sm text-label-sm uppercase tracking-wide";
      }
      if (conf) {
        if (primary.confidence === null || primary.confidence === undefined) conf.remove();
        else conf.textContent = "Confidence: " + Math.round(primary.confidence * 100) + "%";
      }
    } else {
      if (h) h.textContent = "No place verdict for this photo.";
      if (badge) badge.remove();
      if (conf) conf.remove();
    }
    const evBox = node.querySelector("div.bg-surface-container-high.rounded-lg");
    if (evBox) {
      const bullets = Array.from(evBox.children).slice(1);
      const tpl = bullets[0] ? bullets[0].cloneNode(true) : null;
      bullets.forEach((b) => b.remove());
      const ev = (primary && primary.evidence) || [];
      if (ev.length && tpl) {
        const icons = { visible_text: "text_fields", architecture: "architecture", provided_title: "title", context: "near_me", owner_note: "person" };
        for (const e of ev.slice(0, 6)) {
          const b = tpl.cloneNode(true);
          const ic = b.querySelector("span");
          if (ic) ic.textContent = icons[e.kind] || "check_circle";
          const p = b.querySelector("p");
          if (p) p.textContent = e.detail || e.kind || "";
          evBox.appendChild(b);
        }
      } else {
        evBox.remove();
      }
    }
    const runnersTitle = byText(node, "h4", "Other possibilities");
    const runnersGrid = runnersTitle && runnersTitle.parentElement ? runnersTitle.parentElement.querySelector("div.grid") : null;
    const cands = identify.candidates || [];
    if (runnersGrid && cands.length) {
      const ctpl = runnersGrid.children[0].cloneNode(true);
      runnersGrid.innerHTML = "";
      for (const c of cands.slice(0, 3)) {
        const card = ctpl.cloneNode(true);
        const top = card.children[0];
        if (top) {
          if (top.children[0]) top.children[0].textContent = c.name || "Unknown";
          if (top.children[1]) top.children[1].textContent = (c.confidence === null || c.confidence === undefined) ? "—" : Math.round(c.confidence * 100) + "%";
        }
        const bar = card.querySelector("div.h-full");
        if (bar && c.confidence !== null && c.confidence !== undefined) bar.style.width = Math.round(c.confidence * 100) + "%";
        const subs = card.querySelectorAll("span");
        const sub = subs[subs.length - 1];
        if (sub) sub.textContent = areaOfKey(c.key) || ((c.evidence && c.evidence[0] && c.evidence[0].detail) || "");
        runnersGrid.appendChild(card);
      }
    } else if (runnersTitle && runnersTitle.parentElement) {
      runnersTitle.parentElement.remove();
    }
    const connTitle = byText(node, "h4", "Connected to the world");
    const connSec = connTitle ? connTitle.closest("div.flex.flex-col.gap-space-md") : null;
    const groups = result.bridge || {};
    const order = ["same_place", "another_angle", "taken_from_here", "similar_look"];
    const picks = [];
    for (const g of order) {
      if (picks.length >= 3) break;
      if (groups[g] && groups[g].length) picks.push({ group: g, item: groups[g][0] });
    }
    if (connSec && picks.length) {
      const sub = connSec.querySelector("span.font-body-sm");
      if (sub) sub.textContent = picks.length + " world photo" + (picks.length === 1 ? "" : "s") + " connect" + (picks.length === 1 ? "s" : "") + " to yours";
      const grid = connSec.querySelector("div.grid");
      if (grid) {
        const cardTpl = grid.children[0].cloneNode(true);
        grid.innerHTML = "";
        for (const pk of picks) {
          const it = pk.item;
          const card = cardTpl.cloneNode(true);
          const img = card.querySelector("img");
          if (img) {
            img.src = srcOf(it);
            img.setAttribute("data-alt", it.caption || it.photo_id);
            img.alt = it.caption || it.photo_id;
          }
          const gb = card.querySelector("div.absolute");
          if (gb) gb.textContent = BRIDGE_LABELS[pk.group] || pk.group;
          const spans = card.querySelectorAll("span.font-label-md, span.font-body-sm, span.font-label-sm");
          if (spans[0]) spans[0].textContent = it.place || it.photo_id;
          if (spans[1]) spans[1].textContent = it.reason_text || shortReasons(it.reasons);
          const ct = creditText(it.credit, it.collection);
          if (spans[2]) { if (ct) spans[2].textContent = ct; else spans[2].remove(); }
          card.dataset.pid = it.photo_id;
          const wrap = card.querySelector(".relative");
          if (wrap) {
            wrap.style.cursor = "pointer";
            wrap.addEventListener("click", () => { location.hash = "#/photo/" + it.photo_id; });
          }
          grid.appendChild(card);
        }
      }
    } else if (connSec) {
      connSec.remove();
    }
    const pub = byText(node, "button", "Add this photo to the world archive");
    if (pub) pub.remove(); // no such endpoint; see deferred.md
    const other = byText(node, "button", "Show other angles of this place");
    if (other && photo.photo_id) other.addEventListener("click", () => this.send("Show another angle of " + photo.photo_id));
    const dossier = byText(node, "button", "Inspect metadata dossier");
    if (dossier && photo.photo_id) dossier.addEventListener("click", () => { location.hash = "#/photo/" + photo.photo_id; });
    const ask = byText(node, "button", "Ask what has changed");
    if (ask) {
      const lab = ask.querySelectorAll("span");
      if (lab[lab.length - 1]) lab[lab.length - 1].textContent = "Ask about this photo";
      ask.addEventListener("click", () => {
        this.paintContext();
        const ti = $("#thread-input", this.view);
        if (ti) ti.focus();
        this.scrollBottom();
      });
    }
    node.dataset.reply = String(++this.replySeq);
    return node;
  },
  openTour(n) {
    const ov = $("#tour-overlay", this.view);
    if (!ov) return;
    show(ov, "block");
    if (!this.tourWired) {
      this.tourWired = true;
      const tabs = Array.from(ov.querySelectorAll(".tab-trigger"));
      tabs.forEach((t, i) => t.addEventListener("click", () => this.setTour(i + 1)));
      for (let i = 1; i <= 3; i++) {
        const dot = ov.querySelector("#dot-" + i);
        if (dot) dot.addEventListener("click", () => this.setTour(i));
      }
      const prev = byText(ov, "button", "Previous");
      if (prev) prev.addEventListener("click", () => this.setTour(this.tourIdx - 1));
      const next = ov.querySelector("#next-btn-text");
      if (next && next.parentElement) next.parentElement.addEventListener("click", () => this.setTour(this.tourIdx + 1));
      const skip = byText(ov, "button", "Skip tour");
      if (skip) skip.addEventListener("click", () => hide(ov));
      const close = ov.querySelector('[aria-label="Close Tour"]');
      if (close) close.addEventListener("click", () => hide(ov));
      const fin = byText(ov, "button", "Try your own search");
      if (fin) fin.addEventListener("click", () => {
        hide(ov);
        const landing = $("#landing", this.view);
        const target = (landing && !landing.classList.contains("hidden"))
          ? $("#archival-prompt-input", this.view)
          : $("#thread-input", this.view);
        if (target) target.focus();
      });
    }
    this.setTour(n || 1);
  },

  setTour(n) {
    const ov = $("#tour-overlay", this.view);
    if (!ov) return;
    this.tourIdx = Math.min(3, Math.max(1, n));
    const tabs = Array.from(ov.querySelectorAll(".tab-trigger"));
    const activeCls = "tab-trigger flex-1 min-h-[44px] px-space-sm py-2 rounded-t-lg bg-surface-container-lowest text-primary font-label-sm text-label-sm uppercase tracking-wider font-semibold flex items-center justify-center gap-2";
    const idleCls = "tab-trigger flex-1 min-h-[44px] px-space-sm py-2 rounded-t-lg bg-surface-container-high text-on-surface-variant font-label-sm text-label-sm uppercase tracking-wider font-medium flex items-center justify-center gap-2";
    tabs.forEach((t, i) => { t.className = i + 1 === this.tourIdx ? activeCls : idleCls; });
    for (let i = 1; i <= 3; i++) {
      const panel = ov.querySelector("#step-panel-" + i);
      if (panel) { if (i === this.tourIdx) show(panel, "flex"); else hide(panel); }
      const dot = ov.querySelector("#dot-" + i);
      if (dot) {
        dot.className = i === this.tourIdx
          ? "w-3 h-3 rounded-full bg-primary-container transition-all"
          : "w-3 h-3 rounded-full bg-outline-variant hover:bg-outline transition-all";
      }
    }
    const lab = ov.querySelector("#current-step-label");
    if (lab) lab.textContent = String(this.tourIdx);
    const prev = byText(ov, "button", "Previous");
    if (prev) { if (this.tourIdx === 1) hide(prev); else show(prev, "inline-flex"); }
    const nextTxt = ov.querySelector("#next-btn-text");
    const nextBtn = nextTxt ? nextTxt.parentElement : null;
    const fin = byText(ov, "button", "Try your own search");
    const titles = ["", "Next: Honest uncertainty", "Next: Connecting photos", ""];
    if (nextTxt) nextTxt.textContent = titles[this.tourIdx];
    if (nextBtn) { if (this.tourIdx === 3) hide(nextBtn); else show(nextBtn, "inline-flex"); }
    if (fin) { if (this.tourIdx === 3) show(fin, "inline-flex"); else hide(fin); }
    this.fillTourStep(this.tourIdx);
  },

  async fillTourStep(n) {
    const ov = $("#tour-overlay", this.view);
    if (!ov) return;
    if (!this.tourCache[n]) {
      try {
        this.tourCache[n] = await api("/tour/step" + n + ".json");
      } catch (e) {
        const panel = ov.querySelector("#step-panel-" + n);
        if (panel) {
          const h = panel.querySelector("h3");
          if (h) h.textContent = "This tour step is not recorded yet.";
        }
        return;
      }
    }
    const j = this.tourCache[n];
    if (n === 1) this.fillTour1(ov, j);
    else if (n === 2) this.fillTour2(ov, j);
    else this.fillTour3(ov, j);
  },

  fillTour1(ov, j) {
    const panel = ov.querySelector("#step-panel-1");
    if (!panel || !j.hero) return;
    const hero = j.hero;
    const prompt = panel.querySelector(".flex.justify-end p");
    if (prompt) prompt.textContent = "\u201C" + j.prompt + "\u201D";
    const badge = panel.querySelector("span.bg-secondary-container");
    if (badge) {
      const st = (hero.place && hero.place.status) || "candidate";
      badge.textContent = (st === "confirmed" ? "Confirmed" : "Candidate") + " match · " + (j.results || []).length + " photos found";
    }
    const img = panel.querySelector("img");
    if (img) { img.src = hero.src; img.setAttribute("data-alt", hero.caption || ""); img.alt = hero.caption || ""; }
    const plate = panel.querySelector("div.absolute.bottom-2");
    if (plate) plate.textContent = "Plate " + hero.photo_id;
    const meta = panel.querySelectorAll("div.flex.items-center.justify-between span");
    if (meta[0] && hero.credit) meta[0].textContent = "Photo: " + hero.credit.author;
    if (meta[1] && hero.credit) meta[1].textContent = hero.credit.license;
    const ps = panel.querySelectorAll("p");
    if (ps[1] && hero.place) ps[1].textContent = hero.place.name || "";
    const reasons = ((j.results || [])[0] && (j.results || [])[0].reasons) || [];
    if (ps[2]) ps[2].textContent = reasons.join("; ") || hero.caption || "";
    const tagBox = panel.querySelector("div.flex.flex-wrap.gap-space-xs");
    if (tagBox) {
      const tpl = tagBox.children[0].cloneNode(true);
      tagBox.innerHTML = "";
      const tags = [];
      if (hero.place && hero.place.name) tags.push(hero.place.name);
      for (const r of reasons) {
        if (r.indexOf("matches:") === 0) {
          for (const w of r.slice(8).split(",").map((s) => s.trim()).filter(Boolean)) tags.push(w);
        }
      }
      for (const t of tags.slice(0, 4)) {
        const s = tpl.cloneNode(true);
        s.textContent = t;
        tagBox.appendChild(s);
      }
    }
  },

  fillTour2(ov, j) {
    const panel = ov.querySelector("#step-panel-2");
    if (!panel) return;
    const results = (j.results || []).slice(0, 2);
    const prompt = panel.querySelector(".flex.justify-end p");
    if (prompt) prompt.textContent = "\u201C" + j.prompt + "\u201D";
    const badge = panel.querySelector("span.bg-tertiary-container");
    if (badge) {
      const places = {};
      for (const r of results) { if (r.place && r.place.name) places[r.place.name] = 1; }
      badge.textContent = "Candidate match · " + Object.keys(places).length + " possible places shown";
    }
    const grid = panel.querySelector("div.grid");
    results.forEach((r, i) => {
      const card = grid ? grid.children[i] : null;
      if (!card) return;
      const head = card.children[0];
      if (head && head.children[1]) head.children[1].textContent = "Plate " + r.photo_id;
      const img = card.querySelector("img");
      if (img && r.src) { img.src = r.src; img.setAttribute("data-alt", r.caption || ""); img.alt = r.caption || ""; }
      const foot = card.querySelectorAll("div.flex.items-center.justify-between span");
      if (foot[0]) foot[0].textContent = (r.place && r.place.name) || r.photo_id;
      if (foot[1] && r.credit) foot[1].textContent = r.credit.author + " · " + r.credit.license;
      const note = card.querySelector("div.p-space-xs");
      if (note) {
        const ev = (r.place && r.place.evidence && r.place.evidence[0] && r.place.evidence[0].detail) || "";
        note.textContent = ((r.place && r.place.name) || "") + (ev ? " — " + ev : "") || r.caption || "";
      }
    });
  },

  fillTour3(ov, j) {
    const panel = ov.querySelector("#step-panel-3");
    if (!panel || !j.mine || !j.theirs) return;
    const prompt = panel.querySelector(".flex.justify-end p");
    if (prompt) prompt.textContent = j.prompt || "";
    const imgs = panel.querySelectorAll("img");
    if (imgs[0]) { imgs[0].src = j.mine.src; imgs[0].alt = j.mine.caption || j.mine.photo_id; }
    if (imgs[1]) { imgs[1].src = j.theirs.src; imgs[1].alt = j.theirs.caption || j.theirs.photo_id; }
    const persp = panel.querySelector("div.px-1.pt-1\\.5");
    if (persp) persp.textContent = j.mine.caption || j.mine.photo_id;
    const plate = byText(panel, "span", "Plate #");
    if (plate) plate.textContent = "Plate " + j.theirs.photo_id;
    const footer = panel.querySelectorAll("div.flex.items-center.justify-between span");
    for (const s of footer) {
      if (s.className.indexOf("text-outline") !== -1 && j.theirs.credit) {
        s.textContent = j.theirs.credit.author + " · " + j.theirs.credit.license;
      } else if (s.textContent.indexOf("Public Survey Record") !== -1) {
        s.textContent = (j.theirs.place && j.theirs.place.name) || j.theirs.photo_id;
      }
    }
    const strip = panel.querySelector("span.tracking-widest");
    if (strip && j.link) {
      strip.textContent = (BRIDGE_LABELS[j.link.group] || j.link.group) + " · " + (j.link.reason || "");
    }
  },
};

/* ---------- Phase 1: credits + about views ---------- */
const credits = {
  view: null, rows: [], licenses: [], filterKey: "all", query: "", sort: "plate-asc",

  async mount(view) {
    this.view = view;
    this.filterKey = "all";
    this.query = "";
    this.sort = "plate-asc";
    try {
      const d = await api("/api/credits");
      this.rows = d.rows || [];
      this.licenses = d.licenses || [];
      this.render(d);
    } catch (e) {
      this.fail("Credits failed to load: " + ((e && e.message) || e));
    }
  },

  fail(msg) {
    const set = (id) => { const el = this.view.querySelector("#" + id); if (el) el.textContent = "–"; };
    set("cred-n-photos");
    set("cred-n-photogs");
    const line = this.view.querySelector("#cred-licenses-line");
    if (line) line.textContent = msg;
    const empty = this.view.querySelector("#noResultsState");
    if (empty) { empty.textContent = msg; show(empty, "block"); }
  },

  render(d) {
    const view = this.view;
    const set = (id, v) => { const el = view.querySelector("#" + id); if (el) el.textContent = v; };
    set("cred-n-photos", String(d.count || 0));
    set("cred-n-photogs", String(d.photographers || 0));
    set("cred-licenses-line", this.licenses.length + " open license designations");
    this.renderDonut();
    this.renderPills();
    const search = view.querySelector("#creditsSearch");
    if (search) search.addEventListener("input", () => { this.query = search.value; this.renderRows(); });
    const sort = view.querySelector("#sortDropdown");
    if (sort) sort.addEventListener("change", () => { this.sort = sort.value; this.renderRows(); });
    this.renderRows();
    if (this.rows[0]) {
      const ex = view.querySelector("#cite-example");
      if (ex) ex.textContent = citeText(this.rows[0].author, this.rows[0].license, this.rows[0].source_url);
    }
    const copy = view.querySelector("#copyTemplateBtn");
    if (copy) copy.addEventListener("click", () => {
      this.copyText("Photo: [Photographer Name] / ReelWorld Open Cadastre ([License Code]) · [Source URL]");
    });
  },

  renderDonut() {
    const view = this.view;
    const svg = view.querySelector("svg.viewbox, svg");
    const circles = svg ? Array.from(svg.querySelectorAll("circle")).slice(1) : [];
    const total = this.licenses.reduce((n, l) => n + (l.count || 0), 0) || 1;
    const strokes = { "cc-by-sa": "#476556", "cc-by": "#d5643b", cc0: "#1b1e23", other: "#76777b" };
    let cum = 0;
    this.licenses.forEach((l, i) => {
      let c = circles[i];
      if (!c && circles.length) {
        c = circles[circles.length - 1].cloneNode(true);
        svg.appendChild(c);
        circles.push(c);
      }
      if (!c) return;
      const len = Math.round(((l.count || 0) / total) * 88);
      c.setAttribute("stroke-dasharray", len + " 88");
      c.setAttribute("stroke-dashoffset", String(-cum));
      c.setAttribute("stroke", strokes[l.key] || "#76777b");
      cum += len;
    });
    for (let i = this.licenses.length; i < circles.length; i++) circles[i].remove();
    const legend = view.querySelector("div.flex.flex-col.text-\\[11px\\], div.leading-tight");
    const legendBox = legend || (svg && svg.parentElement ? svg.parentElement.querySelector("div.flex.flex-col") : null);
    if (legendBox) {
      const tpl = legendBox.children[0].cloneNode(true);
      legendBox.innerHTML = "";
      for (const l of this.licenses) {
        const row = tpl.cloneNode(true);
        const dot = row.querySelector("span.w-2");
        if (dot) dot.className = "w-2 h-2 rounded-full " + (LIC_DOT[l.key] || "bg-outline");
        row.childNodes.forEach((n) => { if (n.nodeType === 3) n.remove(); });
        row.appendChild(document.createTextNode(" " + (l.count || 0) + " " + (LIC_SHORT[l.key] || l.label) +
          " (" + Math.round(((l.count || 0) / total) * 100) + "%)"));
        legendBox.appendChild(row);
      }
    }
  },

  renderPills() {
    const group = this.view.querySelector("#licenseFilterGroup");
    if (!group) return;
    const pills = Array.from(group.querySelectorAll("button"));
    const activeCls = pills[0] ? pills[0].className : "";
    const idleCls = pills[1] ? pills[1].className : activeCls;
    group.innerHTML = "";
    const total = this.rows.length;
    const mk = (key, label) => {
      const b = document.createElement("button");
      b.className = key === this.filterKey ? activeCls : idleCls;
      b.textContent = label;
      b.addEventListener("click", () => { this.filterKey = key; this.renderPills(); this.renderRows(); });
      group.appendChild(b);
    };
    mk("all", "All Licenses (" + total + ")");
    for (const l of this.licenses) mk(l.key, l.label + " (" + (l.count || 0) + ")");
  },

  filteredRows() {
    const q = this.query.trim().toLowerCase();
    let rows = this.rows.filter((r) => {
      if (this.filterKey !== "all" && r.license_key !== this.filterKey) return false;
      if (!q) return true;
      return ((r.subject || "") + " " + (r.author || "") + " " + (r.photo_id || "")).toLowerCase().indexOf(q) !== -1;
    });
    const by = { "plate-asc": "photo_id", "photographer-asc": "author", "landmark-asc": "subject" }[this.sort] || "photo_id";
    rows = rows.slice().sort((a, b) => String(a[by] || "").localeCompare(String(b[by] || "")));
    return rows;
  },

  renderRows() {
    const view = this.view;
    const tbody = view.querySelector("#creditsTable tbody");
    if (!tbody) return;
    if (!tbody._tpl && tbody.children[0]) tbody._tpl = tbody.children[0].cloneNode(true);
    const tpl = tbody._tpl;
    tbody.innerHTML = "";
    tbody.hidden = false;
    const rows = this.filteredRows();
    const badgeCls = {
      "cc-by-sa": "bg-secondary-container text-on-secondary-container",
      "cc-by": "bg-tertiary-fixed text-on-tertiary-fixed",
      cc0: "bg-primary-container text-surface-bright",
      other: "bg-surface-container-high text-on-surface",
    };
    for (const r of rows) {
      const tr = tpl.cloneNode(true);
      tr.dataset.license = r.license_key || "other";
      tr.dataset.landmark = r.subject || "";
      tr.dataset.photographer = r.author || "";
      tr.dataset.plate = r.photo_id || "";
      const tds = tr.querySelectorAll("td");
      const img = tr.querySelector("img");
      if (img) {
        if (r.src) img.src = r.src;
        img.setAttribute("data-alt", r.subject || r.photo_id);
        img.alt = r.subject || r.photo_id;
      }
      const plate = tr.querySelector("span.absolute");
      if (plate) plate.textContent = r.photo_id || "";
      if (tds[1]) {
        const subj = tds[1].querySelector("div.font-headline-sm");
        if (subj) subj.textContent = r.subject || r.photo_id || "";
        const areaLine = tds[1].querySelector("div.text-on-surface-variant");
        if (areaLine) {
          if (r.area) {
            const spans = areaLine.querySelectorAll("span");
            if (spans[1]) spans[1].textContent = r.area;
          } else areaLine.remove();
        }
        const scene = tds[1].querySelector("span.uppercase");
        if (scene) { if (r.scene) scene.textContent = r.scene; else scene.remove(); }
      }
      if (tds[2]) {
        const who = tds[2].querySelector("div.font-medium");
        if (who) who.textContent = r.author || "Unknown";
        const handle = tds[2].querySelector("div.font-mono");
        if (handle) handle.remove();
        const tag = tds[2].querySelector("span.uppercase");
        if (tag) tag.remove();
      }
      if (tds[3]) {
        const a = tds[3].querySelector("a");
        if (a) {
          const spans = a.querySelectorAll("span");
          if (spans[1]) spans[1].textContent = r.license || "Unknown";
          a.className = "inline-flex items-center gap-1 px-2.5 py-1 rounded font-label-sm text-label-sm " + (badgeCls[r.license_key] || badgeCls.other);
          if (r.deed_url) { a.href = r.deed_url; a.target = "_blank"; a.rel = "noopener noreferrer"; }
          else { a.removeAttribute("href"); a.style.cursor = "default"; }
        }
      }
      if (tds[4]) {
        const a = tds[4].querySelector("a");
        const host = r.source_url ? hostOf(r.source_url) : null;
        if (a) {
          if (host) {
            a.href = r.source_url;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            const spans = a.querySelectorAll("span");
            if (spans[0]) spans[0].textContent = host;
          } else a.remove();
        }
        const ref = tds[4].querySelector("div.text-on-surface-variant\\/70, div.text-\\[11px\\]");
        const refDiv = ref || tds[4].querySelector("div:last-child");
        if (refDiv && refDiv !== a) refDiv.textContent = "Plate: " + (r.photo_id || "");
      }
      if (tds[5]) {
        const cite = tds[5].querySelector(".citation-btn");
        if (cite) cite.addEventListener("click", () => this.copyText(citeText(r.author, r.license, r.source_url)));
        const link = tds[5].querySelector("a");
        if (link && r.photo_id) link.href = "#/photo/" + r.photo_id;
      }
      tbody.appendChild(tr);
    }
    const empty = view.querySelector("#noResultsState");
    if (empty) { if (rows.length) hide(empty); else { empty.textContent = "No credits match this filter."; show(empty, "block"); } }
  },

  copyText(text) {
    const toast = (msg) => {
      const t = this.view.querySelector("#toastNotification");
      const m = this.view.querySelector("#toastMessage");
      if (m) m.textContent = msg;
      if (!t) return;
      t.classList.remove("translate-y-16", "opacity-0", "pointer-events-none");
      setTimeout(() => t.classList.add("translate-y-16", "opacity-0", "pointer-events-none"), 1600);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => toast("Citation copied to clipboard."), () => toast("Copy failed."));
    } else {
      toast("Copy is not available in this browser.");
    }
  },
};

const about = {
  async mount(view) {
    for (let i = 0; i < EX_ABOUT.length; i++) {
      const ex = EX_ABOUT[i];
      const img = view.querySelector("#about-img-" + (i === 0 ? "a" : "b"));
      if (img) { img.src = ex.src; img.setAttribute("data-alt", ex.alt); img.alt = ex.alt; }
      const plate = view.querySelector("#about-plate-" + (i === 0 ? "a" : "b"));
      if (plate) plate.textContent = (i === 0 ? "ARCHIVAL PLATE // " : "STRUCTURAL DETAIL // ") +
        ex.id.toUpperCase() + " " + ex.place.toUpperCase();
    }
    const counts = (typeof rwConfig !== "undefined" && rwConfig.counts) || {};
    const setPhotos = view.querySelector("#about-photos");
    if (setPhotos) setPhotos.textContent = (counts.world === null || counts.world === undefined) ? "–" : String(counts.world);
    const setPhotogs = view.querySelector("#about-photogs");
    if (setPhotogs) {
      try {
        const d = await api("/api/credits");
        setPhotogs.textContent = String(d.photographers || 0);
      } catch (e) {
        setPhotogs.textContent = "–";
      }
    }
    const purge = view.querySelector("#purge-session-btn");
    if (purge) purge.addEventListener("click", async () => {
      const label = purge.querySelector("span:last-child");
      try {
        await api("/sessions/" + encodeURIComponent(sessionId()) + "/reset", { method: "POST" });
        if (label) label.textContent = "Session reset ✓";
      } catch (e) {
        if (label) label.textContent = "Reset failed — try again";
      }
      setTimeout(() => { if (label) label.textContent = "Reset this session"; }, 2000);
    });
  },
};

function creditLine(credit) {
  const wrap = document.createElement("span");
  wrap.appendChild(document.createTextNode("Photo by "));
  const who = document.createElement("strong");
  who.textContent = credit.author || "Unknown photographer";
  wrap.appendChild(who);
  if (credit.license) {
    const lic = document.createElement("span");
    lic.className = "font-mono bg-papyrus-200 px-2 py-0.5 rounded text-[10px] text-espresso-900 border border-parchment-border ml-2";
    if (credit.source_url) {
      const a = document.createElement("a");
      a.href = credit.source_url;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = credit.license;
      a.className = "underline decoration-dotted hover:text-ochre";
      a.addEventListener("click", (e) => e.stopPropagation());
      lic.appendChild(a);
    } else {
      lic.textContent = credit.license;
    }
    wrap.appendChild(lic);
  }
  return wrap;
}

/* ---------- share card: 1080x1350 PNG drawn in the browser ----------
   Same-origin /photos/ bytes keep the canvas clean (no taint). Uses the
   app tokens (parchment, espresso, ochre, forest) and Plus Jakarta Sans. */
const SHARE_W = 1080, SHARE_H = 1350;

function shareRoundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function shareFit(ctx, text, maxW) {
  let t = String(text || "").replace(/\s+/g, " ").trim();
  if (ctx.measureText(t).width <= maxW) return t;
  while (t.length > 1 && ctx.measureText(t + "…").width > maxW) t = t.slice(0, -1);
  return t.trim() + "…";
}

function shareWrap(ctx, text, maxW, maxLines) {
  const words = String(text || "").replace(/\s+/g, " ").trim().split(" ").filter(Boolean);
  const lines = [];
  let line = "";
  words.forEach((w) => {
    const t = line ? line + " " + w : w;
    if (ctx.measureText(t).width > maxW && line) { lines.push(line); line = w; }
    else line = t;
  });
  if (line) lines.push(line);
  return lines.slice(0, maxLines);
}

function sharePill(ctx, x, y, text, font, fg, bg, stroke) {
  ctx.font = font;
  const w = ctx.measureText(text).width + 48, h = 54;
  shareRoundRect(ctx, x, y, w, h, 27);
  if (bg) { ctx.fillStyle = bg; ctx.fill(); }
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 3; ctx.stroke(); }
  ctx.fillStyle = fg;
  ctx.textBaseline = "middle";
  ctx.fillText(text, x + 24, y + h / 2 + 2);
  ctx.textBaseline = "alphabetic";
  return w;
}

function shareLoadPhoto(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("The photo file could not be loaded."));
    img.src = src;
  });
}

async function buildShareCard(d) {
  try { await document.fonts.ready; } catch (e) { /* system fonts then */ }
  const img = await shareLoadPhoto(d.src);
  const cv = document.createElement("canvas");
  cv.width = SHARE_W; cv.height = SHARE_H;
  const ctx = cv.getContext("2d");
  const FONT = '"Plus Jakarta Sans", system-ui, sans-serif';
  const M = 72, CW = SHARE_W - M * 2; // margin, content width
  ctx.fillStyle = "#F4EFEB";
  ctx.fillRect(0, 0, SHARE_W, SHARE_H);
  /* Header: brand left, engine pill right. */
  ctx.fillStyle = "#151311";
  ctx.font = '800 58px ' + FONT;
  ctx.fillText("ReelWorld", M, 132);
  ctx.font = '600 27px ' + FONT;
  const pillText = "Built with Muse Spark Open";
  const pillW = ctx.measureText(pillText).width + 48;
  sharePill(ctx, SHARE_W - M - pillW, 82, pillText, '600 27px ' + FONT,
            "#D35400", "#FAEEE7", "#C85A32");
  /* Photo, cover-fit with rounded corners. */
  const px = M, py = 188, pw = CW, ph = 580;
  const s = Math.max(pw / img.naturalWidth, ph / img.naturalHeight);
  const dw = img.naturalWidth * s, dh = img.naturalHeight * s;
  ctx.save();
  shareRoundRect(ctx, px, py, pw, ph, 28);
  ctx.clip();
  ctx.fillStyle = "#E4DCD2";
  ctx.fillRect(px, py, pw, ph);
  ctx.drawImage(img, px + (pw - dw) / 2, py + (ph - dh) / 2, dw, dh);
  ctx.restore();
  /* Place + status badge. */
  let y = py + ph + 78;
  const place = d.place || {};
  ctx.fillStyle = "#151311";
  ctx.font = '700 52px ' + FONT;
  const nameLines = shareWrap(ctx, place.name || "Place unknown", CW, 2);
  nameLines.forEach((ln) => { ctx.fillText(ln, M, y); y += 62; });
  const st = place.status;
  if (st === "confirmed" || st === "candidate") {
    const label = st === "confirmed" ? "Confirmed" : "Candidate";
    y += 14;
    if (st === "confirmed") {
      sharePill(ctx, M, y, label, '700 28px ' + FONT, "#FFFFFF", "#1E4732", null);
    } else {
      sharePill(ctx, M, y, label, '700 28px ' + FONT, "#C85A32", "#FEF8F4", "#C85A32");
    }
    y += 54;
  }
  /* Two short evidence lines. */
  let evs = (place.evidence || []).map(
    (ev) => (ev.kind ? String(ev.kind).replace(/_/g, " ") + ": " : "") + (ev.detail || ""));
  if (!evs.length) evs = (d.uncertainties || []).slice(0, 2);
  if (!evs.length) evs = ["No recorded evidence."];
  ctx.fillStyle = "#4D4740";
  ctx.font = '400 29px ' + FONT;
  y += 52;
  evs.slice(0, 2).forEach((ev) => {
    ctx.fillText("• " + shareFit(ctx, ev, CW - 34), M, y);
    y += 44;
  });
  /* Credit + footer, placed below the evidence (capped blocks above
     guarantee this stays inside 1350px: worst case ends near y=1330). */
  const divY = y + 36;
  ctx.fillStyle = "#D8CFC3";
  ctx.fillRect(M, divY, CW, 2);
  ctx.fillStyle = "#686057";
  ctx.font = '500 27px ' + FONT;
  const credit = d.collection === "world"
    ? "Photo by " + ((d.credit && d.credit.author) || "Unknown photographer") +
      " • " + ((d.credit && d.credit.license) || "License unknown")
    : "Your personal photo";
  ctx.fillText(shareFit(ctx, credit, CW), M, divY + 60);
  ctx.fillStyle = "#8A8074";
  ctx.font = '500 25px ' + FONT;
  ctx.fillText(d.photo_id + " • ReelWorld archive", M, divY + 112);
  return new Promise((res) => cv.toBlob(res, "image/png"));
}

/* Story cover card: same builder, tokens and pills as the photo card. */
async function buildStoryCard(d) {
  const chapters = d.chapters || [];
  const cover = chapters.length && chapters[0].photos && chapters[0].photos[0];
  if (!cover) throw new Error("The story has no photos to share.");
  try { await document.fonts.ready; } catch (e) { /* system fonts then */ }
  const img = await shareLoadPhoto(cover.src);
  const cv = document.createElement("canvas");
  cv.width = SHARE_W; cv.height = SHARE_H;
  const ctx = cv.getContext("2d");
  const FONT = '"Plus Jakarta Sans", system-ui, sans-serif';
  const M = 72, CW = SHARE_W - M * 2;
  ctx.fillStyle = "#F4EFEB";
  ctx.fillRect(0, 0, SHARE_W, SHARE_H);
  ctx.fillStyle = "#151311";
  ctx.font = '800 58px ' + FONT;
  ctx.fillText("ReelWorld", M, 132);
  ctx.font = '600 27px ' + FONT;
  const pillText = "Built with Muse Spark Open";
  const pillW = ctx.measureText(pillText).width + 48;
  sharePill(ctx, SHARE_W - M - pillW, 82, pillText, '600 27px ' + FONT,
            "#D35400", "#FAEEE7", "#C85A32");
  /* Cover photo. */
  const px = M, py = 188, pw = CW, ph = 440;
  const s = Math.max(pw / img.naturalWidth, ph / img.naturalHeight);
  const dw = img.naturalWidth * s, dh = img.naturalHeight * s;
  ctx.save();
  shareRoundRect(ctx, px, py, pw, ph, 28);
  ctx.clip();
  ctx.fillStyle = "#E4DCD2";
  ctx.fillRect(px, py, pw, ph);
  ctx.drawImage(img, px + (pw - dw) / 2, py + (ph - dh) / 2, dw, dh);
  ctx.restore();
  /* Title, intro, chapter list. */
  let y = py + ph + 72;
  ctx.fillStyle = "#151311";
  ctx.font = '700 52px ' + FONT;
  shareWrap(ctx, d.title || d.theme || "Photo story", CW, 2).forEach((ln) => {
    ctx.fillText(ln, M, y); y += 60;
  });
  ctx.fillStyle = "#4D4740";
  ctx.font = '400 29px ' + FONT;
  y += 50;
  ctx.fillText(shareFit(ctx, d.intro || "", CW), M, y);
  y += 40;
  const nPhotos = chapters.reduce((n, ch) => n + ((ch.photos || []).length), 0);
  chapters.slice(0, 5).forEach((ch, i) => {
    const n = (ch.photos || []).length;
    ctx.fillText((i + 1) + ". " + shareFit(ctx,
      (ch.heading || "") + " — " + n + (n === 1 ? " photo" : " photos"), CW - 44), M, y);
    y += 44;
  });
  /* Credit + footer. */
  const divY = y + 36;
  ctx.fillStyle = "#D8CFC3";
  ctx.fillRect(M, divY, CW, 2);
  const authors = (d.credits || []).map((c) => c.author).filter(Boolean);
  const credit = authors.length
    ? "Photos by " + authors.slice(0, 2).join(", ") +
      (authors.length > 2 ? " +" + (authors.length - 2) + " more" : "")
    : (d.collection === "personal" ? "Your personal photos" : "Photographer unknown");
  ctx.fillStyle = "#686057";
  ctx.font = '500 27px ' + FONT;
  ctx.fillText(shareFit(ctx, credit + " • " + nPhotos + " photos", CW), M, divY + 60);
  ctx.fillStyle = "#8A8074";
  ctx.font = '500 25px ' + FONT;
  ctx.fillText("ReelWorld photo story", M, divY + 112);
  return new Promise((res) => cv.toBlob(res, "image/png"));
}

/* ---------- photo view ---------- */
const SPINNER_SVG = '<svg class="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" fill="currentColor"></path></svg>';

function setBtnLoading(btn, on, text) {
  if (!btn) return;
  if (on) {
    if (btn.dataset.orig === undefined) btn.dataset.orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = "";
    const s = document.createElement("span");
    s.innerHTML = SPINNER_SVG;
    const t = document.createElement("span");
    t.textContent = text || "Working…";
    btn.append(s.firstChild, t);
  } else {
    btn.disabled = false;
    if (btn.dataset.orig !== undefined) btn.innerHTML = btn.dataset.orig;
  }
}

function goHomeSearch(message) {
  pendingSearch = message;
  if ((location.hash || "#/") !== "#/") location.hash = "#/";
  else route();
}

const photo = {
  view: null,
  id: null,
  data: null,

  mount(view, id) {
    this.view = view;
    this.id = id;
    this.data = null;
    $("#back-link", view).addEventListener("click", (e) => {
      e.preventDefault();
      if (window.history.length > 1) window.history.back();
      else location.hash = "#/";
    });
    $("#btn-fullscreen", view).addEventListener("click", () => {
      const fig = $("#hero-figure", view);
      try {
        if (document.fullscreenElement) document.exitFullscreen();
        else if (fig.requestFullscreen) fig.requestFullscreen();
      } catch (e) { /* not supported; the photo stays inline */ }
    });
    $("#ask-form", view).addEventListener("submit", (e) => {
      e.preventDefault();
      const q = $("#ask-input", view).value.trim();
      if (q) this.ask(q);
    });
    $("#ask-chips", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-q]");
      if (!b) return;
      $("#ask-input", view).value = b.dataset.q;
      this.ask(b.dataset.q);
    });
    $("#btn-ask", view).addEventListener("click", () => {
      const input = $("#ask-input", view);
      input.scrollIntoView({ block: "center", behavior: "smooth" });
      input.focus();
    });
    $("#btn-find", view).addEventListener("click", () => this.bridge("all"));
    $("#btn-angle", view).addEventListener("click", () => this.angle());
    $("#btn-more", view).addEventListener("click", () => {
      goHomeSearch("Show me photos like " + this.id);
    });
    $("#btn-reject", view).addEventListener("click", () => goHomeSearch("not this one"));
    $("#btn-share", view).addEventListener("click", () => this.share());
    $("#share-confirm", view).addEventListener("click", () => this.enableSharing());
    $("#bridge-close", view).addEventListener("click", () => hide($("#bridge-panel", view)));
    $("#bridge-groups", view).addEventListener("click", (e) => {
      if (placeLinkClick(e)) return;
      const m = e.target.closest("[data-target]");
      if (m) location.hash = "#/photo/" + m.dataset.target;
    });
    $("#kit-tabs", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-format]");
      if (b) this.paintCitation(b.dataset.format);
    });
    $("#kit-copy", view).addEventListener("click", () => this.copyCitation());
    $("#kit-json", view).addEventListener("click", () => this.downloadJson());
    $("#kit-flag-send", view).addEventListener("click", () => this.sendKitFlag());
    $("#photo-retry", view).addEventListener("click", () => this.load());
    this.load();
  },

  async load() {
    const view = this.view;
    $("#photo-loading", view).hidden = false;
    $("#dossier", view).hidden = true;
    $("#photo-error", view).hidden = true;
    $("#kit-section", view).hidden = true;
    $("#photo-error", view).classList.add("hidden");
    $("#photo-error", view).classList.remove("flex");
    try {
      this.data = await photoDetail(this.id);
      if (!this.data) throw new Error("I could not find that photo.");
      if (!view.isConnected) return;
      this.render(this.data);
      $("#photo-loading", view).hidden = true;
      $("#dossier", view).hidden = false;
      $("#kit-section", view).hidden = false;
      try {
        if (sessionStorage.getItem("rw.askFocus") === this.id) {
          sessionStorage.removeItem("rw.askFocus");
          const input = $("#ask-input", view);
          input.scrollIntoView({ block: "center" });
          input.focus();
        }
      } catch (e) { /* private mode; stay at the top */ }
    } catch (e) {
      if (!view.isConnected) return;
      $("#photo-loading", view).hidden = true;
      $("#photo-error-text", view).textContent = String((e && e.message) || e);
      const box = $("#photo-error", view);
      box.hidden = false;
      box.classList.remove("hidden");
      box.classList.add("flex");
    }
  },

  render(d) {
    const view = this.view;
    const T = (name) => $("#" + name, view).content.firstElementChild;
    $("#dossier-id", view).textContent = "Dossier Item #" + d.photo_id;
    $("#dossier-sub-id", view).textContent = "ID: " + d.photo_id;
    $("#file-name", view).textContent = String(d.file || d.photo_id).split("/").pop();
    $("#collection-chip", view).textContent =
      d.collection === "world" ? "World archive" : "My photo";
    $("#strip-place", view).textContent = (d.place && d.place.name) || "Place unknown";
    const img = $("#hero-photo", view);
    img.src = d.src;
    img.alt = d.caption || d.photo_id;
    img.addEventListener("error", () => img.setAttribute("data-broken", "true"));
    $("#watermark-left", view).textContent = d.photo_id + " • " + d.collection;
    $("#watermark-right", view).textContent = VP_LABEL[d.viewpoint] || d.viewpoint || "";
    const scene = d.scene || {};
    const bits = [scene.type, scene.time_of_day, scene.setting].filter(Boolean);
    $("#scene-line", view).textContent = bits.length ? "Scene: " + bits.join(" • ") : "Scene unknown";
    const n = d.people_count || 0;
    $("#people-line", view).textContent = n + (n === 1 ? " person visible" : " people visible");
    /* 1. Summary. */
    $("#summary-caption", view).textContent = d.caption || d.photo_id;
    const desc = $("#summary-description", view);
    if (d.description && d.description !== d.caption) {
      desc.textContent = d.description;
      desc.classList.remove("hidden");
    } else desc.classList.add("hidden");
    /* 2. Things. */
    const things = d.things || [];
    $("#things-count", view).textContent = things.length + " things recorded";
    const thingsBox = $("#things", view);
    thingsBox.innerHTML = "";
    if (!things.length) thingsBox.textContent = "None recorded";
    things.forEach((t) => {
      const chip = T("tpl-thing").cloneNode(true);
      chip.textContent = t.label || "thing";
      const attrs = (t.attributes || []).join(", ");
      chip.title = [attrs, t.confidence == null ? "" : "confidence " + t.confidence]
        .filter(Boolean).join(" • ") || t.label || "";
      thingsBox.appendChild(chip);
    });
    /* 3. Signs. */
    const signs = d.signs || [];
    $("#signs-count", view).textContent = signs.length + " Identified";
    const signsBox = $("#signs", view);
    signsBox.innerHTML = "";
    if (!signs.length) {
      const p = document.createElement("p");
      p.className = "font-body-sm text-body-sm text-stone-500";
      p.textContent = "No signs read";
      signsBox.appendChild(p);
    }
    signs.forEach((s) => {
      const card = T("tpl-sign").cloneNode(true);
      $("[data-slot=text]", card).textContent = "“" + (s.text || "") + "”";
      if (s.where) {
        const w = $("[data-slot=where]", card);
        w.textContent = s.where;
        w.classList.remove("hidden");
      }
      const leg = String(s.legibility || "").toLowerCase();
      const badge = $("[data-slot=badge]", card);
      if (leg === "clear") badge.className += " bg-[#c9ead8] text-[#1e4732]";
      else if (leg === "partial") badge.className += " bg-[#ffdbcf] text-[#822801]";
      else badge.className += " bg-surface-container-high text-on-surface-variant";
      badge.textContent = leg ? leg[0].toUpperCase() + leg.slice(1) : "Unknown";
      if (typeof s.confidence === "number") {
        const row = $("[data-slot=conf-row]", card);
        row.classList.remove("hidden");
        row.classList.add("flex");
        const bar = $("[data-slot=conf-bar]", row);
        bar.style.width = Math.round(s.confidence * 100) + "%";
        bar.className += leg === "partial" ? " bg-[#d5643b]" : " bg-[#1e4732]";
      }
      signsBox.appendChild(card);
    });
    /* 4. Place. */
    const badges = $("#place-badges", view);
    badges.innerHTML = "";
    const mkBadge = (status) => {
      const b = document.createElement("span");
      if (status === "confirmed") {
        b.className = "bg-[#1e4732] text-white px-2.5 py-0.5 rounded-full text-[11px] font-medium inline-flex items-center gap-1 shadow-sm";
        b.innerHTML = "";
        const ic = document.createElement("span");
        ic.className = "material-symbols-outlined text-[12px]";
        ic.textContent = "check_circle";
        const tx = document.createElement("span");
        tx.textContent = "Confirmed";
        b.append(ic, tx);
      } else {
        b.className = "border border-[#c85a32]/60 text-[#c85a32] bg-[#fef8f4] px-2 py-0.5 rounded-full text-[11px] font-medium inline-flex items-center gap-1";
        const ic = document.createElement("span");
        ic.className = "material-symbols-outlined text-[12px]";
        ic.textContent = "radar";
        const tx = document.createElement("span");
        tx.textContent = "Candidate";
        b.append(ic, tx);
      }
      return b;
    };
    if (d.place) {
      if (d.place.status === "confirmed" || d.place.status === "candidate") {
        badges.appendChild(mkBadge(d.place.status));
      }
      $("#place-name", view).textContent = d.place.name || "Place unknown";
      $("#place-key", view).textContent = d.place.key || "";
      const evBox = $("#place-evidence", view);
      evBox.innerHTML = "";
      (d.place.evidence || []).forEach((ev) => {
        const row = T("tpl-evidence").cloneNode(true);
        const kind = String(ev.kind || "").replace(/_/g, " ");
        $("[data-slot=kind]", row).textContent = kind ? kind + ": " : "";
        $("[data-slot=detail]", row).textContent = ev.detail || "";
        evBox.appendChild(row);
      });
      const wrap = $("#place-evidence-wrap", view);
      wrap.classList.remove("hidden");
      wrap.classList.add("flex");
      if (typeof d.place.confidence === "number") {
        const cw = $("#place-confidence-wrap", view);
        cw.classList.remove("hidden");
        cw.classList.add("flex");
        $("#place-confidence-text", view).textContent =
          Math.round(d.place.confidence * 100) + "%";
        $("#place-confidence-bar", view).style.width =
          Math.round(d.place.confidence * 100) + "%";
      }
    } else {
      $("#place-name", view).textContent = "Place unknown";
      $("#place-key", view).textContent = "";
      const wrap = $("#place-evidence-wrap", view);
      wrap.classList.add("hidden");
      wrap.classList.remove("flex");
    }
    const pn = $("#place-name", view);
    if (d.place && d.place.key) {
      pn.href = "#/place/" + d.place.key;
      pn.classList.add("hover:text-ochre", "hover:underline", "cursor-pointer");
    } else {
      pn.removeAttribute("href");
      pn.classList.remove("hover:text-ochre", "hover:underline", "cursor-pointer");
    }
    const tf = $("#taken-from", view);
    if (d.taken_from && d.taken_from.name) {
      tf.textContent = "Taken from: " + d.taken_from.name +
        (d.taken_from.status ? " (" + d.taken_from.status + ")" : "");
      tf.classList.remove("hidden");
    } else tf.classList.add("hidden");
    const lms = d.landmarks || [];
    const lmWrap = $("#landmarks-wrap", view);
    if (lms.length) {
      const lmBox = $("#landmarks", view);
      lmBox.innerHTML = "";
      lms.forEach((lm) => {
        const row = T("tpl-evidence").cloneNode(true);
        row.className = "flex items-start gap-1.5 text-xs text-espresso-900";
        $("[data-slot=kind]", row).textContent =
          (lm.name || "Landmark") + (lm.status ? " (" + lm.status + ")" : "") + ": ";
        $("[data-slot=detail]", row).textContent =
          (lm.evidence || []).map((e) => e.detail).filter(Boolean).join(" • ") || "";
        lmBox.appendChild(row);
      });
      lmWrap.classList.remove("hidden");
      lmWrap.classList.add("flex");
    } else {
      lmWrap.classList.add("hidden");
      lmWrap.classList.remove("flex");
    }
    /* 5. Uncertainties. */
    const unBox = $("#uncertainties", view);
    unBox.innerHTML = "";
    const uns = d.uncertainties || [];
    if (!uns.length) {
      const p = document.createElement("p");
      p.className = "text-xs text-stone-500";
      p.textContent = "None recorded";
      unBox.appendChild(p);
    }
    uns.forEach((u) => {
      const row = T("tpl-uncertainty").cloneNode(true);
      $("[data-slot=text]", row).textContent = u;
      unBox.appendChild(row);
    });
    /* Credit + license. */
    if (d.collection === "world") {
      $("#credit-line", view).textContent =
        "Photo by " + ((d.credit && d.credit.author) || "Unknown photographer");
      const lic = $("#license-line", view);
      lic.innerHTML = "";
      const label = (d.credit && d.credit.license) || "License unknown";
      if (d.credit && d.credit.source_url) {
        const a = document.createElement("a");
        a.href = d.credit.source_url;
        a.target = "_blank";
        a.rel = "noopener";
        a.className = "underline decoration-dotted hover:text-ochre";
        a.textContent = label;
        lic.appendChild(a);
      } else lic.textContent = label;
      $("#btn-find-label", view).textContent = "Compare with mine";
    } else {
      $("#credit-line", view).textContent = "Your photo";
      $("#license-line", view).textContent = "Private by default";
      $("#btn-find-label", view).textContent = "Find in the world";
    }
    /* Suggested questions. */
    const chips = $("#ask-chips", view);
    $$(":scope > .rw-askchip", chips).forEach((c) => c.remove());
    (d.suggested_questions || []).forEach((q) => {
      const b = T("tpl-askchip").cloneNode(true);
      b.classList.add("rw-askchip");
      b.dataset.q = q;
      $("[data-slot=label]", b).textContent = q;
      chips.appendChild(b);
    });
    this.paintShare(d);
    this.paintKit(d);
  },

  /* Share gating. World photos are public already; personal photos stay
     private until the user explicitly enables sharing, and never when
     people are visible (faces may be showing, and we cannot verify
     otherwise from the fields /api/photo exposes). */
  paintShare(d) {
    const view = this.view;
    const btn = $("#btn-share", view);
    const row = $("#share-row", view);
    const confirm = $("#share-confirm", view);
    this.shareSay("");
    if (d.collection !== "personal") {
      btn.disabled = false;
      hide(row);
      return;
    }
    btn.disabled = true;
    show(row);
    if ((d.people_count || 0) > 0) {
      hide(confirm);
      $("#share-note", view).textContent =
        "Sharing stays off for this photo: people are visible in it, so it can't be shared.";
    } else {
      $("#share-note", view).textContent =
        "Personal photos are private. Sharing exports this photo as an image file.";
      show(confirm);
    }
  },

  enableSharing() {
    const view = this.view;
    hide($("#share-confirm", view));
    $("#share-note", view).textContent = "Sharing enabled for this photo.";
    $("#btn-share", view).disabled = false;
  },

  paintKit(d) {
    const view = this.view;
    const world = d.collection === "world";
    $("#kit-private", view).classList.toggle("hidden", world);
    $("#kit-grid", view).classList.toggle("hidden", !world);
    $("#kit-status", view).classList.toggle("hidden", !world);
    this.kitFlagSay("");
    if (!world) return;
    const c = d.credit || {};
    const author = c.author || "Unknown photographer";
    const lic = c.license || "License unknown";
    $("#kit-photo-id", view).textContent = "SPECIMEN #" + d.photo_id;
    $("#kit-open-full", view).href = d.src;
    const thumb = $("#kit-thumb", view);
    thumb.src = d.src;
    thumb.alt = d.caption || d.photo_id;
    $("#kit-reg", view).textContent = "REG #" + d.photo_id;
    $("#kit-title", view).textContent = (d.place && d.place.name) || d.caption || d.photo_id;
    $("#kit-caption", view).textContent = d.caption || d.photo_id;
    $("#kit-photographer", view).textContent = author;
    $("#kit-license-badge", view).textContent = lic;
    const lname = $("#kit-license-name", view);
    lname.innerHTML = "";
    lname.appendChild(document.createTextNode(LICENSE_NAMES[lic] || lic));
    if (LICENSE_DEEDS[lic]) {
      lname.appendChild(document.createTextNode(" "));
      const a = document.createElement("a");
      a.href = LICENSE_DEEDS[lic];
      a.target = "_blank";
      a.rel = "noopener";
      a.className = "underline decoration-dotted hover:text-ochre";
      a.textContent = "legal code";
      lname.appendChild(a);
    }
    if (d.place && d.place.name) {
      $("#kit-subject", view).textContent = d.place.name;
      $("#kit-subject-sub", view).textContent = "Place status: " + (d.place.status || "unknown");
    } else {
      $("#kit-subject", view).textContent = "No place verdict";
      $("#kit-subject-sub", view).textContent = "The archive has no place verdict for this photo.";
    }
    const srcEl = $("#kit-source", view);
    srcEl.innerHTML = "";
    if (c.source_url) {
      const a = document.createElement("a");
      a.href = c.source_url;
      a.target = "_blank";
      a.rel = "noopener";
      a.className = "underline decoration-dotted hover:text-ochre break-all";
      a.textContent = hostOf(c.source_url);
      srcEl.appendChild(a);
    } else srcEl.textContent = "Source not recorded";
    const fam = licenseFamily(lic);
    $("#kit-note", view).textContent = fam === "zero"
      ? "This photo carries no reuse conditions under " + lic + "; crediting " + author + " is appreciated but not required."
      : fam === "unknown"
      ? "No license is recorded for this photo, so the archive cannot grant reuse. Check the source record first."
      : "Reuse this photo under " + lic + ": credit " + author + " and link the license." +
        (fam === "by-sa" ? " Share any changes under the same license." : "") +
        " Moral rights stay with the photographer.";
    const sum = licenseSummary(lic);
    $("#kit-license-sentence", view).textContent = sum.sentence;
    $("#kit-disclaimer", view).textContent = sum.disclaimer;
    const mx = $("#kit-matrix", view);
    mx.innerHTML = "";
    sum.terms.forEach((t) => {
      const row = document.createElement("div");
      row.className = "bg-surface-container p-3 rounded flex items-start gap-3";
      const ic = document.createElement("div");
      ic.className = "w-7 h-7 rounded flex items-center justify-center shrink-0 " +
        (t.required ? "bg-tertiary-fixed text-on-tertiary-fixed" : "bg-secondary-container text-on-secondary-fixed-variant");
      const glyph = document.createElement("span");
      glyph.className = "material-symbols-outlined text-[18px]";
      glyph.textContent = t.icon;
      ic.appendChild(glyph);
      const tx = document.createElement("div");
      tx.className = "flex flex-col";
      const lab = document.createElement("span");
      lab.className = "font-label-md text-label-md text-on-surface uppercase";
      lab.textContent = t.label;
      const sub = document.createElement("span");
      sub.className = "font-body-sm text-body-sm text-on-surface-variant";
      sub.textContent = t.text;
      tx.append(lab, sub);
      row.append(ic, tx);
      mx.appendChild(row);
    });
    $("#kit-canonical", view).href = this.kitFields().pageUrl;
    $("#kit-status-license", view).textContent = "License: " + lic;
    this.paintCitation("plain");
  },

  kitFields() {
    const d = this.data || {};
    const c = d.credit || {};
    const base = location.origin + location.pathname;
    return {
      author: c.author || "Unknown photographer",
      license: c.license || "License unknown",
      caption: d.caption || d.photo_id || "",
      photoId: d.photo_id || "",
      pageUrl: base + "#/photo/" + (d.photo_id || ""),
      imgUrl: d.src && d.src.indexOf("http") === 0 ? d.src : location.origin + (d.src || ""),
    };
  },

  paintCitation(fmt) {
    const view = this.view;
    this.kitFormat = fmt;
    $$("#kit-tabs [data-format]", view).forEach((b) => {
      const on = b.dataset.format === fmt;
      b.className = "flex-1 min-h-[44px] py-1.5 px-2 rounded font-label-md text-label-md transition-all " +
        (on ? "text-on-primary bg-primary-container shadow-sm" : "text-on-surface-variant hover:text-on-surface");
    });
    $("#kit-citation", view).textContent = kitCitation(fmt, this.kitFields());
  },

  async copyCitation() {
    const view = this.view;
    const label = $("#kit-copy-label", view);
    const icon = $("#kit-copy-icon", view);
    const btn = $("#kit-copy", view);
    try {
      await navigator.clipboard.writeText($("#kit-citation", view).textContent);
    } catch (e) {
      label.textContent = "Copy failed";
      return;
    }
    if (!view.isConnected) return;
    btn.classList.remove("bg-primary-container");
    btn.classList.add("bg-secondary", "text-on-secondary");
    label.textContent = "Copied to clipboard";
    icon.textContent = "check";
    setTimeout(() => {
      if (!view.isConnected) return;
      btn.classList.remove("bg-secondary", "text-on-secondary");
      btn.classList.add("bg-primary-container");
      label.textContent = "Copy credit";
      icon.textContent = "copy_all";
    }, 2200);
  },

  downloadJson() {
    const blob = new Blob([JSON.stringify(this.data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "reelworld-" + this.id + ".json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  },

  kitFlagSay(text) {
    const el = $("#kit-flag-status", this.view);
    el.textContent = text || "";
    el.classList.toggle("hidden", !text);
  },

  async sendKitFlag() {
    const view = this.view;
    const reason = $("#kit-flag-reason", view).value;
    const note = $("#kit-flag-note", view).value.trim();
    this.kitFlagSay("Sending…");
    try {
      const out = await api("/api/flag", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: this.id, reason: reason, note: note, route: location.hash || "#/" }),
      });
      this.kitFlagSay("Recorded " + (out.id || "—") + ". Thank you — a curator will review it.");
    } catch (e) {
      this.kitFlagSay("Flagging failed: " + String((e && e.message) || e));
    }
  },

  shareSay(text) {
    const el = $("#share-status", this.view);
    el.textContent = text || "";
    el.classList.toggle("hidden", !text);
  },

  async share() {
    const d = this.data;
    if (!d) return;
    if (d.collection === "personal" && (d.people_count || 0) > 0) {
      this.shareSay("Sharing stays off for this photo: people are visible in it.");
      return;
    }
    const btn = $("#btn-share", this.view);
    setBtnLoading(btn, true, "Preparing…");
    this.shareSay("");
    try {
      const blob = await buildShareCard(d);
      if (!blob) throw new Error("The card could not be drawn.");
      const name = "reelworld-" + d.photo_id + ".png";
      const file = new File([blob], name, { type: "image/png" });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        await navigator.share({ files: [file], title: "ReelWorld finding",
          text: (d.place && d.place.name) || d.caption || d.photo_id });
        this.shareSay("Shared.");
      } else {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 5000);
        this.shareSay("Card downloaded.");
      }
    } catch (e) {
      if (e && e.name === "AbortError") this.shareSay("");
      else this.shareSay("Sharing failed: " + String((e && e.message) || e));
    } finally {
      setBtnLoading(btn, false);
    }
  },

  async ask(question) {
    const view = this.view;
    const panel = $("#ask-answer", view);
    panel.classList.remove("hidden");
    panel.classList.add("flex");
    $("#ask-text", view).textContent = "Thinking…";
    $("#ask-how", view).classList.add("hidden");
    const src = $("#ask-source", view);
    src.classList.add("hidden");
    const send = $("#ask-send", view);
    send.disabled = true;
    try {
      const data = await api("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ photo_id: this.id, question, session_id: sessionId() }),
      });
      if (!view.isConnected) return;
      $("#ask-text", view).textContent = data.answer || "(no answer)";
      if (data.trace && data.trace.length) {
        renderTrace($("#ask-steps", view), data.trace);
        const ah = $("#ask-how", view);
        ah.classList.remove("hidden");
        ah.open = false;
      }
      if (data.source === "image" && data.note) {
        src.textContent = data.note;
        src.classList.remove("hidden");
      }
    } catch (e) {
      if (!view.isConnected) return;
      $("#ask-text", view).textContent = String((e && e.message) || e);
      $("#ask-how", view).classList.add("hidden");
    } finally {
      send.disabled = false;
    }
  },

  showBridgePanel(title) {
    const panel = $("#bridge-panel", this.view);
    panel.classList.remove("hidden");
    panel.classList.add("flex");
    $("#bridge-title", this.view).textContent = title;
    $("#bridge-groups", this.view).innerHTML = "";
    const msg = $("#bridge-message", this.view);
    msg.textContent = "";
    msg.classList.add("hidden");
    panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
  },

  bridgeSay(text) {
    const msg = $("#bridge-message", this.view);
    msg.textContent = text;
    msg.classList.remove("hidden");
  },

  matchCard(item) {
    const node = $("#tpl-match", this.view).content.firstElementChild.cloneNode(true);
    node.dataset.target = item.photo_id;
    const img = $("[data-slot=img]", node);
    img.src = item.src || srcOf(item);
    img.alt = item.caption || item.photo_id;
    img.addEventListener("error", () => img.setAttribute("data-broken", "true"));
    $("[data-slot=caption]", node).textContent =
      (item.caption || item.photo_id) + "  ·  " + item.photo_id;
    fillPlaceLink(node, item);
    $("[data-slot=reason]", node).textContent = item.reason_text || "match";
    $("[data-slot=score]", node).textContent =
      typeof item.score === "number" ? item.score.toFixed(2) : "";
    return node;
  },

  async bridge() {
    const btn = $("#btn-find", this.view);
    setBtnLoading(btn, true, "Finding…");
    try {
      const data = await api("/api/bridge/" + encodeURIComponent(this.id));
      if (!this.view.isConnected) return;
      const groups = data.groups || {};
      const keys = ["same_place", "another_angle", "taken_from_here", "similar_look"];
      const total = keys.reduce((n, k) => n + ((groups[k] || []).length), 0);
      const other = data.other_collection === "world" ? "the world" : "your photos";
      this.showBridgePanel(total + (total === 1 ? " match in " : " matches in ") + other);
      if (!total) {
        this.bridgeSay("No matching photos found in " + other + " for this photo.");
        return;
      }
      const box = $("#bridge-groups", this.view);
      keys.forEach((k) => {
        const items = groups[k] || [];
        if (!items.length) return;
        const h = document.createElement("div");
        h.className = "flex items-center justify-between";
        const t = document.createElement("span");
        t.className = "font-label-sm text-xs uppercase tracking-wider font-semibold text-stone-600";
        t.textContent = (data.labels && data.labels[k]) || k;
        const c = document.createElement("span");
        c.className = "font-mono text-[11px] text-stone-500";
        c.textContent = items.length + (items.length === 1 ? " photo" : " photos");
        h.append(t, c);
        const list = document.createElement("div");
        list.className = "flex flex-col gap-2 mt-2";
        items.forEach((item) => list.appendChild(this.matchCard(item)));
        const sec = document.createElement("div");
        sec.append(h, list);
        box.appendChild(sec);
      });
    } catch (e) {
      if (!this.view.isConnected) return;
      this.showBridgePanel("Matches");
      this.bridgeSay(String((e && e.message) || e));
    } finally {
      setBtnLoading(btn, false);
    }
  },

  async angle() {
    const btn = $("#btn-angle", this.view);
    setBtnLoading(btn, true, "Looking…");
    try {
      const data = await api("/api/bridge/" + encodeURIComponent(this.id));
      if (!this.view.isConnected) return;
      const items = ((data.groups || {}).another_angle) || [];
      this.showBridgePanel("Another angle");
      if (items.length) {
        const list = document.createElement("div");
        list.className = "flex flex-col gap-2";
        items.forEach((item) => list.appendChild(this.matchCard(item)));
        $("#bridge-groups", this.view).appendChild(list);
        return;
      }
      /* No true other view in the bridge: ask the agent so the reply
         carries its honest message (kind no_other_angle). */
      this.bridgeSay("Asking the search agent… (this can take 15–40 seconds)");
      const chat = await api("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId(),
          message: "Show me another angle of " + this.id,
        }),
      });
      if (!this.view.isConnected) return;
      this.bridgeSay(chat.text || "No other angle found.");
    } catch (e) {
      if (!this.view.isConnected) return;
      this.showBridgePanel("Another angle");
      this.bridgeSay(String((e && e.message) || e));
    } finally {
      setBtnLoading(btn, false);
    }
  },
};

/* ---------- add view ---------- */
const add = {
  view: null,
  file: null,
  previewUrl: null,
  jobId: null,
  photoId: null,
  pollTimer: null,

  STAGES: [
    { key: "uploaded", label: "Uploaded", sub: "Photo received and queued for reading." },
    { key: "looking", label: "Looking at the photo",
      sub: "Pass A reads what the photo shows: caption, things, signs." },
    { key: "placing", label: "Working out the place",
      sub: "Pass B weighs the evidence and names the place." },
    { key: "connecting", label: "Connecting to the world",
      sub: "Embedding, storing, and finding world matches." },
    { key: "done", label: "Done", sub: "Verdict ready on the right." },
  ],
  GROUP_ORDER: ["same_place", "another_angle", "taken_from_here", "similar_look"],
  EV_ICONS: { visible_text: "spellcheck", architecture: "apartment", context: "explore",
    owner_note: "edit_note", landmark: "location_on", place: "location_on" },

  mount(view) {
    this.view = view;
    this.resetRun();
    $$("#phase-tabs [data-phase]", view).forEach((b) =>
      b.addEventListener("click", () => this.switchPhase(Number(b.dataset.phase))));
    const dz = $("#dropzone", view);
    ["dragover", "dragenter"].forEach((ev) => dz.addEventListener(ev, (e) => {
      e.preventDefault();
      dz.classList.add("ring-2", "ring-ochre");
    }));
    ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => {
      e.preventDefault();
      dz.classList.remove("ring-2", "ring-ochre");
    }));
    dz.addEventListener("drop", (e) => {
      const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) this.selectFile(f);
    });
    $("#btn-pick", view).addEventListener("click", () => $("#file-pick", view).click());
    $("#btn-snap", view).addEventListener("click", () => $("#file-snap", view).click());
    $("#file-pick", view).addEventListener("change", (e) => {
      if (e.target.files[0]) this.selectFile(e.target.files[0]);
      e.target.value = "";
    });
    $("#file-snap", view).addEventListener("change", (e) => {
      if (e.target.files[0]) this.selectFile(e.target.files[0]);
      e.target.value = "";
    });
    $("#btn-upload", view).addEventListener("click", () => this.upload());
    $("#job-retry", view).addEventListener("click", () => this.resetRun());
    $("#btn-view-photo", view).addEventListener("click", () => {
      if (this.photoId) location.hash = "#/photo/" + this.photoId;
    });
    $("#btn-result-ask", view).addEventListener("click", () => {
      if (!this.photoId) return;
      try { sessionStorage.setItem("rw.askFocus", this.photoId); } catch (e) {}
      location.hash = "#/photo/" + this.photoId;
    });
    $("#bridge-cards", view).addEventListener("click", (e) => {
      if (placeLinkClick(e)) return;
      const c = e.target.closest("[data-target]");
      if (c) location.hash = "#/photo/" + c.dataset.target;
    });
    try {
      const pending = sessionStorage.getItem("rw.pendingNote");
      if (pending) {
        sessionStorage.removeItem("rw.pendingNote");
        $("#owner-note", view).value = pending.slice(0, 200);
      }
    } catch (e) { /* private mode */ }
    this.renderStepper(-1);
    this.switchPhase(0);
  },

  resetRun() {
    if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; }
    if (this.previewUrl) { URL.revokeObjectURL(this.previewUrl); this.previewUrl = null; }
    this.file = null;
    this.jobId = null;
    this.photoId = null;
    const view = this.view;
    if (!view) return;
    hide($("#specimen", view));
    hide($("#note-wrap", view));
    hide($("#btn-upload", view));
    setBtnLoading($("#btn-upload", view), false);
    $("#btn-upload", view).disabled = false;
    hide($("#job-error", view));
    hide($("#result-pane", view));
    $("#result-waiting", view).classList.remove("hidden");
    $("#eta-text", view).textContent = "Waiting for a photo";
    $("#eta-icon", view).textContent = "schedule";
    $("#stat-elapsed", view).textContent = "Elapsed 0s";
    $("#stat-eta", view).textContent = "ETA —";
    this.say("");
    this.renderStepper(-1);
  },

  say(text) {
    const el = $("#upload-error", this.view);
    el.textContent = text || "";
    el.classList.toggle("hidden", !text);
  },

  switchPhase(n) {
    const view = this.view;
    const left = $("#flow-left-pane", view);
    const right = $("#flow-right-pane", view);
    $$("#phase-tabs [data-phase]", view).forEach((b) => {
      const on = Number(b.dataset.phase) === n;
      b.classList.toggle("bg-primary", on);
      b.classList.toggle("text-on-primary", on);
      b.classList.toggle("shadow-sm", on);
      b.classList.toggle("font-semibold", on);
      b.classList.toggle("text-on-surface-variant", !on);
    });
    left.classList.remove("hidden", "lg:col-span-12", "lg:col-span-5");
    right.classList.remove("hidden", "lg:col-span-12", "lg:col-span-7");
    if (n === 0) { left.classList.add("lg:col-span-5"); right.classList.add("lg:col-span-7"); }
    else if (n === 3) { left.classList.add("hidden"); right.classList.add("lg:col-span-12"); }
    else { left.classList.add("lg:col-span-12"); right.classList.add("hidden"); }
  },

  selectFile(f) {
    const okType = f.type === "image/jpeg" || f.type === "image/png" ||
      /\.(jpe?g|png)$/i.test(f.name || "");
    if (!okType) { this.say("That file is not a JPEG or PNG photo."); return; }
    if (f.size > 10 * 1024 * 1024) { this.say("That photo is over the 10 MB limit."); return; }
    if (f.size === 0) { this.say("That file is empty."); return; }
    this.say("");
    this.file = f;
    if (this.previewUrl) URL.revokeObjectURL(this.previewUrl);
    this.previewUrl = URL.createObjectURL(f);
    const view = this.view;
    $("#specimen-img", view).src = this.previewUrl;
    $("#specimen-name", view).textContent = f.name || "photo";
    const mb = f.size / (1024 * 1024);
    $("#specimen-meta", view).textContent =
      (mb >= 1 ? mb.toFixed(1) + " MB" : Math.round(f.size / 1024) + " KB") +
      " • " + (f.type === "image/png" ? "PNG" : "JPEG");
    $("#specimen-ext", view).textContent = (f.type === "image/png" ? "PNG" : "JPG");
    const chips = $("#specimen-chips", view);
    chips.innerHTML = "";
    const chip = (text) => {
      const s = document.createElement("span");
      s.className = "px-2 py-0.5 rounded bg-surface-variant font-label-sm text-label-sm text-secondary font-medium";
      s.textContent = text;
      return s;
    };
    chips.append(chip(f.type === "image/png" ? "PNG" : "JPEG"), chip(mb >= 1 ? mb.toFixed(1) + " MB" : Math.round(f.size / 1024) + " KB"));
    const spec = $("#specimen", view);
    spec.classList.remove("hidden");
    spec.classList.add("flex");
    const note = $("#note-wrap", view);
    note.classList.remove("hidden");
    const up = $("#btn-upload", view);
    up.classList.remove("hidden");
    up.classList.add("inline-flex");
    this.switchPhase(1);
  },

  async upload() {
    if (!this.file) return;
    const btn = $("#btn-upload", this.view);
    setBtnLoading(btn, true, "Uploading…");
    this.say("");
    try {
      const form = new FormData();
      form.append("photo", this.file, this.file.name || "photo.jpg");
      const note = $("#owner-note", this.view).value.trim();
      if (note) form.append("note", note.slice(0, 200));
      const data = await api("/api/upload", { method: "POST", body: form });
      this.jobId = data.job_id;
      this.photoId = data.photo_id;
      const chips = $("#specimen-chips", this.view);
      const s = document.createElement("span");
      s.className = "px-2 py-0.5 rounded bg-secondary-container font-label-sm text-label-sm text-on-secondary-container font-medium";
      s.textContent = data.photo_id;
      chips.appendChild(s);
      btn.disabled = true;
      this.switchPhase(2);
      await this.pollOnce();
      if (this.view && this.view.isConnected) {
        this.pollTimer = setInterval(() => this.pollOnce(), 2000);
      }
    } catch (e) {
      setBtnLoading(btn, false);
      btn.disabled = false;
      this.say(String((e && e.message) || e));
    }
  },

  fmtDur(s) {
    if (s == null) return "—";
    if (s >= 90) return Math.round(s / 60) + " min";
    return Math.round(s) + "s";
  },

  async pollOnce() {
    try {
      const job = await api("/api/jobs/" + encodeURIComponent(this.jobId));
      if (!this.view || !this.view.isConnected) return;
      this.renderStepper(job.stage_index == null ? 0 : job.stage_index, job);
      $("#stat-elapsed", this.view).textContent = "Elapsed " + this.fmtDur(job.elapsed_seconds);
      $("#stat-eta", this.view).textContent =
        job.status === "done" ? "Finished" : "ETA " + this.fmtDur(job.eta_seconds);
      if (job.status === "done") {
        if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; }
        $("#eta-text", this.view).textContent =
          "Finished in " + this.fmtDur(job.elapsed_seconds);
        $("#eta-icon", this.view).textContent = "check_circle";
        this.renderStepper(4, job);
        this.renderResult(job.result);
        this.switchPhase(3);
      } else if (job.status === "error") {
        if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; }
        $("#eta-text", this.view).textContent = "Run failed";
        $("#eta-icon", this.view).textContent = "error";
        $("#job-error-text", this.view).textContent =
          (job.error || "The job failed.") + (job.stage ? " (during " + job.stage + ")" : "");
        const box = $("#job-error", this.view);
        box.classList.remove("hidden");
        box.classList.add("flex");
      } else {
        $("#eta-text", this.view).textContent = job.status === "queued"
          ? "Queued…"
          : "About " + this.fmtDur(job.eta_seconds) + " left";
        $("#eta-icon", this.view).textContent = "sync";
        $("#eta-icon", this.view).classList.add("animate-spin");
      }
    } catch (e) {
      if (!this.view || !this.view.isConnected) return;
      if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; }
      $("#job-error-text", this.view).textContent = String((e && e.message) || e);
      const box = $("#job-error", this.view);
      box.classList.remove("hidden");
      box.classList.add("flex");
    }
  },

  renderStepper(idx, job) {
    const box = $("#stepper", this.view);
    const line = box.firstElementChild;
    box.innerHTML = "";
    box.appendChild(line);
    const T = (n) => $("#" + n, this.view).content.firstElementChild;
    this.STAGES.forEach((st, i) => {
      let node;
      if (i < idx || (job && job.status === "done")) node = T("tpl-step-done").cloneNode(true);
      else if (i === idx) node = T("tpl-step-active").cloneNode(true);
      else {
        node = T("tpl-step-pending").cloneNode(true);
        $("[data-slot=icon]", node).textContent = i === this.STAGES.length - 1 ? "flag" : "circle";
      }
      $("[data-slot=label]", node).textContent = (i + 1) + ". " + st.label;
      let sub = st.sub;
      if (i === 0 && this.file) {
        sub = "Received " + this.file.name + " (" + Math.round(this.file.size / 1024) + " KB).";
      }
      $("[data-slot=sub]", node).textContent = sub;
      box.appendChild(node);
    });
  },

  renderResult(result) {
    const view = this.view;
    if (!result) return;
    const identify = result.identify || {};
    const bridge = result.bridge || {};
    const rphoto = result.photo || {};
    $("#result-waiting", view).classList.add("hidden");
    const pane = $("#result-pane", view);
    pane.classList.remove("hidden");
    pane.classList.add("flex");
    const primary = identify.primary;
    /* Verdict header. */
    const badge = $("#verdict-badge", view);
    if (!primary) {
      $("#verdict-text", view).textContent = "PLACE UNKNOWN";
      $("#verdict-icon", view).textContent = "radar";
      $("#confidence-index", view).textContent = "—";
      $("#primary-name", view).textContent = "Place unknown";
      $("#primary-sub", view).textContent = "no confident verdict";
      $("#primary-key", view).textContent = this.photoId || "";
    } else {
      const conf = primary.status === "confirmed";
      $("#verdict-text", view).textContent = conf ? "CONFIRMED MATCH" : "CANDIDATE MATCH";
      $("#verdict-icon", view).textContent = conf ? "verified" : "radar";
      $("#confidence-index", view).textContent =
        typeof primary.confidence === "number" ? Math.round(primary.confidence * 100) + "%" : "—";
      $("#primary-name", view).textContent = primary.name || "Place unknown";
      $("#primary-sub", view).textContent = (primary.status || "unknown") + " verdict";
      $("#primary-key", view).textContent = primary.key || "";
    }
    badge.classList.toggle("bg-secondary-container", !!primary);
    badge.classList.toggle("text-on-secondary-container", !!primary);
    badge.classList.toggle("bg-surface-variant", !primary);
    badge.classList.toggle("text-on-surface-variant", !primary);
    /* Evidence. */
    const evBox = $("#evidence-list", view);
    evBox.innerHTML = "";
    const evs = (primary && primary.evidence) || [];
    $("#evidence-count", view).textContent =
      evs.length + (evs.length === 1 ? " piece of evidence" : " pieces of evidence");
    const T = (n) => $("#" + n, view).content.firstElementChild;
    if (!evs.length) {
      const li = document.createElement("li");
      li.className = "text-on-surface-variant";
      li.textContent = "No evidence recorded.";
      evBox.appendChild(li);
    }
    evs.forEach((ev) => {
      const li = T("tpl-aresult-evidence").cloneNode(true);
      $("[data-slot=icon]", li).textContent = this.EV_ICONS[ev.kind] || "verified";
      const kind = String(ev.kind || "").replace(/_/g, " ");
      $("[data-slot=kind]", li).textContent = kind ? kind + ": " : "";
      $("[data-slot=detail]", li).textContent = ev.detail || "";
      evBox.appendChild(li);
    });
    /* Candidates. */
    const cands = identify.candidates || [];
    $("#candidates-note", view).textContent =
      cands.length + (cands.length === 1 ? " considered" : " considered");
    const cBox = $("#candidates", view);
    cBox.innerHTML = "";
    if (!cands.length) {
      const p = document.createElement("p");
      p.className = "font-body-sm text-body-sm text-on-surface-variant";
      p.textContent = "No other possibilities recorded.";
      cBox.appendChild(p);
    }
    cands.forEach((c, i) => {
      const row = T("tpl-candidate").cloneNode(true);
      $("[data-slot=num]", row).textContent = String(i + 2).padStart(2, "0");
      $("[data-slot=name]", row).textContent = c.name || "Unknown";
      $("[data-slot=key]", row).textContent = c.key ? "(" + c.key + ")" : "";
      const pct = typeof c.confidence === "number" ? Math.round(c.confidence * 100) : 0;
      $("[data-slot=bar]", row).style.width = pct + "%";
      $("[data-slot=pct]", row).textContent = pct + "%";
      cBox.appendChild(row);
    });
    /* Origin specimen. */
    $("#origin-img", view).src = rphoto.src || this.previewUrl || "";
    $("#origin-id", view).textContent = this.photoId || "";
    $("#origin-place", view).textContent = (primary && primary.name) || "Place unknown";
    $("#origin-sub", view).textContent =
      "Personal photo" + (rphoto.viewpoint ? " • " + (VP_LABEL[rphoto.viewpoint] || rphoto.viewpoint) : "");
    /* Bridge cards + pills. */
    const groups = bridge.groups || {};
    const labels = bridge.labels || {};
    const nonEmpty = this.GROUP_ORDER.filter((k) => (groups[k] || []).length);
    const total = nonEmpty.reduce((n, k) => n + groups[k].length, 0);
    $("#bridge-count", view).textContent =
      total + (total === 1 ? " world match found" : " world matches found");
    const pills = $("#bridge-pills", view);
    pills.innerHTML = "";
    const pillStyle = {
      same_place: ["border-ochre/40", "bg-primary"],
      another_angle: ["border-ochre/40", "bg-tertiary-container"],
      taken_from_here: ["border-secondary/50", "bg-secondary"],
    };
    nonEmpty.forEach((k) => {
      if (!pillStyle[k]) return;
      const p = T("tpl-bridge-pill").cloneNode(true);
      const shell = p.firstElementChild;
      shell.className += " " + pillStyle[k][0];
      $("[data-slot=dot]", p).className += " " + pillStyle[k][1];
      $("[data-slot=label]", p).textContent = labels[k] || k;
      pills.appendChild(p);
    });
    const cards = $("#bridge-cards", view);
    cards.innerHTML = "";
    const tagStyle = {
      same_place: "bg-primary text-on-primary",
      another_angle: "bg-tertiary-container text-on-tertiary",
      taken_from_here: "bg-secondary text-on-secondary",
      similar_look: "bg-surface-dim text-on-surface-variant",
    };
    nonEmpty.forEach((k) => {
      const item = groups[k][0];
      const card = T("tpl-bridge-card").cloneNode(true);
      card.dataset.target = item.photo_id;
      const img = $("[data-slot=img]", card);
      img.src = item.src || srcOf(item);
      img.alt = item.caption || item.photo_id;
      img.addEventListener("error", () => img.setAttribute("data-broken", "true"));
      const tag = $("[data-slot=tag]", card);
      tag.className += " " + (tagStyle[k] || tagStyle.similar_look);
      tag.textContent = labels[k] || k;
      $("[data-slot=title]", card).textContent = item.place || (item.caption || "").slice(0, 40);
      $("[data-slot=pid]", card).textContent = item.photo_id;
      $("[data-slot=caption]", card).textContent = item.caption || "";
      fillPlaceLink(card, item);
      $("[data-slot=credit]", card).textContent =
        (item.credit && item.credit.author) ? "By " + item.credit.author : item.photo_id;
      $("[data-slot=match]", card).textContent = typeof item.similarity === "number"
        ? Math.round(item.similarity * 100) + "% match"
        : (typeof item.score === "number" ? "score " + item.score.toFixed(2) : "");
      cards.appendChild(card);
    });
    $("#bridge-empty", view).classList.toggle("hidden", total > 0);
  },
};

/* ---------- connected view ---------- */
const connected = {
  view: null,
  tab: "overview",
  overview: null,
  index: null,
  selfPairs: [],
  ringsCache: {},
  anchorPid: null,
  selLink: null,
  explainA: null,
  explainB: null,
  explainBWorld: true,
  history: [],
  filter: "",

  mount(view) {
    this.view = view;
    this.tab = "overview";
    this.overview = null;
    this.index = null;
    this.selfPairs = [];
    this.ringsCache = {};
    this.anchorPid = null;
    this.selLink = null;
    this.explainA = null;
    this.explainB = null;
    this.history = [];
    this.filter = "";
    $("#conn-tabs", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-tab]");
      if (b) this.showTab(b.dataset.tab);
    });
    $("#connected-refresh", view).addEventListener("click", () => this.load());
    $("#connected-retry", view).addEventListener("click", () => this.load());
    $("#ring-search", view).addEventListener("input", (e) => {
      this.filter = e.target.value.trim().toLowerCase();
      this.renderCaptures();
    });
    $("#ring-captures", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-pid]");
      if (b) this.selectAnchor(b.dataset.pid, true);
    });
    $("#ov-places", view).addEventListener("click", (e) => {
      if (e.target.closest("[data-slot=placelink]")) return;
      const r = e.target.closest("[data-slot=rings]");
      if (r && r.dataset.pid) { this.openRings(r.dataset.pid); return; }
      const a = e.target.closest("[data-slot=addangle]");
      if (a) this.addAngle(a.dataset.place, a.dataset.vp);
    });
    $("#ov-self-list", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-a]");
      if (b) this.explainPair(b.dataset.a, b.dataset.b);
    });
    $("#ring-nodes", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-link]");
      if (b) this.selectLink(b.dataset.ring, Number(b.dataset.idx));
    });
    $("#ring-rows", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-link]");
      if (b) this.selectLink(b.dataset.ring, Number(b.dataset.idx));
    });
    $("#ev-close", view).addEventListener("click", () => {
      this.selLink = null;
      this.show($("#ring-evidence", view), false);
      this.paintStage();
    });
    $("#ev-explain", view).addEventListener("click", () => {
      if (this.selLink) this.explainPair(this.anchorPid, this.selLink.member.photo_id);
    });
    $("#ev-recentre", view).addEventListener("click", () => {
      if (this.selLink) this.selectAnchor(this.selLink.member.photo_id, true);
    });
    $("#ring-back", view).addEventListener("click", () => this.goBack());
    $("#ex-a-list", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-pid]");
      if (b) this.pickExplainA(b.dataset.pid);
    });
    $("#ex-b-list", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-pid]");
      if (b) this.pickExplainB(b.dataset.pid, b.dataset.world !== "0");
    });
    $("#ex-run", view).addEventListener("click", () => this.runExplain());
    $("#ex-open-rings", view).addEventListener("click", () => {
      if (this.explainA) this.openRings(this.explainA);
    });
    this.load();
  },

  show(el, on) {
    if (!el) return;
    el.hidden = !on;
    el.classList.toggle("flex", !!on);
  },

  showTab(tab) {
    this.tab = tab;
    const view = this.view;
    $$("#conn-tabs [data-tab]", view).forEach((b) => {
      const on = b.dataset.tab === tab;
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.className = "min-h-[44px] px-5 rounded-lg font-label-md text-label-md transition-all " +
        (on ? "bg-primary-container text-surface shadow-sm" : "text-on-surface-variant hover:text-on-surface");
    });
    ["overview", "rings", "explain"].forEach((t) => {
      this.show($("#conn-" + t, view), t === tab);
    });
  },

  async load() {
    const view = this.view;
    $("#connected-loading", view).hidden = false;
    this.show($("#connected-grid", view), false);
    const empty = $("#connected-empty", view);
    empty.hidden = true;
    empty.classList.add("hidden");
    empty.classList.remove("flex");
    const err = $("#connected-error", view);
    err.hidden = true;
    err.classList.add("hidden");
    err.classList.remove("flex");
    try {
      const [ov, idx, self] = await Promise.all([
        api("/api/places/overview"),
        api("/api/connected"),
        api("/api/connected/self"),
      ]);
      if (!view.isConnected) return;
      $("#connected-loading", view).hidden = true;
      this.overview = ov;
      this.index = idx;
      this.selfPairs = (self && self.pairs) || [];
      const s = idx.summary || {};
      const entries = idx.photos || [];
      const p = s.photos_connected || 0;
      const pl = s.places_connected || 0;
      $("#connected-title", view).textContent =
        p + " of your " + entries.length + (entries.length === 1 ? " photo connects" : " photos connect") +
        " to " + pl + (pl === 1 ? " place" : " places") + " in the world";
      const ovs = ov.summary || {};
      $("#connected-sub", view).textContent =
        (ovs.counterparts || 0) + " world counterparts • " + (ovs.gaps || 0) + " viewpoint gaps";
      if (!entries.length) {
        empty.hidden = false;
        empty.classList.remove("hidden");
        empty.classList.add("flex");
        return;
      }
      this.show($("#connected-grid", view), true);
      this.showTab("overview");
      this.paintOverview();
      this.renderCaptures();
      this.renderExplainA();
      const first = entries.find((e) => e.match_count > 0) || entries[0];
      this.selectAnchor(first.photo.photo_id, false);
    } catch (e) {
      if (!view.isConnected) return;
      $("#connected-loading", view).hidden = true;
      $("#connected-error-text", view).textContent = String((e && e.message) || e);
      err.hidden = false;
      err.classList.remove("hidden");
      err.classList.add("flex");
    }
  },

  /* ---------- overview tab ---------- */

  vpWords(vps) {
    return vps.map((v) => (VP_LABEL[v] || v).toLowerCase()).join(" and ");
  },

  paintOverview() {
    const view = this.view;
    const ov = this.overview || {};
    const s = ov.summary || {};
    $("#ov-captures", view).textContent = s.captures || 0;
    $("#ov-counterparts", view).textContent = s.counterparts || 0;
    $("#ov-places-n", view).textContent = s.places || 0;
    $("#ov-gaps", view).textContent = s.gaps || 0;
    const box = $("#ov-places", view);
    box.innerHTML = "";
    const T = $("#tpl-ov-place", view).content.firstElementChild;
    (ov.places || []).forEach((pl) => {
      const node = T.cloneNode(true);
      $("[data-slot=name]", node).textContent = pl.name || pl.key;
      const link = $("[data-slot=placelink]", node);
      if (pl.key && pl.key !== "unplaced") link.href = "#/place/" + pl.key;
      else link.classList.add("hidden");
      const w = pl.world || {};
      const m = pl.mine || {};
      const wb = w.by_viewpoint || {};
      const g = wb.ground_level || 0;
      const ev = wb.elevated || 0;
      const other = (w.total || 0) - g - ev;
      let counts;
      if (!w.total) counts = "The world has no photos of this place yet.";
      else {
        counts = "The world has " + w.total + " photo" + (w.total === 1 ? "" : "s") +
          " here (" + g + " ground-level, " + ev + " elevated" +
          (other > 0 ? ", " + other + " other" : "") + ").";
      }
      counts += " You have " + (m.total || 0) + ".";
      $("[data-slot=counts]", node).textContent = counts;
      const gaps = pl.gaps || [];
      let gap;
      if (!w.total) gap = "Yours may be the first photos of this place.";
      else if (gaps.length) {
        const n = gaps.reduce((t, v) => t + (wb[v] || 0), 0);
        gap = "Gap: no " + this.vpWords(gaps) + " view from you — the world has " + n + ".";
      } else gap = "No gaps — you match every world viewpoint here.";
      $("[data-slot=gap]", node).textContent = gap;
      const rb = $("[data-slot=rings]", node);
      rb.dataset.pid = (pl.mine_ids || [])[0] || "";
      if (!rb.dataset.pid) rb.classList.add("hidden");
      const ab = $("[data-slot=addangle]", node);
      if (gaps.length) {
        ab.dataset.place = pl.name || pl.key;
        ab.dataset.vp = gaps[0];
        ab.classList.remove("hidden");
        ab.classList.add("inline-flex");
      }
      box.appendChild(node);
    });
    if (!box.children.length) {
      const p = document.createElement("p");
      p.className = "font-body-md text-body-md text-on-surface-variant";
      p.textContent = "No places yet — add a photo to connect it to the world.";
      box.appendChild(p);
    }
    const sl = $("#ov-self-list", view);
    sl.innerHTML = "";
    const T2 = $("#tpl-self-pair", view).content.firstElementChild;
    this.selfPairs.slice(0, 12).forEach((pr) => {
      const node = T2.cloneNode(true);
      node.dataset.a = pr.a.photo_id;
      node.dataset.b = pr.b.photo_id;
      const ia = $("[data-slot=a-img]", node);
      ia.src = pr.a.src;
      ia.alt = pr.a.caption || pr.a.photo_id;
      const ib = $("[data-slot=b-img]", node);
      ib.src = pr.b.src;
      ib.alt = pr.b.caption || pr.b.photo_id;
      $("[data-slot=caps]", node).textContent =
        (pr.a.caption || pr.a.photo_id) + "  +  " + (pr.b.caption || pr.b.photo_id);
      const kc = $("[data-slot=kinds]", node);
      (pr.kinds || []).forEach((k) => {
        const chip = document.createElement("span");
        chip.className = "px-2 py-0.5 rounded-full bg-secondary-container text-on-secondary-fixed font-label-sm text-[11px] font-semibold";
        chip.textContent = KIND_LABEL[k] || k;
        kc.appendChild(chip);
      });
      sl.appendChild(node);
    });
    this.show($("#ov-self", view), this.selfPairs.length > 0);
  },

  openRings(pid) {
    this.showTab("rings");
    this.selectAnchor(pid, true);
  },

  addAngle(place, vp) {
    try {
      sessionStorage.setItem("rw.pendingNote",
        "Gap: " + (VP_LABEL[vp] || vp) + " view of " + place);
    } catch (e) { /* private mode */ }
    location.hash = "#/add";
  },

  /* ---------- rings tab ---------- */

  filteredCaptures() {
    const entries = (this.index && this.index.photos) || [];
    if (!this.filter) return entries;
    return entries.filter((e) => {
      const hay = ((e.photo.caption || "") + " " + e.photo.photo_id).toLowerCase();
      return hay.includes(this.filter);
    });
  },

  renderCaptures() {
    const view = this.view;
    const box = $("#ring-captures", view);
    box.innerHTML = "";
    const T = $("#tpl-capture", view).content.firstElementChild;
    const entries = this.filteredCaptures();
    $("#ring-count", view).textContent = entries.length + " captures";
    entries.forEach((entry) => {
      const node = T.cloneNode(true);
      const pid = entry.photo.photo_id;
      node.dataset.pid = pid;
      const on = pid === this.anchorPid;
      node.className += on
        ? " bg-surface-container-high shadow-md relative"
        : " bg-surface-container-low hover:bg-surface-container shadow-sm";
      if (on) {
        const rail = document.createElement("div");
        rail.className = "absolute -left-1.5 top-6 bottom-6 w-1.5 bg-on-tertiary-container rounded-full";
        node.prepend(rail);
        $("[data-slot=anchor-chip]", node).classList.remove("hidden");
      }
      const img = $("[data-slot=img]", node);
      img.src = entry.photo.src;
      img.alt = entry.photo.caption || pid;
      img.addEventListener("error", () => img.setAttribute("data-broken", "true"));
      const mc = entry.match_count || 0;
      $("[data-slot=links]", node).textContent = mc + (mc === 1 ? " world link" : " world links");
      $("[data-slot=caption]", node).textContent = entry.photo.caption || pid;
      $("[data-slot=pid]", node).textContent = pid;
      box.appendChild(node);
      this.fillCapturePlace(node, pid);
    });
    if (!box.children.length) {
      const p = document.createElement("p");
      p.className = "font-body-sm text-body-sm text-on-surface-variant";
      p.textContent = "No captures match that filter.";
      box.appendChild(p);
    }
  },

  async fillCapturePlace(node, pid) {
    const d = await photoDetail(pid);
    if (!d || !node.isConnected) return;
    $("[data-slot=place]", node).textContent = (d.place && d.place.name) || "Place unknown";
  },

  ringsData() {
    return this.ringsCache[this.anchorPid] || null;
  },

  async selectAnchor(pid, push) {
    if (push && this.anchorPid && this.history[this.history.length - 1] !== this.anchorPid) {
      this.history.push(this.anchorPid);
    }
    this.anchorPid = pid;
    this.selLink = null;
    this.renderCaptures();
    this.show($("#ring-evidence", this.view), false);
    const back = $("#ring-back", this.view);
    this.show(back, this.history.length > 0);
    $("#ring-history-count", this.view).textContent =
      this.history.length ? "(" + this.history.length + ")" : "";
    if (!this.ringsCache[pid]) {
      $("#ring-centre-label", this.view).textContent = "Loading…";
      try {
        this.ringsCache[pid] = await api("/api/rings/" + encodeURIComponent(pid));
      } catch (e) {
        if (!this.view.isConnected || this.anchorPid !== pid) return;
        $("#ring-centre-label", this.view).textContent = String((e && e.message) || e);
        return;
      }
      if (!this.view.isConnected || this.anchorPid !== pid) return;
    }
    const d = this.ringsData();
    $("#ring-centre-label", this.view).textContent =
      (d.caption || d.photo_id) + (d.place ? " — " + d.place : "");
    const ci = $("#ring-centre-img", this.view);
    ci.src = d.src;
    ci.alt = d.caption || d.photo_id;
    const counts = $("#ring-counts", this.view);
    counts.innerHTML = "";
    (d.rings || []).forEach((r) => {
      const chip = document.createElement("span");
      chip.className = "px-2 py-0.5 rounded bg-surface-container-high text-on-surface font-label-sm text-label-sm";
      chip.textContent = r.tag + " · " + r.members.length;
      chip.title = r.label;
      counts.appendChild(chip);
    });
    this.paintStage();
    this.paintRows();
  },

  goBack() {
    const prev = this.history.pop();
    if (prev) this.selectAnchor(prev, false);
  },

  paintStage() {
    const view = this.view;
    const d = this.ringsData();
    const nodes = $("#ring-nodes", view);
    nodes.innerHTML = "";
    const g = $("#ring-threads", view);
    while (g.firstChild) g.removeChild(g.firstChild);
    if (!d) return;
    const NS = "http://www.w3.org/2000/svg";
    (d.rings || []).forEach((ring, ri) => {
      (ring.members || []).forEach((m, i) => {
        const pos = ringLayout(ri, i, ring.members.length);
        const sel = this.selLink && this.selLink.ring === ring.key &&
          this.selLink.member.photo_id === m.photo_id;
        const path = document.createElementNS(NS, "path");
        const mx = (250 + pos.x) / 2;
        const my = (250 + pos.y) / 2;
        const dx = pos.x - 250;
        const dy = pos.y - 250;
        const len = Math.hypot(dx, dy) || 1;
        const cx = (mx - (dy / len) * 14).toFixed(1);
        const cy = (my + (dx / len) * 14).toFixed(1);
        path.setAttribute("d", "M 250 250 Q " + cx + " " + cy + " " + pos.x + " " + pos.y);
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", sel ? "#d5643b" : "#476556");
        path.setAttribute("stroke-width", sel ? "2.5" : "1.5");
        if (!sel && (ri === 0 || ri === 4)) path.setAttribute("stroke-dasharray", "2 3");
        g.appendChild(path);
        const b = document.createElement("button");
        b.type = "button";
        b.dataset.link = "1";
        b.dataset.ring = ring.key;
        b.dataset.idx = String(i);
        b.title = (m.caption || m.photo_id) + " — " + ring.label;
        b.className = "absolute w-14 h-14 rounded-full p-0.5 shadow-md bg-surface-container border-2 " +
          (sel ? "border-on-tertiary-container" : "border-secondary/40 hover:border-secondary");
        b.style.left = (pos.x / 5) + "%";
        b.style.top = (pos.y / 5) + "%";
        b.style.transform = "translate(-50%, -50%)";
        const img = document.createElement("img");
        img.src = m.src;
        img.alt = m.caption || m.photo_id;
        img.className = "rw-photo w-full h-full rounded-full object-cover";
        img.loading = "lazy";
        const tag = document.createElement("span");
        tag.className = "absolute -bottom-2 left-1/2 -translate-x-1/2 px-1.5 rounded bg-primary-container text-surface font-label-sm text-[10px] font-bold";
        tag.textContent = ringLabel(ri, i);
        b.append(img, tag);
        nodes.appendChild(b);
      });
    });
  },

  paintRows() {
    const view = this.view;
    const d = this.ringsData();
    const box = $("#ring-rows", view);
    box.innerHTML = "";
    if (!d) return;
    const T = $("#tpl-ring-row", view).content.firstElementChild;
    let total = 0;
    (d.rings || []).forEach((ring) => {
      if (!ring.members.length) return;
      total += ring.members.length;
      const sec = T.cloneNode(true);
      $("[data-slot=title]", sec).textContent = ring.tag + " · " + ring.label;
      $("[data-slot=count]", sec).textContent =
        ring.members.length + (ring.members.length === 1 ? " photo" : " photos");
      const rows = $("[data-slot=rows]", sec);
      ring.members.forEach((m, i) => {
        const b = document.createElement("button");
        b.type = "button";
        b.dataset.link = "1";
        b.dataset.ring = ring.key;
        b.dataset.idx = String(i);
        b.className = "w-full flex items-center gap-3 p-2 rounded-lg bg-surface-container-highest hover:bg-surface border border-parchment-border/50 text-left min-h-[44px]";
        const img = document.createElement("img");
        img.src = m.src;
        img.alt = m.caption || m.photo_id;
        img.loading = "lazy";
        img.className = "rw-photo w-12 h-12 rounded-lg object-cover flex-shrink-0 bg-surface-container-high";
        const tx = document.createElement("span");
        tx.className = "flex flex-col min-w-0 flex-1";
        const c1 = document.createElement("span");
        c1.className = "font-body-sm text-body-sm text-on-surface truncate";
        c1.textContent = m.caption || m.photo_id;
        const c2 = document.createElement("span");
        c2.className = "font-label-sm text-label-sm text-on-surface-variant truncate";
        c2.textContent = (m.place || "Place unknown") +
          (typeof m.score === "number" ? " · score " + m.score.toFixed(2) : "");
        tx.append(c1, c2);
        b.append(img, tx);
        rows.appendChild(b);
      });
      box.appendChild(sec);
    });
    if (!total) {
      const p = document.createElement("p");
      p.className = "font-body-md text-body-md text-on-surface-variant";
      p.textContent = "No links yet for this photo. Links form by place, viewpoint and look.";
      box.appendChild(p);
    }
  },

  selectLink(ringKey, idx) {
    const d = this.ringsData();
    if (!d) return;
    const ring = (d.rings || []).find((r) => r.key === ringKey);
    const member = ring && ring.members[idx];
    if (!member) return;
    this.selLink = { ring: ringKey, member: member };
    this.paintStage();
    const view = this.view;
    $("#ev-title", view).textContent =
      (d.caption || d.photo_id) + "  ↔  " + (member.caption || member.photo_id);
    $("#ev-badge", view).textContent = ring.tag + ": " + ring.label;
    const q = (n) => view.querySelector('[data-ev="' + n + '"]');
    const ai = q("a-img");
    ai.src = d.src;
    ai.alt = d.caption || d.photo_id;
    q("a-vp").textContent = VP_LABEL[d.viewpoint] || d.viewpoint || "";
    q("a-cap").textContent = (d.caption || d.photo_id) + (d.place ? " — " + d.place : "");
    q("a-link").href = "#/photo/" + d.photo_id;
    const bi = q("b-img");
    bi.src = member.src;
    bi.alt = member.caption || member.photo_id;
    q("b-vp").textContent = VP_LABEL[member.viewpoint] || member.viewpoint || "";
    q("b-cap").textContent = (member.caption || member.photo_id) +
      (member.place ? " — " + member.place : "");
    q("b-credit").textContent = member.credit && member.credit.author
      ? "Photo: " + member.credit.author +
        (member.credit.license ? " · " + member.credit.license : "")
      : (member.collection === "personal" ? "Your photo" : "World archive photo");
    q("b-link").href = "#/photo/" + member.photo_id;
    const rows = q("rows");
    rows.innerHTML = "";
    const T = $("#tpl-ev-row", view).content.firstElementChild;
    evidenceRows(member.facts || {}, VP_LABEL[d.viewpoint] || d.viewpoint,
      VP_LABEL[member.viewpoint] || member.viewpoint).forEach((r) => {
      const node = T.cloneNode(true);
      $("[data-slot=icon]", node).textContent = r.icon;
      $("[data-slot=label]", node).textContent = r.label;
      $("[data-slot=text]", node).textContent = r.text;
      rows.appendChild(node);
    });
    if (member.reason_text) {
      const node = T.cloneNode(true);
      $("[data-slot=icon]", node).textContent = "query_stats";
      $("[data-slot=label]", node).textContent = "Match detail";
      $("[data-slot=text]", node).textContent = member.reason_text;
      rows.appendChild(node);
    }
    this.show($("#ring-evidence", view), true);
    $("#ring-evidence", view).scrollIntoView({ block: "nearest", behavior: "smooth" });
  },

  /* ---------- explain tab ---------- */

  renderExplainA() {
    const view = this.view;
    const box = $("#ex-a-list", view);
    box.innerHTML = "";
    const T = $("#tpl-ex-opt", view).content.firstElementChild;
    ((this.index && this.index.photos) || []).forEach((entry) => {
      const node = T.cloneNode(true);
      node.dataset.pid = entry.photo.photo_id;
      if (entry.photo.photo_id === this.explainA) {
        node.classList.add("ring-2", "ring-on-tertiary-container");
      }
      const img = $("[data-slot=img]", node);
      img.src = entry.photo.src;
      img.alt = entry.photo.caption || entry.photo.photo_id;
      $("[data-slot=cap]", node).textContent = entry.photo.caption || entry.photo.photo_id;
      $("[data-slot=sub]", node).textContent =
        (entry.match_count || 0) + " world links";
      box.appendChild(node);
    });
  },

  async pickExplainA(pid) {
    this.explainA = pid;
    this.explainB = null;
    $("#ex-run", this.view).disabled = true;
    this.show($("#ex-result", this.view), false);
    this.renderExplainA();
    const hint = $("#ex-b-hint", this.view);
    hint.textContent = "Loading links…";
    this.show($("#ex-b-list", this.view), false);
    if (!this.ringsCache[pid]) {
      try {
        this.ringsCache[pid] = await api("/api/rings/" + encodeURIComponent(pid));
      } catch (e) {
        if (!this.view.isConnected || this.explainA !== pid) return;
        hint.textContent = String((e && e.message) || e);
        return;
      }
      if (!this.view.isConnected || this.explainA !== pid) return;
    }
    const box = $("#ex-b-list", this.view);
    box.innerHTML = "";
    const T = $("#tpl-ex-opt", this.view).content.firstElementChild;
    const mk = (m, sub, world) => {
      const node = T.cloneNode(true);
      node.dataset.pid = m.photo_id;
      node.dataset.world = world ? "1" : "0";
      const img = $("[data-slot=img]", node);
      img.src = m.src;
      img.alt = m.caption || m.photo_id;
      $("[data-slot=cap]", node).textContent = m.caption || m.photo_id;
      $("[data-slot=sub]", node).textContent = sub;
      return node;
    };
    let n = 0;
    (this.ringsCache[pid].rings || []).forEach((ring) => {
      (ring.members || []).forEach((m) => {
        box.appendChild(mk(m, ring.tag + " · " + ring.label, true));
        n++;
      });
    });
    this.selfPairs.forEach((pr) => {
      const other = pr.a.photo_id === pid ? pr.b : (pr.b.photo_id === pid ? pr.a : null);
      if (other) {
        box.appendChild(mk(other, "Your photo · " + pr.kinds.map((k) => KIND_LABEL[k] || k).join(", "), false));
        n++;
      }
    });
    if (!n) hint.textContent = "No links for this photo yet.";
    else {
      hint.textContent = "";
      this.show(box, true);
    }
  },

  pickExplainB(pid, world) {
    this.explainB = pid;
    this.explainBWorld = world;
    $$("#ex-b-list [data-pid]", this.view).forEach((b) => {
      b.classList.toggle("ring-2", b.dataset.pid === pid);
      b.classList.toggle("ring-on-tertiary-container", b.dataset.pid === pid);
    });
    $("#ex-run", this.view).disabled = false;
  },

  async explainPair(a, b) {
    this.showTab("explain");
    await this.pickExplainA(a);
    if (!this.view.isConnected || this.explainA !== a) return;
    const opt = this.view.querySelector('#ex-b-list [data-pid="' + b + '"]');
    if (!opt) return;
    this.pickExplainB(b, opt.dataset.world !== "0");
    this.runExplain();
  },

  async runExplain() {
    if (!this.explainA || !this.explainB) return;
    const view = this.view;
    const btn = $("#ex-run", view);
    btn.disabled = true;
    this.show($("#ex-result", view), true);
    $("#ex-verdict", view).textContent = "Explaining…";
    $("#ex-text", view).textContent = "Thinking…";
    $("#ex-icon", view).textContent = "hourglass_top";
    try {
      const out = await api("/api/explain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ photo_a: this.explainA, photo_b: this.explainB }),
      });
      if (!view.isConnected) return;
      this.paintExplain(out);
    } catch (e) {
      if (!view.isConnected) return;
      $("#ex-verdict", view).textContent = "Explanation failed";
      $("#ex-text", view).textContent = String((e && e.message) || e);
      $("#ex-icon", view).textContent = "error_outline";
    } finally {
      btn.disabled = false;
    }
  },

  paintExplain(out) {
    const view = this.view;
    const q = (n) => view.querySelector('[data-ex="' + n + '"]');
    $("#ex-icon", view).textContent = out.linked ? "hub" : "block";
    const kinds = (out.kinds || []).map((k) => KIND_LABEL[k] || k).join(", ");
    $("#ex-verdict", view).textContent = out.linked
      ? "Connection found: " + kinds
      : "No verifiable connection";
    $("#ex-text", view).textContent = out.text || "";
    const pa = out.photos[0];
    const pb = out.photos[1];
    const ia = q("a-img");
    ia.src = pa.src;
    ia.alt = pa.caption || pa.photo_id;
    q("a-cap").textContent = pa.caption || pa.photo_id;
    const ib = q("b-img");
    ib.src = pb.src;
    ib.alt = pb.caption || pb.photo_id;
    q("b-cap").textContent = pb.caption || pb.photo_id;
    const f = out.facts || {};
    const anchor = f.place_name && f.same_place ? f.place_name
      : (f.shared_landmarks || [])[0] || (f.shared_signs || [])[0]
      || (out.linked ? "Visual similarity" : "No shared anchor");
    q("anchor").textContent = anchor;
    q("anchor-sub").textContent = kinds || "different places and subjects";
    const cr = q("credit");
    if (!this.explainBWorld && pa.photo_id === this.explainA) {
      cr.textContent = "Both photos are yours.";
      cr.classList.remove("hidden");
    } else {
      cr.textContent = "";
      cr.classList.add("hidden");
      const worldPid = this.explainBWorld ? this.explainB : this.explainA;
      this.fillExplainCredit(worldPid);
    }
    const ev = $("#ex-evidence", view);
    ev.innerHTML = "";
    const T = $("#tpl-ev-row", view).content.firstElementChild;
    evidenceRows(f, VP_LABEL[pa.viewpoint] || pa.viewpoint,
      VP_LABEL[pb.viewpoint] || pb.viewpoint).forEach((r) => {
      const node = T.cloneNode(true);
      $("[data-slot=icon]", node).textContent = r.icon;
      $("[data-slot=label]", node).textContent = r.label;
      $("[data-slot=text]", node).textContent = r.text;
      ev.appendChild(node);
    });
    q("a-link").href = "#/photo/" + pa.photo_id;
    q("b-link").href = "#/photo/" + pb.photo_id;
    $("#ex-result", view).scrollIntoView({ block: "nearest", behavior: "smooth" });
  },

  async fillExplainCredit(pid) {
    const d = await photoDetail(pid);
    if (!d || !this.view.isConnected) return;
    const cr = this.view.querySelector('[data-ex="credit"]');
    if (d.credit && d.credit.author) {
      cr.textContent = "Photo: " + d.credit.author +
        (d.credit.license ? " · " + d.credit.license : "");
      cr.classList.remove("hidden");
    }
  },
};

/* ---------- agent trace ---------- */
const TRACE_LABELS = {
  understood: "Understood", searched: "Searched", rejected: "Skipped",
  fallback: "Fallback", reinspected: "Looked again", answered: "Answered",
  planned: "Planned", dropped: "Dropped", written: "Written",
  rewrote: "Rewrote",
};

function renderTrace(ol, trace) {
  ol.innerHTML = "";
  (trace || []).forEach((s) => {
    const li = document.createElement("li");
    li.className = "flex items-start gap-2 text-[13px] leading-relaxed";
    const tag = document.createElement("span");
    tag.className = "flex-shrink-0 mt-0.5 px-2 py-0.5 rounded bg-papyrus-200 border border-parchment-border text-espresso-700 text-[11px] font-semibold whitespace-nowrap";
    tag.textContent = TRACE_LABELS[s.step] || s.step;
    const d = document.createElement("span");
    d.className = "text-espresso-800";
    d.textContent = s.detail || "";
    li.append(tag, d);
    ol.appendChild(li);
  });
}

/* ---------- place view ---------- */
/* ---------- my photos library ---------- */
const library = {
  view: null,
  tab: "albums",
  data: null,
  drill: null,
  burstIdx: 0,
  burstTimer: null,
  queue: [],
  qPaused: false,
  qTimer: null,
  qActive: 0,
  qSeq: 0,
  mgrPid: null,

  mount(view) {
    this.view = view;
    this.tab = "albums";
    this.data = null;
    this.drill = null;
    this.queue = [];
    this.qPaused = false;
    this.qActive = 0;
    this.mgrPid = null;
    $("#lib-tabs", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-ltab]");
      if (b) this.showTab(b.dataset.ltab);
    });
    $("#lib-album-cards", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-album]");
      if (b) this.openAlbum(b.dataset.album);
    });
    $("#lib-places", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-place]");
      if (b) this.openPlaceGroup(b.dataset.place);
    });
    $("#lib-bursts", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-burst]");
      if (b) this.openBurst(b.dataset.burst);
    });
    $("#lib-back", view).addEventListener("click", () => {
      this.drill = null;
      this.paintMain();
    });
    $("#lib-detail-grid", view).addEventListener("click", (e) => {
      const t = e.target.closest("[data-pid]");
      if (!t) return;
      if (e.target.closest("[data-slot=correct]")) { this.gotoManage(t.dataset.pid); return; }
      if (e.target.closest("[data-slot=del]")) { this.gotoManage(t.dataset.pid); return; }
    });
    $("#burst-back", view).addEventListener("click", () => {
      this.stopBurst();
      this.drill = null;
      this.paintMain();
    });
    $("#burst-strip", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-frame]");
      if (b) this.burstFrame(Number(b.dataset.frame));
    });
    $("#burst-play", view).addEventListener("click", () => this.burstPlayToggle());
    $("#burst-cover", view).addEventListener("click", () => this.burstSetCover());
    $("#burst-compare", view).addEventListener("click", () => this.burstCompare());
    $("#lib-choose", view).addEventListener("click", () => $("#lib-files", view).click());
    $("#lib-files", view).addEventListener("change", (e) => {
      this.addFiles(e.target.files);
      e.target.value = "";
    });
    const dz = $("#lib-drop", view);
    dz.addEventListener("dragover", (e) => e.preventDefault());
    dz.addEventListener("drop", (e) => {
      e.preventDefault();
      if (e.dataTransfer && e.dataTransfer.files) this.addFiles(e.dataTransfer.files);
    });
    $("#lib-pause", view).addEventListener("click", () => {
      this.qPaused = !this.qPaused;
      $("#lib-pause", view).textContent = this.qPaused ? "Resume launching" : "Pause launching";
      if (!this.qPaused) this.pump();
    });
    $("#lib-clear", view).addEventListener("click", () => {
      this.queue = this.queue.filter((f) => f.status !== "done");
      this.paintQueue();
    });
    $("#lib-cancel", view).addEventListener("click", () => {
      this.queue = this.queue.filter((f) => f.status !== "queued");
      this.paintQueue();
    });
    $("#lib-empty-add", view).addEventListener("click", () => this.showTab("queue"));
    $("#lib-mgr-select", view).addEventListener("change", (e) => {
      this.mgrPid = e.target.value || null;
      this.paintManagePhoto();
    });
    $("#lib-cor-send", view).addEventListener("click", () => this.correct());
    $("#lib-del-btn", view).addEventListener("click", () => this.del());
    $("#lib-delall-btn", view).addEventListener("click", () => this.delAll());
    this.load();
  },

  destroy() {
    if (this.qTimer) { clearInterval(this.qTimer); this.qTimer = null; }
    this.stopBurst();
  },

  show(el, on) {
    if (!el) return;
    el.hidden = !on;
    el.classList.toggle("flex", !!on);
  },

  showTab(tab) {
    this.tab = tab;
    const view = this.view;
    $$("#lib-tabs [data-ltab]", view).forEach((b) => {
      const on = b.dataset.ltab === tab;
      b.className = "min-h-[44px] px-5 rounded-lg font-label-md text-label-md transition-all " +
        (on ? "bg-primary-container text-surface shadow-sm" : "text-on-surface-variant hover:text-on-surface");
    });
    this.paintMain();
  },

  paintMain() {
    const view = this.view;
    const inDrill = this.tab === "albums" && this.drill;
    ["albums", "queue", "manage"].forEach((t) => {
      const el = $("#lib-" + t, view);
      this.show(el, t === this.tab && !inDrill);
    });
    this.show($("#lib-detail", view), !!(inDrill && this.drill.kind === "album"));
    this.show($("#lib-burst", view), !!(inDrill && this.drill.kind === "burst"));
  },

  albumByKey(key) {
    return ((this.data && this.data.albums) || []).find((a) => a.key === key);
  },

  async load(quiet) {
    const view = this.view;
    if (!quiet) {
      $("#lib-loading", view).hidden = false;
      this.show($("#lib-main", view), false);
    }
    $("#lib-error", view).classList.add("hidden");
    try {
      const out = await api("/api/albums");
      if (!view.isConnected) return;
      this.data = out;
      $("#lib-loading", view).hidden = true;
      this.show($("#lib-main", view), true);
      $("#lib-sub", view).textContent =
        out.count + (out.count === 1 ? " photo" : " photos") + " in your private library.";
      this.paintAlbums();
      this.paintManagePicker();
      if (!quiet) {
        this.showTab(this.tab);
        const empty = !out.count;
        $("#lib-empty", view).classList.toggle("hidden", !empty);
      }
      if (this.drill) this.repaintDrill();
    } catch (e) {
      if (!view.isConnected) return;
      $("#lib-loading", view).hidden = true;
      const box = $("#lib-error", view);
      box.textContent = String((e && e.message) || e);
      box.classList.remove("hidden");
    }
  },

  coverFor(ids) {
    const photos = (this.data && this.data.photos) || {};
    const first = (ids || [])[0];
    return first && photos[first] ? photos[first].src : null;
  },

  paintAlbums() {
    const view = this.view;
    const box = $("#lib-album-cards", view);
    box.innerHTML = "";
    const T = $("#tpl-lib-album", view).content.firstElementChild;
    ["all", "above", "signs", "people", "look"].forEach((key) => {
      const a = this.albumByKey(key);
      if (!a) return;
      const node = T.cloneNode(true);
      node.dataset.album = key;
      const img = $("[data-slot=img]", node);
      const src = this.coverFor(a.ids);
      if (src) {
        img.src = src;
        img.alt = a.label;
      } else img.remove();
      $("[data-slot=label]", node).textContent = a.label;
      $("[data-slot=count]", node).textContent = a.count + (a.count === 1 ? " photo" : " photos");
      box.appendChild(node);
    });
    const pl = $("#lib-places", view);
    pl.innerHTML = "";
    const groups = (this.albumByKey("places") || {}).groups || [];
    groups.forEach((g) => {
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.place = g.key;
      b.className = "w-full flex items-center justify-between gap-2 p-3 rounded-xl bg-surface-container-low hover:bg-surface-container-high shadow-sm transition-colors text-left min-h-[44px]";
      const nm = document.createElement("span");
      nm.className = "font-body-md text-body-md text-on-surface truncate";
      nm.textContent = g.name || g.key;
      const ct = document.createElement("span");
      ct.className = "font-label-sm text-label-sm text-on-surface-variant flex-shrink-0";
      ct.textContent = g.ids.length + (g.ids.length === 1 ? " photo" : " photos");
      b.append(nm, ct);
      pl.appendChild(b);
    });
    this.show($("#lib-places-wrap", view), groups.length > 0);
    const bb = $("#lib-bursts", view);
    bb.innerHTML = "";
    const sets = (this.albumByKey("bursts") || {}).sets || [];
    sets.forEach((s) => {
      const node = T.cloneNode(true);
      node.dataset.burst = s.key;
      const img = $("[data-slot=img]", node);
      const photos = (this.data && this.data.photos) || {};
      const cover = photos[s.cover] || photos[s.ids[0]];
      if (cover) {
        img.src = cover.src;
        img.alt = "Burst of " + s.count;
      } else img.remove();
      $("[data-slot=label]", node).textContent = "Burst of " + s.count;
      $("[data-slot=count]", node).textContent = s.cover === s.ids[0] ? "cover: first frame" : "cover: chosen";
      bb.appendChild(node);
    });
    this.show($("#lib-bursts-wrap", view), sets.length > 0);
  },

  openAlbum(key) {
    const a = this.albumByKey(key);
    if (!a) return;
    this.drill = { kind: "album", key: key, title: a.label, ids: a.ids || [] };
    this.paintDetail();
    this.paintMain();
  },

  openPlaceGroup(key) {
    const groups = (this.albumByKey("places") || {}).groups || [];
    const g = groups.find((x) => x.key === key);
    if (!g) return;
    this.drill = { kind: "album", key: "place:" + key, title: g.name || key, ids: g.ids || [] };
    this.paintDetail();
    this.paintMain();
  },

  repaintDrill() {
    if (!this.drill) return;
    if (this.drill.kind === "burst") {
      const sets = (this.albumByKey("bursts") || {}).sets || [];
      const s = sets.find((x) => x.key === this.drill.key);
      if (!s) {
        this.drill = null;
        this.paintMain();
        return;
      }
      this.drill.ids = s.ids;
      this.paintBurst();
    } else {
      this.paintDetail();
    }
  },

  paintDetail() {
    const view = this.view;
    $("#lib-detail-title", view).textContent =
      this.drill.title + " (" + this.drill.ids.length + ")";
    const grid = $("#lib-detail-grid", view);
    grid.innerHTML = "";
    const T = $("#tpl-lib-tile", view).content.firstElementChild;
    const photos = (this.data && this.data.photos) || {};
    this.drill.ids.forEach((pid) => {
      const node = T.cloneNode(true);
      node.dataset.pid = pid;
      const m = photos[pid] || {};
      const link = $("[data-slot=link]", node);
      link.href = "#/photo/" + pid;
      const img = $("[data-slot=img]", node);
      img.src = m.src || "";
      img.alt = m.caption || pid;
      $("[data-slot=cap]", node).textContent = m.caption || pid;
      $("[data-slot=sub]", node).textContent = m.place || "Place unknown";
      grid.appendChild(node);
    });
  },

  openBurst(key) {
    const sets = (this.albumByKey("bursts") || {}).sets || [];
    const s = sets.find((x) => x.key === key);
    if (!s) return;
    this.drill = { kind: "burst", key: key, title: "Burst of " + s.count, ids: s.ids };
    this.burstIdx = 0;
    this.paintBurst();
    this.paintMain();
  },

  paintBurst() {
    const view = this.view;
    const ids = this.drill.ids;
    $("#burst-title", view).textContent = this.drill.title;
    const strip = $("#burst-strip", view);
    strip.innerHTML = "";
    const photos = (this.data && this.data.photos) || {};
    ids.forEach((pid, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.frame = String(i);
      b.className = "w-16 h-16 rounded-lg overflow-hidden flex-shrink-0 border-2 p-0";
      const img = document.createElement("img");
      img.src = (photos[pid] || {}).src || "";
      img.alt = "";
      img.loading = "lazy";
      img.className = "w-full h-full object-cover";
      b.appendChild(img);
      strip.appendChild(b);
    });
    const sa = $("#burst-a", view);
    const sb = $("#burst-b", view);
    sa.innerHTML = "";
    sb.innerHTML = "";
    ids.forEach((pid, i) => {
      [sa, sb].forEach((sel) => {
        const o = document.createElement("option");
        o.value = pid;
        o.textContent = "Frame " + (i + 1) + " (" + pid + ")";
        sel.appendChild(o);
      });
    });
    if (ids[1]) sb.value = ids[1];
    $("#burst-compare-out", view).textContent = "Pick two frames to compare them.";
    this.burstFrame(Math.min(this.burstIdx, ids.length - 1));
  },

  burstFrame(i) {
    const view = this.view;
    const ids = this.drill.ids;
    this.burstIdx = (i + ids.length) % ids.length;
    const pid = ids[this.burstIdx];
    const m = ((this.data && this.data.photos) || {})[pid] || {};
    const img = $("#burst-main", view);
    img.src = m.src || "";
    img.alt = m.caption || pid;
    const sets = (this.albumByKey("bursts") || {}).sets || [];
    const s = sets.find((x) => x.key === this.drill.key);
    const isCover = s && s.cover === pid;
    $("#burst-tag", view).textContent = "Frame " + (this.burstIdx + 1) + " of " + ids.length +
      (isCover ? " · Cover" : "");
    $("#burst-dossier", view).href = "#/photo/" + pid;
    Array.prototype.forEach.call($("#burst-strip", view).children, (t, k) => {
      t.classList.toggle("border-secondary", k === this.burstIdx);
      t.classList.toggle("border-transparent", k !== this.burstIdx);
    });
  },

  burstPlayToggle() {
    const view = this.view;
    if (this.burstTimer) {
      this.stopBurst();
      return;
    }
    const btn = $("#burst-play", view);
    btn.querySelector("span:last-child").textContent = "Pause";
    this.burstTimer = setInterval(() => {
      if (!view.isConnected) { this.stopBurst(); return; }
      this.burstFrame(this.burstIdx + 1);
    }, 500);
  },

  stopBurst() {
    if (this.burstTimer) { clearInterval(this.burstTimer); this.burstTimer = null; }
    if (this.view && this.view.isConnected) {
      const btn = $("#burst-play", this.view);
      if (btn) btn.querySelector("span:last-child").textContent = "Play frames";
    }
  },

  async burstSetCover() {
    const pid = this.drill.ids[this.burstIdx];
    try {
      await api("/api/bursts/" + encodeURIComponent(this.drill.key), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cover: pid }),
      });
      await this.load(true);
    } catch (e) {
      if (this.view.isConnected) {
        $("#burst-tag", this.view).textContent = String((e && e.message) || e);
      }
    }
  },

  async burstCompare() {
    const view = this.view;
    const out = $("#burst-compare-out", view);
    out.textContent = "Comparing…";
    try {
      const r = await api("/api/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ photo_a: $("#burst-a", view).value,
          photo_b: $("#burst-b", view).value }),
      });
      if (!view.isConnected) return;
      const n = (r.differences || []).length;
      out.textContent = (r.answer || "") + (n ? " (" + n + " differences listed.)" : "");
    } catch (e) {
      if (!view.isConnected) return;
      out.textContent = String((e && e.message) || e);
    }
  },

  /* ----- queue ----- */

  addFiles(files) {
    const view = this.view;
    Array.prototype.forEach.call(files || [], (f) => {
      const row = { seq: ++this.qSeq, file: f, name: f.name || "photo.jpg",
        size: f.size || 0, status: "queued", jobId: null, photoId: null,
        stage: "", elapsed: null, error: "" };
      if (row.size > 10 * 1024 * 1024) {
        row.status = "error";
        row.error = "Too large (" + fmtBytes(row.size) + "); 10 MB max.";
      }
      this.queue.push(row);
    });
    this.paintQueue();
    this.pump();
  },

  paintQueue() {
    const view = this.view;
    const box = $("#lib-queue-list", view);
    box.innerHTML = "";
    const T = $("#tpl-queue-row", view).content.firstElementChild;
    const counts = { queued: 0, working: 0, done: 0, error: 0 };
    this.queue.forEach((f) => {
      counts[f.status === "uploading" || f.status === "working" ? "working"
        : (counts[f.status] == null ? "queued" : f.status)]++;
      const node = T.cloneNode(true);
      $("[data-slot=name]", node).textContent = f.name + " (" + fmtBytes(f.size) + ")";
      $("[data-slot=icon]", node).textContent = f.status === "done" ? "check_circle"
        : f.status === "error" ? "error"
        : f.status === "queued" ? "hourglass_top" : "sync";
      let sub = "Queued";
      if (f.status === "uploading") sub = "Uploading…";
      else if (f.status === "working") sub = (f.stage || "Working…") +
        (f.elapsed != null ? " · " + Math.round(f.elapsed) + "s" : "");
      else if (f.status === "done") sub = "Done — " + (f.photoId || "");
      else if (f.status === "error") sub = f.error || "Failed";
      $("[data-slot=sub]", node).textContent = sub;
      const link = $("[data-slot=link]", node);
      if (f.status === "done" && f.photoId) {
        link.href = "#/photo/" + f.photoId;
        link.classList.remove("hidden");
      }
      box.appendChild(node);
    });
    const n = this.queue.length;
    $("#lib-queue-count", view).textContent = n
      ? (counts.done + " done · " + counts.working + " working · " +
        counts.queued + " queued · " + counts.error + " failed")
      : "The queue is empty.";
    if (!this.qTimer && this.queue.some((f) => f.status === "working")) {
      this.qTimer = setInterval(() => this.pollQueue(), 2000);
    }
  },

  pump() {
    if (!this.view || !this.view.isConnected) return;
    while (!this.qPaused && this.qActive < 2) {
      const next = this.queue.find((f) => f.status === "queued");
      if (!next) break;
      this.launch(next);
    }
  },

  async launch(f) {
    f.status = "uploading";
    this.qActive++;
    this.paintQueue();
    try {
      const form = new FormData();
      form.append("photo", f.file, f.name);
      const data = await api("/api/upload", { method: "POST", body: form });
      f.jobId = data.job_id;
      f.photoId = data.photo_id;
      f.status = "working";
    } catch (e) {
      f.status = "error";
      let msg = String((e && e.message) || e);
      if (msg.indexOf("demo code") !== -1) {
        msg += " Enter it in the header field.";
        this.qPaused = true;
        $("#lib-pause", this.view).textContent = "Resume launching";
      }
      f.error = msg;
      this.qActive--;
      if (this.view.isConnected) {
        this.paintQueue();
        this.pump();
        this.settleCheck();
      }
      return;
    }
    this.qActive--;
    if (this.view.isConnected) {
      this.paintQueue();
      this.pump();
    }
  },

  async pollQueue() {
    const working = this.queue.filter((f) => f.status === "working");
    if (!working.length) {
      if (this.qTimer) { clearInterval(this.qTimer); this.qTimer = null; }
      return;
    }
    for (const f of working) {
      try {
        const job = await api("/api/jobs/" + encodeURIComponent(f.jobId));
        f.stage = job.stage || job.status || "";
        f.elapsed = job.elapsed_seconds;
        if (job.status === "done") {
          f.status = "done";
          f.photoId = (job.result && job.result.photo_id) || f.photoId;
        } else if (job.status === "error") {
          f.status = "error";
          f.error = (job.error || "The job failed.") +
            (job.stage ? " (during " + job.stage + ")" : "");
        }
      } catch (e) {
        f.status = "error";
        f.error = "Lost track of the job: " + String((e && e.message) || e);
      }
    }
    if (!this.view.isConnected) return;
    this.paintQueue();
    this.settleCheck();
  },

  settleCheck() {
    if (this.queue.length && this.queue.every((f) => f.status === "done" || f.status === "error")) {
      this.load(true);
    }
  },

  /* ----- manage ----- */

  gotoManage(pid) {
    this.mgrPid = pid;
    this.showTab("manage");
    this.paintManagePicker();
    this.paintManagePhoto();
  },

  paintManagePicker() {
    const view = this.view;
    const sel = $("#lib-mgr-select", view);
    sel.innerHTML = "";
    const photos = (this.data && this.data.photos) || {};
    Object.keys(photos).forEach((pid) => {
      const o = document.createElement("option");
      o.value = pid;
      o.textContent = pid + " — " + (photos[pid].caption || "untitled");
      sel.appendChild(o);
    });
    if (!this.mgrPid || !photos[this.mgrPid]) {
      this.mgrPid = Object.keys(photos)[0] || null;
    }
    if (this.mgrPid) sel.value = this.mgrPid;
    const n = Object.keys(photos).length;
    $("#lib-delall-note", view).textContent = n
      ? "This permanently deletes all " + n + " of your photos. This cannot be undone."
      : "There is nothing to delete.";
    this.paintManagePhoto();
  },

  paintManagePhoto() {
    const view = this.view;
    if (!view) return;
    $("#lib-mgr-dossier", view).href = this.mgrPid ? "#/photo/" + this.mgrPid : "#/library";
  },

  async correct() {
    const view = this.view;
    const st = $("#lib-cor-status", view);
    if (!this.mgrPid) {
      st.textContent = "Choose a photo first.";
      return;
    }
    st.textContent = "Saving…";
    try {
      const out = await api("/api/photo/" + encodeURIComponent(this.mgrPid) + "/correct", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          caption: $("#lib-cor-cap", view).value.trim(),
          place_key: $("#lib-cor-key", view).value.trim(),
          place_name: $("#lib-cor-name", view).value.trim(),
          note: $("#lib-cor-note", view).value.trim(),
        }),
      });
      if (!view.isConnected) return;
      st.textContent = "Corrected: " + (out.corrected || []).join(", ") + "." +
        (out.reembedded ? "" : " (Search entry kept; re-embed failed.)");
      $("#lib-cor-cap", view).value = "";
      $("#lib-cor-key", view).value = "";
      $("#lib-cor-name", view).value = "";
      $("#lib-cor-note", view).value = "";
      this.load(true);
    } catch (e) {
      if (!view.isConnected) return;
      let msg = String((e && e.message) || e);
      if (msg.indexOf("demo code") !== -1) msg += " Enter it in the header field.";
      st.textContent = msg;
    }
  },

  async del() {
    const view = this.view;
    const btn = $("#lib-del-btn", view);
    const st = $("#lib-del-status", view);
    if (!this.mgrPid) {
      st.textContent = "Choose a photo first.";
      return;
    }
    if (!btn.dataset.armed) {
      btn.dataset.armed = "1";
      btn.textContent = "Click again to delete " + this.mgrPid;
      return;
    }
    btn.dataset.armed = "";
    btn.textContent = "Delete photo";
    st.textContent = "Deleting…";
    const pid = this.mgrPid;
    try {
      const out = await api("/api/photo/" + encodeURIComponent(pid), { method: "DELETE" });
      if (!view.isConnected) return;
      const d = out.deleted || {};
      const bits = [];
      if (d.db) bits.push("search entry");
      if (d.file) bits.push("photo file");
      if (d.annotation) bits.push("annotation");
      st.textContent = "Deleted " + pid + " (" + (bits.join(", ") || "nothing found") + ").";
      this.mgrPid = null;
      this.drill = null;
      this.load(true);
    } catch (e) {
      if (!view.isConnected) return;
      let msg = String((e && e.message) || e);
      if (msg.indexOf("demo code") !== -1) msg += " Enter it in the header field.";
      st.textContent = msg;
    }
  },

  async delAll() {
    const view = this.view;
    const btn = $("#lib-delall-btn", view);
    const st = $("#lib-delall-status", view);
    const n = Object.keys((this.data && this.data.photos) || {}).length;
    if (!n) {
      st.textContent = "There is nothing to delete.";
      return;
    }
    if (!btn.dataset.armed) {
      btn.dataset.armed = "1";
      btn.textContent = "Click again to delete all " + n + " photos";
      return;
    }
    btn.dataset.armed = "";
    btn.textContent = "Delete everything";
    st.textContent = "Deleting…";
    try {
      const out = await api("/api/photos/mine", { method: "DELETE" });
      if (!view.isConnected) return;
      const errs = Object.keys(out.errors || {}).length;
      st.textContent = errs
        ? ("Deleted " + out.deleted + "; " + errs + " failed.")
        : ("Deleted all " + out.deleted + " photos.");
      this.mgrPid = null;
      this.drill = null;
      this.load(true);
    } catch (e) {
      if (!view.isConnected) return;
      let msg = String((e && e.message) || e);
      if (msg.indexOf("demo code") !== -1) msg += " Enter it in the header field.";
      st.textContent = msg;
    }
  },
};

/* ---------- world browse ---------- */
const browse = {
  view: null,
  facets: null,
  filters: null,
  offset: 0,
  total: 0,
  gaps: null,
  gapsShown: false,
  qTimer: null,

  mount(view) {
    this.view = view;
    this.facets = null;
    this.filters = { q: "", place: "", theme: "", vp: "", people: "" };
    this.offset = 0;
    this.total = 0;
    this.gaps = null;
    this.gapsShown = false;
    $("#br-q", view).addEventListener("input", (e) => {
      if (this.qTimer) clearTimeout(this.qTimer);
      this.qTimer = setTimeout(() => {
        this.filters.q = e.target.value.trim();
        this.search(true);
      }, 400);
    });
    $("#br-place", view).addEventListener("change", (e) => {
      this.filters.place = e.target.value;
      this.search(true);
    });
    $("#br-themes", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-theme]");
      if (!b) return;
      this.filters.theme = b.dataset.theme;
      this.paintPills();
      this.search(true);
    });
    $("#br-vps", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-vp]");
      if (!b) return;
      this.filters.vp = b.dataset.vp;
      this.paintPills();
      this.search(true);
    });
    $("#br-people", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-people]");
      if (!b) return;
      this.filters.people = b.dataset.people;
      this.paintPills();
      this.search(true);
    });
    $("#br-reset", view).addEventListener("click", () => {
      this.filters = { q: "", place: "", theme: "", vp: "", people: "" };
      $("#br-q", view).value = "";
      $("#br-place", view).value = "";
      this.paintPills();
      this.search(true);
    });
    $("#br-more", view).addEventListener("click", () => this.search(false));
    $("#br-surprise", view).addEventListener("click", () => this.surprise());
    $("#br-gaps-toggle", view).addEventListener("click", () => this.toggleGaps());
    $("#br-gaps", view).addEventListener("click", (e) => {
      const a = e.target.closest("[data-gap-add]");
      if (a) {
        try {
          sessionStorage.setItem("rw.pendingNote",
            a.dataset.gapAdd === "first"
              ? "First photo of " + a.dataset.place
              : "Gap: " + a.dataset.gapAdd + " of " + a.dataset.place);
        } catch (err) { /* private mode */ }
        location.hash = "#/add";
      }
    });
    this.search(true);
  },

  qs(extra) {
    const f = this.filters;
    const p = new URLSearchParams();
    if (f.q) p.set("q", f.q);
    if (f.place) p.set("place_key", f.place);
    if (f.theme) p.set("theme", f.theme);
    if (f.vp) p.set("viewpoint", f.vp);
    if (f.people) p.set("people", f.people);
    Object.keys(extra || {}).forEach((k) => p.set(k, extra[k]));
    return p.toString();
  },

  async search(reset) {
    const view = this.view;
    if (reset) this.offset = 0;
    $("#br-error", view).classList.add("hidden");
    try {
      const out = await api("/api/world?" + this.qs({ limit: 24, offset: this.offset }));
      if (!view.isConnected) return;
      this.total = out.total;
      if (!this.facets) {
        this.facets = out.facets;
        this.paintFacets();
      }
      this.offset += (out.photos || []).length;
      const grid = $("#br-grid", view);
      if (reset) grid.innerHTML = "";
      const T = $("#tpl-br-card", view).content.firstElementChild;
      (out.photos || []).forEach((r) => {
        const node = T.cloneNode(true);
        node.href = "#/photo/" + r.photo_id;
        const img = $("[data-slot=img]", node);
        img.src = r.src;
        img.alt = r.caption || r.photo_id;
        $("[data-slot=cap]", node).textContent = r.caption || r.photo_id;
        $("[data-slot=meta]", node).textContent =
          (r.place || "Place unknown") + " · " + (VP_LABEL[r.viewpoint] || r.viewpoint || "");
        $("[data-slot=credit]", node).textContent = r.credit && r.credit.author
          ? "Photo: " + r.credit.author + (r.credit.license ? " · " + r.credit.license : "")
          : "";
        grid.appendChild(node);
      });
      $("#br-count", view).textContent =
        this.total + (this.total === 1 ? " photo" : " photos") + " in the world archive";
      $("#br-empty", view).classList.toggle("hidden", this.total > 0);
      $("#br-more", view).classList.toggle("hidden", this.offset >= this.total);
      const fx = out.facets || this.facets || {};
      $("#br-stats", view).textContent =
        this.total + " photos · " + ((fx.places || []).length) + " places · " +
        ((fx.themes || []).length) + " themes";
    } catch (e) {
      if (!view.isConnected) return;
      const box = $("#br-error", view);
      box.textContent = String((e && e.message) || e);
      box.classList.remove("hidden");
    }
  },

  pill(parent, key, label, active) {
    const b = document.createElement("button");
    b.type = "button";
    b.dataset[key] = label.key;
    b.className = "min-h-[44px] px-4 rounded-lg font-label-md text-label-md transition-all " +
      (active ? "bg-primary-container text-surface shadow-sm"
        : "bg-surface-container-high text-on-surface-variant hover:text-on-surface");
    b.textContent = label.text;
    parent.appendChild(b);
  },

  paintFacets() {
    const view = this.view;
    const fx = this.facets || {};
    const sel = $("#br-place", view);
    sel.innerHTML = "";
    const all = document.createElement("option");
    all.value = "";
    all.textContent = "All places";
    sel.appendChild(all);
    (fx.places || []).forEach((p) => {
      const o = document.createElement("option");
      o.value = p.key;
      o.textContent = p.name + " (" + p.count + ")";
      sel.appendChild(o);
    });
    const th = $("#br-themes", view);
    th.innerHTML = "";
    this.pill(th, "theme", { key: "", text: "All themes" }, !this.filters.theme);
    (fx.themes || []).forEach((t) => {
      this.pill(th, "theme", { key: t.key, text: t.label + " (" + t.count + ")" },
        this.filters.theme === t.key);
    });
    const vp = $("#br-vps", view);
    vp.innerHTML = "";
    this.pill(vp, "vp", { key: "", text: "Any viewpoint" }, !this.filters.vp);
    (fx.viewpoints || []).forEach((v) => {
      this.pill(vp, "vp", { key: v.key, text: (VP_LABEL[v.key] || v.key) + " (" + v.count + ")" },
        this.filters.vp === v.key);
    });
    this.paintPills();
  },

  paintPills() {
    const view = this.view;
    const on = "min-h-[44px] px-4 rounded-lg font-label-md text-label-md transition-all bg-primary-container text-surface shadow-sm";
    const off = "min-h-[44px] px-4 rounded-lg font-label-md text-label-md transition-all bg-surface-container-high text-on-surface-variant hover:text-on-surface";
    $$("#br-themes [data-theme]", view).forEach((b) => {
      b.className = b.dataset.theme === this.filters.theme ? on : off;
    });
    $$("#br-vps [data-vp]", view).forEach((b) => {
      b.className = b.dataset.vp === this.filters.vp ? on : off;
    });
    $$("#br-people [data-people]", view).forEach((b) => {
      b.className = b.dataset.people === this.filters.people ? on : off;
    });
  },

  async surprise() {
    const view = this.view;
    if (!this.total) return;
    const at = Math.floor(Math.random() * this.total);
    try {
      const out = await api("/api/world?" + this.qs({ limit: 1, offset: at }));
      if (!view.isConnected) return;
      if ((out.photos || []).length) location.hash = "#/photo/" + out.photos[0].photo_id;
    } catch (e) {
      if (!view.isConnected) return;
      const box = $("#br-error", view);
      box.textContent = String((e && e.message) || e);
      box.classList.remove("hidden");
    }
  },

  async toggleGaps() {
    const view = this.view;
    this.gapsShown = !this.gapsShown;
    const box = $("#br-gaps", view);
    $("#br-gaps-toggle", view).textContent =
      this.gapsShown ? "Hide gaps in the archive" : "Show gaps in the archive";
    box.classList.toggle("hidden", !this.gapsShown);
    box.classList.toggle("flex", this.gapsShown);
    if (!this.gapsShown || this.gaps) return;
    try {
      const out = await api("/api/gaps");
      if (!view.isConnected) return;
      this.gaps = out.gaps || [];
      box.innerHTML = "";
      if (!this.gaps.length) {
        box.textContent = "No gaps found — every registered place is covered.";
        return;
      }
      this.gaps.slice(0, 24).forEach((g) => {
        const card = document.createElement("div");
        card.className = "bg-surface-container-highest rounded-xl p-4 flex flex-col gap-2";
        const nm = document.createElement("span");
        nm.className = "font-label-lg text-label-lg text-on-surface font-bold";
        nm.textContent = g.name;
        const meta = document.createElement("span");
        meta.className = "font-label-sm text-label-sm text-on-surface-variant";
        meta.textContent = (g.type || "place") + " · " + g.count +
          (g.count === 1 ? " photo" : " photos");
        const miss = document.createElement("span");
        miss.className = "font-body-sm text-body-sm text-on-surface";
        miss.textContent = gapText(g);
        const row = document.createElement("div");
        row.className = "flex flex-wrap gap-2";
        if (g.count) {
          const pl = document.createElement("a");
          pl.href = "#/place/" + g.key;
          pl.className = "min-h-[44px] px-4 rounded-lg bg-surface-container-high hover:bg-surface-dim text-on-surface font-label-md text-label-md inline-flex items-center";
          pl.textContent = "Open place";
          row.appendChild(pl);
        }
        const add = document.createElement("button");
        add.type = "button";
        add.dataset.gapAdd = g.count ? (g.missing || []).join(", ") : "first";
        add.dataset.place = g.name;
        add.className = "min-h-[44px] px-4 rounded-lg bg-primary-container text-surface hover:bg-primary font-label-md text-label-md transition-colors";
        add.textContent = g.count ? "Add a photo to fill the gap" : "Add the first photo";
        row.append(add, miss);
        card.append(nm, meta, row);
        box.appendChild(card);
      });
    } catch (e) {
      if (!view.isConnected) return;
      box.textContent = String((e && e.message) || e);
    }
  },
};

/* ---------- place page ---------- */
const place = {
  view: null,
  key: null,
  data: null,
  coll: "world",

  mount(view, key) {
    this.view = view;
    this.key = key;
    this.data = null;
    this.coll = "world";
    $("#pl-coll", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-coll]");
      if (!b || !this.data) return;
      this.coll = b.dataset.coll;
      this.render();
    });
    const addNote = () => {
      try {
        sessionStorage.setItem("rw.pendingNote", "Photo of " + (this.data.name || this.key));
      } catch (err) { /* private mode */ }
      location.hash = "#/add";
    };
    $("#pl-add", view).addEventListener("click", addNote);
    $("#pl-empty-add", view).addEventListener("click", () => {
      try {
        sessionStorage.setItem("rw.pendingNote", "First photo of " + (this.data.name || this.key));
      } catch (err) { /* private mode */ }
      location.hash = "#/add";
    });
    this.load();
  },

  async load() {
    const view = this.view;
    $("#pl-loading", view).hidden = false;
    $("#pl-main", view).hidden = true;
    $("#pl-error", view).classList.add("hidden");
    try {
      const data = await api("/api/place/" + this.key + "?collection=both");
      if (!view.isConnected) return;
      this.data = data;
      $("#pl-loading", view).hidden = true;
      $("#pl-main", view).hidden = false;
      this.render();
    } catch (e) {
      if (!view.isConnected) return;
      $("#pl-loading", view).hidden = true;
      const box = $("#pl-error", view);
      box.textContent = String((e && e.message) || e);
      box.classList.remove("hidden");
    }
  },

  items() {
    const d = this.data;
    const out = [];
    Object.keys(d.by_viewpoint || {}).forEach((vp) => {
      (d.by_viewpoint[vp] || []).forEach((r) => {
        if (r.collection === this.coll) out.push({ vp: vp, row: r });
      });
    });
    return out;
  },

  render() {
    const view = this.view;
    const d = this.data;
    const crumbs = $("#pl-crumbs", view);
    crumbs.innerHTML = "";
    (d.hierarchy || []).forEach((h, i, arr) => {
      if (i) {
        const sep = document.createElement("span");
        sep.textContent = "/";
        crumbs.appendChild(sep);
      }
      if (i < arr.length - 1) {
        const a = document.createElement("a");
        a.href = "#/place/" + h.key;
        a.className = "hover:text-ochre hover:underline";
        a.textContent = h.name || h.key;
        crumbs.appendChild(a);
      } else {
        const s = document.createElement("span");
        s.className = "text-on-surface font-semibold";
        s.textContent = h.name || h.key;
        crumbs.appendChild(s);
      }
    });
    $("#pl-name", view).textContent = d.name || d.key;
    const mine = Object.keys(d.by_viewpoint || {}).reduce((t, vp) =>
      t + (d.by_viewpoint[vp] || []).filter((r) => r.collection === "personal").length, 0);
    const world = Object.keys(d.by_viewpoint || {}).reduce((t, vp) =>
      t + (d.by_viewpoint[vp] || []).filter((r) => r.collection === "world").length, 0);
    $$("#pl-coll [data-coll]", view).forEach((b) => {
      const on = b.dataset.coll === this.coll;
      b.className = "min-h-[44px] px-4 rounded-lg font-label-md text-label-md transition-all " +
        (on ? "bg-primary-container text-surface shadow-sm"
          : "text-on-surface-variant hover:text-on-surface");
      b.textContent = b.dataset.coll === "world" ? "World (" + world + ")" : "Mine (" + mine + ")";
    });
    const shown = this.items();
    const vps = {};
    shown.forEach((it) => {
      vps[it.vp] = vps[it.vp] || [];
      vps[it.vp].push(it.row);
    });
    const order = ["ground_level", "elevated", "aerial", "interior", "water_level", "unknown"];
    const vpsHere = order.filter((v) => vps[v]);
    $("#pl-meta", view).textContent = shown.length +
      (shown.length === 1 ? " photo" : " photos") + " · " + vpsHere.length +
      (vpsHere.length === 1 ? " viewpoint" : " viewpoints") +
      (d.type ? " · " + d.type : "");
    const secs = $("#pl-sections", view);
    secs.innerHTML = "";
    const T = $("#tpl-pl-section", view).content.firstElementChild;
    const TP = $("#tpl-pl-plate", view).content.firstElementChild;
    vpsHere.forEach((vp) => {
      const sec = T.cloneNode(true);
      $("[data-slot=title]", sec).textContent = VP_LABEL[vp] || vp;
      $("[data-slot=count]", sec).textContent = vps[vp].length +
        (vps[vp].length === 1 ? " photo" : " photos");
      const grid = $("[data-slot=grid]", sec);
      vps[vp].forEach((r) => {
        const node = TP.cloneNode(true);
        node.href = "#/photo/" + r.photo_id;
        const img = $("[data-slot=img]", node);
        img.src = r.src;
        img.alt = r.caption || r.photo_id;
        $("[data-slot=cap]", node).textContent = r.caption || r.photo_id;
        const mineTag = $("[data-slot=credit]", node);
        if (r.collection === "personal") mineTag.textContent = "Your photo";
        else mineTag.classList.add("hidden");
        grid.appendChild(node);
      });
      secs.appendChild(sec);
    });
    const sg = $("#pl-signs", view);
    sg.innerHTML = "";
    (d.signs || []).forEach((s) => {
      const p = document.createElement("p");
      p.className = "font-body-sm text-body-sm text-on-surface";
      p.textContent = "\u201c" + s.text + "\u201d — read in " + s.photos +
        (s.photos === 1 ? " photo" : " photos");
      sg.appendChild(p);
    });
    $("#pl-signs-wrap", view).classList.toggle("hidden", !(d.signs || []).length);
    const cr = $("#pl-credits", view);
    cr.innerHTML = "";
    (d.credits || []).forEach((c) => {
      const p = document.createElement("p");
      p.className = "font-body-sm text-body-sm text-on-surface-variant";
      p.textContent = "Photo: " + (c.author || "Unknown") +
        (c.license ? " · " + c.license : "");
      cr.appendChild(p);
    });
    $("#pl-credits-wrap", view).classList.toggle("hidden", !(d.credits || []).length);
    const rel = $("#pl-related", view);
    rel.innerHTML = "";
    (d.related || []).slice(0, 24).forEach((r) => {
      const a = document.createElement("a");
      a.href = "#/place/" + r.key;
      a.className = "inline-flex items-center gap-1.5 min-h-[44px] px-3 rounded-lg bg-surface-container-low hover:bg-surface-container-high text-on-surface font-label-sm text-label-sm";
      a.textContent = (r.name || r.key) + " ×" + r.photos;
      rel.appendChild(a);
    });
    $("#pl-rel-wrap", view).classList.toggle("hidden", !(d.related || []).length);
    const empty = !shown.length;
    $("#pl-empty", view).classList.toggle("hidden", !empty);
    $("#pl-empty", view).classList.toggle("flex", empty);
    if (empty) {
      $("#pl-empty-text", view).textContent = this.coll === "mine"
        ? "You have no photos of this place yet."
        : "No photos of this place yet.";
    }
  },
};

/* ---------- shared match-card place link ---------- */
function fillPlaceLink(node, item) {
  const el = $("[data-slot=place]", node);
  if (!el) return;
  if (item.place_key) {
    $("[data-slot=place-text]", el).textContent = item.place || "Place page";
    el.dataset.placeLink = item.place_key;
    el.classList.remove("hidden");
    el.classList.add("inline-flex");
  } else {
    el.classList.add("hidden");
    el.classList.remove("inline-flex");
  }
}

function placeLinkClick(e) {
  const pl = e.target.closest("[data-place-link]");
  if (!pl) return false;
  if (pl.tagName !== "A") location.hash = "#/place/" + pl.dataset.placeLink;
  return true;
}

/* ---------- story view ---------- */
/* ---------- story player (shared by studio preview and showcase) ---------- */
const player = {
  timer: null,
  st: null,

  fmt(s) {
    s = Math.max(0, Math.round(s));
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  },

  mount(root, full) {
    this.destroy();
    const chapters = (full && full.chapters) || [];
    root.innerHTML = "";
    if (!chapters.length) {
      root.textContent = "This story has no scenes.";
      return;
    }
    const reduce = !!(window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    const frame = document.createElement("div");
    frame.className = "relative w-full aspect-[9/16] rounded-xl overflow-hidden bg-black shadow-md";
    const img = document.createElement("img");
    img.className = "absolute inset-0 w-full h-full object-cover";
    img.alt = "";
    const grad = document.createElement("div");
    grad.className = "absolute inset-x-0 bottom-0 h-2/5 bg-gradient-to-t from-black/80 to-transparent pointer-events-none";
    const top = document.createElement("div");
    top.className = "absolute top-0 inset-x-0 flex items-center justify-between px-3 py-2 text-white font-label-sm text-label-sm";
    const tag = document.createElement("span");
    tag.className = "px-2 py-0.5 rounded bg-black/50";
    const time = document.createElement("span");
    time.className = "px-2 py-0.5 rounded bg-black/50 font-mono";
    top.append(tag, time);
    const bot = document.createElement("div");
    bot.className = "absolute bottom-0 inset-x-0 p-3 flex flex-col gap-1";
    const head = document.createElement("div");
    head.className = "text-white font-label-lg text-label-lg font-bold";
    const cap = document.createElement("div");
    cap.className = "text-white/90 font-body-sm text-body-sm";
    const cred = document.createElement("div");
    cred.className = "text-white/70 font-label-sm text-label-sm";
    bot.append(head, cap, cred);
    frame.append(img, grad, top, bot);
    const track = document.createElement("div");
    track.className = "h-1 rounded bg-surface-container-high overflow-hidden mt-2";
    const bar = document.createElement("div");
    bar.className = "h-full bg-secondary rounded";
    bar.style.width = "0%";
    track.appendChild(bar);
    const ctrls = document.createElement("div");
    ctrls.className = "flex items-center justify-center gap-2 mt-2";
    const mk = (icon, label) => {
      const b = document.createElement("button");
      b.type = "button";
      b.title = label;
      b.setAttribute("aria-label", label);
      b.className = "w-11 h-11 min-w-[44px] min-h-[44px] rounded-full bg-surface-container-low hover:bg-surface-container-high text-on-surface flex items-center justify-center";
      const s = document.createElement("span");
      s.className = "material-symbols-outlined text-[20px]";
      s.textContent = icon;
      b.appendChild(s);
      return b;
    };
    const prev = mk("skip_previous", "Previous scene");
    const play = mk("pause", "Play or pause");
    const next = mk("skip_next", "Next scene");
    const replay = mk("replay", "Replay");
    replay.classList.add("hidden");
    prev.addEventListener("click", () => this.jump(this.st.idx - 1));
    next.addEventListener("click", () => this.jump(this.st.idx + 1));
    play.addEventListener("click", () => this.toggle());
    replay.addEventListener("click", () => {
      replay.classList.add("hidden");
      this.jump(0);
      this.play();
    });
    ctrls.append(prev, play, next, replay);
    const strip = document.createElement("div");
    strip.className = "flex gap-2 overflow-x-auto py-1 mt-1";
    chapters.forEach((c) => {
      const t = document.createElement("button");
      t.type = "button";
      t.className = "w-12 h-16 rounded-lg overflow-hidden flex-shrink-0 border-2 border-transparent p-0";
      const ti = document.createElement("img");
      ti.src = c.src;
      ti.alt = "";
      ti.loading = "lazy";
      ti.className = "w-full h-full object-cover";
      t.appendChild(ti);
      strip.appendChild(t);
    });
    Array.prototype.forEach.call(strip.children, (t, i) => {
      t.addEventListener("click", () => this.jump(i));
    });
    root.append(frame, track, ctrls, strip);
    this.st = { root: root, chapters: chapters, idx: 0, elapsed: 0, playing: true,
      reduce: reduce, img: img, tag: tag, time: time, head: head, cap: cap,
      cred: cred, bar: bar, play: play, replay: replay, strip: strip,
      painted: -1,
      total: chapters.reduce((t, c) => t + (Number(c.seconds) || 0), 0) };
    this.paint(true);
    const self = this;
    this.timer = setInterval(() => self.tick(), 100);
  },

  destroy() {
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
    this.st = null;
  },

  sceneStart(i) {
    let t = 0;
    for (let k = 0; k < i; k++) t += Number(this.st.chapters[k].seconds) || 0;
    return t;
  },

  paint(full) {
    const st = this.st;
    if (!st) return;
    const c = st.chapters[st.idx];
    if (full || st.painted !== st.idx) {
      st.img.src = c.src;
      st.img.alt = c.caption || c.photo_id;
      st.head.textContent = c.heading || ("Scene " + (st.idx + 1));
      st.cap.textContent = c.caption || "";
      st.cred.textContent = creditText(c.credit, c.collection) || "";
      Array.prototype.forEach.call(st.strip.children, (t, i) => {
        t.classList.toggle("border-secondary", i === st.idx);
        t.classList.toggle("border-transparent", i !== st.idx);
      });
      st.painted = st.idx;
    }
    st.tag.textContent = (st.idx + 1) + "/" + st.chapters.length +
      (c.heading ? " · " + c.heading : "");
    const abs = this.sceneStart(st.idx) + st.elapsed;
    st.time.textContent = this.fmt(abs) + " / " + this.fmt(st.total);
    st.bar.style.width = (st.total ? Math.min(100, (abs / st.total) * 100) : 0) + "%";
    st.play.firstChild.textContent = st.playing ? "pause" : "play_arrow";
  },

  tick() {
    const st = this.st;
    if (!st) return;
    if (!st.root.isConnected) { this.destroy(); return; }
    if (!st.playing) return;
    st.elapsed += 0.1;
    const dur = Number(st.chapters[st.idx].seconds) || 0;
    if (st.elapsed >= dur) {
      if (st.idx + 1 >= st.chapters.length) {
        st.elapsed = dur;
        st.playing = false;
        st.replay.classList.remove("hidden");
        this.paint(false);
        return;
      }
      st.idx++;
      st.elapsed = 0;
    }
    if (!st.reduce) {
      const prog = dur ? Math.min(1, st.elapsed / dur) : 0;
      const z = st.idx % 2 ? 1.1 - 0.1 * prog : 1 + 0.1 * prog;
      st.img.style.transform = "scale(" + z.toFixed(3) + ")";
    }
    this.paint(false);
  },

  jump(i) {
    const st = this.st;
    if (!st) return;
    if (i < 0) i = 0;
    if (i >= st.chapters.length) i = st.chapters.length - 1;
    st.idx = i;
    st.elapsed = 0;
    st.replay.classList.add("hidden");
    this.paint(true);
  },

  play() {
    if (this.st) {
      this.st.playing = true;
      this.paint(false);
    }
  },

  toggle() {
    const st = this.st;
    if (!st) return;
    if (!st.playing) {
      const dur = Number(st.chapters[st.idx].seconds) || 0;
      if (st.idx >= st.chapters.length - 1 && st.elapsed >= dur) {
        st.idx = 0;
        st.elapsed = 0;
        st.replay.classList.add("hidden");
      }
      st.playing = true;
    } else st.playing = false;
    this.paint(false);
  },
};

/* ---------- stories list + create ---------- */
const stories = {
  view: null,
  tone: "postcard",
  source: "both",
  target: "short",
  making: false,
  makeTimer: null,

  mount(view) {
    this.view = view;
    this.tone = "postcard";
    this.source = "both";
    this.target = "short";
    this.making = false;
    this.paintPills();
    const pick = (id, key) => {
      $("#" + id, view).addEventListener("click", (e) => {
        const b = e.target.closest("button[data-" + key + "]");
        if (!b) return;
        this[key] = b.dataset[key];
        this.paintPills();
      });
    };
    pick("story-tones", "tone");
    pick("story-sources", "source");
    pick("story-targets", "target");
    $("#story-suggest", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-prompt]");
      if (b) $("#story-create-prompt", view).value = b.dataset.prompt;
    });
    $("#story-make", view).addEventListener("click", () => this.make());
    $("#stories-grid", view).addEventListener("click", (e) => {
      const card = e.target.closest("[data-sid]");
      if (!card) return;
      if (e.target.closest("[data-slot=del]")) { this.del(card); return; }
      if (e.target.closest("[data-slot=open]")) location.hash = "#/stories/" + card.dataset.sid;
    });
    this.load();
  },

  paintPills() {
    const view = this.view;
    const groups = [["story-tones", "tone"], ["story-sources", "source"], ["story-targets", "target"]];
    groups.forEach(([id, key]) => {
      $$("#" + id + " button", view).forEach((b) => {
        const on = b.dataset[key] === this[key];
        b.className = "min-h-[44px] px-4 rounded-lg font-label-md text-label-md transition-all " +
          (on ? "bg-primary-container text-surface shadow-sm" : "bg-surface-container-high text-on-surface-variant hover:text-on-surface");
      });
    });
  },

  say(text, isError) {
    const view = this.view;
    const busy = $("#story-making", view);
    const err = $("#story-make-error", view);
    if (isError) {
      busy.classList.add("hidden");
      err.textContent = text;
      err.classList.remove("hidden");
    } else if (text) {
      err.classList.add("hidden");
      busy.textContent = text;
      busy.classList.remove("hidden");
    } else {
      busy.classList.add("hidden");
      err.classList.add("hidden");
    }
  },

  async make() {
    if (this.making) return;
    const view = this.view;
    const prompt = $("#story-create-prompt", view).value.trim();
    if (!prompt) {
      this.say("Describe the story first — a theme, a place, a walk.", true);
      return;
    }
    this.making = true;
    this.say("Planning…");
    $("#story-make", view).disabled = true;
    const t0 = performance.now();
    this.makeTimer = setInterval(() => {
      if (view.isConnected) this.say("Planning… " + Math.round((performance.now() - t0) / 1000) + "s elapsed");
    }, 1000);
    try {
      const out = await api("/api/stories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: $("#story-create-title", view).value.trim(),
          prompt: prompt, tone: this.tone, source: this.source, target: this.target,
        }),
      });
      try {
        sessionStorage.setItem("rw.storyTrace." + out.story.id, JSON.stringify(out.trace || []));
      } catch (e) { /* private mode */ }
      location.hash = "#/stories/" + out.story.id;
    } catch (e) {
      if (!view.isConnected) return;
      this.say(String((e && e.message) || e), true);
    } finally {
      clearInterval(this.makeTimer);
      this.makeTimer = null;
      this.making = false;
      if (view.isConnected) $("#story-make", view).disabled = false;
    }
  },

  async load() {
    const view = this.view;
    const grid = $("#stories-grid", view);
    grid.innerHTML = "";
    $("#stories-empty", view).classList.add("hidden");
    $("#stories-error", view).classList.add("hidden");
    try {
      const out = await api("/api/stories");
      if (!view.isConnected) return;
      const list = out.stories || [];
      $("#stories-count", view).textContent = list.length + (list.length === 1 ? " story" : " stories");
      if (!list.length) {
        $("#stories-empty", view).classList.remove("hidden");
        return;
      }
      const T = $("#tpl-story-card", view).content.firstElementChild;
      list.forEach((s) => {
        const node = T.cloneNode(true);
        node.dataset.sid = s.id;
        const img = $("[data-slot=img]", node);
        if (s.cover_src) {
          img.src = s.cover_src;
          img.alt = s.title || s.id;
        } else img.remove();
        const st = $("[data-slot=status]", node);
        const pub = s.status === "published";
        st.textContent = pub ? "Published" : "Draft";
        st.className += pub
          ? " bg-secondary-container text-on-secondary-fixed"
          : " bg-surface-container-high text-on-surface-variant";
        $("[data-slot=title]", node).textContent = s.title || s.id;
        $("[data-slot=meta]", node).textContent =
          s.scenes + (s.scenes === 1 ? " scene" : " scenes") + " · " + s.seconds + "s · " + (s.tone || "");
        grid.appendChild(node);
      });
    } catch (e) {
      if (!view.isConnected) return;
      const box = $("#stories-error", view);
      box.textContent = String((e && e.message) || e);
      box.classList.remove("hidden");
    }
  },

  async del(card) {
    const btn = card.querySelector("[data-slot=del]");
    if (!btn.dataset.armed) {
      btn.dataset.armed = "1";
      btn.textContent = "Sure?";
      return;
    }
    try {
      await api("/api/stories/" + encodeURIComponent(card.dataset.sid), { method: "DELETE" });
      if (this.view.isConnected) this.load();
    } catch (e) {
      if (this.view.isConnected) {
        const box = $("#stories-error", this.view);
        box.textContent = String((e && e.message) || e);
        box.classList.remove("hidden");
      }
    }
  },
};

/* ---------- story studio (one draft) ---------- */
const builder = {
  view: null,
  id: null,
  full: null,
  stage: "review",
  rec: null,
  recCancel: false,

  mount(view, id) {
    this.view = view;
    this.id = id;
    this.full = null;
    this.stage = "review";
    this.rec = null;
    this.recCancel = false;
    $("#bld-tabs", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-stage]");
      if (b) this.showStage(b.dataset.stage);
    });
    $("#bld-title", view).addEventListener("input", () => this.markDirty());
    $("#bld-tones", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-tone]");
      if (!b || !this.full) return;
      this.full.story.tone = b.dataset.tone;
      this.paintTones();
      this.markDirty();
    });
    $("#bld-scenes", view).addEventListener("input", () => this.markDirty());
    $("#bld-scenes", view).addEventListener("click", (e) => this.sceneClick(e));
    $("#bld-shorter", view).addEventListener("click", () => this.makeShorter());
    $("#bld-save", view).addEventListener("click", () => this.save());
    $("#bld-delete", view).addEventListener("click", () => this.del());
    $("#bld-webm-record", view).addEventListener("click", () => this.recordWebm());
    $("#bld-webm-cancel", view).addEventListener("click", () => this.cancelExport());
    $("#bld-md", view).addEventListener("click", () => this.downloadFile("md"));
    $("#bld-json", view).addEventListener("click", () => this.downloadFile("json"));
    $("#bld-link", view).addEventListener("click", () => this.copyLink());
    $("#bld-publish", view).addEventListener("click", () => this.publish());
    this.load();
  },

  cancelExport() {
    this.recCancel = true;
    if (this.rec) {
      try { this.rec.stop(); } catch (e) { /* already stopped */ }
    }
  },

  show(el, on) {
    if (!el) return;
    el.hidden = !on;
    el.classList.toggle("flex", !!on);
  },

  showStage(stage) {
    this.stage = stage;
    const view = this.view;
    $$("#bld-tabs [data-stage]", view).forEach((b) => {
      const on = b.dataset.stage === stage;
      b.className = "min-h-[44px] px-5 rounded-lg font-label-md text-label-md transition-all " +
        (on ? "bg-primary-container text-surface shadow-sm" : "text-on-surface-variant hover:text-on-surface");
    });
    ["review", "player", "export"].forEach((t) => {
      this.show($("#stage-" + t, view), t === stage);
    });
    if (stage === "player" && this.full) player.mount($("#bld-player", view), this.full);
    else player.destroy();
  },

  async load() {
    const view = this.view;
    $("#bld-loading", view).hidden = false;
    this.show($("#bld-main", view), false);
    $("#bld-error", view).classList.add("hidden");
    try {
      const out = await api("/api/stories/" + encodeURIComponent(this.id));
      if (!view.isConnected) return;
      this.full = out;
      $("#bld-loading", view).hidden = true;
      this.show($("#bld-main", view), true);
      let trace = null;
      try {
        trace = JSON.parse(sessionStorage.getItem("rw.storyTrace." + this.id) || "null");
        sessionStorage.removeItem("rw.storyTrace." + this.id);
      } catch (e) { trace = null; }
      if (trace && trace.length) {
        const box = $("#bld-trace", view);
        box.innerHTML = "";
        renderTrace(box, trace);
        this.show(box, true);
      }
      this.paintAll();
      this.showStage("review");
    } catch (e) {
      if (!view.isConnected) return;
      $("#bld-loading", view).hidden = true;
      const box = $("#bld-error", view);
      box.textContent = String((e && e.message) || e);
      box.classList.remove("hidden");
    }
  },

  paintAll() {
    const view = this.view;
    const st = this.full.story;
    $("#bld-title", view).value = st.title || "";
    const chip = $("#bld-status", view);
    const pub = st.status === "published";
    chip.textContent = pub ? "Published" : "Draft";
    chip.className = "px-2 py-0.5 rounded font-label-sm text-label-sm font-bold uppercase tracking-wider flex-shrink-0 " +
      (pub ? "bg-secondary-container text-on-secondary-fixed" : "bg-surface-container-high text-on-surface-variant");
    this.paintTones();
    this.paintScenes();
    this.paintPublish();
    $("#bld-save", view).disabled = true;
    $("#bld-save-status", view).textContent = "";
  },

  paintTones() {
    const view = this.view;
    $$("#bld-tones [data-tone]", view).forEach((b) => {
      const on = b.dataset.tone === this.full.story.tone;
      b.className = "min-h-[44px] px-4 rounded-lg font-label-md text-label-md transition-all " +
        (on ? "bg-primary-container text-surface shadow-sm" : "bg-surface-container-high text-on-surface-variant hover:text-on-surface");
    });
  },

  paintScenes() {
    const view = this.view;
    const box = $("#bld-scenes", view);
    box.innerHTML = "";
    const T = $("#tpl-bld-scene", view).content.firstElementChild;
    (this.full.chapters || []).forEach((c, i) => {
      const node = T.cloneNode(true);
      node.dataset.pid = c.photo_id;
      const img = $("[data-slot=img]", node);
      img.src = c.src;
      img.alt = c.caption || c.photo_id;
      $("[data-slot=idx]", node).textContent = "Scene " + (i + 1);
      const pb = $("[data-slot=people]", node);
      if ((c.people || 0) > 0) {
        pb.textContent = c.people + (c.people === 1 ? " person — blocks publish" : " people — block publish");
        pb.classList.remove("hidden");
      }
      $("[data-slot=heading]", node).value = c.heading || "";
      $("[data-slot=caption]", node).value = c.caption || "";
      $("[data-slot=secs]", node).textContent = c.seconds + "s";
      const probs = (this.full.problems || {})[String(i)] || [];
      if (probs.length) {
        const w = $("[data-slot=problems]", node);
        w.textContent = "Heading warning: " + probs.join("; ");
        w.classList.remove("hidden");
      }
      box.appendChild(node);
    });
  },

  paintPublish() {
    const view = this.view;
    const st = this.full.story;
    const blocked = this.full.faces_blocked || [];
    const pub = st.status === "published";
    const fb = $("#bld-faces", view);
    if (blocked.length) {
      fb.textContent = "Cannot publish: people are visible in " + blocked.join(", ") +
        ". Faces are never published — remove those scenes first.";
      fb.classList.remove("hidden");
    } else fb.classList.add("hidden");
    $("#bld-publish", view).disabled = pub || blocked.length > 0;
    const link = $("#bld-showcase-link", view);
    link.classList.toggle("hidden", !pub);
    link.classList.toggle("inline-flex", pub);
    if (pub) $("#bld-pub-status", view).textContent = "Published to the Showcase.";
  },

  collectScenes() {
    const view = this.view;
    const out = [];
    $$("#bld-scenes [data-pid]", view).forEach((node) => {
      out.push({
        photo_id: node.dataset.pid,
        seconds: parseFloat($("[data-slot=secs]", node).textContent) || 4,
        heading: $("[data-slot=heading]", node).value.trim(),
        caption: $("[data-slot=caption]", node).value.trim(),
      });
    });
    return out;
  },

  markDirty() {
    $("#bld-save", this.view).disabled = false;
    $("#bld-save-status", this.view).textContent = "Unsaved changes.";
  },

  sceneClick(e) {
    const node = e.target.closest("[data-pid]");
    if (!node) return;
    const box = $("#bld-scenes", this.view);
    const secsEl = $("[data-slot=secs]", node);
    const secs = () => parseFloat(secsEl.textContent) || 4;
    if (e.target.closest("[data-slot=slower]")) {
      secsEl.textContent = Math.max(1, Math.round((secs() - 0.5) * 2) / 2) + "s";
      this.markDirty();
    } else if (e.target.closest("[data-slot=faster]")) {
      secsEl.textContent = Math.min(15, Math.round((secs() + 0.5) * 2) / 2) + "s";
      this.markDirty();
    } else if (e.target.closest("[data-slot=up]")) {
      if (node.previousElementSibling) {
        box.insertBefore(node, node.previousElementSibling);
        this.renumber();
        this.markDirty();
      }
    } else if (e.target.closest("[data-slot=down]")) {
      if (node.nextElementSibling) {
        box.insertBefore(node.nextElementSibling, node);
        this.renumber();
        this.markDirty();
      }
    } else if (e.target.closest("[data-slot=remove]")) {
      node.remove();
      this.renumber();
      this.markDirty();
    }
  },

  renumber() {
    $$("#bld-scenes [data-pid]", this.view).forEach((node, i) => {
      $("[data-slot=idx]", node).textContent = "Scene " + (i + 1);
    });
  },

  makeShorter() {
    const nodes = $$("#bld-scenes [data-pid]", this.view);
    const total = nodes.reduce((t, n) => t + (parseFloat($("[data-slot=secs]", n).textContent) || 0), 0);
    if (total <= 14 || !nodes.length) return;
    const f = 14 / total;
    nodes.forEach((n) => {
      const s = parseFloat($("[data-slot=secs]", n).textContent) || 4;
      $("[data-slot=secs]", n).textContent = Math.max(2, Math.round(s * f * 2) / 2) + "s";
    });
    this.markDirty();
  },

  async save() {
    const view = this.view;
    const btn = $("#bld-save", view);
    btn.disabled = true;
    $("#bld-save-status", view).textContent = "Saving…";
    try {
      const out = await api("/api/stories/" + encodeURIComponent(this.id), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: $("#bld-title", view).value.trim(),
          tone: this.full.story.tone,
          chapters: this.collectScenes(),
        }),
      });
      if (!view.isConnected) return;
      this.full = out;
      this.paintAll();
      $("#bld-save-status", view).textContent = "Saved.";
      if (this.stage === "player") player.mount($("#bld-player", view), this.full);
    } catch (e) {
      if (!view.isConnected) return;
      btn.disabled = false;
      $("#bld-save-status", view).textContent = String((e && e.message) || e);
    }
  },

  async del() {
    const btn = $("#bld-delete", this.view);
    if (!btn.dataset.armed) {
      btn.dataset.armed = "1";
      btn.textContent = "Click again to delete";
      return;
    }
    try {
      await api("/api/stories/" + encodeURIComponent(this.id), { method: "DELETE" });
      location.hash = "#/stories";
    } catch (e) {
      if (this.view.isConnected) {
        btn.dataset.armed = "";
        btn.textContent = "Delete story";
        $("#bld-save-status", this.view).textContent = String((e && e.message) || e);
      }
    }
  },

  downloadFile(kind) {
    const full = this.full;
    if (!full) return;
    const isMd = kind === "md";
    const text = isMd
      ? buildStoryMarkdown(full.story, full.chapters)
      : JSON.stringify(full, null, 2);
    const blob = new Blob([text], { type: isMd ? "text/markdown" : "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "reelworld-" + this.id + (isMd ? ".md" : ".json");
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  },

  async copyLink() {
    const url = location.origin + location.pathname + "#/stories/" + this.id;
    const st = $("#bld-link-status", this.view);
    try {
      await navigator.clipboard.writeText(url);
      st.textContent = "Copied. The link opens this studio on this device only.";
    } catch (e) {
      st.textContent = "Copy failed — the address bar holds the same link.";
    }
  },

  async publish() {
    const view = this.view;
    const st = $("#bld-pub-status", view);
    st.textContent = "Publishing…";
    try {
      const out = await api("/api/stories/" + encodeURIComponent(this.id) + "/publish", { method: "POST" });
      if (!view.isConnected) return;
      this.full = out;
      this.paintAll();
      st.textContent = "Published to the Showcase.";
    } catch (e) {
      if (!view.isConnected) return;
      const msg = String((e && e.message) || e);
      st.textContent = /demo code/i.test(msg)
        ? "Demo mode: unlock with the demo code in the header, then retry."
        : msg;
    }
  },

  loadImage(src) {
    return new Promise((res) => {
      const im = new Image();
      im.onload = () => res(im);
      im.onerror = () => res(null);
      im.src = src;
    });
  },

  drawScene(ctx, im, ch, prog, idx, W, H) {
    const z = idx % 2 ? 1.1 - 0.1 * prog : 1 + 0.1 * prog;
    const iw = im.naturalWidth || W;
    const ih = im.naturalHeight || H;
    const cover = Math.max(W / iw, H / ih) * z;
    const dw = iw * cover;
    const dh = ih * cover;
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, W, H);
    ctx.drawImage(im, (W - dw) / 2, (H - dh) / 2, dw, dh);
    const grad = ctx.createLinearGradient(0, H * 0.6, 0, H);
    grad.addColorStop(0, "rgba(0,0,0,0)");
    grad.addColorStop(1, "rgba(0,0,0,0.8)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, H * 0.6, W, H * 0.4);
    ctx.fillStyle = "#fff";
    ctx.font = '700 30px "Plus Jakarta Sans", sans-serif';
    ctx.fillText(String(ch.heading || ("Scene " + (idx + 1))).slice(0, 60), 28, H - 120);
    ctx.font = '400 22px "Plus Jakarta Sans", sans-serif';
    ctx.fillStyle = "rgba(255,255,255,0.9)";
    ctx.fillText(String(ch.caption || "").slice(0, 80), 28, H - 84);
    const ct = creditText(ch.credit, ch.collection) || "";
    if (ct) {
      ctx.font = '400 18px "Plus Jakarta Sans", sans-serif';
      ctx.fillStyle = "rgba(255,255,255,0.7)";
      ctx.fillText(ct.slice(0, 80), 28, H - 52);
    }
  },

  async recordWebm() {
    const view = this.view;
    const full = this.full;
    const chapters = (full && full.chapters) || [];
    const status = $("#bld-webm-status", view);
    const bar = $("#bld-webm-bar", view);
    const track = $("#bld-webm-track", view);
    const dl = $("#bld-webm-dl", view);
    const recBtn = $("#bld-webm-record", view);
    const cancelBtn = $("#bld-webm-cancel", view);
    const reset = () => {
      recBtn.disabled = false;
      cancelBtn.classList.add("hidden");
      track.classList.add("hidden");
    };
    dl.classList.add("hidden");
    dl.classList.remove("inline-flex");
    if (!chapters.length) {
      status.textContent = "This story has no scenes.";
      return;
    }
    const probe = document.createElement("canvas");
    if (!window.MediaRecorder || typeof probe.captureStream !== "function") {
      status.textContent = "This browser cannot record video. Try Chrome or Edge.";
      return;
    }
    const webm = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"]
      .find((m) => { try { return MediaRecorder.isTypeSupported(m); } catch (e) { return false; } });
    if (!webm) {
      status.textContent = "This browser cannot record WebM (it only offers other formats). Try Chrome or Edge.";
      return;
    }
    recBtn.disabled = true;
    cancelBtn.classList.remove("hidden");
    track.classList.remove("hidden");
    bar.style.width = "0%";
    status.textContent = "Loading photos…";
    const imgs = [];
    for (const c of chapters) {
      const im = await this.loadImage(c.src);
      if (!im) {
        status.textContent = "Could not load " + c.photo_id + "; export stopped.";
        reset();
        return;
      }
      imgs.push(im);
      if (!view.isConnected) return;
    }
    const W = 540;
    const H = 960;
    const cv = document.createElement("canvas");
    cv.width = W;
    cv.height = H;
    const ctx = cv.getContext("2d");
    const stream = cv.captureStream(30);
    const rec = new MediaRecorder(stream, { mimeType: webm, videoBitsPerSecond: 2500000 });
    this.rec = rec;
    this.recCancel = false;
    const chunks = [];
    rec.ondataavailable = (e) => {
      if (e.data && e.data.size) chunks.push(e.data);
    };
    const stopped = new Promise((res) => { rec.onstop = res; });
    rec.start(250);
    const total = chapters.reduce((t, c) => t + (Number(c.seconds) || 0), 0);
    let done = 0;
    const t0 = performance.now();
    for (let i = 0; i < chapters.length; i++) {
      const secs = Number(chapters[i].seconds) || 4;
      const frames = Math.max(1, Math.round(secs * 30));
      for (let f = 0; f < frames; f++) {
        if (this.recCancel || !view.isConnected) break;
        this.drawScene(ctx, imgs[i], chapters[i], f / frames, i, W, H);
        bar.style.width = Math.min(100, ((done + (f / frames) * secs) / total) * 100) + "%";
        status.textContent = "Recording scene " + (i + 1) + "/" + chapters.length + "…";
        await new Promise((r) => setTimeout(r, 1000 / 30));
      }
      if (this.recCancel || !view.isConnected) break;
      done += secs;
    }
    const cancelled = this.recCancel || !view.isConnected;
    try { rec.stop(); } catch (e) { /* already stopped */ }
    await stopped;
    stream.getTracks().forEach((t) => t.stop());
    this.rec = null;
    if (cancelled) {
      if (view.isConnected) status.textContent = "Export cancelled.";
      reset();
      return;
    }
    const blob = new Blob(chunks, { type: "video/webm" });
    dl.href = URL.createObjectURL(blob);
    dl.download = "reelworld-" + this.id + ".webm";
    dl.childNodes.forEach(() => {});
    dl.innerHTML = "";
    dl.appendChild(document.createTextNode(
      "Download video (" + (blob.size / 1048576).toFixed(1) + " MB WebM)"));
    dl.classList.remove("hidden");
    dl.classList.add("inline-flex");
    const took = Math.round((performance.now() - t0) / 1000);
    status.textContent = "Recorded " + total + "s of story in " + took + "s.";
    setTimeout(() => URL.revokeObjectURL(dl.href), 60000);
    reset();
  },
};

/* ---------- showcase ---------- */
const showcase = {
  view: null,
  list: [],

  mount(view) {
    this.view = view;
    this.list = [];
    $("#sc-grid", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-sid]");
      if (b) this.open(b.dataset.sid);
    });
    $("#sc-featured", view).addEventListener("click", () => {
      if (this.list.length) this.open(this.list[0].id);
    });
    $("#sc-close", view).addEventListener("click", () => this.close());
    $("#sc-modal", view).addEventListener("click", (e) => {
      if (e.target.id === "sc-modal") this.close();
    });
    document.addEventListener("keydown", this.esc);
    this.load();
  },

  esc(e) {
    if (e.key === "Escape" && showcase.view) {
      const m = $("#sc-modal", showcase.view);
      if (m && !m.classList.contains("hidden")) showcase.close();
    }
  },

  close() {
    const view = this.view;
    if (!view) return;
    player.destroy();
    const m = $("#sc-modal", view);
    m.classList.add("hidden");
    m.classList.remove("flex");
  },

  async load() {
    const view = this.view;
    const err = $("#sc-error", view);
    err.classList.add("hidden");
    try {
      const out = await api("/api/stories?status=published");
      if (!view.isConnected) return;
      this.list = out.stories || [];
      $("#sc-count", view).textContent =
        this.list.length + (this.list.length === 1 ? " story" : " stories") + " published";
      const main = $("#sc-main", view);
      main.hidden = false;
      main.classList.add("flex");
      if (!this.list.length) {
        $("#sc-empty", view).classList.remove("hidden");
        $("#sc-featured", view).classList.add("hidden");
        return;
      }
      const f = this.list[0];
      const fi = $("#sc-f-img", view);
      if (f.cover_src) {
        fi.src = f.cover_src;
        fi.alt = f.title || f.id;
      }
      $("#sc-f-title", view).textContent = f.title || f.id;
      $("#sc-f-meta", view).textContent = this.meta(f);
      const grid = $("#sc-grid", view);
      grid.innerHTML = "";
      const T = $("#tpl-sc-card", view).content.firstElementChild;
      this.list.forEach((s) => {
        const node = T.cloneNode(true);
        node.dataset.sid = s.id;
        const img = $("[data-slot=img]", node);
        if (s.cover_src) {
          img.src = s.cover_src;
          img.alt = s.title || s.id;
        } else img.remove();
        $("[data-slot=runtime]", node).textContent = s.seconds + "s";
        $("[data-slot=title]", node).textContent = s.title || s.id;
        $("[data-slot=meta]", node).textContent = this.meta(s);
        grid.appendChild(node);
      });
    } catch (e) {
      if (!view.isConnected) return;
      err.textContent = String((e && e.message) || e);
      err.classList.remove("hidden");
    }
  },

  meta(s) {
    return s.scenes + (s.scenes === 1 ? " scene" : " scenes") + " · " + s.seconds + "s" +
      (s.tone ? " · " + s.tone : "");
  },

  async open(sid) {
    const view = this.view;
    const m = $("#sc-modal", view);
    m.classList.remove("hidden");
    m.classList.add("flex");
    $("#sc-title", view).textContent = "Loading…";
    try {
      const full = await api("/api/stories/" + encodeURIComponent(sid));
      if (!view.isConnected) return;
      $("#sc-title", view).textContent = full.story.title || sid;
      player.mount($("#sc-player", view), full);
      const box = $("#sc-credits", view);
      box.innerHTML = "";
      const seen = [];
      (full.chapters || []).forEach((c) => {
        const ct = creditText(c.credit, c.collection);
        if (ct && !seen.includes(ct)) {
          seen.push(ct);
          const p = document.createElement("p");
          p.className = "font-label-sm text-label-sm text-on-surface-variant";
          p.textContent = ct;
          box.appendChild(p);
        }
      });
      $("#sc-studio", view).href = "#/stories/" + sid;
    } catch (e) {
      if (!view.isConnected) return;
      $("#sc-title", view).textContent = String((e && e.message) || e);
    }
  },
};

/* ---------- router ---------- */
let pendingSearch = null;
const viewCache = new Map();
async function loadView(name) {
  if (!viewCache.has(name)) {
    viewCache.set(name, fetch("/views/" + name + ".html").then((r) => {
      if (!r.ok) throw new Error("view " + name + " missing");
      return r.text();
    }));
  }
  return viewCache.get(name);
}

function stubView(title, phase, body) {
  const mount = $("#view");
  mount.innerHTML = "";
  const sec = document.createElement("section");
  sec.className = "w-full rounded-xl bg-surface-container-low border border-outline-variant/40 p-space-lg shadow-md flex flex-col gap-space-sm max-w-2xl";
  const tag = document.createElement("span");
  tag.className = "font-label-sm text-label-sm uppercase tracking-wider text-secondary font-semibold";
  tag.textContent = "Coming in Phase " + phase;
  const h = document.createElement("h2");
  h.className = "font-headline-lg text-headline-lg text-primary tracking-tight";
  h.textContent = title;
  const p = document.createElement("p");
  p.className = "font-body-md text-body-md text-on-surface-variant leading-relaxed";
  p.textContent = body;
  const a = document.createElement("a");
  a.className = "min-h-[44px] px-space-lg py-space-sm bg-primary text-on-primary rounded-lg font-label-lg text-label-lg inline-flex items-center gap-space-xs w-fit";
  a.href = "#/";
  a.textContent = "Back to Reel";
  sec.append(tag, h, p, a);
  mount.appendChild(sec);
}

async function showErrorView(message, retry) {
  setActiveTab("");
  try {
    const html = await loadView("404");
    $("#view").innerHTML = html;
    hide($("#err404-card", $("#view")));
    $("#err-message", $("#view")).textContent = message;
    $("#err-retry", $("#view")).addEventListener("click", () => { if (retry) retry(); });
    try {
      await api("/health");
      $("#err-api", $("#view")).textContent = "Online";
    } catch (e) { $("#err-api", $("#view")).textContent = "Unreachable"; }
  } catch (e) {
    stubView("Something went wrong", "0", message);
  }
}

async function show404() {
  setActiveTab("");
  try {
    const html = await loadView("404");
    $("#view").innerHTML = html;
    hide($("#err-card", $("#view")));
    $("#err404-path", $("#view")).textContent = location.hash || "#/";
    const n = rwConfig.counts && rwConfig.counts.world;
    $("#err404-count", $("#view")).textContent =
      "Public Cadastre" + (typeof n === "number" ? " (" + n + " photos)" : "");
  } catch (e) {
    stubView("I could not find that page.", "0",
      "The link you followed does not match any page.");
  }
}

async function route() {
  const hash = location.hash || "#/";
  clearInterval(home.loadingTimer);
  if (add.pollTimer) { clearInterval(add.pollTimer); add.pollTimer = null; }
  player.destroy();
  builder.cancelExport();
  library.destroy();
  if (hash.startsWith("#/place/")) {
    const key = decodeURIComponent(hash.slice("#/place/".length));
    setActiveTab("");
    try {
      const html = await loadView("place");
      $("#view").innerHTML = html;
      place.mount($("#view"), key);
    } catch (e) {
      showErrorView(String((e && e.message) || e), () => route());
    }
    return;
  }
  if (hash.startsWith("#/photo/")) {
    const id = decodeURIComponent(hash.slice("#/photo/".length));
    setActiveTab("");
    try {
      const html = await loadView("photo");
      $("#view").innerHTML = html;
      photo.mount($("#view"), id);
    } catch (e) {
      showErrorView(String((e && e.message) || e), () => route());
    }
    return;
  }
  if (hash.startsWith("#/add")) {
    setActiveTab("");
    try {
      const html = await loadView("add");
      $("#view").innerHTML = html;
      add.mount($("#view"));
    } catch (e) {
      showErrorView(String((e && e.message) || e), () => route());
    }
    return;
  }
  if (hash.startsWith("#/stories/")) {
    const id = decodeURIComponent(hash.slice("#/stories/".length));
    setActiveTab("stories");
    try {
      const html = await loadView("builder");
      $("#view").innerHTML = html;
      builder.mount($("#view"), id);
    } catch (e) {
      showErrorView(String((e && e.message) || e), () => route());
    }
    return;
  }
  if (hash === "#/stories") {
    setActiveTab("stories");
    try {
      const html = await loadView("stories");
      $("#view").innerHTML = html;
      stories.mount($("#view"));
    } catch (e) {
      showErrorView(String((e && e.message) || e), () => route());
    }
    return;
  }
  if (hash.startsWith("#/connected")) {
    setActiveTab("connected");
    try {
      const html = await loadView("connected");
      $("#view").innerHTML = html;
      connected.mount($("#view"));
    } catch (e) {
      showErrorView(String((e && e.message) || e), () => route());
    }
    return;
  }
  if (hash === "#/browse") {
    setActiveTab("browse");
    try {
      const html = await loadView("browse");
      $("#view").innerHTML = html;
      browse.mount($("#view"));
    } catch (e) {
      showErrorView(String((e && e.message) || e), () => route());
    }
    return;
  }
  if (hash === "#/library") {
    setActiveTab("");
    try {
      const html = await loadView("library");
      $("#view").innerHTML = html;
      library.mount($("#view"));
    } catch (e) {
      showErrorView(String((e && e.message) || e), () => route());
    }
    return;
  }
  if (hash === "#/showcase") {
    setActiveTab("stories");
    try {
      const html = await loadView("showcase");
      $("#view").innerHTML = html;
      showcase.mount($("#view"));
    } catch (e) {
      showErrorView(String((e && e.message) || e), () => route());
    }
    return;
  }
  if (hash === "#/about") {
    setActiveTab("about");
    try {
      const html = await loadView("about");
      $("#view").innerHTML = html;
      about.mount($("#view"));
    } catch (e) {
      showErrorView(String((e && e.message) || e), () => route());
    }
    return;
  }
  if (hash === "#/credits") {
    setActiveTab("");
    try {
      const html = await loadView("credits");
      $("#view").innerHTML = html;
      credits.mount($("#view"));
    } catch (e) {
      showErrorView(String((e && e.message) || e), () => route());
    }
    return;
  }
  if (hash === "#/" || hash === "") {
    setActiveTab("reel");
    try {
      const html = await loadView("home");
      $("#view").innerHTML = html;
      home.mount($("#view"));
    } catch (e) {
      showErrorView(String((e && e.message) || e), () => route());
    }
    return;
  }
  show404();
}

/* ---------- boot ---------- */
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    const landing = $("#archival-prompt-input");
    const thread = $("#thread-input");
    const input = (landing && !landing.closest("section.hidden")) ? landing : thread;
    if (input) { e.preventDefault(); input.focus(); }
  }
});
$("#demo-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("#demo-code").value.trim();
  try {
    if (v) sessionStorage.setItem("rw.demoCode", v);
    else sessionStorage.removeItem("rw.demoCode");
  } catch (err) { /* private mode */
  }
  $("#demo-code").value = "";
  paintDemo();
});
window.addEventListener("hashchange", route);
refreshShell();
route();
