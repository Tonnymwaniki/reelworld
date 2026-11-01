"""Focused checks for scene assembly (backend/film.py).

Transitions from metadata, precedence, vantage notes: pure code,
no model. Run from the project root:  python backend/test_film.py
"""
import json
import sys
import tempfile
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

SCRIPT_BEATS = [{"role": "build", "intent": "wander", "photo_ids": ["p1"]}]
GOOD_SCRIPT = {"title": "T", "openings": ["O1", "O2", "O3"],
               "scenes": {"p1": {"narration": "Buses park here in the light.",
                                 "caption": "Buses park.",
                                 "silent_reason": ""}}}
orig_ask = llm.ask
try:
    llm.ask = lambda *a, **k: {"text": json.dumps(GOOD_SCRIPT)}
    w = [{**sc("p1"), "seconds": 4},
         {**sc("p2"), "seconds": 4, "caption_note": "You were here"}]
    title, openings = film_mod.write_script(
        w, BRIEFS, SCRIPT_BEATS, "S.", trace=(tw := []))
    check(title == "T" and openings == ["O1", "O2", "O3"]
          and w[0]["narration"] == "Buses park here in the light."
          and w[0]["caption"] == "Buses park." and w[0]["silent"] is False
          and w[0]["narration_source"] == "script-model"
          and w[1]["narration"] == "You were here" and len(tw) == 1,
          "script written")
    replies = [json.dumps({"title": "T", "openings": ["O1", "O2", "O3"],
                           "scenes": {"p9": {"narration": "x", "caption": "",
                                             "silent_reason": ""}}}),
               json.dumps(GOOD_SCRIPT)]
    llm.ask = lambda *a, **k: {"text": replies.pop(0)}
    w = [{**sc("p1"), "seconds": 4}]
    film_mod.write_script(w, BRIEFS, SCRIPT_BEATS, "S.")
    check(w[0]["narration"] == "Buses park here in the light.",
          "script retry recovers")
    llm.ask = lambda *a, **k: {"text": "garbage"}
    w = [{**sc("p1"), "seconds": 4}]
    title, openings = film_mod.write_script(
        w, BRIEFS, SCRIPT_BEATS, "S.", trace=(tw2 := []))
    check(w[0]["narration"] == "Stored one."
          and w[0]["narration_source"] == "stored-caption"
          and title is None and openings == []
          and "stored captions" in tw2[0]["detail"], "script fallback")
    seen = {}
    llm.ask = lambda *a, **k: (seen.update(prompt=a[0], **k),
                               {"text": json.dumps(GOOD_SCRIPT)})[1]
    w = [{**sc("p1"), "seconds": 4}]
    film_mod.write_script(w, BRIEFS, SCRIPT_BEATS, "S.", trace=(tw3 := []),
                          image_path="sheet.jpg")
    check(seen.get("image_path") == "sheet.jpg"
          and "attached photos" in seen.get("prompt", "")
          and "same way" in seen.get("prompt", "")
          and "studying the photos" in tw3[0]["detail"],
          "script studies the photos")
    vgood = lambda narr: {"title": "T", "openings": ["O1", "O2", "O3"],
                          "scenes": {"p1": {"narration": narr, "caption": "",
                                            "silent_reason": ""}}}
    vreplies = [json.dumps(vgood("Tonny skates across the plaza.")),
                json.dumps(vgood("I skate across the plaza."))]
    llm.ask = lambda *a, **k: {"text": vreplies.pop(0)}
    vbriefs = {"p1": dict(BRIEFS["p1"], owner_present=True)}
    w = [{**sc("p1"), "seconds": 4}]
    film_mod.write_script(w, vbriefs, SCRIPT_BEATS, "S.", voice="i",
                          profile={"name": "Tonny"})
    check(w[0]["narration"] == "I skate across the plaza.",
          "wrong voice retried")
    seen_style = {}
    llm.ask = lambda *a, **k: (seen_style.update(prompt=a[0]),
                               {"text": json.dumps(GOOD_SCRIPT)})[1]
    w = [{**sc("p1"), "seconds": 4}]
    film_mod.write_script(w, BRIEFS, SCRIPT_BEATS, "S.", style="cinematic")
    check("present tense" in seen_style["prompt"]
          and "hustle and bustle" in seen_style["prompt"],
          "writer carries voice rules")

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
        film_mod.write_script([{**sc("p1"), "seconds": 4}], BRIEFS,
                              SCRIPT_BEATS, "S.")
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
    sheet = {"title": "T", "cover": "p1", "spine": "The street, held still.",
             "beats": [{"role": "build", "intent": "go", "photo_ids": ["p1"],
                        "pacing": "medium", "camera": "hold", "reason": "r"}]}
    script_calls = []

    def fake_ask(*a, **k):
        if k.get("purpose") == "script":
            script_calls.append(1)
            if len(script_calls) == 1:
                return {"text": json.dumps({"p1": {
                    "focus": "the street",
                    "focus_source": "place: K (confirmed)",
                    "held_back": ["viewpoint: ground_level", "people: 0"],
                    "callback_of": None}})}
            return {"text": json.dumps(
                {"title": "T", "openings": ["O1", "O2", "O3"],
                 "scenes": {"p1": {"narration": "Buses park here.",
                                   "caption": "Buses wait.",
                                   "silent_reason": ""}}})}
        if k.get("purpose") == "critic":
            return {"text": json.dumps(
                {"p1": {"flags": ["flat description"], "note": "dull"}})}
        if k.get("purpose") == "rewrite":
            return {"text": json.dumps(
                {"p1": {"narration": "Buses park here.",
                        "caption": "Buses wait."}})}
        if k.get("purpose") == "judge":
            return {"text": json.dumps(
                {"ranking": ["O1", "O2", "O3"], "reason": "short"})}
        return {"text": json.dumps(
            {"title": SUP, "intents": [SUP],
             "scenes": {"p1": {"claims": [SUP, SUP]}}})}

    llm.ask = fake_ask
    film = film_mod.build_film(sheet, rows, foc, "short", trace=(tb := []))
    check(film["cover"] == "p1" and len(film["scenes"]) == 1
          and film["scenes"][0]["narration"] == "Buses park here."
          and film["scenes"][0]["caption"] == "Buses wait."
          and film["openings"] == ["O1", "O2", "O3"]
          and "(mood: busy)" in film["scenes"][0]["why"]
          and film["scenes"][0]["focal"]["mood"] == "busy"
          and film["verification"]["verified"]
          and film["total_seconds"] == 8.0
          and any("Outside" in t["detail"] for t in tb),
          "build_film end to end")
    check(film["version"] == 2, "film schema v2")
    check(film["spine"] == "The street, held still.", "film carries the spine")
    check(all(s["duration"] == s["seconds"] for s in film["scenes"]),
          "duration mirrors seconds")
    check(all(isinstance(s["evidence"], list) and s["evidence"]
              and all(isinstance(e, str) for e in s["evidence"])
              for s in film["scenes"]), "scenes carry evidence")
    s2 = {**sc("p1"), "narration": "Buses park here.", "caption": "Buses wait."}
    llm.ask = lambda *a, **k: {"text": json.dumps(
        {"title": SUP, "intents": [SUP],
         "scenes": {"p1": {"claims": [SUP, {"verdict": "unsupported",
                                            "rewrite": "Buses rest."}]}}})}
    _t, _b, kept, ver = film_mod.edit_captions("T", [{"intent": "go"}], [s2],
                                               BRIEFS)
    check(kept[0]["narration"] == "Buses park here."
          and kept[0]["caption"] == "Buses rest." and ver["fixed"] == 1,
          "narration and caption verified")
