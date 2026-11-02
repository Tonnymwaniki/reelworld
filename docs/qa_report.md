# ReelWorld QA report (pre-submission, static review)

Date: 2026-11-02. Method: read-only static review by six reviewers; no server
started, no browser run, no secrets opened. Every verdict below cites an
inspected file body. Live proof still needed — see Appendix A.

Verdicts: `PASS` = checked, no fix needed. `OPEN` = needs a fix (with
severity + suggested fix). `FIXED` = fixed in the QA pass on 2026-11-02
(each cites the code or test). Extra fixes outside the numbered items:
usage guards in `scripts/cost_check.py`, `scripts/refresh_probe.py`,
`scripts/script_check.py`, and `data-broken` guards on every remaining
frontend `img` site (see F2).

## Counts (recounted after the QA pass; first verdict per item head)

| Section | PASS | FIXED | OPEN | Notes |
|---|---|---|---|---|
| 1 secrets-privacy | 7 | 3 | 1 | |
| 2 endpoints | 13 | 9 | 11 | 68 routes + `/photos` mount |
| 3 demo-abuse | 14 | 1 | 4 | 2 dups with §2 (outline FIXED, stories-bypass open) |
| 4 safety | 10 | 1 | 7 | 1 dup with §1 (reasoning fallback FIXED) |
| 5 honesty | 6 | 4 | 2 | |
| 6 frontend flows | 8 | 2 | 1 | code-reading only, no browser |
| 7 failure modes | 4 | 1 | 3 | |
| 8 submission readiness | 3 | 3 | 4 | |
| Total | 65 | 24 | 33 | 122 heads; ~3 dups across sections |

---

## 1 Secrets and privacy

- 1a tracked tree clean — PASS. `git ls-files` contains none of the 17
  private paths (`.env`, `data/photos`, `data/index`,
  `data/annotations/personal`, `data/annotations/raw`, `data/chats`,
  `data/stories`, `data/profile.json`, `data/personal_manifest.csv`,
  `data/llm_calls.jsonl`, `data/cache`, `data/focal`,
  `data/attributes/personal_*`, `data/face`, `data/outlines`, `data/audio`,
  `*.zip`); `data/attributes/*` holds only world ids
  (`cbd/hills/landmarks/market/park/street`).
- 1b history secrets clean — PASS. No secret value in history: `sb_secret`
  zero commits; `service_role` hit `13358bb` is a placeholder doc at
  `backend/load_supabase.py:9`; `Bearer` hits are Bearer-plus-key-from-env at
  `scripts/key_test.py:38` (never prints, `scripts/key_test.py:8,27`);
  `BASETEN`/`META_API`/`DEMO_CODE` hits are env names / `os.getenv` / test
  code (`backend/test_guard.py:50`); `wk-`/`ws-` hits are design binaries;
  `password` hits are `input type=password` (`frontend/index.html:239`);
  `.env` never committed.
- 1b history privates clean — PASS. `git log --` all private paths is empty;
  `rev-list` over 1617 objects has zero `jpg/jpeg/webp/zip/.env/chats/stories/
  cache/face/audio/focal/outlines` blobs; zero deleted images; `selfie -S`
  hits `238572b`/`6ae828a` are code-only.
- 1c gitignore — PASS. `check-ignore -v` maps each private to
  `.gitignore:1,5,6,7,8,10,12,14,15,16,17,18,19,20,21,22,24`; `.env` present,
  untracked, ignored.
- 1c `.env.example` — FIXED. `.env.example` added with all 30 setting
  names and empty values only (no values); covers providers, budgets,
  rate limits, flags, studio voice and test switches.
- 1d llm status/probe — PASS. `backend/api.py:297-302` via
  `backend/llm.py:314-355` and `backend/api.py:277-294` return provider
  names/hosts/models/speeds only; docstrings state no keys; host-only helpers
  `backend/llm.py:86-97`.
- 1d frontend config — PASS. `backend/api.py:469-475` returns demo booleans /
  counts / `evaluation=None` (missing `docs/evaluation.md`), never
  `DEMO_CODE`/keys; frontend is keyless (`frontend/app.js:1-2`), demo code in
  `sessionStorage` only (`frontend/app.js:8870-8871`) sent as `X-Demo-Code`
  (`frontend/app.js:20-28`), password field `frontend/index.html:239`.
- 1d key handling — PASS. Keys only via `os.environ`/`os.getenv`
  (`backend/api.py:188,306,2116`, `backend/chat.py:423`,
  `backend/llm.py:415`, `backend/sam.py:26`), compared never returned; no
  `api_key=` literal; no key logging; llm log rows key-free
  (`backend/llm.py:226-234`); `DROP_KEYS` strips embedding/lex
  (`backend/api.py:104,151-152`).
- 1d reasoning fallback — FIXED. `_extract_text` (`backend/llm.py`)
  never reads `reasoning_content`: a reasoning-only reply is empty, so
  the fallback/retry engages; new test asserts a reasoning-only reply
  yields `""` (`backend/test_llm.py`).
- 1d personal serving — OPEN (medium). `backend/api.py:228` mounts `/photos`
  with no guard (dir `backend/api.py:72`); `/api/photos` and `/api/photo`
  serve `collection=personal` openly (`backend/api.py:1379-1396,1399-1410`);
  `_demo_guard` covers writes only
  (`backend/api.py:492,502,559,624,644,2198,3118,3189,3696,3762,3781`).
  Matches reads-open design but conflicts with private-by-default. Fix: guard
  the personal branch/mount when `DEMO_MODE=false`, or document that the
  demo host carries sample personal data only.
- 1d manifest paths — FIXED. All 132 `file` values rewritten to
  `data/photos/world/<theme>/<base>`, each verified to exist on disk;
  zero absolute paths remain. Consumers already matched basename-only.

## 2 Endpoints (`backend/api.py`, 68 handlers + `/photos` mount)

Core behaviour — PASS (each with file:line):

- 2-P1 inventory — PASS. 68 handlers `backend/api.py:231-3800` + `/photos`
  `StaticFiles` (`backend/api.py:228`); no other route files.
- 2-P2 models — PASS. 25 pydantic models (`ChatRequest:202` …
  `CorrectRequest:3648`); missing/wrong-type → FastAPI 422 unless a manual
  400 runs first.
- 2-P3 codes — PASS. 400 validation, 403 demo-guard (`backend/api.py:431-436`),
  404 not-found, 409 publish-faces (`backend/story_engine.py:195-201`), 413
  upload>10MB (`backend/api.py:2221`), 422 pydantic-auto, 429 guard/budget,
  501 not-configured, 502 downstream, 503 engine/frontend; `{detail}` envelope.
- 2-P4 no global handlers — PASS. No `add_exception_handler` in `backend/`;
  `app=FastAPI(title)` (`backend/api.py:226`), no debug → default 500
  envelope, no traceback leak.
- 2-P5 secrets — PASS. Keys only via `os.environ`/`os.getenv`
  (`backend/api.py:188,2116`, `backend/sam.py:24-29`,
  `backend/studio_voice.py:74-75`); `.env` never opened.
