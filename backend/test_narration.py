"""Checks for backend/narration.py.
Run from the project root:  python backend/test_narration.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import narration as narr  # noqa: E402

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


check(narr.resolve_voice("you", {"refer_as": "i"}) == "you", "story voice wins")
check(narr.resolve_voice(None, {"refer_as": "i"}) == "i", "profile default")
check(narr.resolve_voice("bogus", None) == "name", "fallback name")

facts = narr.owner_facts({
    "p1": {"provided": {"owner": {"present": True, "position": "left"}},
           "observed": {"people": {"count": 3}}},
    "p2": {"provided": {"owner": {"present": False}},
           "observed": {"people": {"count": 1}}},
    "p3": {"observed": {}},
})
check(facts["p1"] == {"present": True, "position": "left", "people": 3},
      "facts present")
check(facts["p2"] == {"present": False, "position": None, "people": 1},
      "facts absent")
check(facts["p3"] == {"present": None, "position": None, "people": 0},
      "facts unknown")

block = narr.rules_block({"name": "Tonny", "refer_as": "you"},
                          {"p1": facts["p1"]}, "you")
check("Tonny" in block and 'as "you"' in block, "rules carry name + voice")
check("p1: owner present (left), 3 people" in block, "rules carry facts")
check("never name any other person" in block.lower(), "rules forbid others")
noname = narr.rules_block(None, {}, "name")
check("No owner name is known" in noname, "rules without profile")

check(narr.check_text("Tonny is here.", "Tonny", True) == [],
      "name allowed when present")
bad = narr.check_text("Tonny is here.", "Tonny", False)
check(len(bad) == 1 and bad[0]["type"] == "owner_name", "name flagged")
check(narr.check_text("tonny waved.", "Tonny", False) != [], "case-insensitive")
check(narr.check_text("You are here.", "Tonny", False) == [],
      "you ignored in chat scope")
check(narr.check_text("You are here.", "Tonny", False, "caption") != [],
      "you flagged in captions")
check(narr.check_text("A person walks.", "Tonny", False, "caption") == [],
      "plain caption clean")

fixed, n = narr.repair_text("Tonny waves. Birds fly.", "Tonny", False)
check(fixed == "Birds fly." and len(n) == 1, "repair drops sentence")
fixed2, n2 = narr.repair_text("Tonny waves.", "Tonny", False)
check(fixed2 == "" and len(n2) == 1, "repair can empty")
fixed3, n3 = narr.repair_text("Tonny waved to Sarah.", "Tonny", False, "caption")
check(fixed3 == "" and "Sarah" not in fixed3 and len(n3) == 1,
      "hostile caption dropped whole")
check(narr.public_text("Tonny waves.", "Tonny") == "the photographer waves.",
      "public swaps name")
check(narr.public_text("tonny's view.", "Tonny") == "the photographer's view.",
      "public possessive")
check(narr.public_text("Tonny waves.", "") == "Tonny waves.", "public no name")
check(narr.public_text("A person walks.", "Tonny") == "A person walks.",
      "public plain kept")

print(f"test_narration.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
