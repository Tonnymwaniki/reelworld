"""Checks for search-spec owner support (clean_spec + EMPTY_SPEC).
Run from the project root:  python backend/test_search_spec.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import clean_spec  # noqa: E402
from chat import EMPTY_SPEC, NO_TAGS_TEXT  # noqa: E402
from fastapi import HTTPException  # noqa: E402

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


def expect_400(fn, label):
    global fails, total
    total += 1
    try:
        fn()
    except HTTPException as e:
        if e.status_code != 400:
            fails += 1
            print(f"FAIL {label}: status {e.status_code}, want 400")
    except Exception as e:  # noqa: BLE001 (any other error is a failure)
        fails += 1
        print(f"FAIL {label}: {type(e).__name__} {e}")
    else:
        fails += 1
        print(f"FAIL {label}: no error raised")


check(EMPTY_SPEC["owner_only"] is False, "EMPTY_SPEC defaults owner_only false")
check(NO_TAGS_TEXT == "You have not told me which photos you are in. "
      "Tag a few and I will find them.", "none-tagged message exact")

s = clean_spec({"query": "me at KICC", "collection": "world", "owner_only": True})
check(s["owner_only"] is True and s["collection"] == "personal",
      "owner_only forces personal")
check(clean_spec({"query": "x"})["owner_only"] is False, "default false")

expect_400(lambda: clean_spec({"query": "x", "owner_only": "yes"}), "reject owner_only string")
expect_400(lambda: clean_spec({"query": "x", "owner_only": 1}), "reject owner_only 1")
expect_400(lambda: clean_spec({"query": "  "}), "reject empty query")

print(f"test_search_spec.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
