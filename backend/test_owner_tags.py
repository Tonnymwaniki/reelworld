"""Checks for backend/owner_tags.py.
Run from the project root:  python backend/test_owner_tags.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import owner_tags as tags  # noqa: E402

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


check(tags.get_owner({}) == {"present": None, "position": None}, "missing reads unreviewed")
check(tags.owner_present_of({}) is None, "present helper None")
check(tags.owner_present_of({"provided": {"owner": {"present": True}}}) is True,
      "present helper True")

r = tags.set_owner({}, True, "left")
own = r["provided"]["owner"]
check(own["present"] is True and own["position"] == "left", "set present + position")
check(bool(own["tagged_at"]), "tagged_at set")

r2 = tags.set_owner({}, False, "right")
check(r2["provided"]["owner"] == {"present": False, "position": None,
                                  "tagged_at": r2["provided"]["owner"]["tagged_at"]},
      "position forced null when absent")

for bad_pos in ("middle", "", 1):
    try:
        tags.set_owner({}, True, bad_pos)
        check(False, f"reject position {bad_pos!r}")
    except ValueError:
        check(True, f"reject position {bad_pos!r}")

for bad_present in (None, 1, "yes"):
    try:
        tags.set_owner({}, bad_present)
        check(False, f"reject present {bad_present!r}")
    except ValueError:
        check(True, f"reject present {bad_present!r}")

orig = {"provided": {"file": "x.jpg"}}
out = tags.set_owner(orig, True)
check("owner" not in orig["provided"] and out["provided"]["file"] == "x.jpg",
      "set copies, keeps file")

check(tags.clear_owner(out)["provided"] == {"file": "x.jpg"}, "clear removes owner")
check(tags.clear_owner({}) == {}, "clear empty is empty")

weird = {"provided": {"owner": {"present": "yes", "position": "up"}}}
check(tags.get_owner(weird) == {"present": None, "position": None},
      "malformed reads unreviewed")

print(f"test_owner_tags.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
