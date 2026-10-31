"""Owner profile store (backend/owner_profile.py).

The owner's display name for narration, WITHOUT any face recognition.
The name comes only from what the owner types into PUT /api/profile;
nothing here ever works out who someone is from their face. The file
is local and git-ignored; the public demo has no profile, so no name
is ever shown there.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

PROFILE_PATH = Path(__file__).resolve().parent.parent / "data" / "profile.json"
REFER_CHOICES = ("name", "you", "i")
MAX_NAME_LEN = 40

_extra_name_chars = frozenset(" '-’")


def _now():
    return datetime.now(timezone.utc).isoformat()


def validate_name(name):
    """Return the stripped name, or raise ValueError with the reason."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("name must be 1 to 40 characters")
    if len(cleaned) > MAX_NAME_LEN:
        raise ValueError("name must be 1 to 40 characters")
    for ch in cleaned:
        if not (ch.isalpha() or ch in _extra_name_chars):
            raise ValueError("name may only use letters, spaces, hyphens and apostrophes")
    return cleaned


def validate_refer_as(refer_as):
    if refer_as not in REFER_CHOICES:
        raise ValueError("refer_as must be one of: name, you, i")
    return refer_as


def load_profile():
    """Return the stored profile dict, or None when there is none."""
    try:
        raw = PROFILE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or not data.get("name"):
        return None
    return data


def save_profile(name, refer_as=None):
    """Create or update the profile. refer_as None keeps the old choice."""
    cleaned = validate_name(name)
    old = load_profile() or {}
    choice = old.get("refer_as", "name") if refer_as is None else validate_refer_as(refer_as)
    now = _now()
    data = {"name": cleaned,
            "refer_as": choice,
            "created_at": old.get("created_at", now),
            "updated_at": now}
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    return data


def delete_profile():
    """Remove the profile file. Returns True when one existed."""
    try:
        PROFILE_PATH.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True
