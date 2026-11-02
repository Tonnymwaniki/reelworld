"""Focused checks for the hybrid router (backend/router.py).

Compact state, topic handling, id validation, terminal replies,
compound validation and the JSON fallback: no model or database
(llm.ask_tools / llm.ask are scripted, the engine is faked).
Run from the project root:  python backend/test_router.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chat as chat_mod  # noqa: E402  (needs the sys.path line above)
import llm as llm_mod  # noqa: E402
import router as router_mod  # noqa: E402

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


def fresh_state():
    return {"spec": dict(chat_mod.EMPTY_SPEC), "focus": None, "last": [],
            "rejected": set(), "topic": {"id": 0, "label": ""},
            "replies": [], "user_texts": [], "pending": None}


class FakeTable:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *a):
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class FakeEngine:
    def __init__(self):
        self.state = fresh_state()
        self.session_id = None
        self.turn_llm = []
        self.search_calls = []
        self.tagged = 1
        self.rows = [
            {"photo_id": "mtn_001", "caption": "A misty mountain ridge.",
             "lex": "misty mountain", "similarity": 0.9},
            {"photo_id": "mtn_002", "caption": "A clear mountain lake.",
             "lex": "clear mountain", "similarity": 0.8}]
        self.photos = {}
        self.sb_rows = []

    def search(self, spec, exclude, verify=True):
        self.search_calls.append(dict(spec))
        return ([dict(r) for r in self.rows], None,
                [{"step": "searched", "detail": "fake search"}])

    def related(self, anchor, spec, exclude, angle):
        return ([dict(r) for r in self.rows], None,
                [{"step": "searched", "detail": "fake related"}])

    def fetch_photo(self, pid, cols):
        return self.photos.get(pid)

    def tagged_count(self):
        return self.tagged

    @property
    def sb(self):
        eng = self

        class FakeSB:
            def table(self, name):
                return FakeTable(eng.sb_rows)

        return FakeSB()


class Script:
    """Scripted llm.ask_tools replies."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        r = dict(self.replies.pop(0))
        r.setdefault("provider", "stub")
        r.setdefault("seconds", 0.1)
        r.setdefault("fallback_used", False)
        r.setdefault("malformed", False)
        r.setdefault("text", "")
        r.setdefault("calls", [])
        return r


def run_turn(eng, message):
    out, steps = None, []
    for item in router_mod.route_stream(eng, message):
        if item[0] == "step":
            steps.append((item[1], item[2]))
        else:
            out = item[1]
    return out, steps


def tool_call(name, args, cid="c1"):
    return {"id": cid, "name": name, "args": args}


def seed_reply(eng):
    eng.state["replies"] = [{"photos": [
        {"id": "mtn_001", "label": "A misty mountain ridge.",
         "verdict": "yes"},
        {"id": "mtn_002", "label": "A clear mountain lake.",
         "verdict": None}]}]


# compact state + membership
eng = FakeEngine()
seed_reply(eng)
eng.state["focus"] = {"photo_id": "mtn_001", "caption": "A misty ridge."}
cs = router_mod.build_compact_state(eng)
check(cs["latest"][1]["id"] == "mtn_002" and cs["prev1"] == []
      and cs["focus"]["id"] == "mtn_001"
      and cs["rejected_count"] == 0, "compact state shape")
check(router_mod.state_ids(cs) == {"mtn_001", "mtn_002"},
      "state ids")
check("{state}" not in router_mod.ROUTER_PROMPT.replace("{state}", "{}")
      and "clarify" in router_mod.ROUTER_PROMPT, "router prompt slots")
check("second one" in router_mod.ROUTER_PROMPT
      and "never invent" in router_mod.ROUTER_PROMPT.lower(),
      "ref rules in prompt")
check("two or more replies" in router_mod.ROUTER_PROMPT
      and "two or more replies" in router_mod.JSON_FALLBACK_PROMPT,
      "cross-reply matches clarify")
check("must_include: ALWAYS the core subject" in router_mod.ROUTER_PROMPT
      and "no constraint mapping (snow, rainbow, waterfall)"
      in router_mod.ROUTER_PROMPT,
      "subject must_include always set")
cs2 = {"latest": [{"n": 1, "id": "mtn_002",
                   "label": "A clear mountain lake."}],
       "prev1": [{"n": 1, "id": "mtn_001",
                  "label": "A misty mountain ridge."}],
       "prev2": []}