- 2-P6 static/shell — PASS. `GET /` (`backend/api.py:231`) 200/503; app.js /
  story-render.js / styles.css (`backend/api.py:238-259`); `/views/{name}.html`
  allowlist (`backend/api.py:77-79,262-269`) 404/503, no traversal;
  `/health` (`backend/api.py:272`); `/tour/{name}.json` (`backend/api.py:1080`);
  `/og-image.png` (`backend/api.py:695`); `/api/config` (`backend/api.py:469`);
  `/api/llm/status` (`backend/api.py:297`); `POST /api/llm/probe` guarded
  (`backend/api.py:277-294`).
- 2-P7 profile/owner/face core — PASS. `GET/PUT/DELETE /api/profile`
  (`backend/api.py:483-518`, validation `backend/owner_profile.py:25-41`);
  owner-tags + summary (`backend/api.py:553-610`); face-reference get/delete
  (`backend/api.py:634-646`); face-scan (`backend/api.py:649-692`,
  `backend/face_match.py:30-37,167-185`).
- 2-P8 chat/chats core — PASS. `POST /chat` (`backend/api.py:703-788`) and
  `/chat/stream` SSE (`backend/api.py:789-831`); chats CRUD
  (`backend/api.py:844-909`, `backend/chats.py:49-82,147-160`); session reset
  (`backend/api.py:1288`).
- 2-P9 search/related/reject core — PASS. `/api/search`
  (`backend/api.py:1101-1190`); `/api/related` (`backend/api.py:1191-1238`);
  `/api/reject` (`backend/api.py:1239-1287`).
- 2-P10 photos/ask/compare/explain core — PASS. `/api/photos`
  (`backend/api.py:1379-1398`); `/api/photo/{id}` shape
  (`backend/api.py:1399-1469`); ask/compare/explain happy paths
  (`backend/api.py:1472-1610,2853-2930`).
- 2-P11 story/stories/films/audio core — PASS. `/api/story`
  (`backend/api.py:1875-1930`); stories CRUD + publish
  (`backend/api.py:3034-3208`); films (`backend/api.py:3209-3321`,
  `backend/film.py:718-741`); audio (`backend/api.py:3322-3360`,
  `backend/studio_voice.py:41-53,129-140`).
- 2-P12 place/graph core — PASS. place (`backend/api.py:2301-2481`); bridge
  (`backend/api.py:2482-2539`); identify (`backend/api.py:2540-2582`);
  connected/rings/overview/self
  (`backend/api.py:2583-2830`, link facts `backend/api.py:2655-2694`).
- 2-P13 library/credits/flag core — PASS. albums/bursts/world/gaps/correct/
  delete/export (`backend/api.py:3441-3850`); credits/flag
  (`backend/api.py:942-1025`).

Open items (9 fixed in the QA pass; the rest below stay open):

- 2-O1 outline unguarded — FIXED. `POST /api/outline`
  (`backend/api.py:1033-1073`) spends paid Meta SAM calls
  (`backend/sam.py:95-131`) with no `_guard_or_429`; every sibling model
  endpoint is guarded (ask `:1474`, compare `:1559`, explain `:2854`, story
  `:1880`, films `:3218`, audio `:3332`, probe `:283`). Fixed: standard
  pre-guard added plus budget catch; outline is on the contract 429 list.
  Test: outline returns 429 at zero budget (`backend/test_guard.py`).
- 2-O2 stories prompt rate bypass — OPEN (medium, dup with §3). `POST
  /api/stories` prompt path (`backend/api.py:3034-3053`) calls `story()` with
  `request=None`, so `_guard_expensive` checks budget only
  (`backend/api.py:361-366`), skipping rate windows. Fix: pass `request`
  through or pre-guard in `stories_create`.
- 2-O3 refresh no rate guard — FIXED. `POST
  /api/stories/{id}/refresh` (`backend/api.py:3115-3172`) makes LLM calls
  (`_chapter_text:3141`) with `_demo_guard` but no `_guard_or_429`. Fixed:
  standard guard added; refresh is on the contract 429 list. Test: refresh
  returns 429 at zero budget (`backend/test_guard.py`).
- 2-O4 story voice not validated — FIXED. `POST /api/story`
  (`backend/api.py:1881-1888`) never 400s on unknown voice though the
  contract requires it (`docs/api_contract.md:427-428`); `resolve_voice`
  silently falls back (`backend/narration.py:24-30`), while
  `stories_create:3045` and films `:3229` validate. Fixed: `/api/story`
  validates voice like films and returns 400 (`backend/test_routes.py`).
- 2-O5 upload reads body before size check — OPEN (medium, partial fix).
  Raw-byte uploads now pre-check the declared `Content-Length` and refuse
  413 before reading (`backend/api.py:2226-2231`, `backend/test_routes.py`);
  the multipart path (`await up.read()`, `:2222`) still reads before the
  10MB check. Fix: cap the multipart part size.
- 2-O6 face-reference b64 unbounded — OPEN (medium). `image_b64`
  (`backend/api.py:613-614`, `min_length=1`, no max) decoded unbounded in
  `backend/face_match.py:63-71`. Fix: add `max_length` + byte cap in
  `b64_to_bytes` → 400/413.
- 2-O7 unbounded text into LLM — OPEN (low). No `max_length` on
  `ChatRequest.message` (`backend/api.py:204`), ask question (`:1298`),
  compare question (`:1305`), story theme (`:1622`), film prompt (`:3200`),
  outline prompt (`:1030`). Fix: add documented caps (e.g. message 2000,
  question 500, theme/prompt 280) → 400.
- 2-O8 owner-tags list unbounded — OPEN (low). `photo_ids`
  (`backend/api.py:548`) unbounded; sequential DB + re-embed per id
  (`backend/api.py:573-591`). Fix: cap at ~50 → 400.
- 2-O9 explain empty-id — FIXED. `photo_a/b` lack `min_length=1`
  (`backend/api.py:2843-2845`), so `""` → 404 (`backend/api.py:2860`) not
  422, unlike ask/compare (`backend/api.py:1296-1304`). Fixed: both ids
  carry `min_length=1` (`backend/test_routes.py`).
- 2-O10 chat resting-path guard — FIXED. Resting path calls
  `get_engine` outside try (`backend/api.py:706-708,799-800`) → Engine
  failure yields 500 not 503. Fixed: both `/chat` and `/chat/stream`
  resting paths catch engine failure (`backend/test_guard.py`).
- 2-O11 ask `_compact_record` outside try — OPEN (low).
  (`backend/api.py:1483-1485`) → malformed record `KeyError` yields 500;
  compare already guards (`backend/api.py:1572-1579`). Fix: move inside try →
  502.
- 2-O12 `_coerce_embedding` unguarded — FIXED. `json.loads`
  (`backend/api.py:2441-2442`) called from bridge `:2487`, rings `:2722`,
  identify `:2533`, connected `:2559`, self `:2813`, albums `:3457`, films
  `:3284` → 500 on malformed embedding. Fixed: `_coerce_embedding`
  raises 502 on corrupt values (`backend/test_routes.py`).
