"""Scene assembly for directed stories.

Transitions, cards and pacing are pure code; captions and the editor
pass use the reasoning model via llm.ask, always checked against the
stored records. build_film runs the whole pipeline.
"""
import json
import math
import os
import re
from pathlib import Path

import llm
import narration as narration_mod
import owner_profile as owner_profile_mod
import voices as voices_mod
from chat import extract_json
from director import CAMERAS, PACINGS, ROLES, normalize_style, summarize_record

ROOT = Path(__file__).resolve().parent.parent

TRANSITIONS = ("dissolve", "rise", "descend", "dip", "iris", "vantage",
               "cut")
VANTAGE_A = "You were here"
VANTAGE_B = "and this is what you saw"
FOUND_MIN, FOUND_MAX = 4, 60
PACING_SECONDS = {"slow": 4.0, "medium": 3.0, "quick": 2.0}
BOOKEND_BONUS = 0.5  # establish/resolve breathe a little longer
CARD_BONUS = 1.2
BURST_RATES = {"slow": 0.25, "medium": 0.21, "quick": 0.18}
TARGET_SECONDS = {"short": 20.0, "medium": 40.0}
MIN_SCENE, MAX_SCENE = 1.0, 8.0

HIGH = ("elevated", "aerial")


def transition_for(prev, curr):
    """Transition into curr from prev (pure).

    Each side is {place_key, viewpoint, collection, taken_from_key}.
    Precedence: vantage > iris > rise/descend > dissolve > dip > cut.
    Unknown places never count as same or changed.
    """
    a_personal = prev.get("collection") == "personal"
    b_personal = curr.get("collection") == "personal"
    a_place = prev.get("place_key") or None
    b_place = curr.get("place_key") or None
    if (a_personal and b_personal and a_place
            and (curr.get("taken_from_key") or None) == a_place):
        return "vantage"
    if a_personal and curr.get("collection") == "world":
        return "iris"
    vp_a, vp_b = prev.get("viewpoint"), curr.get("viewpoint")
    if vp_a == "ground_level" and vp_b in HIGH:
        return "rise"
    if vp_a in HIGH and vp_b == "ground_level":
        return "descend"
    if a_place and b_place:
        return "dissolve" if a_place == b_place else "dip"
    return "cut"


def found_text_for(record, place_status):
    """First clear sign of 4-60 chars as a title card (pure).

    Returns {"text", "badge"} or None. The text is the stored
    string exactly, unchanged; badge is Confirmed/Candidate only
    when the place status is known.
    """
    obs = (record or {}).get("observed") or {}
    for t in obs.get("visible_text") or []:
        text = t.get("text") or ""
        if t.get("legibility") == "clear" and FOUND_MIN <= len(text) <= FOUND_MAX:
            status = (place_status or "").lower()
            badge = ("Confirmed" if status == "confirmed"
                     else "Candidate" if status == "candidate" else None)
            return {"text": text, "badge": badge}
    return None


def assemble_scenes(beatsheet, metas, records=None):
    """Beats -> ordered scenes with role/pacing/camera/transition (pure).

    metas maps photo_id -> {place_key, viewpoint, collection,
    taken_from_key}; records maps photo_id -> annotation record.
    The first scene has transition_in None; a vantage transition
    writes the caption notes on both scenes; only the first scene
    of each place gets a found-text card.
    """
    scenes = []
    for b in beatsheet.get("beats") or []:
        role = b.get("role") if b.get("role") in ROLES else "build"
        pacing = b.get("pacing") if b.get("pacing") in PACINGS else "medium"
        camera = b.get("camera") if b.get("camera") in CAMERAS else "push_in"
        for pid in b.get("photo_ids") or []:
            scenes.append({"photo_id": pid, "role": role, "pacing": pacing,
                           "camera": camera, "transition_in": None,
                           "caption_note": None, "found_text": None,
                           "why": str(b.get("reason") or "")})
    seen_places = set()
    for s in scenes:
        key = (metas.get(s["photo_id"]) or {}).get("place_key") or None
        if key in seen_places:
            continue
        seen_places.add(key)
        rec = (records or {}).get(s["photo_id"])
        status = ((rec or {}).get("inferred") or {}).get("place") or {}
        s["found_text"] = found_text_for(rec, status.get("status"))
    for i in range(1, len(scenes)):
        prev = metas.get(scenes[i - 1]["photo_id"]) or {}
        curr = metas.get(scenes[i]["photo_id"]) or {}
        name = transition_for(prev, curr)
        scenes[i]["transition_in"] = name
        if name == "vantage":
            scenes[i - 1]["caption_note"] = VANTAGE_A
            scenes[i]["caption_note"] = VANTAGE_B
    return scenes


def merge_bursts(scenes, bursts):
    """Fold burst frames into stop-motion scenes (pure).

    bursts is a list of id-groups. Consecutive scenes with the same
    role/pacing/camera whose photos share one burst group merge into
    one scene (first scene's fields win; burst-mates are near-copies
    so their transitions would be dissolves anyway). Every scene
    gains frames + frame_seconds (None unless merged).
    """
    sets = [set(g) for g in (bursts or []) if len(set(g)) > 1]

    def burst_of(pid):
        for s in sets:
            if pid in s:
                return s
        return None

    out = []
    for s in scenes:
        cur = dict(s)
        cur["frames"] = [cur["photo_id"]]
        cur["frame_seconds"] = None
        if out:
            prev = out[-1]
            bs = burst_of(cur["photo_id"])
            same_dir = (prev["role"], prev["pacing"], prev["camera"]) == \
                (cur["role"], cur["pacing"], cur["camera"])
            if bs is not None and same_dir \
                    and (set(prev["frames"]) | {cur["photo_id"]}) <= bs:
                prev["frames"].append(cur["photo_id"])
                prev["frame_seconds"] = BURST_RATES.get(prev["pacing"], 0.21)
                continue
        out.append(cur)
    return out


def apply_pacing(scenes, target, trace=None):
    """Seconds per scene, scaled to the target length (pure + trace).

    Base from pacing, +0.5 for establish/resolve, +1.2 with a card;
    burst scenes play frames x rate. Normal scenes scale so the
    total hits the target; bursts keep their rate, clamped 1-8s;
    a miss beyond 10 percent is noted, never hidden.
    """
    for s in scenes:
        frames = s.get("frames") or [s["photo_id"]]
        if len(frames) > 1:
            base = len(frames) * BURST_RATES.get(s.get("pacing"), 0.21)
            s["burst"] = True
        else:
            base = PACING_SECONDS.get(s.get("pacing"), 3.0)
            s["burst"] = False
        if s.get("role") in ("establish", "resolve"):
            base += BOOKEND_BONUS
        if s.get("found_text"):
            base += CARD_BONUS
        s["seconds"] = round(base, 2)
    want = TARGET_SECONDS[target]
    raw = round(sum(s["seconds"] for s in scenes), 2)
    fixed = sum(s["seconds"] for s in scenes if s["burst"])
    flex = [s for s in scenes if not s["burst"]]
    flex_total = sum(s["seconds"] for s in flex)
    if flex and flex_total > 0 and fixed < want:
        factor = (want - fixed) / flex_total
        for s in flex:
            s["seconds"] = round(
                min(MAX_SCENE, max(MIN_SCENE, s["seconds"] * factor)), 2)
    total = round(sum(s["seconds"] for s in scenes), 2)
    if trace is not None:
        detail = (f"Paced {len(scenes)} scenes from {raw}s to {total}s "
                  f"(target {want}s).")
        if want and abs(total - want) / want > 0.10:
            detail += " Outside 10 percent: clamps or fixed burst time."
        trace.append({"step": "paced", "detail": detail})
    return scenes


