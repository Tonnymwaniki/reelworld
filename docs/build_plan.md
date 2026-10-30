# ReelWorld rebuild: plan

Authoritative designs: `frontend/design/stitch_export_final/` (41 screens +
5 design systems + 3 theme notes). Older `stitch_export/` is fallback only.
Tokens: warm archival Material set (surface/tertiary/...) on most screens,
plus the papyrus/espresso/ochre/sage set (ring diagram screen). Both live in
the shell `tailwind.config`; Plus Jakarta Sans throughout.

Assistant name: **Reel**. English only (no Swahili code remains; if any is
reintroduced it goes behind `ENABLE_SWAHILI=false`). "Built with Muse Spark
Open" is prominent in the header of every page. Nav: Reel, Browse,
Connected, Stories, About.

## Route map

| Route | Phase | Screen folder(s) | Status |
|---|---|---|---|
| `#/` Reel thread + landing hero | 1 | reelworld_landing_page, reel_conversational_photo_discovery, reel_conversation_thread_desktop, reel_reply_states_flag_controls_desktop, chat_live_progress_while_assistant_works, chat_adding_a_photo_live_place_identification, chat_photo_opened_evidence_dossier_beside_thread | P0: old home view; P1: rebuilt |
| `#/tour` overlay | 1 | reelworld_the_60_second_tour | P1 |
| `#/credits` | 1 | reelworld_photo_credits_license_directory | P0: stub; P1: built |
| `#/about` | 1 | reelworld_about_reelworld_reel | P0: stub; P1: built |
| flag control | 1 | reelworld_flag_this_result | P1 |
| `#/photo/<id>` dossier | 2 | chat_photo_opened_evidence_dossier_beside_thread, world_attribution_kit_plate_nbo_0021 | P0: old view; P2: rebuilt |
| `#/connected` rings | 3 | connected_the_ring_diagram_hero_screen, connected_where_you_ve_been_overview, connected_from_here_i_saw_this_vantage_links, connected_how_are_these_two_connected_flow, connected_link_evidence_panel, connected_section_states_loading_empty_gap_error | P0: old view; P3: rebuilt |
| `#/stories`, `#/stories/<id>`, `#/showcase` | 4 | stories_create_a_story, stories_building_the_story, stories_the_story_player_9_16_vertical_quad_frame, stories_review_and_adjust, stories_export_and_publish, stories_showcase | P0: nav points at old `#/story`; P4: rebuilt |
| `#/library` My Photos | 5 | my_photos_library_smart_albums, my_photos_library_states, my_photos_add_photos_ingestion_queue, my_photos_burst_detail_curation, my_photos_manage_photo_correction, my_photos_delete_and_export | P0: stub; P5: built |
| `#/browse` world + `#/place/<key>` | 5 | world_public_photographic_cadastre, world_place_page_kicc_nairobi, world_gaps_in_the_cadastre | P0: `#/place` old view, `#/browse` stub; P5: built |
| `#/add` upload | 5 | (old view until P5 queue replaces it) | P0: old view; P5: replaced |
| 404 / error | 0 | reelworld_not_found_404_error_states | P0 |
| og image | 0 | reelworld_social_share_preview_image_1200x630 | P0: Pillow build at `/og-image.png` |

## Endpoints

Existing (keep working): `GET /health`, `POST /chat`, `POST /api/search`,
`POST /sessions/{id}/reset`, `GET /api/photos`, `POST /api/compare`,
`POST /api/story` (kept; the P4 engine powers the new UI),
`GET /api/photo/{id}`, `POST /api/ask`, `GET /photos/{path}`,
`POST /api/upload`, `GET /api/jobs/{id}`, `GET /api/place/{key}`,
`GET /api/bridge/{id}`, `GET /api/connected`, `GET /api/identify/{id}`.

New:
| Endpoint | Phase | Purpose |
|---|---|---|
| `GET /api/config` | 0 | `{demo_mode, outlines_enabled, swahili_enabled}` for the shell |
| `POST /chat/stream` (SSE) | 1 | steps really run + final result |
| `GET /api/credits` | 1 | credits from `data/manifest.csv` |
| `POST /api/flag` | 1 | append to `data/flags.jsonl` (git-ignored) |
| `GET /api/rings/{photo_id}` | 3 | ring groups + link evidence, ≤8/ring |
| `GET /api/places/overview` | 3 | coverage counts by viewpoint |
| `GET /api/connected/self` | 3 | personal↔personal links |
| `POST /api/explain` | 3 | how two photos connect, from records |
| `POST/GET/PATCH/DELETE /api/stories[/{id}]`, `POST .../publish` | 4 | story engine (`backend/story_engine.py`, `data/stories/`) |
| `GET /api/albums` | 5 | smart albums from annotations |
| `POST /api/photo/{id}/correct` | 5 | correction → Pass B rerun, `human_review` |
| `DELETE /api/photo/{id}` | 5 | real deletion, reports what was removed |
| `GET /api/export` | 5 | zip of photos + annotation JSON |
| `GET /api/world` (+facets) | 5 | filtered world browse |
| `GET /api/gaps` | 5 | thin places + missing viewpoints |
| `POST /api/outline` | — | 501 `FEATURE_OUTLINES=false` (deferred) |

## Demo mode (choice, stated)

`DEMO_MODE` (default true) and `DEMO_CODE` come from `.env`. When on, the
sample library is shown and upload/delete/correct/publish are disabled
unless the request carries header `X-Demo-Code` matching `DEMO_CODE`
(403 + clear message otherwise). The UI has a code field; the code lives
only in `sessionStorage`. `DEMO_MODE=false` enables everything (local real
library). Same data either way; the flag gates writes, not reads.

## Notes

- `docs/annotation_schema.md` (named in the brief) does not exist; the
  schema lives in the annotation JSON + `backend/schema*.sql`. Not blocking.
- Old views stay live until their phase replaces them; unbuilt new routes
  show a styled "coming in Phase N" stub so no link is dead.
- `backend/test_muse.py` is a manual Baseten probe, not a maintained test.
- Pillow is pre-approved and already installed (verified 2026-10-30).
