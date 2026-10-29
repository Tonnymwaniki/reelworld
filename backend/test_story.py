"""Focused checks for story heading validation (backend/api.py).

Covers _heading_problems only: pure logic, no model or database.
Run from the project root:  python backend/test_story.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import _heading_problems  # noqa: E402  (needs the sys.path line above)


def fact(time=None, setting=None, viewpoint=None):
    return {"time": time, "setting": setting, "viewpoint": viewpoint}


DAY_OUT = fact("day", "outdoor", "ground")
DAY_HIGH = fact("day", "outdoor", "elevated")
NIGHT_OUT = fact("night", "outdoor", "ground")
DUSK_OUT = fact("twilight", "outdoor", "elevated")
INDOOR = fact("day", "indoor", "ground")
MIXED = fact("day", "mixed", "ground")
BLANK = fact(None, None, None)

CASES = [
    # (heading, facts, min_problems, max_problems, label)
    ("City Lights at Night", [DAY_OUT, DAY_HIGH], 1, 1, "night-vs-day"),
    ("City Lights at Night", [NIGHT_OUT, DAY_OUT], 0, 0, "night-partial-support"),
    ("City Lights at Night", [NIGHT_OUT], 0, 0, "night-supported"),
    ("Morning Market", [NIGHT_OUT, NIGHT_OUT], 1, 1, "day-vs-night"),
    ("Morning Market", [DAY_OUT], 0, 0, "day-supported"),
    ("Evening Glow", [DAY_OUT, DAY_HIGH], 1, 1, "twilight-vs-day"),
    ("Evening Glow", [DUSK_OUT], 0, 0, "twilight-supported"),
    ("Inside the Hall", [DAY_OUT], 1, 1, "indoor-vs-outdoor"),
    ("Inside the Hall", [MIXED], 0, 0, "indoor-mixed-abstains"),
    ("Street Life", [INDOOR], 1, 1, "outdoor-vs-indoor"),
    ("Street Life", [DAY_OUT], 0, 0, "outdoor-supported"),
    ("The City From Above", [DAY_OUT], 1, 1, "above-vs-ground"),
    ("The City From Above", [DAY_HIGH], 0, 0, "above-supported"),
    ("Elevated Views of Avenues", [DAY_OUT], 1, 1, "elevated-vs-ground"),
    ("Elevated Views of Avenues", [DAY_HIGH], 0, 0, "elevated-supported"),
    ("At Street Level", [fact("day", "outdoor", "aerial")], 1, 1, "ground-vs-aerial"),
    ("City Lights at Night", [BLANK, BLANK], 0, 0, "unknown-abstains"),
    ("Green Heart of the City", [DAY_OUT], 0, 0, "no-claims"),
]

fails = 0
for heading, facts, lo, hi, label in CASES:
    n = len(_heading_problems(heading, facts))
    if not (lo <= n <= hi):
        fails += 1
        print(f"FAIL {label}: {heading!r} -> {n} problems, want {lo}..{hi}")
print(f"test_story.py: {len(CASES) - fails}/{len(CASES)} checks passed")
sys.exit(1 if fails else 0)