def _brief_text(b):
    b = b or {}
    own = b.get("owner_present")
    if own is True:
        pos = b.get("owner_position")
        owner_bit = "owner: present" + (f" ({pos})" if pos else "")
    elif own is False:
        owner_bit = "owner: absent"
    else:
        owner_bit = "owner: unknown"
    return (f"{b.get('place') or 'unknown place'} "
            f"({b.get('place_status') or 'unknown'}), "
            f"{b.get('viewpoint') or 'unknown'}, {b.get('scene') or 'unknown scene'}; "
            f"things: {', '.join(b.get('things') or []) or 'none'}; "
            f"signs: {'; '.join(b.get('signs') or []) or 'none'}; "
            f"taken from: {b.get('taken_from') or 'unknown'}; "
            f"people: {b.get('people', 0)}; {owner_bit}")


def _narration_for(briefs, pids, voice, profile):
    """(voice, profile, facts) for caption/editor prompts (pure)."""
    if profile is None:
        try:
            profile = owner_profile_mod.load_profile()
        except Exception:
            profile = None
    voice = narration_mod.resolve_voice(voice, profile)
    facts = {}
    for pid in pids:
        b = briefs.get(pid) or {}
        facts[pid] = {"present": b.get("owner_present"),
                      "position": b.get("owner_position"),
                      "people": b.get("people", 0) or 0}
    return voice, profile, facts


def _scene_owner_ok(text, name, brief, scope="caption"):
    """(repaired, violations) for one scene caption."""
    allowed = (brief or {}).get("owner_present") is True
    return narration_mod.repair_text(text, name, allowed, scope)


def _selection_candidates(evidence, brief):
    """Candidate focus facts: record evidence + the owner's brief."""
    cands = [e for e in (evidence or []) if isinstance(e, str) and e.strip()]
    if isinstance(brief, dict):
        if str(brief.get("about") or "").strip():
            cands.append(f"owner's brief: {str(brief['about']).strip()}")
        if str(brief.get("feeling") or "").strip():
            cands.append(f"owner's feeling: {str(brief['feeling']).strip()}")
    return cands


def _validate_selection(data, cands_by_pid, order):
    """(entries, problems): entries maps pid -> selection (pure)."""
    if not isinstance(data, dict):
        return None, ["reply is not a JSON object"]
    entries, problems = {}, []
    for pos, pid in enumerate(order):
        raw = data.get(pid)
        if not isinstance(raw, dict):
            problems.append(f"missing selection for {pid}")
            continue
        if not (cands_by_pid.get(pid) or []):
            if (raw.get("focus") or "") != "" or raw.get("held_back") != [] \
                    or (raw.get("focus_source") or "") != "" \
                    or raw.get("callback_of") is not None:
                problems.append(f"{pid} has no candidates; leave it empty")
            entries[pid] = {"focus": "", "focus_source": "",
                            "held_back": [], "callback_of": None}
            continue
        focus = raw.get("focus")
        if not isinstance(focus, str) or not focus.strip() or len(focus) > 80:
            problems.append(f"{pid} focus must be 1-80 characters")
        if raw.get("focus_source") not in (cands_by_pid.get(pid) or []):
            problems.append(f"{pid} focus_source is not one of its candidates")
        held = raw.get("held_back")
        if not isinstance(held, list) or any(not isinstance(h, str) for h in held):
            problems.append(f"{pid} held_back must be a string list")
            held = []
        elif any(h not in (cands_by_pid.get(pid) or []) for h in held):
            problems.append(f"{pid} held_back leaves non-candidates")
        cb = raw.get("callback_of")
        if cb is not None and cb not in order[:pos]:
            problems.append(f"{pid} callback_of is not an earlier scene")
        entries[pid] = {"focus": focus.strip()[:80] if isinstance(focus, str) else "",
                        "focus_source": raw.get("focus_source"),
                        "held_back": list(held),
                        "callback_of": cb if cb in order[:pos] else None}
    if problems:
        return None, problems
    return entries, []


def select_details(scenes, beats, briefs, spine, brief=None, trace=None,
                   session_id=None):
    """Pick each scene's focus detail (one model call, in place).

    scenes gain focus_detail {text, source}, held_back [candidate
    strings] and callback_of (photo_id or None). Candidates are the
    record-only evidence strings plus the owner's brief words. The
    focus must be one candidate; held_back lists the rest. Invalid
    output retries once, then code takes each scene's first fact.
    A repeated focus without a callback is switched in code to the
    next unused candidate. Never raises except on budget.
    """
    order = [s["photo_id"] for s in scenes]
    cands = {pid: _selection_candidates(
        evidence_for(briefs.get(pid)), brief) for pid in order}
    intents = {}
    for b in beats or []:
        for pid in b.get("photo_ids") or []:
            intents.setdefault(pid, (b.get("role"), b.get("intent")))
    lines = [f"Story spine: {spine or '(none)'}.",
             "Choose what each scene is ABOUT: exactly one candidate fact per "
             "scene. Reply ONE JSON object keyed by photo id, no prose:",
             '{"<id>": {"focus": "the telling thing, max 80 chars", '
             '"focus_source": "<exactly one candidate below>", '
             '"held_back": ["<other candidates left out>"], '
             '"callback_of": "<earlier photo id>" or null}}']
    for s in scenes:
        pid = s["photo_id"]
        role, intent = intents.get(pid, (s.get("role"), ""))
        lines.append(f"Scene {pid} ({role or 'scene'}: {intent or 'no intent'}):")
        for i, c in enumerate(cands[pid], 1):
            lines.append(f"{i}. {c}")
        if not cands[pid]:
            lines.append("(no candidates; leave this scene empty)")
    if str((brief or {}).get("avoid") or "").strip():
        lines.append("Never choose or echo anything matching what the owner "
                     f"said to avoid: {str(brief['avoid']).strip()}")
    lines.append("Rules: focus comes from focus_source (copy or close "
                 "paraphrase, max 80 chars); held_back lists the other "
                 "candidates left out on purpose; never repeat a "
                 "focus_source across scenes unless callback_of names the "
                 "earlier scene it deliberately echoes.")
    base = "\n".join(lines)
    entries, last_problems = None, []
    for attempt in (1, 2):
        prompt = base if attempt == 1 else (
            base + "\nRejected: " + "; ".join(last_problems) + ". Fix every one.")
        try:
            data = extract_json(llm.ask(
                prompt, temperature=0.2, purpose="script",
                session_id=session_id)["text"])
            entries, last_problems = _validate_selection(data, cands, order)
        except llm.LLMBudgetSpent:
            raise
        except (RuntimeError, ValueError) as e:
            entries, last_problems = None, [f"unusable reply: {e}"[:120]]
        if entries is not None:
            break
    coded = entries is None
    if coded:
        entries = {}
        for pid in order:
            first = (cands[pid] or [""])[0]
            entries[pid] = {"focus": first[:80], "focus_source": first,
                            "held_back": cands[pid][1:], "callback_of": None}
    for s in scenes:
        e = entries[s["photo_id"]]
        s["focus_detail"] = {"text": e["focus"], "source": e["focus_source"]}
        s["held_back"] = e["held_back"]
        s["callback_of"] = e["callback_of"]
    if trace is not None:
        trace.append({"step": "focused",
                      "detail": ("Detail selection failed twice; using each "
                                 "scene's first fact." if coded else
                                 f"Selected the focus detail for {len(scenes)} "
                                 "scene(s).")})
    used = set()
    for s in scenes:
        src = (s.get("focus_detail") or {}).get("source") or ""
        if src and src in used and not s.get("callback_of"):
            alt = next((c for c in cands[s["photo_id"]] if c not in used), None)
            if alt is None:
                if trace is not None:
                    trace.append({"step": "focused",
                                  "detail": f"Scene {s['photo_id']} repeats an "
                                  "earlier focus (no alternative candidate)."})
                continue
            s["focus_detail"] = {"text": alt[:80], "source": alt}
            s["held_back"] = [src] + [h for h in s.get("held_back", [])
                                      if h != alt]
            if trace is not None:
                trace.append({"step": "focused",
                              "detail": f"Scene {s['photo_id']} focus repeated "
                              f"an earlier scene; switched to {alt[:60]}."})
            used.add(alt)
        elif src:
            used.add(src)
    return scenes