finally:
    llm.ask = orig_ask

NEED2 = [{**sc("p1"), "seconds": 4}, {**sc("p2"), "seconds": 4}]


def script_reply(n1, n2, cap="Short line.", openings=None, title="T"):
    return {"title": title,
            "openings": openings if openings is not None else ["O1", "O2", "O3"],
            "scenes": {"p1": {"narration": n1, "caption": cap,
                              "silent_reason": ""},
                       "p2": {"narration": n2, "caption": cap,
                              "silent_reason": ""}}}


entries, _, _, problems = film_mod._validate_script(
    script_reply("Buses gather here in the morning light daily.",
                 "Morning buses rest here now."), NEED2, "")
check(entries is not None and entries["p1"]["narration"].startswith("Buses gather"),
      "valid script passes")
_, _, _, problems = film_mod._validate_script(
    script_reply(" ".join(f"w{i}" for i in range(20)),
                 "Morning buses rest here now."), NEED2, "")
check(any("needs 8-12" in p for p in problems), "long narration rejected")
_, _, _, problems = film_mod._validate_script(
    {"title": "T", "openings": ["O1", "O2", "O3"],
     "scenes": {"p1": {"narration": "", "caption": "",
                       "silent_reason": "Let it breathe."},
                "p2": {"narration": "", "caption": "",
                       "silent_reason": "Hold still."}}}, NEED2, "")
