"""Focused checks for connected-link helpers (backend/api.py).

Covers ring_of, link_facts, kinds_of: pure logic, no database.
Run from the project root:  python backend/test_links.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import kinds_of, link_facts, ring_of  # noqa: E402  (needs the sys.path line above)

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


SRC = {"place_key": "kenya/nairobi/kicc", "taken_from_key": None,
       "landmark_keys": ["kenya/nairobi/city-hall"], "viewpoint": "ground_level"}


def cand(**kw):
    d = {"place_key": None, "taken_from_key": None, "landmark_keys": [],
         "viewpoint": "ground_level"}
    d.update(kw)
    return d


check(ring_of(SRC, cand(place_key="kenya/nairobi/kicc")) == "same_place", "ring r1")
check(ring_of(SRC, cand(place_key="kenya/nairobi/kicc",
                        viewpoint="elevated")) == "another_angle", "ring r2")
check(ring_of(cand(place_key="kenya/nairobi/kicc", taken_from_key="kenya/nairobi/uhuru-park",
                   landmark_keys=[], viewpoint="ground_level"),
              cand(place_key="kenya/nairobi/uhuru-park")) == "where_stood", "ring r3")
check(ring_of(SRC, cand(place_key="kenya/nairobi/other",
                        landmark_keys=["kenya/nairobi/kicc"])) == "in_background", "ring r4a")
check(ring_of(SRC, cand(place_key="kenya/nairobi/city-hall")) == "in_background", "ring r4b")
check(ring_of(SRC, cand(place_key="kenya/nairobi/other")) == "similar", "ring r5")
check(ring_of(cand(place_key="kenya/nairobi", landmark_keys=[], viewpoint="ground_level"),
              cand(place_key="kenya/nairobi")) == "similar", "broad area is not r1")

RECA = {"observed": {"visible_text": [{"text": "NAIROBI CITY HALL"}],
                     "entities": [{"label": "bus"}]},
        "inferred": {"place": {"key": "k", "name": "City Hall"}, "taken_from": {},
                     "landmarks": [{"key": "lk", "name": "Tower"}]}}
RECB = {"observed": {"visible_text": [{"text": "nairobi city hall!"}],
                     "entities": [{"label": "Bus"}, {"label": "car"}]},
        "inferred": {"place": {"key": "k", "name": "City Hall"}, "taken_from": {},
                     "landmarks": [{"key": "lk", "name": "Tower"}]}}
f = link_facts(RECA, RECB)
check(f["same_place"] and f["shared_signs"] == ["nairobi city hall"]
      and f["shared_entities"] == ["bus"]
      and f["shared_landmarks"] == ["Tower"], "facts shared")
f2 = link_facts(RECA, {"observed": {}, "inferred": {}})
check(not f2["same_place"] and f2["shared_signs"] == []
      and f2["shared_landmarks"] == [] and f2["shared_entities"] == [], "facts empty")

check(kinds_of(f, "ground_level", "elevated")
      == ["another_angle", "shared_landmark", "shared_sign"], "kinds angle+shared")
check(kinds_of(f2) == [], "kinds none")

print(f"test_links.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
