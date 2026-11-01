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
VERIFY_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "verdicts"
BATCH = 4
VERIFY_BATCH = 8
VERIFY_TOP = 12
VERDICTS = ("yes", "no", "unsure")
MAX_REASON_WORDS = 6
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


CONSTRAINT_SLOTS = {"atmosphere": ATMOSPHERE, "light": LIGHT,
                    "time_of_day": TIME_OF_DAY, "vegetation": VEGETATION,
                    "crowd": CROWD}
OPS = ("is", "is_not")


def normalize_constraints(raw):
    """Cleaned [{attribute, op, values}] (pure).

    Drops anything malformed, unknown, or outside the slot enums
    ("unknown" values included — they never match a filter, so
    they are pointless, not harmful). Water takes true/false.
    """
    if not isinstance(raw, list):
        return []
    out = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        attr = c.get("attribute")
        op = c.get("op")
        values = c.get("values")
        if attr == "water_visible":
            allowed = (True, False)
        elif attr in CONSTRAINT_SLOTS:
            allowed = CONSTRAINT_SLOTS[attr]
        else:
            continue
        if op not in OPS or not isinstance(values, list) or not values:
            continue
        clean = [v for v in values if v in allowed]
        if not clean:
            continue
        out.append({"attribute": attr, "op": op, "values": clean})
    return out


def attributes_filter(constraints):
    """SQL filter_attributes param for "is" constraints (pure).

    {"atmosphere": [...], ...} or None when no "is" constraint
    exists. "is_not" is applied in code (unknowns are kept).
    """
    filt = {}
    for c in constraints or []:
        if c.get("op") == "is" and c.get("values"):
            filt[c["attribute"]] = list(c["values"])
    return filt or None


def violates_is_not(attributes, constraints):
    """True when stored attributes break an "is_not" constraint (pure).

    Missing attributes or "unknown" values never violate: the
    photo might still qualify (step 3 checks it visually).
    """
    attrs = attributes if isinstance(attributes, dict) else {}
    for c in constraints or []:
        if c.get("op") != "is_not":
            continue
        got = (attrs.get(c.get("attribute")) or {}).get("value")
        if got is not None and got != "unknown" and got in (c.get("values") or []):
            return True
    return False


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


_VERIFY_VALUE_WORDS = {
    "clear": "clear", "partly_cloudy": "partly cloudy",
    "overcast": "overcast", "hazy": "hazy",
    "misty_or_foggy": "misty or foggy", "rainy": "rainy",
    "dusty": "dusty", "golden_hour": "golden hour",
    "harsh_midday": "harsh midday", "soft": "soft",
    "night_lit": "night-lit", "backlit": "backlit",
    "dawn": "dawn", "morning": "morning", "midday": "midday",
    "afternoon": "afternoon", "dusk": "dusk", "night": "night",
    "none": "no greenery", "sparse": "sparse greenery",
    "lush": "lush greenery", "empty": "empty of people",
    "few": "a few people", "many": "a crowd",
}
_VERIFY_ATTR_NOUN = {"atmosphere": "atmosphere", "light": "light",
                     "time_of_day": "", "water_visible": "",
                     "vegetation": "", "crowd": ""}
_HAVE_WORDS = {"clear": "clear skies",
               "partly_cloudy": "partly cloudy skies",
               "overcast": "overcast skies", "hazy": "haze",
               "misty_or_foggy": "mist", "rainy": "rain",
               "dusty": "dust"}

VERIFY_PROMPT_TEMPLATE = """You verify visual conditions from a contact sheet.
The sheet shows these photos top to bottom:
{photo_list}
For EVERY photo, judge EVERY check below. Output ONE JSON object keyed by
EXACTLY these photo ids (copy them character-for-character, in any order),
no prose:
{"<photo_id>": {"1": {"verdict": "yes|no|unsure", "reason": "at most six words"}}}
Checks:
{checks}
Rules: "yes" only when the condition is clearly visible; "unsure" when you
cannot tell — never guess. The reason names what you see, at most six words.
Definitions: misty or foggy is a visible veil or soft white layers of water
vapour, often in valleys or between ridges, that clearly reduces contrast at
near or middle distance. Hazy is a uniform grey, brown or blue loss of
contrast with distance and NO soft layers. Never call haze mist.
Every listed id must appear with every check number; never invent or alter an id."""