- 2-O13 photo-id strip inconsistent — FIXED. `_record_or_404` strips
  (`backend/api.py:1548`), as do rings `:2720`, identify `:2542`, correct
  `:3697`, delete `:3763`, but `photo_detail:1404` and `_bridge_src:2423` do
  not. Fixed: both strip now.
- 2-O14 world `?limit=0` — OPEN (low). `GET /api/world`
  (`backend/api.py:3541`, `int(limit or 60)`) returns 60 for `limit=0`, while
  `list_photos:1383` / bridge `:2484` clamp to 1. Fix: clamp 1–200.
- 2-O15 `max_people` bool — FIXED. `clean_spec`
  (`backend/api.py:1117-1119`) accepts `True` as int. Fixed: `clean_spec`
  requires `type(...) is int` (`backend/test_routes.py`).
- 2-O16 chat create title unbounded — FIXED. Create
  (`backend/chats.py:102`) unbounded but rename truncates `[:80]`
  (`backend/api.py:887`). Fixed: create truncates `[:80]`
  (`backend/test_chats.py`).
- 2-O17 file-write `OSError` → 500 — OPEN (low, partial fix). `api_flag`
  now maps `OSError` to 503 with a calm message (`backend/api.py:1034`);
  burst prefs (`burst_cover`) and upload `write_bytes` still map to 500.
  Fix: wrap those two the same way.
- 2-O18 undocumented shapes — OPEN (low). 17 shapes missing from
  `docs/api_contract.md`: credits, flag, outline, rings, places/overview,
  connected/self, bursts, world(full), gaps, photo-correct, DELETE photo,
  DELETE photos/mine, export, albums(full), explain(full), chat/stream
  events, static `/app.js`/`/story-render.js`/`/styles.css`/`/views`/`/tour`.
  Fix: document or move to `docs/deferred.md`.
- 2-O19 contract staleness — OPEN (low). `/api/config` extra keys
  (`backend/api.py:439-475` vs contract `:27-28`); `/api/photos` example
  missing `owner_present`/`place_key` (`backend/api.py:1391-1396` vs
  contract `:326-341`); `/chat` spec missing `owner_only`/`constraints`
  (`backend/api.py:770-772` vs contract `:147-157`); `/api/ask`
  `session_id` passed to `llm.ask` (`backend/api.py:1495`) though contract
  `:602` says unused. Fix: sync the contract.
- 2-O20 minor shape notes — OPEN (low, info). `DELETE /api/photos/mine`
  errors are `str(exception)` (`backend/api.py:3790-3792`); refresh/publish
  `request` has no `None` default (`backend/api.py:3116,3185`);
  `_demo_guard(None)` raises `AttributeError` in `DEMO_MODE`
  (`backend/api.py:311-316`, direct-call only); 404 tone mixed. Fix: tidy
  when touching those handlers; no demo-day action required.

## 3 Demo gating and abuse

- 3a guard helper — PASS. `_demo_unlocked`/`_demo_guard`
  (`backend/api.py:311-316,431-436`); `DEMO_MODE`/`DEMO_CODE` (`:305-306`);
  403 messages (`:435-436`); frontend `sessionStorage` + `X-Demo-Code`
  (`frontend/app.js:20-29`).
- 3a guarded writes — PASS. 11 sites: `PUT/DELETE /api/profile` (`:492,:502`),
  owner-tags (`:559`), face-reference (`:624,:644`), upload (`:2198`),
  refresh (`:3118`), publish (`:3189`), correct (`:3696`), DELETE photo
  (`:3762`), DELETE photos/mine (`:3781`).
- 3a unguarded-by-design writes — PASS. Chats CRUD
  (`backend/api.py:850,876,892,905`, visitor-scoped); flag (`:1007`,
  docstring `:1009-1010` always allowed); stories create/update/delete
  (`:3034,:3099,:3173`, drafts local/private `:3187-3188`); burst cover
  (`:3508`, display pref `:3510`); reset (`:1288`, memory-only); export
  (`:3800`, read `:3802`).
- 3a token-spending guarded — PASS. `/chat` (`:705` + budget catch `:726`),
  `/chat/stream` (`:796,:828`), probe (`:283`), ask (`:1474`), compare
  (`:1559`), story (`:1880`), explain (`:2856`), films (`:3218`), audio
  (`:3332`), outline + refresh (guarded in the QA pass); budget/rate →
  resting/429.
- 3a outline unguarded — FIXED (dup of 2-O1). Guard added, on the
  contract 429 list; see 2-O1.
- 3a upload Pass A+B bypass — OPEN (high). `POST /api/upload`
  (`backend/api.py:2194`) is demo-guarded only; `run_upload_job` Pass A+B
  Baseten calls (`backend/api.py:2112-2136`) bypass rate limit and
  `DAILY_TOKEN_BUDGET` (budget counts `llm_calls.jsonl` only). Fix: count
  upload model calls in the budget and rate-limit the endpoint (or require
  the demo code even when `DEMO_MODE=false` for hosted demos).
- 3a stories/refresh/reject rate gaps — OPEN (medium, dup of 2-O2/2-O3,
  partial fix). Refresh now pre-guards (see 2-O3); stories prompt variant
  still calls `story()` with `request=None` (budget-only) and reject still
  skips pre-guard rate accounting. Fix: thread `request` through both.
- 3a model-free unguarded — PASS. `/api/search verify=False` (`:1166`,
  `backend/chat.py:599-603`), `/api/related` direct tool (`:1216`), face-scan
  local CV (`:649-692`) spend no model tokens, correctly unguarded.
- 3b world-only endpoints — PASS. `/api/world` filters `eq world`
  (`backend/api.py:3544-3546`); credits world (`:952-953`); gaps world
  (`:3640-3641`); identify-nearest world (`:2525-2526`); place defaults world,
  personal only on `?collection=` (`:2308-2331`).
- 3b personal reads allowed — PASS by design. Build plan gates writes not
  reads: `/api/photos?collection=personal` (`:1379-1396`); `/api/photo` any
  id (`:1399-1409`); `/photos` static (`:228`); albums (`:3441`); export
  (`:3800-3810`); search `filter_collection` + `owner_only`
  (`backend/chat.py:444-456,480-482`). In tension with §1 personal-serving;
  needs the documented demo convention.
- 3b raw annotations never served — PASS. Only `/photos` static + fixed files
  + `VIEW_NAMES` whitelist (`backend/api.py:77-79,262-269`); personal credit
  forced `None` (`:170,:1445-1447`); no auth layer matches single-user
  local/demo model.
- 3c rate helper — PASS. `_rate_settings` 6/60 live
  (`backend/api.py:339-351`); `_visitor_id` ip+cookie (`:329-336`);
  `_guard_expensive` budget-first + 4x demo multiplier + sliding windows
  (`:354-393`); `_guard_or_429` → 429 `RESTING_TEXT` (`:396-399`); resting
  payload (`:409-428`); chat 200-resting (`:705-708,:796-801`).
