# ReelWorld API contract

Base URL (local): `http://127.0.0.1:8000`. All JSON bodies are UTF-8.
Errors use the FastAPI envelope: `{"detail": "<message>"}` with the status
below. Photo files: `/chat` results carry a stored `file` path like
`data/photos/world/cbd/cbd_001.jpg`; clients map it to a URL by replacing
the `data/photos/` prefix with `/photos/`. The `/api/*` endpoints already
return that mapped URL as `src`.

## `GET /`

Serves `frontend/index.html`.

- 200 `text/html`
- 503 `{detail}` when the page file is missing

## `GET /health`

Liveness check. Touches neither the model nor the database.

- 200: `{"status": "ok"}`

## `POST /chat`

One conversation turn. `session_id` selects the in-memory conversation
(spec, focus photo, rejected ids); sessions are created on first use and
forgotten on server restart.

Request:

```json
{ "session_id": "demo", "message": "a busy street market with vegetables" }
```

- `session_id`: string, default `"default"`, blank becomes `"default"`
- `message`: non-empty string. `"open N"` focuses result N of the last reply.

Response:

```json
{
  "session_id": "demo",
  "text": "Here is what I found:",
  "results": [
    {
      "photo_id": "market_005",
      "collection": "world",
      "file": "data/photos/world/market/market_005.jpg",
      "caption": "…",
      "viewpoint": "ground_level",
      "similarity": 0.71,
      "score": 0.83,
      "reasons": ["meaning 0.71", "matches: market, vegetables"],
      "credit": {"author": "…", "license": "CC BY-SA 4.0",
                 "source_url": "…", "title": "…"}
    }
  ],
  "focus_photo_id": "market_005",
  "spec": {
    "query": "busy street market with vegetables",
    "collection": "world",
    "viewpoints": [],
    "max_people": null,
    "must_include": ["vegetables"],
    "avoid_terms": []
  },
  "kind": "ok"
}
```

- `kind` styles the reply: `ok`, `no_strong_match` (nothing clearly shows
  a required word), `no_other_angle` (no true other view exists),
  `need_focus` (search or open a photo first), `not_found` (named photo
  id does not exist), `question_answer` (answer about the focus photo).
- `results` rows also carry stored metadata columns (`place_key`,
  `place_name`, `taken_from_key`, `landmark_keys`, …). `embedding` and
  `lex` are never sent. `credit` is the world's `{author, license,
  source_url, title}` and null for personal photos.
- `text` is shown to the user verbatim.

- 422 invalid body, 503 engine unavailable, 502 search failed

## `POST /api/search`

Runs a search spec directly with **no language-model call**. Honours the
session's rejected ids and stores the spec in the session, exactly as if
`/chat` had parsed it. Powers instant filter-chip removal: send the spec
minus the chip.

Request:

```json
{
  "session_id": "demo",
  "spec": {"query": "busy street market", "collection": "world",
           "viewpoints": ["elevated"], "max_people": null,
           "must_include": ["vegetables"], "avoid_terms": ["cars"]}
}
```

Missing keys fall back to empty (`""` / `"world"` / `[]` / null);
unknown keys are ignored. `query` must be non-empty, `collection` one
of `world`, `personal`, `both`, `viewpoints` from `ground_level`,
`elevated`, `aerial`, `interior`, `water_level`, `max_people` null or
>= 0, word lists holding strings (lowercased on the way in).

Response: the same shape as `/chat` (`session_id`, `text`, `results`
with credit, `focus_photo_id`, `spec`, `kind`, where `kind` is `ok` or
`no_strong_match`).

- 400 invalid spec, 422 invalid body, 503 engine unavailable, 502 failed

## `POST /sessions/{session_id}/reset`

Forgets one conversation. Next `/chat` call with that id starts fresh.

- 200: `{"session_id": "demo", "reset": true}`

## `GET /api/photos?collection=&limit=`

Photo grid listing, ordered by `photo_id`.

- `collection`: `world` (default) or `personal`
- `limit`: integer, default 24, clamped to 1–200

Response:

```json
{
  "collection": "world",
  "count": 24,
  "photos": [
    {
      "photo_id": "cbd_001",
      "collection": "world",
      "src": "/photos/world/cbd/cbd_001.jpg",
      "caption": "…",
      "viewpoint": "elevated",
      "place": "Nairobi CBD"
    }
  ]
}
```

- 400 unknown collection, 502 list failed

## `GET /api/photo/{photo_id}`

Stable evidence-panel shape for one photo.

Response:

```json
{
  "photo_id": "street_024",
  "collection": "world",
  "file": "data/photos/world/street/street_024.jpg",
  "src": "/photos/world/street/street_024.jpg",
  "caption": "…",
  "description": "…",
  "viewpoint": "ground_level",
  "scene": {"type": "street", "time_of_day": "daytime", "setting": "outdoor"},
  "people_count": 9,
  "things": [
    {"label": "…", "attributes": ["…"], "salience": 5, "confidence": 0.97}
  ],
  "signs": [
    {"text": "MID YEAR SALE", "legibility": "clear", "confidence": 0.94,
     "where": "on a red and yellow billboard on the left"}
  ],
  "place": {"name": "Nairobi", "key": "kenya/nairobi", "status": "candidate",
            "evidence": [{"kind": "…", "detail": "…"}], "confidence": 0.85},
  "taken_from": null,
  "landmarks": [
    {"name": "…", "status": "confirmed", "evidence": [{"kind": "…", "detail": "…"}]}
  ],
  "uncertainties": ["…"],
  "credit": {"author": "…", "license": "CC BY-SA 4.0", "source_url": "…", "title": "…"},
  "suggested_questions": ["What does the sign say?", "Where was this taken?",
                          "What is happening here?"]
}
```

- `file` is the stored path; `src` is the ready `/photos/…` URL.
- `things` keeps the top 8 by salience. `place`/`taken_from` are null
  when unknown. `credit` is null for personal photos.
- `suggested_questions` is built in code (no model call): "What does
  the sign say?" with signs, "Where was this taken?" with a place,
  "What is happening here?" always, "How many people are visible?"
  with people — first three win.
- Empty lists mean "none recorded", stated plainly by the UI.

- 404 `{"detail": "I could not find that photo."}`, 502 lookup failed

## `POST /api/ask`

Answers one question about one photo. First tries the stored annotation;
when it cannot answer, re-inspects the actual photo file with the vision
model (same provider and model as annotation) and says so.

Request:

```json
{ "photo_id": "street_024", "question": "what does the sign say?",
  "session_id": "demo" }
