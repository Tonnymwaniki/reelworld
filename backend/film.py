"""Scene assembly for directed stories (pure code, no model).

Beats flatten to scenes in order; each scene gains its transition_in
(chosen from the neighbouring scenes' records), and later steps add
found-text cards, durations, captions and verification.
"""
from director import CAMERAS, PACINGS, ROLES

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