- 3c budget — PASS. `llm.ensure_budget` (`:382-386`), `tokens_today`
  Nairobi-midnight (`:358-379`), `DAILY_TOKEN_BUDGET` default 3000000
  (`:100-110`); ask pre-checks (`:400,:501`); probe ignores budget internally
  (`:172-178`) but the endpoint pre-guards (`:283`).
- 3c zero-budget reads — PASS. Guard/LLM-free: world (`:3537`), place
  (`:2301`), credits (`:942`), tour (`:1080`), connected (`:2583`), overview
  (`:2761`), self (`:2798`), rings (`:2718`), bridge (`:2482`), identify
  (`:2540`), photos/photo (`:1379,:1399`), status (`:297-302`),
  albums/gaps/export; matches contract (`:903-904`).
- 3d traversal — PASS. `/photos` confined (`:228`); views whitelist
  (`:262-269`); tour `TOUR_STEPS` (`:1080-1088`); audio 16-hex validated
  (`backend/studio_voice.py:129-142`) before `FileResponse` (`:3348-3355`);
  stories `ID_RE` (`backend/story_engine.py:19,36-39`); chats charset
  (`backend/chats.py:23-46`) + scope revalidation (`:131-132`).
- 3d pid-derived paths — OPEN (low). `_persist_owner_tag` (`:521-528`),
  correct (`:3705`), delete (`:3748`) rely on DB-404-first with no explicit
  `^[A-Za-z0-9_-]+$` check; outline honors absolute DB file paths
  (`:1061-1066`); upload `request.body()` read before the 413 check
  (`:2214-2221`) allows a large-body memory spike. Fix: add the charset
  check, confine outline paths to `data/photos`, pre-check `Content-Length`.
- 3d upload validation — PASS. `MAX_UPLOAD` 10MB (`:2010`), multipart
  `max_part_size` (`:2202`), 413 (`:2220-2221`), magic-byte JPEG/PNG
  (`:2222-2227`), server-minted id+ext (`:2228`), note truncated (`:2232-2233`).
- 3d sequential story ids — OPEN (high). Story ids `st-YYYYMMDD-NNNN`
  (`backend/story_engine.py:46-54`) live in a global namespace with ungated
  list/read/update/delete (`backend/api.py:3034,3093,3099,3173`), so any demo
  visitor can enumerate/tamper/delete others' drafts (publish gate `:3189`
  only protects Showcase injection). Fix: scope stories to the visitor
  cookie like chats, or require the demo code for story writes on the demo
  host; use unguessable ids for new stories.
- 3d entropy — PASS. Chat ids sequential per-scope (`backend/chats.py:70-82`)
  but isolated by uuid4 visitor secret (`:132,:373`) with cross-scope 404s;
  job ids uuid4 (`:2021`); audio sha1-16 (`backend/studio_voice.py:35-38`);
  visitor cookie uuid4.

## 4 Safety

- 4a publish gate — PASS. `_require_faceless` raises 409
  (`backend/story_engine.py:195-201`); `publish()` re-fetches fresh people
  counts (`:210-213`); `update()` re-checks published stories (`:176-179`);
  wired (`backend/api.py:3190-3194`); UI disables + warns
  (`frontend/app.js:6821-6835`, badges `:6803-6807`).
- 4a Showcase — PASS. Lists `status=published` only
  (`backend/api.py:3081-3090`, `backend/story_engine.py:69-89`,
  `frontend/app.js:7529`); detail `?public=1` (`frontend/app.js:7585`).
- 4a unlisted links — PASS (removed). `frontend/views/builder.html:8`
  draft/published only; copy-link is device-local (`frontend/app.js:7244-7252`
  + text `:7249`, `frontend/views/builder.html:103`).
- 4a story exports — OPEN (low). WebM `recordWebm`
  (`frontend/app.js:7329-7476`) and MD/JSON `downloadFile` (`:7227-7242`)
  have no faces check; mitigated as private on-device downloads
  (`frontend/views/builder.html:78-79`). Fix (optional): warn when
  `chaptersWithPeople` (`frontend/app.js:452-454`) is non-empty.
- 4a photo share card — OPEN (low). Gate is client-side only (`paintShare`
  `:3114-3136`, `share()` re-check `:3330-3333`, local card `:2615+,3342-3354`,
  no server endpoint); devtools bypass is trivial; `/photos` is openly
  served (`backend/api.py:228`), so this is an accidental-share guard, not
  access control. Fix: only if the threat model needs it — add a server
  share endpoint re-checking `observed.people.count`; consider auth for
  `/photos/personal`.
- 4a export zip — PASS (noted, not a violation). Includes faces photos +
  annotations + `profile.json` by design as the owner's own download
  (`backend/api.py:3800-3850`, read not demo-gated `:3802`).
- 4b no-identification net — PASS. Annotate prompt (`backend/annotate.py:62-63`)
  + `identified=False` (`:327`); `ANSWER_PROMPT` (`backend/chat.py:293-299`);
  compare/image prompts (`backend/api.py:1310-1336`); story prompt (`:1637`);
  explain (`:2829`); narration `rules_block` + check/repair
  (`backend/narration.py:72-147`) applied in ask/compare/story/explain.
- 4b face-match scope — PASS. Suggest-confirm-only
  (`backend/face_match.py:1-9`); scan writes nothing
  (`backend/api.py:649-654`, `backend/face_match.py:183-185`); personal-only
  (`backend/api.py:664-667`); owner-tap confirm (`:553-557`); outputs are
  distance/band/faces, no names (`:685-690`).
- 4b EXIF/GPS leak — OPEN (medium). Upload stores raw bytes verbatim
  (`backend/api.py:2222-2230`), served as-is (`:228`); no EXIF strip anywhere
  (only PIL uses: `backend/focal.py:97`, `backend/llm.py:165-169`); export
  ships originals (`backend/api.py:3817`). Fix: re-encode via PIL
  (transpose + save without exif) before writing; backfill existing personal
  originals; document in privacy notes.
- 4c owner-name gating — PASS. Per-photo facts + strict name check +
  sentence-drop repair (`backend/narration.py:33-147`); applied in ask
  (`backend/api.py:1500,1529`), compare (`:1598,1606`), headings
  (`:3004-3009`), explain (`:2903-2910`); voice `backend/narration.py:24-31`.
- 4c public-story redaction gaps — OPEN (low). Core opt-in PASSES
  (`include_name` validated+stored `backend/story_engine.py:205-216`, public
  redaction `backend/api.py:3010-3019`, checkbox
  `frontend/views/builder.html:108-112`); but redaction covers
  title/`brief.about`/headings/texts only, not `brief.feeling`/`avoid` or
  captions, and `GET /api/stories/{id}` without `public=1`
  (`backend/api.py:3093-3096`) returns the unredacted draft with no read
  gate. Fix: extend `public_text` to feeling/avoid/caption; force public
  rendering when `DEMO_MODE` and no demo code.