check(any("max a quarter" in p for p in problems), "silent quota enforced")
NEED4 = NEED2 + [{**sc("p3"), "seconds": 4}, {**sc("p4"), "seconds": 4}]
_, _, _, problems = film_mod._validate_script(
    {"title": "T", "openings": ["O1", "O2", "O3"],
     "scenes": {"p1": {"narration": "", "caption": "", "silent_reason": ""},
                "p2": {"narration": "Buses gather here in the morning light daily.",
                        "caption": "", "silent_reason": ""},
                "p3": {"narration": "Buses gather here in the morning light daily.",
                        "caption": "", "silent_reason": ""},
                "p4": {"narration": "Morning buses rest here now.", "caption": "",
                        "silent_reason": ""}}}, NEED4, "")
check(problems == ["p1 silent scene needs a reason"], "silent needs a reason")
_, _, _, problems = film_mod._validate_script(
    script_reply("Buses gather here in the morning light daily.",
                 "Morning buses rest here now here here here here here here here here."),
    NEED2, "")
check(any("final line" in p for p in problems), "final stays short")
_, _, _, problems = film_mod._validate_script(
    script_reply("Buses gather here in the morning light daily.",
                 "The plaza holds quiet shadows."), NEED2, "")
check(any("echo" in p for p in problems), "closing echo enforced")
_, _, _, problems = film_mod._validate_script(
    script_reply("Buses gather here in the morning light daily.",
                 "Morning buses rest here now.", openings=["O1", "O2"]),
    NEED2, "")
check(any("openings" in p for p in problems), "three openings required")
_, _, _, problems = film_mod._validate_script(
    script_reply("Buses gather here in the morning light daily.",
                 "Morning buses rest here now.",
                 cap="one two three four five six seven eight nine ten eleven"),
    NEED2, "")
check(any("10 words" in p for p in problems), "caption stays short")

