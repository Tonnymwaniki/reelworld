import os
import sys

sys.path.insert(0, "backend")
from dotenv import load_dotenv

load_dotenv("backend/.env")
load_dotenv(".env")
from supabase import create_client

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
rows = sb.table("photos").select("photo_id,record").eq("collection", "world").execute().data

for label, words in {"kicc": ["kicc"], "matatu": ["matatu"],
                     "veg": ["vegetable", "cabbage", "tomato"],
                     "market": ["marikiti", "wakulima", "city market"]}.items():
    hits = []
    for r in rows:
        rec = r.get("record") or {}
        obs = rec.get("observed") or {}
        blob = " ".join([obs.get("caption", ""), obs.get("description", ""),
                         " ".join(e.get("label", "") for e in obs.get("entities", [])),
                         " ".join(s.get("text", "") for s in obs.get("visible_text", [])),
                         (((rec.get("inferred") or {}).get("place") or {}).get("name") or "")]).lower()
        if any(w in blob for w in words):
            cap = (obs.get("caption") or "")[:75]
            hits.append((r["photo_id"], cap))
    print(label, len(hits))
    for h in hits[:5]:
        print("   ", h)
