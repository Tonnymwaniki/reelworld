-- ReelWorld schema v3: owner presence tags.
--
-- Run this AFTER schema.sql + schema_v2.sql in the Supabase SQL editor,
-- BEFORE reloading (python backend\load_supabase.py). Safe to run again.
--
-- owner_present mirrors record.provided.owner.present as a real column so
-- SQL (search_photos in step 4) can filter on it. true = the owner tagged
-- themselves in this photo; false = tagged "not me"; null = not reviewed.
-- World rows stay null: tags exist on personal photos only.

ALTER TABLE photos ADD COLUMN IF NOT EXISTS owner_present BOOLEAN;

COMMENT ON COLUMN photos.owner_present IS
'Owner-tagged presence (true/false/null = yes/no/not reviewed). Set only by the owner via POST /api/owner-tags; mirrored from record.provided.owner.present by the loader.';

-- search_photos v2: owner filter + owner_present in results.
-- Replaces the v1 function (same name, params and returned columns,
-- plus filter_owner and owner_present). Run in the Supabase SQL editor.
-- If the CREATE fails on landmark_keys, the column is jsonb not text[]:
-- change "landmark_keys text[]" below to "landmark_keys jsonb" and rerun.

DROP FUNCTION IF EXISTS search_photos;

CREATE OR REPLACE FUNCTION search_photos(
  query_embedding vector(384),
  match_count int,
  filter_collection text DEFAULT NULL,
  filter_viewpoints text[] DEFAULT NULL,
  max_people int DEFAULT NULL,
  exclude_ids text[] DEFAULT NULL,
  filter_owner boolean DEFAULT NULL
)
RETURNS TABLE (
  photo_id text,
  collection text,
  file text,
  caption text,
  place_key text,
  place_name text,
  taken_from_key text,
  landmark_keys text[],
  viewpoint text,
  scene_type text,
  people_count int,
  lex text,
  owner_present boolean,
  similarity float
)
LANGUAGE sql STABLE AS $$
  SELECT
    p.photo_id, p.collection, p.file, p.caption,
    p.place_key, p.place_name, p.taken_from_key,
    p.landmark_keys, p.viewpoint, p.scene_type,
    p.people_count, p.lex, p.owner_present,
    1 - (p.embedding <=> query_embedding) AS similarity
  FROM photos p
  WHERE (filter_collection IS NULL OR p.collection = filter_collection)
    AND (filter_viewpoints IS NULL OR p.viewpoint = ANY (filter_viewpoints))
    AND (max_people IS NULL OR p.people_count <= max_people)
    AND (exclude_ids IS NULL OR NOT (p.photo_id = ANY (exclude_ids)))
    AND (filter_owner IS NOT TRUE OR p.owner_present IS TRUE)
  ORDER BY p.embedding <=> query_embedding
  LIMIT match_count;
$$;
