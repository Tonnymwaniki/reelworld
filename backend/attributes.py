"""Per-photo visual attributes for constrained search (vision, cached).

Every photo gets a fixed checklist judged from the image itself:
atmosphere, light, time of day, water, vegetation, crowd, plus up
to 5 notable objects. Each value carries a confidence and a short
evidence phrase; "unknown" is always allowed. Results are cached
at data/attributes/<photo_id>.json (personal ones git-ignored)
and mirrored to the photos.attributes column by the loader.
"""
import hashlib
import json
from pathlib import Path

import llm
from chat import extract_json
from focal import build_contact_sheet

ATTR_DIR = Path(__file__).resolve().parent.parent / "data" / "attributes"
SHEETS_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "attr_sheets"
BATCH = 4
RETRIABLE_REASONS = ("missing from vision reply", "invalid vision entry")

ATMOSPHERE = ("clear", "partly_cloudy", "overcast", "hazy",
              "misty_or_foggy", "rainy", "dusty", "unknown")
LIGHT = ("golden_hour", "harsh_midday", "soft", "night_lit",
         "backlit", "unknown")
TIME_OF_DAY = ("dawn", "morning", "midday", "afternoon", "dusk",
               "night", "unknown")
VEGETATION = ("none", "sparse", "lush", "unknown")
CROWD = ("empty", "few", "many", "unknown")
MAX_OBJECTS = 5
MAX_EVIDENCE = 120

ATTRIBUTES_PROMPT_TEMPLATE = """You judge visual conditions from a contact sheet.
The sheet shows these photos top to bottom:
{photo_list}
For EVERY listed photo, output ONE JSON object keyed by EXACTLY
these photo ids (copy them character-for-character, in any
order), no prose:
{"<photo_id>": {"atmosphere": {"value": ..., "confidence": 0.0-1.0, "evidence": "..."},
"light": {...}, "time_of_day": {...}, "water_visible": {"value": true|false|"unknown", ...},
"vegetation": {...}, "crowd": {...},
"objects": [{"name": "...", "confidence": 0.0-1.0, "evidence": "..."}]}}
Allowed values — atmosphere: clear|partly_cloudy|overcast|hazy|misty_or_foggy|rainy|dusty|unknown;
light: golden_hour|harsh_midday|soft|night_lit|backlit|unknown;
time_of_day: dawn|morning|midday|afternoon|dusk|night|unknown;
vegetation: none|sparse|lush|unknown; crowd: empty|few|many|unknown.
At most 5 objects, each a short visible thing with confidence and evidence.
Evidence is a short phrase naming what you see (at most 120 characters).
When unsure use "unknown" with low confidence — never guess.
Definitions: misty_or_foggy is a visible veil or soft white layers of water
vapour, often in valleys or between ridges, that clearly reduces contrast at
near or middle distance. hazy is a uniform grey, brown or blue loss of
contrast with distance and NO soft layers. Never call haze mist.
Every listed id must appear; never invent or alter an id."""


def build_attributes_prompt(photo_ids):
    """Prompt with the sheet's ids listed (pure; model copies, not OCRs)."""
    listed = "\n".join(f"{n}. {pid}" for n, pid in enumerate(photo_ids, 1))
    return ATTRIBUTES_PROMPT_TEMPLATE.replace("{photo_list}", listed)


def _clamp01(v):
    try:
        return min(1.0, max(0.0, float(v)))
    except (TypeError, ValueError):
        return None


def _clean_evidence(v):
    if not isinstance(v, str) or not v.strip():
        return None
    return v.strip()[:MAX_EVIDENCE]


def _valid_slot(raw, allowed):
    """{"value", "confidence", "evidence"} or None (pure).

    "unsure" is normalized to "unknown".
    """
    if not isinstance(raw, dict):
        return None
    value = raw.get("value")
    if value == "unsure":
        value = "unknown"
    conf = _clamp01(raw.get("confidence"))
    ev = _clean_evidence(raw.get("evidence"))
    if value not in allowed or conf is None or ev is None:
        return None
    return {"value": value, "confidence": round(conf, 3), "evidence": ev}


def _valid_water(raw):
    if not isinstance(raw, dict):
        return None
    value = raw.get("value")
    if value == "unsure":
        value = "unknown"
    conf = _clamp01(raw.get("confidence"))
    ev = _clean_evidence(raw.get("evidence"))
    if value not in (True, False, "unknown") or conf is None or ev is None:
        return None
    return {"value": value, "confidence": round(conf, 3), "evidence": ev}


def _valid_objects(raw):
    if not isinstance(raw, list):
        return None
    out = []
    for item in raw[:MAX_OBJECTS]:
        if not isinstance(item, dict):
            return None
        name = item.get("name")
        conf = _clamp01(item.get("confidence"))
        ev = _clean_evidence(item.get("evidence"))
        if not isinstance(name, str) or not name.strip() or conf is None \
                or ev is None:
            return None
        out.append({"name": name.strip()[:60], "confidence": round(conf, 3),
                    "evidence": ev})
    return out


