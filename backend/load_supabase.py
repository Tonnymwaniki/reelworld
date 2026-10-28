"""
ReelWorld: load the annotated photos and their embeddings into Supabase.

Prerequisites:
  1. python -m pip install supabase
  2. schema.sql has been run in the Supabase SQL Editor
  3. .env contains:
       SUPABASE_URL=https://<your-project>.supabase.co
       SUPABASE_SERVICE_KEY=<your secret / service_role key>
  4. The index is built:  python backend\\retrieval.py build

Run from the project root:
    python backend\\load_supabase.py

Safe to run again: rows are upserted by photo_id.
"""
import json
import os
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parent.parent
ANN = ROOT / "data" / "annotations"
INDEX = ROOT / "data" / "index"
BATCH = 40


def main():
    load_dotenv(ROOT / ".env")
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    vecs = np.load(INDEX / "embeddings.npy")
    meta = json.loads((INDEX / "meta.json").read_text(encoding="utf-8"))
    if len(vecs) != len(meta):
        raise SystemExit("Index files do not match. Run: python backend\\retrieval.py build")

    records = {}
    for col in ("world", "personal"):
        for p in (ANN / col).glob("*.json"):
            r = json.loads(p.read_text(encoding="utf-8"))
            records[r["photo_id"]] = r

    rows = []
    for m, v in zip(meta, vecs):
        rec = records.get(m["photo_id"])
        if rec is None:
            print(f"No record for {m['photo_id']}, skipping")
            continue
        rows.append({
            "photo_id": m["photo_id"],
            "collection": m["collection"],
            "file": m["file"],
            "caption": m["caption"],
            "place_key": m["place_key"],
            "place_name": m["place_name"],
            "taken_from_key": m["taken_from_key"],
            "landmark_keys": m["landmark_keys"],
            "viewpoint": m["viewpoint"],
            "scene_type": m["scene_type"],
            "people_count": m["people_count"],
            "lex": m["lex"],
            "record": rec,
            "embedding": [float(x) for x in v],
        })

    print(f"Uploading {len(rows)} photos in batches of {BATCH} ...")
    for i in range(0, len(rows), BATCH):
        sb.table("photos").upsert(rows[i:i + BATCH], on_conflict="photo_id").execute()
        print(f"  {min(i + BATCH, len(rows))}/{len(rows)}")

    total = sb.table("photos").select("photo_id", count="exact").execute().count
    print(f"Rows now in Supabase: {total}")

    # Sanity check: the first world photo should come back as its own best match.
    first = next(r for r in rows if r["collection"] == "world")
    res = sb.rpc("match_photos", {
        "query_embedding": first["embedding"],
        "match_count": 3,
        "filter_collection": "world",
    }).execute()
    print(f"\nSanity search, photos like {first['photo_id']}:")
    for r in res.data:
        print(f"  {r['photo_id']:<14} {r['similarity']:.3f}  {r['caption'][:80]}")


if __name__ == "__main__":
    main()