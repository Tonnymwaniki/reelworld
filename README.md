# ReelWorld

A conversational visual knowledge network: describe a photo, refine the
search, and ask evidence-backed questions about what it shows.

Built for the Meta Global AI Developer Hackathon (Indie track).

## Status
Project scaffold only. All features are built during the hackathon
(Oct 26 - Nov 4, 2026).

## Pre-event preparation
The 100-photo Kenyan photo collection (openly licensed, Wikimedia Commons)
and its download script were prepared before the event. Everything else
in this repo is new work.

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

## Run it

```powershell
python -m uvicorn backend.api:app --reload
```

Then open http://127.0.0.1:8000 in a browser.