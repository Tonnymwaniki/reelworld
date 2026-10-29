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

Two sections in one app:
1. **My Photos**: the user's phone photos, searchable in plain language, private.
2. **World**: the Kenyan photo collection.
3. **The bridge**: on any photo, "Find in the world" and "Another angle"; on a world
   photo, "Compare with mine". One search box works across both; results are grouped
   "From you" and "From the world".

Every photo opens a detail view with an **evidence panel**: caption, what was seen
(entities), signs read (exact text and how legible), place and landmark with their
status (confirmed or candidate), and a list of uncertainties. Honest wording matters:
when the engine says it found no other view of a place, show that message, never
pad results.

## Build plan (small steps; stop and show me after each)

1. `backend/api.py`: FastAPI app wrapping `Engine`. Share the heavy parts (embedding
   model, clients) across sessions but keep conversation state per `session_id`.
   Endpoints: `POST /chat`, `GET /health`, `POST /sessions/{session_id}/reset`,
   `GET /api/photos?collection=&limit=`, `GET /api/photo/{photo_id}`
   (record summary for the evidence panel), `POST /api/ask`.
   Serve photos from `data/photos` at `/photos/...`.
2. `frontend/index.html`: one responsive page (vanilla JS and CSS, no build step,
   mobile first). Tabs World / My Photos, a chat-style search bar, a photo grid, a
   photo detail view with the evidence panel and the bridge buttons.
3. Polish for the demo video: loading states, empty states, a clean visual style
   inspired by Kenyan colours but restrained, keyboard and touch friendly.

## Rules

- Never print, log, commit or hard-code secrets. Keys live in `.env` only
  (`BASETEN_API_KEY`, `META_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`).
  The frontend must never see a key. `.env` and `data/photos`, `data/index`,
  `data/annotations/personal`, `data/annotations/raw` stay git-ignored.
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
