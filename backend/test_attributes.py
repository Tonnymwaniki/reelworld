"""Focused checks for visual attributes (backend/attributes.py).

Prompt shape, strict validation, unsure handling, fallbacks and
the cached ensure flow with a stubbed model call. No model.
Run from the project root:  python backend/test_attributes.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import attributes as attr_mod  # noqa: E402  (needs the sys.path line above)
import llm  # noqa: E402
from PIL import Image  # noqa: E402

import io  # noqa: E402


def tiny_jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (200, 30, 30)).save(buf, "JPEG")
    return buf.getvalue()


FAKE_BYTES = tiny_jpeg()

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


def slot(value, conf=0.8, ev="seen clearly"):
    return {"value": value, "confidence": conf, "evidence": ev}


def good_entry():
    return {"atmosphere": slot("misty_or_foggy"),
            "light": slot("soft"), "time_of_day": slot("morning"),
            "water_visible": slot(True), "vegetation": slot("lush"),
            "crowd": slot("few"),
            "objects": [{"name": "ridge", "confidence": 0.9,
                         "evidence": "a long ridge"}]}


prompt = attr_mod.build_attributes_prompt(["a1", "b2"])
check("1. a1" in prompt and "2. b2" in prompt
      and "Never call haze mist" in prompt, "prompt lists ids + mist rule")

parsed = attr_mod.parse_attributes_response(
    json.dumps({"a1": good_entry()}), ["a1"])
check(parsed["a1"]["atmosphere"]["value"] == "misty_or_foggy"
      and parsed["a1"]["water_visible"]["value"] is True
      and parsed["a1"]["fallback"] is False, "valid reply kept")

entry = good_entry()
entry["atmosphere"] = slot("unsure", 0.2, "cannot tell")
parsed = attr_mod.parse_attributes_response(json.dumps({"a1": entry}), ["a1"])
check(parsed["a1"]["atmosphere"]["value"] == "unknown"
      and parsed["a1"]["fallback"] is False, "unsure becomes unknown")

entry = good_entry()
entry["light"] = slot("neon", 0.9, "bright signs")
parsed = attr_mod.parse_attributes_response(json.dumps({"a1": entry}), ["a1"])
check(parsed["a1"]["fallback"] is True
      and parsed["a1"]["fallback_reason"] == "invalid vision entry",
      "bad enum falls back")

parsed = attr_mod.parse_attributes_response(json.dumps({}), ["a1"])
check(parsed["a1"]["fallback"] is True
      and parsed["a1"]["fallback_reason"] == "missing from vision reply",
      "missing id falls back")

parsed = attr_mod.parse_attributes_response("not json {{{", ["a1"])
check(parsed["a1"]["fallback"] is True, "bad JSON falls back")

entry = good_entry()
entry["objects"] = [{"name": f"thing{i}", "confidence": 0.5,
                     "evidence": "there"} for i in range(6)]
parsed = attr_mod.parse_attributes_response(json.dumps({"a1": entry}), ["a1"])
check(len(parsed["a1"]["objects"]) == 5, "objects capped at five")

entry = good_entry()
entry["crowd"] = slot("few", 1.5, "some people")
parsed = attr_mod.parse_attributes_response(json.dumps({"a1": entry}), ["a1"])
check(parsed["a1"]["crowd"]["confidence"] == 1.0, "confidence clamped")

entry = good_entry()
entry["vegetation"] = slot("lush", 0.8, "  ")
parsed = attr_mod.parse_attributes_response(json.dumps({"a1": entry}), ["a1"])
check(parsed["a1"]["fallback"] is True, "empty evidence falls back")

for water in (True, False, "unknown"):
    entry = good_entry()
    entry["water_visible"] = slot(water)
    parsed = attr_mod.parse_attributes_response(json.dumps({"a1": entry}),
                                                ["a1"])
    check(parsed["a1"]["water_visible"]["value"] is water
          or parsed["a1"]["water_visible"]["value"] == water,
          f"water {water} ok")
entry = good_entry()
entry["water_visible"] = slot("yes")
parsed = attr_mod.parse_attributes_response(json.dumps({"a1": entry}), ["a1"])
check(parsed["a1"]["fallback"] is True, "bad water value falls back")

fb = attr_mod.fallback_entry("a1", "vision failed: x")
check(fb["atmosphere"]["value"] == "unknown" and fb["objects"] == []
      and fb["fallback"] is True, "fallback is all-unknown")

tmp = tempfile.TemporaryDirectory()
attr_mod.ATTR_DIR = Path(tmp.name)
calls = []
orig_ask = llm.ask
try:
    llm.ask = lambda *a, **k: (calls.append(a[0]),
                               {"text": json.dumps({"a1": good_entry()})})[1]
    out = attr_mod.ensure_attributes(
        ["a1"], load_bytes=lambda pid: (FAKE_BYTES, "image/jpeg")
        if pid == "a1" else None, trace=(tr := []))
    check(out["a1"]["atmosphere"]["value"] == "misty_or_foggy"
          and len(calls) == 1, "ensure calls vision once")
    out = attr_mod.ensure_attributes(["a1", "gone"], load_bytes=lambda pid: None)
    check(out["a1"]["atmosphere"]["value"] == "misty_or_foggy"
          and len(calls) == 1
          and out["gone"]["fallback_reason"] == "photo bytes unavailable",
          "cache hit skips vision; missing bytes fall back")
    llm.ask = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
    out = attr_mod.ensure_attributes(
        ["b2"], load_bytes=lambda pid: (FAKE_BYTES, "image/jpeg"),
        trace=(tr2 := []))
    check(out["b2"]["fallback"] is True
          and any(t["step"] == "attributes" for t in tr2),
          "vision failure falls back with trace")
finally:
    llm.ask = orig_ask

print(f"test_attributes.py: {total - fails}/{total} checks passed")
