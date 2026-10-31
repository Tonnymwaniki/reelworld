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
