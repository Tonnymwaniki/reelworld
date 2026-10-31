"""Scene assembly for directed stories.

Transitions, cards and pacing are pure code; captions and the editor
pass use the reasoning model via llm.ask, always checked against the
stored records. build_film runs the whole pipeline.
"""
import json
import os
import re
from pathlib import Path

import llm
import narration as narration_mod
import owner_profile as owner_profile_mod
from chat import extract_json
from director import CAMERAS, PACINGS, ROLES, summarize_record

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


def write_captions(scenes, briefs, trace=None, session_id=None,
                   voice=None, profile=None, image_path=None):
    """One caption per scene from photos + records (one model call).

    briefs maps photo_id -> summarize_record() dict. The model
    studies the attached photos for feel and detail, but the
    records are the fact authority. Vantage scenes keep their note
    as the whole caption (set in code, no model). Invalid output
    retries once, then falls back to the stored caption. Model
    captions are code-checked for owner references; repaired ones
    fall back to the stored caption when emptied.
    voice/profile override the stored profile (tests). Sets caption
    + caption_source. Budget errors propagate.
    """
    need = [s for s in scenes if not s.get("caption_note")]
    for s in scenes:
        if s.get("caption_note"):
            s["caption"] = s["caption_note"]
            s["caption_source"] = "vantage-note"
    if not need:
        return scenes
    voice, profile, facts = _narration_for(
        briefs, [s["photo_id"] for s in need], voice, profile)
    name = (profile or {}).get("name") or ""
    lines = ["Write one caption (ONE sentence, under 140 characters) per photo,",
             "using ONLY these stored facts. Never add outside facts, never invent.",
             "Study the attached photos (labelled top to bottom) with these facts:",
             "let the photos guide the feel and the choice of detail, but every",
             "claim must be backed by the stored facts.",
             "Sound like a vlog voiceover: varied, energetic, moving through an outing.",
             "Vary the set: name a shared place or sign ONCE across all captions;",
             "other captions say here / this view / the plaza, and lead with what is",
             "new in that photo instead of re-listing shared facts.",
             "Never start two captions with the same word.",
             narration_mod.rules_block(profile, facts, voice)]
    for s in need:
        lines.append(f"- {s['photo_id']}: {_brief_text(briefs.get(s['photo_id']))}")
    base = ("\n".join(lines)
            + '\nOutput ONE JSON object keyed by photo id: {"<id>": "caption"}.')
    pids = [s["photo_id"] for s in need]
    last_problems = []
    for attempt in (1, 2):
        prompt = base if attempt == 1 else (
            base + "\nRejected: " + "; ".join(last_problems) + ". Fix every one.")
        try:
            data = extract_json(llm.ask(
                prompt, temperature=0.1, purpose="captions",
                session_id=session_id, image_path=image_path)["text"])
        except llm.LLMBudgetSpent:
            raise
        except (RuntimeError, ValueError) as e:
            last_problems = [f"unusable reply: {e}"[:120]]
            continue
        if not isinstance(data, dict):
            last_problems = ["reply is not a JSON object"]
            continue
        missing = [p for p in pids if not isinstance(data.get(p), str)
                   or not data[p].strip()]
        last_problems = [f"missing caption for {p}" for p in missing]
        if voice in ("you", "i"):
            want = '"you"' if voice == "you" else '"I"'
            last_problems += [
                f"wrong voice in {p}: use {want}, not the name"
                for p in pids
                if isinstance(data.get(p), str) and data[p].strip()
                and (briefs.get(p) or {}).get("owner_present") is True
                and narration_mod.voice_spans(data[p], name, voice)]
        if not last_problems:
            repaired = 0
            for s in need:
                cap = data[s["photo_id"]].strip()[:280]
                fixed_cap, bad = _scene_owner_ok(
                    cap, name, briefs.get(s["photo_id"]))
                if bad:
                    repaired += 1
                    cap = fixed_cap or (((briefs.get(s["photo_id"]) or {}).get("caption")
                                          or s["photo_id"])[:280])
                s["caption"] = cap
                s["caption_source"] = "records-model"
            if trace is not None:
                detail = (f"Wrote {len(need)} captions from the records."
                          if image_path is None else
                          f"Wrote {len(need)} captions studying the photos "
                          "with their records.")
                if repaired:
                    detail += f" Removed unsupported owner references in {repaired}."
                trace.append({"step": "wrote", "detail": detail})
            return scenes
    for s in need:
        s["caption"] = ((briefs.get(s["photo_id"]) or {}).get("caption")
                        or s["photo_id"])[:280]
        s["caption_source"] = "stored-caption"
    if trace is not None:
        trace.append({"step": "wrote",
                      "detail": "Caption writing failed twice; using stored captions."})
    return scenes


