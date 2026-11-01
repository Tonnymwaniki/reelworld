"""Focused checks for search constraints (backend/attributes.py).

Validation, the SQL filter builder and the is_not matcher: pure
code, no model. Run from the project root:
python backend/test_constraints.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from attributes import (attributes_filter, normalize_constraints,  # noqa: E402
                        violates_is_not)

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


good = [{"attribute": "atmosphere", "op": "is", "values": ["misty_or_foggy"]},
        {"attribute": "crowd", "op": "is_not", "values": ["many"]},
        {"attribute": "water_visible", "op": "is", "values": [True]}]
check(normalize_constraints(good) == good, "valid constraints kept")
check(normalize_constraints("nope") == [], "non-list dropped")
check(normalize_constraints([
    {"attribute": "mood", "op": "is", "values": ["happy"]},
    {"attribute": "atmosphere", "op": "maybe", "values": ["clear"]},
    {"attribute": "light", "op": "is", "values": []},
    {"attribute": "crowd", "op": "is", "values": ["huge"]},
    {"attribute": "water_visible", "op": "is", "values": ["yes"]},
    "junk", None]) == [], "bad constraints dropped")
check(normalize_constraints(
    [{"attribute": "atmosphere", "op": "is",
      "values": ["clear", "bogus"]}]) == [
    {"attribute": "atmosphere", "op": "is", "values": ["clear"]}],
    "bad values pruned, good kept")

check(attributes_filter(good) == {"atmosphere": ["misty_or_foggy"],
                                  "water_visible": [True]},
      "SQL filter takes is-only")
check(attributes_filter(
    [{"attribute": "crowd", "op": "is_not", "values": ["many"]}]) is None,
      "no is-constraints means no SQL filter")
check(attributes_filter([]) is None, "empty means no SQL filter")

attrs = {"atmosphere": {"value": "hazy", "confidence": 1, "evidence": "x"},
         "crowd": {"value": "many", "confidence": 1, "evidence": "x"}}
check(violates_is_not(
    attrs, [{"attribute": "atmosphere", "op": "is_not",
             "values": ["hazy"]}]) is True, "is_not hit violates")
check(violates_is_not(
    attrs, [{"attribute": "atmosphere", "op": "is_not",
             "values": ["misty_or_foggy"]}]) is False, "is_not miss passes")
check(violates_is_not(
    {"atmosphere": {"value": "unknown", "confidence": 0, "evidence": "x"}},
    [{"attribute": "atmosphere", "op": "is_not",
      "values": ["hazy"]}]) is False, "unknown never violates")
check(violates_is_not(
    None, [{"attribute": "crowd", "op": "is_not",
            "values": ["many"]}]) is False, "missing attributes pass")
check(violates_is_not(
    attrs, [{"attribute": "crowd", "op": "is", "values": ["few"]}]) is False,
      "is-constraints ignored here")

import chat as chat_mod  # noqa: E402  (template must survive .format)
try:
    rendered = chat_mod.PARSE_PROMPT.format(
        spec="{}", focus="null", message="misty mountains",
        viewpoints="ground_level, elevated")
    check('"attribute"' in rendered and "{spec}" not in rendered,
          "parse prompt formats with constraint docs")
except KeyError as err:
    check(False, f"parse prompt formats with constraint docs ({err})")

print(f"test_constraints.py: {total - fails}/{total} checks passed")