WORDS_PER_SECOND = 2.5
FINAL_SHORT_WORDS = 12


def _fit_range(seconds):
    """(lo, hi) narration words fitting a scene at 2.5 wps ±15% (pure)."""
    sec = max(0.5, float(seconds or 0))
    return int(WORDS_PER_SECOND * 0.85 * sec), math.ceil(WORDS_PER_SECOND * 1.15 * sec)


_STOP_WORDS = frozenset(
    "a an the and or but of to in on at for is are was were be been it its "
    "as by from with that this these those then than next here there you your "
    "yours i me my we our they them their what when where which while who how "
    "not no yes if so very just more most into over after before again once "
    "narrator vlog guys look see watch hey welcome back another across still "
    "every under bright daylight".split())


def _content_words(text, extra=()):
    """Lowercased content words longer than 4 chars (pure)."""
    stop = _STOP_WORDS | {w.lower() for w in extra}
    return {w for w in re.findall(r"[a-z']+", (text or "").lower())
            if len(w) > 4 and w not in stop}


def _validate_script(data, need, name):
    """(entries, title, openings, problems) for one script reply (pure).

    need: scenes in order, each with photo_id + seconds. entries maps
    pid -> {narration, caption, silent_reason}. The final scene must
    land on a short non-silent line (lower fit bound waived); the
    closing must share a content word with the opening unless the
    opening is silent.
    """
    if not isinstance(data, dict):
        return None, None, [], ["reply is not a JSON object"]
    problems = []
    title = data.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 80:
        problems.append("title must be 1-80 characters")
    openings = data.get("openings")
    if not isinstance(openings, list) or len(openings) != 3 \
            or any(not isinstance(o, str) or not o.strip() or len(o) > 280
                   for o in openings):
        problems.append("openings must be 3 non-empty lines")
    got = data.get("scenes")
    if not isinstance(got, dict):
        return None, None, [], problems + ["scenes is not an object"]
    entries, silent = {}, 0
    for pos, s in enumerate(need):
        pid = s["photo_id"]
        raw = got.get(pid)
        if not isinstance(raw, dict):
            problems.append(f"missing script for {pid}")
            continue
        narr = raw.get("narration")
        if not isinstance(narr, str):
            problems.append(f"{pid} narration is not a string")
            narr = ""
        cap = raw.get("caption")
        if not isinstance(cap, str) or len(cap.split()) > 10:
            problems.append(f"{pid} caption must be 10 words or fewer")
            cap = cap if isinstance(cap, str) else ""
        reason = raw.get("silent_reason")
        if narr.strip():
            words = len(narr.split())
            if pos == len(need) - 1:
                hi = min(FINAL_SHORT_WORDS, _fit_range(s.get("seconds"))[1])
                if words > hi:
                    problems.append(f"{pid} final line must be {hi} words or fewer")
            else:
                lo, hi = _fit_range(s.get("seconds"))
                if not lo <= words <= hi:
                    problems.append(
                        f"{pid} narration is {words} words, needs {lo}-{hi}")
        else:
            silent += 1
            if not isinstance(reason, str) or not reason.strip():
                problems.append(f"{pid} silent scene needs a reason")
        entries[pid] = {"narration": narr.strip(),
                        "caption": cap.strip(),
                        "silent_reason": (reason.strip()[:140]
                                          if isinstance(reason, str) else "")}
    if silent * 4 > len(need):
        problems.append(f"{silent} of {len(need)} scenes silent (max a quarter)")
    openers = {}
    for s in need:
        narr = entries.get(s["photo_id"], {}).get("narration", "")
        if not narr.strip():
            continue
        op = " ".join(narr.split()[:3]).lower()
        if op in openers:
            problems.append(
                f"{s['photo_id']} opens the same way as {openers[op]}")
        else:
            openers[op] = s["photo_id"]
    first = entries.get(need[0]["photo_id"], {}).get("narration", "") if need else ""
    last = entries.get(need[-1]["photo_id"], {}).get("narration", "") if need else ""
    if first.strip() and last.strip() and \
            not (_content_words(first, [name]) & _content_words(last, [name])):
        problems.append("closing line does not echo the opening")
    if problems:
        return None, None, [], problems
    return (entries, title.strip()[:80],
            [o.strip()[:280] for o in openings], [])


def _fit_fallback(stored, seconds):
    """Stored caption cut to the scene's word budget (pure)."""
    words = str(stored or "").split()
    if not words:
        return ""
    _, hi = _fit_range(seconds)
    if len(words) <= hi:
        return " ".join(words)
    sents = [s for s in re.split(r"(?<=[.!?])\s+", str(stored).strip()) if s]
    out = []
    for s in sents:
        if len(" ".join(out + [s]).split()) <= hi:
            out.append(s)
        else:
            break
    if out:
        return " ".join(out)
    return " ".join(words[:hi])


