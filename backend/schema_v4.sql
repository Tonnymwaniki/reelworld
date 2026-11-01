-- ReelWorld schema v4: visual attributes.
--
-- Run this AFTER schema.sql + v2 + v3 in the Supabase SQL editor,
-- BEFORE reloading (python backend\load_supabase.py). Safe to run again.
--
-- attributes mirrors data/attributes/<photo_id>.json as jsonb so SQL
-- (search_photos below) can filter on it. Each slot is
-- {"value", "confidence", "evidence"}; objects is a list of
-- {"name", "confidence", "evidence"}. Missing/unknown info never
-- passes a positive filter.

ALTER TABLE photos ADD COLUMN IF NOT EXISTS attributes jsonb;

CREATE INDEX IF NOT EXISTS photos_attributes_gin
  ON photos USING gin (attributes);

COMMENT ON COLUMN photos.attributes IS
'Visual checklist judged from the image (atmosphere, light, time_of_day, water_visible, vegetation, crowd, objects). Mirrored from data/attributes/ by the loader.';

-- search_photos v3: attribute filter + attributes in results.
-- Replaces the v2 function (same name and params plus
-- filter_attributes and attributes). Run in the Supabase SQL editor.
-- If the CREATE fails on landmark_keys, the column is jsonb not text[]:
-- change "landmark_keys text[]" below to "landmark_keys jsonb" and rerun.
--
-- filter_attributes shape: {"atmosphere": ["misty_or_foggy"],
-- "crowd": ["empty", "few"]}. AND across keys, OR within a key.
-- Water values are JSON booleans: {"water_visible": [true]}.

DROP FUNCTION IF EXISTS search_photos;

CREATE OR REPLACE FUNCTION search_photos(
  query_embedding vector(384),
  match_count int,
  filter_collection text DEFAULT NULL,
  filter_viewpoints text[] DEFAULT NULL,
  max_people int DEFAULT NULL,
  exclude_ids text[] DEFAULT NULL,
  filter_owner boolean DEFAULT NULL,
  filter_attributes jsonb DEFAULT NULL
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
  attributes jsonb,
  similarity float
)
LANGUAGE sql STABLE AS $$
  SELECT
    p.photo_id, p.collection, p.file, p.caption,
    p.place_key, p.place_name, p.taken_from_key,
    p.landmark_keys, p.viewpoint, p.scene_type,
    p.people_count, p.lex, p.owner_present, p.attributes,
    1 - (p.embedding <=> query_embedding) AS similarity
  FROM photos p
  WHERE (filter_collection IS NULL OR p.collection = filter_collection)
    AND (filter_viewpoints IS NULL OR p.viewpoint = ANY (filter_viewpoints))
    AND (max_people IS NULL OR p.people_count <= max_people)
    AND (exclude_ids IS NULL OR NOT (p.photo_id = ANY (exclude_ids)))
    AND (filter_owner IS NOT TRUE OR p.owner_present IS TRUE)
    AND (filter_attributes IS NULL OR (
      (filter_attributes->'atmosphere' IS NULL OR
        p.attributes->'atmosphere'->>'value' = ANY (
          SELECT jsonb_array_elements_text(filter_attributes->'atmosphere')))
      AND (filter_attributes->'light' IS NULL OR
        p.attributes->'light'->>'value' = ANY (
          SELECT jsonb_array_elements_text(filter_attributes->'light')))
      AND (filter_attributes->'time_of_day' IS NULL OR
        p.attributes->'time_of_day'->>'value' = ANY (
          SELECT jsonb_array_elements_text(filter_attributes->'time_of_day')))
      AND (filter_attributes->'water_visible' IS NULL OR
        p.attributes->'water_visible'->>'value' = ANY (
          SELECT jsonb_array_elements_text(filter_attributes->'water_visible')))
      AND (filter_attributes->'vegetation' IS NULL OR
        p.attributes->'vegetation'->>'value' = ANY (
          SELECT jsonb_array_elements_text(filter_attributes->'vegetation')))
      AND (filter_attributes->'crowd' IS NULL OR
        p.attributes->'crowd'->>'value' = ANY (
          SELECT jsonb_array_elements_text(filter_attributes->'crowd')))
    ))
  ORDER BY p.embedding <=> query_embedding
  LIMIT match_count;
$$;
