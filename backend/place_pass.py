"""
ReelWorld: Pass B (infer places and landmarks), version passB-v1.

Reads the Pass A records (text only, no image is sent), plus provided context
(manifest title for world photos, optional owner notes for personal photos), and
adds to each record's "inferred" block:

  landmarks[]        named landmarks, each with evidence and a status computed IN CODE
  place              the place the photo SHOWS (subject), with a stable place key
  taken_from         the place the camera was AT, when it can be told
  place_candidates[] alternatives
  cultural_context[] local terms visible in the scene

Evidence rule (enforced in code, not trusted to the model):
  * "visible_text" evidence only counts if that text is really in the record.
  * A landmark is "confirmed" if it has verified visible text, OR at least two
    different kinds of evidence including something observed in the photo.
  * A manifest title or owner note on its own is never enough: "candidate".

Place keys come from data/places.json (a registry with aliases, seeded with
well-known Kenyan places) so "KICC" and "Kenyatta International Convention
Centre" end up with the same key.

Run from the project root:
    python backend\\place_pass.py --collection world --limit 3
    python backend\\place_pass.py --collection all --workers 4
    python backend\\place_pass.py --photo cbd_003 --force

Optional file for personal photos: data/personal_manifest.csv with columns
    photo_id,owner_note
e.g. personal_006,"View from the top of KICC looking over the CBD"
"""
import argparse
import csv
import json
import os
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from annotate import BASE_URL, MODEL, extract_json

ROOT = Path(__file__).resolve().parent.parent
ANN = ROOT / "data" / "annotations"
RAW = ANN / "raw"
REGISTRY_PATH = ROOT / "data" / "places.json"
PERSONAL_NOTES = ROOT / "data" / "personal_manifest.csv"

PROMPT_VERSION = "passB-v1"
MAX_TOKENS = 8000
KINDS = {"visible_text", "architecture", "provided_title", "owner_note", "context"}
LOCK = threading.Lock()

SEED_PLACES = {
    "kenya/nairobi/cbd/kicc": ("Kenyatta International Convention Centre", "building",
        ["KICC", "Kenyatta International Conference Centre", "Kenyatta International Convention Center"]),
    "kenya/nairobi/cbd/cbk-pension-towers": ("CBK Pension Towers", "building",
        ["Pension Towers", "CBK Pension Tower", "Central Bank Pension Towers"]),
    "kenya/nairobi/cbd/times-tower": ("Times Tower", "building", ["KRA Times Tower"]),
    "kenya/nairobi/cbd/teleposta-towers": ("Teleposta Towers", "building", ["Teleposta Tower"]),
    "kenya/nairobi/cbd/anniversary-towers": ("Anniversary Towers", "building", ["Anniversary Tower"]),
    "kenya/nairobi/cbd/hilton-nairobi": ("Hilton Nairobi", "building", ["Nairobi Hilton", "Hilton Hotel Nairobi"]),
    "kenya/nairobi/cbd/kenyatta-avenue": ("Kenyatta Avenue", "street", ["Kenyatta Ave"]),
    "kenya/nairobi/cbd/nairobi-railway-station": ("Nairobi Railway Station", "building", ["Nairobi Station"]),
    "kenya/nairobi/cbd": ("Nairobi CBD", "district",
        ["Nairobi central business district", "Nairobi city centre", "Nairobi city center", "Nairobi downtown"]),
    "kenya/nairobi/uhuru-park": ("Uhuru Park", "park", ["Uhuru Gardens Park"]),
    "kenya/nairobi/central-park": ("Central Park Nairobi", "park", ["Central Park"]),
    "kenya/nairobi/nairobi-national-park": ("Nairobi National Park", "park", []),
    "kenya/nairobi/karura-forest": ("Karura Forest", "park", ["Karura Forest Reserve"]),
    "kenya/nairobi/gikomba-market": ("Gikomba Market", "market", ["Gikomba"]),
    "kenya/nairobi/marikiti-market": ("Marikiti Market", "market", ["Marikiti"]),
    "kenya/nairobi": ("Nairobi", "city", []),
    "kenya/kajiado/ngong-hills": ("Ngong Hills", "natural", ["Ngong Hill"]),
    "kenya/narok/maasai-mara": ("Maasai Mara", "natural", ["Masai Mara", "Maasai Mara National Reserve"]),
    "kenya/nakuru/lake-nakuru-national-park": ("Lake Nakuru National Park", "park", ["Lake Nakuru"]),
    "kenya/kajiado/amboseli-national-park": ("Amboseli National Park", "park", ["Amboseli"]),
    "kenya/nakuru/lake-naivasha": ("Lake Naivasha", "natural", ["Naivasha"]),
    "kenya/mount-kenya": ("Mount Kenya", "natural", []),
    "kenya/mombasa": ("Mombasa", "city", []),
    "kenya/kisumu": ("Kisumu", "city", []),
    "kenya/nakuru": ("Nakuru", "city", ["Nakuru town"]),
}