def constraint_key(c):
    """Cache key for a constraint's positive condition (pure).

    The op is left out on purpose: "with mist" and "without mist"
    ask about the same visible thing, so one cached verdict serves
    both and the code inverts it for is_not.
    """
    vals = ",".join("true" if v is True else "false" if v is False else str(v)
                    for v in c.get("values") or [])
    return f"{c.get('attribute')}={vals}"


def constraint_words(c):
    """Positive-condition words for the model prompt (pure; never negated)."""
    attr = c.get("attribute")
    words = []
    for v in c.get("values") or []:
        if attr == "water_visible":
            words.append("visible water" if v is True else "no visible water")
        else:
            words.append(_VERIFY_VALUE_WORDS.get(v, str(v)))
    core = " or ".join(words) or "anything"
    return f"{core} {_VERIFY_ATTR_NOUN.get(attr, '')}".strip()


def constraint_display(c):
    """Asker's-view words for replies and the trace (pure)."""
    core = constraint_words(c)
    return f"no {core}" if c.get("op") == "is_not" else core


def build_verify_prompt(photo_ids, checks):
    """Prompt with the sheet's ids and numbered checks (pure).

    checks is [(ckey, words)]; the model answers by check number so
    ids stay copyable and verdicts stay parseable.
    """
    listed = "\n".join(f"{n}. {pid}" for n, pid in enumerate(photo_ids, 1))
    numbered = "\n".join(f"{n}. {w}" for n, (_, w) in enumerate(checks, 1))
    return (VERIFY_PROMPT_TEMPLATE.replace("{photo_list}", listed)
            .replace("{checks}", numbered))


def parse_verify_response(text, photo_ids, checks):
    """Strict-validate one vision reply (pure).

    Returns {pid: {ckey: {"verdict", "reason"}}}. Anything missing
    or malformed becomes "unsure": a broken reply must never drop
    a photo, only decline to vouch for it.
    """
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
        per = {}
        for n, (ckey, _w) in enumerate(checks, 1):
            verdict, reason = "unsure", "missing from reply"
            if isinstance(raw, dict):
                slot = raw.get(str(n), raw.get(n))
                if isinstance(slot, dict):
                    if slot.get("verdict") in VERDICTS:
                        verdict = slot["verdict"]
                    why = slot.get("reason")
                    if isinstance(why, str) and why.strip():
                        reason = " ".join(why.split()[:MAX_REASON_WORDS])
                    else:
                        reason = "not judged"
                else:
                    reason = "not judged"
            per[ckey] = {"verdict": verdict, "reason": reason}
        out[pid] = per
    return out


def combine_verdicts(constraints, verdicts):
    """(verdict, reason, detail) from per-condition judgments (pure).

    verdicts maps constraint_key to the model's yes/no/unsure about
    the POSITIVE condition; is_not inverts it in code. Missing
    judgments count as unsure.
    """
    detail = []
    status = "satisfied"
    reason = ""
    for c in normalize_constraints(constraints):
        got = verdicts.get(constraint_key(c)) or {}
        seen = got.get("verdict", "unsure")
        why = got.get("reason", "not checked")
        if c["op"] == "is_not":
            seen = {"yes": "no", "no": "yes"}.get(seen, "unsure")
        state = {"yes": "satisfied", "no": "violated"}.get(seen, "unsure")
        detail.append({"check": constraint_display(c), "status": state,
                       "reason": why})
        if state == "violated":
            status = "violated"
            if not reason:
                reason = why
        elif state == "unsure" and status == "satisfied":
            status = "unsure"
            reason = why
        elif status == "satisfied" and not reason:
            reason = why
    verdict = {"satisfied": "yes", "violated": "no"}.get(status, "unsure")
    return verdict, reason or "not checked", detail


def few_note(n, constraints):
    """Honest count line when fewer than 3 photos pass (pure)."""
    words = " and ".join(constraint_display(c)
                         for c in normalize_constraints(constraints))
    plural = "s" if n != 1 else ""
    verb = "show" if n != 1 else "shows"
    return f"Only {n} photo{plural} clearly {verb} {words}."