def write_script(scenes, briefs, beats, spine, brief=None, style="postcard",
                 trace=None, session_id=None, voice=None, profile=None,
                 image_path=None):
    """(title, openings): the whole script in one model call.

    briefs maps photo_id -> summarize_record() dict. Each scene gains
    narration (the spoken line, "" when silent), silent + silent_reason,
    caption (short on-screen text, "" allowed) and narration_source /
    caption_source. Vantage scenes keep their note as both lines (set
    in code, no model). The model studies the attached photos for
    feel and detail, but the records are the fact authority. Invalid
    output retries once, then each scene falls back to its stored
    caption. Narration is code-checked for owner references and
    voice; repaired lines fall back when emptied. Budget errors
    propagate.
    """
    need = [s for s in scenes if not s.get("caption_note")]
    for s in scenes:
        if s.get("caption_note"):
            s["narration"] = s["caption_note"]
            s["caption"] = s["caption_note"]
            s["silent"] = False
            s["silent_reason"] = ""
            s["narration_source"] = "vantage-note"
            s["caption_source"] = "vantage-note"
    if not need:
        return None, []
    voice, profile, facts = _narration_for(
        briefs, [s["photo_id"] for s in need], voice, profile)
    name = (profile or {}).get("name") or ""
    intents = {}
    for b in beats or []:
        for pid in b.get("photo_ids") or []:
            intents.setdefault(pid, (b.get("role"), b.get("intent")))
    lines = ["Write the whole film script in one voice, one line per scene.",
             f"Story spine: {spine or '(none)'}.",
             "A line never narrates what the viewer can already see: add the "
             "angle it was seen from, the contrast with the previous scene, "
             "what the owner told us about the day, or a reflection that "
             "follows from the facts.",
             "Use ONLY the stored facts below. Never add outside facts, never "
             "invent: no dates, no history, no names but the owner's, no "
             "places not in the records.",
             "Study the attached photos (labelled top to bottom) with these "
             "facts: let the photos guide the feel and the choice of detail, "
             "but every claim must be backed by the stored facts.",
             voices_mod.voice_block(style),
             narration_mod.rules_block(profile, facts, voice)]
    if isinstance(brief, dict):
        about = str(brief.get("about") or "").strip()
        feeling = str(brief.get("feeling") or "").strip()
        avoid = str(brief.get("avoid") or "").strip()
        if about or feeling:
            lines.append("The owner's own words about this day (provided "
                         "facts, usable as facts): "
                         + "; ".join(x for x in
                                     [f"about: {about}" if about else "",
                                      f"feeling: {feeling}" if feeling else ""]
                                     if x))
        if avoid:
            lines.append(f"Never mention or echo: {avoid}.")
    for s in need:
        pid = s["photo_id"]
        lo, hi = _fit_range(s.get("seconds"))
        role, intent = intents.get(pid, (s.get("role"), ""))
        foc = (s.get("focus_detail") or {}).get("text") or "(no focus)"
        lines.append(f"Scene {pid} ({role or 'scene'}, {s.get('seconds')}s, "
                     f"aim {lo}-{hi} words; intent: {intent or 'none'}):")
        lines.append(f"  focus: {foc}")
        lines.append(f"  facts: {_brief_text(briefs.get(pid))}")
    if style == "cinematic" and len(need) >= 4:
        lines.append("Cinematic craft: leave exactly one scene silent "
                     "(empty narration with a silent_reason) — pick the "
                     "scene where stillness says the most.")
    lines.append("Reply ONE JSON object, no prose: "
                 '{"title": "…", "openings": ["…", "…", "…"], '
                 '"scenes": {"<id>": {"narration": "the spoken line (or \\"\\" '
                 'for a deliberate silent scene)", "caption": "on-screen text, '
                 '10 words or fewer (or \\"\\")", '
                 '"silent_reason": "why silent (or \\"\\")"}}}. '
                 "Rules: narration fits its scene at about 2.5 words per "
                 "second (±15%); at most a quarter of the scenes are silent, "
                 "each with a reason; the closing line echoes an image or "
                 "phrase from the opening; the final scene lands on a short "
                 "line (12 words or fewer). Openings are three alternative "
                 "first lines.")
    base = "\n".join(lines)
    pids = [s["photo_id"] for s in need]
    entries, wtitle, openings, last_problems = None, None, [], []
    for attempt in (1, 2):
        prompt = base if attempt == 1 else (
            base + "\nRejected: " + "; ".join(last_problems) + ". Fix every one.")
        try:
            data = extract_json(llm.ask(
                prompt, temperature=0.3, purpose="script",
                session_id=session_id, image_path=image_path)["text"])
            entries, wtitle, openings, last_problems = _validate_script(
                data, need, name)
        except llm.LLMBudgetSpent:
            raise
        except (RuntimeError, ValueError) as e:
            entries, last_problems = None, [f"unusable reply: {e}"[:120]]
            continue
        if entries is not None and voice in ("you", "i"):
            want = '"you"' if voice == "you" else '"I"'
            last_problems = [
                f"wrong voice in {p}: use {want}, not the name"
                for p in pids
                if entries[p]["narration"]
                and (briefs.get(p) or {}).get("owner_present") is True
                and narration_mod.voice_spans(entries[p]["narration"], name,
                                              voice)]
            if last_problems:
                entries = None
        if entries is not None:
            break
    if entries is None:
        for s in need:
            stored = ((briefs.get(s["photo_id"]) or {}).get("caption")
                      or s["photo_id"])
            s["narration"] = _fit_fallback(stored, s.get("seconds"))
            s["caption"] = " ".join(stored.split()[:10])
            s["silent"] = False
            s["silent_reason"] = ""
            s["narration_source"] = "stored-caption"
            s["caption_source"] = "stored-caption"
        if trace is not None:
            trace.append({"step": "wrote",
                          "detail": "Script writing failed twice; using stored "
                                    "captions."})
        return None, []
    repaired = 0
    for s in need:
        e = entries[s["photo_id"]]
        narr, bad = _scene_owner_ok(e["narration"], name,
                                    briefs.get(s["photo_id"]))
        if bad:
            repaired += 1
            stored = ((briefs.get(s["photo_id"]) or {}).get("caption")
                      or s["photo_id"])
            narr = _fit_fallback(stored, s.get("seconds")) if not narr else narr
        cap, bad_cap = _scene_owner_ok(e["caption"], name,
                                       briefs.get(s["photo_id"]))
        if bad_cap:
            repaired += 1
            cap = cap if cap else ""
        s["narration"] = narr
        s["caption"] = " ".join(cap.split()[:10])
        s["silent"] = not bool(narr.strip())
        s["silent_reason"] = e["silent_reason"] if s["silent"] else ""
        s["narration_source"] = "script-model"
        s["caption_source"] = "script-model"
    if trace is not None:
        detail = (f"Wrote the script for {len(need)} scenes."
                  if image_path is None else
                  f"Wrote the script for {len(need)} scenes studying the "
                  "photos with their records.")
        if repaired:
            detail += f" Removed unsupported owner references in {repaired}."
        trace.append({"step": "wrote", "detail": detail})
    return wtitle, openings


CRITIC_FLAGS = ("lists", "cliche", "repetition", "narrates the obvious",
                  "flat description", "too long for the scene",
                  "breaks the voice", "uses a banned phrase")


def _validate_critique(data, pids):
    """(entries, problems) for one critic reply (pure)."""
    if not isinstance(data, dict):
        return None, ["reply is not a JSON object"]
    entries, problems = {}, []
    for pid in pids:
        raw = data.get(pid)
        if not isinstance(raw, dict):
            problems.append(f"missing critique for {pid}")
            continue
        flags = raw.get("flags")
        if not isinstance(flags, list) \
                or any(f not in CRITIC_FLAGS for f in flags):
            problems.append(f"{pid} flags must come from the allowed list")
            flags = []
        note = raw.get("note")
        if note is not None and not isinstance(note, str):
            problems.append(f"{pid} note is not a string")
            note = ""
        entries[pid] = {"flags": list(flags), "note": (note or "")[:280]}
    if problems:
        return None, problems
    return entries, []


def _speaking(scenes):
    """Scenes with a draft spoken line (vantage + silent excluded)."""
    return [s for s in scenes
            if not s.get("caption_note") and (s.get("narration") or "").strip()]


def check_notes(notes, ids):
    """Cleaned {photo_id: note} for scene notes (pure).

    Notes are owner-provided facts (140 chars max). Unknown
    photo ids, non-strings and over-long notes raise
    ValueError; blank notes are dropped.
    """
    if not notes:
        return {}
    if not isinstance(notes, dict):
        raise ValueError("notes must map photo ids to text.")
    known = set(ids or [])
    cleaned = {}
    for pid, note in notes.items():
        if pid not in known:
            raise ValueError(f"note for unknown photo: {pid}")
        if not isinstance(note, str) or not note.strip():
            if isinstance(note, str):
                continue
            raise ValueError(f"note for {pid} must be text.")
        if len(note.strip()) > 140:
            raise ValueError(f"note for {pid} must be 140 characters or fewer.")
        cleaned[pid] = note.strip()
    return cleaned


