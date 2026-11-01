"""Regression checks for api._story_full owner-heading flags.

A headed chapter must never crash the story detail, and a heading
that names the owner (or uses you/I) on an untagged photo must be
flagged. No database: _photos_by_ids and the profile are stubbed.
Run from the project root:  python backend/test_story_full.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import api  # noqa: E402
import focal as focal_mod  # noqa: E402
import owner_profile as owner_profile_mod  # noqa: E402
import story_engine as eng_mod  # noqa: E402

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


def rec(present):
    return {
        "observed": {
            "caption": "A person walks.", "description": "",
            "scene": {"setting": "outdoor", "time_of_day": "daytime"},
            "camera": {}, "entities": [], "spatial_relations": [],
            "visible_text": [], "people": {"count": 1},
        },
        "inferred": {"landmarks": [], "place": {}, "taken_from": {},
                     "cultural_context": "", "uncertainties": []},
        "provided": {"owner": {"present": present}},
    }


def row(pid, present):
    return {"photo_id": pid, "collection": "personal",
            "file": f"data/photos/personal/{pid}.jpg",
            "caption": "A person walks.", "viewpoint": "ground_level",
            "place_name": "Test place", "record": rec(present)}


ROWS = {"t1": row("t1", None), "t2": row("t2", True)}
HINT = "refresh the narration"

real_lookup = api._photos_by_ids
real_profile = owner_profile_mod.load_profile
api._photos_by_ids = lambda ids, cols="": {i: ROWS[i] for i in ids if i in ROWS}  # noqa: E731
owner_profile_mod.load_profile = lambda: {"name": "Tonny", "refer_as": "name"}  # noqa: E731
try:
    out = api._story_full({"chapters": [
        {"photo_id": "t1", "heading": "Tonny at the gate", "text": "x"},
        {"photo_id": "t2", "heading": "Tonny at the gate", "text": "x"},
        {"photo_id": "t1", "heading": "A quiet gate", "text": "x"},
    ]})
    probs = out["problems"]
    check(any(HINT in p for p in probs.get("0", [])),
          "untagged heading flagged")
    check(not any(HINT in p for p in probs.get("1", [])),
          "tagged heading not flagged")
    check("2" not in probs, "plain heading clean")
    pub = {"status": "published", "include_name": False,
           "title": "Tonny at KICC",
           "brief": {"about": "Tonny day out", "feeling": "calm", "avoid": ""},
           "chapters": [
               {"photo_id": "t2", "heading": "Tonny at the gate",
                "text": "Tonny waves."}]}
    shown = api._story_full(pub, True)
    check(shown["story"]["title"] == "the photographer at KICC"
          and shown["chapters"][0]["text"] == "the photographer waves."
          and "Tonny" not in shown["chapters"][0]["heading"],
          "public hides name")
    check(shown["story"]["brief"]["about"] == "the photographer day out",
          "public scrubs brief")
    check(pub["title"] == "Tonny at KICC", "stored story untouched")
    kept = api._story_full(pub, False)
    check("Tonny" in kept["chapters"][0]["text"], "owner view keeps name")
    opt = api._story_full(dict(pub, include_name=True), True)
    check("Tonny" in opt["chapters"][0]["text"], "opt-in keeps name public")
    draft = api._story_full(dict(pub, status="draft"), True)
    check("Tonny" in draft["chapters"][0]["text"], "draft never rewritten")
    real_llm_json = api._llm_json
    real_record = api._record_or_404
    real_items = api._story_sheet_items
    real_save = focal_mod.save_sheet
    calls, seen_items, nv = {}, {}, []
    try:
        def fake_llm_json(prompt, *a, **k):
            calls["prompt"] = prompt
            calls.update(k)
            return {"text": "Tonny walks."}

        def fake_save(items):
            seen_items["items"] = items
            return "sheet.jpg"

        api._llm_json = fake_llm_json
        api._record_or_404 = lambda pid: ROWS[pid]["record"]  # noqa: E731
        api._story_sheet_items = lambda att: [  # noqa: E731
            (r["photo_id"], b"x") for r in att]
        focal_mod.save_sheet = fake_save
        text, _ = api._chapter_text(
            "Gate", [(ROWS["t2"], {})], [ROWS["t2"]], "name",
            prior="Earlier.", theme="my day out", novision=nv)
        check(text == "Tonny walks."
              and calls.get("image_path") == "sheet.jpg",
              "chapter model sees the photos")
        check("my day out" in calls.get("prompt", "")
              and "attached photos" in calls.get("prompt", "")
              and "same first word" in calls.get("prompt", ""),
              "chapter prompt carries theme + vision + variety")
        check(seen_items.get("items") == [("t2", b"x")] and nv == [],
              "sheet built from chapter rows")
        replies = ["Tonny walks.", "I walk."]

        def fake_retry(prompt, *a, **k):
            calls["retry_prompt"] = prompt
            return {"text": replies.pop(0)}

        api._llm_json = fake_retry
        text2, _ = api._chapter_text(
            "Gate", [(ROWS["t2"], {})], [ROWS["t2"]], "i",
            prior="", theme="x", novision=[])
        check(text2 == "I walk." and '"I"' in calls["retry_prompt"],
              "wrong voice retried")
        replies2 = ["Tonny walks.", "Tonny strolls."]
        api._llm_json = lambda prompt, *a, **k: {"text": replies2.pop(0)}  # noqa: E731
        text3, flag3 = api._chapter_text(
            "Gate", [(ROWS["t2"], {})], [ROWS["t2"]], "i",
            prior="", theme="x", novision=[])
        check(text3 == "t2" and flag3 == "repaired",
              "stubborn voice falls back")
    finally:
        api._llm_json = real_llm_json
        api._record_or_404 = real_record
        api._story_sheet_items = real_items
        focal_mod.save_sheet = real_save
    check(api._story_sheet_items([]) == []
          and api._story_sheet_items([{"photo_id": "x"}]) == []
          and api._story_sheet_items(
              [{"photo_id": "x", "file": "data/photos/personal/nope.jpg"}]) == [],
          "sheet items skip missing files")
    check(focal_mod.save_sheet([]) is None, "empty sheet is None")
    real_guard = api._demo_guard
    real_fetch_for = api._story_fetch_for
    real_chapter = api._chapter_text
    real_eng_load = eng_mod.load
    real_eng_update = eng_mod.update
    got = {}
    try:
        def fake_chapter(h, comp, att, voice, prior="", theme="",
                         novision=None):
            got["voice"] = voice
            return ("I walk.", None)

        api._demo_guard = lambda request: None  # noqa: E731
        api._story_fetch_for = lambda ids: (lambda pid: {"people": 0})  # noqa: E731
        api._chapter_text = fake_chapter
        eng_mod.load = lambda sid: {"id": sid, "voice": "i", "prompt": "x",  # noqa: E731
                                    "chapters": [{"photo_id": "t2",
                                                  "heading": "Gate",
                                                  "text": "old", "seconds": 4}]}
        eng_mod.update = lambda sid, **k: {"id": sid,  # noqa: E731
                                           "voice": k.get("voice", "i"),
                                           "chapters": k["chapters"]}
        out = api.story_refresh("st-x", api.StoryRefreshRequest(), None)
        check(got.get("voice") == "i", "refresh writes in stored voice")
        check(out["story"]["voice"] == "i", "refresh keeps stored voice")
    finally:
        api._demo_guard = real_guard
        api._story_fetch_for = real_fetch_for
        api._chapter_text = real_chapter
        eng_mod.load = real_eng_load
        eng_mod.update = real_eng_update
    owner_profile_mod.load_profile = lambda: (_ for _ in ()).throw(  # noqa: E731
        RuntimeError("no profile"))
    out2 = api._story_full({"chapters": [
        {"photo_id": "t1", "heading": "Tonny at the gate", "text": "x"}]})
    check(out2["problems"] == {}, "no profile, no owner flags")
finally:
    api._photos_by_ids = real_lookup
    owner_profile_mod.load_profile = real_profile

print(f"test_story_full.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