- 4c demo-mode name reads — OPEN (medium). `GET /api/profile`
  (`backend/api.py:483-487`), `GET /api/face-reference` incl. preview
  (`:634-639`), `POST /api/face-scan` (`:649-692`), owner-tags summary
  (`:597-610`) have no demo/read gate; safety is deployment convention only
  (`backend/owner_profile.py:6-7`, `backend/api.py:485-486`). Frontend tag
  view fetches all three (`frontend/app.js:7949-7961`). Fix: when
  `DEMO_MODE` and the request lacks the demo code, return null/empty for
  profile + face reads (a read mirror of `_demo_guard`).
- 4c deletion partial — OPEN (low). `DELETE /api/profile` clears profile +
  all owner tags + re-embeds (`backend/api.py:500-518`) and tag undo works
  (`:579-580`), but not face reference files (separate `:642-646`), saved
  stories, saved chats, or the LLM cache; photo delete
  (`backend/api.py:3735-3757`) leaves story/chapter refs (tolerated
  `:2972`). Fix: cascade face-reference clearing into profile delete;
  document/warn about (or prune) stories/chats/cache remnants.
- 4d keys — PASS. Server-side env names only (`backend/llm.py:184,415,512`,
  `backend/api.py:188,2116`, `backend/sam.py:24-29,114`); status/probe/config
  return names/hosts/models only
  (`backend/llm.py:314-355`, `backend/api.py:277-303,469-475`); call logs
  exclude keys (`backend/llm.py:195-199,434-444`); frontend keyless
  (`frontend/app.js:1-2,24-29`); `.env` ignored (`.gitignore:1`).
- 4d reasoning — FIXED (dup of §1). `_extract_text` no longer reads
  `reasoning_content`; see §1 1d reasoning fallback.
- 4d story JSON — PASS. Stores title/prompt/tone/chapters/people/include_name
  only (`backend/story_engine.py:147-151,208-217`), no keys/reasoning.
- 4e HTML injection — PASS. All user text via `textContent`/`.value`/
  canvas-`fillText`/Blob-download; ~90 `innerHTML` sinks are `""` clears
  (e.g. `frontend/app.js:942,1280,2921,6794,7590`) or static `SPINNER_SVG`
  (`:2764,2773`) or `dataset.orig` restore (`:2769,2779`) or same-origin
  allowlisted view templates (`loadView` `:7614-7622` + `VIEW_NAMES`
  `backend/api.py:77-79,262-269`, sinks `:7650,7667,8694-8839`);
  story-render `fillText` inherently safe
  (`frontend/story-render.js:265,268,293,310,325-326,343,400,412,414,421`);
  flags write-only (`backend/api.py:1007-1025`); no
  `document.write`/`outerHTML`/`insertAdjacentHTML`.
- 4e href hardening — OPEN (low). `a.href` from record `source_url`
  (`frontend/app.js:3157,3190,3232`) has no `http(s)` validation
  (`dataset.usertext` `:684` is safe). Fix: allowlist `http(s)` + `mailto`,
  else render as text.

## 5 Honesty (wording and numbers)

- H1 Built-with label — PASS. Header pill `frontend/index.html:211` + footer
  pill `:293` persist across hash routes (views mount into `#view`); also
  `frontend/story-render.js:417` and share card
  (`frontend/app.js:2630,2711`). Header pill hides on xs but the footer
  always shows.
- H2 world-photo credits — PASS. `creditText` (`frontend/app.js:191-194`,
  world-only) used in thread (`:1171,:1179`), browse (`:5557`), compare
  (`:1746`), tour (`:2185,2232,2256`), showcase (`:7589`), dossier + kit.
- H3 English-only — PASS. `lang=en` (`frontend/index.html:2`); zero Swahili
  strings in frontend; `docs/deferred.md:14` rule.
- H4 no UI for unbuilt features — PASS. `frontend/views/photo.html:1-5`
  Outlines toggle + voice memo removed; no `/api/outline` fetch in frontend
  (backend-only `backend/api.py:1033` behind the feature flag); no mic UI;
  thread tune button hidden (`frontend/app.js:570`, `docs/deferred.md:15`);
  stories voice is a backed POV choice, not speech.
- H5a invented model claims — FIXED. The two rows now read "Muse Spark
  Open (Modal primary, Baseten fallback) / Chat, answers, stories" and
  "Subject outlines (SAM) — planned, not live yet / Not in this build".
- H5b unmeasured methodology labels — OPEN (medium).
  `frontend/views/about.html:16` `Version 2.4.1`, `:49` `SHA-512 Signed`,
  `:69` `Deterministic Facade Indexing`, `:78` `Zero-Biometric Volumetric
  Alignment`, `:116` `Cryptographic Immutability`, `:135` `Segment Anything
  Powered`, `:154` `Sub-40ms Vector Match`, `:494-528`
  sandboxing/expulsion/redaction; violates `docs/deferred.md:20`
  live-counts-or-nothing. Fix: cut or reword to plain true statements.
- H5c live-inference pulse — FIXED. Label now reads "Annotated with
  Muse Spark Open" (`frontend/views/photo.html`).
- H5d 60-second tour — OPEN (low). `frontend/views/home.html:52,1302` has no
  timer (3 user-paced steps); fallback copy (`:1358` `14 correlated angle
  frames`, `:1390` `28-story octagonal`, `:1445,:1465` plate ids,
  `:1453,:1472,:1548` credits, `:1557` `18m baseline`) shows pre-fetch and
  stays on fetch failure (only `h3` replaced,
  `frontend/app.js:2155-2160`); mitigated — `/tour/step{1,2,3}.json` exist and
  `fillTour1/2/3` overwrite on success. Fix: hide panels until JSON loads;
  rename `Take the tour`.
- H5e credits fallbacks — FIXED. `fail()` now also zeroes the donut
  segments and sets each legend row to "–" (`frontend/app.js`).
- H5f home stats flash — FIXED. The three stat spans default to `–`
  until `fillLanding` paints live numbers.
- H5g template defaults — PASS. Trace overwritten/hidden
  (`frontend/app.js:1265-1288`), OCR callout hidden (`:1467`), compare fully
  overwritten (`:1718-1775`), add-photo fiction overwritten + publish button
  removed (`:1945-2064`), upload timings real (`:1848-1888`). Soft-marketing
  note (not filed): `100% Provenance Recorded` (`home.html:444`), `zero
  generative synthesis` (`:765`), 404 cadastre copy
  (`frontend/views/404.html:188-194`).
- H6 verdicts/counts/messages — PASS. `verdictMark` yes/no/unsure
  (`frontend/app.js:316-336`) matches `check{verdict,reason}`
  (`backend/chat.py:569`, `backend/router.py:676-680`); `reinspected` step
  (`backend/api.py:1537`) gates the banner (`frontend/app.js:1444-1448`);
  counts via `/api/config` (`backend/api.py:469-475`); honest
  `no_other_angle` (`frontend/app.js:125`); sign Clear/Partial
  (`:2950-2962`), place Confirmed/Candidate (`:2969-2994`).

## 6 Frontend flows (code reading; no browser run)