def critique_script(scenes, briefs, style, trace=None, session_id=None):
    """{pid: {flags, note}} for lines needing a rewrite (one model call).

    Only speaking scenes are judged. Invalid output retries once,
    then the draft is kept. Never raises except on budget.
    """
    need = _speaking(scenes)
    if not need:
        return {}
    lines = ["Criticize each narration line as craft, not facts. Voice: "
             + style + ".",
             "Reply ONE JSON object keyed by photo id, no prose: "
             '{"<id>": {"flags": [...], "note": "..."}}. Use [] when a '
             "line is fine. Allowed flags, exactly: " + "; ".join(CRITIC_FLAGS)
             + "."]
    for s in need:
        lines.append(f"Scene {s['photo_id']} ({s.get('seconds')}s): "
                     f"{s.get('narration')}")
        lines.append(f"  focus: {(s.get('focus_detail') or {}).get('text') or '-'}")
        lines.append(f"  facts: {_brief_text(briefs.get(s['photo_id']))}")
    base = "\n".join(lines)
    pids = [s["photo_id"] for s in need]
    entries, last_problems = None, []
    for attempt in (1, 2):
        prompt = base if attempt == 1 else (
            base + "\nRejected: " + "; ".join(last_problems) + ". Fix every one.")
        try:
            data = extract_json(llm.ask(
                prompt, temperature=0.3, purpose="critic",
                session_id=session_id)["text"])
            entries, last_problems = _validate_critique(data, pids)
        except llm.LLMBudgetSpent:
            raise
        except (RuntimeError, ValueError) as e:
            entries, last_problems = None, [f"unusable reply: {e}"[:120]]
        if entries is not None:
            break
    if entries is None:
        if trace is not None:
            trace.append({"step": "critiqued",
                          "detail": "Critic failed twice; keeping the draft."})
        return {}
    flagged = {p: e for p, e in entries.items() if e["flags"]}
    if trace is not None:
        n = sum(len(e["flags"]) for e in flagged.values())
        if not flagged:
            detail = "Critic found no issues."
        else:
            per = "; ".join(f"{p}: {', '.join(e['flags'])}"
                            for p, e in sorted(flagged.items()))
            detail = (f"Critic found {n} issues in {len(flagged)} "
                      f"lines ({per}).")
        trace.append({"step": "critiqued", "detail": detail})
    return flagged


def rewrite_lines(scenes, briefs, flagged, style, voice, profile,
                  trace=None, session_id=None, label="flagged", notes=None):
    """Rewrite flagged lines in place (one model call).

    Lines that fail fit, voice or owner checks keep their draft.
    If the rewrite breaks a working closing echo, the opening and
    closing fall back to their draft lines. label names the lines
    in the trace. notes maps photo ids to owner notes (provided
    facts, worked into the flagged scenes that carry them).
    Never raises except on budget.
    """
    need = _speaking(scenes)
    order = [s["photo_id"] for s in need]
    pids = [p for p in order if p in flagged]
    if not pids:
        return
    by_id = {s["photo_id"]: s for s in scenes}
    rvoice, rprofile, _ = _narration_for(briefs, pids, voice, profile)
    name = (rprofile or {}).get("name") or ""
    draft = {p: (by_id[p].get("narration") or "",
                 by_id[p].get("caption") or "") for p in pids}
    draft_echo = bool(_content_words(by_id[order[0]].get("narration"), [name])
                      & _content_words(by_id[order[-1]].get("narration"), [name]))
    lines = ["Rewrite these flagged narration lines in the " + style + " voice.",
             narration_mod.rules_block(rprofile, {p: {
                 "present": (briefs.get(p) or {}).get("owner_present"),
                 "position": (briefs.get(p) or {}).get("owner_position"),
                 "people": (briefs.get(p) or {}).get("people", 0) or 0}
                 for p in pids}, rvoice),
             "Reply ONE JSON object keyed by photo id, no prose: "
             '{"<id>": {"narration": "…", "caption": "≤10 words"}}. '
             "Keep each line's spirit; fix only what the flags name. "
             "The closing line must still echo the opening."]
    for p in pids:
        s = by_id[p]
        lo, hi = _fit_range(s.get("seconds"))
        if p == order[-1]:
            hi = min(FINAL_SHORT_WORDS, hi)
        lines.append(f"Scene {p} (aim {lo}-{hi} words; "
                     f"flags: {', '.join(flagged[p]['flags'])}; "
                     f"note: {flagged[p]['note'] or '-'}):")
        lines.append(f"  line: {s.get('narration')}")
        lines.append(f"  facts: {_brief_text(briefs.get(p))}")
        if (notes or {}).get(p):
            lines.append("  owner note (the owner's own words, a provided "
                         f"fact — work it in): {notes[p]}")
    base = "\n".join(lines)
    fresh, last_problems = None, []
    for attempt in (1, 2):
        prompt = base if attempt == 1 else (
            base + "\nRejected: " + "; ".join(last_problems) + ". Fix every one.")
        try:
            data = extract_json(llm.ask(
                prompt, temperature=0.3, purpose="rewrite",
                session_id=session_id)["text"])
            fresh, last_problems = _validate_rewrite(data, by_id, pids, order)
        except llm.LLMBudgetSpent:
            raise
        except (RuntimeError, ValueError) as e:
            fresh, last_problems = None, [f"unusable reply: {e}"[:120]]
        if fresh is not None:
            break
    if fresh is None:
        if trace is not None:
            trace.append({"step": "rewrote",
                          "detail": "Rewrite failed twice; keeping the draft lines."})
        return
    applied, kept = 0, 0
    for p in pids:
        narr, bad = narration_mod.repair_text(
            fresh[p]["narration"], name,
            (briefs.get(p) or {}).get("owner_present") is True, "caption")
        cap, bad_cap = narration_mod.repair_text(
            fresh[p]["caption"], name,
            (briefs.get(p) or {}).get("owner_present") is True, "caption")
        if bad or bad_cap or (rvoice in ("you", "i") and narration_mod.voice_spans(
                narr, name, rvoice)):
            kept += 1
            continue
        by_id[p]["narration"] = narr
        by_id[p]["caption"] = " ".join(cap.split()[:10])
        by_id[p]["narration_source"] = "script-rewrite"
        by_id[p]["caption_source"] = "script-rewrite"
        applied += 1
    if draft_echo and not (_content_words(by_id[order[0]].get("narration"), [name])
                           & _content_words(by_id[order[-1]].get("narration"), [name])):
        for p in (order[0], order[-1]):
            if p in pids:
                by_id[p]["narration"], by_id[p]["caption"] = draft[p]
        if trace is not None:
            trace.append({"step": "rewrote",
                          "detail": "Kept the draft opening and closing to "
                                    "preserve the echo."})
    if trace is not None:
        detail = f"Rewrote {applied} {label} line{'s' if applied != 1 else ''}."
        if kept:
            detail += f" Kept the draft for {kept}."
        trace.append({"step": "rewrote", "detail": detail})


def _validate_rewrite(data, by_id, pids, order):
    """(entries, problems) for one rewrite reply (pure)."""
    if not isinstance(data, dict):
        return None, ["reply is not a JSON object"]
    entries, problems = {}, []
    for p in pids:
        raw = data.get(p)
        if not isinstance(raw, dict):
            problems.append(f"missing rewrite for {p}")
            continue
        narr = raw.get("narration")
        if not isinstance(narr, str) or not narr.strip():
            problems.append(f"{p} rewrite is empty")
            continue
        words = len(narr.split())
        lo, hi = _fit_range(by_id[p].get("seconds"))
        if p == order[-1]:
            hi = min(FINAL_SHORT_WORDS, hi)
            if words > hi:
                problems.append(f"{p} rewrite must be {hi} words or fewer")
        elif not lo <= words <= hi:
            problems.append(f"{p} rewrite is {words} words, needs {lo}-{hi}")
        cap = raw.get("caption")
        if not isinstance(cap, str) or len(cap.split()) > 10:
            problems.append(f"{p} rewritten caption must be 10 words or fewer")
            cap = ""
        entries[p] = {"narration": narr.strip(), "caption": cap.strip()}
    if problems:
        return None, problems
    return entries, []


