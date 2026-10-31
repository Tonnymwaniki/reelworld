"""Checks for backend/owner_profile.py.
Run from the project root:  python backend/test_owner_profile.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import owner_profile as prof  # noqa: E402

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


tmp = tempfile.TemporaryDirectory()
prof.PROFILE_PATH = Path(tmp.name) / "profile.json"

check(prof.load_profile() is None, "no profile at first")
check(prof.delete_profile() is False, "delete missing is False")

p = prof.save_profile("  Tonny ", refer_as="name")
check(p["name"] == "Tonny", "name stripped")
check(p["refer_as"] == "name", "refer_as stored")
check(bool(p["created_at"]) and bool(p["updated_at"]), "timestamps set")
check(prof.load_profile() == p, "roundtrip")

p2 = prof.save_profile("Tonny M", refer_as=None)
check(p2["refer_as"] == "name", "refer_as kept when omitted")
check(p2["created_at"] == p["created_at"], "created_at kept")

for bad in ("", "   ", "x" * 41, "Tonny7", "a@b", "O'Brien2"):
    try:
        prof.save_profile(bad)
        check(False, f"reject {bad!r}")
    except ValueError:
        check(True, f"reject {bad!r}")

for good in ("Mary-Jane", "O'Brien", "A B"):
    check(prof.validate_name(good) == good, f"accept {good}")

try:
    prof.save_profile("Tonny", refer_as="they")
    check(False, "reject bad refer_as")
except ValueError:
    check(True, "reject bad refer_as")

prof.PROFILE_PATH.write_text("{oops", encoding="utf-8")
check(prof.load_profile() is None, "corrupt file reads as None")

check(prof.delete_profile() is True, "delete removes file")
check(prof.load_profile() is None, "gone after delete")

print(f"test_owner_profile.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
