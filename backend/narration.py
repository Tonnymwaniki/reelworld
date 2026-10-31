"""Owner-name narration rules (backend/narration.py).

Pure helpers shared by every prompt that writes text about photos
(stories, captions, answers, compare, explain). Two layers:

1. Prompt rules (rules_block): tell the model who the owner is, how
   to refer to them (refer_as), and the per-photo owner facts.
2. Code check (check_text / repair_text): mechanical safety net.
   The owner's NAME is checked strictly everywhere; you/I/me/my
   only in caption scope (descriptive text where the assistant
   never addresses the reader). Position words and other people's
   names are prompt+editor enforced — code cannot tell "the
   flagpole on the left" from "you on the left".
"""

import re

VOICES = ("name", "you", "i")

_YOU_WORDS = re.compile(r"\b(you|your|yours|yourself|I|me|my|mine)\b",
                         re.IGNORECASE)


def resolve_voice(story_voice, profile):
    """Story override, else the profile's choice, else "name"."""
    if story_voice in VOICES:
        return story_voice
    if isinstance(profile, dict) and profile.get("refer_as") in VOICES:
        return profile["refer_as"]
    return "name"


def owner_facts(records):
    """{photo_id: {present, position, people}} from {photo_id: record}."""
    out = {}
    for pid, rec in (records or {}).items():
        rec = rec or {}
        own = (rec.get("provided") or {}).get("owner") or {}
        present = own.get("present")
        out[pid] = {
            "present": present if present is True else (False if present is False else None),
            "position": own.get("position") if own.get("position") in (
                "left", "centre", "right") else None,
            "people": ((rec.get("observed") or {}).get("people") or {}).get("count", 0) or 0,
        }
    return out


def rules_block(profile, facts, voice):
    """Prompt-ready owner rules. facts: owner_facts() output."""
    name = (profile or {}).get("name") or ""
    voice = voice if voice in VOICES else "name"
    how = {"name": f"by name ({name})" if name else "by name",
           "you": 'as "you"', "i": 'as "I"'}[voice]
    lines = []
    if name:
        lines.append(f"The photo owner calls themselves {name}; refer to the "
                     f"owner {how} and never any other way.")
    else:
        lines.append("No owner name is known: never use any name for any person.")
    lines.append("Owner facts per photo (present = the owner tagged "
                 "themselves in it; use left/centre/right only when given):")
    for pid, f in (facts or {}).items():
        if f["present"] is True:
            pos = f" ({f['position']})" if f["position"] else ""
            lines.append(f"- {pid}: owner present{pos}, {f['people']} people")
        elif f["present"] is False:
            lines.append(f"- {pid}: owner NOT present, {f['people']} people")
        else:
            lines.append(f"- {pid}: owner presence unknown, {f['people']} people")
    lines.extend([
        "Rules: where the owner is the only person, refer to them per the voice above. "
        "Where several people include the owner, say the owner is among them. "
        "Where the owner is absent or unknown, call people \"a person\", \"someone\" or "
        "\"a few people\" and never use the owner's name. Never name any other person, "
        "never guess a name or relationship, and never describe a person's looks "
        "beyond what the stored record states."])
    return "\n".join(lines)


def _name_spans(text, name):
    if not name:
        return []
    return [m for m in re.finditer(r"\b" + re.escape(name) + r"\b", text or "",
                                   re.IGNORECASE)]


def check_text(text, name, allowed, scope="chat"):
    """Violation spans in text. allowed: owner.present is True for the
    text's photo(s). scope "caption" also flags you/I/me/my."""
    bad = []
    for m in _name_spans(text, name):
        if not allowed:
            bad.append({"type": "owner_name", "start": m.start(), "end": m.end(),
                        "text": m.group(0)})
    if scope == "caption" and not allowed:
        for m in _YOU_WORDS.finditer(text or ""):
            bad.append({"type": "owner_voice", "start": m.start(), "end": m.end(),
                        "text": m.group(0)})
    return bad


def voice_spans(text, name, voice):
    """Name spans that violate a you/I voice (empty otherwise).

    Under voice "you"/"i" the owner's name must never appear; the
    model was told to use that voice and no other. Voice "name"
    (or no name) has nothing to violate.
    """
    if voice not in ("you", "i") or not name:
        return []
    return [{"type": "voice_name", "start": m.start(), "end": m.end(),
             "text": m.group(0)} for m in _name_spans(text, name)]


def drop_sentences(text, spans):
    """Remove every sentence containing a violation span (pure)."""
    if not spans:
        return text or ""
    sents = [s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s]
    kept = []
    pos = 0
    for s in sents:
        start = (text or "").find(s, pos)
        end = start + len(s)
        pos = end
        if not any(v["start"] < end and v["end"] > start for v in spans):
            kept.append(s)
    return " ".join(kept).strip()


def public_text(text, name):
    """Public Showcase version: the owner's name becomes "the
    photographer" (whole words, any case). No name, no change."""
    if not name or not text:
        return text or ""
    return re.sub(r"\b" + re.escape(name) + r"\b", "the photographer",
                  text, flags=re.IGNORECASE)


def repair_text(text, name, allowed, scope="chat"):
    """(repaired, violations): drop violating sentences. Empty means the
    caller must fall back (stored caption) or drop the scene."""
    bad = check_text(text, name, allowed, scope)
    if not bad:
        return text, []
    return drop_sentences(text, bad), bad