orig_ask = llm.ask
try:
    llm.ask = lambda *a, **k: {"text": json.dumps(
        {"p1": {"flags": ["repetition", "cliche"], "note": "dull"},
         "p2": {"flags": [], "note": ""}})}
    ss = [{**sc("p1"), "seconds": 4, "narration": "Buses gather here daily.",
           "focus_detail": {"text": "buses", "source": "x"}},
          {**sc("p2"), "seconds": 4, "narration": "Morning buses rest.",
           "focus_detail": {"text": "morning", "source": "y"}}]
    flagged = film_mod.critique_script(ss, BRIEFS, "postcard", trace=(tc := []))
    check(flagged == {"p1": {"flags": ["repetition", "cliche"], "note": "dull"}}
          and any("2 issues in 1" in t["detail"] for t in tc),
          "critic flags parsed")
    replies = ["garbage", json.dumps({"p1": {"flags": [], "note": ""}})]
    llm.ask = lambda *a, **k: {"text": replies.pop(0)}
    ss = [{**sc("p1"), "seconds": 4, "narration": "Buses rest."}]
    flagged = film_mod.critique_script(ss, BRIEFS, "postcard")
    check(flagged == {}, "critic retry recovers")
    llm.ask = lambda *a, **k: {"text": "garbage"}
    flagged = film_mod.critique_script(ss, BRIEFS, "postcard", trace=(tc2 := []))
    check(flagged == {} and any("keeping the draft" in t["detail"] for t in tc2),
          "critic failure keeps draft")
    flagged = {"p1": {"flags": ["flat description"], "note": "dull"}}
    llm.ask = lambda *a, **k: {"text": json.dumps(
        {"p1": {"narration": "Buses gather here in the morning light daily.",
                "caption": "Morning buses."}})}
    ss = [{**sc("p1"), "seconds": 4, "narration": "Buses rest here.",
           "caption": "Old."},
          {**sc("p2"), "seconds": 4, "narration": "Morning buses rest here now.",
           "caption": "Old two."}]
    film_mod.rewrite_lines(ss, BRIEFS, flagged, "postcard", None, None,
                           trace=(tr := []))
    check(ss[0]["narration"] == "Buses gather here in the morning light daily."
          and ss[0]["narration_source"] == "script-rewrite"
          and any("Rewrote 1" in t["detail"] for t in tr), "rewrite applies")
    flagged = {"p1": {"flags": ["cliche"], "note": "x"}}
    bad = {"p1": {"narration": " ".join(f"w{i}" for i in range(30)),
                  "caption": "Way too long."}}
    llm.ask = lambda *a, **k: {"text": json.dumps(bad)}
    ss = [{**sc("p1"), "seconds": 4, "narration": "Buses rest here.",
           "caption": "Old."}]
    film_mod.rewrite_lines(ss, BRIEFS, flagged, "postcard", None, None,
                           trace=(tr2 := []))
    check(ss[0]["narration"] == "Buses rest here."
          and any("failed twice" in t["detail"] for t in tr2),
          "rewrite misfit keeps draft")
    flagged = {"p1": {"flags": ["cliche"], "note": "x"},
               "p2": {"flags": ["lists"], "note": "y"}}
    llm.ask = lambda *a, **k: {"text": json.dumps(
        {"p1": {"narration": "Towers loom above the empty streets tonight calm.",
                "caption": "Towers."},
         "p2": {"narration": "Shadows settle over the quiet marketplace stalls.",
                "caption": "Shadows."}})}
    ss = [{**sc("p1"), "seconds": 4, "narration": "Buses rest here.",
           "caption": "Old one."},
          {**sc("p2"), "seconds": 4, "narration": "Morning buses rest here now.",
           "caption": "Old two."}]
    film_mod.rewrite_lines(ss, BRIEFS, flagged, "postcard", None, None,
                           trace=(tr3 := []))
    check(ss[0]["narration"] == "Buses rest here."
          and ss[1]["narration"] == "Morning buses rest here now."
          and any("preserve the echo" in t["detail"] for t in tr3),
          "rewrite preserves echo")
    openings = ["Morning buses gather in the soft light daily now.",
                "Buses.",
                "Towers loom while the buses gather below."]
    llm.ask = lambda *a, **k: {"text": json.dumps(
        {"ranking": [openings[1], openings[0], openings[2]],
         "reason": "echoes morning"})}
    ss = [{**sc("p1"), "seconds": 4, "narration": "Buses rest here.",
           "caption": "Old."},
          {**sc("p2"), "seconds": 4, "narration": "Morning buses rest here now.",
           "caption": "Old."}]
    film_mod.judge_opening(ss, BRIEFS, openings, "S.", "postcard", None, None,
                           trace=(tj := []))
    check(ss[0]["narration"] == openings[0]
          and ss[0]["narration_source"] == "script-judge"
          and any("Opening 1 chosen" in t["detail"] for t in tj),
          "judge picks opening")
    llm.ask = lambda *a, **k: {"text": json.dumps(
        {"ranking": ["Buses.", "Towers.", "Plaza."], "reason": "short"})}
    ss = [{**sc("p1"), "seconds": 4, "narration": "Buses rest here.",
           "caption": "Old."}]
    film_mod.judge_opening(ss, BRIEFS, ["Buses.", "Towers.", "Plaza."], "S.",
                           "postcard", None, None, trace=(tj2 := []))
    check(ss[0]["narration"] == "Buses rest here."
          and any("No opening fit" in t["detail"] for t in tj2),
          "judge keeps on misfit")
    ss = [{**sc("p1"), "seconds": 4, "caption_note": "You were here",
           "narration": "You were here"}]
    film_mod.judge_opening(ss, BRIEFS, ["A fine opening line here today.",
                                        "Another fine opening line here today.",
                                        "Yet another opening line here today."],
                           "S.", "postcard", None, None, trace=(tj3 := []))
    check(any("fixed" in t["detail"] for t in tj3), "judge skips fixed opening")
finally:
    llm.ask = orig_ask

tmp = tempfile.TemporaryDirectory()
odir = Path(tmp.name)
odir.joinpath("a1.json").write_text(json.dumps(
    {"matches": [{"box_norm": {"x1": 0.2, "y1": 0.3, "x2": 0.6, "y2": 0.7}}]}),
    encoding="utf-8")
odir.joinpath("bad.json").write_text("not json", encoding="utf-8")
odir.joinpath("empty.json").write_text(json.dumps({"matches": []}),
                                       encoding="utf-8")
sp = film_mod.spotlight_for("a1", outlines_dir=odir)
check(sp == {"x": 0.4, "y": 0.5, "r": 0.28}, "spotlight from box")
check(film_mod.spotlight_for("missing", outlines_dir=odir) is None,
      "spotlight missing silent")
