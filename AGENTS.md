# ReelWorld: project guide for coding agents

ReelWorld is a conversational visual knowledge network for photos. Users describe
a photo in plain language, refine the search ("not this one, from a higher angle"),
ask evidence-backed questions about a photo, and connect their own photos to a
world collection of Kenyan photos. Built solo for the Meta Global AI Developer
Hackathon (Indie track). Environment: Windows, PowerShell, Python 3.14.

## What already exists (do not rewrite; build on it)

- `data/photos/world/<theme>/*.jpg` and `data/photos/personal/*.jpg` (git-ignored)
- `data/annotations/<collection>/<photo_id>.json`: structured records (Pass A observed
  layer, Pass B places and landmarks). Schema: `docs/annotation_schema.md`.
- `backend/annotate.py` (Pass A, Muse Spark Open via Baseten) and
  `backend/place_pass.py` (Pass B). Finished; leave them alone.
- `backend/retrieval.py`: local index, `search`, `like` and the scoring helpers.
- Supabase (Postgres + pgvector): table `photos` (see `backend/schema.sql`) and the
  functions `match_photos` and `search_photos` (`backend/schema_v2.sql`).
  146 photos are loaded (132 world, 14 personal).
- `backend/chat.py`: class `Engine` with `turn(message)` returning
  `{"text": str, "results": [rows]}`. It keeps conversation state (current spec,
  focus photo, rejected ids). It also has a terminal loop in `main()`.

## The product (what the app must show)

The assistant is named **Reel**. English only. Navigation: Reel, Browse,
Connected, Stories, About. "Built with Muse Spark Open" is prominent in the
header of every page. Designs in `frontend/design/stitch_export_final/` are
authoritative; wire them exactly, only adding behaviour and data.

1. **Reel** (`#/`): landing hero, then a chat thread — user bubbles, assistant
   replies with photo blocks, "why it matched" lines, action chips, suggested
   follow-ups, filter chips, context pill, "How I found this" trace, honest
   message states, compare mode, in-thread add-photo flow, live SSE progress,
   60-second tour, Credits, About, "Flag this".
2. **Photo detail** (`#/photo/<id>`): evidence panel (caption, things, signs
   with Clear/Partial, place Confirmed/Candidate + evidence, uncertainties,
   credit, suggested questions, Ask, bridge buttons, place link) plus the
   attribution kit sheet.
3. **Connected** (`#/connected`): places overview, SVG ring diagram, link
   evidence, explain-a-connection, phone fallback rows.
4. **Stories** (`#/stories`, `#/showcase`): story engine, player, review,
   WebM export, publish flow with faces-blocking, Showcase (no likes/comments).
5. **My Photos** (`#/library`): smart albums, upload queue, bursts, correction,
   real deletion, data export. **World** (`#/browse` + `#/place/<key>`):
   filtered browse, place pages, gaps, "Add the first photo".

Honest wording matters: when the engine says it found no other view of a
place, show that message, never pad results. Never invent data; unbackable
design elements go to `docs/deferred.md`, never the UI.

## Demo mode

`DEMO_MODE=true` (default, in `.env`) shows the sample library and disables
upload, delete, correction and publish unless the request carries header
`X-Demo-Code` matching `DEMO_CODE` in `.env` (403 + clear message otherwise).
The UI offers a code field and keeps the code in `sessionStorage` only.
`DEMO_MODE=false` enables everything (the local real library). Same data
either way; the flag gates writes, not reads.

## Owner names (no face recognition, ever)

Stories and answers may call the owner by name in their own photos, but
names come ONLY from what the owner tells us — the system must never
work out who someone is from their face, and must never name anyone
other than the owner. `data/profile.json` (git-ignored, local) holds
`{name, refer_as, created_at, updated_at}` via `backend/owner_profile.py`
and `GET/PUT/DELETE /api/profile` (writes demo-gated). A photo counts
as "owner is in it" only when the owner has tagged it so (owner tags,
next). The public demo has no profile and shows no name.

## Model providers and limits (settings live in `.env`, names only here)

