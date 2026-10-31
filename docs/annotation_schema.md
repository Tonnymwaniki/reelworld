# Annotation record schema

One JSON file per photo: `data/annotations/<collection>/<photo_id>.json`.
`schema_version` is currently `"0.1"`. Three layers, in trust order:

## `provided` — facts given with the photo, never modelled

- `file`: relative photo path (always present).
- World photos: `author`, `license`, `source_url`, `title` (credit).
- `owner` (personal photos only): the owner's own presence tag,
  `{present: true | false | null, position: "left" | "centre" |
  "right" | null, tagged_at}`. `null` present means not reviewed.
  Set ONLY by the owner tapping "I'm in this" / "Not me" (`POST
  /api/owner-tags`). Never set from a model, never from a face.
  A photo counts as "owner is in it" only when `present` is true.

## `observed` — what the annotation pass saw in the pixels

`caption`, `description`, `retrieval_queries[]`, `tags[]`,
`scene` (type, setting, time_of_day, weather, lighting,
crowd_level, activity_summary), `camera` (viewpoint,
height_estimate, facing, distance, framing, orientation,
subject_focus), `entities[]` (id, label, category, attributes,
count, salience, position, evidence, confidence),
`spatial_relations[]`, `visible_text[]` (text, language,
entity_id, location_in_image, legibility, confidence),
`people` (count, count_confidence, faces_visible, activities,
identified — always false: the system never identifies people).

## `inferred` — place verdicts over the evidence

`landmarks[]` (name, key, type, status, evidence[]) and `place`
(name, key, status, evidence, confidence). Status is `confirmed`,
`candidate`, or `human_review` (owner correction, final).

## Owner overrides (top level)

Corrections write `corrected_by: "you"` + `corrected_at` and edit
in place. `uncertainties` may list open questions. The loader
mirrors `provided.owner.present` into the Supabase `photos`
column `owner_present` (see `backend/schema_v3.sql`).
