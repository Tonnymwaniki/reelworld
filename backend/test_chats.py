"""Focused checks for saved chats (backend/chats.py + endpoints).

Storage, titles, snapshots, restore, expiry and the six /api/chats
routes: no model or database (dirs are temp, the engine is faked).
Run from the project root:  python backend/test_chats.py
"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chats as chats_mod  # noqa: E402  (needs the sys.path line above)

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


tmp = tempfile.TemporaryDirectory()
chats_mod.CHATS_DIR = Path(tmp.name)

PAYLOAD = {"text": "Only 2 photos clearly show mist.",
           "kind": "ok",
           "spec": {"query": "misty mountains", "collection": "world",
                    "viewpoints": [], "max_people": None,
                    "must_include": ["mountains"], "avoid_terms": [],
                    "owner_only": False, "constraints": [
                        {"attribute": "atmosphere", "op": "is",
                         "values": ["misty_or_foggy"]}]},
           "results": [{"photo_id": "hills_022",
                        "file": "data/photos/world/hills/hills_022.jpg",
                        "caption": "A foggy mountain.",
                        "check": {"verdict": "yes",
                                  "reason": "soft white veil visible"}}],
           "trace": [{"step": "routed",
                      "detail": "tools: search in 1 round(s) via native."}],
           "about_photo_id": None,
           "topic": {"id": 1, "label": "mountains", "new": True},
           "label": "Mountains / with mist", "options": None}
SNAP = {"spec": dict(PAYLOAD["spec"]), "focus": None,
        "last": list(PAYLOAD["results"]), "rejected": [],
        "replies": [{"photos": [{"id": "hills_022",
                                 "label": "A foggy mountain.",
                                 "verdict": "yes"}]}],
        "topic": {"id": 1, "label": "mountains"}}

# ids + validation
check(chats_mod.valid_chat_id("chat_20261101_0001"), "good id valid")
check(not chats_mod.valid_chat_id("../x")
      and not chats_mod.valid_chat_id("a b")
      and not chats_mod.valid_chat_id("")
      and not chats_mod.valid_chat_id(None), "bad ids rejected")

# create + auto title
c1 = chats_mod.create_chat("local")
check(c1["id"].startswith("chat_") and c1["title"] == "New chat"
      and c1["title_auto"] is True
      and chats_mod.chat_path("local", c1["id"]).exists(), "create empty")
c2 = chats_mod.create_chat("local", "Mountains")
check(c2["id"] != c1["id"] and c2["title"] == "Mountains"
      and c2["title_auto"] is False, "create with title")
check(chats_mod.auto_title("  show me\n mountains  ")
      == "Show me mountains", "title squeezed")
check(chats_mod.auto_title("show me photos of mountains with mist and fog rolling over the hills")
      == "Show me photos of mountains with mist and fog", "title cuts at a word")
check(chats_mod.auto_title("mountains?") == "Mountains", "title strips punctuation")
check(chats_mod.auto_title("   ") == "New chat", "title blanks")
check(len(chats_mod.auto_title("x" * 100)) == 48, "title caps length")
check(chats_mod.auto_title("x" * 100) == "X" + "x" * 47, "title truncated")

# append turns: records, verdicts, title, snapshot
got = chats_mod.append_turn("local", c1["id"], "mountains with mist",
                            PAYLOAD, SNAP)
check(got is not None and len(got["messages"]) == 2
      and got["messages"][0] == {"role": "user",
                                 "text": "mountains with mist",
                                 "time": got["messages"][0]["time"]}
      and got["title"] == "Mountains with mist", "first turn recorded")
reel = got["messages"][1]
check(reel["kind"] == "ok" and reel["topic_id"] == 1
      and reel["topic_new"] is True and reel["label"].startswith("Mountains")
      and reel["spec"]["must_include"] == ["mountains"]
      and reel["results"][0]["check"]["verdict"] == "yes"
      and reel["trace"][0]["step"] == "routed", "reel record complete")
check(got["state"]["topic"] == {"id": 1, "label": "mountains"}
      and got["state"]["replies"][0]["photos"][0]["id"] == "hills_022",
      "state snapshot stored")
got = chats_mod.append_turn("local", c1["id"], "from above", PAYLOAD, SNAP)
check(len(got["messages"]) == 4 and got["title"] == "Mountains with mist",
      "manual-era title sticks")
check(chats_mod.append_turn("local", "chat_nope", "hi", PAYLOAD, SNAP)
      is None, "append to missing chat is None")
check(not chats_mod.scan_reasoning(got), "no reasoning stored")
check(chats_mod.scan_reasoning({"a": {"reasoning_content": "x"}}),
      "reasoning scan trips")

# summaries + list order + thumbs
sums = chats_mod.list_chats("local")
check([s["id"] for s in sums] == [c1["id"], c2["id"]]
      and sums[0]["message_count"] == 4
      and sums[0]["thumb"] == {"photo_id": "hills_022",
                               "file": "data/photos/world/hills/hills_022.jpg"}
      and sums[1]["thumb"] is None, "list newest first with thumbs")

# snapshot roundtrip + restore
estate = {"spec": dict(PAYLOAD["spec"]), "focus": {"photo_id": "hills_022"},
          "last": list(PAYLOAD["results"]), "rejected": {"old_001"},
          "replies": list(SNAP["replies"]),
          "topic": {"id": 2, "label": "x"}, "pending": {"options": []},
          "user_texts": ["stale"]}
snap = chats_mod.snapshot_state(estate)
check(snap["rejected"] == ["old_001"], "rejected set to sorted list")
fresh = {"spec": {}, "focus": None, "last": [], "rejected": set(),
         "replies": [], "topic": {"id": 0, "label": ""}, "pending": None,
         "user_texts": []}
eng = SimpleNamespace(state=fresh)
chats_mod.apply_state(
    eng, {"state": snap,
          "messages": [{"role": "user", "text": "a"},
                       {"role": "reel", "text": "b"},
                       {"role": "user", "text": "c"},
                       {"role": "user", "text": "d"},
                       {"role": "user", "text": "e"}]})
check(fresh["rejected"] == {"old_001"} and fresh["topic"]["id"] == 2
      and fresh["pending"] is None and fresh["user_texts"] == ["c", "d", "e"]
      and fresh["focus"] == {"photo_id": "hills_022"}, "restore exact")

# expiry: demo scopes age out, local never does
old = chats_mod.create_chat("visitor1")
p = chats_mod.chat_path("visitor1", old["id"])
raw = json.loads(p.read_text(encoding="utf-8"))
raw["updated_at"] = (datetime.now(timezone.utc)
                     - timedelta(days=8)).isoformat()
p.write_text(json.dumps(raw), encoding="utf-8")
check(chats_mod.load_chat("visitor1", old["id"]) is None
      and not p.exists(), "expired demo chat gone on load")
old2 = chats_mod.create_chat("visitor1")
p2 = chats_mod.chat_path("visitor1", old2["id"])
raw = json.loads(p2.read_text(encoding="utf-8"))
raw["updated_at"] = (datetime.now(timezone.utc)
                     - timedelta(days=8)).isoformat()
p2.write_text(json.dumps(raw), encoding="utf-8")
check(chats_mod.cleanup_expired("visitor1") == 1
      and not p2.exists(), "cleanup deletes expired")
check(chats_mod.cleanup_expired("local") == 0, "local never cleaned")
old3 = chats_mod.create_chat("local")
p3 = chats_mod.chat_path("local", old3["id"])
raw = json.loads(p3.read_text(encoding="utf-8"))
raw["updated_at"] = (datetime.now(timezone.utc)
                     - timedelta(days=30)).isoformat()
p3.write_text(json.dumps(raw), encoding="utf-8")
check(chats_mod.load_chat("local", old3["id"]) is not None,
      "local never expires")

# delete paths
check(chats_mod.delete_chat("local", c2["id"]) is True
      and chats_mod.load_chat("local", c2["id"]) is None, "delete one")
check(chats_mod.delete_chat("local", "chat_nope") is False,
      "delete missing is False")
n = chats_mod.delete_all("local")
check(n == 2 and chats_mod.list_chats("local") == [], "delete all")

print(f"test_chats.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
