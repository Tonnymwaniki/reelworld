"""Record the 60-second tour: run three real prompts against the engine once
and save the responses to data/tour/step{1,2,3}.json. The tour overlay plays
these back with a "Saved example, not a live search" banner.

Nothing is invented: prompts are the tour's; every photo, score, place and
credit comes from the live engine. Re-running overwrites the snapshots.

Run from the project root (needs .env + network, takes a few minutes):
  python scripts/record_tour.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from api import _photo_detail_shape, attach_credits, bridge, photo_url, public_row  # noqa: E402
from chat import Engine  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "tour"

STEP1 = "A modernist building with a fluted tower and amphitheatre in Nairobi"
STEP2 = "The market with wooden carvings and baskets near city hall"
STEP3_PHOTO = "personal_006"


def detail(eng, photo_id):
    row = eng.fetch_photo(photo_id, "photo_id,collection,file,record")
    if not row:
        raise SystemExit(f"tour needs {photo_id} but it is not in the archive")
    return _photo_detail_shape(row)


def shaped(eng, results):
    rows = [public_row(r) for r in results]
    attach_credits(rows)
    out = []
    for r in rows:
        d = detail(eng, r["photo_id"])
        src = r.get("src") or (photo_url(r.get("file")) if r.get("file") else None)
        out.append({"photo_id": r["photo_id"], "src": src,
                    "caption": r.get("caption"), "score": r.get("score"),
                    "reasons": r.get("reasons"), "credit": r.get("credit"),
                    "place": d.get("place")})
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    eng = Engine()

    print(f"step 1: {STEP1!r}", flush=True)
    out1 = eng.turn(STEP1)
    if not out1["results"]:
        raise SystemExit("step 1 found no photos; aborting (tour needs real results)")
    hero = detail(eng, out1["results"][0]["photo_id"])
    (OUT / "step1.json").write_text(json.dumps({
        "prompt": STEP1, "text": out1["text"], "kind": out1["kind"],
        "results": shaped(eng, out1["results"]),
        "hero": {"photo_id": hero["photo_id"], "src": hero.get("src"),
                 "caption": hero.get("caption"), "place": hero.get("place"),
                 "uncertainties": hero.get("uncertainties"),
                 "credit": hero.get("credit")}}, ensure_ascii=False), encoding="utf-8")
    print(f"  kind={out1['kind']} hero={hero['photo_id']}", flush=True)

    print(f"step 2: {STEP2!r}", flush=True)
    eng.state["rejected"] = set()
    out2 = eng.turn(STEP2)
    if not out2["results"]:
        raise SystemExit("step 2 found no photos; aborting (tour needs real results)")
    hero2 = detail(eng, out2["results"][0]["photo_id"])
    (OUT / "step2.json").write_text(json.dumps({
        "prompt": STEP2, "text": out2["text"], "kind": out2["kind"],
        "results": shaped(eng, out2["results"]),
        "hero": {"photo_id": hero2["photo_id"], "src": hero2.get("src"),
                 "caption": hero2.get("caption"), "place": hero2.get("place"),
                 "uncertainties": hero2.get("uncertainties"),
                 "credit": hero2.get("credit")}}, ensure_ascii=False), encoding="utf-8")
    print(f"  kind={out2['kind']} hero={hero2['photo_id']}", flush=True)

    print(f"step 3: bridge for {STEP3_PHOTO}", flush=True)
    groups = bridge(STEP3_PHOTO, 8)["groups"]
    mine = detail(eng, STEP3_PHOTO)
    link = None
    for gname in ("same_place", "another_angle", "taken_from_here", "similar_look"):
        if groups.get(gname):
            link = {"group": gname, "item": groups[gname][0]}
            break
    if link is None:
        raise SystemExit(f"step 3: {STEP3_PHOTO} has no bridge matches; aborting")
    theirs = detail(eng, link["item"]["photo_id"])
    (OUT / "step3.json").write_text(json.dumps({
        "prompt": f"Connecting {STEP3_PHOTO} to the world",
        "mine": {"photo_id": mine["photo_id"], "src": mine.get("src"),
                 "caption": mine.get("caption"), "place": mine.get("place")},
        "link": {"group": link["group"], "reason": link["item"].get("reason_text")},
        "theirs": {"photo_id": theirs["photo_id"], "src": theirs.get("src"),
                   "caption": theirs.get("caption"), "place": theirs.get("place"),
                   "credit": theirs.get("credit")}}, ensure_ascii=False), encoding="utf-8")
    print(f"  link={link['group']} {theirs['photo_id']}", flush=True)
    print("tour recorded to data/tour/")


if __name__ == "__main__":
    main()
