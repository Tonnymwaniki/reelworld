# Screen → data map

Every Stitch screen element, its endpoint, and the exact fields that feed
it. Base URL `http://127.0.0.1:8000`. See `api_contract.md` for shapes.

## 0. Shell (every page)

| Element | Endpoint | Fields |
|---|---|---|
| Header label + nav | static | "Built with Muse Spark Open" pill; Reel, Browse, Connected, Stories, About |
| API status pill | `GET /api/config` | reachable → "API: Online", else "API: unreachable" (never a fake latency) |
| Demo banner + code field | `GET /api/config` → `demo_mode` | shown only when true; code kept in `sessionStorage`, sent as `X-Demo-Code` |
| 404 card | `GET /api/config` → `counts.world` | requested path verbatim; "Public Cadastre (N photos)" with the real N |
| Error card | live | real error message verbatim, retry re-runs the failed route, live API check |

## 1. Home and search

| Element | Endpoint | Fields |
|---|---|---|
| Chat bar | `POST /chat` `{session_id, message}` | send `message`; read `text`, `kind` |
| Filter chips | `POST /chat` → `spec` | `viewpoints`, `max_people`, `collection`, `must_include`, `avoid_terms`, `owner_only` ("Photos of me"); removing one sends the spec minus that filter to `POST /api/search` `{session_id, spec}` |
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
| `need_tags` (zero tagged photos) | `kind` + `text` | show `text` verbatim, no grid, plus a "Tag your photos" button linking `#/profile/tag`; "Photos of me" chip stays |
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
| Share this finding | local canvas card, no endpoint | 1080×1350 PNG: `src` photo, `place.name` + Confirmed/Candidate badge, first 2 `place.evidence[]`, world `credit` line, ReelWorld + "Built with Muse Spark Open"; Web Share API when available, else PNG download; personal photos disabled + "private" note until explicit confirm, never when `people_count` > 0 |
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

## 6. Story (`#/story`)

| Element | Endpoint | Fields |
|---|---|---|
| Theme input + collection toggle | `POST /api/story` `{theme, collection}` | send `theme` + `world`/`personal`/`both`; read `title`, `intro` |
| Progress | — | spinner + "Writing your story..." + live elapsed seconds |
| Chapters | `chapters[]` | `heading`, `photos[]` (`src`, `caption`, link to `#/photo/<photo_id>`), `text` verbatim |
| Photographers | `credits[]` | `author`, `license` (linked to `source_url`) |
| Share this story | local canvas card, no endpoint | 1080×1350 PNG reusing the photo-card builder: cover photo, title, chapter list, credit line; Web Share API when available, else download |
| Trace | `trace[]` | `planned` / `searched` / `rewrote` / `dropped` / `written` + `detail`, collapsed |
| Empty / error | no chapters → honest line + trace; HTTP status → `{"detail"}` verbatim + retry |

## 7. Story engine v2 (directed film; step 1: no screen changes)

Step 1 is backend-only (focal cache + background compute). No story
screen gains or loses any element yet: the focal point, safe crop
and mood surface in the player/exporter from step 7 on, and
"why this shot" in the review screen from step 10 on.

## 8. Story player + WebM export (step 7: one canvas renderer)

| Element | Source | Behaviour |
|---|---|---|
| Player frame | `StoryRender.renderFrame` on a 540×960 canvas | smart 9:16 crop, focal camera moves, transitions, found-text cards, lower-third captions, "From the world" tags, burst stop-motion, end card with credits |
| Play / pause / prev / next / replay / scene strip | player chrome in `app.js` | unchanged controls; scene strip thumbnails from `scene.src` |
| WebM export | same `renderFrame` at 1080×1920, 30 fps | `canvas.captureStream` + MediaRecorder (vp9 → vp8 → webm); status names resolution, size, seconds; 720×1280 fallback when the benchmark is slow |
| Reduced motion | `prefers-reduced-motion` at mount/export | dissolves only, no zooms or slides, 1.25× holds; export status says "(reduced motion)" |
| Read aloud (play only) | player toggle + `speechSynthesis` (English voice) | speaks each scene's first sentence; scenes advance when the voice finishes and hold their last clean frame if speech runs long (preview only, export unchanged); stops on pause, jump, end, or toggle-off; UI states it is not in the exported video |
| Spotlight | `scene.spotlight {x, y, r}` from `data/outlines/<id>.json` (first match) when `FEATURE_OUTLINES` is on | renderer drifts the crop toward the subject + slight push (skipped under reduced motion) and dims the frame except the subject circle; missing/disabled/malformed outlines ignored silently; captions stay undimmed |
| Missing photo | image fails to load | player paints a "Photo unavailable" placeholder and keeps playing; export stops with the photo id named |
| Old stories | chapters, no scenes | migrated on read (heading + text joined, 3s scenes, plain cuts); they play and export unchanged otherwise |
| Burst frames (step 11 contract) | `scene.frame_srcs` map | the v2 story endpoint must serve a src per burst frame id; unknown frame ids paint the placeholder |

