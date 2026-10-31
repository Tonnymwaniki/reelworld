"""Beat-sheet planning for directed stories (reasoning, text only).

The director sees record summaries + focal moods (never pixels) and
returns a beat sheet: title, cover photo, and beats with role, intent,
photos, pacing, camera and reason. Output is strictly validated;
invalid output is retried once (with the problems listed), then a
deterministic fallback plan is built in code so the pipeline always
has valid beats. Every path is noted in the trace.
"""
import llm
from chat import extract_json

ROLES = ("establish", "build", "turn", "resolve")
PACINGS = ("slow", "medium", "quick")
CAMERAS = ("push_in", "pull_back", "pan_to_focal", "hold")
STYLES = ("postcard", "field-notes", "documentary")
ARCS = {
    "postcard": "arrival, a telling detail, the reveal, a closing line",
    "field-notes": "a question, the evidence, the conclusion",
    "documentary": "the setting, the subject, the context, the change",
}
TARGET_SCENES = {"short": (3, 6), "medium": (6, 12)}
MAX_BEATS = 4


def normalize_style(style):
    """field_notes -> field-notes; raises ValueError when unknown."""
    s = (style or "").strip().lower().replace("_", "-")
    if s not in STYLES:
        raise ValueError(f"style must be one of {', '.join(STYLES)}.")
    return s


def summarize_record(photo_id, viewpoint, record):
    """One-photo brief for the director (pure)."""
    rec = record or {}
    obs, inf = rec.get("observed") or {}, rec.get("inferred") or {}
    scene = obs.get("scene") or {}
    ents = sorted(obs.get("entities") or [], key=lambda e: e.get("salience", 0),
                  reverse=True)
    things = [str(e.get("label") or "") for e in ents[:6] if e.get("label")]
    signs = [f"{t.get('text')} ({t.get('legibility')})"
             for t in (obs.get("visible_text") or [])[:4] if t.get("text")]
    place = inf.get("place") or {}
    taken = inf.get("taken_from") or {}
    scene_bits = [scene.get("type"), scene.get("setting"), scene.get("time_of_day")]
    return {"photo_id": photo_id,
            "place": (place.get("name") or "unknown place").strip(),
            "place_status": place.get("status"),
            "viewpoint": viewpoint or "unknown",
            "scene": ", ".join(b for b in scene_bits if b) or "unknown scene",
            "things": things,
            "signs": signs,
            "taken_from": (taken.get("name") or "").strip() or None,
            "people": (obs.get("people") or {}).get("count", 0) or 0}


def build_director_prompt(user_prompt, style, target, briefs, focals):
    """Director prompt: arc, lengths, candidates, focal moods (pure)."""
    lo, hi = TARGET_SCENES[target]
    lines = [f"1. {style}: shape the beats along this arc: {ARCS[style]}.",
             f"2. Length {target}: use {lo} to {hi} photos in total, "
             f"1 to {MAX_BEATS} beats.",
             f"3. Use ONLY these photo ids, each at most once, "
             f"no outside facts:"]
    for b in briefs:
        f = (focals or {}).get(b["photo_id"]) or {}
        lines.append(
            f"- {b['photo_id']}: {b['place']} ({b['place_status'] or 'unknown'}), "
            f"{b['viewpoint']}, {b['scene']}; things: {', '.join(b['things']) or 'none'}; "
            f"signs: {'; '.join(b['signs']) or 'none'}; "
            f"taken from: {b['taken_from'] or 'unknown'}; "
            f"people: {b['people']}; mood: {f.get('mood', 'unknown')} "
            f"(confidence {f.get('confidence', 0)}).")
    lines.append(
        'Output ONE JSON object, no prose: {"title": "…", "cover": "<photo_id>", '
        '"beats": [{"role": establish|build|turn|resolve, "intent": "…", '
        '"photo_ids": ["…"], "pacing": slow|medium|quick, '
        '"camera": push_in|pull_back|pan_to_focal|hold, "reason": "…"}]}. '
        "Roles: establish opens, build gathers, turn shifts, resolve lands. "
        "Cameras: push_in moves closer, pull_back widens, pan_to_focal glides "
        "to the subject, hold stays still.")
    return (f"You plan a directed photo film about: {user_prompt}\n"
            + "\n".join(lines))


