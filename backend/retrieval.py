"""
ReelWorld: retrieval core (build index, search, and "find like this photo"), v2.

Works on the annotation records in data/annotations (Pass A + Pass B). Embeds a
search document built from each record, then ranks with a hybrid score.

"like" (the bridge) separates a photo's MAIN SUBJECT from places that only show
up in the background:
  * a photo whose subject is a landmark visible in your photo ranks highest
  * the same specific place ranks next; a broad district counts for less
  * photos taken from the place you were standing rank below subject matches
  * a shared landmark that is only background adds a small boost
  * "another angle" is only claimed for subject matches seen from a new viewpoint

Run from the project root:

  1. Build (or rebuild after any annotation change):
       python backend\\retrieval.py build

  2. Search with plain language:
       python backend\\retrieval.py search "busy market with piles of watermelons"
       python backend\\retrieval.py search "view of the city from above" --collection world --top 8

  3. The bridge:
       python backend\\retrieval.py like personal_006 --collection world --top 12
       python backend\\retrieval.py like personal_002 --collection world
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
ANN = ROOT / "data" / "annotations"
INDEX = ROOT / "data" / "index"
MODEL_NAME = "BAAI/bge-small-en-v1.5"

STOPWORDS = {
    "the", "and", "with", "for", "from", "that", "this", "show", "find", "photo",
    "photos", "picture", "pictures", "image", "images", "want", "see", "any", "some",
    "are", "was", "were", "has", "have", "into", "over", "near", "like", "looking",
    "there", "their", "them", "than", "then", "about", "where", "which", "what",
}

# "like" scoring weights
W_SUBJECT_IS_MY_LANDMARK = 0.60   # their main subject is a landmark visible in my photo
W_SAME_SPECIFIC_PLACE = 0.60      # same specific place (a landmark, park, street, ...)
W_SAME_BROAD_AREA = 0.20          # same district or city only
W_MY_SUBJECT_IN_THEIR_BG = 0.20   # my main subject shows up behind their subject
W_SHARED_BACKGROUND = 0.10        # a shared landmark, background in both
W_RELATED_AREA = 0.10             # one place sits inside the other (building in district)
W_TAKEN_FROM = 0.15               # photographed from the place the other photo shows
P_INTERIOR = 0.05                 # interiors rarely help an outdoor photo


# ---------- building the index ----------

def load_records():
    for col in ("world", "personal"):
        for p in sorted((ANN / col).glob("*.json")):
            yield json.loads(p.read_text(encoding="utf-8"))


def search_text(rec):
    obs, inf = rec["observed"], rec["inferred"]
    parts = [obs["caption"], obs["description"]]
    parts.append("Tags: " + ", ".join(obs.get("tags", [])))
    things = []
    for e in obs.get("entities", []):
        if e.get("salience", 0) >= 2:
            attrs = ", ".join(e.get("attributes", [])[:3])
            things.append(f"{e['label']} ({attrs})" if attrs else e["label"])
    parts.append("Things: " + "; ".join(things))
    signs = [t["text"] for t in obs.get("visible_text", []) if t.get("legibility") != "unreadable"]
    if signs:
        parts.append("Signs: " + "; ".join(signs))
    place = inf.get("place")
    if place:
        parts.append(f"Place: {place['name']}")
    taken = inf.get("taken_from")
    if taken:
        parts.append(f"Photographed from: {taken['name']}")
    lms = [l["name"] for l in inf.get("landmarks", [])]
    if lms:
        parts.append("Landmarks: " + "; ".join(lms))
    sc, cam = obs.get("scene", {}), obs.get("camera", {})
    parts.append(f"Scene: {sc.get('type')}, {sc.get('setting')}, {sc.get('time_of_day')}, "
                 f"crowd {sc.get('crowd_level')}. Viewpoint: {cam.get('viewpoint')}, "
                 f"{cam.get('distance')} distance, facing {cam.get('facing')}.")
    parts.append(f"People count: {obs.get('people', {}).get('count', 0)}")
    cc = [c["term"] for c in inf.get("cultural_context", [])]
    if cc:
        parts.append("Local terms: " + ", ".join(cc))
    parts.append("Described as: " + " | ".join(obs.get("retrieval_queries", [])))
    return "\n".join(p for p in parts if p)


def meta_for(rec, text):
    obs, inf = rec["observed"], rec["inferred"]
    return {
        "photo_id": rec["photo_id"],
        "collection": rec["collection"],
        "file": rec["provided"]["file"],
        "caption": obs["caption"],
        "place_key": inf.get("place_key"),
        "place_name": (inf.get("place") or {}).get("name"),
        "taken_from_key": (inf.get("taken_from") or {}).get("key"),
        "landmark_keys": sorted({l["key"] for l in inf.get("landmarks", [])
                                 if l.get("key") and l.get("status") == "confirmed"}),
        "viewpoint": obs["camera"].get("viewpoint"),
        "scene_type": obs["scene"].get("type"),
        "people_count": obs["people"].get("count", 0),
        "lex": text.lower(),
    }


def get_model():
    from fastembed import TextEmbedding
    return TextEmbedding(MODEL_NAME)


def build():
    recs = list(load_records())
    texts = [search_text(r) for r in recs]
    print(f"Embedding {len(recs)} records with {MODEL_NAME} ...")
    model = get_model()
    vecs = np.array(list(model.embed(texts)), dtype="float32")
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    INDEX.mkdir(parents=True, exist_ok=True)
    np.save(INDEX / "embeddings.npy", vecs)
    meta = [meta_for(r, t) for r, t in zip(recs, texts)]
    (INDEX / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    worlds = sum(1 for m in meta if m["collection"] == "world")
    print(f"Done. {worlds} world + {len(meta) - worlds} personal photos indexed in {INDEX}")


# ---------- searching ----------

def load_index():
    vecs = np.load(INDEX / "embeddings.npy")
    meta = json.loads((INDEX / "meta.json").read_text(encoding="utf-8"))
    return vecs, meta


def tokens(query):
    return [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 3 and w not in STOPWORDS]


def search(query, collection=None, top=5, vecs=None, meta=None, model=None):
    if vecs is None:
        vecs, meta = load_index()
    model = model or get_model()
    q = np.array(next(iter(model.query_embed(query))), dtype="float32")
    q /= np.linalg.norm(q)
    cos = vecs @ q
    toks = tokens(query)
    results = []
    for i, m in enumerate(meta):
        if collection and m["collection"] != collection:
            continue
        lex = (sum(1 for t in toks if t in m["lex"]) / len(toks)) if toks else 0.0
        score = float(cos[i]) + 0.25 * lex
        results.append({**m, "score": score, "meaning": float(cos[i]), "keywords": lex})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top]


def depth(key):
    return len(key.split("/")) if key else 0


def is_specific(key):
    """True for every place key except the known broad ones (country, city, CBD)."""
    return key not in ("kenya", "kenya/nairobi", "kenya/mombasa",
                       "kenya/kisumu", "kenya/nakuru", "kenya/nairobi/cbd")


def related_area(a, b):
    """True if one key sits inside the other, e.g. kenya/nairobi/cbd and kenya/nairobi/cbd/kicc."""
    if not (a and b and a != b):
        return False
    if a.startswith(b + "/"):
        parent = b
    elif b.startswith(a + "/"):
        parent = a
    else:
        return False
    return len(parent.split("/")) >= 3


def like(photo_id, collection="world", top=8, vecs=None, meta=None):
    """Photos related to photo_id, ranked by subject match first, background second."""
    if vecs is None:
        vecs, meta = load_index()
    idx = next((i for i, m in enumerate(meta) if m["photo_id"] == photo_id), None)
    if idx is None:
        raise SystemExit(f"No indexed photo called {photo_id}")
    src = meta[idx]
    src_lms = set(src["landmark_keys"])
    results = []
    for i, m in enumerate(meta):
        if i == idx or (collection and m["collection"] != collection):
            continue
        score = float(vecs[i] @ vecs[idx])
        reasons, subject_match = [], False
        cand_lms = set(m["landmark_keys"])

        if src["place_key"] and src["place_key"] == m["place_key"]:
            if is_specific(m["place_key"]):
                score += W_SAME_SPECIFIC_PLACE
                reasons.append(f"same place: {m['place_key']}")
                subject_match = True
            else:
                score += W_SAME_BROAD_AREA
                reasons.append(f"same area: {m['place_key']}")
        elif m["place_key"] in src_lms:
            score += W_SUBJECT_IS_MY_LANDMARK
            reasons.append(f"shows a landmark in your photo: {m['place_key']}")
            subject_match = True
        elif src["place_key"] in cand_lms:
            score += W_MY_SUBJECT_IN_THEIR_BG
            reasons.append(f"your photo's place is visible in it: {src['place_key']}")
        elif related_area(src["place_key"], m["place_key"]):
            score += W_RELATED_AREA
            reasons.append(f"same area: {m['place_key']}")

        shared_bg = (src_lms & cand_lms) - {m["place_key"], src["place_key"]}
        if shared_bg and not subject_match:
            score += W_SHARED_BACKGROUND
            reasons.append("also shows: " + ", ".join(sorted(shared_bg)))

        if src["taken_from_key"] and src["taken_from_key"] == m["place_key"]:
            score += W_TAKEN_FROM
            reasons.append(f"shows where your photo was taken: {m['place_key']}")
        elif src["place_key"] and src["place_key"] == m["taken_from_key"]:
            score += W_TAKEN_FROM
            reasons.append(f"taken from the place in your photo: {src['place_key']}")

        if subject_match and src["viewpoint"] != m["viewpoint"]:
            reasons.append(f"another angle ({m['viewpoint']} vs {src['viewpoint']})")
        if m["viewpoint"] == "interior" and src["viewpoint"] != "interior":
            score -= P_INTERIOR
        results.append({**m, "score": score, "reasons": reasons})
    results.sort(key=lambda r: r["score"], reverse=True)
    return src, results[:top]


# ---------- command line ----------

def show(results, with_reasons=False):
    for n, r in enumerate(results, 1):
        extra = ""
        if with_reasons and r.get("reasons"):
            extra = "\n      " + " | ".join(r["reasons"])
        print(f"{n:2d}. {r['photo_id']:<14} {r['score']:.2f}  [{r['viewpoint']}] "
              f"{(r['caption'] or '')[:95]}{extra}")


def main():
    ap = argparse.ArgumentParser(description="ReelWorld retrieval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="build the search index from the annotations")
    s = sub.add_parser("search", help="search with plain language")
    s.add_argument("query")
    s.add_argument("--collection", choices=["world", "personal"])
    s.add_argument("--top", type=int, default=5)
    l = sub.add_parser("like", help="find photos related to one photo")
    l.add_argument("photo_id")
    l.add_argument("--collection", choices=["world", "personal"], default="world")
    l.add_argument("--top", type=int, default=8)
    args = ap.parse_args()

    if args.cmd == "build":
        build()
    elif args.cmd == "search":
        show(search(args.query, args.collection, args.top))
    else:
        src, res = like(args.photo_id, args.collection, args.top)
        print(f"Like {src['photo_id']} ({src['collection']}): {src['caption']}")
        print(f"place={src['place_key']}  taken_from={src['taken_from_key']}  "
              f"landmarks={src['landmark_keys']}  viewpoint={src['viewpoint']}\n")
        show(res, with_reasons=True)


if __name__ == "__main__":
    main()