def none_note(constraints, fails):
    """Honest nothing-found line naming the closest real conditions (pure).

    fails are rows (with stored attributes) that failed the visual
    check; the most common stored value for the constrained
    attribute names what the closest photos actually show.
    """
    base = "I could not find a photo that clearly shows that."
    cons = normalize_constraints(constraints)
    if not cons or not fails:
        return base + " The closest ones are below."
    attr = cons[0]["attribute"]
    vals = []
    for r in fails:
        v = ((r.get("attributes") or {}).get(attr) or {}).get("value")
        if v is not None and v != "unknown":
            vals.append(v)
    if not vals:
        return base + " The closest ones are below."
    top = max(set(vals), key=vals.count)
    if attr == "water_visible":
        have = "visible water" if top is True else "no visible water"
    else:
        have = _HAVE_WORDS.get(top, _VERIFY_VALUE_WORDS.get(top, str(top)))
    return f"{base} These have {have}, not {constraint_display(cons[0])}."


def mixed_note(nclear, nmaybe, constraints):
    """Honest count line when some pass clearly, some might (pure)."""
    words = " and ".join(constraint_display(c)
                         for c in normalize_constraints(constraints))
    verb = "shows" if nclear == 1 else "show"
    return f"Only {nclear} clearly {verb} {words}; {nmaybe} more might."


def maybe_note(n, constraints):
    """Honest line when nothing verified but some might qualify (pure)."""
    words = " and ".join(constraint_display(c)
                         for c in normalize_constraints(constraints))
    who = "this one" if n == 1 else f"these {n}"
    return f"I could not verify {words} clearly; {who} might show it."


def load_verdicts(pid):
    """Cached {ckey: {"verdict", "reason"}} for a photo ({} when none)."""
    p = VERIFY_DIR / f"{pid}.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        if isinstance(v, dict) and v.get("verdict") in VERDICTS \
                and isinstance(v.get("reason"), str):
            out[k] = {"verdict": v["verdict"], "reason": v["reason"]}
    return out


def save_verdicts(pid, verdicts):
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    (VERIFY_DIR / f"{pid}.json").write_text(
        json.dumps(verdicts, ensure_ascii=False), encoding="utf-8")


def verify_photos(photo_ids, constraints, *, load_bytes, trace=None,
                  session_id=None):
    """Per-photo verdicts against constraints (cached; vision in sheets of 8).

    load_bytes(pid) returns (bytes, mime) or None. Returns (results,
    info): results[pid] is {"verdict" (yes|unsure|no), "reason",
    "detail"}; info has checked/cached counts, llm call metadata and
    fallback_used. Model failures leave photos "unsure" with a trace
    note instead of raising.
    """
    cons = normalize_constraints(constraints)
    conds = []
    for c in cons:
        key = constraint_key(c)
        if key not in [k for k, _ in conds]:
            conds.append((key, constraint_words(c)))
    cached = {pid: load_verdicts(pid) for pid in photo_ids}
    need = [pid for pid in photo_ids
            if any(k not in cached[pid] for k, _ in conds)]
    info = {"checked": len(photo_ids), "fresh": 0,
            "cached": len(photo_ids) - len(need),
            "calls": [], "fallback_used": False}
    for i in range(0, len(need), VERIFY_BATCH):
        batch = need[i:i + VERIFY_BATCH]
        items, missing = [], []
        for pid in batch:
            try:
                got = load_bytes(pid)
            except Exception:
                got = None
            if got is None:
                missing.append(pid)
            else:
                items.append((pid, got[0]))
        present = [pid for pid, _ in items]
        bchecks = [(k, w) for k, w in conds
                   if any(k not in cached[pid] for pid in present)]
        if items and bchecks:
            try:
                sheet, _ = build_contact_sheet(items)
            except Exception as e:
                sheet = None
                if trace is not None:
                    trace.append({"step": "checked",
                                  "detail": f"contact sheet failed: {e}; "
                                  "photos kept as unsure."})
            if sheet is not None:
                try:
                    res = llm.ask(
                        build_verify_prompt(present, bchecks),
                        image_path=_sheet_path(items, sheet),
                        purpose="verify", session_id=session_id)
                    info["calls"].append({"provider": res.get("provider"),
                                         "seconds": res.get("seconds")})
                    if res.get("fallback_used"):
                        info["fallback_used"] = True
                    parsed = parse_verify_response(
                        res["text"], present, bchecks)
                    for pid, per in parsed.items():
                        for k, v in per.items():
                            # Cache real judgments only; a photo the
                            # model skipped is retried next time.
                            if k not in cached[pid] \
                                    and v["reason"] != "missing from reply":
                                cached[pid][k] = v
                        save_verdicts(pid, cached[pid])
                    info["fresh"] += len(present)
                except RuntimeError as e:
                    if trace is not None:
                        trace.append({"step": "checked",
                                      "detail": f"visual check failed: {e}; "
                                      "photos kept as unsure."})
                    for pid in present:
                        for k, _ in bchecks:
                            cached[pid].setdefault(
                                k, {"verdict": "unsure",
                                    "reason": "check failed"})
        for pid in missing:
            for k, _ in conds:
                cached[pid].setdefault(
                    k, {"verdict": "unsure", "reason": "photo unavailable"})
    results = {}
    for pid in photo_ids:
        verdict, reason, detail = combine_verdicts(cons, cached[pid])
        results[pid] = {"verdict": verdict, "reason": reason,
                        "detail": detail}
    return results, info


