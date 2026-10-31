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

## SAM outlines implemented (needs live verification)

- `dev.meta.ai` key belongs to the Meta Model API (`api.meta.ai`), not
  `api.llama.com` — docs + live 401s proved the pasted "same system"
  claim wrong. `key_test.py` now probes Model API (chat 200 confirmed).
- New `backend/sam.py`: Responses call (`sam-3.1`, base64 data URL,
  `include_confidence`, `one_bit`), grammar parser per the SAM docs
  (boxes + normalized + opaque masks; malformed records skipped).
- `POST /api/outline` is real: 501 without flag/key, 404 unknown photo,
  400 promptless without entities, 502 on Meta errors. Prompt defaults
  to the top entity label. `FEATURE_OUTLINES` defaults true.
- `_msg_text()` in chat/api tolerates reasoning-style null content.
- Verifier gains an `outline` step (landmarks_003 + "tower").
- NOT run here (no Python in this sandbox): user runs verifier.
- Probe/app env unified (`META_API_MODEL` alias, `meta.ai` key routing); probe
  `max_tokens` 200 so reasoning models return visible content.
- Reasoning root-caused (docs + live captures): Spark reasons first and
  the budget counts reasoning, so probes starved (`length` + null even
  at 200 tokens). Probe + app now send `reasoning_effort: minimal`
  (extra_body, meta.ai only) via `chat_kwargs()`/`chat_create()`;
  `META_API_MODEL` wins over stale `LLAMA_WONDER_MODEL`. SAM 404 was a
  `/compat/v1` SAM_BASE_URL in `.env` (fix: delete that line).
- New `backend/test_parser_env.py`: 5 checks, plain-script style.
- Browser pass caught "wow thank you" re-searching: new `social_reply()`
  short-circuits small-talk-only messages (kind `chat`, no LLM call) in
  `turn_stream`; anything substantive still searches. Frontend needed no
  change (`renderText` path, no nomatch template). Test: 26 checks.

## Phase 2: photo dossier + attribution kit

- P0 dossier already wired the full evidence panel (caption, things,
  signs Clear/Partial + confidence, place Confirmed/Candidate + evidence,
  landmarks, taken_from, uncertainties, credit, suggested questions, Ask
  with trace, bridge groups, share gating) — audit found no gaps, so no
  rebuild was needed there.
- Built the attribution kit sheet from the `world_attribution_kit_plate`
  export: plate mount, provenance ledger (photographer/license/subject/
  source, all from `/api/photo`), credit line with Plain/HTML/BibTeX tabs
  + copy, per-family license summary matrix (BY-SA/BY/CC0/unknown),
  JSON record download, report-inaccuracy via `/api/flag`. Personal
  photos get an honest private note instead of a kit.
- Honesty removals (documented in the view header): fake cadastre URLs,
  hashes, face-verification badge, sector pills, "signed" JSON-LD, year
  in BibTeX. No inline onclick.
- No backend change: kit uses existing `/api/photo` + `/api/flag`.
- Tests: new `frontend/photo.test.js` 60/60, `home.test.js` still 38/38
  (both run here). Browser pass pending user.
- Out of scope, noted: the design's Outlines toggle is feasible now
  (SAM live) but not in the P2 checklist; candidate for later.

## Phase 3: connected rings + explain (needs user Python run + browser)

- Backend (appended to `backend/api.py`, `retrieval.py` untouched):
  `GET /api/rings/{id}` (5 rings, ≤8 each, R5 similarity floor 0.5,
  per-member deterministic facts), `GET /api/places/overview`
  (world-vs-mine viewpoint counts + gaps), `GET /api/connected/self`
  (personal↔personal pairs), `POST /api/explain` (facts + strict
  evidence-only LLM paragraph, honest no-link reply without a call).
  Ring rule: each photo lands in exactly one ring, R1-R4 earned by
  place/landmark keys, never fuzzy names.
- Frontend: `#/connected` rebuilt with Overview / Ring diagram / Explain
  tabs from the six connected exports — stats, place cards with gap
  lines, self rows, SVG ring stage (design radii) + phone rows, link
  evidence panel, explain flow with chain graphic. Honesty removals:
  versions, latency pills, dates, elevations/rays/angles, cadastre refs,
  hashes, fake counts; vantage geometry deferred (self rows instead).