```

`photo_id` and `question` are required non-empty strings; `session_id`
is accepted and currently unused.

Response:

```json
{ "photo_id": "street_024", "question": "…",
  "answer": "…", "source": "annotation", "note": null }
```

- `source` is `annotation`, or `image` when the answer came from
  re-reading the photo — then `note` reads "This answer came from
  looking at the photo again."
- Image answers stay under 120 words and never identify people.

- 422 invalid body, 404 unknown photo, 502 answer/look failed

## `GET /photos/{path}`

Raw photo bytes, e.g. `/photos/world/market/market_001.jpg`.

- 200 `image/jpeg` (or png), 404 when the file is missing

## `POST /api/upload` (new)

Accepts one photo and annotates it in the background as a personal photo.
Primary form is `multipart/form-data` with fields:

- `photo`: image file, required. JPEG or PNG, at most 10 MB.
- `owner_note`: text, optional. Stored in `data/personal_manifest.csv` and
  used by Pass B as the owner's note (a hint, never proof on its own).

Fallback (no extra package needed): POST the raw image bytes as the body
with `Content-Type: image/jpeg` (or `image/png`) and an optional
`?owner_note=` query parameter.

Response is immediate; the work continues in the job:

- 202: `{ "job_id": "9f2c…", "status": "queued", "stage": "uploaded" }`
- 400 missing/empty file, unsupported type, unreadable image
- 413 body larger than 10 MB
- 501 multipart used but `python-multipart` is not installed
  (`pip install python-multipart` enables it; raw-byte upload works without it)

The job runs, in order: Pass A (`annotate.py`, unchanged) → Pass B
(`place_pass.py`, unchanged; registry may gain new place keys) → embedding
with the shared model → upsert into Supabase table `photos` with
`collection: "personal"`. It also writes
`data/photos/personal/<photo_id>.<ext>`,
`data/annotations/personal/<photo_id>.json`, and the raw model outputs
under `data/annotations/raw/`. `photo_id` is the next free
`personal_NNN`. The local `data/index` is not rebuilt; run
`python backend\retrieval.py build` if the offline index must include it.

## `GET /api/jobs/{job_id}`

Status of an upload job, driving the stage-by-stage progress display.

Response:

```json
{
  "job_id": "9f2c…",
  "status": "running",
  "stage": "placing",
  "stage_index": 2,
  "stage_count": 5,
  "photo_id": "personal_015",
  "error": null,
  "created_at": "2026-10-28T15:01:02+00:00",
  "updated_at": "2026-10-28T15:02:40+00:00",
  "elapsed_seconds": 98.0,
  "eta_seconds": 210.5,
  "result": null
}
```

- `status`: `queued`, `running`, `done`, `error`.
- `stage` runs `uploaded` → `looking` (Pass A sees the photo) →
  `placing` (Pass B places it) → `connecting` (embedding, storing,
  bridge refresh) → `done`. On `error`, `stage` is where it failed.
- `stage_index` is 0-based into those 5 stages; `stage_count` is 5.
- `elapsed_seconds` runs live until the job ends, then freezes.
  `eta_seconds` averages completed jobs (default 60) and is 0 once
  terminal.
- `photo_id` is set at accept time. When `status` is `done`, `result`
  holds `{photo, identify, bridge}`: the `/api/photo` shape, the
  `/api/identify` shape, and the task-5 bridge groups (limit 4).

Jobs live in server memory and are lost on restart.

- 404 unknown job id

## `GET /api/bridge/{photo_id}?limit=`

Matching photos from the *other* collection, grouped by why they match
(personal → world is "find in the world"; world → personal backs
"compare with mine"). Candidates are ranked look-first with the same
shared scoring as chat's related photos, then grouped. This is the only
endpoint that returns `similar_look` matches (labelled "Looks similar").

- `limit`: integer per group, default 4, clamped to 1–8

Response:

```json
{
  "photo_id": "personal_006",
  "collection": "personal",
  "other_collection": "world",
  "labels": {"same_place": "Same place", "another_angle": "Another angle",
             "taken_from_here": "Taken from here", "similar_look": "Looks similar"},
  "groups": {
    "same_place": [
      {"photo_id": "cbd_018", "collection": "world",
       "file": "data/photos/…", "src": "/photos/…", "caption": "…",
       "viewpoint": "ground_level", "place": "Nairobi CBD",
       "similarity": 0.75, "score": 1.21,
       "reasons": ["same place: kenya/nairobi/cbd"],
       "reason_text": "same place: kenya/nairobi/cbd",
       "credit": {"author": "…", "license": "…", "source_url": "…", "title": "…"}}
    ],
    "another_angle": [],
    "taken_from_here": [],
    "similar_look": []
  }
}
```

- All four group keys are always present (possibly empty): `same_place`
  (same subject, same viewpoint), `another_angle` (same subject from a
  different viewpoint), `taken_from_here` (shows the spot the photo was
  taken from), `similar_look` (everything else, best look-alike first).
- Each item is a standard result row (`credit` included) plus
  `reason_text`, the human reasons joined for the "why it matched" line.

- 404 unknown photo id, same message as `/api/photo/{photo_id}`
- 502 bridge search failed

## `GET /api/connected?limit=`

For every personal photo, its grouped world matches, plus a summary.
Only real place-based links count here: `same_place`, `another_angle`
and `taken_from_here`. `similar_look` matches are never returned by
this endpoint and never counted (they appear only in `/api/bridge`,
which backs the photo detail view).
Served from an in-memory cache that is built on first request and
rebuilt after each upload job finishes (also lost on restart, like
jobs; no new database tables).

- `limit`: matches per group, default 2, clamped to 1–8

Response:

```json
{
  "updated_at": "2026-10-28T15:20:00+00:00",
  "count": 14,
  "summary": {"photos_connected": 14, "places_connected": 31, "matches_total": 840},
  "photos": [
    {
      "photo": {"photo_id": "personal_002",
                "src": "/photos/personal/personal_002.jpg", "caption": "…"},
      "groups": {"same_place": ["<same item shape as /api/bridge>"],
                 "another_angle": [], "taken_from_here": []},
      "match_count": 12
    }
  ]
}
```

- `match_count` counts place-based matches before `limit` slicing; the
  summary is computed over those totals, so it never shifts with
  `limit`. `photos_connected` counts personal photos with at least one
  place-based link.
- `places_connected` counts distinct matched place keys among
  place-based matches only.

- 502 connected index failed (first build only; cached reads never touch the DB)

## `GET /api/identify/{photo_id}`

The "Where is this?" verdict for any existing photo, derived from the
stored place, place candidates and landmark data. No model call is made.

Response:

```json
{
  "photo_id": "personal_006",
  "primary": {"name": "CBK Pension Towers",
              "key": "kenya/nairobi/cbd/cbk-pension-towers",
              "status": "confirmed",
              "evidence": [{"kind": "…", "detail": "…"}],
              "confidence": 0.97},
  "candidates": [
    {"name": "…", "key": "…", "confidence": 0.6,
     "evidence": [{"kind": "…", "detail": "…"}]}
  ],
  "nearest_world_photos": [
    {"photo_id": "cbd_003", "src": "/photos/…",
     "caption": "…", "place": "CBK Pension Towers"}
  ]
}
```

- `primary` is the stored place verdict, or null when unknown.
- `candidates` holds up to 3 place candidates (landmarks fill in when
  no candidates were recorded).
- `nearest_world_photos` holds up to 5 world photos: same-place matches
  when the place key is known, else the closest stored-embedding
  neighbours (still no model call).

- 404 unknown photo id, same message as `/api/photo/{photo_id}`
- 502 lookup/search failed
