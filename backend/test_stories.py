"""Focused checks for the story engine (backend/story_engine.py).

CRUD + validation + faces-blocking against fixture photos in a temp
dir: no database, no model. Run from the project root:
python backend/test_stories.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import story_engine as eng  # noqa: E402  (needs the sys.path line above)

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


def expect(status, fn, label):
    global fails, total
    total += 1
    try:
        fn()
    except eng.StoryError as e:
        if e.status != status:
            fails += 1
            print(f"FAIL {label}: status {e.status}, want {status}")
    except Exception as e:  # noqa: BLE001 (any other error is a failure)
        fails += 1
        print(f"FAIL {label}: {type(e).__name__} {e}")
    else:
        fails += 1
        print(f"FAIL {label}: no error raised")


PHOTOS = {"a1": {"people": 0}, "a2": {"people": 0}, "b1": {"people": 2}}


def fetch(pid):
    return PHOTOS.get(pid)


tmp = tempfile.TemporaryDirectory()
eng.STORIES_DIR = Path(tmp.name)

s = eng.create(title="  Day out ", chapters=[{"photo_id": "a1"}, {"photo_id": "a2", "seconds": 6}],
               fetch=fetch)
check(s["title"] == "Day out" and s["status"] == "draft"
      and len(s["chapters"]) == 2 and s["chapters"][0]["seconds"] == 4, "create defaults")
check(s["id"].startswith("st-") and eng.load(s["id"])["id"] == s["id"], "roundtrip")
expect(400, lambda: eng.create(chapters=[{"photo_id": "nope"}], fetch=fetch), "unknown photo 400")
expect(400, lambda: eng.create(chapters=[], fetch=fetch), "empty chapters 400")
expect(400, lambda: eng.create(tone="noir", chapters=[{"photo_id": "a1"}], fetch=fetch), "bad tone 400")
expect(400, lambda: eng.create(chapters=[{"photo_id": "a1", "seconds": 99}], fetch=fetch), "bad seconds 400")

u = eng.update(s["id"], title="Day out 2",
               chapters=[{"photo_id": "a2", "heading": "Hi", "seconds": 5},
                         {"photo_id": "a1", "seconds": 5}], fetch=fetch)
check(u["title"] == "Day out 2" and u["chapters"][0]["photo_id"] == "a2"
      and u["chapters"][0]["heading"] == "Hi", "update reorder+heading")

blocked = eng.create(title="Faces", chapters=[{"photo_id": "b1"}], fetch=fetch)
expect(409, lambda: eng.publish(blocked["id"], fetch), "faces block publish")
try:
    eng.publish(blocked["id"], fetch)
except eng.StoryError as e:
    check(e.extra.get("blocked") == ["b1"], "blocked ids listed")
p = eng.publish(s["id"], fetch)
check(p["status"] == "published" and p["published_at"], "publish clean")
expect(409, lambda: eng.update(s["id"], chapters=[{"photo_id": "b1"}], fetch=fetch),
       "faces block published edit")
check([x["id"] for x in eng.list_stories("published")] == [s["id"]], "list published")
check(len(eng.list_stories()) == 2, "list all")
eng.remove(s["id"])
expect(404, lambda: eng.load(s["id"]), "deleted story 404")
expect(404, lambda: eng.remove(s["id"]), "double delete 404")

print(f"test_stories.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
