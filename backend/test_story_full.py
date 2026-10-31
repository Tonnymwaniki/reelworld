"""Regression checks for api._story_full owner-heading flags.

A headed chapter must never crash the story detail, and a heading
that names the owner (or uses you/I) on an untagged photo must be
flagged. No database: _photos_by_ids and the profile are stubbed.
Run from the project root:  python backend/test_story_full.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import api  # noqa: E402
import owner_profile as owner_profile_mod  # noqa: E402

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


def rec(present):
    return {
        "observed": {
            "caption": "A person walks.", "description": "",
            "scene": {"setting": "outdoor", "time_of_day": "daytime"},
            "camera": {}, "entities": [], "spatial_relations": [],
            "visible_text": [], "people": {"count": 1},
        },
        "inferred": {"landmarks": [], "place": {}, "taken_from": {},
                     "cultural_context": "", "uncertainties": []},
        "provided": {"owner": {"present": present}},
    }


def row(pid, present):
    return {"photo_id": pid, "collection": "personal",
            "file": f"data/photos/personal/{pid}.jpg",
            "caption": "A person walks.", "viewpoint": "ground_level",
            "place_name": "Test place", "record": rec(present)}


ROWS = {"t1": row("t1", None), "t2": row("t2", True)}
HINT = "refresh the narration"

real_lookup = api._photos_by_ids
real_profile = owner_profile_mod.load_profile
api._photos_by_ids = lambda ids, cols="": {i: ROWS[i] for i in ids if i in ROWS}  # noqa: E731
owner_profile_mod.load_profile = lambda: {"name": "Tonny", "refer_as": "name"}  # noqa: E731
try:
    out = api._story_full({"chapters": [
        {"photo_id": "t1", "heading": "Tonny at the gate", "text": "x"},
        {"photo_id": "t2", "heading": "Tonny at the gate", "text": "x"},
        {"photo_id": "t1", "heading": "A quiet gate", "text": "x"},
    ]})
    probs = out["problems"]
    check(any(HINT in p for p in probs.get("0", [])),
          "untagged heading flagged")
    check(not any(HINT in p for p in probs.get("1", [])),
          "tagged heading not flagged")
    check("2" not in probs, "plain heading clean")
    pub = {"status": "published", "include_name": False,
           "title": "Tonny at KICC", "chapters": [
               {"photo_id": "t2", "heading": "Tonny at the gate",
                "text": "Tonny waves."}]}
    shown = api._story_full(pub, True)
    check(shown["story"]["title"] == "the photographer at KICC"
          and shown["chapters"][0]["text"] == "the photographer waves."
          and "Tonny" not in shown["chapters"][0]["heading"],
          "public hides name")
    check(pub["title"] == "Tonny at KICC", "stored story untouched")
    kept = api._story_full(pub, False)
    check("Tonny" in kept["chapters"][0]["text"], "owner view keeps name")
    opt = api._story_full(dict(pub, include_name=True), True)
    check("Tonny" in opt["chapters"][0]["text"], "opt-in keeps name public")
    draft = api._story_full(dict(pub, status="draft"), True)
    check("Tonny" in draft["chapters"][0]["text"], "draft never rewritten")
    owner_profile_mod.load_profile = lambda: (_ for _ in ()).throw(  # noqa: E731
        RuntimeError("no profile"))
    out2 = api._story_full({"chapters": [
        {"photo_id": "t1", "heading": "Tonny at the gate", "text": "x"}]})
    check(out2["problems"] == {}, "no profile, no owner flags")
finally:
    api._photos_by_ids = real_lookup
    owner_profile_mod.load_profile = real_profile

print(f"test_story_full.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
