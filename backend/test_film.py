"""Focused checks for scene assembly (backend/film.py).

Transitions from metadata, precedence, vantage notes: pure code,
no model. Run from the project root:  python backend/test_film.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import film as film_mod  # noqa: E402  (needs the sys.path line above)
import llm  # noqa: E402

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


def meta(place=None, vp="ground_level", coll="world", taken=None):
    return {"place_key": place, "viewpoint": vp, "collection": coll,
            "taken_from_key": taken}


T = film_mod.transition_for
check(T(meta("k"), meta("k")) == "dissolve", "same place dissolves")
check(T(meta("k", vp="ground_level"), meta("k", vp="aerial")) == "rise",
      "rise beats dissolve")
check(T(meta("k", vp="aerial"), meta("k", vp="ground_level")) == "descend",
      "descend beats dissolve")
check(T(meta("a"), meta("b")) == "dip", "place change dips")
check(T(meta("k", coll="personal"), meta("k")) == "iris",
      "personal to world irises")
check(T(meta("a", vp="ground_level", coll="personal"),
        meta("b", vp="aerial")) == "iris", "iris beats rise and dip")
check(T(meta("x", coll="personal"),
        meta("y", coll="personal", taken="x")) == "vantage", "vantage pair")
check(T(meta("x", vp="ground_level", coll="personal"),
        meta("y", vp="aerial", coll="personal", taken="x")) == "vantage",
      "vantage beats rise and dip")
check(T(meta(), meta()) == "cut", "unknown places cut")
check(T(meta("k"), meta()) == "cut", "half-known places cut")
check(T(meta("k", coll="world"), meta("k", coll="personal")) == "dissolve",
      "world to personal is no iris")
check(T(meta("k", vp="interior"), meta("k", vp="aerial")) == "dissolve",
      "interior rise is no rise")

sheet = {"title": "t", "cover": "a",
         "beats": [{"role": "establish", "intent": "go",
                    "photo_ids": ["a", "b"], "pacing": "slow",
                    "camera": "hold", "reason": "why-a"}]}
metas = {"a": meta("x", coll="personal"),
         "b": meta("y", coll="personal", taken="x")}
scenes = film_mod.assemble_scenes(sheet, metas)
check(len(scenes) == 2 and scenes[0]["transition_in"] is None
      and scenes[1]["transition_in"] == "vantage"
      and scenes[0]["caption_note"] == "You were here"
      and scenes[1]["caption_note"] == "and this is what you saw"
      and scenes[0]["role"] == "establish"
      and scenes[0]["why"] == "why-a", "assemble flattens + vantage notes")

F = film_mod.found_text_for


def rec_with(*signs):
    return {"observed": {"visible_text": list(signs)},
            "inferred": {"place": {"status": "confirmed"}}}


check(F(rec_with({"text": "KICC", "legibility": "clear"}), "confirmed")
      == {"text": "KICC", "badge": "Confirmed"}, "clear sign cards")
check(F(rec_with({"text": "  KeEp  ", "legibility": "clear"}), "candidate")
      == {"text": "  KeEp  ", "badge": "Candidate"}, "text kept exactly")
check(F(rec_with({"text": "KICC", "legibility": "partial"}), "confirmed") is None,
      "partial sign skipped")
check(F(rec_with({"text": "ABC", "legibility": "clear"}), "confirmed") is None,
      "short text skipped")
check(F(rec_with({"text": "x" * 61, "legibility": "clear"}), "confirmed") is None,
      "long text skipped")
check(F(rec_with({"text": "KICC", "legibility": "clear"}), None)
      == {"text": "KICC", "badge": None}, "no badge when unknown")
check(F(rec_with({"text": "no", "legibility": "clear"},
                 {"text": "SECOND ONE", "legibility": "clear"}), "confirmed")
      == {"text": "SECOND ONE", "badge": "Confirmed"}, "first qualifying wins")

sheet3 = {"title": "t", "cover": "a",
          "beats": [{"role": "build", "intent": "go", "photo_ids": ["a", "b", "c"],
                     "pacing": "medium", "camera": "hold", "reason": "r"}]}
metas3 = {"a": meta("x"), "b": meta("x"), "c": meta("y")}
recs3 = {p: rec_with({"text": "SIGN HERE", "legibility": "clear"})
         for p in ("a", "b", "c")}
scenes3 = film_mod.assemble_scenes(sheet3, metas3, recs3)
check(scenes3[0]["found_text"] == {"text": "SIGN HERE", "badge": "Confirmed"}
      and scenes3[1]["found_text"] is None
      and scenes3[2]["found_text"] == {"text": "SIGN HERE", "badge": "Confirmed"},
      "first scene of each place only")

def sc(pid, role="build", pacing="medium", card=None):
    return {"photo_id": pid, "role": role, "pacing": pacing,
            "camera": "hold", "transition_in": None, "caption_note": None,
            "found_text": card, "why": ""}


CARD = {"text": "X", "badge": None}
m = film_mod.merge_bursts([sc("a"), sc("b"), sc("c")], [["a", "b"]])
check(len(m) == 2 and m[0]["frames"] == ["a", "b"]
      and m[0]["frame_seconds"] == 0.21 and m[1]["frames"] == ["c"]
      and m[1]["frame_seconds"] is None, "burst merges")
m = film_mod.merge_bursts([sc("a", role="establish"), sc("b", role="build")],
                          [["a", "b"]])
check(len(m) == 2, "different roles stay split")

three = film_mod.apply_pacing([sc("a"), sc("b"), sc("c")], "short")
check([s["seconds"] for s in three] == [6.67, 6.67, 6.67]
      and abs(sum(s["seconds"] for s in three) - 20.0) <= 0.1,
      "scales to target")
four = film_mod.apply_pacing([sc("a", card=CARD), sc("b", pacing="quick"),
                              sc("c"), sc("d")], "short")
check(abs(four[0]["seconds"] / four[1]["seconds"] - 2.1) < 0.01,
      "card bonus in formula")
mixed = film_mod.merge_bursts(
    [sc(p) for p in ("a", "b", "c", "d", "e", "f", "g", "h", "i")],
    [["a", "b", "c", "d"]])
mixed = film_mod.apply_pacing(mixed, "short")
check(mixed[0]["seconds"] == 0.84 and mixed[0]["burst"]
      and abs(sum(s["seconds"] for s in mixed) - 20.0) <= 0.1,
      "bursts keep rate, rest scales")
only_burst = film_mod.apply_pacing(
    film_mod.merge_bursts([sc("a", pacing="quick"), sc("z", pacing="quick")],
                          [["a", "z"]]), "short", trace=(tr := []))
check(only_burst[0]["seconds"] == 0.36 and "Outside" in tr[0]["detail"],
      "all-burst noted")
one = film_mod.apply_pacing([sc("a", pacing="quick")], "short",
                            trace=(tr2 := []))
check(one[0]["seconds"] == 8.0 and "Outside" in tr2[0]["detail"],
      "clamped and noted")
film_mod.apply_pacing([], "short", trace=(tr3 := []))
check("Outside" in tr3[0]["detail"], "empty film noted")

BRIEFS = {"p1": {"caption": "Stored one.", "place": "K", "place_status": "confirmed",
                       "viewpoint": "ground_level", "scene": "street",
                       "things": ["bus"], "signs": [], "taken_from": None,
                       "people": 0},
            "p2": {"caption": "Stored two.", "place": "K", "place_status": None,
                   "viewpoint": "ground_level", "scene": "plaza", "things": [],
                   "signs": [], "taken_from": None, "people": 0}}
SUP = {"verdict": "supported", "rewrite": None}

orig_ask = llm.ask
try:
    llm.ask = lambda *a, **k: {"text": json.dumps({"p1": "Buses park here."})}
    w = film_mod.write_captions([sc("p1"), {**sc("p2"), "caption_note": "You were here"}],
                                BRIEFS, trace=(tw := []))
    check(w[0]["caption"] == "Buses park here." and w[0]["caption_source"] == "records-model"
          and w[1]["caption"] == "You were here" and len(tw) == 1, "captions written")
    replies = [json.dumps({"p9": "wrong id"}), json.dumps({"p1": "Second try."})]
    llm.ask = lambda *a, **k: {"text": replies.pop(0)}
    w = film_mod.write_captions([sc("p1")], BRIEFS)
    check(w[0]["caption"] == "Second try.", "caption retry recovers")
    llm.ask = lambda *a, **k: {"text": "garbage"}
    w = film_mod.write_captions([sc("p1")], BRIEFS, trace=(tw2 := []))
    check(w[0]["caption"] == "Stored one." and w[0]["caption_source"] == "stored-caption"
          and "stored captions" in tw2[0]["detail"], "caption fallback")

    s1 = sc("p1")
    s1["caption"] = "Buses park here. People wait."
    llm.ask = lambda *a, **k: {"text": json.dumps(
        {"title": SUP, "intents": [SUP],
         "scenes": {"p1": {"claims": [SUP, SUP]}}})}
    _t, _b, kept, ver = film_mod.edit_captions("T", [{"intent": "go"}], [s1],
                                               BRIEFS, trace=(te := []))
    check(ver["verified"] and ver["checked"] == 4 and ver["fixed"] == 0
          and "4 claims, 0 fixed" in te[0]["detail"], "clean edit verifies")
    s1["caption"] = "Buses park here. Elephants dance."
    llm.ask = lambda *a, **k: {"text": json.dumps(
        {"title": SUP, "intents": [SUP],
         "scenes": {"p1": {"claims": [SUP, {"verdict": "unsupported",
                                            "rewrite": "People wait."}]}}})}
    _t, _b, kept, ver = film_mod.edit_captions("T", [{"intent": "go"}], [s1],
                                               BRIEFS)
    check(kept[0]["caption"] == "Buses park here. People wait." and ver["fixed"] == 1,
          "rewrite applied")
    llm.ask = lambda *a, **k: {"text": json.dumps(
        {"title": SUP, "intents": [SUP],
         "scenes": {"p1": {"claims": [SUP, {"verdict": "unsupported",
                                            "rewrite": None}]}}})}
    _t, _b, kept, ver = film_mod.edit_captions("T", [{"intent": "go"}], [s1],
                                               BRIEFS)
    check(kept[0]["caption"] == "Buses park here." and ver["fixed"] == 1,
          "claim removed")
    s1["caption"] = "Elephants dance."
    llm.ask = lambda *a, **k: {"text": json.dumps(
        {"title": SUP, "intents": [SUP],
         "scenes": {"p1": {"claims": [{"verdict": "unsupported",
                                       "rewrite": None}]}}})}
    _t, _b, kept, ver = film_mod.edit_captions("T", [{"intent": "go"}], [s1],
                                               BRIEFS)
    check(kept == [] and ver["dropped"] == ["p1"], "empty scene dropped")
    s1["caption"] = "Buses park here."
    llm.ask = lambda *a, **k: {"text": json.dumps(
        {"title": {"verdict": "unsupported", "rewrite": "Better title"},
         "intents": [SUP], "scenes": {"p1": {"claims": [SUP]}}})}
    nt, _b, _k, ver = film_mod.edit_captions("Old", [{"intent": "go"}], [s1],
                                             BRIEFS)
    check(nt == "Better title" and ver["verified"], "title rewritten")
    llm.ask = lambda *a, **k: {"text": json.dumps(
        {"title": {"verdict": "unsupported", "rewrite": None},
         "intents": [SUP], "scenes": {"p1": {"claims": [SUP]}}})}
    _t, _b, _k, ver = film_mod.edit_captions("Old", [{"intent": "go"}], [s1],
                                             BRIEFS)
    check(not ver["verified"] and "not verified" in ver["note"],
          "unfixable title flagged")
    llm.ask = lambda *a, **k: {"text": "garbage"}
    _t, _b, kept, ver = film_mod.edit_captions("T", [{"intent": "go"}], [s1],
                                               BRIEFS, trace=(te2 := []))
    check(not ver["verified"] and kept[0]["caption"] == "Buses park here."
          and "not verified" in te2[0]["detail"], "failed pass flagged")

    def spent(*a, **k):
        raise llm.LLMBudgetSpent("spent")
    llm.ask = spent
    try:
        film_mod.write_captions([sc("p1")], BRIEFS)
        check(False, "writer budget propagates")
    except llm.LLMBudgetSpent:
        check(True, "writer budget propagates")
    try:
        film_mod.edit_captions("T", [], [sc("p1")], BRIEFS)
        check(False, "editor budget propagates")
    except llm.LLMBudgetSpent:
        check(True, "editor budget propagates")

    vA = {**sc("a"), "caption_note": "You were here", "caption": "You were here",
          "caption_source": "vantage-note"}
    film_mod._refit_scenes(
        [vA, sc("c")],
        {"a": meta("x", coll="personal"), "c": meta("y")},
        {"a": {"observed": {"caption": "Stored A."}}})
    check(vA["caption_note"] is None and vA["caption"] == "Stored A."
          and vA["caption_source"] == "stored-caption", "orphan note repaired")

    rows = {"p1": {"place_key": "k", "viewpoint": "ground_level",
                   "collection": "world", "record": {"observed": {
                       "scene": {"type": "street"}, "entities": [],
                       "visible_text": [], "people": {"count": 0},
                       "caption": "Stored one."},
                       "inferred": {"place": {"name": "K", "status": "confirmed"},
                                    "taken_from": {}}}}}
    foc = {"p1": {"mood": "busy", "confidence": 0.8}}
    sheet = {"title": "T", "cover": "p1",
             "beats": [{"role": "build", "intent": "go", "photo_ids": ["p1"],
                        "pacing": "medium", "camera": "hold", "reason": "r"}]}
    llm.ask = lambda *a, **k: {"text": json.dumps(
        {"p1": "Buses park here."} if k.get("purpose") == "captions" else
        {"title": SUP, "intents": [SUP], "scenes": {"p1": {"claims": [SUP]}}})}
    film = film_mod.build_film(sheet, rows, foc, "short", trace=(tb := []))
    check(film["cover"] == "p1" and len(film["scenes"]) == 1
          and film["scenes"][0]["caption"] == "Buses park here."
          and "(mood: busy)" in film["scenes"][0]["why"]
          and film["scenes"][0]["focal"]["mood"] == "busy"
          and film["verification"]["verified"]
          and film["total_seconds"] == 8.0
          and any("Outside" in t["detail"] for t in tb),
          "build_film end to end")
finally:
    llm.ask = orig_ask

print(f"test_film.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