hit = router_mod._cross_reply_ref("tell me about that mountain", cs2)
check(hit is not None and hit[0] == "mountain"
      and [p["id"] for _, p in hit[1]] == ["mtn_002", "mtn_001"],
      "cross-reply that-noun matches")
check(router_mod._cross_reply_ref("tell me about the second one", cs2)
      is None
      and router_mod._cross_reply_ref("not that mountain", cs2) is None
      and router_mod._cross_reply_ref(
          "tell me about that mountain",
          {"latest": cs2["latest"], "prev1": [], "prev2": []}) is None,
      "ordinals, rejections, single reply left alone")
check("Never ask the user a question in direct text" in router_mod.ROUTER_PROMPT
      and "never a question" in router_mod.JSON_FALLBACK_PROMPT,
      "questions use clarify, not text")

# prefixes + pending (pure)
t, a, m = router_mod._strip_prefixes("new search: markets")
check((t, a, m) == ("new", None, "markets"), "new search prefix")
t, a, m = router_mod._strip_prefixes("refine: from above")
check((t, a, m) == ("refine", None, "from above"), "refine prefix")
t, a, m = router_mod._strip_prefixes("about mtn_001: what sign?")
check((t, a, m) == (None, "mtn_001", "what sign?"), "about prefix")
t, a, m = router_mod._strip_prefixes("new search:")
check((t, m) == (None, "new search:"), "bare prefix left alone")
pend = router_mod._pending_options(
    [{"label": "Continue previous search", "message": "continue previous"},
     {"label": "Start new search", "message": "new search"}],
    cs, "markets")
check(pend[0]["forced_topic"] == "refine"
      and pend[1]["forced_topic"] == "new"
      and pend[0]["message"] == "markets", "topic pending")
pend = router_mod._pending_options(
    [{"label": "A misty ridge", "message": "photo 1"}], cs, "what sign?")
check(pend[0]["forced_about"] == "mtn_001", "photo pending resolves n")

