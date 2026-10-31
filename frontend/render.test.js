/* Tests for frontend/story-render.js (the one canvas renderer).
 * Run: node frontend/render.test.js
 * Uses a fake 2d context that records calls; no browser needed. */
"use strict";
const fs = require("fs");
const path = require("path");
const R = require("./story-render.js");

let passed = 0;
let failed = 0;
function check(name, cond) {
  if (cond) passed++;
  else {
    failed++;
    console.log("FAIL " + name);
  }
}
function near(a, b, eps) {
  return Math.abs(a - b) <= (eps || 1e-6);
}

/* Fake image with real dimensions. */
function fakeImg(w, h) {
  return { naturalWidth: w, width: w, naturalHeight: h, height: h };
}

/* Fake 2d context: records every call and property set. */
function fakeCtx() {
  const calls = [];
  const ctx = {
    calls: calls,
    fillStyle: "",
    font: "",
    textAlign: "",
    textBaseline: "",
    filter: "none",
  };
  let alpha = 1;
  Object.defineProperty(ctx, "globalAlpha", {
    get() { return alpha; },
    set(v) {
      alpha = v;
      calls.push({ m: "setAlpha", v: v });
    },
  });
  for (const m of ["save", "restore", "fillRect", "drawImage", "fillText",
                  "beginPath", "arc", "clip", "rect", "roundRect", "fill"]) {
    ctx[m] = (...args) => calls.push({ m: m, args: args, style: ctx.fillStyle });
  }
  ctx.measureText = (s) => ({ width: String(s).length * 10 });
  ctx.createLinearGradient = () => ({ addColorStop() {} });
  return ctx;
}

function texts(ctx) {
  return ctx.calls.filter((c) => c.m === "fillText").map((c) => String(c.args[0]));
}
function hasText(ctx, sub) {
  return texts(ctx).some((t) => t.indexOf(sub) >= 0);
}
function methods(ctx) {
  return ctx.calls.map((c) => c.m);
}

const SIZE = { width: 1080, height: 1920 };

function scene(over) {
  return Object.assign({
    photo_id: "p1", src: "/p1", collection: "personal",
    credit: { author: "Me", license: "" },
    seconds: 3, focal: null, role: "build", pacing: "medium",
    camera: "hold", transition_in: null, found_text: null,
    caption_note: null, caption: "A quiet caption here.",
    why: "", frames: ["p1"], frame_seconds: 0, burst: false,
  }, over || {});
}

function film(over) {
  return Object.assign({
    title: "Test film",
    scenes: [scene({ photo_id: "p1" }), scene({ photo_id: "p2", transition_in: "cut" })],
    images: { p1: fakeImg(1200, 800), p2: fakeImg(1200, 800) },
    reducedMotion: false,
    themeColor: "#123456",
  }, over || {});
}

const FOCAL = {
  focal: { x: 0.4, y: 0.45 },
  subject_box: null,
  safe_crop_916: { x: 0.1, y: 0, w: 0.375, h: 1 },
  mood: "calm",
  confidence: 0.9,
};

/* --- timeline / sceneAt --- */
{
  const tl = R.timeline(film());
  check("timeline starts", JSON.stringify(tl.starts) === "[0,3]");
  check("timeline total has end card", near(tl.total, 9));
  const mid = R.sceneAt(film(), 1);
  check("sceneAt mid scene", mid.kind === "scene" && mid.index === 0 && near(mid.local, 1));
  const f = film();
  f.scenes[1].transition_in = "dissolve";
  const tr = R.sceneAt(f, 2.6);
  check("sceneAt dissolve window", tr.kind === "transition" && tr.from === 0 &&
        tr.to === 1 && tr.q > 0 && tr.q < 1);
  const edge = R.sceneAt(f, 3);
  check("sceneAt boundary is incoming", edge.kind === "scene" && edge.index === 1 &&
        near(edge.local, 0));
  const end = R.sceneAt(film(), 8.9);
  check("sceneAt end card", end.kind === "end" && end.local > 2 && end.local <= 3);
  const past = R.sceneAt(film(), 99);
  check("sceneAt clamps past end", past.kind === "end" && near(past.local, 3));
  const cut = R.sceneAt(film(), 2.999);
  check("cut has no overlap", cut.kind === "scene" && cut.index === 0);
  const red = film({ reducedMotion: true });
  const rtl = R.timeline(red);
  check("reduced scales total", near(rtl.total, 11.25));
  check("reduced forces dissolve", R.transitionName(red, 1) === "dissolve");
  check("reduced transition dur", near(R.transitionDur(red, 1), 0.4));
  const weird = film();
  weird.scenes[1].transition_in = "whirl";
  check("unknown transition is cut", R.transitionName(weird, 1) === "cut" &&
        R.transitionDur(weird, 1) === 0);
  check("empty story is end", R.sceneAt(film({ scenes: [] }), 0).kind === "end");
}