def _sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s]


def _check_verdict(v):
    return isinstance(v, dict) and v.get("verdict") in ("supported", "unsupported") \
        and (v.get("rewrite") is None or isinstance(v.get("rewrite"), str))


def edit_captions(title, beats, scenes, briefs, trace=None, session_id=None,
                  voice=None, profile=None):
    """Verify every caption sentence against the records (one model call).

    Vantage-note captions are code, already true, and skipped. Returns
    (title, beats, scenes, verification). Unsupported claims are
    rewritten once or removed; scenes left empty are dropped; the
    title and beat intents are rewritten when fixable. The owner's
    name (or you/I) may stay only in scenes whose photos have
    owner.present true — the model verdicts enforce this, and a code
    check afterwards drops what slips through. Any failure of the
    pass itself marks the film not verified. Budget errors propagate.
    """
    beats = [dict(b) for b in (beats or [])]
    checkable = [s for s in scenes if not s.get("caption_note")]
    sents = {s["photo_id"]: _sentences(s.get("caption")) for s in checkable}
    voice, profile, facts = _narration_for(
        briefs, [s["photo_id"] for s in checkable], voice, profile)
    name = (profile or {}).get("name") or ""
    lines = ["Check each sentence against ONLY the stored facts for its photo.",
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
        lines.append(f"Photo {s['photo_id']} facts: "
                     f"{_brief_text(briefs.get(s['photo_id']))}")
        for i, sent in enumerate(sents[s["photo_id"]]):
            lines.append(f"Photo {s['photo_id']} sentence {i}: {sent}")
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
            out = []
            for sent, claim in zip(sents[s["photo_id"]],
                                   data["scenes"][s["photo_id"]]["claims"]):
                if claim["verdict"] == "supported":
                    out.append(sent)
                elif claim["rewrite"]:
                    out.append(claim["rewrite"].strip())
                    fixed += 1
                else:
                    fixed += 1
            if not out:
                verification["dropped"].append(s["photo_id"])
                continue
            cap = " ".join(out)[:280]
            cap, bad = _scene_owner_ok(cap, name, briefs.get(s["photo_id"]))
            if bad:
                fixed += 1
                if not cap:
                    verification["dropped"].append(s["photo_id"])
                    continue
            s["caption"] = cap
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
    """Re-derive transitions, notes, captions and cards after drops (pure).

    Neighbourhoods changed, so transitions, vantage notes and
    first-per-place cards are recomputed from scratch; model
    captions stay, vantage captions follow their notes.
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
            s["caption"] = s["caption_note"]
            s["caption_source"] = "vantage-note"
        elif s["photo_id"] in had_note:
            rec = (records or {}).get(s["photo_id"]) or {}
            s["caption"] = ((rec.get("observed") or {}).get("caption")
                            or s["photo_id"])[:280]
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
               outlines_enabled=None, image_path=None):
    """Full pipeline: scenes, cards, pacing, captions, editor, re-pace.

    rows_by_id maps photo_id -> row {place_key, viewpoint,
    collection, record}. Returns the film dict (title, cover,
    beats, scenes, total_seconds, verification). voice/profile
    override the stored profile for narration. outlines_enabled
    defaults to FEATURE_OUTLINES. image_path is a contact sheet
    the caption writer studies with the records (None writes from
    the records only). Trace is appended, never replaced. Budget
    errors propagate.
    """
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
    write_captions(scenes, briefs, trace, session_id, voice, profile,
                   image_path=image_path)
    title, beats, kept, verification = edit_captions(
        beatsheet.get("title"), beatsheet.get("beats"), scenes,
        briefs, trace, session_id, voice, profile)
    if len(kept) != len(scenes):
        _refit_scenes(kept, metas, records)
        apply_pacing(kept, target, trace)
        if trace is not None:
            trace.append({"step": "checked",
                          "detail": f"Re-fit {len(kept)} scenes after drops."})
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
            "scenes": kept,
            "total_seconds": round(sum(s["seconds"] for s in kept), 2),
            "verification": verification}
