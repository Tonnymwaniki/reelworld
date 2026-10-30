import os
import sys

sys.path.insert(0, "backend")
from dotenv import load_dotenv

load_dotenv("backend/.env")
load_dotenv(".env")
from supabase import create_client

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
rows = sb.table("photos").select("photo_id,file,record").eq("collection", "world").execute().data
for r in rows:
    if r["photo_id"].startswith("street_00"):
        cap = (((r.get("record") or {}).get("observed") or {}).get("caption") or "")[:80]
        print(r["photo_id"], "|", cap)
keys = set()
for r in rows:
    k = (((r.get("record") or {}).get("inferred") or {}).get("place") or {}).get("key")
    if k:
        keys.add(k)
print("places with world photos:", len(keys))
