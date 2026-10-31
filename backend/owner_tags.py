"""Owner presence tags (backend/owner_tags.py).

Pure record helpers for the "provided" layer: `provided.owner` says
whether the OWNER is in one of their own photos. Tags are set by the
owner only (tapping "I'm in this" / "Not me") — never by a model, never
from a face. `present: null` means not reviewed yet.

Shape: {present: true | false | null,
        position: "left" | "centre" | "right" | null,
        tagged_at: iso timestamp}
"""

import json
from datetime import datetime, timezone

POSITIONS = ("left", "centre", "right")


def get_owner(record):
    """Normalized owner tag: missing or malformed reads as not reviewed."""
    own = ((record or {}).get("provided") or {}).get("owner") or {}
    present = own.get("present")
    if present is not True and present is not False:
        present = None
    position = own.get("position")
    if position not in POSITIONS:
        position = None
    return {"present": present, "position": position}


def owner_present_of(record):
    """True / False / None for response shaping."""
    return get_owner(record)["present"]


def set_owner(record, present, position=None):
    """Return a copy of the record with the owner tag set (pure).

    `present` must be a real bool. `position` is kept only when
    present is True, else forced to null. Raises ValueError.
    """
    if present is not True and present is not False:
        raise ValueError("present must be true or false")
    if position is not None and position not in POSITIONS:
        raise ValueError("position must be one of: left, centre, right")
    rec = json.loads(json.dumps(record or {}))
    rec.setdefault("provided", {})["owner"] = {
        "present": present,
        "position": position if present is True else None,
        "tagged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return rec


def clear_owner(record):
    """Return a copy of the record with the owner tag removed (pure)."""
    rec = json.loads(json.dumps(record or {}))
    prov = rec.get("provided")
    if isinstance(prov, dict):
        prov.pop("owner", None)
    return rec
