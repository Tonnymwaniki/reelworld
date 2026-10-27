"""
ReelWorld: Pass A (observe) annotation, version passA-v2.1.

Sends a photo to Muse Spark Open and saves a structured record that follows
docs/annotation_schema.md (v0.1). Pass A fills the observed layer, the privacy
flags and the uncertainties. Landmarks and places (Pass B) come next.

Run from the project root:

  One photo:
    python backend\\annotate.py --photo data\\photos\\personal\\personal_001.jpg --force

  A whole collection (skips photos that already have a record):
    python backend\\annotate.py --collection personal --workers 4
    python backend\\annotate.py --collection world --workers 4

  Try a few first:
    python backend\\annotate.py --collection world --limit 3 --workers 3

  Re-do records made with an older version:
    add --force

Output:
  data/annotations/<collection>/<photo_id>.json     the record
  data/annotations/raw/<photo_id>_attemptN.txt      raw model output
"""
import argparse
import base64
import csv
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
PHOTOS = ROOT / "data" / "photos"
OUT = ROOT / "data" / "annotations"
RAW = OUT / "raw"
MANIFEST = ROOT / "data" / "manifest.csv"

MODEL = "meta-models/muse-spark-open-1026"
BASE_URL = "https://inference.baseten.co/v1"
SCHEMA_VERSION = "0.1"
PROMPT_VERSION = "passA-v2.1"
MAX_TOKENS = 12000

VIEWPOINTS = {"ground_level", "elevated", "aerial", "interior", "water_level"}
LEGIBILITY = {"clear", "partial", "unreadable"}
SENSITIVITY = {"low", "medium", "high"}

PROMPT = """You are the annotation engine for ReelWorld, a visual knowledge platform.
Look at the photo and return ONE JSON object and nothing else (no commentary).

Rules:
1. Describe only what is visible. Do not invent details.
2. Never identify or name any person. Describe people only by count, activity
   and general clothing.
3. Copy visible text exactly as it appears, including capitalization. Each
   separate sign, banner or label is its own visible_text entry. Never combine
   words from different signs. If a sign is cut off by the edge of the photo or
   blurry, set legibility "partial" and write only the letters you can see. Never
   guess missing letters. Only list a sign if you can read at least 3 letters of
   it; otherwise leave it out and mention it in uncertainties. Ignore text printed
   on people's clothing or bags.
4. Never claim something is absent. Use counts instead (0 is allowed).
5. All confidence values are numbers from 0 to 1.
6. List the 8 to 15 most salient entities (fewer if the photo has fewer).
   salience: 1 = minor background, 5 = main subject.
7. spatial_relations may only use: left_of, right_of, behind, in_front_of,
   beside, above, below, on, inside, near. At most 12. Use entity ids.
8. retrieval_queries: exactly 3 different natural ways a person might describe
   this photo when searching for it.
9. uncertainties: plain-language list of things that cannot be determined from
   the photo.
10. camera.distance is the distance from the camera to the main subject. A person
    standing in front of a large building is "medium" even if they look large in
    the frame. Use "close" only for subjects within a few metres, and "far" for
    distant buildings, skylines or landscapes.
11. people.count and privacy.people_count must be the same number.

Return this structure:
{
  "caption": "one sentence",
  "description": "one paragraph of visible things only",
  "retrieval_queries": ["...", "...", "..."],
  "tags": ["short", "search", "terms"],
  "scene": {
    "type": "market | street | park | plaza | building | landscape | other",
    "setting": "indoor | outdoor | mixed",
    "time_of_day": "dawn | morning | daytime | evening | night | unknown",
    "weather": "short phrase or unknown",
    "lighting": "short phrase",
    "crowd_level": "empty | sparse | moderate | busy",
    "activity_summary": "short phrase"
  },
  "camera": {
    "viewpoint": "ground_level | elevated | aerial | interior | water_level",
    "height_estimate": "eye_level | raised | high | very_high",
    "facing": "short phrase, e.g. toward the building / across the street / down at the city",
    "distance": "close | medium | far",
    "framing": "wide | medium | close_up",
    "orientation": "portrait | landscape",
    "subject_focus": "short phrase"
  },
  "entities": [
    {
      "id": "e1",
      "label": "short noun phrase",
      "category": "building | vehicle | person_group | produce | plant | animal | sign | structure | terrain | object | other",
      "attributes": ["visible attributes"],
      "count": 1,
      "salience": 5,
      "position": "coarse position, e.g. left, center-right, background",
      "evidence": "what in the photo shows this",
      "confidence": 0.9
    }
  ],
  "spatial_relations": [
    {"subject": "e1", "predicate": "left_of", "object": "e2", "confidence": 0.9}
  ],
  "visible_text": [
    {
      "text": "exact text of ONE sign, banner or label",
      "language": "en | sw | other | unknown",
      "entity_id": "e3 or null",
      "location_in_image": "where it appears",
      "legibility": "clear | partial | unreadable",
      "confidence": 0.9
    }
  ],
  "people": {
    "count": 0,
    "count_confidence": 0.9,
    "faces_visible": false,
    "activities": ["short phrases"]
  },
  "privacy": {
    "faces_visible": false,
    "people_count": 0,
    "license_plates_visible": false,
    "screens_or_documents_visible": false,
    "private_space": false,
    "sensitivity": "low | medium | high"
  },
  "uncertainties": ["..."]
}
"""