## 9. Profile (`#/profile`) + self-tagging (`#/profile/tag`)

| Element | Endpoint | Fields |
|---|---|---|
| Name input + save | `PUT /api/profile` | `name`; 400 text shown verbatim; demo code needed for the write |
| Voice choice + 3 example sentences | same PUT | `refer_as` saved with the name (voice alone needs a saved name first); examples use the profile name or "Your name" |
| Privacy block | none (static) | "Face matching only compares the reference photo you upload against your own photos, to suggest which ones you are in. Nothing is tagged until you confirm it, no one else is ever identified, and your name is used only on photos you tag." |
| Tag/export/delete | `#/profile/tag`, `/api/export`, `DELETE /api/profile` | delete runs only after the inline confirm panel; delete clears the profile + every tag (records, Supabase, fresh embeddings) and reports "Your profile and N photo tags are deleted."; export zip gains `profile.json` + `owner_tags.json` |
| Tag grid | `GET /api/albums` photo entries | `src`, `caption`, `people`, `owner_present`, `owner_position`; people-first order; dossier link per tile |
| I'm in this / Not me / Left-Centre-Right | `POST /api/owner-tags` | per-tile immediate tag; position row only when people > 1; bulk "I'm in all selected" for the selection |
| Progress + undo | `GET /api/owner-tags/summary` | "N of M reviewed (X you, Y not you)" + bar; undo restores each photo's previous state (null clears) |
| Name prompt | `PUT /api/profile` | first present-tag without a profile asks for the name, then continues the pending tag |
| "Are you in this photo?" | same two endpoints | library queue rows + `#/add` result pane after a job finishes: Yes / No / Skip, inline name prompt when needed |
| "You are in this photo" badge | `owner_present` | library tiles + photo dossier (links to the tag page) + Reel result mounts (top-right) + Connected ring nodes (dot + title note); "Me" album in the library, with a tag-yourself empty state |
| Match-my-face panel | `POST/GET/DELETE /api/face-reference`, `POST /api/face-scan` | reference upload + preview + remove; ranked suggestion rows (thumb, band pill, face count, tag state, Yes/No → `POST /api/owner-tags`); unscored count with hand-tag note; scan writes nothing |

## 10. Story studio narration (`#/stories`, `#/stories/<id>`)

| Element | Endpoint | Fields |
|---|---|---|
| Narration voice pills (By name / As you / As I) | `GET /api/profile` default, sent on `POST /api/stories` as `voice` | starts from the profile's `refer_as` (else By name); honesty note: the name is used only on tagged photos |
| Scene problem flags | `problems` in the story detail | headings using the name or you/I on untagged photos are flagged with "change it or refresh the narration" |
| Refresh narration | `POST /api/stories/{id}/refresh` | rewrites texts with the current name + tags; trace painted under the review tab; demo code needed |
| "Include my name in this public story" | `POST /api/stories/{id}/publish` `{include_name}` | checkbox, default off; disabled once published showing the stored choice; off means the Showcase shows "the photographer" |
| Directed film section | `POST /api/films` | "Direct this story" builds a v2 cut from the chapter photos; each scene shows role/camera/transition/duration, "Why this shot", caption, evidence, verification pill, trace |
| Try another direction | same endpoint + `seed` | same photos, new seed; "Preview this direction" plays/exports the cut (player + export note the cut); stale warning when chapters change; "Back to story cut" restores v1 |