- F1 Reel thread — PASS. SSE (`frontend/app.js:765-809`), chip drop
  (`:1241-1246`), suggestions, trace, copy/flag/retry (`:1583-1611`),
  history arrows, `Cmd+K` (`:8850`); compare (`:1635-1782`, needs 2);
  in-thread add (`:1834-1943`, demo hint `:1913`); tour (`:2083-2266`); flag
  dialog (`:1784-1828`).
- F2 photo detail — PASS. All buttons wired (`frontend/app.js:2800-2850`);
  img `src` + broken fallback (`:2900-2902`, `frontend/styles.css:67-69`,
  extended in the QA pass to every remaining `img` site: thread thumbs,
  ring nodes/rows, strips, burst main, review rows, tag review, picker);
  kit hrefs (`:3157,:3232`); place link (`:3026-3028`); ask / another-angle /
  upload incl. honest `no_other_angle`.
- F3 upload `#/add` — PASS. Phase tabs incl. Inspection View
  (`frontend/app.js:3545-3546,3626-3643`); dropzone/drag/pick/snap; type +
  10MB guard (`:3646-3649`); stepper/poll/result/bridge/footer.
- F4 Connected — PASS. Tabs/refresh/search/captures/places/self/rings/rows/
  evidence/explain/back/run (`frontend/app.js:3971-4028`); mobile ring-rows
  fallback (`frontend/views/connected.html:102,119`).
- F5 stories/builder/showcase — PASS. Create pills/make/grid/del
  (`frontend/app.js:6458-6489`); builder tabs/review/player/export/direct/
  WebM/publish faces-blocking (`:6656,:6672,:6685,:6690,:6835`); narration
  `/api/audio` (`:6154,:7293`); showcase modal + Esc + credits
  (`:7497-7602`).
- F6 library/browse/place/about/credits/404 — PASS. Library
  (`frontend/app.js:4719-4799`, export `GET backend/api.py:3800`); browse
  filters/surprise/gaps (`:5463-5517`); place (`:5721-5739`); about
  fill+purge (`:2498-2528`); credits (`:2306-2371`); router + 404
  (`:8682-8846`, `show404 :7663-7677`).
- F7 dead link — FIXED. Breadcrumb now points at `#/`.
- F8 image src vs routes — PASS. `/photos` StaticFiles
  (`backend/api.py:228`) + `srcOf` (`frontend/app.js:40-45`) + `public_src`
  (`backend/api.py:193-199`); `/views` (`:262`); `/tour` (`:1080`, files on
  disk); `/og-image.png` (`:695`, file on disk); 6/6 hardcoded `EX_*.jpg`
  verified on disk.
- F9 undefined CSS vars — FIXED. Added 16 `:root` `--color-*` aliases
  mapping to the defined archival tokens (two with no exact counterpart
  map to the closest token: `--on-primary`, `--on-secondary-container`).
- F10 390px layout — PASS mostly. Bottom nav (`frontend/index.html:254`),
  off-canvas chats + scrim (`frontend/styles.css:121-141`), ring-rows
  fallback, tables in `overflow-x-auto`, padded tour modal; browse
  `grid-cols-2` is tight (~170px cards) but usable.
- F11 keyboard/reduced-motion — OPEN (low, core passes). Passes:
  `focus-visible` (`frontend/styles.css:60-65`), reduced-motion kill
  (`:112-117,:238-240`), native dialog Esc, showcase Esc
  (`frontend/app.js:7509`), arrows, `Cmd+K` (`:8850`). Gap: tour overlay +
  chats sidebar lack Esc close and focus trap; tour dots are 12px
  (supplementary; tabs/prev/next are 44px). Fix: add Esc + trap to both.

## 7 Failure modes

- FM1 primary-provider fails — PASS. `backend/llm.py:405-439` fallback retry
  once, empty-answer retry (`:424-425`); trace discloses `native with the
  fallback provider` (`backend/router.py:1044-1046`); tests
  (`backend/test_llm.py:112-118,128-133`).
- FM2 both-providers-fail chat — PASS. `ask_tools` never raises, returns
  malformed (`backend/llm.py:504-551`); `_json_fallback` catches → calm `I
  couldn't work out what to do with that. Try rephrasing.`
  (`backend/router.py:963-971`, `kind=chat`).
- FM2b both-fail direct endpoints — OPEN (medium). `/api/ask|compare|explain`
  + chat-fallback raise 502 echoing raw exception text
  (`backend/api.py:1499,1583,2900,729`, e.g. `search failed:
  RuntimeError: model call failed on both providers: ...`). Fix: log the
  raw error server-side, return a calm public message + `trace.provider`
  detail only.
- FM3a missing keys — FIXED. `PARSER_KEY` now uses `os.environ.get(..., "")`
  (`backend/chat.py:96`; the value is write-only, no reader), so `uvicorn
  backend.api` starts without keys and model features fail calmly later.
  Keys documented in README + `.env.example`. Test: subprocess imports
  `chat` with all key vars stripped (`backend/test_parser_env.py`).
- FM3b missing photo bytes — PASS. `load_bytes` None
  (`backend/chat.py:550-555`) → `unsure`/`photo unavailable`
  (`backend/attributes.py:669-672`, `:334-337`); outlines 502 `photo file is
  missing on disk` (`backend/api.py:1066`).
- FM3c missing local index — OPEN (low, CLI-only). `load_index` unguarded
  (`backend/retrieval.py:143-146`, `FileNotFoundError` traceback);
  like-unknown-id exits cleanly (`:295`); server path uses Supabase, not the
  local index. Fix: catch and print `run: python backend/retrieval.py build`.
- FM4 empty results — PASS. `Nothing matches all of that. Try dropping a
  detail.` (`backend/chat.py:712-718`, `owner_only` variant `:713-715`);
  honest no-other-angle note, never pads (`:763-770`); `/api/search`
  `kind=no_strong_match` (`backend/api.py:1171-1175`).
- FM5 timeouts — OPEN (medium). `LLM_TIMEOUT_SECONDS` default 90
  (`backend/llm.py:109`) passed per-attempt (`:116,:457`); exactly one
  fallback attempt, no backoff; worst case per `ask()` is 2×90s and
  multi-call turns can hang minutes before the calm message; SAM 120s
  (`backend/sam.py:95,116`); studio voice 180s
  (`backend/studio_voice.py:61-65`); Supabase client has no explicit timeout.
  Fix: lower per-attempt timeout for chat (e.g. 30s), add one short backoff,
  stream progress over SSE so the wait is visible; set a Supabase timeout.

## 8 Submission readiness

- 8.1 README identity — PASS core + count FIXED. What + hackathon
  (`README.md:1-6`) and the pre-event photo-collection note (`:12-15`) are
  explicit — PASS; `100-photo` updated to the real 132-photo world count
  with a manifest pointer — FIXED.
