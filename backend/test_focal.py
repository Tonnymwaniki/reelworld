"""Focused checks for focal data (backend/focal.py).

Crop math, response validation, contact sheets, cache, fallbacks:
no model (llm.ask is stubbed where needed). Run from the project
root:  python backend/test_focal.py
"""
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import focal as focal_mod  # noqa: E402  (needs the sys.path line above)
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


# crop math
c = focal_mod.center_crop_916(1600, 900)
check(c == {"x": 0.3418, "y": 0.0, "w": 0.3164, "h": 1.0}, f"landscape crop {c}")
c = focal_mod.center_crop_916(900, 1600)
check(c == {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, f"portrait crop {c}")
c = focal_mod.center_crop_916(1000, 1000)
check(c == {"x": 0.2188, "y": 0.0, "w": 0.5625, "h": 1.0}, f"square crop {c}")

# response validation
GOOD = {"p1": {"focal": {"x": 0.3, "y": 0.4},
               "subject_box": {"x": 0.2, "y": 0.3, "w": 0.2, "h": 0.2},
               "safe_crop_916": {"x": 0.2, "y": 0.0, "w": 0.3, "h": 1.0},
               "mood": "grand", "confidence": 0.9}}
import json  # noqa: E402
parsed = focal_mod.parse_focal_response(json.dumps(GOOD), ["p1"], {"p1": (100, 100)})
check(parsed["p1"]["mood"] == "grand" and not parsed["p1"]["fallback"]
      and parsed["p1"]["subject_box"]["w"] == 0.2, "valid entry kept")
parsed = focal_mod.parse_focal_response("{}", ["p1"], {"p1": (100, 100)})
check(parsed["p1"]["fallback"] and parsed["p1"]["confidence"] == 0.0, "missing falls back")
low = {"p1": {**GOOD["p1"], "confidence": 0.1}}
parsed = focal_mod.parse_focal_response(json.dumps(low), ["p1"], {"p1": (100, 100)})
check(parsed["p1"]["fallback"], "low confidence falls back")
bad_mood = {"p1": {**GOOD["p1"], "mood": "sleepy"}}
parsed = focal_mod.parse_focal_response(json.dumps(bad_mood), ["p1"], {"p1": (100, 100)})
check(parsed["p1"]["fallback"], "bad mood falls back")
bad_box = {"p1": {**GOOD["p1"], "subject_box": {"x": 9, "y": 0, "w": 1, "h": 1}}}
parsed = focal_mod.parse_focal_response(json.dumps(bad_box), ["p1"], {"p1": (100, 100)})
check(not parsed["p1"]["fallback"] and parsed["p1"]["subject_box"] is None,
      "bad box nulled, entry kept")

# contact sheet geometry: 2 thumbs, 512 wide, 48px labels
sheet, sizes = focal_mod.build_contact_sheet(
    [("a", jpeg(800, 600, "red")), ("b", jpeg(600, 800, "blue"))])
from PIL import Image  # noqa: E402
im = Image.open(io.BytesIO(sheet))
check(im.size == (512, 48 + 384 + 48 + 683), f"sheet size {im.size}")
check(sizes == {"a": (800, 600), "b": (600, 800)}, "sheet sizes")

# prompt lists the exact ids for the model to copy
prompt = focal_mod.build_focal_prompt(["street_007", "market_006"])
check("1. street_007" in prompt and "2. market_006" in prompt, "prompt lists ids")

# cache roundtrip + ensure_focal with stubbed vision
tmp = tempfile.TemporaryDirectory()
focal_mod.FOCAL_DIR = Path(tmp.name)
orig_ask = llm.ask
try:
    llm.ask = lambda *a, **k: {"text": json.dumps(GOOD)}
    trace = []
    out = focal_mod.ensure_focal(
        ["p1"], load_bytes=lambda pid: (jpeg(100, 100, "red"), "image/jpeg"),
        trace=trace)
    check(out["p1"]["mood"] == "grand" and (Path(tmp.name) / "p1.json").exists(),
          "ensure caches vision")
    calls = []
    llm.ask = lambda *a, **k: calls.append(1) or {"text": json.dumps(GOOD)}
    out = focal_mod.ensure_focal(["p1"], load_bytes=lambda pid: None, trace=[])
    check(out["p1"]["mood"] == "grand" and not calls, "cache hit skips vision")

    def boom(*a, **k):
        raise RuntimeError("down")
    llm.ask = boom
    trace = []
    out = focal_mod.ensure_focal(
        ["p2"], load_bytes=lambda pid: (jpeg(100, 100, "red"), "image/jpeg"),
        trace=trace)
    check(out["p2"]["fallback"] and out["p2"]["confidence"] == 0.0
          and any("vision failed" in t["detail"] for t in trace),
          "vision failure falls back with trace")
    out = focal_mod.ensure_focal(["p3"], load_bytes=lambda pid: None, trace=[])
    check(out["p3"]["fallback"] and out["p3"]["safe_crop_916"] is None,
          "missing bytes fall back without crop")
    replies = [{"text": "{}"}, {"text": json.dumps({"p4": GOOD["p1"]})}]
    llm.ask = lambda *a, **k: replies.pop(0)
    out = focal_mod.ensure_focal(
        ["p4"], load_bytes=lambda pid: (jpeg(100, 100, "red"), "image/jpeg"),
        trace=[])
    check(out["p4"]["mood"] == "grand" and not out["p4"]["fallback"]
          and not replies, "retry recovers missing id")
    llm.ask = lambda *a, **k: {"text": "{}"}
    out = focal_mod.ensure_focal(
        ["p5"], load_bytes=lambda pid: (jpeg(100, 100, "red"), "image/jpeg"),
        trace=[])
    check(out["p5"]["fallback"], "retry exhausted keeps fallback")
finally:
    llm.ask = orig_ask

print(f"test_focal.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
