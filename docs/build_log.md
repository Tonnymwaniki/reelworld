# Build log

One entry per phase: done, tested how, commit id, open problems.
On session restart, read this + `docs/build_plan.md` and continue at
the first unfinished phase.

## Phase 0 — foundation (done)

- Wrote `docs/build_plan.md` (41 screens → routes → endpoints, new vs
  existing), `docs/deferred.md`, this log; updated `AGENTS.md` (Reel,
  English-only, demo mode, phases).
- Tokens: merged design_system_v6 (authoritative) + papyrus set into the
  shell config and `frontend/styles.css`. Choices: `rounded-full` keeps
  9999px (screenshots show true pills; v6's `full: 0.75rem` contradicts
  them); radius DEFAULT/lg/xl adopted (old views will look tighter until
  their phase replaces them); `secondary` is now #476556 (v6), forest
  green stays under `forest`.
- Shell: export header (avatar removed: no user profiles; cluster pill
  is live API status, never a fake latency), 5-tab nav + mobile nav,
  demo banner + code field (sessionStorage only), export footer minus
  the GitHub link (no URL known; deferred), router with phase stubs,
  404 + error views from the export (fake node names, latencies, uptime
  and Inspect Pipe removed; real path/count/message/API check instead).
- Backend: `GET /api/config` (flags + real counts), demo gate
  (`X-Demo-Code`, 403) on upload, `GET /og-image.png`.
- `scripts/make_og_image.py` → `frontend/og-image.png` (1200×630, real
  photos/credits/counts 132/70/51; dropped fake latency, names, %s, domain).
- Old views stay live until replaced; unbuilt routes show honest stubs.
- Tested: `/api/config` (demo true, 132/16), `/` 200 (label/nav/og),
  `/views/404.html` 200, og 200 PNG, upload w/o code 403, gate branches
  (right code/no code/demo off), old endpoints OK, JS + both suites green.
- Commit id: (this commit; see `git log`).
- Open: footer GitHub link needs the real repo URL; Phase 1 builds Reel.

## Phase 1 — Reel thread, credits, about, flag, tour (done, needs server smoke)

- Backend: `turn_stream` + `POST /chat/stream` (SSE step/result/error),
  `GET /api/credits` (manifest + captions/places), `POST /api/flag`
  (`data/flags.jsonl`, never demo-gated), `GET /tour/{step}.json`,
  demo gate on upload. `scripts/record_tour.py` + `data/tour/*.json`.
- Meta key (safe part): `META_API_KEY` is set; `PARSER_*` placeholders
  no longer override the working Baseten defaults (`_env_or`);
  `POST /api/outline` returns honest 501; `scripts/probe_meta.py`
  probes the Meta endpoint once its docs arrive. Routing reasoning to
  Meta needs the base URL + model name (asked, still open).
- Also: `/api/config` counts gain `places` + `themes`;
  `VIEW_NAMES` gains `about`, `credits`; tour `shaped()` now keeps
  `src` (snapshots must be re-recorded: step 2 candidates lack `src`).
- Frontend: `p1_extract.py` (landing+thread+frags+credits+about from the
  exports), `p1_assemble.py` (12 templates into `home.html`; tour-modal
  landmark fixed). `app.js` rewritten for the thread: SSE progress with
  live elapsed + stop, filter chips with instant re-search, action chips,
  suggestions, compare-select + `/api/compare`, flag dialog, in-thread
  add-photo with job polling, 60-second tour, live stats + trust sample,
  credits directory (metrics, donut, pills, search, sort, cite, toast),
  about (live counts, duo, session reset).
- Honesty pass: 53 external placeholder images stripped (all JS-filled
  from real data); fake stats/copy/benchmarks replaced with live counts
  or removed; inline `onclick` removed; tune button + world-publish
  button deferred (rows in `docs/deferred.md`). Landing cards verified
  offline: market_018 / cbd_020 / landmarks_004 / street_022; trust
  sample landmarks_003; about duo cbd_002 + hills_006.
- Tested: `node --check`, `home.test.js` 32/32, structural verify (every
  wired id/template/handler resolves; old views intact). NOT run here
  (no Python in this sandbox): py_compile, `backend/test_story.py`,
  `record_tour.py` re-run, server smoke. User-run commands in the chat
  report.
- Commit id: (this commit; see `git log`).
- Open: re-record tour; Meta endpoint docs; footer GitHub URL; Phase 2
  rebuilds the photo detail view.

## Meta Llama routing (post-P1; needs probe + search test)

- `.env` gained the Llama set (`META_API_BASE_URL`/`LLAMA_API_BASE`,
  `LLAMA_WONDER_MODEL`, `LLAMA_SPARK_MODEL`, `SAM_BASE_URL`,
  `SAM_MODEL`); removed a pasted junk line and retired the stale
  `PARSER_KEY_ENV=MODAL_API_KEY` pointer (Modal was never real).
- `chat.resolve_parser()`: explicit `PARSER_*` wins; else Meta Llama
  (compat base + Wonder + `META_API_KEY`) when fully configured; else
  Baseten. Key pointers to placeholders are ignored; the key follows
  the base. Covers parse, answers, ask, compare and story.
- `scripts/probe_meta.py` now probes the resolved backend and prints
  base/model/key-name (never the key).
- SAM 3.1 is segmentation, not chat: outlines stay 501 until Meta's SAM
  request/response docs arrive (one curl example is enough).
- NOT run here (no Python in this sandbox): probe, py_compile,
  live search test. User-run commands in the chat report.
- Commit id: (this commit; see `git log`).

## Shell/hygiene fixes (from browser paste)

- Icons rendered as text: the Material Symbols URL had malformed axes;
  replaced with the documented `opsz,wght,FILL,GRAD` spec.
- Removed invented `v2.4` from the shell header; replaced the false
  "Encrypted locally" footer claim with the true privacy line.
- Fixed cascaded UTF-8 mojibake across views + frags (151 runs reversed
  to clean bullets, quotes, dashes, checks) and the false
  "Nairobi/Mombasa/Kisumu" stat sub-label.
- `home.test.js` gains view-hygiene regressions: 38/38 green.