def judge_opening(scenes, briefs, openings, spine, style, voice, profile,
                  trace=None, session_id=None):
    """Replace the opening line with the judged best alternative (in place).

    One model call ranks the openings; the first one that fits the
    opening scene, echoes the closing and passes the owner checks
    wins. Anything failing keeps the draft opening. Never raises
    except on budget.
    """
    if not openings:
        if trace is not None:
            trace.append({"step": "judged",
                          "detail": "No alternative openings; kept the draft opening."})
        return
    first = scenes[0] if scenes else None
    if first is None or first.get("caption_note") \
            or not (first.get("narration") or "").strip():
        if trace is not None:
            trace.append({"step": "judged",
                          "detail": "The opening is fixed; kept it."})
        return
    need = _speaking(scenes)
    closing = need[-1].get("narration") or "" if need else ""
    rvoice, rprofile, _ = _narration_for(
        briefs, [first["photo_id"]], voice, profile)
    name = (rprofile or {}).get("name") or ""
    allowed = (briefs.get(first["photo_id"]) or {}).get("owner_present") is True
    lo, hi = _fit_range(first.get("seconds"))
    lines = ["Rank these three alternative opening lines for the film.",
             f"Spine: {spine or '(none)'}. Voice: {style}.",
             f"The winner must be {lo}-{hi} words and share a striking word "
             f"with the closing line: {closing or '(none)'}.",
             "Reply ONE JSON object, no prose: "
             '{"ranking": ["<opening text>", ...], "reason": "..."}.']
    for i, o in enumerate(openings, 1):
        lines.append(f"{i}. {o}")
    base = "\n".join(lines)
    ranking, reason, last_problems = None, "", []
    for attempt in (1, 2):
        prompt = base if attempt == 1 else (
            base + "\nRejected: " + "; ".join(last_problems) + ". Fix every one.")
        try:
            data = extract_json(llm.ask(
                prompt, temperature=0.2, purpose="judge",
                session_id=session_id)["text"])
            ranking, reason, last_problems = _validate_judge(data, openings)
        except llm.LLMBudgetSpent:
            raise
        except (RuntimeError, ValueError) as e:
            ranking, last_problems = None, [f"unusable reply: {e}"[:120]]
        if ranking is not None:
            break
    if ranking is None:
        if trace is not None:
            trace.append({"step": "judged",
                          "detail": "Judge failed twice; kept the draft opening."})
        return
    for choice in ranking:
        words = len(choice.split())
        if not lo <= words <= hi:
            continue
        if len(need) <= 1:
            echo_ok = bool(_content_words(choice, [name]))
        else:
            echo_ok = bool(_content_words(choice, [name])
                            & _content_words(closing, [name]))
        if not echo_ok:
            continue
        fixed, bad = narration_mod.repair_text(choice, name, allowed, "caption")
        if bad or (rvoice in ("you", "i")
                   and narration_mod.voice_spans(fixed, name, rvoice)):
            continue
        first["narration"] = fixed
        first["narration_source"] = "script-judge"
        if trace is not None:
            n = openings.index(choice) + 1
            trace.append({"step": "judged",
                          "detail": f"Opening {n} chosen: {reason}"[:280]})
        return
    if trace is not None:
        trace.append({"step": "judged",
                      "detail": "No opening fit; kept the draft opening."})


def _validate_judge(data, openings):
    """(ranking, reason, problems) for one judge reply (pure)."""
    if not isinstance(data, dict):
        return None, "", ["reply is not a JSON object"]
    ranking = data.get("ranking")
    reason = data.get("reason")
    problems = []
    if not isinstance(ranking, list) or sorted(ranking) != sorted(openings):
        problems.append("ranking must list the three openings")
    if not isinstance(reason, str) or not reason.strip():
        problems.append("judge gave no reason")
    if problems:
        return None, "", problems
    return list(ranking), reason.strip()[:280], []


def fit_durations(scenes, briefs, target, style, voice, profile,
                  trace=None, session_id=None):
    """Fit every narration inside its scene (in place).

    A line longer than its scene extends the scene up to 1.5s;
    lines still too long go through the rewrite pass once with a
    too-long flag. Vantage and silent lines are fixed and skipped.
    The closing line is held to FINAL_SHORT_WORDS even when it
    fits its scene's range (the editor can lengthen it after the
    writer's validation). The final total is traced against the
    target (±10%). Never raises except on budget.
    """
    need = [s for s in scenes if not s.get("caption_note")]
    final_pid = need[-1]["photo_id"] if need else None

    def cap(s):
        hi = _fit_range(s.get("seconds"))[1]
        if final_pid is not None and s["photo_id"] == final_pid:
            hi = min(FINAL_SHORT_WORDS, hi)
        return hi

    extended = False
    for s in scenes:
        narr = (s.get("narration") or "").strip()
        if not narr or s.get("caption_note"):
            continue
        words = len(narr.split())
        sec = float(s.get("seconds") or 0)
        if words <= cap(s):
            continue
        ext = round(min(1.5, max(0.0, words / WORDS_PER_SECOND - sec)), 2)
        if ext > 0:
            s["seconds"] = round(sec + ext, 2)
            extended = True
            if trace is not None:
                trace.append({"step": "fitted",
                              "detail": f"Scene {s['photo_id']} extended to "
                              f"{s['seconds']}s for its narration."})
    left = [s["photo_id"] for s in scenes
            if (s.get("narration") or "").strip() and not s.get("caption_note")
            and len(s["narration"].split()) > cap(s)]
    if left:
        rewrite_lines(scenes, briefs,
                      {p: {"flags": ["too long for the scene"],
                           "note": "shorten to fit"} for p in left},
                      style, voice, profile, trace, session_id,
                      label="over-long")
        for s in scenes:
            narr = (s.get("narration") or "").strip()
            if s["photo_id"] in left and narr \
                    and len(narr.split()) > cap(s):
                if trace is not None:
                    trace.append({"step": "fitted",
                                  "detail": f"Scene {s['photo_id']} narration "
                                  f"still exceeds its scene ({len(narr.split())} "
                                  "words)."})
    total = round(sum(float(s.get("seconds") or 0) for s in scenes), 2)
    room = TARGET_SECONDS.get(target, 20.0)
    if trace is not None:
        if not extended and not left:
            trace.append({"step": "fitted",
                          "detail": "All lines fit their scenes."})
        else:
            detail = f"Final length {total}s (target {room}s)."
            if abs(total - room) > room * 0.1:
                detail = f"Final length {total}s (target {room}s, outside 10 percent)."
            trace.append({"step": "fitted", "detail": detail})


def _sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s]


def _check_verdict(v):
    return isinstance(v, dict) and v.get("verdict") in ("supported", "unsupported") \
        and (v.get("rewrite") is None or isinstance(v.get("rewrite"), str))


