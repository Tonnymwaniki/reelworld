/* StoryRender: one canvas renderer for the story player AND exporter.
 *
 * renderFrame(story, t, ctx, size) paints the film frame at time t. The
 * player calls it every animation frame; the exporter calls it at fixed
 * 1/30s steps, so what you preview is exactly what you export.
 *
 * Story shape (v2 films have it; legacy chapters pass migrateChapters):
 *   { title, scenes: [{ photo_id, src, collection, credit: {author, license},
 *     seconds, focal: {focal, subject_box, safe_crop_916, mood, confidence} | null,
 *     role, pacing, camera, transition_in, found_text: {text, badge} | null,
 *     caption, frames: [photo_id], frame_seconds }],
 *     images: {photo_id: img}, reducedMotion: bool, themeColor? }
 * Loaded as a plain script (global StoryRender) and via require in tests.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.StoryRender = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const WANT_W = 1080;
  const WANT_H = 1920;
  const FALLBACK_W = 720;
  const FALLBACK_H = 1280;
  const FPS = 30;
  const END_CARD_SECONDS = 3;
  const REDUCED_SCALE = 1.25;
  const DIP_FALLBACK = "#C85A32";
  const CARD_WINDOW = 1.8;
  const FONT = '"Plus Jakarta Sans", sans-serif';
  const TRANSITION_SECONDS = {
    dissolve: 0.8, dip: 0.8, iris: 0.9, rise: 0.9, descend: 0.9,
    cut: 0, vantage: 0,
  };
  const REDUCED_TRANSITION = 0.4;
  const CAMERAS = ["push_in", "pull_back", "pan_to_focal", "hold"];

  function clamp01(p) {
    return Math.min(1, Math.max(0, p));
  }

  function easeInOut(p) {
    p = clamp01(p);
    return p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
  }

  function secsOf(scene) {
    return Number(scene.seconds) || 3;
  }

  function scaleOf(story) {
    return story.reducedMotion ? REDUCED_SCALE : 1;
  }

  /* Scene start times (scaled) + content/end totals. */
  function timeline(story) {
    const k = scaleOf(story);
    const starts = [];
    let t = 0;
    for (const s of story.scenes) {
      starts.push(t);
      t += secsOf(s) * k;
    }
    const endStart = t;
    const total = t + END_CARD_SECONDS * k;
    return { starts: starts, endStart: endStart, total: total, scale: k };
  }

  function transitionName(story, i) {
    if (i <= 0) return null;
    const name = story.scenes[i].transition_in || "cut";
    if (story.reducedMotion) return "dissolve";
    return Object.prototype.hasOwnProperty.call(TRANSITION_SECONDS, name) ? name : "cut";
  }

  function transitionDur(story, i) {
    if (i <= 0) return 0;
    if (story.reducedMotion) return REDUCED_TRANSITION;
    return TRANSITION_SECONDS[transitionName(story, i)] || 0;
  }

  /* Where time t falls: a scene, a transition overlap, or the end card. */
  function sceneAt(story, t) {
    const tl = timeline(story);
    t = Math.min(Math.max(0, t), tl.total);
    if (t >= tl.endStart || !story.scenes.length) {
      return { kind: "end", local: Math.min(t - tl.endStart, END_CARD_SECONDS * tl.scale) };
    }
    let i = 0;
    while (i + 1 < story.scenes.length && t >= tl.starts[i + 1]) i++;
    if (i + 1 < story.scenes.length) {
      const d = transitionDur(story, i + 1);
      if (d > 0 && t >= tl.starts[i + 1] - d) {
        return { kind: "transition", from: i, to: i + 1,
                 q: clamp01((t - (tl.starts[i + 1] - d)) / d) };
      }
    }
    return { kind: "scene", index: i, local: t - tl.starts[i] };
  }

  function imgDims(img) {
    return { w: (img && (img.naturalWidth || img.width)) || 0,
             h: (img && (img.naturalHeight || img.height)) || 0 };
  }

  /* Source rect for a scene at progress p (0-1): smart crop + camera.
   * Always matches the canvas aspect, so the draw never stretches. */
  function sourceRect(img, scene, p, canvasAspect, reduced) {
    const dims = imgDims(img);
    const iw = dims.w;
    const ih = dims.h;
    const crop = scene.focal && scene.focal.safe_crop_916;
    let bx;
    let by;
    let bw;
    let bh;
    if (crop) {
      bx = crop.x * iw;
      by = crop.y * ih;
      bw = crop.w * iw;
      bh = crop.h * ih;
    } else {
      bw = ih * canvasAspect <= iw ? ih * canvasAspect : iw;
      bh = bw / canvasAspect;
      bx = (iw - bw) / 2;
      by = (ih - bh) / 2;
    }
    let camera = CAMERAS.indexOf(scene.camera) >= 0 ? scene.camera : "hold";
    if (reduced || (scene.frames && scene.frames.length > 1)) camera = "hold";
    if (camera === "hold") return fitRect(bx, by, bw, bh, iw, ih, canvasAspect);
    const e = easeInOut(p);
    const f = (scene.focal && scene.focal.focal) || null;
    const fx = f ? f.x * iw : bx + bw / 2;
    const fy = f ? f.y * ih : by + bh / 2;
    let zoom;
    let cx;
    let cy;
    if (camera === "push_in") {
      zoom = 1 - 0.12 * e;
      cx = fx;
      cy = fy;
    } else if (camera === "pull_back") {
      zoom = 0.88 + 0.12 * e;
      cx = fx;
      cy = fy;
    } else {
      zoom = 0.88;
      cx = bx + bw / 2 + (fx - (bx + bw / 2)) * e;
      cy = by + bh / 2 + (fy - (by + bh / 2)) * e;
    }
    return fitRect(cx - (bw * zoom) / 2, cy - (bh * zoom) / 2,
                   bw * zoom, bh * zoom, iw, ih, canvasAspect);
  }

  function fitRect(x, y, w, h, iw, ih, aspect) {
    w = Math.min(w, iw);
    h = w / aspect;
    if (h > ih) {
      h = ih;
      w = h * aspect;
    }
    x = Math.min(Math.max(0, x), Math.max(0, iw - w));
    y = Math.min(Math.max(0, y), Math.max(0, ih - h));
    return { sx: x, sy: y, sw: w, sh: h };
  }

  function wrapLines(ctx, text, maxW) {
    const words = String(text || "").split(/\s+/).filter(Boolean);
    const lines = [];
    let line = "";
    for (const w of words) {
      const trial = line ? line + " " + w : w;
      if (ctx.measureText(trial).width <= maxW || !line) line = trial;
      else {
        lines.push(line);
        line = w;
      }
    }
    if (line) lines.push(line);
    return lines;
  }

  function pickImage(story, scene, local) {
    const frames = (scene.frames && scene.frames.length ? scene.frames : [scene.photo_id]);
    let pid = scene.photo_id;
    if (frames.length > 1 && scene.frame_seconds > 0) {
      pid = frames[Math.floor(local / scene.frame_seconds) % frames.length];
    }
    return { img: (story.images || {})[pid] || null, pid: pid };
  }

  function sceneDuration(story, i) {
    return secsOf(story.scenes[i]) * scaleOf(story);
  }

  function drawCover(ctx, img, rect, W, H, dx, dy) {
    ctx.drawImage(img, rect.sx, rect.sy, rect.sw, rect.sh, dx, dy, W, H);
  }

  /* No-crop fallback: blurred cover background + sharp contained photo. */
  function drawBlurFill(ctx, img, W, H) {
    const dims = imgDims(img);
    const cover = Math.max(W / dims.w, H / dims.h);
    const bw = dims.w * cover;
    const bh = dims.h * cover;
    ctx.save();
    try {
      ctx.filter = "blur(24px) brightness(0.55)";
    } catch (e) { /* older canvas: plain dark backdrop stays */ }
    ctx.drawImage(img, (W - bw) / 2, (H - bh) / 2, bw, bh);
    try {
      ctx.filter = "none";
    } catch (e) { /* ignore */ }
    ctx.restore();
    const fit = Math.min(W / dims.w, H / dims.h);
    const dw = dims.w * fit;
    const dh = dims.h * fit;
    ctx.drawImage(img, 0, 0, dims.w, dims.h, (W - dw) / 2, (H - dh) / 2, dw, dh);
  }

  function drawMissing(ctx, scene, W, H, k) {
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = "rgba(255,255,255,0.85)";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = '400 ' + Math.round(36 * k) + 'px ' + FONT;
    ctx.fillText("Photo unavailable", W / 2, H / 2 - 24 * k);
    ctx.fillStyle = "rgba(255,255,255,0.55)";
    ctx.font = '400 ' + Math.round(28 * k) + 'px ' + FONT;
    ctx.fillText(String(scene.photo_id || ""), W / 2, H / 2 + 24 * k);
  }

  function pill(ctx, cx, y, w, h, fill) {
    ctx.fillStyle = fill;
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") ctx.roundRect(cx - w / 2, y, w, h, h / 2);
    else ctx.rect(cx - w / 2, y, w, h);
    ctx.fill();
  }

  function drawFoundCard(ctx, scene, W, H, k) {
    const card = scene.found_text;
    if (!card || !card.text) return;
    ctx.save();
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    let y = H * 0.30;
    if (card.badge) {
      const bf = '600 ' + Math.round(28 * k) + 'px ' + FONT;
      ctx.font = bf;
      const bw = ctx.measureText(card.badge).width + 56 * k;
      pill(ctx, W / 2, y, bw, 52 * k,
           card.badge === "Confirmed" ? "#c9ead8" : "#F4DFD2");
      ctx.fillStyle = card.badge === "Confirmed" ? "#032015" : "#390c00";
      ctx.fillText(card.badge, W / 2, y + 27 * k);
      y += 76 * k;
    }
    ctx.font = '700 ' + Math.round(60 * k) + 'px ' + FONT;
    const lines = wrapLines(ctx, card.text, W - 200 * k).slice(0, 3);
    let widest = 0;
    for (const ln of lines) widest = Math.max(widest, ctx.measureText(ln).width);
    const boxH = lines.length * 78 * k + 56 * k;
    ctx.fillStyle = "rgba(21,19,17,0.80)";
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") {
      ctx.roundRect(W / 2 - widest / 2 - 48 * k, y, widest + 96 * k, boxH, 24 * k);
    } else {
      ctx.rect(W / 2 - widest / 2 - 48 * k, y, widest + 96 * k, boxH);
    }
    ctx.fill();
    ctx.fillStyle = "#fff";
    lines.forEach((ln, i) => ctx.fillText(ln, W / 2, y + 66 * k + i * 78 * k));
    ctx.restore();
  }

  function drawCaption(ctx, scene, W, H, k) {
    if (!scene.caption) return;
    const grad = ctx.createLinearGradient(0, H * 0.66, 0, H);
    grad.addColorStop(0, "rgba(0,0,0,0)");
    grad.addColorStop(1, "rgba(0,0,0,0.82)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, H * 0.66, W, H * 0.34);
    ctx.fillStyle = "rgba(255,255,255,0.92)";
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
    ctx.font = '400 ' + Math.round(42 * k) + 'px ' + FONT;
    const lines = wrapLines(ctx, scene.caption, W - 128 * k).slice(0, 3);
    lines.forEach((ln, i) => ctx.fillText(ln, 64 * k, H - 96 * k - (lines.length - 1 - i) * 54 * k));
  }

  function drawTag(ctx, scene, W, k) {
    if (scene.collection !== "world") return;
    const author = (scene.credit && scene.credit.author) || "";
    const label = author ? "From the world · " + author : "From the world";
    ctx.font = '600 ' + Math.round(28 * k) + 'px ' + FONT;
    const w = ctx.measureText(label).width + 56 * k;
    ctx.fillStyle = "rgba(0,0,0,0.55)";
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") ctx.roundRect(48 * k, 56 * k, w, 52 * k, 26 * k);
    else ctx.rect(48 * k, 56 * k, w, 52 * k);
    ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(label, 76 * k, 83 * k);
  }

  function canvasFocal(img, scene, W, H) {
    const aspect = W / H;
    const dims = imgDims(img);
    const r = sourceRect(img, scene, 0.5, aspect, true);
    const f = (scene.focal && scene.focal.focal) || { x: 0.5, y: 0.5 };
    return { x: ((f.x * dims.w - r.sx) / r.sw) * W,
             y: ((f.y * dims.h - r.sy) / r.sh) * H };
  }

  /* Paint one scene's frame; overlays optional (off for outgoing shots). */
  function drawScene(ctx, story, i, local, W, H, opts) {
    const scene = story.scenes[i];
    const dur = sceneDuration(story, i);
    const p = clamp01(local / dur);
    const picked = pickImage(story, scene, local);
    const img = picked.img;
    const dims = imgDims(img);
    const k = W / WANT_W;
    if (!img || !dims.w || !dims.h) {
      drawMissing(ctx, scene, W, H, k);
      if (!opts.quiet) {
        drawTag(ctx, scene, W, k);
        drawCaption(ctx, scene, W, H, k);
      }
      return;
    }
    const hasCrop = !!(scene.focal && scene.focal.safe_crop_916);
    if (hasCrop) {
      const r = sourceRect(img, scene, p, W / H, !!story.reducedMotion);
      drawCover(ctx, img, r, W, H, opts.dx || 0, opts.dy || 0);
    } else {
      drawBlurFill(ctx, img, W, H);
    }
    if (opts.quiet) return;
    if (scene.found_text && scene.found_text.text && local < Math.min(CARD_WINDOW, dur * 0.6)) {
      drawFoundCard(ctx, scene, W, H, k);
    }
    drawTag(ctx, scene, W, k);
    drawCaption(ctx, scene, W, H, k);
  }

  function drawEndCard(ctx, story, local, W, H) {
    const k = W / WANT_W;
    const alpha = clamp01(local / 0.5);
    ctx.fillStyle = "#151311";
    ctx.fillRect(0, 0, W, H);
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#fff";
    ctx.font = '700 ' + Math.round(70 * k) + 'px ' + FONT;
    wrapLines(ctx, story.title || "ReelWorld story", W - 160 * k).slice(0, 2)
      .forEach((ln, i) => ctx.fillText(ln, W / 2, H * 0.36 + i * 84 * k));
    const seen = {};
    const credits = [];
    for (const s of story.scenes) {
      const author = (s.credit && s.credit.author) || "";
      if (!author || seen[author]) continue;
      seen[author] = true;
      const lic = (s.credit && s.credit.license) || "";
      credits.push("Photo: " + author + (lic ? " · " + lic : ""));
    }
    ctx.font = '400 ' + Math.round(32 * k) + 'px ' + FONT;
    ctx.fillStyle = "rgba(255,255,255,0.78)";
    credits.slice(0, 6).forEach((ln, i) => ctx.fillText(ln, W / 2, H * 0.48 + i * 48 * k));
    if (credits.length > 6) {
      ctx.fillText("+ " + (credits.length - 6) + " more", W / 2, H * 0.48 + 6 * 48 * k);
    }
    ctx.font = '600 ' + Math.round(30 * k) + 'px ' + FONT;
    const built = "Built with Muse Spark Open";
    const w = ctx.measureText(built).width + 64 * k;
    pill(ctx, W / 2, H * 0.86, w, 56 * k, "#C85A32");
    ctx.fillStyle = "#fff";
    ctx.fillText(built, W / 2, H * 0.86 + 29 * k);
    ctx.restore();
  }

  function renderTransition(ctx, story, from, to, q, W, H) {
    const name = transitionName(story, to);
    const durFrom = sceneDuration(story, from);
    const tl = timeline(story);
    const localFrom = Math.min(durFrom, (tl.starts[to] - tl.starts[from]));
    if (name === "dissolve") {
      drawScene(ctx, story, from, localFrom, W, H, { quiet: true });
      ctx.save();
      ctx.globalAlpha = easeInOut(q);
      drawScene(ctx, story, to, 0, W, H, {});
      ctx.restore();
    } else if (name === "dip") {
      const phase = q < 0.5 ? q * 2 : (1 - q) * 2;
      drawScene(ctx, story, q < 0.5 ? from : to, q < 0.5 ? localFrom : 0, W, H, {});
      ctx.fillStyle = story.themeColor || DIP_FALLBACK;
      ctx.globalAlpha = easeInOut(phase);
      ctx.fillRect(0, 0, W, H);
      ctx.globalAlpha = 1;
    } else if (name === "iris") {
      drawScene(ctx, story, from, localFrom, W, H, { quiet: true });
      const picked = pickImage(story, story.scenes[to], 0);
      const ctr = picked.img && (picked.img.naturalWidth || picked.img.width)
        ? canvasFocal(picked.img, story.scenes[to], W, H) : { x: W / 2, y: H / 2 };
      const maxR = Math.hypot(W, H) / 2;
      ctx.save();
      ctx.beginPath();
      ctx.arc(ctr.x, ctr.y, Math.max(1, easeInOut(q) * maxR), 0, Math.PI * 2);
      ctx.clip();
      drawScene(ctx, story, to, 0, W, H, { quiet: q < 0.6 });
      ctx.restore();
    } else if (name === "rise" || name === "descend") {
      const e = easeInOut(q);
      const off = (name === "rise" ? -1 : 1) * e * H;
      drawScene(ctx, story, from, localFrom, W, H, { quiet: true, dx: 0, dy: off });
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, W, H);
      ctx.clip();
      drawScene(ctx, story, to, 0, W, H,
                { quiet: true, dx: 0, dy: off + (name === "rise" ? H : -H) });
      ctx.restore();
      /* Repaint the incoming frame's overlays so text never slides away. */
      ctx.save();
      ctx.globalAlpha = e;
      const k = W / WANT_W;
      const scene = story.scenes[to];
      drawTag(ctx, scene, W, k);
      drawCaption(ctx, scene, W, H, k);
      ctx.restore();
    } else {
      /* cut and vantage: hard switch at the boundary. */
      drawScene(ctx, story, q < 1 ? from : to, q < 1 ? localFrom : 0, W, H,
                { quiet: q < 1 });
    }
  }

  /* THE frame painter. story: adapted film; t: seconds; ctx: canvas 2d
   * context of size.width x size.height (a 9:16 size). */
  function renderFrame(story, t, ctx, size) {
    const W = size.width;
    const H = size.height;
    ctx.save();
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, W, H);
    const pos = sceneAt(story, t);
    if (pos.kind === "end") {
      drawEndCard(ctx, story, pos.local, W, H);
    } else if (pos.kind === "transition") {
      renderTransition(ctx, story, pos.from, pos.to, pos.q, W, H);
    } else {
      drawScene(ctx, story, pos.index, pos.local, W, H, {});
    }
    ctx.restore();
    ctx.globalAlpha = 1;
    try {
      ctx.filter = "none";
    } catch (e) { /* ignore */ }
  }

  /* Default every field the renderer reads, so v2 films paint as-is. */
  function adaptFilm(film, extra) {
    const scenes = (film.scenes || []).map((s) => ({
      photo_id: s.photo_id || "",
      src: s.src || "",
      collection: s.collection || "",
      credit: s.credit || null,
      seconds: Number(s.seconds) || 3,
      focal: s.focal || null,
      role: s.role || "",
      pacing: s.pacing || "medium",
      camera: s.camera || "hold",
      transition_in: s.transition_in || null,
      found_text: s.found_text || null,
      caption_note: s.caption_note || null,
      caption: s.caption || s.caption_note || "",
      why: s.why || "",
      frames: (s.frames && s.frames.length ? s.frames : [s.photo_id]).slice(),
      frame_seconds: Number(s.frame_seconds) || 0,
      burst: !!s.burst,
    }));
    return Object.assign({
      title: film.title || "ReelWorld story",
      scenes: scenes,
      images: {},
      reducedMotion: false,
      themeColor: null,
    }, extra || {});
  }

  /* Legacy chapter stories play through the same renderer. Captions are
   * joined heading + text; every other v2 field takes its plain default. */
  function migrateChapters(full) {
    const film = {
      title: (full.story && full.story.title) || "ReelWorld story",
      scenes: (full.chapters || []).map((c) => {
        const parts = [c.heading, c.text || c.caption].filter(Boolean);
        return {
          photo_id: c.photo_id || "",
          src: c.src || "",
          collection: c.collection || "",
          credit: c.credit || null,
          seconds: 3,
          caption: parts.join(". "),
        };
      }),
    };
    return adaptFilm(film);
  }

  return {
    WANT_W: WANT_W, WANT_H: WANT_H, FALLBACK_W: FALLBACK_W, FALLBACK_H: FALLBACK_H,
    FPS: FPS, END_CARD_SECONDS: END_CARD_SECONDS, REDUCED_SCALE: REDUCED_SCALE,
    TRANSITION_SECONDS: TRANSITION_SECONDS,
    renderFrame: renderFrame, sceneAt: sceneAt, timeline: timeline,
    transitionName: transitionName, transitionDur: transitionDur,
    sourceRect: sourceRect, wrapLines: wrapLines, canvasFocal: canvasFocal,
    adaptFilm: adaptFilm, migrateChapters: migrateChapters,
  };
});
