# ReelWorld

A conversational visual knowledge network: describe a photo, refine the
search, and ask evidence-backed questions about what it shows.

Built for the Meta Global AI Developer Hackathon (Indie track).

## Status
Working app. Everything except the photo collection below was built during the hackathon
(Oct 26 - Nov 4, 2026).

## Pre-event preparation
The 132-photo world collection of Kenyan photos (openly licensed, Wikimedia Commons, see `data/manifest.csv`)
and its download script were prepared before the event. Everything else
in this repo — the annotations, search, chat, stories, and all code — is new work from the event.

## How it works
Reel answers from stored photo records, never from memory: each photo
has a structured annotation (caption, things, signs, place verdict).
Chat parses your message into a search spec, searches Supabase
(pgvector) plus a local embedding index, and — when you ask about a
visual condition such as mist — re-checks the top candidates by
looking at the photos again. Every reply carries a trace ("How I
found this") and per-photo verdicts. Stories are directed films built
only from the same records. See `docs/api_contract.md` and
`docs/screen_data_map.md` for the full map.

Honest limits: Reel says when it is unsure (Candidate places, Partial
signs, "unsure" verdicts) and when it finds nothing. It never
identifies people; the owner's name is used only on photos the owner
tagged. Subject outlines (SAM) and non-English UI are not in this
build (see `docs/deferred.md`).

## Demo mode
`DEMO_MODE=true` (default) serves the sample library and gates every
write — upload, delete, correction, profile, owner tags, stories,
publish, chat clearing — behind the `DEMO_CODE` value, sent as the
`X-Demo-Code` header. The UI has a code field and keeps the code in
`sessionStorage` only. Set `DEMO_MODE=false` for a fully open local
library.

## Model providers and limits

All chat reasoning flows through `backend/llm.py`: a primary provider
(Modal) with automatic fallback (Baseten) on any error, timeout or
empty answer. Upload annotation stays on Baseten. Settings live in
`.env` (names only here) and are re-read live, so toggles apply
without a restart:

| Setting | Default |
|---|---|
| `PARSER_BASE_URL`, `PARSER_KEY_ENV`, `PARSER_MODEL` | (required) primary endpoint, key-var name, model |
| `MODAL_API_KEY` | (required) the primary key; never printed or logged |
| `FALLBACK_BASE_URL`, `FALLBACK_KEY_ENV`, `FALLBACK_MODEL` | Baseten endpoint, `BASETEN_API_KEY`, `meta-models/muse-spark-open-1026` |
| `LLM_TIMEOUT_SECONDS` | `90` |
| `DAILY_TOKEN_BUDGET` | `3000000` (real tokens, reset at midnight Africa/Nairobi) |
| `REQUESTS_PER_MINUTE`, `REQUESTS_PER_DAY` | `6`, `60` per visitor when `DEMO_MODE=true` (demo code quadruples); no limits when false |
| `FORCE_PRIMARY_FAIL` | `false` (testing only: force the fallback to answer) |

When limited, chat answers kind `resting` and other model endpoints
answer 429; browse, place pages, credits, the tour and Connected keep
working. `GET /api/llm/status` shows providers, speeds, tokens used,
budget left and image routing; `POST /api/llm/probe` re-tests whether
the primary accepts images.

## Where the Meta models run
- Chat, answers, compare, explain, story scripts: Muse Spark Open,
  primary on Modal (`PARSER_*`), automatic fallback on Baseten
  (`FALLBACK_*`, default `meta-models/muse-spark-open-1026`).
- Photo annotation (`backend/annotate.py`, `backend/place_pass.py`):
  Baseten only.
- Studio narration voice: Kokoro TTS on Modal (`modal/tts.py`, see
  `docs/studio_voice.md`) with browser-voice fallback.

## Data sources and credits
World photos: Wikimedia Commons contributors, per-photo credits in
`data/manifest.csv` and on every world photo in the UI (`/api/credits`,
Credits page). Personal photos are the owner's private sample library,
never served publicly in demo mode.

## Run it (fresh clone)

```powershell
git clone https://github.com/Tonnymwaniki/reelworld.git
cd reelworld
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env: SUPABASE_URL, SUPABASE_SERVICE_KEY, MODAL_API_KEY,
# PARSER_BASE_URL, PARSER_MODEL, BASETEN_API_KEY, DEMO_CODE.
# Then create the tables (run backend/schema.sql, schema_v2.sql,
# schema_v3.sql, schema_v4.sql in Supabase) and load the data:
python backend\retrieval.py build
python backend\load_supabase.py
python -m uvicorn backend.api:app --reload
```

Then open http://127.0.0.1:8000 in a browser. Without keys the
server still starts; model features answer with a calm error message
until `.env` is configured.