def validate_beatsheet(data, photo_ids, target):
    """Strict beat-sheet check (pure). Returns (beatsheet, None) or
    (None, problems). Never raises on bad model output."""
    problems = []
    allowed = set(photo_ids)
    if not isinstance(data, dict):
        return None, ["reply is not a JSON object"]
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        problems.append("title is missing")
    if data.get("cover") not in allowed:
        problems.append("cover is not one of the photos")
    beats = data.get("beats")
    if not isinstance(beats, list) or not beats:
        problems.append("beats is empty")
        beats = []
    if len(beats) > MAX_BEATS:
        problems.append(f"more than {MAX_BEATS} beats")
    seen, total = set(), 0
    clean = []
    for i, b in enumerate(beats[:MAX_BEATS]):
        label = f"beat {i + 1}"
        if not isinstance(b, dict):
            problems.append(f"{label} is not an object")
            continue
        if b.get("role") not in ROLES:
            problems.append(f"{label} has a bad role")
        if not isinstance(b.get("intent"), str) or not b["intent"].strip():
            problems.append(f"{label} has no intent")
        pids = b.get("photo_ids")
        if not isinstance(pids, list) or not pids:
            problems.append(f"{label} has no photos")
            pids = []
        for pid in pids:
            if pid not in allowed:
                problems.append(f"{label} uses unknown photo {pid!r}")
            elif pid in seen:
                problems.append(f"{label} repeats photo {pid!r}")
            else:
                seen.add(pid)
                total += 1
        if b.get("pacing") not in PACINGS:
            problems.append(f"{label} has a bad pacing")
        if b.get("camera") not in CAMERAS:
            problems.append(f"{label} has a bad camera")
        if not isinstance(b.get("reason"), str) or not b["reason"].strip():
            problems.append(f"{label} has no reason")
        clean.append({"role": b.get("role"), "intent": str(b.get("intent") or ""),
                      "photo_ids": [p for p in pids if p in allowed],
                      "pacing": b.get("pacing"), "camera": b.get("camera"),
                      "reason": str(b.get("reason") or "")})
    lo, hi = TARGET_SCENES[target]
    if not (total <= hi and (total >= lo or total == len(allowed))):
        problems.append(f"{total} photos does not fit {target} ({lo}-{hi})")
    if problems:
        return None, problems
    return {"title": title.strip()[:80], "cover": data["cover"],
            "beats": clean}, None


def fallback_beats(user_prompt, style, target, briefs, focals):
    """Deterministic valid beats when the model fails twice (pure).

    Photos in candidate order, roles along the arc, camera from
    focal confidence. Always valid by construction.
    """
    lo, hi = TARGET_SCENES[target]
    ids = [b["photo_id"] for b in briefs]
    n = min(max(len(ids), min(lo, len(ids))), hi)
    take = ids[:max(n, 1)]
    roles = ["establish", "build", "turn", "resolve"][:max(1, min(len(take), 4))]
    phases = ARCS[style].split(", ")
    beats = []
    for i, role in enumerate(roles):
        chunk = take[i::len(roles)]
        if not chunk:
            continue
        conf = min(((focals or {}).get(p) or {}).get("confidence", 0) for p in chunk)
        beats.append({"role": role,
                      "intent": f"{phases[min(i, len(phases) - 1)]} (planned fallback)",
                      "photo_ids": chunk, "pacing": "medium",
                      "camera": "pan_to_focal" if conf >= 0.3 else "push_in",
                      "reason": "Fallback plan: model beats failed validation twice."})
    return {"title": (user_prompt or "").strip()[:80] or "Untitled film",
            "cover": take[0] if take else None, "beats": beats}


def plan_beats(user_prompt, style, target, briefs, focals, trace=None,
               fallback=None, session_id=None):
    """Beat sheet via the director (reasoning, text only).

    briefs: summarize_record() dicts; focals: {photo_id: focal entry}.
    fallback(briefs) may replace the built-in code fallback (the API
    passes the current planner there). Returns (beatsheet, source)
    where source is "director", "director-retry" or "fallback".
    """
    style = normalize_style(style)
    if target not in TARGET_SCENES:
        raise ValueError("target must be short or medium.")
    if not briefs:
        raise ValueError("the director needs at least one photo.")
    base = build_director_prompt(user_prompt, style, target, briefs, focals)
    allowed = [b["photo_id"] for b in briefs]
    last_problems = []
    for attempt in (1, 2):
        prompt = base if attempt == 1 else (
            base + "\nYour last reply was rejected for: "
            + "; ".join(last_problems) + ". Fix every problem.")
        try:
            text = llm.ask(prompt, temperature=0.3, purpose="director",
                           session_id=session_id)["text"]
            data = extract_json(text)
            sheet, last_problems = validate_beatsheet(data, allowed, target)
        except llm.LLMBudgetSpent:
            raise
        except (RuntimeError, ValueError) as e:
            sheet, last_problems = None, [f"unusable reply: {e}"[:120]]
        if sheet is not None:
            if trace is not None:
                trace.append({"step": "planned",
                              "detail": f"Director planned {len(sheet['beats'])} beats "
                                        f"({sum(len(b['photo_ids']) for b in sheet['beats'])} "
                                        f"photos) for {style}, {target}."})
            return sheet, ("director" if attempt == 1 else "director-retry")
        if trace is not None:
            trace.append({"step": "planned",
                          "detail": f"Director attempt {attempt} rejected: "
                                    f"{'; '.join(last_problems)}."})
    sheet = fallback(briefs) if fallback else fallback_beats(
        user_prompt, style, target, briefs, focals)
    if trace is not None:
        trace.append({"step": "planned",
                      "detail": "Model beats failed twice; using the fallback plan."})
    return sheet, "fallback"