PROMPT = """You are the place-inference engine for ReelWorld, a visual knowledge platform.
You are given a structured description of ONE photo (no image) and may add what
the photo tells us about where it is. Return ONE JSON object and nothing else.

Rules:
1. Use ONLY the information provided. Do not use outside knowledge to add
   features the description does not mention.
2. Every landmark and place needs evidence. Each evidence item has a kind:
   - "visible_text": copy the exact sign text from visible_text that supports it
   - "architecture": a distinctive visible feature from the entities or description
   - "provided_title": the file title (world photos only)
   - "owner_note": the owner's note (personal photos only)
   - "context": other supporting detail
3. Never name a place you have no evidence for. If unsure, leave it out.
4. "place" is the place the photo SHOWS (its subject). "taken_from" is the place
   the camera was AT, if the evidence tells you (for example an owner note saying
   the photo was taken from the top of a building). Use null if unknown.
5. Use these exact names when they apply: {known}
6. cultural_context: only local terms clearly shown (for example matatu, kiosk,
   mkokoteni, kanga), with the language, and the evidence. Empty list if none.
7. hierarchy is a list from country down, like ["Kenya", "Nairobi", "CBD"].
8. All confidence values are numbers from 0 to 1.
9. Never identify any person.

Return this structure:
{{
  "landmarks": [
    {{"name": "...", "type": "building | park | market | street | natural | district | other",
      "evidence": [{{"kind": "visible_text | architecture | provided_title | owner_note | context", "detail": "..."}}],
      "confidence": 0.9}}
  ],
  "place": {{"name": "...", "hierarchy": ["Kenya", "..."],
            "evidence": [{{"kind": "...", "detail": "..."}}], "confidence": 0.9}},
  "taken_from": null,
  "place_candidates": [
    {{"name": "...", "hierarchy": ["Kenya", "..."], "evidence": [{{"kind": "...", "detail": "..."}}], "confidence": 0.5}}
  ],
  "cultural_context": [
    {{"term": "...", "local_name": "...", "language": "...", "evidence": "..."}}
  ],
  "notes": ["anything that could not be determined"]
}}

PHOTO RECORD:
{context}
"""


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def load_registry():
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    reg = {k: {"name": n, "type": t, "aliases": a} for k, (n, t, a) in SEED_PLACES.items()}
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")
    return reg


def resolve_key(name, hierarchy, registry, ptype="other"):
    """Map a place name to a stable key, adding unknown places to the registry."""
    n = norm(name)
    if not n:
        return None
    with LOCK:
        for key, p in registry.items():
            names = [norm(p["name"])] + [norm(a) for a in p.get("aliases", [])]
            if n in names:
                return key
        for key, p in registry.items():
            names = [norm(p["name"])] + [norm(a) for a in p.get("aliases", [])]
            if any(len(x) >= 8 and x in n for x in names):
                return key
        parts = [slug(h) for h in (hierarchy or [])[:3] if slug(h)]
        key = "/".join(parts + [slug(name)]) if parts else "unknown/" + slug(name)
        if key not in registry:
            registry[key] = {"name": name, "type": ptype, "aliases": []}
            REGISTRY_PATH.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
        return key


