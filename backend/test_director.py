"""Focused checks for the director pass (backend/director.py).

Summaries, prompt, strict validation, retry, fallback: no model
(llm.ask is stubbed). Run from the project root:
  python backend/test_director.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import director as director_mod  # noqa: E402  (needs the sys.path line above)
import llm  # noqa: E402

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


REC = {"observed": {
    "scene": {"type": "street", "setting": "outdoor", "time_of_day": "day"},
    "entities": [{"label": "bus", "salience": 5}, {"label": "crowd", "salience": 3}],
    "visible_text": [{"text": "KICC", "legibility": "clear"}],
    "people": {"count": 12}},
    "inferred": {
    "place": {"name": "KICC", "status": "confirmed"},
    "taken_from": {"name": "City Hall Way"}}}

b = director_mod.summarize_record("p1", "ground_level", REC)
check(b["things"] == ["bus", "crowd"] and b["signs"] == ["KICC (clear)"]
      and b["people"] == 12 and b["taken_from"] == "City Hall Way"
      and b["place"] == "KICC" and b["scene"] == "street, outdoor, day",
      "record summary")
b = director_mod.summarize_record("p2", None, {})
check(b["place"] == "unknown place" and b["taken_from"] is None
      and b["things"] == [] and b["people"] == 0, "empty record summary")
check(director_mod.normalize_style("field_notes") == "field-notes",
      "style alias")
try:
    director_mod.normalize_style("noir")
    check(False, "bad style raises")
except ValueError:
    check(True, "bad style raises")

BRIEFS = [{"photo_id": f"p{i}", "place": "KICC", "place_status": "confirmed",
           "viewpoint": "ground_level", "scene": "street", "things": ["bus"],
           "signs": [], "taken_from": None, "people": 0} for i in (1, 2, 3, 4)]
FOCALS = {f"p{i}": {"mood": "busy", "confidence": 0.8} for i in (1, 2, 3, 4)}
prompt = director_mod.build_director_prompt("my day", "postcard", "short",
                                            BRIEFS, FOCALS)
check("arrival" in prompt and "p3" in prompt and "busy" in prompt
      and "3 to 6" in prompt, "prompt carries arc, ids, moods")

GOOD = {"title": "My day", "cover": "p1",
        "beats": [{"role": "establish", "intent": "arrive", "photo_ids": ["p1", "p2"],
                   "pacing": "slow", "camera": "push_in", "reason": "sets the scene"},
                  {"role": "resolve", "intent": "leave", "photo_ids": ["p3", "p4"],
                   "pacing": "medium", "camera": "pull_back", "reason": "closes"}]}
IDS = ["p1", "p2", "p3", "p4"]
sheet, problems = director_mod.validate_beatsheet(GOOD, IDS, "short")
check(sheet is not None and sheet["cover"] == "p1"
      and len(sheet["beats"]) == 2, "valid sheet passes")


def invalid(mutator, label):
    bad = json.loads(json.dumps(GOOD))
    mutator(bad)
    sheet, problems = director_mod.validate_beatsheet(bad, IDS, "short")
    check(sheet is None and problems, label)


invalid(lambda d: d["beats"].__setitem__(0, {**d["beats"][0], "role": "fly"}),
        "bad role rejected")
invalid(lambda d: d["beats"].__setitem__(0, {**d["beats"][0], "pacing": "warp"}),
        "bad pacing rejected")
invalid(lambda d: d["beats"].__setitem__(0, {**d["beats"][0], "camera": "zoom"}),
        "bad camera rejected")
invalid(lambda d: d["beats"][1].__setitem__("photo_ids", ["p2", "p9"]),
        "unknown photo rejected")
invalid(lambda d: d["beats"][1].__setitem__("photo_ids", ["p2", "p3"]),
        "repeated photo rejected")
invalid(lambda d: d.update({"cover": "p9"}), "bad cover rejected")
invalid(lambda d: d.update({"beats": []}), "empty beats rejected")
many = {"title": "t", "cover": "p1",
        "beats": [{"role": "build", "intent": "x",
                   "photo_ids": chunk, "pacing": "quick",
                   "camera": "hold", "reason": "y"}
                  for chunk in (["p1", "p2"], ["p3", "p4"],
                                ["p5", "p6"], ["p7"])]}
sheet, problems = director_mod.validate_beatsheet(
    many, [f"p{i}" for i in range(1, 8)], "short")
check(sheet is None and any("7 photos" in p for p in problems),
      "oversize rejected")

fb = director_mod.fallback_beats("my day", "postcard", "short", BRIEFS, FOCALS)
sheet, problems = director_mod.validate_beatsheet(fb, IDS, "short")
check(sheet is not None and fb["cover"] == "p1", "fallback valid")

orig_ask = llm.ask
try:
    llm.ask = lambda *a, **k: {"text": json.dumps(GOOD)}
    sheet, source = director_mod.plan_beats("my day", "postcard", "short",
                                            BRIEFS, FOCALS, trace=[])
    check(source == "director" and sheet["title"] == "My day", "director plans")
    replies = ["not json{{", json.dumps(GOOD)]
    llm.ask = lambda *a, **k: {"text": replies.pop(0)}
    trace = []
    sheet, source = director_mod.plan_beats("my day", "postcard", "short",
                                            BRIEFS, FOCALS, trace=trace)
    check(source == "director-retry" and len(trace) == 2, "retry recovers")
    llm.ask = lambda *a, **k: {"text": "still bad"}
    trace = []
    sheet, source = director_mod.plan_beats("my day", "postcard", "short",
                                            BRIEFS, FOCALS, trace=trace)
    check(source == "fallback" and sheet["cover"] == "p1"
          and any("fallback" in t["detail"] for t in trace), "fallback noted")

    def spent(*a, **k):
        raise llm.LLMBudgetSpent("spent")
    llm.ask = spent
    try:
        director_mod.plan_beats("my day", "postcard", "short", BRIEFS, FOCALS)
        check(False, "budget propagates")
    except llm.LLMBudgetSpent:
        check(True, "budget propagates")
    try:
        director_mod.plan_beats("x", "postcard", "short", [], {})
        check(False, "empty briefs raise")
    except ValueError:
        check(True, "empty briefs raise")
finally:
    llm.ask = orig_ask

print(f"test_director.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
