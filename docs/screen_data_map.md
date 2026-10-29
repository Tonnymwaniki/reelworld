# Screen → data map

Every Stitch screen element, its endpoint, and the exact fields that feed
it. Base URL `http://127.0.0.1:8000`. See `api_contract.md` for shapes.

## 1. Home and search

| Element | Endpoint | Fields |
|---|---|---|
| Chat bar | `POST /chat` `{session_id, message}` | send `message`; read `text`, `kind` |
| Filter chips | `POST /chat` → `spec` | `viewpoints`, `max_people`, `collection`, `must_include`, `avoid_terms`; removing one sends the spec minus that filter to `POST /api/search` `{session_id, spec}` |
| Results grid | `POST /chat` / `POST /api/search` → `results[]` | `photo_id`, `file` → `/photos/…` URL, `caption`, `reasons`, `score` |
| Card "why it matched" line | same row | `reasons` joined with " · " |
| "How I found this" (under results, collapsed) | `POST /chat` / `POST /api/search` → `trace[]` | `step` (plain label) + `detail` verbatim, in order |
| Compare toggle (each card) | local selection, max 2 (third replaces oldest) | `photo_id` per card |
| Compare panel | `POST /api/compare` `{photo_a, photo_b}` | side-by-side `src` + `caption`, `answer`, `differences[]` (`aspect`, `a`, `b`); Close clears selection |
| Photographer line on card | same row | `credit.author`, `credit.license` (null for personal photos) |
| Card place name | same row | `place` text links to `#/place/<place_key>` when `place_key` is set |
| Empty (no search yet) | — | static suggestions; no call |
| `no_strong_match` | `kind` + `text` | show `text` verbatim above the closest-match grid, plus the "Add the first one" card; its button opens `#/add` and the `spec.query` is remembered for the note field |
| `need_focus` / `not_found` | `kind` + `text` | show `text` verbatim, no grid |
| Loading | — | spinner + "Searching…"; replies take 15–40s |
| Error | HTTP status | `{"detail"}` message verbatim |

## 2. Photo detail (`GET /api/photo/{photo_id}`)

| Element | Fields |
|---|---|
| Photo | `src` (fallback: map `file`) |
| Caption | `caption`, `description` |
| Things seen | `things[]`: `label`, `attributes`, `salience`, `confidence` |
| Signs | `signs[]`: `text` (exact), `legibility`, `confidence`, `where`; empty list → "No signs read" |
| Place + status + evidence | `place.name` (links to `#/place/<key>` when `key` is set), `place.status` (Confirmed/Candidate), `place.evidence[]` (`kind`, `detail`), `place.confidence`; null → "Place unknown" |
| Taken from | `taken_from` (same shape) or hide when null |
| Landmarks | `landmarks[]`: `name`, `status`, `evidence[]` |
| Uncertainties | `uncertainties[]` or "None recorded" |
| Credit line | `credit.author`, `credit.license`, `credit.source_url` (link), `credit.title`; null → hide |
| Scene line | `scene.type`, `scene.time_of_day`, `scene.setting`, `viewpoint`, `people_count` |
| Suggested questions (3) | `suggested_questions[]`; tapping one calls Ask with it |
| Find in the world (personal only) | `POST /chat` "Show me photos in the world like {photo_id}" |
| Compare with mine (world only) | `POST /chat` "Show me photos in my photos like {photo_id}" |
| Another angle | `POST /chat` "Show me another angle of {photo_id}"; `kind: no_other_angle` → show `text` |
| More like this | `POST /chat` "Show me photos like {photo_id}" |
| Ask about this photo | `POST /api/ask` `{photo_id, question}` → `answer`; `source: image` → show `note` ("looked at the photo again"); `trace[]` under the answer (collapsed) |
| Not this one | `POST /chat` "not this one" (rejects focus, re-searches) |
| Loading / error | skeleton panel; `{"detail"}` verbatim; 404 → "I could not find that photo." |

## 3. Add a photo and "Where is this?"

| Element | Endpoint | Fields |
|---|---|---|
| Upload picker | `POST /api/upload` | multipart field `photo` (JPEG/PNG ≤ 10 MB) + `note` (200 chars max, prefilled from a remembered no-match search when present); or raw bytes with `Content-Type: image/*`. Immediate 202: `job_id`, `status`, `stage` |
| Stage progress | `GET /api/jobs/{job_id}` polled | `stage` (`uploaded` → `looking` → `placing` → `connecting` → `done`), `stage_index`/`stage_count`, `elapsed_seconds`, `eta_seconds`; `status: error` → `error` + failed `stage` |
| Result place | done `result.identify` | `primary` (`name`, `status`, `confidence`, `evidence`) |
| Other possibilities | done `result.identify` | `candidates[]` (`name`, `confidence`, `evidence`), up to 3 |
| Connected world photos | done `result.bridge.groups` | `same_place[]`, `another_angle[]`, `taken_from_here[]`, `similar_look[]` (labelled "Looks similar"); item `src`, `caption`, `reason_text`; `place` links to `#/place/<place_key>` |
| Result photo panel | done `result.photo` | full `/api/photo` shape |
| Standalone verdict | `GET /api/identify/{photo_id}` | same `primary`/`candidates`/`nearest_world_photos` for any existing photo |
| Loading / empty / error | job states | `queued` → "Uploaded, waiting…"; `error` → message + retry (re-upload); identify `primary: null` → "Place unknown" |

## 4. Connected

| Element | Endpoint | Fields |
|---|---|---|
| Summary line | `GET /api/connected` → `summary` | `photos_connected`, `places_connected`, `matches_total` (place-based links only, never similar_look), e.g. "9 of your photos connect to 6 places" |
| User photo rows | `photos[]` → `photo` | `photo_id`, `src`, `caption` |
| Grouped world matches | `photos[]` → `groups` | `same_place`, `another_angle`, `taken_from_here` only (no `similar_look`); item `src`, `caption`, `reason_text`, `score`; `place` links to `#/place/<place_key>`; `?limit=` (default 2, max 8) per group |
| Match count | `photos[]` | `match_count` (place-based matches, pre-limit) |
| Loading | first build takes seconds | skeleton rows; later reads are cached (`updated_at` tells staleness) |
| Empty | `count: 0` or all `match_count: 0` | "Upload a photo to see what it connects to" |
| Error | HTTP status | `{"detail"}` verbatim |

## 5. Place (`#/place/<key>`)

| Element | Endpoint | Fields |
|---|---|---|
| Title, type, aliases, breadcrumbs | `GET /api/place/<key>` | `name`, `type`, `aliases`, `hierarchy[]` (`key`, `name`) |
| Photo count | same | `total_photos`; "Only one photo of this place so far." when 1; empty state when 0 |
| World / World+mine toggle | same + `?collection=` | `world` default; `personal` adds the user's photos |
| Viewpoint groups | same → `by_viewpoint` | group per viewpoint with `photo_id`, `src`, `caption`, `collection`; cards open the dossier |
| Signs | same → `signs[]` | `text` + `photos` count (clear legibility only) |
| Photographers | same → `credits[]` | `author`, `license` (linked to `source_url`) |
| Related places | same → `related[]` | `name` × `photos`, links to `#/place/<key>` |
| Loading / error | skeleton blocks while waiting; error panel + Retry button on failure |