def grade(evidence, vt_texts):
    """Return (status, valid_evidence). Verifies visible_text claims against the record."""
    valid, kinds, vt_ok = [], set(), False
    for e in evidence if isinstance(evidence, list) else []:
        if not isinstance(e, dict) or e.get("kind") not in KINDS:
            continue
        detail = str(e.get("detail") or "")
        if e["kind"] == "visible_text":
            dl = detail.lower()
            if not any(len(t) >= 4 and (t.lower() in dl or (len(dl) >= 4 and dl in t.lower())) for t in vt_texts):
                continue  # claimed text is not in the record: unsupported
            vt_ok = True
        kinds.add(e["kind"])
        valid.append({"kind": e["kind"], "detail": detail})
    observed = vt_ok or "architecture" in kinds
    confirmed = vt_ok or (observed and len(kinds) >= 2)
    return ("confirmed" if confirmed else "candidate"), valid


def conf(x, default=0.5):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 1 else default


def load_notes():
    notes = {}
    if PERSONAL_NOTES.exists():
        with open(PERSONAL_NOTES, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                pid = row.get("photo_id")
                if pid:
                    notes[pid] = row.get("owner_note", "")
                else:
                    print(f"Skipping a row in personal_manifest.csv without a photo_id: {row}")
    return notes


def build_context(rec, notes):
    obs = rec["observed"]
    title = rec["provided"].get("title")
    if title:
        title = re.sub(r"^File:", "", title)
        title = re.sub(r"\.(jpe?g|png)$", "", title, flags=re.I)
    ctx = {
        "collection": rec["collection"],
        "provided_title": title if rec["collection"] == "world" else None,
        "owner_note": notes.get(rec["photo_id"]) if rec["collection"] == "personal" else None,
        "caption": obs["caption"],
        "description": obs["description"],
        "tags": obs["tags"],
        "scene": obs["scene"],
        "camera": obs["camera"],
        "entities": [{"label": e["label"], "attributes": e.get("attributes", []),
                      "evidence": e.get("evidence"), "confidence": e.get("confidence")}
                     for e in obs["entities"]],
        "visible_text": [{"text": t["text"], "legibility": t["legibility"]} for t in obs["visible_text"]],
        "uncertainties": rec["inferred"].get("uncertainties", []),
    }
    return json.dumps(ctx, indent=1, ensure_ascii=False)


def process(client, path, registry, notes, force):
    rec = json.loads(path.read_text(encoding="utf-8"))
    pid = rec["photo_id"]
    if not force and any(p.get("pass") == "B" for p in rec["provenance"]["passes"]):
        return pid, "skipped (already has Pass B)", None

    known = ", ".join(sorted({p["name"] for p in registry.values()}))
    prompt = PROMPT.format(known=known, context=build_context(rec, notes))
    data, usage, extra = None, None, ""
    for attempt in (1, 2):
        try:
            resp = client.chat.completions.create(
                model=MODEL, temperature=0.1, max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": prompt + extra}])
        except Exception as e:
            return pid, f"API error: {e}", None
        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        RAW.mkdir(parents=True, exist_ok=True)
        (RAW / f"{pid}_passB_attempt{attempt}.txt").write_text(text, encoding="utf-8")
        try:
            data = extract_json(text)
            if not isinstance(data.get("landmarks"), list):
                raise ValueError("landmarks must be a list")
            break
        except Exception as e:
            data = None
            extra = f"\n\nYour previous answer was not valid ({e}). Return the JSON object only."
    if data is None:
        return pid, "FAILED: no valid JSON", None

    vt_texts = [t["text"] for t in rec["observed"]["visible_text"] if t.get("text")]

    landmarks = []
    for lm in data["landmarks"]:
        if not isinstance(lm, dict) or not lm.get("name"):
            continue
        status, ev = grade(lm.get("evidence"), vt_texts)
        if not ev:
            continue
        landmarks.append({
            "name": lm["name"],
            "key": resolve_key(lm["name"], None, registry, lm.get("type", "other")),
            "type": lm.get("type", "other"),
            "status": status, "evidence": ev, "confidence": conf(lm.get("confidence")),
        })

    def place_block(p):
        if not isinstance(p, dict) or not p.get("name"):
            return None
        status, ev = grade(p.get("evidence"), vt_texts)
        if not ev:
            return None
        return {"name": p["name"], "hierarchy": p.get("hierarchy") or [],
                "key": resolve_key(p["name"], p.get("hierarchy"), registry),
                "status": status, "evidence": ev, "confidence": conf(p.get("confidence"))}

    place = place_block(data.get("place"))
    taken_from = place_block(data.get("taken_from"))
    candidates = [c for c in (place_block(c) for c in data.get("place_candidates") or []) if c]
    cultural = [c for c in data.get("cultural_context") or [] if isinstance(c, dict) and c.get("term")]

    inf = rec["inferred"]
    inf["landmarks"] = landmarks
    inf["place"] = place
    inf["place_key"] = place["key"] if place else None
    inf["taken_from"] = taken_from
    inf["place_candidates"] = candidates
    inf["cultural_context"] = cultural
    for note in data.get("notes") or []:
        if note not in inf["uncertainties"]:
            inf["uncertainties"].append(note)

    passes = [p for p in rec["provenance"]["passes"] if p.get("pass") != "B"]
    passes.append({
        "pass": "B", "model": MODEL, "prompt_version": PROMPT_VERSION,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "raw_output_path": f"data/annotations/raw/{pid}_passB_attempt{attempt}.txt",
        "tokens": getattr(usage, "total_tokens", None),
    })
    rec["provenance"]["passes"] = passes
    path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")

    conf_n = sum(1 for l in landmarks if l["status"] == "confirmed")
    return pid, f"ok, place={inf['place_key']}, landmarks={len(landmarks)} ({conf_n} confirmed)", inf["place_key"]


def main():
    ap = argparse.ArgumentParser(description="ReelWorld Pass B: places and landmarks")
    ap.add_argument("--collection", choices=["world", "personal", "all"])
    ap.add_argument("--photo", help="a photo id such as cbd_003")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    client = OpenAI(base_url=BASE_URL, api_key=os.environ["BASETEN_API_KEY"])
    registry = load_registry()
    notes = load_notes()

    if args.photo:
        paths = list(ANN.glob(f"*/{args.photo}.json"))
    elif args.collection:
        cols = ["world", "personal"] if args.collection == "all" else [args.collection]
        paths = sorted(p for c in cols for p in (ANN / c).glob("*.json"))
    else:
        ap.error("give --collection or --photo")
    if args.limit:
        paths = paths[: args.limit]

    print(f"Pass B on {len(paths)} record(s) ({PROMPT_VERSION})")
    start = time.time()

    def run(p):
        pid, status, key = process(client, p, registry, notes, args.force)
        print(f"{pid}: {status}", flush=True)
        return status, key

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run, paths))

    ok = [r for r in results if r[0].startswith("ok")]
    print(f"Done in {time.time() - start:.0f}s. {len(ok)} updated, {len(results) - len(ok)} skipped or failed.")
    counts = Counter(k for _, k in ok if k)
    if counts:
        print("Photos per place key:")
        for k, n in counts.most_common(15):
            print(f"  {n:3d}  {k}")


if __name__ == "__main__":
    main()