def edit_captions(title, beats, scenes, briefs, trace=None, session_id=None,
                  voice=None, profile=None, notes=None):
    """Verify every narration + caption sentence against the records.

    One model call. Vantage-note lines are code, already true, and
    skipped. notes maps photo ids to owner notes, which count as
    provided facts for their scenes. Returns (title, beats, scenes,
    verification).
    Unsupported claims are rewritten once or removed; scenes left
    fully empty are dropped; the title and beat intents are
    rewritten when fixable. The owner's name (or you/I) may stay
    only in scenes whose photos have owner.present true — the model
    verdicts enforce this, and a code check afterwards drops what
    slips through. Scenes without a narration key are checked
    caption-only (legacy shape). Any failure of the pass itself
    marks the film not verified. Budget errors propagate.
    """
    beats = [dict(b) for b in (beats or [])]
    checkable = [s for s in scenes if not s.get("caption_note")]
    sents = {}
    for s in checkable:
        if s.get("narration") is None:
            fields = [("caption", s.get("caption") or "")]
        else:
            fields = [("narration", s.get("narration") or ""),
                      ("caption", s.get("caption") or "")]
        sents[s["photo_id"]] = [(kind, sent) for kind, text in fields
                                for sent in _sentences(text)]
    voice, profile, facts = _narration_for(
        briefs, [s["photo_id"] for s in checkable], voice, profile)
    name = (profile or {}).get("name") or ""
    lines = ["Check each sentence against ONLY the stored facts for its photo,",
             "plus any owner note given with those facts.",
             narration_mod.rules_block(profile, facts, voice),
             "Judge owner references by those rules: the owner's name (or you/I) "
             "is supported ONLY in a scene whose photo facts say owner present, "
             "unsupported everywhere else (rewrite without it, or null).",
             'Verdict per claim: "supported" or "unsupported". For unsupported',
             "claims give a rewrite from stored facts only, or null to remove.",
             "Output ONE JSON object, no prose:",
             '{"title": {"verdict": …, "rewrite": …|null},',
             ' "intents": [{"verdict": …, "rewrite": …|null}],',
             ' "scenes": {"<photo_id>": {"claims": [{"verdict": …, "rewrite": …|null}]}}}',
             f"Title: {title}"]
    for i, b in enumerate(beats):
        lines.append(f"Intent {i}: {b.get('intent') or ''}")
    for s in checkable:
        facts_line = (f"Photo {s['photo_id']} facts: "
                      f"{_brief_text(briefs.get(s['photo_id']))}")
        if (notes or {}).get(s["photo_id"]):
            facts_line += f" Owner note (provided fact): {notes[s['photo_id']]}"
        lines.append(facts_line)
        for i, (kind, sent) in enumerate(sents[s["photo_id"]]):
            lines.append(f"Photo {s['photo_id']} {kind} sentence {i}: {sent}")
    verification = {"checked": 0, "fixed": 0, "dropped": [],
                    "verified": True, "note": ""}
    try:
        data = extract_json(llm.ask(
            "\n".join(lines), temperature=0.1, purpose="editor",
            session_id=session_id)["text"])
        if not isinstance(data, dict) or not _check_verdict(data.get("title")):
            raise ValueError("bad title verdict")
        intents = data.get("intents")
        if not isinstance(intents, list) or len(intents) != len(beats) \
                or not all(_check_verdict(v) for v in intents):
            raise ValueError("bad intent verdicts")
        got = data.get("scenes")
        if not isinstance(got, dict):
            raise ValueError("bad scene verdicts")
        for pid, lst in sents.items():
            claims = (got.get(pid) or {}).get("claims")
            if not isinstance(claims, list) or len(claims) != len(lst) \
                    or not all(_check_verdict(c) for c in claims):
                raise ValueError(f"bad claims for {pid}")
    except llm.LLMBudgetSpent:
        raise
    except (RuntimeError, ValueError) as e:
        verification["verified"] = False
        verification["note"] = f"editor pass failed: {e}"[:160]
        if trace is not None:
            trace.append({"step": "checked",
                          "detail": "Editor pass failed; film not verified."})
        return title, beats, scenes, verification
    fixed = 0
    new_title, titles_clean = title, True
    if data["title"]["verdict"] == "unsupported":
        if data["title"]["rewrite"]:
            new_title = data["title"]["rewrite"].strip()[:80]
            fixed += 1
        else:
            titles_clean = False
    for b, v in zip(beats, data["intents"]):
        if v["verdict"] == "unsupported":
            if v["rewrite"]:
                b["intent"] = v["rewrite"].strip()[:280]
                fixed += 1
            else:
                titles_clean = False
    kept = []
    for s in scenes:
        if s in checkable:
            if not sents[s["photo_id"]] and s.get("narration") is not None:
                kept.append(s)
                continue
            outs = {"narration": [], "caption": []}
            for (kind, sent), claim in zip(sents[s["photo_id"]],
                                           data["scenes"][s["photo_id"]]["claims"]):
                if claim["verdict"] == "supported":
                    outs[kind].append(sent)
                elif claim["rewrite"]:
                    outs[kind].append(claim["rewrite"].strip())
                    fixed += 1
                else:
                    fixed += 1
            if s.get("narration") is None:
                if not outs["caption"]:
                    verification["dropped"].append(s["photo_id"])
                    continue
                cap = " ".join(outs["caption"])[:280]
                cap, bad = _scene_owner_ok(cap, name, briefs.get(s["photo_id"]))
                if bad:
                    fixed += 1
                    if not cap:
                        verification["dropped"].append(s["photo_id"])
                        continue
                s["caption"] = cap
            else:
                narr = " ".join(outs["narration"])[:280]
                cap = " ".join(outs["caption"])[:280]
                narr, bad_n = _scene_owner_ok(narr, name, briefs.get(s["photo_id"]))
                cap, bad_c = _scene_owner_ok(cap, name, briefs.get(s["photo_id"]))
                if bad_n or bad_c:
                    fixed += 1
                if not narr.strip() and not cap.strip():
                    verification["dropped"].append(s["photo_id"])
                    continue
                s["narration"] = narr
                s["caption"] = " ".join(cap.split()[:10])
                s["silent"] = not bool(narr.strip())
                if s["silent"] and not s.get("silent_reason"):
                    s["silent_reason"] = "Every claim failed verification."
        kept.append(s)
    checked = sum(len(v) for v in sents.values()) + 1 + len(beats)
    verification["checked"] = checked
    verification["fixed"] = fixed
    verification["verified"] = titles_clean
    note = f"checked against records: {checked} claims, {fixed} fixed"
    if verification["dropped"]:
        note += f"; dropped {', '.join(verification['dropped'])}"
    if not titles_clean:
        note += "; title or intent unfixable: not verified"
    verification["note"] = note
    if trace is not None:
        trace.append({"step": "checked", "detail": note[0].upper() + note[1:] + "."})
    return new_title, beats, kept, verification


def _refit_scenes(scenes, metas, records):
    """Re-derive transitions, notes, lines and cards after drops (pure).

    Neighbourhoods changed, so transitions, vantage notes and
    first-per-place cards are recomputed from scratch; model lines
    stay, vantage lines follow their notes.
    """
    had_note = {s["photo_id"] for s in scenes if s.get("caption_note")}
    for s in scenes:
        s["caption_note"] = None
    for i, s in enumerate(scenes):
        if i == 0:
            s["transition_in"] = None
            continue
        prev = metas.get(scenes[i - 1]["photo_id"]) or {}
        curr = metas.get(s["photo_id"]) or {}
        name = transition_for(prev, curr)
        s["transition_in"] = name
        if name == "vantage":
            scenes[i - 1]["caption_note"] = VANTAGE_A
            s["caption_note"] = VANTAGE_B
    for s in scenes:
        if s.get("caption_note"):
            s["narration"] = s["caption_note"]
            s["caption"] = s["caption_note"]
            s["silent"] = False
            s["silent_reason"] = ""
            s["narration_source"] = "vantage-note"
            s["caption_source"] = "vantage-note"
        elif s["photo_id"] in had_note:
            rec = (records or {}).get(s["photo_id"]) or {}
            stored = ((rec.get("observed") or {}).get("caption")
                      or s["photo_id"])[:280]
            s["narration"] = stored
            s["caption"] = stored
            s["silent"] = False
            s["silent_reason"] = ""
            s["narration_source"] = "stored-caption"
            s["caption_source"] = "stored-caption"
    seen = set()
    for s in scenes:
        s["found_text"] = None
        key = (metas.get(s["photo_id"]) or {}).get("place_key") or None
        if key in seen:
            continue
        seen.add(key)
        rec = (records or {}).get(s["photo_id"])
        status = ((rec or {}).get("inferred") or {}).get("place") or {}
        s["found_text"] = found_text_for(rec, status.get("status"))
    return scenes