- Tests: `backend/test_links.py` (11 checks, user-run),
  `frontend/connected.test.js` 100/100 here; photo 60/60, home 38/38.
- Verifier gains rings/overview/self/explain steps.

## Phase 4: story engine + player + publish + Showcase (needs user run)

- New `backend/story_engine.py`: file-backed drafts (`data/stories/`,
  git-ignored), validation, faces-blocking publish (people-visible
  scenes block with ids named). Endpoints: CRUD `/api/stories[/{id}]`
  + `POST .../publish` (demo-gated; drafts ungated like flags).
  Create from prompt reuses the `/api/story` planner (short ≤5 scenes,
  medium ≤12); or from explicit photo_ids. GET/PATCH return enriched
  chapters (src/credit/people), heading problems, face flags.
- Frontend: `#/stories` (create + drafts), `#/stories/<id>` studio
  (building trace, review with reorder/edit/durations/problems,
  player preview, WebM/Markdown/JSON export, publish), `#/showcase`
  (published grid + player modal, no likes/comments). Old `#/story`
  view removed. Shared 9:16 player with Ken Burns (off under
  reduced-motion); WebM via canvas + MediaRecorder with real sizes;
  no MP4 anywhere.
- Honesty removals: versions, latency, sessions, ETAs, hashes,
  coords, capture dates, camera telemetry, invented sizes/counts/
  licenses/curators, unlisted tier, ZIP bundle. Tone mapping: player
  styling + caption pick (documented in code).
- Tests: `backend/test_stories.py` (15 checks, user-run),
  `frontend/stories.test.js` 118/118 here; all suites 316/316.
- Verifier gains a stories CRUD roundtrip step.

## Phase 5: libraries + world browse + gaps (needs user run)

- Backend: `GET /api/albums` (all/places/above/signs/people/look +
  bursts clustered by embedding similarity >= 0.85, covers in
  `data/library.json`), `PATCH /api/bursts/{key}` cover,
  `GET /api/world` (place/theme/viewpoint/people/text filters +
  facets; theme from the file path), `GET /api/gaps` (thin + empty
  non-unknown places), `POST /api/photo/{id}/correct` (personal-only
  owner overrides + re-embed, demo-gated), `DELETE /api/photo/{id}`
  + `DELETE /api/photos/mine` (file+annotation+row cascade,
  demo-gated), `GET /api/export` (ZIP of photos+annotations, ungated
  read). Corrections and deletes refresh the connected index.
- Frontend: `#/library` (albums, album drill, burst detail with
  frame player + cover pick + side-by-side compare, multi-file
  upload queue with pause/clear/cancel, correction + delete +
  export + delete-all), `#/browse` (filters, surprise, gaps with
  add-first links), `#/place/<key>` rebuilt (world/mine toggle,
  viewpoint sections, signs, credits, related, empty state).
- Deviations, all deliberate: `#/add` kept (queue is the fast path,
  single upload keeps owner notes); correction stores overrides
  without a Pass B rerun (pipeline stays out of requests); no theme
  albums for personal photos (no theme data); vantage geometry and
  EXIF/telemetry cut as unbackable.
- Tests: `backend/test_library.py` (14 checks, user-run),
  `frontend/library.test.js` 172/172 here; all suites 488/488.
- Verifier gains albums/world/gaps/export steps plus correct/delete
  guards (world photo must 400/403, nothing mutated).

## Phase 6: polish + acceptance audit (user acceptance run pending)

- Route audit: 13 views resolve, no phase stubs left, no `#/story`
  refs, no TODO/FIXME/console.log. Demo audit: the 5 listed writes
  (upload, correct, delete, delete-all, publish) are guarded; reads,
  flags, drafts and local prefs are documented ungated. No secrets
  in tracked files. og/meta + footer verified (no GitHub URL known).
- Honesty purge: v2.4/version pills (404/add/home), fake 94.6% stat
  and batch number (home badge), fake trace rows (OCR/Gazette/pixels
  → live-trace shell), fake credit-table rows (8 dead rows deleted;
  tbody hidden until live render), fake citation URL/id (real
  market_018 example), hardcoded license counts (neutral until live).
  Template placeholders (NBO-*/C. Karanja) neutralized in home.html.
  Dead `_frag_*.html` build leftovers deleted (unreferenced).
- Credits row 1 kept as a hidden structural template: every slot is
  overwritten or removed by renderRows before display.