/* --- sourceRect --- */
{
  const img = fakeImg(1600, 1000);
  const base = scene({ focal: FOCAL, camera: "push_in" });
  const r0 = R.sourceRect(img, base, 0, 1080 / 1920, false);
  check("crop matches canvas aspect", near(r0.sw / r0.sh, 1080 / 1920, 1e-3));
  const r1 = R.sourceRect(img, base, 1, 1080 / 1920, false);
  check("push_in zooms in", r1.sw < r0.sw);
  const out0 = R.sourceRect(img, scene({ focal: FOCAL, camera: "pull_back" }),
                             0, 1080 / 1920, false);
  const out1 = R.sourceRect(img, scene({ focal: FOCAL, camera: "pull_back" }),
                             1, 1080 / 1920, false);
  check("pull_back zooms out", out1.sw > out0.sw);
  const pan0 = R.sourceRect(img, scene({ focal: FOCAL, camera: "pan_to_focal" }),
                             0, 1080 / 1920, false);
  const pan1 = R.sourceRect(img, scene({ focal: FOCAL, camera: "pan_to_focal" }),
                             1, 1080 / 1920, false);
  check("pan moves toward focal", Math.abs(pan1.sx + pan1.sw / 2 - 0.4 * 1600) <
        Math.abs(pan0.sx + pan0.sw / 2 - 0.4 * 1600));
  const rh0 = R.sourceRect(img, base, 0, 1080 / 1920, true);
  const rh1 = R.sourceRect(img, base, 1, 1080 / 1920, true);
  check("reduced motion holds", rh0.sw === rh1.sw && rh0.sx === rh1.sx);
  const burst = scene({ focal: FOCAL, camera: "push_in",
                        frames: ["p1", "p2"], frame_seconds: 0.2 });
  const b0 = R.sourceRect(img, burst, 0, 1080 / 1920, false);
  const b1 = R.sourceRect(img, burst, 1, 1080 / 1920, false);
  check("burst holds", b0.sw === b1.sw && b0.sx === b1.sx);
  const unk = R.sourceRect(img, scene({ focal: FOCAL, camera: "spin" }),
                            0.5, 1080 / 1920, false);
  check("unknown camera holds", unk.sw > 0 && unk.sh > 0);
  const nocrop = R.sourceRect(img, scene({ focal: null }), 0.5, 1080 / 1920, false);
  check("no-crop rect matches aspect", near(nocrop.sw / nocrop.sh, 1080 / 1920, 1e-3));
  const cf = R.canvasFocal(fakeImg(1000, 1000),
    scene({ focal: { focal: { x: 0.5, y: 0.5 },
                     safe_crop_916: { x: 0.21875, y: 0, w: 0.5625, h: 1 } } }),
    1080, 1920);
  check("canvasFocal maps to canvas", near(cf.x, 540, 1) && near(cf.y, 960, 1));
}

