"""Style voices for the script writers (pure prompt text).

Four voices; every voice shares the universal rules (variety, no
lists, no filler openers, banned phrases, no emojis, restrained
exclamation). The film caption writer uses voice_block now; step
5's whole-script writer reuses it.
"""
VOICE_STYLES = ("postcard", "field-notes", "documentary", "cinematic")

BANNED = ("bustling", "vibrant", "tapestry", "nestled", "hustle and bustle",
          "testament to", "a sea of", "melting pot", "in the heart of")

_STYLE_LINES = {
    "postcard": "Voice postcard: warm, short, first-hand — write like a "
                "postcard from the day. An exclamation mark is allowed here "
                "only, and only when it fits.",
    "field-notes": "Voice field notes: precise, evidence-first, understated "
                   "— name what proves it, no flourish, no exclamation marks.",
    "documentary": "Voice documentary: calm, factual, measured — an even "
                   "documentary voice, no exclamation marks.",
    "cinematic": "Voice cinematic: sparse, dramatic, present tense — short "
                 "lines that leave silence between ideas, no exclamation marks.",
}


def normalize_voice_style(style):
    """field_notes -> field-notes; raises ValueError when unknown."""
    s = (style or "").strip().lower().replace("_", "-")
    if s not in VOICE_STYLES:
        raise ValueError(f"style must be one of {', '.join(VOICE_STYLES)}.")
    return s


def voice_block(style):
    """Prompt-ready voice rules (pure). Raises ValueError when unknown."""
    s = normalize_voice_style(style)
    return "\n".join([
        _STYLE_LINES[s],
        "Vary sentence length across scenes; never open two scenes the same way.",
        "No lists of objects. No filler openers: never start a line with "
        "\"This is\", \"Here we see\" or \"There is\".",
        "Banned phrases (unless the exact word is quoted from a sign in the "
        "records): " + "; ".join(BANNED) + ".",
        "No emojis. No exclamation marks except in postcard, sparingly."])