def extract_json(text):
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found in model output")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        # Fall back to the last top-level object in case reasoning text came first.
        for m in reversed(list(re.finditer(r"\{", text))):
            try:
                return json.loads(text[m.start():end + 1])
            except json.JSONDecodeError:
                continue
        raise


def clean_text(d):
    """Drop empty or tiny text fragments; note unreadable signs as uncertainties."""
    texts = d.get("visible_text")
    if not isinstance(texts, list) or not isinstance(d.get("uncertainties"), list):
        return
    cleaned = []
    for t in texts:
        if not isinstance(t, dict):
            continue
        txt = (t.get("text") or "").strip()
        if not txt:
            where = t.get("location_in_image") or "in the photo"
            d["uncertainties"].append(f"unreadable text {where}")
            continue
        if t.get("legibility") == "partial" and len(txt) < 3:
            continue
        cleaned.append(t)
    d["visible_text"] = cleaned


def is_conf(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 1


def validate(d):
    """Return (errors, flags). Errors trigger a retry; flags go to human review."""
    errors, flags = [], []
    for key in ["caption", "description", "retrieval_queries", "tags", "scene",
                "camera", "entities", "spatial_relations", "visible_text",
                "people", "privacy", "uncertainties"]:
        if key not in d:
            errors.append(f"missing key: {key}")
    if errors:
        return errors, flags

    rq = d["retrieval_queries"]
    if not (isinstance(rq, list) and len(rq) == 3 and all(isinstance(q, str) and q for q in rq)):
        errors.append("retrieval_queries must be a list of exactly 3 strings")
    if not isinstance(d["tags"], list):
        errors.append("tags must be a list")
    if not isinstance(d["scene"], dict):
        errors.append("scene must be an object")
    cam = d["camera"]
    if not isinstance(cam, dict) or cam.get("viewpoint") not in VIEWPOINTS:
        errors.append(f"camera.viewpoint must be one of {sorted(VIEWPOINTS)}")

    ids = set()
    ents = d["entities"]
    if not isinstance(ents, list) or not ents:
        errors.append("entities must be a non-empty list")
        ents = []
    for e in ents:
        if not isinstance(e, dict) or not e.get("id") or not e.get("label"):
            errors.append("every entity needs id and label")
            continue
        if e["id"] in ids:
            errors.append(f"duplicate entity id {e['id']}")
        ids.add(e["id"])
        if not isinstance(e.get("salience"), int) or not 1 <= e["salience"] <= 5:
            errors.append(f"entity {e['id']}: salience must be an integer 1-5")
        if not is_conf(e.get("confidence")):
            errors.append(f"entity {e['id']}: confidence must be 0-1")
        elif e.get("salience", 0) >= 4 and e["confidence"] < 0.5:
            flags.append(f"low confidence on major entity {e['id']} ({e['label']})")

    rels = d["spatial_relations"] if isinstance(d["spatial_relations"], list) else []
    for r in rels:
        if r.get("subject") not in ids or r.get("object") not in ids:
            errors.append(f"relation refers to unknown entity: {r}")

    texts = d["visible_text"]
    if not isinstance(texts, list):
        errors.append("visible_text must be a list")
        texts = []
    for t in texts:
        if t.get("legibility") not in LEGIBILITY:
            errors.append(f"visible_text legibility must be one of {sorted(LEGIBILITY)}")
        elif t["legibility"] == "partial":
            flags.append(f"partially legible text: {t.get('text')!r}")

    ppl = d["people"]
    if not isinstance(ppl, dict) or not isinstance(ppl.get("count"), int) or "faces_visible" not in ppl:
        errors.append("people needs integer count and faces_visible")
    pr = d["privacy"]
    if not isinstance(pr, dict) or pr.get("sensitivity") not in SENSITIVITY:
        errors.append(f"privacy.sensitivity must be one of {sorted(SENSITIVITY)}")
    if not isinstance(d["uncertainties"], list):
        errors.append("uncertainties must be a list")
    return errors, flags


def load_manifest():
    rows = {}
    if MANIFEST.exists():
        with open(MANIFEST, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = Path(row["file"].replace("\\", "/")).name
                rows[name] = row
    return rows


def call_model(client, photo_path, extra=""):
    mime = "image/png" if photo_path.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(photo_path.read_bytes()).decode()
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0.2,
        max_tokens=MAX_TOKENS,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT + extra},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
    )
    return resp.choices[0].message.content or "", getattr(resp, "usage", None)