orig_tools = llm_mod.ask_tools
orig_ask = llm_mod.ask
try:
    # search new: fresh topic, rejected cleared, label
    eng = FakeEngine()
    eng.state["rejected"] = {"old_001"}
    llm_mod.ask_tools = Script([{"calls": [tool_call("search", {
        "query": "misty mountains", "topic": "new",
        "constraints": [{"attribute": "atmosphere", "op": "is",
                         "values": ["misty_or_foggy"]}]})]}])
    out, steps = run_turn(eng, "mountains with mist")
    check(out["kind"] == "ok" and len(out["results"]) == 2
          and eng.state["topic"]["id"] == 1
          and eng.state["rejected"] == set()
          and out["topic"]["new"] is True
          and "misty or foggy" in (out.get("label") or ""),
          "search new starts a topic")
    check(any(s[0] == "routed" and "search in 1 round" in s[1]
              for s in [(t["step"], t["detail"]) for t in out["trace"]]),
          "trace logs tools and rounds")

    # search refine: query kept when "", constraints replaced wholesale
    eng.state["spec"] = {"query": "misty mountains", "collection": "world",
                         "viewpoints": [], "max_people": 0,
                         "must_include": [], "avoid_terms": [],
                         "owner_only": False,
                         "constraints": [{"attribute": "atmosphere",
                                          "op": "is",
                                          "values": ["misty_or_foggy"]}]}
    llm_mod.ask_tools = Script([{"calls": [tool_call("search", {
        "query": "", "topic": "refine",
        "constraints": [{"attribute": "atmosphere", "op": "is_not",
                         "values": ["misty_or_foggy"]}]})]}])
    out, _ = run_turn(eng, "now without mist")
    spec = eng.search_calls[-1]
    check(spec["query"] == "misty mountains"
          and spec["constraints"] == [{"attribute": "atmosphere",
                                       "op": "is_not",
                                       "values": ["misty_or_foggy"]}]
          and spec["max_people"] == 0
          and eng.state["topic"]["id"] == 1, "refine merges, flips clean")

    # forced prefix overrides the model's topic
    llm_mod.ask_tools = Script([{"calls": [tool_call(
        "search", {"query": "markets", "topic": "refine"})]}])
    out, _ = run_turn(eng, "new search: markets")
    check(out["topic"]["new"] is True and eng.state["topic"]["id"] == 2,
          "new search prefix forces a topic")

    # unknown id -> clarify card + pending; "photo 1" resolves it
    import api as api_mod  # noqa: E402
    orig_api_ask = api_mod.ask
    seen_ask = []
    api_mod.ask = lambda req: seen_ask.append(req.photo_id) or {
        "answer": "A veil.", "source": "annotation", "note": None,
        "trace": [{"step": "answered", "detail": "stub"}]}
    try:
        eng = FakeEngine()
        seed_reply(eng)
        llm_mod.ask_tools = Script([{"calls": [tool_call(
            "ask_photo", {"photo_id": "nope_001",
                          "question": "what sign?"})]}])
        out, _ = run_turn(eng, "what does the sign say?")
        check(out["kind"] == "clarify" and out["options"]
              and eng.state["pending"] is not None
              and not seen_ask, "unknown id asks which one")
        llm_mod.ask_tools = Script([{"calls": [tool_call(
            "ask_photo", {"photo_id": "mtn_001",
                          "question": "what sign?", "ref": "photo 1"})]}])
        out, _ = run_turn(eng, "photo 1")
        check(seen_ask == ["mtn_001"] and out["kind"] == "question_answer"
              and out["about_photo_id"] == "mtn_001"
              and out["took_to_mean"] == "I took 'photo 1' to mean "
              "this photo.", "pending photo resolves + ref noted")
    finally:
        api_mod.ask = orig_api_ask

    # cross-reply "that mountain": code clarify, no model call; tap resolves
    eng = FakeEngine()
    eng.state["replies"] = [
        {"photos": [{"id": "mtn_001", "label": "A misty mountain ridge.",
                     "verdict": "yes"}]},
        {"photos": [{"id": "mtn_002", "label": "A clear mountain lake.",
                     "verdict": None}]}]
    eng.photos = {
        "mtn_001": {"photo_id": "mtn_001", "collection": "world",
                    "viewpoint": "ground_level", "people_count": 4,
                    "record": {"observed": {"caption": "ridge"},
                               "inferred": {}, "provided": {}}}}
    script = Script([])
    llm_mod.ask_tools = script
    out, _ = run_turn(eng, "tell me about that mountain")
    check(out["kind"] == "clarify" and len(out["options"]) == 2
          and script.calls == 0
          and out["text"].startswith("Which mountain do you mean?"),
          "cross-reply clarify without a model call")
    llm_mod.ask_tools = Script([
        {"calls": [tool_call("get_photo_facts",
                             {"photo_id": "mtn_001"})]},
        {"text": "mtn_001 shows a ridge."}])
    out, _ = run_turn(eng, "the one in previous")
    check(out["kind"] == "question_answer"
          and out["about_photo_id"] == "mtn_001",
          "clarify tap reprocesses with the forced photo")

    # count text is built by code
    eng = FakeEngine()
    eng.sb_rows = [
        {"photo_id": "p1", "collection": "personal",
         "place_key": "kenya/nairobi/cbd/kicc",
         "place_name": "Kenyatta International Convention Centre",
         "owner_present": True, "attributes": {}},
        {"photo_id": "p2", "collection": "personal",
         "place_key": "kenya/nairobi/cbd/kicc",
         "place_name": "Kenyatta International Convention Centre",
         "owner_present": True, "attributes": {}},
        {"photo_id": "w1", "collection": "world",
         "place_key": "kenya/nairobi/cbd/kicc",
         "place_name": "Kenyatta International Convention Centre",
         "owner_present": None, "attributes": {}}]
    llm_mod.ask_tools = Script([{"calls": [tool_call(
        "count", {"collection": "personal", "place_key": "kicc"})]}])
    out, _ = run_turn(eng, "how many photos do I have at KICC?")
    check(out["text"] == "You have 2 photos at Kenyatta International "
          "Convention Centre.", "count text from data: " + out["text"])

    # compound: facts then grounded text; tampered ids fall back to code
    eng = FakeEngine()
    seed_reply(eng)
    eng.photos = {
        "mtn_001": {"photo_id": "mtn_001", "collection": "world",
                    "viewpoint": "ground_level", "people_count": 4,
                    "record": {"observed": {"caption": "ridge",
                                            "people": "four hikers"},
                               "inferred": {"place": {"name": "Mt Kenya",
                                                      "status": "Candidate"}},
                               "provided": {}}},
        "mtn_002": {"photo_id": "mtn_002", "collection": "world",
                    "viewpoint": "ground_level", "people_count": 1,
                    "record": {"observed": {"caption": "lake",
                                            "people": "one person"},
                               "inferred": {"place": {"name": "Unknown",
                                                      "status": None}},
                               "provided": {}}}}
    llm_mod.ask_tools = Script([
        {"calls": [tool_call("get_photo_facts", {"photo_id": "mtn_001"},
                             "c1"),
                   tool_call("get_photo_facts", {"photo_id": "mtn_002"},
                             "c2")]},
        {"text": "mtn_001 has the most people (4)."}])
    out, _ = run_turn(eng, "which has the most people?")
    check(out["text"] == "mtn_001 has the most people (4).",
          "grounded compound answer kept")
    llm_mod.ask_tools = Script([
        {"calls": [tool_call("get_photo_facts", {"photo_id": "mtn_001"})]},
        {"text": "zzz_999 has the most people (9)."}])
    out, _ = run_turn(eng, "which has the most people?")
    check("zzz_999" not in out["text"] and "mtn_001" in out["text"],
          "invented id falls back to code text")
    check(out["kind"] == "question_answer"
          and out.get("about_photo_id") == "mtn_001",
          "facts fallback binds to the photo")

    # facts with ref: grounded answer binds to the photo + notes the ref
    llm_mod.ask_tools = Script([
        {"calls": [tool_call("get_photo_facts", {"photo_id": "mtn_001",
                                                 "ref": "the second one"})]},
        {"text": "mtn_001 shows a ridge with four hikers."}])
    out, _ = run_turn(eng, "tell me about the second one")
    check(out["kind"] == "question_answer"
          and out["about_photo_id"] == "mtn_001"
          and out["took_to_mean"] == "I took 'the second one' to mean "
          "this photo."
          and out["text"] == "mtn_001 shows a ridge with four hikers.",
          "facts answer binds to the photo")

    # multi-facts: the answer binds to the first photo id it names
    llm_mod.ask_tools = Script([
        {"calls": [tool_call("get_photo_facts", {"photo_id": "mtn_001"}),
                   tool_call("get_photo_facts", {"photo_id": "mtn_002"})]},
        {"text": "mtn_002 shows a lake; mtn_001 shows a ridge."}])
    out, _ = run_turn(eng, "tell me about those two")
    check(out["kind"] == "question_answer"
          and out["about_photo_id"] == "mtn_002",
          "grounded answer binds to first-named photo")

    # malformed tool calls -> JSON fallback path, logged in trace
    eng = FakeEngine()
    eng.sb_rows = [{"photo_id": "p1", "collection": "personal",
                    "place_key": "", "place_name": "", "owner_present": None,
                    "attributes": {}}]
    llm_mod.ask_tools = Script([{"malformed": True}])
    llm_mod.ask = lambda *a, **k: {
        "text": '{"calls": [{"name": "count", "args": {}}]}',
        "provider": "stub", "seconds": 0.2}
    out, _ = run_turn(eng, "how many photos?")
    check(out["text"] == "1 photo in the archive."
          and any(t["step"] == "routed" and "JSON fallback" in t["detail"]
                  for t in out["trace"]), "JSON fallback answers + logged")
    llm_mod.ask = orig_ask

    # chitchat passes; chitchat naming an unknown id is replaced
    eng = FakeEngine()
    llm_mod.ask_tools = Script([{"text": "Hello! What are we looking for?"}])
    out, _ = run_turn(eng, "howdy partner")
    check(out["kind"] == "chat" and out["text"].startswith("Hello"),
          "chitchat passes through")
    llm_mod.ask_tools = Script([{"text": "I found zzz_999 for you."}])
    out, _ = run_turn(eng, "well hello friend")
    check(out["text"].startswith("I can search photos"),
          "chitchat with invented id replaced")

    # clarify tool stores pending; "continue previous" applies it
    eng = FakeEngine()
    eng.state["spec"] = dict(chat_mod.EMPTY_SPEC, query="misty mountains")
    llm_mod.ask_tools = Script([{"calls": [tool_call("clarify", {
        "question": "New search or refine?",
        "options": [{"label": "Continue previous search",
                     "message": "continue previous"},
                    {"label": "Start new search",
                     "message": "new search"}]})]}])
    out, _ = run_turn(eng, "markets")
    check(out["kind"] == "clarify" and len(out["options"]) == 2
          and eng.state["pending"] is not None, "clarify card + pending")
    llm_mod.ask_tools = Script([{"calls": [tool_call(
        "search", {"query": "markets", "topic": "new"})]}])
    out, _ = run_turn(eng, "continue previous")
    check(eng.state["topic"]["id"] == 0
          and eng.search_calls[-1]["query"] == "markets",
          "pending answer forces refine")

    # need_tags short-circuits owner searches
    eng = FakeEngine()
    eng.tagged = 0
    llm_mod.ask_tools = Script([{"calls": [tool_call(
        "search", {"query": "me", "topic": "new", "owner_only": True,
                   "collection": "personal"})]}])
    out, _ = run_turn(eng, "photos of me")
    check(out["kind"] == "need_tags" and not eng.search_calls,
          "need_tags without searching")

    # verify tool: stubbed vision, verdict text + checked rows
    import attributes as attr_mod  # noqa: E402
    orig_vq = attr_mod.verify_question
    attr_mod.verify_question = lambda *a, **k: (
        {"mtn_001": {"verdict": "yes", "reason": "veil visible"}},
        {"calls": [], "cached": 0, "fallback_used": False})
    try:
        eng = FakeEngine()
        seed_reply(eng)
        eng.photos = {"mtn_001": {"file": "data/photos/world/x.jpg",
                                  "photo_id": "mtn_001",
                                  "collection": "world",
                                  "caption": "ridge", "viewpoint": "ground"}}
        llm_mod.ask_tools = Script([{"calls": [tool_call(
            "verify", {"photo_ids": ["mtn_001"],
                       "question": "which show mist?"})]}])
        out, _ = run_turn(eng, "which of these show mist?")
        check("Yes (1): mtn_001 (veil visible)" in out["text"]
              and out["results"][0]["check"]["verdict"] == "yes",
              "verify verdicts into text + rows")
    finally:
        attr_mod.verify_question = orig_vq
