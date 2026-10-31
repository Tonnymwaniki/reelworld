"""Per-photo composition data for the story director (vision, cached).

Every result is cached at data/focal/<photo_id>.json. Vision output is
used for composition ONLY (focal point, crops, mood) — never as facts;
captions and claims always come from the annotation records.
"""
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import llm
from chat import extract_json

FOCAL_DIR = Path(__file__).resolve().parent.parent / "data" / "focal"
SHEETS_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "focal_sheets"
MOODS = ("calm", "busy", "grand", "intimate")
BATCH = 8
THUMB_W = 512
LABEL_H = 48
LABEL_FONT_SIZE = 28
MIN_CONFIDENCE = 0.3
RETRIABLE_REASONS = ("missing from vision reply", "invalid vision entry")

FOCAL_PROMPT_TEMPLATE = """You are a film director reading a contact sheet.
The sheet shows these photos top to bottom:
{photo_list}
For EVERY listed photo, judge composition only. Output ONE JSON object
keyed by EXACTLY these photo ids (copy them character-for-character,
in any order), no prose:
{"<photo_id>": {"focal": {"x": 0.0-1.0, "y": 0.0-1.0},
"subject_box": {"x": 0-1, "y": 0-1, "w": 0-1, "h": 0-1} or null,
"safe_crop_916": {"x": 0-1, "y": 0-1, "w": 0-1, "h": 0-1},
"mood": calm|busy|grand|intimate, "confidence": 0.0-1.0}}
Rules: focal is the main subject as fractions of that thumbnail;
subject_box is a tight box or null when there is no clear subject;
safe_crop_916 is the best portrait 9:16 window INSIDE the photo as
fractions and MUST include the focal point; mood is the overall
feeling; confidence is your certainty. Fractions only, never pixels.
Every listed id must appear; never invent or alter an id."""


def build_focal_prompt(photo_ids):
    """Prompt with the sheet's ids listed (pure; model copies, not OCRs)."""
    listed = "\n".join(f"{n}. {pid}" for n, pid in enumerate(photo_ids, 1))
    return FOCAL_PROMPT_TEMPLATE.replace("{photo_list}", listed)


def _clamp01(v):
    try:
        return min(1.0, max(0.0, float(v)))
    except (TypeError, ValueError):
        return None


def _valid_box(b):
    if not isinstance(b, dict):
        return None
    vals = {k: _clamp01(b.get(k)) for k in ("x", "y", "w", "h")}
    if any(v is None for v in vals.values()):
        return None
    if vals["w"] <= 0 or vals["h"] <= 0:
        return None
    if vals["x"] + vals["w"] > 1.001 or vals["y"] + vals["h"] > 1.001:
        return None
    return {k: round(v, 4) for k, v in vals.items()}


def center_crop_916(w, h):
    """Centred 9:16 window as fractions (pure)."""
    ratio = 9 / 16
    if w / h > ratio:
        cw = h * ratio
        return {"x": round((w - cw) / 2 / w, 4), "y": 0.0,
                "w": round(cw / w, 4), "h": 1.0}
    ch = w / ratio
    return {"x": 0.0, "y": round((h - ch) / 2 / h, 4),
            "w": 1.0, "h": round(ch / h, 4)}


def _crop_has_focal(crop, focal):
    return (crop["x"] <= focal["x"] <= crop["x"] + crop["w"]
            and crop["y"] <= focal["y"] <= crop["y"] + crop["h"])


def build_contact_sheet(items):
    """Single-column sheet: label bar + full 512-wide thumb each.

    Fractions of a thumbnail equal fractions of its photo. Returns
    (jpeg_bytes, {photo_id: (w, h)}) with original sizes.
    """
    thumbs = []
    sizes = {}
    for pid, raw in items:
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        sizes[pid] = im.size
        nw = THUMB_W
        nh = max(1, round(im.size[1] * THUMB_W / im.size[0]))
        thumbs.append((pid, im.resize((nw, nh), Image.LANCZOS)))
    total_h = sum(LABEL_H + t.size[1] for _, t in thumbs)
    sheet = Image.new("RGB", (THUMB_W, total_h), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=LABEL_FONT_SIZE)
    except TypeError:  # Pillow before 10.1 has no sized default font
        font = ImageFont.load_default()
    y = 0
    for pid, thumb in thumbs:
        draw.text((12, 8), pid, font=font, fill=(255, 255, 255))
        sheet.paste(thumb, (0, y + LABEL_H))
        y += LABEL_H + thumb.size[1]
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=88)
    return buf.getvalue(), sizes


def fallback_entry(pid, size, reason):
    """Centre focal, confidence 0; crop only when dimensions are known."""
    return {"photo_id": pid, "focal": {"x": 0.5, "y": 0.5},
            "subject_box": None,
            "safe_crop_916": center_crop_916(*size) if size else None,
            "mood": "calm", "confidence": 0.0,
            "fallback": True, "fallback_reason": reason}