def annotate(client, photo_path, manifest, force=False):
    photo_path = photo_path.resolve()
    collection = "personal" if "personal" in photo_path.parts else "world"
    photo_id = photo_path.stem
    out_path = OUT / collection / f"{photo_id}.json"
    if out_path.exists() and not force:
        return photo_id, "skipped (already annotated)"

    RAW.mkdir(parents=True, exist_ok=True)
    (OUT / collection).mkdir(parents=True, exist_ok=True)

    extra, data, errors, flags, usage, attempt = "", None, [], [], None, 0
    for attempt in (1, 2):
        try:
            text, usage = call_model(client, photo_path, extra)
        except Exception as e:
            return photo_id, f"API error: {e}"
        (RAW / f"{photo_id}_attempt{attempt}.txt").write_text(text, encoding="utf-8")
        try:
            data = extract_json(text)
            clean_text(data)
            errors, flags = validate(data)
        except Exception as e:
            data, errors = None, [f"could not parse JSON: {e}"]
        if not errors:
            break
        extra = ("\n\nYour previous answer had these problems. Fix them and return "
                 "the full JSON again:\n- " + "\n- ".join(errors))
    if errors:
        return photo_id, f"FAILED validation: {errors}"

    # Safety and consistency rules enforced in code, not trusted to the model.
    data["people"]["identified"] = False
    pr = data["privacy"]
    pr["people_count"] = data["people"]["count"]
    pr["faces_visible"] = data["people"]["faces_visible"]
    if collection == "personal" and data["people"]["count"] > 0 and pr["sensitivity"] == "low":
        pr["sensitivity"] = "medium"
    pr["share_default"] = (collection == "world") and pr["sensitivity"] != "high"

    provided = {"file": str(photo_path.relative_to(ROOT)).replace("\\", "/")}
    if collection == "world":
        m = manifest.get(photo_path.name)
        if m:
            provided.update({"license": m["license"], "author": m["author"],
                             "source_url": m["source_url"], "title": m["title"]})

    observed = {k: data[k] for k in [
        "caption", "description", "retrieval_queries", "tags", "scene", "camera",
        "entities", "spatial_relations", "visible_text", "people"]}
    record = {
        "photo_id": photo_id,
        "schema_version": SCHEMA_VERSION,
        "collection": collection,
        "provided": provided,
        "observed": observed,
        "inferred": {"landmarks": [], "place_candidates": [],
                     "uncertainties": data["uncertainties"]},
        "privacy": pr,
        "provenance": {
            "passes": [{
                "pass": "A", "model": MODEL, "prompt_version": PROMPT_VERSION,
                "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "raw_output_path": f"data/annotations/raw/{photo_id}_attempt{attempt}.txt",
                "tokens": getattr(usage, "total_tokens", None),
            }],
            "human_review": {"status": "flagged" if flags else "none", "notes": flags},
        },
    }
    out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    note = f" (flags: {len(flags)})" if flags else ""
    return photo_id, f"ok, {len(data['entities'])} entities{note}"


def main():
    ap = argparse.ArgumentParser(description="ReelWorld Pass A annotation")
    ap.add_argument("--photo", help="path to one photo")
    ap.add_argument("--collection", choices=["world", "personal"], help="annotate a whole collection")
    ap.add_argument("--limit", type=int, help="only the first N photos")
    ap.add_argument("--workers", type=int, default=1, help="parallel calls (try 4)")
    ap.add_argument("--force", action="store_true", help="re-annotate existing records")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    client = OpenAI(base_url=BASE_URL, api_key=os.environ["BASETEN_API_KEY"])
    manifest = load_manifest()

    if args.photo:
        photos = [Path(args.photo)]
    elif args.collection:
        exts = {".jpg", ".jpeg", ".png"}
        photos = sorted(p for p in (PHOTOS / args.collection).rglob("*") if p.suffix.lower() in exts)
    else:
        ap.error("give --photo or --collection")
    if args.limit:
        photos = photos[: args.limit]

    print(f"Annotating {len(photos)} photo(s) with {MODEL} ({PROMPT_VERSION})")
    start = time.time()

    def run(p):
        pid, status = annotate(client, p, manifest, args.force)
        print(f"{pid}: {status}", flush=True)
        return status

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        statuses = list(pool.map(run, photos))

    ok = sum(s.startswith("ok") for s in statuses)
    print(f"Done in {time.time() - start:.0f}s. {ok} annotated, "
          f"{len(statuses) - ok} skipped or failed. Records in {OUT}")


if __name__ == "__main__":
    main()