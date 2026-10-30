import os
import sys

sys.path.insert(0, "backend")
from dotenv import load_dotenv

load_dotenv("backend/.env")
load_dotenv(".env")
from supabase import create_client

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
rows = sb.table("photos").select("photo_id,collection,file,record").eq("collection", "world").execute().data

# distinct cities from place_keys
cities = set()
for r in rows:
    k = (((r.get("record") or {}).get("inferred") or {}).get("place") or {}).get("key") or ""
    p = k.split("/")
    if len(p) >= 2:
        cities.add(p[1])
print("cities:", sorted(cities))

# example-card candidates: captions matching each theme
import re

want = {"veg": ["vegetable", "cabbage", "tomato"], "sky": ["skyline"],
        "kicc": ["kicc"], "matatu": ["matatu"]}
for label, words in want.items():
    hits = []
    for r in rows:
        cap = (((r.get("record") or {}).get("observed") or {}).get("caption") or "").lower()
        if any(w in cap for w in words):
            hits.append((r["photo_id"], cap[:80]))
    print(label, len(hits), hits[:4])