/* --- renderFrame --- */
{
  const f = film();
  f.scenes[0].focal = FOCAL;
  const c0 = fakeCtx();
  R.renderFrame(f, 0.5, c0, SIZE);
  check("bg painted black first", c0.calls[1].m === "fillRect" &&
        c0.calls[1].style === "#000");
  check("scene draws image", c0.calls.some((c) => c.m === "drawImage" && c.args.length === 9));
  check("caption painted", hasText(c0, "A quiet caption here."));

  const miss = film({ images: {} });
  const c1 = fakeCtx();
  R.renderFrame(miss, 0.5, c1, SIZE);
  check("missing image placeholder", hasText(c1, "Photo unavailable") &&
        hasText(c1, "A quiet caption here."));

  const card = film();
  card.scenes[0].focal = FOCAL;
  card.scenes[0].found_text = { text: "KICC TOWER SIGN", badge: "Confirmed" };
  const c2 = fakeCtx();
  R.renderFrame(card, 0.5, c2, SIZE);
  check("found card early", hasText(c2, "KICC TOWER SIGN") && hasText(c2, "Confirmed"));
  const c3 = fakeCtx();
  R.renderFrame(card, 2.5, c3, SIZE);
  check("found card gone later", !hasText(c3, "KICC TOWER SIGN"));

  const world = film();
  world.scenes[0].collection = "world";
  world.scenes[0].credit = { author: "Jane", license: "CC BY 4.0" };
  const c4 = fakeCtx();
  R.renderFrame(world, 0.5, c4, SIZE);
  check("world cutaway tag", hasText(c4, "From the world") && hasText(c4, "Jane"));

  const burst = film();
  burst.images = { a: fakeImg(800, 800), b: fakeImg(800, 800) };
  burst.scenes[0] = scene({ photo_id: "a", focal: FOCAL, frames: ["a", "b"],
                             frame_seconds: 0.2, burst: true });
  const c5 = fakeCtx();
  R.renderFrame(burst, 0.05, c5, SIZE);
  const c6 = fakeCtx();
  R.renderFrame(burst, 0.25, c6, SIZE);
  const imgAt = (c) => (c.calls.find((x) => x.m === "drawImage") || {}).args;
  check("burst swaps frames", imgAt(c5)[0] === burst.images.a &&
        imgAt(c6)[0] === burst.images.b);

  const end = film();
  const c7 = fakeCtx();
  R.renderFrame(end, 8.5, c7, SIZE);
  check("end card credits", hasText(c7, "Test film") && hasText(c7, "Photo: Me") &&
        hasText(c7, "Built with Muse Spark Open"));

  for (const [name, want] of [["dissolve", "setAlpha"], ["iris", "arc"],
                              ["dip", "fillRect"], ["rise", "drawImage"],
                              ["descend", "drawImage"]]) {
    const tf = film();
    tf.scenes[0].focal = FOCAL;
    tf.scenes[1].focal = FOCAL;
    tf.scenes[1].transition_in = name;
    const d = R.transitionDur(tf, 1);
    const tc = fakeCtx();
    R.renderFrame(tf, 3 - d / 2, tc, SIZE);
    const ms = methods(tc);
    let ok = ms.indexOf(want) >= 0;
    if (name === "dissolve") {
      ok = tc.calls.some((c) => c.m === "setAlpha" && c.v > 0 && c.v < 1);
    }
    if (name === "dip") {
      ok = tc.calls.some((c) => c.m === "fillRect" && c.style === "#123456");
    }
    if (name === "iris") ok = ok && ms.indexOf("clip") >= 0;
    check("transition " + name, ok);
  }
  const c8 = fakeCtx();
  R.renderFrame(film(), 1, c8, SIZE);
  check("ctx state restored", c8.globalAlpha === 1 && c8.filter === "none");
}

/* --- adapt + migrate + wiring --- */
{
  const ad = R.adaptFilm({ title: "T", scenes: [{ photo_id: "x", caption_note: "hi" }] });
  check("adaptFilm defaults", ad.scenes[0].seconds === 3 &&
        ad.scenes[0].caption === "hi" &&
        JSON.stringify(ad.scenes[0].frames) === '["x"]' &&
        ad.reducedMotion === false);
  const mig = R.migrateChapters({ story: { title: "Old" },
    chapters: [{ photo_id: "p", heading: "Head", text: "Body text." }] });
  check("migrateChapters joins caption", mig.title === "Old" &&
        mig.scenes[0].caption === "Head. Body text." && mig.scenes[0].seconds === 3);
  const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
  const ri = html.indexOf("story-render.js");
  const ai = html.indexOf('src="/app.js"');
  check("index wires renderer before app", ri > 0 && ai > 0 && ri < ai);
}

console.log(`render.test.js: ${passed}/${passed + failed} checks passed`);
process.exit(failed ? 1 : 0);