- `docs/deferred.md` extended with the P2-P6 unbackable cuts.
- Tests: `home.test.js` grows to 48/48 with template-hygiene
  regressions; all suites 498/498 here.
- Commit id: (this commit; see `git log`).

## Directed-film Stories, step 1: focal data (tests user-run, commit pending)

- New `backend/llm.py`: single door to the model for all calls
  (text + vision), key name never printed.
- New `backend/focal.py`: contact-sheet vision (Pillow, up to 8
  thumbs, 512px + id labels), strict per-id JSON, cache at
  `data/focal/<photo_id>.json` (git-ignored), centre fallback
  with confidence 0 + trace note below 0.3 or on failure.
- Upload hook: `run_upload_job` computes focal after done, in its
  own try/except so it can never flip the job to error.
- New `backend/test_focal.py` (17 checks, no model) and
  `scripts/focal_check.py <photo_id> [...]` (live probe).
- Docs: `api_contract.md` + `screen_data_map.md` gain a
  step-1 section (no endpoint or screen changes yet).
- `backend/annotate.py`, `backend/place_pass.py` untouched.
- Commit id: (this commit; see `git log`).

## Modal switchboard, step 1: llm.py primary/fallback (user-run green)

- `backend/llm.py` rewritten: `ask()` returns text + metadata,
  primary from PARSER_* (live .env re-read, no restart), Baseten
  fallback, one retry on error/timeout/empty, 8000-token floor
  except purpose "simple", annotate-style image data URLs,
  Modal-Routing-Affinity-Key only for modal hosts with a session.
- `focal.py`, `test_focal.py`, `focal_check.py` moved to the new
  signature (sheets via `data/cache/focal_sheets/`).
- New `backend/test_llm.py` (21 checks, stubbed client, no net).
- `.gitignore` gains `data/cache/`, `data/llm_calls.jsonl`.
- Tests: `test_llm.py` 21/21, `test_focal.py` 17/17 here; live
  focal probe returned real JSON (confidence 0.82).
- Commit id: (this commit; see `git log`).

## Modal switchboard, step 2: image probe (user-run green)

- `probe_images()` in `llm.py`: tiny generated PNG + one-word
  question; transport success = accepts. Cached at
  `data/cache/llm_caps.json`; lazy on first image use; ignores
  FORCE_PRIMARY_FAIL and the budget; never raises.
- Image calls skip a rejecting primary, straight to fallback.
- New `POST /api/llm/probe` (names/hosts/models + caps, no keys).
- Tests: `test_llm.py` 28/28; live probe: Modal
  meta-models/Muse-Spark-Open-816B-A42B accepts images.
- Commit id: (this commit; see `git log`).

## Modal switchboard, step 3: status (user-run green)

- `llm.status()`: provider names/hosts/models, avg seconds +
  success rate over the last 50 calls, tokens today, budget
  left, last error, image capability. No model calls, no keys.
- New `GET /api/llm/status` (always available, never gated).
- Tests: `test_llm.py` 35/35; live status showed the Modal
  primary, 2008 probe tokens today, images handled by modal.
- Commit id: (this commit; see `git log`).

## Modal switchboard, step 4: budget + rate limits (user-run green)

- Visitor = IP + `rw_visitor` cookie (minted when missing);
  6/min + 60/day per visitor, x4 with the demo code, live-read,
  none when DEMO_MODE is false. Budget (real tokens) checked
  first. Chat answers kind `resting` (stream: one result event);
  ask/compare/explain/story/probe answer 429. Reads untouched.
- New `backend/test_guard.py` (11 checks, fake requests).
- Tests: `test_guard.py` 11/11; live 7 rapid chats gave 6 ok
  then resting.
- Commit id: (this commit; see `git log`).

## Repair: api.py whitespace damage + LF normalization (committed)

- The step-4 commit rewrote `backend/api.py` with a blank line
  after every line (a PowerShell whole-file write). Python ran
  it fine, but the diff was noise. Restored the file from the
  step-3 commit and re-applied the identical guard wiring with
  single-line edits (+127/-9, verified same behaviour).
- Normalized `backend/api.py` and `backend/chat.py` to LF
  (byte-exact, `git diff -w` clean) and added `.gitattributes`
  (`*.py text eol=lf`) so it never recurs. Lesson: never
  whole-file writes from PowerShell; bytes or the edit tool.
- Commit id: (this commit; see `git log`).
