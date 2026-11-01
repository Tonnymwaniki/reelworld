"""Focused checks for search filtering + verify pass.

lex_has word forms, avoid exclusion, positive matching, the
verify prompt/order helpers, and Engine.verify with a stubbed
model call. No model or database.
Run from the project root:  python backend/test_search_verify.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chat as chat_mod  # noqa: E402  (needs the sys.path line above)
from retrieval import lex_has  # noqa: E402

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


check(lex_has("a tall building downtown", "buildings"),
      "plural term matches singular")
check(lex_has("scattered houses and fields", "house"),
      "singular term matches plural")
check(lex_has("a mountain ridge", "mountain"), "exact term matches")
check(not lex_has("a mountain ridge", "building"), "absent term misses")
check(not lex_has("a clasp knife", "glass"), "-ss never stems")
check(not lex_has("anything", ""), "empty term misses")
check(not lex_has("", "mountain"), "empty lex misses")

rows = [{"photo_id": "mtn", "lex": "a misty mountain peak, no buildings"},
        {"photo_id": "hut", "lex": "houses in front of hazy mountains"},
        {"photo_id": "kicc", "lex": "brutalist concrete building tower"}]
kept, dropped = chat_mod.split_avoid(rows, ["buildings", "structures"])
check([r["photo_id"] for r in kept] == ["hut"] and dropped == 2,
      "avoid excludes across word forms")
kept, dropped = chat_mod.split_avoid(rows, [])
check(len(kept) == 3 and dropped == 0, "no avoid terms keeps all")

pos = chat_mod.only_matching(rows, ["mountain"], [])
check([r["photo_id"] for r in pos] == ["mtn", "hut"],
      "zero-term guesses dropped")
pos = chat_mod.only_matching(rows, [], ["tower"])
check([r["photo_id"] for r in pos] == ["kicc"],
      "must terms match stem-tolerantly")

prompt = chat_mod.build_verify_prompt(
    "just a mountain", "mountain", "buildings",
    ["- mtn: a misty mountain peak"])
check("just a mountain" in prompt and "Must NOT show: buildings" in prompt
      and '"keep"' in prompt and "- mtn:" in prompt,
      "verify prompt carries the request")

ordered = chat_mod.apply_verify_order(rows, ["hut", "mtn", "nope", "hut"])
check([r["photo_id"] for r in ordered] == ["hut", "mtn"],
      "verify order keeps listed best-first")
check(chat_mod.apply_verify_order(rows, []) == [], "empty ids keep nothing")

eng = chat_mod.Engine.__new__(chat_mod.Engine)
eng.ask = lambda *a, **k: json.dumps(
    {"keep": [{"photo_id": "mtn", "reason": "pure mountain"}]})
kept_rows, trace = eng.verify(
    rows, {"query": "just a mountain", "must_include": ["mountain"],
           "avoid_terms": ["buildings"]})
check([r["photo_id"] for r in kept_rows] == ["mtn"]
      and trace and trace[0]["step"] == "checked"
      and "kept 1" in trace[0]["detail"], "verify keeps the model's pick")


def boom(*a, **k):
    raise RuntimeError("model down")


eng.ask = boom
kept_rows, trace = eng.verify(
    rows, {"query": "q", "must_include": ["mountain"], "avoid_terms": []})
check(kept_rows == rows and "code order" in trace[0]["detail"],
      "verify failure keeps code order")
kept_rows, trace = eng.verify(
    rows, {"query": "q", "must_include": [], "avoid_terms": []})
check(kept_rows == rows and trace == [],
      "plain queries skip the model call")

api_src = (Path(__file__).resolve().parent / "api.py").read_text(encoding="utf-8")
start = api_src.index("def api_search(")
end = api_src.index("\n@app.post", start)
check("verify=False" in api_src[start:end],
      "/api/search keeps its no-model promise")

print(f"test_search_verify.py: {total - fails}/{total} checks passed")