- 8.2 README setup — FIXED (live trial still the owner's step, see 8.10).
  README now has a copy-paste block: venv, `pip install -r
  requirements.txt`, copy `.env.example`, schema + load, run — plus the
  keyless-start guarantee from the FM3a fix.
- 8.3 README gaps — FIXED. Added how-it-works + honest limits,
  `DEMO_MODE`/`X-Demo-Code` gating, where-each-model-runs (SAM outlines,
  studio voice), and data-sources/credits sections.
- 8.4 README models — PASS core + OPEN (low). Modal primary + Baseten
  fallback + `meta-models/muse-spark-open-1026` (`README.md:19-33`) matches
  `backend/llm.py:38-42` — PASS; but no checked-in Modal Muse-Spark deploy
  file (`modal/` holds only `tts.py`) — OPEN (low). Fix: check in the deploy
  file or say where it lives.
- 8.5 README `.env` claim — FIXED. README now documents the behaviour
  default and points at `.env.example`, which lists every key.
- 8.6 evaluation — OPEN (low). `docs/evaluation.md` does not exist
  (`Test-Path` False); `backend/evaluate.py:1-16,34` writes it only after
  hand-labelling; `data/eval/queries.json` exists. No evaluation numbers to
  cite; `/api/config` returns `evaluation=None`. Fix: run the eval or drop
  eval claims from the submission.
- 8.7 dependencies — OPEN (medium, was high; partial fix).
  `requirements.txt` added (14 packages incl. `python-multipart`,
  `opencv-python-headless`, `httpx`) but unpinned — versions were not
  observable from the sandbox. Fix: owner runs `pip freeze` and pins.
- 8.8 repo size — OPEN (medium, owner decision). `data/photos` ignored
  (`.gitignore:5`) — fine; `frontend/design` confirmed tracked: 102 files,
  35.7MB of stitch exports (`git ls-files`). They are the in-repo style
  reference per `AGENTS.md`, so not removed unilaterally. Fix: owner
  decides — keep, LFS, or untrack keeping one screenshot.
- 8.9 private paths — PASS. `.gitignore` covers `.env:1`, `data/photos:5`,
  personal+raw annotations `:6-7`, index `:8`, flags/manifest/stories/chats/
  audio/face/cache `:9-22`; `.env` present in the worktree and ignored. Live
  `git status --ignored` still unverified.
- 8.10 run command — OPEN (medium, unverified). `README` command matches
  `backend/api.py:27-28`, `sys.path` insert (`:46`) makes `import chat` work,
  `frontend/index.html` is committed so `/` serves, default uvicorn address
  matches; no `backend/__init__.py` (namespace import expected ok); but
  `python` was not on one sandbox `PATH`, so execution was never observed.
  Fix: run Appendix A on the owner machine and paste the output into the
  submission checklist.

## Top-3 worries after the QA pass (for the submission)

1. A judge's fresh clone is still unproven. `requirements.txt` (unpinned),
   `.env.example`, the README setup block and the keyless-start fix are in,
   but nobody has run a fresh clone end to end (§8.10). Fix order: pin
   versions → run Appendix A on a clean machine → paste the output.
2. The public demo can still be abused for money. Outline is now guarded,
   but upload Pass A+B still bypasses the budget (§3 — high) and global
   sequential story ids still let any visitor rewrite others' drafts (§3 —
   high). Fix order: budget upload calls → scope stories to visitors.
3. Trust and privacy gaps are still visible on demo day. Personal bytes,
   profile name, and face preview read without the demo code (§1/§4 —
   medium); uploads keep EXIF/GPS (§4 — medium); `about.html` still carries
   unmeasured labels (§5 H5b — medium). Fixed since the draft: invented
   model rows (§5 H5a), CSS aliases (§6 F9). Fix order: read-guards → EXIF
   strip → H5b honesty pass.

## Appendix A — PowerShell live verification (deduplicated, not yet run)

Run from the repo root on the owner machine. Replace `<id>` placeholders
with real ids and `<paste-demo-code>` with the demo code from `.env`
(never commit or paste the value elsewhere).

```powershell
# A0. Prereqs + start (one terminal stays on the server)
Test-Path .env.example; Test-Path .env; Test-Path docs/evaluation.md
git check-ignore -v .env data/photos/world/x.jpg data/index/x data/annotations/personal/p.json data/annotations/raw/r.json data/chats/a.json data/stories/s.json data/profile.json data/personal_manifest.csv data/llm_calls.jsonl data/cache/c.json data/focal/f.json data/attributes/personal_001.json data/face/f.json data/outlines/o.json data/audio/a.wav test.zip
python -m uvicorn backend.api:app --reload
```

```powershell
# A1. Base handles + health/config/static/secrets-absence
$B='http://127.0.0.1:8000'; $J=@{'Content-Type'='application/json'}
Invoke-RestMethod $B/health
(Invoke-RestMethod $B/api/llm/status | ConvertTo-Json -Depth 6) | Select-String -Pattern 'reasoning|api[_-]?key|bearer' -AllMatches  # expect no matches
Invoke-RestMethod $B/api/config | ConvertTo-Json -Depth 4
Invoke-WebRequest $B/ -UseBasicParsing | Select-Object StatusCode
Invoke-WebRequest $B/views/home.html -UseBasicParsing | Select-Object StatusCode
Invoke-WebRequest $B/photos/world/market/market_018.jpg -UseBasicParsing | Select-Object StatusCode
Invoke-RestMethod $B/tour/step1.json | Select-Object prompt
Select-String -Path frontend/app.js -Pattern 'reasoning_content|BASETEN_API_KEY|META_API_KEY|SUPABASE_SERVICE_KEY' -AllMatches  # expect no matches
Select-String -Path frontend/app.js -Pattern 'innerHTML\s*=' -AllMatches | Select-Object LineNumber,Line  # every hit must be ''-clear, SPINNER_SVG, dataset.orig, or loadView template
```

```powershell
# A2. Demo gating: 403 without code, OK with code
try { Invoke-RestMethod -Method Put -Uri $B/api/profile -Headers $J -Body '{"name":"Ama"}' } catch { $_.Exception.Response.StatusCode.value__; $_.ErrorDetails.Message }
try { Invoke-RestMethod -Method Post -Uri $B/api/upload -ContentType 'image/jpeg' -Body ([byte[]](1,2,3)) } catch { $_.Exception.Response.StatusCode.value__ }
$H=@{'X-Demo-Code'='<paste-demo-code>'}
Invoke-RestMethod -Method Put -Uri $B/api/profile -Headers ($J+$H) -Body '{"name":"Ama"}'
```

```powershell
# A3. Personal-read exposure (run WITHOUT the demo code; any personal bytes = §1/§4 findings live)
Invoke-RestMethod "$B/api/photos?collection=personal&limit=1"
Invoke-WebRequest "$B/photos/personal/personal_001.jpg" -Method Head -UseBasicParsing | Select-Object StatusCode
Invoke-RestMethod $B/api/profile
(Invoke-RestMethod $B/api/face-reference).present
Get-ChildItem data/chats -Recurse -Filter *.json | Select-String 'reasoning' | Select-Object -First 5
```