def parse_focal_response(text, photo_ids, sizes):
    """Strict-validate one vision reply (pure). Bad entries fall back."""
    try:
        data = extract_json(text)
    except (ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    lookup = {k.lower().strip(): v for k, v in data.items()
              if isinstance(k, str)}
    out = {}
    for pid in photo_ids:
        size = sizes.get(pid)
        raw = lookup.get(pid.lower(), data.get(pid))
        if not isinstance(raw, dict):
            out[pid] = fallback_entry(pid, size, "missing from vision reply")
            continue
        focal = _valid_box({"x": (raw.get("focal") or {}).get("x"),
                            "y": (raw.get("focal") or {}).get("y"),
                            "w": 0.01, "h": 0.01})
        mood = raw.get("mood")
        conf = _clamp01(raw.get("confidence"))
        if focal is None or mood not in MOODS or conf is None:
            out[pid] = fallback_entry(pid, size, "invalid vision entry")
            continue
        if conf < MIN_CONFIDENCE:
            out[pid] = fallback_entry(pid, size, f"confidence {conf} below 0.3")
            continue
        focal = {"x": focal["x"], "y": focal["y"]}
        crop = _valid_box(raw.get("safe_crop_916"))
        if crop is None or not _crop_has_focal(crop, focal):
            crop = center_crop_916(*size) if size else None
        out[pid] = {"photo_id": pid, "focal": focal,
                    "subject_box": _valid_box(raw.get("subject_box")),
                    "safe_crop_916": crop, "mood": mood,
                    "confidence": round(conf, 3), "fallback": False}
    return out


def load_cached(pid):
    """Cached entry or None (shape-checked)."""
    p = FOCAL_DIR / f"{pid}.json"
    try:
        entry = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict) or not isinstance(entry.get("focal"), dict):
        return None
    return entry


def save_cache(pid, entry):
    FOCAL_DIR.mkdir(parents=True, exist_ok=True)
    (FOCAL_DIR / f"{pid}.json").write_text(json.dumps(entry, ensure_ascii=False),
                                           encoding="utf-8")


def ensure_focal(photo_ids, *, load_bytes, trace=None):
    """Focal data for photo_ids (cached; vision in sheets of 8).

    load_bytes(pid) returns (bytes, mime) or None. Anything vision
    cannot do falls back to centre with confidence 0 and a trace note.
    """
    out = {}
    need = []
    for pid in photo_ids:
        hit = load_cached(pid)
        if hit is None:
            need.append(pid)
        else:
            out[pid] = hit
    for i in range(0, len(need), BATCH):
        batch = need[i:i + BATCH]
        items, missing = [], []
        for pid in batch:
            got = load_bytes(pid)
            if got is None:
                missing.append(pid)
            else:
                items.append((pid, got[0]))
        sizes = {}
        if items:
            try:
                sheet, sizes = build_contact_sheet(items)
            except Exception as e:
                if trace is not None:
                    trace.append({"step": "focal",
                                  "detail": f"contact sheet failed: {e}; using centre."})
                sheet, sizes = None, {}
            if sheet is not None:
                try:
                    SHEETS_DIR.mkdir(parents=True, exist_ok=True)
                    key = hashlib.sha1(
                        ",".join(sorted(p for p, _ in items)).encode()).hexdigest()[:16]
                    sheet_path = SHEETS_DIR / f"{key}.jpg"
                    sheet_path.write_bytes(sheet)
                    res = llm.ask(build_focal_prompt([p for p, _ in items]),
                                  image_path=str(sheet_path), purpose="focal")
                    parsed = parse_focal_response(
                        res["text"], [p for p, _ in items], sizes)
                    retriable = [p for p, _ in items
                                 if parsed[p].get("fallback_reason") in RETRIABLE_REASONS]
                    if retriable:  # one retry on a smaller sheet, then fallbacks stand
                        try:
                            ritems = [(p, raw) for p, raw in items if p in retriable]
                            rsheet, rsizes = build_contact_sheet(ritems)
                            rkey = hashlib.sha1(
                                ",".join(sorted(p for p, _ in ritems)).encode()
                            ).hexdigest()[:16]
                            rpath = SHEETS_DIR / f"{rkey}.jpg"
                            rpath.write_bytes(rsheet)
                            rres = llm.ask(
                                build_focal_prompt([p for p, _ in ritems]),
                                image_path=str(rpath), purpose="focal")
                            for rpid, entry in parse_focal_response(
                                    rres["text"], retriable, rsizes).items():
                                if not entry.get("fallback"):
                                    parsed[rpid] = entry
                        except RuntimeError:
                            pass
                except RuntimeError as e:
                    parsed = {p: fallback_entry(p, sizes.get(p), f"vision failed: {e}")
                              for p, _ in items}
                    if trace is not None:
                        trace.append({"step": "focal",
                                      "detail": f"vision failed, {len(items)} "
                                                f"photo(s) fall back to centre."})
                for pid, entry in parsed.items():
                    save_cache(pid, entry)
                    out[pid] = entry
        for pid in missing:
            entry = fallback_entry(pid, None, "photo bytes unavailable")
            save_cache(pid, entry)
            out[pid] = entry
        if trace is not None:
            fell = [p for p in batch
                    if out.get(p, {}).get("fallback") and p not in missing]
            if fell:
                trace.append({"step": "focal",
                              "detail": f"low-confidence vision for "
                                        f"{', '.join(fell)}; using centre."})
    return out