def fallback_entry(pid, reason):
    """All-unknown entry; filtering treats it as no information."""
    unk = {"value": "unknown", "confidence": 0.0, "evidence": reason[:MAX_EVIDENCE]}
    water = {"value": "unknown", "confidence": 0.0,
             "evidence": reason[:MAX_EVIDENCE]}
    return {"photo_id": pid, "atmosphere": dict(unk), "light": dict(unk),
            "time_of_day": dict(unk), "water_visible": water,
            "vegetation": dict(unk), "crowd": dict(unk), "objects": [],
            "fallback": True, "fallback_reason": reason}


def parse_attributes_response(text, photo_ids):
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
        raw = lookup.get(pid.lower(), data.get(pid))
        if not isinstance(raw, dict):
            out[pid] = fallback_entry(pid, "missing from vision reply")
            continue
        entry = {"photo_id": pid,
                 "atmosphere": _valid_slot(raw.get("atmosphere"), ATMOSPHERE),
                 "light": _valid_slot(raw.get("light"), LIGHT),
                 "time_of_day": _valid_slot(raw.get("time_of_day"), TIME_OF_DAY),
                 "water_visible": _valid_water(raw.get("water_visible")),
                 "vegetation": _valid_slot(raw.get("vegetation"), VEGETATION),
                 "crowd": _valid_slot(raw.get("crowd"), CROWD),
                 "objects": _valid_objects(raw.get("objects"))}
        if any(entry[k] is None for k in ("atmosphere", "light",
                                            "time_of_day", "water_visible",
                                            "vegetation", "crowd", "objects")):
            out[pid] = fallback_entry(pid, "invalid vision entry")
            continue
        entry["fallback"] = False
        out[pid] = entry
    return out


def load_cached(pid):
    """Cached entry or None (shape-checked)."""
    p = ATTR_DIR / f"{pid}.json"
    try:
        entry = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict) \
            or not isinstance(entry.get("atmosphere"), dict):
        return None
    return entry


def save_cache(pid, entry):
    ATTR_DIR.mkdir(parents=True, exist_ok=True)
    (ATTR_DIR / f"{pid}.json").write_text(json.dumps(entry, ensure_ascii=False),
                                          encoding="utf-8")


def _sheet_path(items, sheet):
    SHEETS_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(
        ",".join(sorted(p for p, _ in items)).encode()).hexdigest()[:16]
    path = SHEETS_DIR / f"{key}.jpg"
    path.write_bytes(sheet)
    return str(path)


def ensure_attributes(photo_ids, *, load_bytes, trace=None):
    """Attribute checklists for photo_ids (cached; vision in sheets of 4).

    load_bytes(pid) returns (bytes, mime) or None. Anything vision
    cannot do falls back to all-unknown and a trace note.
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
        if items:
            try:
                sheet, _ = build_contact_sheet(items)
            except Exception as e:
                if trace is not None:
                    trace.append({"step": "attributes",
                                  "detail": f"contact sheet failed: {e}."})
                sheet = None
            if sheet is not None:
                try:
                    res = llm.ask(
                        build_attributes_prompt([p for p, _ in items]),
                        image_path=_sheet_path(items, sheet),
                        purpose="attributes")
                    parsed = parse_attributes_response(
                        res["text"], [p for p, _ in items])
                    retriable = [p for p, _ in items
                                 if parsed[p].get("fallback_reason") in RETRIABLE_REASONS]
                    if retriable:  # one retry on a smaller sheet, then fallbacks stand
                        try:
                            ritems = [(p, raw) for p, raw in items if p in retriable]
                            rsheet, _ = build_contact_sheet(ritems)
                            rres = llm.ask(
                                build_attributes_prompt([p for p, _ in ritems]),
                                image_path=_sheet_path(ritems, rsheet),
                                purpose="attributes")
                            for rpid, entry in parse_attributes_response(
                                    rres["text"], retriable).items():
                                if not entry.get("fallback"):
                                    parsed[rpid] = entry
                        except RuntimeError:
                            pass
                except RuntimeError as e:
                    parsed = {p: fallback_entry(p, f"vision failed: {e}")
                              for p, _ in items}
                    if trace is not None:
                        trace.append({"step": "attributes",
                                      "detail": f"vision failed, {len(items)} "
                                                f"photo(s) fall back to unknown."})
                for pid, entry in parsed.items():
                    save_cache(pid, entry)
                    out[pid] = entry
        for pid in missing:
            entry = fallback_entry(pid, "photo bytes unavailable")
            save_cache(pid, entry)
            out[pid] = entry
        if trace is not None:
            fell = [p for p in batch
                    if out.get(p, {}).get("fallback") and p not in missing]
            if fell:
                trace.append({"step": "attributes",
                              "detail": f"unknown attributes for "
                                        f"{', '.join(fell)} (vision unusable)."})
    return out
