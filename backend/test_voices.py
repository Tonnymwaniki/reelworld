"""Checks for backend/voices.py.
Run from the project root:  python backend/test_voices.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import voices as voices_mod  # noqa: E402

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


check("first-hand" in voices_mod.voice_block("postcard"), "postcard voice")
check("evidence-first" in voices_mod.voice_block("field-notes"),
      "field-notes voice")
check("measured" in voices_mod.voice_block("documentary"), "documentary voice")
check("present tense" in voices_mod.voice_block("cinematic"), "cinematic voice")
block = voices_mod.voice_block("postcard")
check("hustle and bustle" in block and "tapestry" in block, "banned joined")
check("No emojis" in block and "Here we see" in block, "universal rules")
check(voices_mod.normalize_voice_style("field_notes") == "field-notes",
      "style alias")
try:
    voices_mod.voice_block("noir")
    check(False, "bad style raises")
except ValueError:
    check(True, "bad style raises")

print(f"test_voices.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