def verify_question(photo_ids, question, *, load_bytes, trace=None,
                    session_id=None):
    """Answer one question per photo from the images (cached, sheets of 8).

    Powers the router's verify tool ("which of these show mist?").
    Returns ({pid: {"verdict" (yes|unsure|no), "reason"}}, info)
    with info shaped like verify_photos. Cached per photo and
    question hash; failures stay "unsure" with a trace note.
    """
    qkey = "q:" + hashlib.sha1(
        (question or "").strip().lower().encode()).hexdigest()[:12]
    checks = [(qkey, (question or "").strip() or "anything")]
    cached = {pid: load_verdicts(pid) for pid in photo_ids}
    need = [pid for pid in photo_ids if qkey not in cached[pid]]
    info = {"checked": len(photo_ids), "fresh": 0,
            "cached": len(photo_ids) - len(need),
            "calls": [], "fallback_used": False}
    for i in range(0, len(need), VERIFY_BATCH):
        batch = need[i:i + VERIFY_BATCH]
        items = []
        for pid in batch:
            try:
                got = load_bytes(pid)
            except Exception:
                got = None
            if got is None:
                cached[pid][qkey] = {"verdict": "unsure",
                                     "reason": "photo unavailable"}
            else:
                items.append((pid, got[0]))
        present = [pid for pid, _ in items]
        if not items:
            continue
        try:
            sheet, _ = build_contact_sheet(items)
        except Exception as e:
            sheet = None
            if trace is not None:
                trace.append({"step": "checked",
                              "detail": f"contact sheet failed: {e}; "
                              "photos kept as unsure."})
        if sheet is None:
            for pid in present:
                cached[pid][qkey] = {"verdict": "unsure",
                                     "reason": "check failed"}
            continue
        try:
            res = llm.ask(build_verify_prompt(present, checks),
                          image_path=_sheet_path(items, sheet),
                          purpose="verify", session_id=session_id)
            info["calls"].append({"provider": res.get("provider"),
                                 "seconds": res.get("seconds")})
            if res.get("fallback_used"):
                info["fallback_used"] = True
            for pid, per in parse_verify_response(
                    res["text"], present, checks).items():
                if per[qkey]["reason"] != "missing from reply":
                    cached[pid][qkey] = per[qkey]
                else:
                    cached[pid][qkey] = {"verdict": "unsure",
                                        "reason": "not judged"}
                save_verdicts(pid, cached[pid])
            info["fresh"] += len(present)
        except RuntimeError as e:
            if trace is not None:
                trace.append({"step": "checked",
                              "detail": f"visual check failed: {e}; "
                              "photos kept as unsure."})
            for pid in present:
                cached[pid][qkey] = {"verdict": "unsure",
                                     "reason": "check failed"}
    return {pid: {"verdict": cached[pid][qkey]["verdict"],
                 "reason": cached[pid][qkey]["reason"]} for pid in photo_ids}, info