def evidence_for(brief):
    """Short fact strings backing one scene (pure): place, viewpoint,
    signs, things, people, taken-from. Records only, no model."""
    b = brief or {}
    ev = []
    place = (b.get("place") or "unknown place").strip() or "unknown place"
    st = b.get("place_status")
    ev.append(f"place: {place}" + (f" ({st})" if st else ""))
    if b.get("viewpoint"):
        ev.append(f"viewpoint: {b['viewpoint']}")
    for s in (b.get("signs") or [])[:2]:
        ev.append(f"sign: {s}")
    things = ", ".join((b.get("things") or [])[:3])
    if things:
        ev.append(f"shows: {things}")
    ev.append(f"people: {b.get('people', 0)}")
    if b.get("taken_from"):
        ev.append(f"taken from: {b['taken_from']}")
    return ev


def spotlight_for(photo_id, outlines_dir=None, enabled=True):
    """{x, y, r} spotlight from the saved outline, or None.

    Pure file read of data/outlines/<photo_id>.json (the first
    match's box_norm); missing, disabled or malformed files are
    ignored silently. Never calls any outline service.
    """
    if not enabled or not photo_id:
        return None
    base = Path(outlines_dir) if outlines_dir else ROOT / "data" / "outlines"
    try:
        data = json.loads((base / f"{photo_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    matches = data.get("matches") if isinstance(data, dict) else None
    if not matches:
        return None
    bn = (matches[0] or {}).get("box_norm") or {}
    try:
        x1, y1, x2, y2 = (float(bn[k]) for k in ("x1", "y1", "x2", "y2"))
    except (TypeError, ValueError):
        return None
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        return None
    size = max(x2 - x1, y2 - y1)
    return {"x": round((x1 + x2) / 2, 4), "y": round((y1 + y2) / 2, 4),
            "r": round(min(0.6, max(0.25, 0.7 * size)), 4)}


def attach_spotlights(scenes, outlines_dir=None, enabled=True):
    """Attach spotlight dicts where outline files exist (in place).

    Returns the count attached. Silent when none apply.
    """
    n = 0
    for s in scenes or []:
        sp = spotlight_for(s.get("photo_id"), outlines_dir, enabled)
        if sp:
            s["spotlight"] = sp
            n += 1
    return n


def build_film(beatsheet, rows_by_id, focals, target, bursts=None,
               trace=None, session_id=None, voice=None, profile=None,
               outlines_enabled=None, image_path=None, brief=None,
               style="postcard", notes=None):
    """Full pipeline: scenes, cards, pacing, script, critic, rewrite,
    judge, editor, re-pace, duration fit.

    rows_by_id maps photo_id -> row {place_key, viewpoint,
    collection, record}. Returns the film dict (title, cover,
    beats, spine, scenes, total_seconds, verification). voice/profile
    override the stored profile for narration. outlines_enabled
    defaults to FEATURE_OUTLINES. image_path is a contact sheet
    the caption writer studies with the records (None writes from
    the records only). brief is the owner's day brief (provided
    facts the focus pass may choose). style picks the writer's
    voice (unknown falls back to postcard, traced). notes maps
    photo ids to owner notes: provided facts attached to their
    scenes, forced through the rewrite and honoured by the
    editor. Trace is appended, never replaced. Budget errors
    propagate.
    """
    try:
        style = normalize_style(style)
    except ValueError:
        if trace is not None:
            trace.append({"step": "styled",
                          "detail": f"Unknown style {style!r}; using postcard."})
        style = "postcard"
    if outlines_enabled is None:
        outlines_enabled = os.getenv("FEATURE_OUTLINES", "true").strip().lower() == "true"
    briefs, metas, records = {}, {}, {}
    for pid, row in (rows_by_id or {}).items():
        row = row or {}
        rec = row.get("record") or {}
        briefs[pid] = summarize_record(pid, row.get("viewpoint"), rec)
        taken = (rec.get("inferred") or {}).get("taken_from") or {}
        metas[pid] = {"place_key": row.get("place_key"),
                      "viewpoint": row.get("viewpoint"),
                      "collection": row.get("collection"),
                      "taken_from_key": taken.get("key")}
        records[pid] = rec
    scenes = assemble_scenes(beatsheet, metas, records)
    scenes = merge_bursts(scenes, bursts)
    apply_pacing(scenes, target, trace)
    select_details(scenes, beatsheet.get("beats"), briefs,
                   beatsheet.get("spine"), brief=brief, trace=trace,
                   session_id=session_id)
    wtitle, openings = write_script(
        scenes, briefs, beatsheet.get("beats"), beatsheet.get("spine"),
        brief=brief, style=style, trace=trace, session_id=session_id,
        voice=voice, profile=profile, image_path=image_path)
    notes = {p: n for p, n in (notes or {}).items()
             if isinstance(n, str) and n.strip()
             and p in {s["photo_id"] for s in scenes}}
    for s in scenes:
        if s["photo_id"] in notes:
            s["owner_note"] = notes[s["photo_id"]]
    flagged = critique_script(scenes, briefs, style, trace, session_id)
    if notes:
        fixed = {s["photo_id"] for s in scenes} - \
            {s["photo_id"] for s in _speaking(scenes)}
        used = sorted(set(notes) - fixed)
        for p in used:
            flagged.setdefault(p, {"flags": [], "note": ""})
            flagged[p]["flags"].append("owner note")
        if trace is not None:
            detail = f"Using owner notes on {len(used)} scene(s)."
            if set(notes) & fixed:
                detail += " Notes on fixed lines were skipped."
            trace.append({"step": "noted", "detail": detail})
    if flagged:
        rewrite_lines(scenes, briefs, flagged, style, voice, profile,
                      trace, session_id, notes=notes)
    judge_opening(scenes, briefs, openings, beatsheet.get("spine"), style,
                  voice, profile, trace, session_id)
    title, beats, kept, verification = edit_captions(
        wtitle or beatsheet.get("title"), beatsheet.get("beats"), scenes,
        briefs, trace, session_id, voice, profile, notes=notes)
    if len(kept) != len(scenes):
        _refit_scenes(kept, metas, records)
        apply_pacing(kept, target, trace)
        if trace is not None:
            trace.append({"step": "checked",
                          "detail": f"Re-fit {len(kept)} scenes after drops."})
    fit_durations(kept, briefs, target, style, voice, profile,
                  trace, session_id)
    for s in kept:
        f = (focals or {}).get(s["photo_id"]) or {}
        base_why = s.get("why") or ""
        s["why"] = f"{base_why} (mood: {f.get('mood', 'unknown')})".strip()
        s["focal"] = f or None
        s["duration"] = s["seconds"]
        s["evidence"] = evidence_for(briefs.get(s["photo_id"]))
    cover = beatsheet.get("cover")
    if cover not in [s["photo_id"] for s in kept]:
        cover = kept[0]["photo_id"] if kept else None
        if trace is not None:
            trace.append({"step": "checked",
                          "detail": "Cover scene was dropped; using the first scene."})
    n_spot = attach_spotlights(kept, enabled=outlines_enabled)
    if n_spot and trace is not None:
        trace.append({"step": "staged",
                      "detail": f"Spotlight on {n_spot} scene(s) with outlines."})
    return {"version": 2, "title": title, "cover": cover, "beats": beats,
            "spine": beatsheet.get("spine"), "openings": openings,
            "scenes": kept,
            "total_seconds": round(sum(s["seconds"] for s in kept), 2),
            "verification": verification}
