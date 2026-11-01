"""Focused checks for visual verification (attributes.verify_photos).

Prompt building, verdict parsing/combining, caching, honest notes:
no model (llm.ask is stubbed where needed). Run from the project
root:  python backend/test_vision_check.py
"""
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import attributes as attr_mod  # noqa: E402  (needs the sys.path line above)
import llm  # noqa: E402

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


def jpeg(w, h, color):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


MIST = {"attribute": "atmosphere", "op": "is", "values": ["misty_or_foggy"]}
NO_MIST = {"attribute": "atmosphere", "op": "is_not",
           "values": ["misty_or_foggy"]}

# wording helpers
check(attr_mod.constraint_key(MIST) == "atmosphere=misty_or_foggy",
      "constraint key")
check(attr_mod.constraint_key(NO_MIST) == "atmosphere=misty_or_foggy",
      "key ignores op so flips reuse verdicts")
check(attr_mod.constraint_words(MIST) == "misty or foggy atmosphere",
      "positive words")
check(attr_mod.constraint_display(NO_MIST) == "no misty or foggy atmosphere",
      "asker-view negation")
check(attr_mod.constraint_words(
    {"attribute": "water_visible", "op": "is",
     "values": [True]}) == "visible water", "water words")

# prompt lists ids + numbered checks, never negated
p = attr_mod.build_verify_prompt(["a", "b"], [("k1", "misty or foggy")])
check("1. a" in p and "1. misty or foggy" in p
      and "Never call haze mist" in p, "verify prompt shape")

# parsing: good, malformed, long reasons
GOOD = {"p1": {"1": {"verdict": "yes", "reason": "soft white veil visible"}}}
out = attr_mod.parse_verify_response(
    json.dumps(GOOD), ["p1"], [("k1", "mist")])
check(out["p1"]["k1"] == {"verdict": "yes",
                          "reason": "soft white veil visible"},
      "valid verdict kept")
out = attr_mod.parse_verify_response("{}", ["p1"], [("k1", "mist")])
check(out["p1"]["k1"]["verdict"] == "unsure", "missing photo is unsure")
out = attr_mod.parse_verify_response(
    json.dumps({"p1": {"1": {"verdict": "maybe", "reason": "x"}}}),
    ["p1"], [("k1", "mist")])
check(out["p1"]["k1"]["verdict"] == "unsure", "bad verdict is unsure")
out = attr_mod.parse_verify_response(
    json.dumps({"p1": {"1": {"verdict": "yes",
                              "reason": "one two three four five six seven"}}}),
    ["p1"], [("k1", "mist")])
check(out["p1"]["k1"]["reason"] == "one two three four five six",
      "reason trimmed to six words")

# combining, incl. is_not inversion
ck = "atmosphere=misty_or_foggy"
v, r, d = attr_mod.combine_verdicts(
    [MIST], {ck: {"verdict": "yes", "reason": "veil visible"}})
check(v == "yes" and d[0]["status"] == "satisfied", "is + yes passes")
v, r, d = attr_mod.combine_verdicts(
    [NO_MIST], {ck: {"verdict": "yes", "reason": "veil visible"}})
check(v == "no" and d[0]["status"] == "violated", "is_not + yes fails")
v, r, d = attr_mod.combine_verdicts(
    [NO_MIST], {ck: {"verdict": "no", "reason": "clear ridge"}})
check(v == "yes", "is_not + no passes")
v, r, d = attr_mod.combine_verdicts([MIST], {})
check(v == "unsure" and r == "not checked", "missing judgment is unsure")

# honest notes
check(attr_mod.few_note(2, [MIST])
      == "Only 2 photos clearly show misty or foggy atmosphere.",
      "few note")
fails_rows = [{"attributes": {"atmosphere": {"value": "hazy"}}},
              {"attributes": {"atmosphere": {"value": "hazy"}}},
              {"attributes": {"atmosphere": {"value": "clear"}}}]
check(attr_mod.none_note([MIST], fails_rows)
      == "I could not find a photo that clearly shows that. "
         "These have haze, not misty or foggy atmosphere.",
      "none note names real conditions")
check(attr_mod.mixed_note(1, 2, [MIST])
      == "Only 1 clearly shows misty or foggy atmosphere; 2 more might.",
      "mixed note")
check(attr_mod.maybe_note(2, [MIST])
      == "I could not verify misty or foggy atmosphere clearly; "
         "these 2 might show it.",
      "maybe note")

# verify_photos with stubbed vision: cache, failure, missing bytes
tmp = tempfile.TemporaryDirectory()
attr_mod.VERIFY_DIR = Path(tmp.name)
orig_ask = llm.ask
try:
    llm.ask = lambda *a, **k: {"text": json.dumps(GOOD),
                               "provider": "stub", "seconds": 1.0,
                               "fallback_used": False}
    res, info = attr_mod.verify_photos(
        ["p1"], [MIST],
        load_bytes=lambda pid: (jpeg(100, 100, "red"), "image/jpeg"))
    check(res["p1"]["verdict"] == "yes" and len(info["calls"]) == 1
          and (Path(tmp.name) / "p1.json").exists(), "vision verdict cached")
    calls = []
    llm.ask = lambda *a, **k: calls.append(1) or {"text": "{}"}
    res, info = attr_mod.verify_photos(
        ["p1"], [NO_MIST], load_bytes=lambda pid: None)
    check(res["p1"]["verdict"] == "no" and not calls
          and info["cached"] == 1, "cache hit skips vision, flips op")

    def boom(*a, **k):
        raise RuntimeError("down")
    llm.ask = boom
    trace = []
    res, info = attr_mod.verify_photos(
        ["p2"], [MIST],
        load_bytes=lambda pid: (jpeg(100, 100, "red"), "image/jpeg"),
        trace=trace)
    check(res["p2"]["verdict"] == "unsure" and not info["calls"]
          and any("visual check failed" in t["detail"] for t in trace),
          "vision failure keeps unsure with trace")
    res, _ = attr_mod.verify_photos(["p3"], [MIST],
                                    load_bytes=lambda pid: None)
    check(res["p3"]["verdict"] == "unsure"
          and res["p3"]["reason"] == "photo unavailable",
          "missing bytes stay unsure")
finally:
    llm.ask = orig_ask

print(f"test_vision_check.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