```powershell
# A4. Chat/search/related/reject + validation codes
Invoke-RestMethod -Method Post -Uri $B/chat -Headers $J -Body '{"session_id":"qa","message":"busy street market"}'
try { Invoke-RestMethod -Method Post -Uri $B/chat -Headers $J -Body '{"session_id":"qa"}' } catch { $_.Exception.Response.StatusCode.value__ }  # 422
Invoke-RestMethod -Method Post -Uri $B/api/search -Headers $J -Body '{"session_id":"qa","spec":{"query":"market","collection":"world"}}'
try { Invoke-RestMethod -Method Post -Uri $B/api/search -Headers $J -Body '{"spec":{"query":"","collection":"mars"}}' } catch { $_.Exception.Response.StatusCode.value__ }  # 400
Invoke-RestMethod -Method Post -Uri $B/api/related -Headers $J -Body '{"photo_id":"<id>","mode":"similar"}'
try { Invoke-RestMethod -Method Post -Uri $B/api/related -Headers $J -Body '{"photo_id":"<id>","mode":"sideways"}' } catch { $_.Exception.Response.StatusCode.value__ }  # 400
```

```powershell
# A5. Photos/place/graph reads
Invoke-RestMethod "$B/api/photos?collection=world&limit=2"; Invoke-RestMethod $B/api/photo/<id>
try { Invoke-RestMethod $B/api/photo/nope_999 } catch { $_.Exception.Response.StatusCode.value__ }  # 404
Invoke-RestMethod $B/api/place/kenya/nairobi; Invoke-RestMethod "$B/api/bridge/<id>?limit=1"; Invoke-RestMethod $B/api/identify/<id>
Invoke-RestMethod "$B/api/connected?limit=1"; Invoke-RestMethod $B/api/rings/<id>
Invoke-RestMethod $B/api/albums; Invoke-RestMethod "$B/api/world?limit=2"
Invoke-RestMethod "$B/api/world?limit=0" | Select-Object total,limit  # want clamp, not 60
Invoke-RestMethod $B/api/gaps; Invoke-RestMethod $B/api/credits; Invoke-RestMethod $B/api/places/overview; Invoke-RestMethod "$B/api/connected/self?limit=2"
```

```powershell
# A6. Model endpoints (guarded) + known-gap probes
Invoke-RestMethod -Method Post -Uri $B/api/ask -Headers $J -Body '{"photo_id":"<id>","question":"What does the sign say?"}'
Invoke-RestMethod -Method Post -Uri $B/api/compare -Headers $J -Body '{"photo_a":"<id1>","photo_b":"<id2>"}'
try { Invoke-RestMethod -Method Post -Uri $B/api/compare -Headers $J -Body '{"photo_a":"<id>","photo_b":"<id>"}' } catch { $_.Exception.Response.StatusCode.value__ }  # 400
Invoke-RestMethod -Method Post -Uri $B/api/explain -Headers $J -Body '{"photo_a":"<id1>","photo_b":"<id2>"}'
try { Invoke-RestMethod -Method Post -Uri $B/api/explain -Headers $J -Body '{"photo_a":"","photo_b":"<id>"}' } catch { $_.Exception.Response.StatusCode.value__ }  # want 422, currently 404
Invoke-RestMethod -Method Post -Uri $B/api/story -Headers $J -Body '{"theme":"markets","voice":"garbage"}'  # want 400, currently 200
try { Invoke-RestMethod -Method Post -Uri $B/api/outline -Headers $J -Body '{"photo_id":"<id>"}' } catch { $_.Exception.Response.StatusCode.value__ }  # 501 when disabled; guard gap needs a rate test with demo code
Invoke-RestMethod -Method Post -Uri $B/api/films -Headers $J -Body '{"photo_ids":["<id1>","<id2>"],"target":"short"}'
try { Invoke-RestMethod -Method Post -Uri $B/api/films -Headers $J -Body '{"photo_ids":["<id>"],"style":"noir"}' } catch { $_.Exception.Response.StatusCode.value__ }  # 400
Invoke-RestMethod -Method Post -Uri $B/api/audio -Headers $J -Body '{"text":"Hello Nairobi"}'
try { Invoke-RestMethod -Method Post -Uri $B/api/audio -Headers $J -Body '{"text":""}' } catch { $_.Exception.Response.StatusCode.value__ }  # 400
```

```powershell
# A7. Stories publish faces-block + showcase (creates a draft = write; needs a faces photo id + demo code)
$body = @{ title='faces-probe'; photo_ids=@('PERSONAL_FACES'); target='short' } | ConvertTo-Json
$st = Invoke-RestMethod -Method Post -Uri $B/api/stories -ContentType 'application/json' -Body $body
$st.faces_blocked
try { Invoke-RestMethod -Method Post -Uri ($B+"/api/stories/"+$st.story.id+"/publish") -ContentType 'application/json' -Body '{"include_name":false}' -Headers @{'X-Demo-Code'='<paste-demo-code>'} } catch { $_.Exception.Response.StatusCode.value__; ($_ | Out-String) }  # expect 409 + 'Faces are never published'
(Invoke-RestMethod "$B/api/stories?status=published").stories | Select-Object id,status
try { Invoke-RestMethod $B/api/jobs/deadbeef } catch { $_.Exception.Response.StatusCode.value__ }  # 404
Invoke-RestMethod -Method Post -Uri $B/api/flag -Headers $J -Body '{"target":"<id>","reason":"other"}'
try { Invoke-RestMethod -Method Post -Uri $B/api/flag -Headers $J -Body '{"target":"<id>","reason":"bogus"}' } catch { $_.Exception.Response.StatusCode.value__ }  # 400
```

```powershell
# A8. EXIF round-trip (needs exiftool + an uploaded id served at /photos)
Invoke-WebRequest -Uri $B/photos/personal/PERSONAL_WITH_GPS.jpg -OutFile $env:TEMP/rw_exif.jpg
exiftool -GPSPosition -Model -DateTimeOriginal "$env:TEMP/rw_exif.jpg"  # any GPS tags = §4 EXIF finding confirmed live
```

```powershell
# A9. Manual browser pass at 390px (not runnable headless): every route, tour open/Esc, compare select-2, in-thread add, ring-rows fallback, keyboard-only run, prefers-reduced-motion run.
```

## Gaps and limits

- No live server or browser was run by any reviewer; all dynamic claims
  (status codes, SSE events, rate-limit/resting replies, 403/409/413 paths,
  file streaming, audio playback, WebM recording, model failover, Supabase
  shapes, upload pipeline, OpenCV bands) need Appendix A on the owner
  machine. Prior unresolved carried forward: endpoints live behaviour,
  model outputs, Supabase shapes, upload end-to-end, face paths; safety
  dynamic proof + `docs/evaluation.md` future policy + demo-host
  `data/profile.json` / `data/face/*` presence; honesty/frontend runtime,
  SSE pacing, audio quality, `ENABLE_SWAHILI`, `100% Provenance` data audit;
  failure-docs git-tracked size, live behaviours, per-blob MB, namespace
  import on Python 3.14.
- No secret value was read or is cited in this report; only env-var names,
  placeholders, and code references appear.