finally:
    llm_mod.ask_tools = orig_tools
    llm_mod.ask = orig_ask

# FORCE_TOOLCALL_FAIL short-circuits ask_tools with no network
orig_one = llm_mod._call_tools_one
orig_budget = llm_mod.ensure_budget
orig_flag = llm_mod._env("FORCE_TOOLCALL_FAIL", "false")
import os as os_mod  # noqa: E402
os_mod.environ["FORCE_TOOLCALL_FAIL"] = "true"
llm_mod._call_tools_one = lambda *a, **k: (_ for _ in ()).throw(
    AssertionError("network used"))
llm_mod.ensure_budget = lambda: None
try:
    res = llm_mod.ask_tools([{"role": "user", "content": "hi"}], [])
    check(res["malformed"] is True and res["calls"] == [],
          "forced tool-call failure is malformed")
finally:
    llm_mod._call_tools_one = orig_one
    llm_mod.ensure_budget = orig_budget
    if orig_flag == "false":
        os_mod.environ.pop("FORCE_TOOLCALL_FAIL", None)
    else:
        os_mod.environ["FORCE_TOOLCALL_FAIL"] = orig_flag

check(router_mod.is_rejection("Not this one")
      and router_mod.is_rejection("not this!")
      and not router_mod.is_rejection("not this one, show markets")
      and not router_mod.is_rejection("show me more"), "bare rejection match")

# "not this one" drops the focus photo into rejected before searching
eng = FakeEngine()
eng.state["focus"] = {"photo_id": "mtn_001", "caption": "ridge"}
llm_mod.ask_tools = Script([{"calls": [tool_call(
    "search", {"query": "", "topic": "refine"})]}])
try:
    out, _ = run_turn(eng, "Not this one")
    check(eng.state["rejected"] == {"mtn_001"}, "focus rejected on refine")
finally:
    llm_mod.ask_tools = orig_tools

# reciprocal-rank fusion (pure)
r1 = [{"photo_id": "a", "similarity": 0.9},
      {"photo_id": "b", "similarity": 0.8}]
r2 = [{"photo_id": "b", "similarity": 0.7},
      {"photo_id": "c", "similarity": 0.6}]
fused, multi = chat_mod.fuse_ranked([r1, r2])
check([r["photo_id"] for r in fused] == ["b", "a", "c"]
      and multi == {"b": 2}, "fusion ranks overlap first")

print(f"test_router.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