All reasoning goes through `backend/llm.py`. The primary provider answers;
on any error, timeout or empty answer the call retries once on the
fallback. Settings are re-read live (process env, then `.env`), so
toggles apply without a restart. Upload annotation stays on Baseten
(`backend/annotate.py`, untouched); SAM outlines (`backend/sam.py`)
use a separate API and are outside the switchboard.

| Setting | Default | Meaning |
|---|---|---|
| `PARSER_BASE_URL` | (required) | Primary reasoning endpoint (Modal) |
| `PARSER_KEY_ENV` | (required) | Name of the env var holding the primary key |
| `PARSER_MODEL` | (required) | Primary model name |
| `MODAL_API_KEY` | (required) | The primary key itself; never printed or logged |
| `FALLBACK_BASE_URL` | `https://inference.baseten.co/v1` | Fallback endpoint |
| `FALLBACK_KEY_ENV` | `BASETEN_API_KEY` | Name of the fallback key var |
| `FALLBACK_MODEL` | `meta-models/muse-spark-open-1026` | Fallback model name |
| `LLM_TIMEOUT_SECONDS` | `90` | Per-attempt model timeout |
| `DAILY_TOKEN_BUDGET` | `3000000` | Prompt + completion tokens per day, real usage, reset at midnight Africa/Nairobi |
| `REQUESTS_PER_MINUTE` | `6` | Per-visitor expensive requests per minute (`DEMO_MODE=true` only) |
| `REQUESTS_PER_DAY` | `60` | Per-visitor expensive requests per day (`DEMO_MODE=true` only) |
| `FORCE_PRIMARY_FAIL` | `false` | Testing only: `true` forces every primary attempt to fail so the fallback answers |

Visitors are IP + `rw_visitor` cookie; a valid demo code quadruples the
rate limits. When limited, chat answers kind `resting` with a calm
message, other model endpoints answer 429; everything model-free
(browse, place pages, credits, tour, Connected) keeps working.
Ask/compare/explain answers are cached 24h in `data/cache/llm/`
(keyed by photo ids + question + record hashes); hits show
"answered earlier" and skip the budget. Calls are logged to
`data/llm_calls.jsonl` (git-ignored); `GET /api/llm/status` shows
providers, speeds, tokens, budget and image routing.

## Build plan (phases; commit after each)

See `docs/build_plan.md` (screen→route→endpoint map) and `docs/build_log.md`
(per-phase log; read both on session restart and continue at the first
unfinished phase). After each phase: start the server, test for real (API
calls + page load), show the output, commit. Do not ask unless truly blocked.

0. Foundation: plan/deferred docs, AGENTS.md, merged tokens, shared shell
   (header, nav, footer, routing, error/404), demo handling, og/meta tags.
1. Reel home: thread UI, SSE progress, compare, in-thread add, tour, credits,
   about, flag.
2. Photo detail: evidence panel + attribution kit.
3. Connected rings + explain.
4. Story engine + player + publish + Showcase.
5. Libraries: albums, queue, bursts, correction, deletion, export, world
   browse/filters/gaps.
6. Polish + full acceptance pass.

## Rules

- Never print, log, commit or hard-code secrets. Keys live in `.env` only
  (`BASETEN_API_KEY`, `META_API_KEY`, `MODAL_API_KEY`, `SUPABASE_URL`,
  `SUPABASE_SERVICE_KEY`). The frontend must never see a key. `.env` and
  `data/photos`, `data/index`, `data/annotations/personal`,
  `data/annotations/raw`, `data/cache`, `data/llm_calls.jsonl` stay
  git-ignored.
- Do not identify people in photos. Personal photos are private by default.
- Do not change the annotation schema or the existing scripts without asking.
- Ask before installing a new package; prefer what is already used
  (`openai`, `supabase`, `fastembed`, `numpy`, `python-dotenv`).
- Use PowerShell-compatible commands in any instructions you give.
- Keep code simple and readable; short comments where the reason is not obvious.
- After each step: run it, tell me how to test it, and suggest a commit message.
  Commit often. This is a hackathon repo, so the git history must show the work
  built during the event.

## Commands

- Terminal chat: `python backend\chat.py`
- Rebuild local index: `python backend\retrieval.py build`
- Reload Supabase: `python backend\load_supabase.py`
- Planned: `uvicorn backend.api:app --reload` then open http://127.0.0.1:8000
