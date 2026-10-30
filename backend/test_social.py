"""Focused checks for social-only replies (backend/chat.py).

Covers social_reply only: pure logic, no model or database.
Run from the project root:  python backend/test_social.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chat import SOCIAL_REPLY, social_reply  # noqa: E402  (needs the sys.path line above)

WANT = {v: k for k, v in SOCIAL_REPLY.items()}

CASES = [
    # (message, want_intent_or_None)
    ("wow thank you", "thanks"),
    ("Thanks!", "thanks"),
    ("thank you so much", "thanks"),
    ("many thanks reel", "thanks"),
    ("hello", "greeting"),
    ("hi there", "greeting"),
    ("hello reel", "greeting"),
    ("good morning", "greeting"),
    ("bye", "bye"),
    ("goodbye!", "bye"),
    ("good night", "bye"),
    ("ok", "ack"),
    ("okay cool", "ack"),
    ("wow", "ack"),
    ("nice", "ack"),
    ("hahaha", None),  # not the exact word "haha"
    ("thanks, now from above", None),
    ("thanks but no people", None),
    ("not this one", None),
    ("no people", None),
    ("no", None),
    ("my photos", None),
    ("a nairobi street", None),
    ("open 1", None),  # handled by its own shortcut, not social
    ("good night photos", None),
    ("", None),
]

fails = 0
for message, want in CASES:
    got = social_reply(message)
    got_intent = WANT.get(got) if got is not None else None
    if got_intent != want:
        fails += 1
        print(f"FAIL {message!r}: got {got_intent}, want {want}")
print(f"test_social.py: {len(CASES) - fails}/{len(CASES)} checks passed")
sys.exit(1 if fails else 0)
