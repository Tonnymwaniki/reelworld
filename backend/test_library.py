"""Focused checks for library helpers (backend/api.py).

cluster_bursts, apply_correction, gap_list, _theme_of: pure logic,
no database. Run from the project root:  python backend/test_library.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import (LibraryError, _theme_of, apply_correction,  # noqa: E402
                 cluster_bursts, gap_list)

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


def expect(status, fn, label):
    global fails, total
    total += 1
    try:
        fn()
    except LibraryError as e:
        if e.status != status:
            fails += 1
            print(f"FAIL {label}: status {e.status}, want {status}")
    except Exception as e:  # noqa: BLE001 (any other error is a failure)
        fails += 1
        print(f"FAIL {label}: {type(e).__name__} {e}")
    else:
        fails += 1
        print(f"FAIL {label}: no error raised")


check(cluster_bursts(["a", "b", "c"], {("a", "b"): 0.9}) == [["a", "b"]], "burst pair")
check(cluster_bursts(["a", "b", "c"], {("a", "b"): 0.9, ("b", "c"): 0.9,
                                       ("a", "c"): 0.5}) == [["a", "b", "c"]],
      "burst transitive")
check(cluster_bursts(["a", "b", "c", "d"], {("a", "b"): 0.9, ("c", "d"): 0.86})
      == [["a", "b"], ["c", "d"]], "burst two")
check(cluster_bursts(["a", "b"], {("a", "b"): 0.5}) == [], "burst below floor")

REC = {"observed": {"caption": "old"},
       "inferred": {"place": {"key": "k", "name": "N", "status": "confirmed",
                              "evidence": [], "confidence": 0.9}}}
new, changed = apply_correction(REC, {"caption": " new ", "place_key": "",
                                      "place_name": "", "note": ""})
check(changed == ["caption"] and new["observed"]["caption"] == "new"
      and REC["observed"]["caption"] == "old", "correct caption")
new2, ch2 = apply_correction(REC, {"caption": "", "place_key": "K2",
                                   "place_name": "Place Two", "note": "typo"})
pl = new2["inferred"]["place"]
check(ch2 == ["place"] and pl["key"] == "k2" and pl["status"] == "human_review"
      and "typo" in pl["evidence"][0], "correct place")
expect(400, lambda: apply_correction(REC, {"caption": " ", "place_key": "",
                                           "place_name": "", "note": ""}),
       "correct empty 400")

ROWS = [{"photo_id": "w1", "place_key": "k/a", "viewpoint": "ground_level"}]
REG = {"k/a": {"name": "A", "type": "building"}, "k/b": {"name": "B", "type": "park"}}
g = gap_list(ROWS, REG)
check([x["key"] for x in g] == ["k/b", "k/a"], "gaps order empties first")
check(g[0]["kinds"] == ["empty"] and g[0]["missing"] == ["all"], "gap empty")
check("single" in g[1]["kinds"] and "interior" in g[1]["kinds"], "gap single+interior")
check(gap_list([], {"unknown/x": {"name": "X"}}) == [], "unknown skipped")

check(_theme_of("data/photos/world/market/m_001.jpg") == "market", "theme path")
check(_theme_of("C:\\x\\world\\cbd\\c.jpg") == "cbd", "theme windows")
check(_theme_of("data/photos/personal/p.jpg") == "", "theme personal blank")

print(f"test_library.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