check(film_mod.spotlight_for("bad", outlines_dir=odir) is None,
      "spotlight malformed silent")
check(film_mod.spotlight_for("empty", outlines_dir=odir) is None,
      "spotlight no matches silent")
check(film_mod.spotlight_for("a1", outlines_dir=odir, enabled=False) is None,
      "spotlight flag off silent")
scenes = [{"photo_id": "a1"}, {"photo_id": "missing"}]
check(film_mod.attach_spotlights(scenes, outlines_dir=odir) == 1
      and scenes[0]["spotlight"] == sp and "spotlight" not in scenes[1],
      "attach counts and skips")

SEL_BRIEFS = {"p1": BRIEFS["p1"], "p2": BRIEFS["p2"]}
SEL_BEATS = [{"role": "build", "intent": "wander", "photo_ids": ["p1", "p2"]}]
C1 = film_mod.evidence_for(BRIEFS["p1"])
C2 = film_mod.evidence_for(BRIEFS["p2"])
SEL_BRIEF = {"about": "a slow day", "feeling": "calm", "avoid": "buses"}
BC1 = C1 + ["owner's brief: a slow day", "owner's feeling: calm"]
BC2 = C2 + ["owner's brief: a slow day", "owner's feeling: calm"]
GOOD_SEL = {"p1": {"focus": "the buses lined up", "focus_source": C1[0],
                    "held_back": BC1[1:], "callback_of": None},
            "p2": {"focus": "a slow day out",
                    "focus_source": "owner's brief: a slow day",
                    "held_back": [c for c in BC2
                                  if c != "owner's brief: a slow day"],
                    "callback_of": None}}
orig_ask = llm.ask
try:
    seen = {}
    llm.ask = lambda *a, **k: (seen.update(prompt=a[0]),
                               {"text": json.dumps(GOOD_SEL)})[1]
    ss = [sc("p1"), sc("p2")]
    film_mod.select_details(ss, SEL_BEATS, SEL_BRIEFS, "A spine.",
                            brief=SEL_BRIEF, trace=(tf := []))
    check(ss[0]["focus_detail"] == {"text": "the buses lined up",
                                    "source": C1[0]}
          and ss[1]["focus_detail"]["source"] == "owner's brief: a slow day"
          and len(ss[0]["held_back"]) == len(BC1) - 1
          and any("Selected the focus" in t["detail"] for t in tf)
          and "avoid: buses" in seen["prompt"], "focus selected")
    replies = ["garbage", json.dumps(GOOD_SEL)]
    llm.ask = lambda *a, **k: {"text": replies.pop(0)}
    ss = [sc("p1"), sc("p2")]
    film_mod.select_details(ss, SEL_BEATS, SEL_BRIEFS, "S.", brief=SEL_BRIEF)
    check(ss[0]["focus_detail"]["source"] == C1[0], "focus retry recovers")
    llm.ask = lambda *a, **k: {"text": "garbage"}
    ss = [sc("p1")]
    film_mod.select_details(ss, SEL_BEATS, SEL_BRIEFS, "S.", trace=(tf2 := []))
    check(ss[0]["focus_detail"] == {"text": C1[0][:80], "source": C1[0]}
          and any("first fact" in t["detail"] for t in tf2), "focus fallback")
    same = {"p1": SEL_BRIEFS["p1"], "p2": SEL_BRIEFS["p1"]}
    dup = {"p1": {"focus": "First", "focus_source": C1[0],
                  "held_back": C1[1:], "callback_of": None},
           "p2": {"focus": "Second", "focus_source": C1[0],
                  "held_back": C1[1:], "callback_of": None}}
    llm.ask = lambda *a, **k: {"text": json.dumps(dup)}
    ss = [sc("p1"), sc("p2")]
    film_mod.select_details(ss, SEL_BEATS, same, "S.", trace=(tf3 := []))
    check(ss[1]["focus_detail"]["source"] == C1[1]
          and any("switched" in t["detail"] for t in tf3),
          "dup focus switched")
finally:
    llm.ask = orig_ask
bad_cb = {"p1": {"focus": "X", "focus_source": C1[0], "held_back": [],
                 "callback_of": "p9"}}
check(film_mod._validate_selection(bad_cb, {"p1": C1}, ["p1"])[0] is None,
      "bad callback rejected")

print(f"test_film.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
