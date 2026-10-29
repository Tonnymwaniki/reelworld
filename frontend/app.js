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
async function api(path, opts) {
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
async function refreshShell() {
  try {
    await api("/health");
    $("#api-status-dot").className = "w-2 h-2 rounded-full bg-sage";
    $("#api-status-text").textContent = "API: Online";
  } catch (e) {
    $("#api-status-dot").className = "w-2 h-2 rounded-full bg-ochre";
    $("#api-status-text").textContent = "API: unreachable";
    const t = $("#agent-status-text");
    if (t) t.textContent = "Semantic Agent Offline";
  }
  try {
    const mine = await api("/api/photos?collection=personal&limit=200");
    $("#personal-count").textContent = String(mine.count);
  } catch (e) { $("#personal-count").textContent = "–"; }
}

function setActiveTab(tab) {
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

const home = {
  browse: "world",
  lastRun: null, // () => void, for retry
  loadingTimer: null,
  view: null,

  mount(view) {
    this.view = view;
    $("#search-form", view).addEventListener("submit", (e) => {
      e.preventDefault();
      const q = $("#conversational-input", view).value.trim();
      if (q) this.search(q);
    });
    $("#quick-queries", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-query]");
      if (!b) return;
      const input = $("#conversational-input", view);
      input.value = b.dataset.query;
      this.search(b.dataset.query);
    });
    $$("[data-density]", view).forEach((b) => b.addEventListener("click", () => {
      this.setDensity(b.dataset.density);
    }));
    $("#error-retry", view).addEventListener("click", () => {
      if (this.lastRun) this.lastRun();
    });
    $("#results-grid", view).addEventListener("click", (e) => {
      const card = e.target.closest("article[data-photo-id]");
      if (card) location.hash = "#/photo/" + card.dataset.photoId;
    });
    if (pendingSearch) {
      const m = pendingSearch;
      pendingSearch = null;
      $("#conversational-input", view).value = m;
      this.search(m);
    } else {
      this.browse(this.browse);
    }
  },

  setDensity(d) {
    const grid = $("#results-grid", this.view);
    grid.dataset.density = d;
    $$("[data-density]", this.view).forEach((b) => {
      const on = b.dataset.density === d;
      b.className = on
        ? "p-1.5 rounded bg-papyrus-100 text-espresso-950 shadow-archival"
        : "p-1.5 rounded text-espresso-600 hover:text-espresso-950";
    });
  },

  setLoading(on) {
    const view = this.view;
    if (on) {
      hide($("#results-grid", view)); hide($("#empty-state", view)); hide($("#error-state", view));
      const box = $("#loading", view);
      show(box, "block");
      hide($("#cog-bubble", view));
      const t0 = Date.now();
      const tick = () => {
        $("#loading-elapsed", view).textContent = Math.floor((Date.now() - t0) / 1000) + "s";
      };
      tick();
      this.loadingTimer = setInterval(tick, 1000);
    } else {
      clearInterval(this.loadingTimer);
      hide($("#loading", view));
    }
  },

  fail(err, retry) {
    this.setLoading(false);
    this.lastRun = retry || null;
    $("#error-text", this.view).textContent = String((err && err.message) || err);
    hide($("#results-grid", this.view)); hide($("#empty-state", this.view));
    show($("#error-state", this.view));
  },

  /* Browse tab listing (no search yet). */
  async browse(collection) {
    this.browse = collection;
    setActiveTab(collection);
    this.lastRun = () => this.browse(collection);
    this.setLoading(true);
    try {
      const data = await api("/api/photos?collection=" + collection + "&limit=24");
      this.setLoading(false);
      hide($("#cog-bubble", this.view));
      hide($("#error-state", this.view));
      $("#results-title", this.view).textContent =
        collection === "world" ? "World Archive" : "My Photos";
      $("#results-scope", this.view).textContent =
        data.count + (data.count === 1 ? " photo" : " photos");
      if (!data.photos.length) {
        hide($("#results-grid", this.view));
        $("#empty-title", this.view).textContent =
          collection === "world" ? "The World archive is empty" : "No photos yet";
        $("#empty-text", this.view).textContent =
          collection === "world"
            ? "Nothing is listed in the World collection right now."
            : "Add your first photo to see it here, then ask where it connects.";
        show($("#empty-state", this.view));
        return;
      }
      hide($("#empty-state", this.view));
      this.renderGrid(data.photos, false);
    } catch (e) { this.fail(e, () => this.browse(collection)); }
  },

  /* Full chat turn (slow: 15-40s). */
  async search(message) {
    this.lastRun = () => this.search(message);
    this.setLoading(true);
    try {
      const data = await api("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId(), message }),
      });
      this.setLoading(false);
      this.renderChat(data);
    } catch (e) { this.fail(e, () => this.search(message)); }
  },

  /* Instant re-search after a chip is removed (no model call). */
  async research(spec) {
    this.setLoading(true);
    try {
      const data = await api("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId(), spec }),
      });
      this.setLoading(false);
      this.renderChat(data);
    } catch (e) { this.fail(e, () => this.research(spec)); }
  },

  renderChat(data) {
    hide($("#error-state", this.view));
    /* Message bubble: engine text verbatim, badge styled by kind. */
    const bubble = $("#cog-bubble", this.view);
    show(bubble);
    $("#cog-text", this.view).textContent = data.text || "";
    $("#cog-kind-text", this.view).textContent = KIND_BADGE[data.kind] || data.kind || "ok";
    const badge = $("#cog-kind", this.view);
    const warm = data.kind && data.kind !== "ok" && data.kind !== "question_answer";
    badge.className = warm
      ? "inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold bg-ochre-soft text-ochre-clay border border-ochre/25"
      : "inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold bg-sage-light text-sage-900 border border-sage-border";
    this.renderChips(data.spec || {});
    /* Results. */
    const rows = data.results || [];
    if (!rows.length) {
      hide($("#results-grid", this.view)); hide($("#empty-state", this.view));
      $("#results-title", this.view).textContent = "No matches";
      $("#results-scope", this.view).textContent = "See the message above";
      return;
    }
    hide($("#empty-state", this.view));
    $("#results-title", this.view).textContent =
      rows.length + (rows.length === 1 ? " Archive Match" : " Archive Matches");
    const scope = (data.spec && data.spec.collection) || "world";
    $("#results-scope", this.view).textContent =
      scope === "both" ? "World + your photos" : scope === "personal" ? "Your photos" : "World archive";
    const mixed = rows.some((r) => r.collection === "personal") &&
                  rows.some((r) => r.collection === "world");
    this.renderGrid(rows, true, mixed ? scope : null);
  },

  /* Spec -> removable chips; removing one re-searches without that filter. */
  renderChips(spec) {
    const box = $("#chips", this.view);
    $$(":scope > .rw-chip", box).forEach((c) => c.remove());
    const tpl = $("#chip-template");
    const chips = [];
    (spec.viewpoints || []).forEach((v) => chips.push({
      icon: VP_ICON[v] || "sell", label: VP_LABEL[v] || v,
      drop: (s) => ({ ...s, viewpoints: (s.viewpoints || []).filter((x) => x !== v) }),
    }));
    if (spec.max_people === 0) chips.push({
      icon: "person_off", label: "No people", drop: (s) => ({ ...s, max_people: null }),
    });
    else if (typeof spec.max_people === "number") chips.push({
      icon: "group", label: "At most " + spec.max_people,
      drop: (s) => ({ ...s, max_people: null }),
    });
    (spec.must_include || []).forEach((w) => chips.push({
      icon: "check_circle", label: "Shows “" + w + "”",
      drop: (s) => ({ ...s, must_include: (s.must_include || []).filter((x) => x !== w) }),
    }));
    (spec.avoid_terms || []).forEach((w) => chips.push({
      icon: "block", label: "No “" + w + "”",
      drop: (s) => ({ ...s, avoid_terms: (s.avoid_terms || []).filter((x) => x !== w) }),
    }));
    if (spec.collection === "personal") chips.push({
      icon: "photo_library", label: "My photos only",
      drop: (s) => ({ ...s, collection: "both" }),
    });
    chips.forEach((c) => {
      const node = tpl.content.firstElementChild.cloneNode(true);
      node.classList.add("rw-chip");
      $("[data-slot=icon]", node).textContent = c.icon;
      $("[data-slot=label]", node).textContent = c.label;
      $("[data-slot=x]", node).setAttribute("aria-label", "Remove filter " + c.label);
      $("[data-slot=x]", node).addEventListener("click", () => this.research(c.drop({ ...spec })));
      box.appendChild(node);
    });
    $("#chips-label", this.view).style.display = chips.length ? "" : "none";
  },

  groupHeader(text) {
    const h = document.createElement("div");
    h.className = "col-span-full flex items-center gap-3 pt-2";
    const line = "h-px flex-1 bg-parchment-border";
    h.innerHTML = "";
    const l1 = document.createElement("span"); l1.className = line;
    const t = document.createElement("span");
    t.className = "text-xs font-bold uppercase tracking-wider text-espresso-600";
    t.textContent = text;
    const l2 = document.createElement("span"); l2.className = line;
    h.append(l1, t, l2);
    return h;
  },

  renderGrid(rows, withReasons, grouped) {
    const grid = $("#results-grid", this.view);
    grid.innerHTML = "";
    const tpl = $("#card-template");
    let i = 0;
    const addRow = (row) => {
      grid.appendChild(this.card(tpl, row, withReasons, i));
      i += 1;
    };
    if (grouped) {
      const mine = rows.filter((r) => r.collection === "personal");
      const world = rows.filter((r) => r.collection !== "personal");
      if (mine.length) {
        grid.appendChild(this.groupHeader("From you"));
        mine.forEach(addRow);
      }
      if (world.length) {
        grid.appendChild(this.groupHeader("From the world"));
        world.forEach(addRow);
      }
    } else {
      rows.forEach(addRow);
    }
    show(grid, "grid");
  },

  card(tpl, row, withReasons, i) {
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.dataset.photoId = row.photo_id;
    const thumb = $("[data-slot=img]", node).parentElement;
    thumb.classList.add(ASPECTS[i % ASPECTS.length]);
    const img = $("[data-slot=img]", node);
    img.src = srcOf(row);
    img.alt = row.caption || row.photo_id;
    img.addEventListener("error", () => img.setAttribute("data-broken", "true"));
    if (withReasons && typeof row.similarity === "number") {
      const pct = $("[data-slot=pct]", node);
      pct.textContent = Math.round(row.similarity * 100) + "%";
      pct.classList.remove("hidden");
      pct.classList.add("inline-flex");
    }
    const vp = row.viewpoint;
    if (vp && VP_LABEL[vp]) {
      const chip = $("[data-slot=vp]", node);
      $("[data-slot=vp-icon]", chip).textContent = VP_ICON[vp];
      $("[data-slot=vp-text]", chip).textContent = VP_LABEL[vp];
      chip.classList.remove("hidden");
      chip.classList.add("inline-flex");
    }
    $("[data-slot=place]", node).textContent = row.place_name || row.place || "Place unknown";
    $("[data-slot=pid]", node).textContent = row.photo_id;
    $("[data-slot=caption]", node).textContent = row.caption || row.photo_id;
    if (withReasons && row.reasons && row.reasons.length) {
      const m = $("[data-slot=matched]", node);
      $("[data-slot=matched-text]", m).textContent = row.reasons.join(" · ");
      m.classList.remove("hidden");
      m.classList.add("flex");
    }
    const credit = $("[data-slot=credit]", node);
    if (row.collection === "world" && row.credit) {
      credit.appendChild(creditLine(row.credit));
    } else if (row.collection === "world") {
      credit.textContent = "World archive photo";
      this.fillCardDetail(node, row.photo_id);
    } else {
      credit.textContent = "From your photos";
    }
    if (!withReasons || !row.credit) this.fillCardDetail(node, row.photo_id, !withReasons);
    return node;
  },

  /* One cached /api/photo call per card fills the status badge and, for
     world browse rows, the credit line. Everything shown is real data. */
  async fillCardDetail(node, photoId, needCredit) {
    const d = await photoDetail(photoId);
    if (!d || !node.isConnected) return;
    const st = d.place && d.place.status;
    if (st === "confirmed" || st === "candidate") {
      const badge = $("[data-slot=status]", node);
      const dot = $("[data-slot=status-dot]", node);
      if (st === "confirmed") {
        badge.classList.add("text-emerald-300", "border-sage-600/40");
        dot.classList.add("bg-sage");
      } else {
        badge.classList.add("text-ochre-warm", "border-ochre/30");
        dot.classList.add("bg-ochre-warm");
      }
      $("[data-slot=status-text]", badge).textContent =
        st === "confirmed" ? "Confirmed" : "Candidate";
      badge.classList.remove("hidden");
      badge.classList.add("inline-flex");
    }
    if (needCredit && d.collection === "world" && d.credit) {
      const credit = $("[data-slot=credit]", node);
      credit.innerHTML = "";
      credit.appendChild(creditLine(d.credit));
    }
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
    $("#bridge-close", view).addEventListener("click", () => hide($("#bridge-panel", view)));
    $("#bridge-groups", view).addEventListener("click", (e) => {
      const m = e.target.closest("[data-target]");
      if (m) location.hash = "#/photo/" + m.dataset.target;
    });
    $("#photo-retry", view).addEventListener("click", () => this.load());
    this.load();
  },

  async load() {
    const view = this.view;
    $("#photo-loading", view).hidden = false;
    $("#dossier", view).hidden = true;
    $("#photo-error", view).hidden = true;
    $("#photo-error", view).classList.add("hidden");
    $("#photo-error", view).classList.remove("flex");
    try {
      this.data = await photoDetail(this.id);
      if (!this.data) throw new Error("I could not find that photo.");
      if (!view.isConnected) return;
      this.render(this.data);
      $("#photo-loading", view).hidden = true;
      $("#dossier", view).hidden = false;
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
  },

  async ask(question) {
    const view = this.view;
    const panel = $("#ask-answer", view);
    panel.classList.remove("hidden");
    panel.classList.add("flex");
    $("#ask-text", view).textContent = "Thinking…";
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
      if (data.source === "image" && data.note) {
        src.textContent = data.note;
        src.classList.remove("hidden");
      }
    } catch (e) {
      if (!view.isConnected) return;
      $("#ask-text", view).textContent = String((e && e.message) || e);
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
      const c = e.target.closest("[data-target]");
      if (c) location.hash = "#/photo/" + c.dataset.target;
    });
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
      if (note) form.append("owner_note", note);
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
  data: null,
  selected: null,
  filter: "",

  GROUP_ORDER: ["same_place", "another_angle", "taken_from_here", "similar_look"],
  GROUP_META: {
    same_place: { title: "Same Place", dot: "bg-on-tertiary-container",
      icon: "near_me", arc: "Bridge: Same Place", note: "Same subject, same viewpoint" },
    another_angle: { title: "Another Angle", dot: "bg-secondary",
      icon: "view_in_ar", arc: "Bridge: Another Angle", note: "Same subject, different viewpoint" },
    taken_from_here: { title: "Where You Were Standing", dot: "bg-primary-container",
      icon: "tripod", arc: "Bridge: Taken From Here", note: "Shows where you stood" },
    similar_look: { title: "Similar Look", dot: "bg-outline",
      icon: "filter_tilt_shift", arc: "Bridge: Similar Look", note: "Closest look-alikes" },
  },

  mount(view) {
    this.view = view;
    this.data = null;
    this.selected = null;
    this.filter = "";
    $("#connected-refresh", view).addEventListener("click", () => this.load());
    $("#connected-retry", view).addEventListener("click", () => this.load());
    $("#captures-filter", view).addEventListener("input", (e) => {
      this.filter = e.target.value.trim().toLowerCase();
      this.renderList();
    });
    $("#captures-list", view).addEventListener("click", (e) => {
      const b = e.target.closest("[data-pid]");
      if (b) this.select(b.dataset.pid);
    });
    $("#anchor-groups", view).addEventListener("click", (e) => {
      const c = e.target.closest("article[data-target]");
      if (c) location.hash = "#/photo/" + c.dataset.target;
    });
    this.load();
  },

  async load() {
    const view = this.view;
    $("#connected-loading", view).hidden = false;
    $("#connected-grid", view).hidden = true;
    $("#connected-empty", view).hidden = true;
    $("#connected-empty", view).classList.add("hidden");
    $("#connected-empty", view).classList.remove("flex");
    $("#connected-error", view).hidden = true;
    $("#connected-error", view).classList.add("hidden");
    $("#connected-error", view).classList.remove("flex");
    try {
      const data = await api("/api/connected");
      if (!view.isConnected) return;
      $("#connected-loading", view).hidden = true;
      const s = data.summary || {};
      const p = s.photos_connected || 0;
      const pl = s.places_connected || 0;
      $("#connected-title", view).textContent =
        p + " of your " + (p === 1 ? "photo connects" : "photos connect") +
        " to " + pl + (pl === 1 ? " place" : " places") + " in the world";
      let upd = "";
      if (data.updated_at) {
        const t = new Date(data.updated_at);
        if (!isNaN(t)) upd = " • updated " + t.toLocaleString();
      }
      $("#connected-sub", view).textContent =
        (s.matches_total || 0) + " world matches" + upd;
      $("#connected-count", view).textContent = p + " Connected";
      const entries = data.photos || [];
      if (!entries.length || entries.every((e) => !(e.match_count > 0))) {
        const box = $("#connected-empty", view);
        box.hidden = false;
        box.classList.remove("hidden");
        box.classList.add("flex");
        return;
      }
      this.data = data;
      $("#connected-grid", view).hidden = false;
      const first = entries.find((e) => e.match_count > 0) || entries[0];
      this.select(first.photo.photo_id);
    } catch (e) {
      if (!view.isConnected) return;
      $("#connected-loading", view).hidden = true;
      $("#connected-error-text", view).textContent = String((e && e.message) || e);
      const box = $("#connected-error", view);
      box.hidden = false;
      box.classList.remove("hidden");
      box.classList.add("flex");
    }
  },

  filtered() {
    const entries = (this.data && this.data.photos) || [];
    if (!this.filter) return entries;
    return entries.filter((e) => {
      const hay = ((e.photo.caption || "") + " " + e.photo.photo_id).toLowerCase();
      return hay.includes(this.filter);
    });
  },

  renderList() {
    const view = this.view;
    const box = $("#captures-list", view);
    box.innerHTML = "";
    const T = $("#tpl-capture", view).content.firstElementChild;
    this.filtered().forEach((entry) => {
      const node = T.cloneNode(true);
      const pid = entry.photo.photo_id;
      node.dataset.pid = pid;
      const on = pid === this.selected;
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
      this.fillPlace(node, pid);
    });
    if (!box.children.length) {
      const p = document.createElement("p");
      p.className = "font-body-sm text-body-sm text-on-surface-variant";
      p.textContent = "No captures match that filter.";
      box.appendChild(p);
    }
  },

  async fillPlace(node, pid) {
    const d = await photoDetail(pid);
    if (!d || !node.isConnected) return;
    $("[data-slot=place]", node).textContent = (d.place && d.place.name) || "Place unknown";
  },

  select(pid) {
    this.selected = pid;
    this.renderList();
    this.renderAnchor();
  },

  renderAnchor() {
    const view = this.view;
    const entry = ((this.data && this.data.photos) || [])
      .find((e) => e.photo.photo_id === this.selected);
    if (!entry) return;
    const img = $("#anchor-img", view);
    img.src = entry.photo.src;
    img.alt = entry.photo.caption || entry.photo.photo_id;
    img.addEventListener("error", () => img.setAttribute("data-broken", "true"));
    $("#anchor-id", view).textContent = "ID: " + entry.photo.photo_id;
    $("#anchor-caption", view).textContent = entry.photo.caption || entry.photo.photo_id;
    const mc = entry.match_count || 0;
    $("#anchor-links", view).textContent =
      mc + (mc === 1 ? " Linked World Artifact Found" : " Linked World Artifacts Found");
    $("#anchor-dossier", view).href = "#/photo/" + entry.photo.photo_id;
    const groups = entry.groups || {};
    const box = $("#anchor-groups", view);
    box.innerHTML = "";
    const T = (n) => $("#" + n, view).content.firstElementChild;
    let shown = 0;
    this.GROUP_ORDER.forEach((k) => {
      const items = groups[k] || [];
      if (!items.length) return;
      const meta = this.GROUP_META[k];
      const sec = T("tpl-cgroup").cloneNode(true);
      $("[data-slot=arc-icon]", sec).textContent = meta.icon;
      $("[data-slot=arc-label]", sec).textContent = meta.arc;
      $("[data-slot=dot]", sec).className += " " + meta.dot;
      $("[data-slot=title]", sec).textContent = meta.title;
      $("[data-slot=count]", sec).textContent =
        items.length + (items.length === 1 ? " archive capture" : " archive captures");
      $("[data-slot=note]", sec).textContent = meta.note;
      const cards = $("[data-slot=cards]", sec);
      items.forEach((item) => cards.appendChild(this.matchCard(T, item)));
      shown += items.length;
      box.appendChild(sec);
    });
    $("#anchor-nolinks", view).classList.toggle("hidden", shown > 0);
  },

  matchCard(T, item) {
    const node = T("tpl-cmatch").cloneNode(true);
    node.dataset.target = item.photo_id;
    const img = $("[data-slot=img]", node);
    img.src = item.src || srcOf(item);
    img.alt = item.caption || item.photo_id;
    img.addEventListener("error", () => img.setAttribute("data-broken", "true"));
    $("[data-slot=match]", node).textContent = typeof item.similarity === "number"
      ? Math.round(item.similarity * 100) + "% Match"
      : (typeof item.score === "number" ? "score " + item.score.toFixed(2) : "");
    const vp = $("[data-slot=vp]", node);
    if (item.viewpoint && VP_LABEL[item.viewpoint]) vp.textContent = VP_LABEL[item.viewpoint];
    else vp.classList.add("hidden");
    $("[data-slot=byline]", node).textContent = item.credit && item.credit.author
      ? "Photo by " + item.credit.author : "World archive photo";
    $("[data-slot=pid]", node).textContent = item.photo_id;
    $("[data-slot=title]", node).textContent =
      item.place || (item.caption || item.photo_id).slice(0, 60);
    $("[data-slot=reason]", node).textContent = item.reason_text || "match";
    const credit = $("[data-slot=credit]", node);
    if (item.credit && (item.credit.author || item.credit.license)) {
      const b = document.createElement("span");
      b.className = "font-semibold text-on-surface";
      b.textContent = "Photo by " + (item.credit.author || "Unknown");
      credit.appendChild(b);
      if (item.credit.license) {
        credit.appendChild(document.createTextNode(" • License: "));
        if (item.credit.source_url) {
          const a = document.createElement("a");
          a.href = item.credit.source_url;
          a.target = "_blank";
          a.rel = "noopener";
          a.className = "underline decoration-dotted hover:text-ochre";
          a.textContent = item.credit.license;
          a.addEventListener("click", (e) => e.stopPropagation());
          credit.appendChild(a);
        } else credit.appendChild(document.createTextNode(item.credit.license));
      }
    } else {
      credit.textContent = "World archive photo";
    }
    return node;
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

function stubView(title, body) {
  const mount = $("#view");
  mount.innerHTML = "";
  const sec = document.createElement("section");
  sec.className = "w-full rounded-2xl bg-parchment-card border border-parchment-border p-8 shadow-archival flex flex-col gap-3 max-w-2xl";
  const h = document.createElement("h2");
  h.className = "text-xl font-bold text-espresso-950 tracking-tight";
  h.textContent = title;
  const p = document.createElement("p");
  p.className = "text-sm text-espresso-700 leading-relaxed";
  p.textContent = body;
  const a = document.createElement("a");
  a.className = "inline-flex items-center gap-1.5 h-10 px-4 rounded-xl bg-espresso-900 text-papyrus-100 text-sm font-semibold w-fit";
  a.href = "#/";
  a.textContent = "Back to search";
  sec.append(h, p, a);
  mount.appendChild(sec);
}

async function route() {
  const hash = location.hash || "#/";
  clearInterval(home.loadingTimer);
  if (add.pollTimer) { clearInterval(add.pollTimer); add.pollTimer = null; }
  if (hash.startsWith("#/photo/")) {
    const id = decodeURIComponent(hash.slice("#/photo/".length));
    setActiveTab("");
    try {
      const html = await loadView("photo");
      $("#view").innerHTML = html;
      photo.mount($("#view"), id);
    } catch (e) {
      stubView("The photo view failed to load", String((e && e.message) || e));
    }
    return;
  }
  if (hash.startsWith("#/add")) {
    setActiveTab("add");
    try {
      const html = await loadView("add");
      $("#view").innerHTML = html;
      add.mount($("#view"));
    } catch (e) {
      stubView("The add-photo view failed to load", String((e && e.message) || e));
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
      stubView("The Connected view failed to load", String((e && e.message) || e));
    }
    return;
  }
  try {
    const html = await loadView("home");
    $("#view").innerHTML = html;
    home.mount($("#view"));
  } catch (e) {
    stubView("The home view failed to load", String((e && e.message) || e));
  }
}

/* ---------- boot ---------- */
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    const input = $("#conversational-input");
    if (input) { e.preventDefault(); input.focus(); }
  }
});
$$(".js-tab, .js-mtab").forEach((a) => {
  a.addEventListener("click", (e) => {
    const tab = a.dataset.tab;
    if (tab === "world" || tab === "personal") {
      e.preventDefault();
      home.browse = tab;
      if ((location.hash || "#/") !== "#/") { location.hash = "#/"; return; }
      if (home.view && home.view.isConnected) home.browse(tab);
      else route();
    }
  });
});
window.addEventListener("hashchange", route);
refreshShell();
route();
