"""Hybrid router: one model call per message, code-run tools.

The model receives a COMPACT STATE (never the whole chat history)
plus tool definitions, and either calls tools or answers directly
(chitchat only). Our code runs every tool, validates every argument,
and builds the reply from the tool results: search text comes from
structured results, never from the model. Only ask_photo, compare
and chitchat use model-written text, plus short grounded answers to
compound data questions, which code validates photo-by-photo.

A turn runs at most 3 model rounds: later rounds only fire tools
that depend on earlier results. Native OpenAI-style tool calling is
used; when it comes back malformed or empty we retry once on the
fallback provider (inside llm.ask_tools) and then route once with a
plain JSON-only prompt. The trace records which path ran.
Reasoning content is never used, shown or stored.
"""
import json
import re

import chat as chat_mod
import llm as llm_mod

MAX_ROUNDS = 3
ID_RE = re.compile(r"\b[a-z]+_\d+\b")
CONSTRAINT_ATTRS = ("atmosphere", "light", "time_of_day",
                    "water_visible", "vegetation", "crowd")
FACT_FIELDS = ("caption", "place", "viewpoint", "signs", "things",
               "people", "taken_from", "credit")


def _fn(name, desc, props, required=()):
    return {"type": "function",
            "function": {"name": name, "description": desc,
                         "parameters": {"type": "object",
                                        "properties": props,
                                        "required": list(required)}}}


_CONSTRAINT_SCHEMA = {
    "type": "array",
    "items": {"type": "object",
              "properties": {
                  "attribute": {"type": "string",
                                "enum": list(CONSTRAINT_ATTRS)},
                  "op": {"type": "string", "enum": ["is", "is_not"]},
                  "values": {"type": "array", "items": {}}},
              "required": ["attribute", "op", "values"]}}

TOOL_SCHEMAS = [
    _fn("search", "Find photos. topic=new drops everything and starts a "
        "fresh search; topic=refine changes the current one. Resend the "
        "COMPLETE intended filters every time.",
        {"query": {"type": "string"},
         "alt_queries": {"type": "array", "items": {"type": "string"}},
         "constraints": _CONSTRAINT_SCHEMA,
         "viewpoints": {"type": "array",
                        "items": {"type": "string",
                                  "enum": ["ground_level", "elevated",
                                           "aerial", "interior",
                                           "water_level"]}},
         "max_people": {"type": ["integer", "null"]},
         "must_include": {"type": "array",
                          "items": {"type": "string"}},
         "avoid_terms": {"type": "array", "items": {"type": "string"}},
         "owner_only": {"type": "boolean"},
         "topic": {"type": "string", "enum": ["new", "refine"]},
         "collection": {"type": "string",
                        "enum": ["world", "personal", "both"]}},
        ["topic"]),
    _fn("related", "More photos from one anchor photo: another viewpoint "
        "of the same place (angle) or lookalikes (similar).",
        {"photo_id": {"type": "string"},
         "mode": {"type": "string", "enum": ["angle", "similar"]},
         "collection": {"type": "string",
                        "enum": ["world", "personal", "both"]},
         "ref": {"type": ["string", "null"]}},
        ["photo_id", "mode"]),
    _fn("get_photo_facts", "Stored record facts for one photo (no model "
        "call). Use it to compare photos from data.",
        {"photo_id": {"type": "string"},
         "fields": {"type": "array",
                    "items": {"type": "string",
                              "enum": list(FACT_FIELDS)}}},
        ["photo_id"]),
    _fn("count", "Count photos from data (no model call). place_key is a "
        "place name or key fragment such as KICC.",
        {"collection": {"type": "string",
                        "enum": ["world", "personal", "both"]},
         "place_key": {"type": ["string", "null"]},
         "owner_only": {"type": "boolean"},
         "constraints": _CONSTRAINT_SCHEMA}),
    _fn("verify", "Look at up to 12 photos and answer one yes/no "
        "question per photo. Only for explicit check questions.",
        {"photo_ids": {"type": "array",
                       "items": {"type": "string"}},
         "question": {"type": "string"}},
        ["photo_ids", "question"]),
    _fn("ask_photo", "Answer a question about ONE photo from its stored "
        "record (looks at the image again when the record cannot answer).",
        {"photo_id": {"type": "string"},
         "question": {"type": "string"},
         "ref": {"type": ["string", "null"]}},
        ["photo_id", "question"]),
    _fn("compare", "Compare TWO photos from their stored records.",
        {"photo_a": {"type": "string"},
         "photo_b": {"type": "string"},
         "question": {"type": ["string", "null"]},
         "ref": {"type": ["string", "null"]}},
        ["photo_a", "photo_b"]),
    _fn("clarify", "Ask the user to choose (2-3 options). Use it instead "
        "of guessing: new topic vs refine, or which photo they mean.",
        {"question": {"type": "string"},
         "options": {"type": "array",
                     "items": {"type": "object",
                               "properties": {
                                   "label": {"type": "string"},
                                   "message": {"type": "string"}},
                               "required": ["label", "message"]}}},
        ["question", "options"]),
]

ROUTER_PROMPT = """You route one chat message for Reel, a photo-search assistant for Kenyan photos. You have TOOLS for everything that needs photos or data. Either call tools or answer directly.

STATE (JSON: topic, current search, recent photos as {n, id, label, verdict}, focus photo, rejected count, last user messages):
{state}

TOOLS (call with exact arguments):
- search: find photos. topic "new" = fresh search (drops everything); "refine" = change the current search. Resend the COMPLETE intended filters every time (query, viewpoints, max_people, collection, owner_only, must_include, avoid_terms, constraints) — anything omitted is dropped on refine, except the query which is kept when you pass "". alt_queries: up to 2 short paraphrases. constraints use attribute/op/values with this vocabulary: atmosphere = clear|partly_cloudy|overcast|hazy|misty_or_foggy|rainy|dusty; light = golden_hour|harsh_midday|soft|night_lit|backlit; time_of_day = dawn|morning|midday|afternoon|dusk|night; water_visible = true|false; vegetation = none|sparse|lush; crowd = empty|few|many. Mappings: "misty", "foggy", "with mist" = atmosphere is [misty_or_foggy]; "without mist", "no fog", "not misty" = atmosphere is_not [misty_or_foggy]; "not hazy" = is_not [hazy]; "clear sky" = is [clear]; "cloudy" = is [overcast, partly_cloudy]; "rainy" = is [rainy]; "golden hour" = light is [golden_hour]; "at night" = time_of_day is [night]; "empty" = crowd is [empty]; "crowded" = crowd is [many]; "lush" = vegetation is [lush]; "dry" = vegetation is [none]; "with water" = water_visible is [true]. must_include/avoid_terms are single lowercase words for concrete things ("vegetables", "cars"). "photos of me" = owner_only true with collection personal.
- related: more photos from one anchor: mode "angle" (same place, different viewpoint) or "similar" (looks alike).
- get_photo_facts: stored facts for one photo (caption, place, signs, people...). No model call. Use it to compare photos from data.
- count: count photos from data (collection, place name fragment, owner_only, constraints).
- verify: look at up to 12 photos and answer one yes/no question per photo ("which of these show mist?", "is the sign readable?"). Only for explicit check questions — search already verifies constraints by itself.
- ask_photo: answer a question about ONE photo from its record (it re-looks at the image when the record cannot answer).
- compare: compare TWO photos from their records.
- clarify: ask the user to choose (2-3 options {label, message}). Topic options MUST be {label "Continue previous search", message "continue previous"} and {label "Start new search", message "new search"}. Photo options MUST be {label "<short caption>", message "photo <n>"} using the n from the state.

REFERENCES: "the second one" / "open 3" = latest[n].id. "that mountain" / "the market photo" = the best caption match in the state. Pass the exact id, plus ref = the exact words you resolved ("the second one"), or null when they named the id. Never invent or guess an id: use only ids in the state (or from earlier tool results this turn, which the harness lists). If no photo fits, call clarify. "not this one" = search refine keeping the spec (the harness drops the focus photo).

TURNS: one round is usual. A 2nd/3rd round is allowed ONLY for tools that need earlier results (facts after a search, an answer after facts). After data tools return, answer SHORT from those results, naming photo ids. Answer DIRECTLY (no tools) ONLY for chitchat: greetings, thanks, goodbye, "what can you do". Never describe photos from memory; never write search results as text. Replies are built by code; your text is used only for chitchat and grounded answers."""

JSON_FALLBACK_PROMPT = """You route one chat message for a photo assistant. Reply with ONE JSON object only: {"calls": [{"name": "...", "args": {...}}]} or {"text": "..."} for chitchat only (greetings, thanks, goodbye).
Tools: search(query, alt_queries, constraints[{attribute, op, values}], viewpoints, max_people, must_include, avoid_terms, owner_only, topic new|refine, collection), related(photo_id, mode angle|similar), get_photo_facts(photo_id, fields), count(collection, place_key, owner_only, constraints), verify(photo_ids, question), ask_photo(photo_id, question), compare(photo_a, photo_b, question), clarify(question, options[{label, message}]).
Rules: topic "new" drops everything, "refine" changes the current search (resend COMPLETE filters). Resolve "the second one" to latest[n].id and never invent ids (state ids only). Constraints vocab: atmosphere = clear|partly_cloudy|overcast|hazy|misty_or_foggy|rainy|dusty; light = golden_hour|harsh_midday|soft|night_lit|backlit; time_of_day = dawn|morning|midday|afternoon|dusk|night; water_visible = true|false; vegetation = none|sparse|lush; crowd = empty|few|many. "misty/with mist" = atmosphere is [misty_or_foggy]; "without mist/no fog" = is_not. Clarify (don't guess) when unsure: topic options are {Continue previous search / continue previous} and {Start new search / new search}; photo options are {<caption> / photo <n>}.
STATE:
{state}
USER:
{message}"""


def build_compact_state(engine):
    """Compact router state from the session (never the history)."""
    st = engine.state
    replies = (st.get("replies") or [])[-3:]

    def pack(rep):
        return [{"n": n, "id": p.get("id"), "label": p.get("label"),
                 "verdict": p.get("verdict")}
                for n, p in enumerate(rep.get("photos") or [], 1)]

    pads = [[], [], []]
    for i, rep in enumerate(replies):
        pads[2 - (len(replies) - 1 - i)] = pack(rep)
    prev2, prev1, latest = pads
    focus = st.get("focus") or {}
    return {
        "topic_id": (st.get("topic") or {}).get("id", 0),
        "topic_label": (st.get("topic") or {}).get("label", ""),
        "spec": st.get("spec") or {},
        "latest": latest, "prev1": prev1, "prev2": prev2,
        "focus": ({"id": focus.get("photo_id"),
                   "caption": (focus.get("caption") or "")[:80]}
                  if focus.get("photo_id") else None),
        "rejected_count": len(st.get("rejected") or set()),
        "recent_user": (st.get("user_texts") or [])[-3:],
    }


def state_ids(cstate):
    """Every photo id the model may use (pure)."""
    ids = set()
    for rep in (cstate.get("latest") or [], cstate.get("prev1") or [],
                cstate.get("prev2") or []):
        for p in rep:
            if p.get("id"):
                ids.add(p["id"])
    if (cstate.get("focus") or {}).get("id"):
        ids.add(cstate["focus"]["id"])
    return ids


class _Terminal(Exception):
    """Raised to end the turn now with a finished response dict."""

    def __init__(self, out):
        super().__init__("terminal reply")
        self.out = out


def _strip_prefixes(message, forced_topic=None, forced_about=None):
    """Button-style prefixes to forced values (pure).

    "new search: X" / "refine: X" force the search topic; "about
    <id>: Q" forces the photo question tools answer. A bare prefix
    with nothing after it is left alone for the model.
    """
    m = re.match(r"\s*(new search|refine)\s*:\s*(.+)$", message, re.I | re.S)
    if m and not forced_topic:
        forced_topic = "new" if m.group(1).lower().startswith("new") else "refine"
        return forced_topic, forced_about, m.group(2).strip()
    m = re.match(r"\s*about\s+([a-z]+_\d+)\s*:\s*(.+)$", message, re.I | re.S)
    if m and not forced_about:
        return forced_topic, m.group(1), m.group(2).strip()
    return forced_topic, forced_about, message


ORDINALS = ("first", "second", "third", "fourth", "fifth")


def _pending_options(clarify_options, cstate, orig_message):
    """Model clarify options to matchable pending options (pure).

    Each becomes {keys, forced_topic?, forced_about?, message}:
    topic shortcuts force the topic on the ORIGINAL message, photo
    shortcuts force the photo, anything else reprocesses as a new
    message. Keys accept the exact message, the label, ordinals and
    photo numbers so typed replies match button taps.
    """
    latest = cstate.get("latest") or []
    by_n = {p.get("n"): p.get("id") for p in latest if p.get("id")}
    pending = []
    for i, o in enumerate(clarify_options or []):
        if not isinstance(o, dict):
            continue
        label = str(o.get("label") or "")
        msg = str(o.get("message") or "")
        keys = {msg.strip().lower(), label.strip().lower()} - {""}
        forced_topic, forced_about, use_msg = None, None, msg
        low = msg.strip().lower()
        if low in ("continue previous", "keep refining"):
            forced_topic, use_msg = "refine", orig_message
            keys |= {"continue", "previous", "refine", "keep refining"}
        elif low in ("new search", "start new"):
            forced_topic, use_msg = "new", orig_message
            keys |= {"new", "new search", "start new"}
        else:
            ids = ID_RE.findall(low)
            state_hit = [x for x in ids if x in state_ids(cstate)]
            if state_hit:
                forced_about, use_msg = state_hit[0], orig_message
                keys.add(state_hit[0])
            else:
                m = re.fullmatch(r"photo\s+(\d+)", low)
                if m and int(m.group(1)) in by_n:
                    forced_about, use_msg = by_n[int(m.group(1))], orig_message
                    n = int(m.group(1))
                    keys |= {f"photo {n}", f"number {n}", str(n)}
                    if n <= len(ORDINALS):
                        keys.add(ORDINALS[n - 1])
        if not use_msg.strip():
            continue
        pending.append({"keys": sorted(keys), "forced_topic": forced_topic,
                        "forced_about": forced_about, "message": use_msg})
    return pending


def _apply_pending(state, message):
    """Match a reply against pending clarify options (pure side).

    Returns (forced_topic, forced_about, message). Pending clears
    after one turn whether it matched or not.
    """
    pending = state.get("pending") or None
    state["pending"] = None
    if not pending:
        return None, None, message
    norm = message.strip().lower()
    for opt in pending.get("options") or []:
        for k in opt.get("keys") or []:
            if k and (k == norm or k in norm or norm in k):
                return (opt.get("forced_topic"), opt.get("forced_about"),
                        opt.get("message") or message)
    return None, None, message


def _unknown_ids(text, seen):
    """Photo ids in text that are not in the allowed set (pure)."""
    return sorted(set(ID_RE.findall(text or "")) - set(seen))


def _auto_clarify(ctx, offender=None):
    """Terminal 'which photo?' card from the latest reply (pure side)."""
    latest = ctx["cstate"].get("latest") or []
    options, pending = [], []
    for p in latest[:5]:
        if not p.get("id"):
            continue
        options.append({"label": (p.get("label") or p["id"])[:40],
                        "message": f"photo {p.get('n')}"})
        keys = {f"photo {p.get('n')}", str(p.get("n") or ""),
                (p.get("label") or "").lower(), p["id"]}
        if p.get("n") and p["n"] <= len(ORDINALS):
            keys.add(ORDINALS[p["n"] - 1])
        pending.append({"keys": sorted(keys - {""}),
                        "forced_topic": None, "forced_about": p["id"],
                        "message": ctx["message"]})
    ctx["engine"].state["pending"] = {"options": pending} if pending else None
    text = "Which photo do you mean?"
    if offender:
        text = f"I don't have a photo called {offender}. " + text
    if options:
        text += "\n\n" + "\n".join(f"- {o['label']} (reply '{o['message']}')"
                                   for o in options)
    ctx["options"] = options
    ctx["trace"].append({"step": "asked",
                          "detail": "The photo reference was not in the "
                          "recent photos, so I asked which one."})
    return {"text": text, "results": [], "kind": "clarify"}


def _check_id(pid, ctx):
    """Validated photo id, or an auto-clarify terminal."""
    if isinstance(pid, str) and (pid in ctx["allowed"] or pid in ctx["seen"]):
        return pid
    raise _Terminal(_auto_clarify(ctx, pid if isinstance(pid, str) else None))


def _tool_search(engine, args, ctx):
    from attributes import normalize_constraints
    st = engine.state
    topic = args.get("topic")
    if ctx["forced_topic"]:
        topic = ctx["forced_topic"]
    current = st.get("spec") or {}
    if topic not in ("new", "refine"):
        topic = "new" if not current.get("query") else "refine"
    if topic == "new":
        spec = dict(chat_mod.EMPTY_SPEC)
        st["topic"] = {"id": (st.get("topic") or {}).get("id", 0) + 1,
                       "label": (args.get("query") or ctx["message"])[:48]}
        st["rejected"] = set()
        new_topic = True
    else:
        spec = {k: (list(v) if isinstance(v, list) else v)
                for k, v in current.items()}
        new_topic = False
    if isinstance(args.get("query"), str) and args["query"].strip():
        spec["query"] = args["query"].strip()
    elif topic == "new" and not spec["query"]:
        spec["query"] = ctx["message"]
    alts = [q.strip() for q in (args.get("alt_queries") or [])
            if isinstance(q, str) and q.strip()][:2]
    spec["alt_queries"] = alts
    if isinstance(args.get("constraints"), list):
        spec["constraints"] = normalize_constraints(args["constraints"])
    elif topic == "new":
        spec["constraints"] = []
    if isinstance(args.get("viewpoints"), list):
        spec["viewpoints"] = [v for v in args["viewpoints"]
                              if v in chat_mod.VIEWPOINTS]
    elif topic == "new":
        spec["viewpoints"] = []
    if "max_people" in args:
        v = args["max_people"]
        if v is None or (isinstance(v, int) and not isinstance(v, bool)
                         and v >= 0):
            spec["max_people"] = v
    if isinstance(args.get("must_include"), list):
        spec["must_include"] = [str(w).lower() for w in args["must_include"]
                                if str(w).strip()][:10]
    elif topic == "new":
        spec["must_include"] = []
    if isinstance(args.get("avoid_terms"), list):
        spec["avoid_terms"] = [str(w).lower() for w in args["avoid_terms"]
                               if str(w).strip()][:10]
    elif topic == "new":
        spec["avoid_terms"] = []
    if isinstance(args.get("owner_only"), bool):
        spec["owner_only"] = args["owner_only"]
    if args.get("collection") in ("world", "personal", "both"):
        spec["collection"] = args["collection"]
    if spec.get("owner_only"):
        spec["collection"] = "personal"
    st["spec"] = spec
    if spec.get("owner_only") and engine.tagged_count() == 0:
        ctx["trace"].append(
            {"step": "answered",
             "detail": "No tagged photos yet, so I pointed at the tagging page."})
        return ({"matched": [], "note": "need_tags"}, [],
                {"text": chat_mod.NO_TAGS_TEXT, "results": [],
                 "kind": "need_tags"})
    rows, note, sub = engine.search(spec, st.get("rejected") or set())
    ctx["trace"].extend(sub)
    ctx["seen"] |= {r["photo_id"] for r in rows if r.get("photo_id")}
    ctx["last_rows"] = rows
    matched = any((r.get("check") or {}).get("verdict") == "yes" for r in rows)
    kind = "no_strong_match" if (note and not matched) else "ok"
    label = (spec["query"] or "")[:32].strip().capitalize() or "Photos"
    if spec.get("constraints"):
        from attributes import constraint_display
        label += " / " + ", ".join(constraint_display(c)
                                   for c in spec["constraints"])
    ctx["label"] = label
    ctx["topic"] = {"id": st["topic"]["id"], "label": st["topic"]["label"],
                    "new": new_topic}
    model_rows = [{"n": n, "id": r["photo_id"],
                   "caption": (r.get("caption") or "")[:120]}
                  for n, r in enumerate(rows, 1)]
    steps = [(t["step"], t["detail"]) for t in sub]
    return ({"matched": model_rows, "note": note},
            steps,
            {"text": note or "Here is what I found:", "results": rows,
             "kind": kind})


def _tool_related(engine, args, ctx):
    pid = ctx["forced_about"] or args.get("photo_id")
    pid = _check_id(pid, ctx)
    mode = args.get("mode")
    angle_mode = (mode == "angle") if mode in ("angle", "similar") else False
    spec = dict(engine.state.get("spec") or {})
    if args.get("collection") in ("world", "personal", "both"):
        spec["collection"] = args["collection"]
    rows, note, sub = engine.related(
        pid, spec, engine.state.get("rejected") or set(), angle_mode)
    ctx["trace"].extend(sub)
    ctx["seen"] |= {r["photo_id"] for r in rows if r.get("photo_id")}
    ctx["last_rows"] = rows
    if isinstance(args.get("ref"), str) and args["ref"].strip():
        ctx["took"] = (f"I took '{args['ref'].strip()[:60]}' to mean "
                       f"this photo.")
    label = ("other angles of" if angle_mode else "photos like") + f" {pid}"
    ctx["label"] = label
    kind = "no_other_angle" if note else "ok"
    model_rows = [{"n": n, "id": r["photo_id"],
                   "caption": (r.get("caption") or "")[:120]}
                  for n, r in enumerate(rows, 1)]
    steps = [(t["step"], t["detail"]) for t in sub]
    word = "other angles of" if angle_mode else "photos like"
    return ({"matched": model_rows, "note": note},
            steps,
            {"text": note or f"Showing {word} {pid}:", "results": rows,
             "kind": kind})


def _record_facts(rec, row, fields):
    """Small defensive fact dict from a stored record (pure)."""
    obs, inf = rec.get("observed") or {}, rec.get("inferred") or {}
    facts = {}
    if "caption" in fields:
        facts["caption"] = obs.get("caption")
    if "place" in fields:
        place = inf.get("place") or {}
        facts["place"] = {"name": place.get("name"),
                          "status": place.get("status")}
    if "viewpoint" in fields:
        facts["viewpoint"] = row.get("viewpoint")
    if "signs" in fields:
        seen = obs.get("visible_text") or []
        facts["signs"] = [{"text": (s.get("text") or "")[:80],
                           "legibility": s.get("legibility")}
                          for s in seen[:5] if isinstance(s, dict)]
    if "things" in fields:
        ents = obs.get("entities") or []
        facts["things"] = [str(e.get("label") or e)[:40] for e in ents[:8]]
    if "people" in fields:
        facts["people_count"] = row.get("people_count")
        facts["people"] = str(obs.get("people") or "")[:200] or None
    if "taken_from" in fields:
        taken = inf.get("taken_from") or {}
        facts["taken_from"] = taken.get("name")
    if "credit" in fields:
        prov = rec.get("provided") or {}
        facts["credit"] = ({"author": prov.get("author"),
                            "license": prov.get("license")}
                           if row.get("collection") == "world" else None)
    return facts


def _tool_facts(engine, args, ctx):
    pid = ctx["forced_about"] or args.get("photo_id")
    pid = _check_id(pid, ctx)
    fields = [f for f in (args.get("fields") or []) if f in FACT_FIELDS]
    if not fields:
        fields = ["caption", "place", "viewpoint", "signs", "things",
                  "people", "taken_from"]
    row = engine.fetch_photo(
        pid, "photo_id,collection,viewpoint,people_count,record")
    if not row or not isinstance(row.get("record"), dict):
        return ({"photo_id": pid, "error": "photo not found"}, [], None)
    facts = _record_facts(row["record"], row, fields)
    detail = f"Read the stored facts for {pid}."
    ctx["trace"].append({"step": "facts", "detail": detail})
    return ({"photo_id": pid, "facts": facts}, [("facts", detail)], None)


def _tool_count(engine, args, ctx):
    from attributes import normalize_constraints
    coll = args.get("collection")
    if coll not in ("world", "personal", "both"):
        coll = "both"
    frag = args.get("place_key")
    frag = frag.strip().lower() if isinstance(frag, str) and frag.strip() else None
    owner_only = args.get("owner_only") is True
    cons = normalize_constraints(args.get("constraints"))
    try:
        rows = (engine.sb.table("photos")
                .select("photo_id,collection,place_key,place_name,"
                        "owner_present,attributes").execute().data or [])
    except Exception as e:
        return ({"error": f"count failed: {e}"}, [], None)
    hits = []
    for r in rows:
        if coll != "both" and r.get("collection") != coll:
            continue
        if owner_only and r.get("owner_present") is not True:
            continue
        if frag and frag not in str(r.get("place_key") or "").lower() \
                and frag not in str(r.get("place_name") or "").lower():
            continue
        ok = True
        attrs = r.get("attributes") if isinstance(r.get("attributes"), dict) else {}
        for c in cons:
            got = (attrs.get(c["attribute"]) or {}).get("value")
            if c["op"] == "is":
                if got not in (c.get("values") or []):
                    ok = False
            elif got is not None and got != "unknown" \
                    and got in (c.get("values") or []):
                ok = False
        if ok:
            hits.append(r)
    n = len(hits)
    place = ""
    if frag:
        names = [r.get("place_name") for r in hits if r.get("place_name")]
        label = max(set(names), key=names.count) if names else frag
        place = f" at {label}"
    plural = "s" if n != 1 else ""
    if coll == "personal" or owner_only:
        text = f"You have {n} photo{plural}{place}."
    elif coll == "world":
        text = f"{n} world photo{plural}{place}."
    else:
        text = f"{n} photo{plural}{place} in the archive."
    if n == 0:
        text = "No photos match that."
    detail = f"Counted {n} photo{plural}{place}."
    ctx["trace"].append({"step": "counted", "detail": detail})
    return ({"count": n, "text": text}, [("counted", detail)],
            {"text": text, "results": [], "kind": "chat"})


def _tool_verify(engine, args, ctx):
    from attributes import verify_question
    pids = [p for p in (args.get("photo_ids") or []) if isinstance(p, str)][:12]
    if not pids:
        return ({"error": "photo_ids must be a non-empty list"}, [], None)
    question = args.get("question")
    if not isinstance(question, str) or not question.strip():
        return ({"error": "question must be a non-empty string"}, [], None)
    for pid in pids:
        _check_id(pid, ctx)
    files = {}
    for pid in pids:
        row = engine.fetch_photo(pid, "file")
        files[pid] = (row or {}).get("file")

    def load_bytes(pid):
        from pathlib import Path
        p = Path(chat_mod.ROOT) / str(files.get(pid) or "")
        if not p.is_file():
            return None
        return (p.read_bytes(), "image/png" if p.suffix.lower() == ".png"
                else "image/jpeg")

    verdicts, info = verify_question(
        pids, question.strip(), load_bytes=load_bytes, trace=ctx["trace"],
        session_id=engine.session_id)
    engine.turn_llm.extend(info.get("calls") or [])
    if info.get("fallback_used"):
        ctx["trace"].append({"step": "checked",
                              "detail": "The primary provider refused images, "
                              "so the fallback checked the photos."})
    yes = [p for p in pids if verdicts[p]["verdict"] == "yes"]
    no = [p for p in pids if verdicts[p]["verdict"] == "no"]
    unsure = [p for p in pids if verdicts[p]["verdict"] == "unsure"]
    detail = (f"Looked at {len(pids)} photos ({info.get('cached', 0)} from "
              f"the cache): {len(yes)} yes, {len(no)} no, "
              f"{len(unsure)} unsure.")
    ctx["trace"].append({"step": "checked", "detail": detail})
    bits = []
    for group, word in ((yes, "Yes"), (no, "No"), (unsure, "Not sure")):
        if group:
            names = ", ".join(f"{p} ({verdicts[p]['reason']})"
                              for p in group)
            bits.append(f"{word} ({len(group)}): {names}")
    text = " ".join(bits) if bits else "No photos to check."
    rows = []
    for pid in yes + unsure:
        row = engine.fetch_photo(
            pid, "photo_id,collection,file,caption,viewpoint")
        if row:
            row["check"] = {"verdict": verdicts[pid]["verdict"],
                            "reason": verdicts[pid]["reason"],
                            "detail": [{"check": question.strip()[:80],
                                        "status": verdicts[pid]["verdict"],
                                        "reason": verdicts[pid]["reason"]}]}
            rows.append(row)
    kind = "ok" if rows else "chat"
    if not rows:
        text = f"None of them show it. {text}"
    ctx["label"] = f"Check: {question.strip()[:40]}"
    return ({"verdicts": verdicts}, [("checked", detail)],
            {"text": text, "results": rows, "kind": kind})


def _tool_ask(engine, args, ctx):
    from api import AskRequest, ask as api_ask  # lazy: api imports chat
    pid = ctx["forced_about"] or args.get("photo_id")
    pid = _check_id(pid, ctx)
    question = args.get("question")
    if not isinstance(question, str) or not question.strip():
        return ({"error": "question must be a non-empty string"}, [], None)
    try:
        out = api_ask(AskRequest(photo_id=pid, question=question.strip(),
                                 session_id=engine.session_id))
    except llm_mod.LLMBudgetSpent:
        raise
    except Exception as e:
        status = getattr(e, "status_code", None)
        if status == 429:
            raise llm_mod.LLMBudgetSpent(str(e))
        return ({"error": f"ask failed: {e}"}, [], None)
    ctx["trace"].extend(out.get("trace") or [])
    ctx["about"] = pid
    if isinstance(args.get("ref"), str) and args["ref"].strip():
        ctx["took"] = (f"I took '{args['ref'].strip()[:60]}' to mean "
                       "this photo.")
    text = out.get("answer") or "I cannot tell from the stored annotation."
    if out.get("source") == "image" and out.get("note"):
        text += "\n\n" + out["note"]
    steps = [(t.get("step", "checked"), t.get("detail", ""))[:2]
             for t in (out.get("trace") or [])]
    return ({"photo_id": pid, "answer": text},
            steps,
            {"text": text, "results": [], "kind": "question_answer",
             "_about": pid})


def _tool_compare(engine, args, ctx):
    from api import CompareRequest  # lazy: api imports chat
    from api import compare as api_compare
    pid_a = _check_id(args.get("photo_a"), ctx)
    pid_b = _check_id(args.get("photo_b"), ctx)
    if pid_a == pid_b:
        return ({"error": "same photo"}, [],
                {"text": "Those are the same photo.",
                 "results": [], "kind": "chat"})
    question = args.get("question")
    if question is not None and (not isinstance(question, str)
                                 or not question.strip()):
        question = None
    try:
        out = api_compare(CompareRequest(photo_a=pid_a, photo_b=pid_b,
                                         question=question))
    except llm_mod.LLMBudgetSpent:
        raise
    except Exception as e:
        status = getattr(e, "status_code", None)
        if status == 429:
            raise llm_mod.LLMBudgetSpent(str(e))
        return ({"error": f"compare failed: {e}"}, [], None)
    ctx["trace"].extend(out.get("trace") or [])
    ctx["about"] = pid_a
    ctx["abouts"] = [pid_a, pid_b]
    ctx["differences"] = out.get("differences") or []
    if isinstance(args.get("ref"), str) and args["ref"].strip():
        ctx["took"] = (f"I took '{args['ref'].strip()[:60]}' to mean "
                       "these photos.")
    rows = []
    for pid in (pid_a, pid_b):
        row = engine.fetch_photo(
            pid, "photo_id,collection,file,caption,viewpoint")
        if row:
            rows.append(row)
    text = out.get("answer") or "The records do not state a clear difference."
    steps = [(t.get("step", "checked"), t.get("detail", ""))[:2]
             for t in (out.get("trace") or [])]
    return ({"photo_a": pid_a, "photo_b": pid_b, "answer": text},
            steps,
            {"text": text, "results": rows, "kind": "compare",
             "_abouts": [pid_a, pid_b]})


def _tool_clarify(engine, args, ctx):
    question = args.get("question")
    options = args.get("options")
    if not isinstance(question, str) or not question.strip() \
            or not isinstance(options, list) or len(options) < 2:
        return ({"error": "clarify needs a question and 2-3 options"},
                [], None)
    options = [o for o in options[:3]
               if isinstance(o, dict) and str(o.get("label") or "").strip()
               and str(o.get("message") or "").strip()]
    if len(options) < 2:
        return ({"error": "clarify needs a question and 2+ valid options"},
                [], None)
    options = [{"label": str(o["label"])[:60],
                "message": str(o["message"])[:200]} for o in options]
    engine.state["pending"] = {
        "options": _pending_options(options, ctx["cstate"], ctx["message"])}
    text = (question.strip() + "\n\n"
            + "\n".join(f"- {o['label']} (reply '{o['message']}')"
                        for o in options))
    ctx["options"] = options
    ctx["trace"].append({"step": "asked",
                          "detail": "The message was ambiguous, so I asked "
                          "which was meant."})
    return ({"asked": question.strip()},
            [],
            {"text": text, "results": [], "kind": "clarify"})


_TOOLS = {"search": _tool_search, "related": _tool_related,
          "get_photo_facts": _tool_facts, "count": _tool_count,
          "verify": _tool_verify, "ask_photo": _tool_ask,
          "compare": _tool_compare, "clarify": _tool_clarify}
_TERMINAL_NAMES = ("search", "related", "count", "verify", "ask_photo",
                   "compare", "clarify")

_UNDERSTOOD = {"search": "Searching for that.",
               "related": "Finding related photos.",
               "get_photo_facts": "Reading the stored facts.",
               "count": "Counting from the data.",
               "verify": "Checking the actual photos.",
               "ask_photo": "Looking up that photo.",
               "compare": "Comparing those photos.",
               "clarify": "That was ambiguous, so I asked."}


def _combine_terminal(replies):
    """One reply from same-round terminal answers (pure side).

    replies is [(name, out)]; clarify wins, asks merge with
    headers, otherwise the first reply stands.
    """
    for name, out in replies:
        if name == "clarify":
            return out
        if name == "search" and out.get("kind") == "need_tags":
            return out
    asks = [(n, o) for n, o in replies if n in ("ask_photo", "compare")]
    if asks and len(asks) == len(replies):
        parts = []
        for _n, o in asks:
            tag = o.get("_about") or (o.get("_abouts") or [""])[0]
            parts.append(f"About {tag}: {o['text']}" if tag else o["text"])
        merged = {"text": "\n\n".join(parts), "results": [],
                  "kind": "question_answer"}
        for _n, o in asks:
            merged["results"].extend(o.get("results") or [])
            if o.get("_abouts"):
                merged["_abouts"] = o["_abouts"]
        return merged
    return replies[0][1]


def _code_summary(ctx, tool_data):
    """Last-resort reply from tool results when the model won't land."""
    rows = ctx.get("last_rows") or []
    if rows:
        return {"text": "Here is what I found:", "results": rows,
                "kind": "ok"}
    facts = tool_data.get("get_photo_facts") or []
    facts = [f for f in facts if f.get("facts")]
    if facts:
        lines = []
        for f in facts:
            known = ", ".join(f"{k}: {v}" for k, v in f["facts"].items()
                              if v not in (None, "", {}, []))
            lines.append(f"- {f['photo_id']}: {known[:160]}")
        return {"text": "From the records:\n" + "\n".join(lines),
                "results": [], "kind": "chat"}
    if tool_data.get("verify"):
        return {"text": "I looked but could not put that together. "
                "Try rephrasing.",
                "results": [], "kind": "chat"}
    return {"text": "I couldn't put that together. Try rephrasing.",
            "results": [], "kind": "chat"}


def _tool_msg(call_id, result):
    return {"role": "tool", "tool_call_id": call_id or "json",
            "content": json.dumps(result, ensure_ascii=False)[:6000]}


def _assistant_msg(text, calls):
    return {"role": "assistant", "content": text or None,
            "tool_calls": [
                {"id": c.get("id") or f"call_{i}",
                 "type": "function",
                 "function": {"name": c.get("name", ""),
                              "arguments": json.dumps(c.get("args") or {})}}
                for i, c in enumerate(calls)]}


def _run_calls(engine, ctx, calls, tool_data):
    """Execute one round's calls. Returns (steps, answers, terminal).

    Terminal tools end the turn only when every call in the round
    is terminal; mixed rounds feed back for another round.
    """
    steps, replies = [], []
    messages = []
    for tc in calls:
        name, args = tc.get("name"), tc.get("args")
        if name not in _TOOLS or not isinstance(args, dict):
            messages.append(_tool_msg(
                tc.get("id"), {"error": f"unknown tool '{name}'"}))
            continue
        ctx["tools_used"].append(name)
        try:
            result, tsteps, reply = _TOOLS[name](engine, args, ctx)
        except _Terminal:
            raise
        except llm_mod.LLMBudgetSpent:
            raise
        except Exception as e:
            result, tsteps, reply = ({"error": f"{name} failed: {e}"},
                                     [], None)
        tool_data.setdefault(name, []).append(result)
        steps.extend(tsteps)
        messages.append(_tool_msg(tc.get("id"), result))
        if reply is not None and name in _TERMINAL_NAMES:
            replies.append((name, reply))
    terminal = None
    if replies and len(replies) == len(
            [tc for tc in calls if tc.get("name") in _TOOLS]):
        terminal = _combine_terminal(replies)
    return steps, messages, terminal


def _rounds(engine, ctx, messages):
    """Route loop (generator): yields steps, returns the response."""
    tool_data = {}
    understood = None
    for rnd in range(1, MAX_ROUNDS + 1):
        ctx["rounds"] = rnd
        res = llm_mod.ask_tools(messages, TOOL_SCHEMAS, purpose="route",
                                session_id=engine.session_id)
        engine.turn_llm.append({"provider": res.get("provider"),
                                "seconds": res.get("seconds") or 0})
        if res.get("fallback_used"):
            ctx["used_fallback"] = True
        if res.get("malformed"):
            ctx["path"] = "json"
            out = yield from _json_fallback(engine, ctx, messages)
            return out
        calls = res.get("calls") or []
        text = (res.get("text") or "").strip()
        if understood is None:
            understood = (_UNDERSTOOD.get(calls[0]["name"])
                          if calls else "That was small talk, so I just replied.")
            ctx["trace"].append({"step": "understood", "detail": understood})
            ctx["understood_sent"] = True
            yield ("step", "understood", understood)
        if not calls:
            if rnd == 1 and not ctx["tools_used"]:
                return _chitchat(ctx, text)
            return _grounded(ctx, text, tool_data)
        messages.append(_assistant_msg(text, calls))
        steps, answers, terminal = _run_calls(engine, ctx, calls, tool_data)
        messages.extend(answers)
        for name, detail in steps:
            yield ("step", name, detail)
        if terminal is not None:
            return terminal
    return _code_summary(ctx, tool_data)


def _json_fallback(engine, ctx, messages):
    """Single plain-JSON routing attempt (generator). Terminal: no loops."""
    user_text = ""
    for m in messages:
        if m.get("role") == "user":
            user_text = m.get("content") or ""
    prompt = (JSON_FALLBACK_PROMPT
              .replace("{state}", json.dumps(ctx["cstate"], ensure_ascii=False))
              .replace("{message}", user_text))
    try:
        res = llm_mod.ask(prompt, purpose="route",
                          session_id=engine.session_id)
    except llm_mod.LLMBudgetSpent:
        raise
    except Exception:
        raise _Terminal({"text": "I couldn't work out what to do with "
                         "that. Try rephrasing.",
                         "results": [], "kind": "chat"})
    engine.turn_llm.append({"provider": res.get("provider"),
                            "seconds": res.get("seconds") or 0})
    try:
        data = chat_mod.extract_json(res.get("text"))
    except (ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    calls = [c for c in (data.get("calls") or [])
             if isinstance(c, dict) and c.get("name") in _TOOLS
             and isinstance(c.get("args"), dict)]
    if calls and not ctx.get("understood_sent"):
        first = calls[0]["name"]
        detail = _UNDERSTOOD.get(first, "Working out what you asked for.")
        ctx["trace"].append({"step": "understood", "detail": detail})
        ctx["understood_sent"] = True
        yield ("step", "understood", detail)
    tool_data = {}
    steps, _answers, terminal = _run_calls(engine, ctx, calls, tool_data)
    for name, detail in steps:
        yield ("step", name, detail)
    if terminal is not None:
        return terminal
    text = data.get("text") if isinstance(data.get("text"), str) else ""
    if text.strip() and not calls:
        return _chitchat(ctx, text.strip())
    if text.strip():
        return _grounded(ctx, text.strip(), tool_data)
    return _code_summary(ctx, tool_data)


def _chitchat(ctx, text):
    """Round-1 direct text (chitchat only), id-validated."""
    if not text or _unknown_ids(text, ctx["seen"]):
        text = "I can search photos — describe what you're looking for."
    return {"text": text, "results": [], "kind": "chat"}


def _grounded(ctx, text, tool_data):
    """Post-tool model text, validated against seen ids."""
    if not text or _unknown_ids(text, ctx["seen"]):
        return _code_summary(ctx, tool_data)
    return {"text": text, "results": ctx.get("last_rows") or [],
            "kind": "ok" if ctx.get("last_rows") else "chat"}


def _finish(ctx, out):
    """Attach trace extras + routed/answered entries (pure side)."""
    for key in ("label", "topic", "options"):
        if ctx.get(key) is not None:
            out[key] = ctx[key]
    if ctx.get("about"):
        out["about_photo_id"] = ctx["about"]
    if ctx.get("abouts"):
        out["about_photo_ids"] = ctx["abouts"]
    if ctx.get("took"):
        out["took_to_mean"] = ctx["took"]
    if ctx.get("differences"):
        out["differences"] = ctx["differences"]
    out.pop("_about", None)
    out.pop("_abouts", None)
    tools = ", ".join(ctx["tools_used"]) or "none"
    via = "the JSON fallback" if ctx["path"] == "json" else "native"
    if ctx["path"] == "native" and ctx.get("used_fallback"):
        via = "native with the fallback provider"
    extra = " (chitchat)" if tools == "none" else ""
    ctx["trace"].append({"step": "routed",
                          "detail": f"tools: {tools} in {ctx['rounds']} "
                          f"round(s) via {via}{extra}."})
    kind = out.get("kind")
    n = len(out.get("results") or [])
    if kind == "need_tags":
        answered = "No tagged photos yet, so I pointed at the tagging page."
    elif kind == "clarify":
        answered = "Asked which was meant."
    elif kind == "question_answer":
        answered = f"Answered about {ctx.get('about')}."
    elif kind == "compare":
        answered = "Compared the two photos."
    elif kind in ("no_strong_match", "no_other_angle"):
        answered = (f"Nothing clearly matched; showing the {n} "
                    "closest photos.")
    elif kind == "chat":
        answered = "Replied."
    else:
        answered = f"Showing {n} photos."
    ctx["trace"].append({"step": "answered", "detail": answered})
    out["trace"] = ctx["trace"]
    return out


def route_stream(engine, message):
    """One routed turn (generator): steps, then ("result", response)."""
    st = engine.state
    st.setdefault("topic", {"id": 0, "label": ""})
    st.setdefault("replies", [])
    st.setdefault("user_texts", [])
    st.setdefault("pending", None)
    m = re.fullmatch(r"\s*open\s+(\d)\s*", message, re.I)
    if m and st.get("last") and 1 <= int(m.group(1)) <= len(st["last"]):
        st["focus"] = st["last"][int(m.group(1)) - 1]
        detail = f"Focused on result {m.group(1)}: {st['focus']['photo_id']}."
        trace = [{"step": "understood", "detail": detail},
                 {"step": "answered", "detail": detail}]
        yield ("step", "understood", detail)
        yield ("step", "wrote", "Reply ready.")
        yield ("result", {"text": f"Focused on {st['focus']['photo_id']}: "
                          f"{st['focus']['caption']}",
                          "results": [], "kind": "ok", "trace": trace,
                          "topic": dict(st["topic"], new=False)})
        return
    forced_topic, forced_about, message = _apply_pending(st, message)
    forced_topic, forced_about, message = _strip_prefixes(
        message, forced_topic, forced_about)
    soc = chat_mod.social_reply(message)
    if soc is not None:
        detail = "That message was small talk, not a search, so I just replied."
        trace = [{"step": "understood", "detail": detail},
                 {"step": "routed",
                  "detail": "tools: none in 0 rounds (small talk)."},
                 {"step": "answered", "detail": "Replied."}]
        yield ("step", "understood", detail)
        yield ("step", "wrote", "Reply ready.")
        yield ("result", {"text": soc, "results": [], "kind": "chat",
                          "trace": trace,
                          "topic": dict(st["topic"], new=False)})
        return
    st["user_texts"] = (st.get("user_texts") or [])[-2:] + [message]
    cstate = build_compact_state(engine)
    notes = []
    if forced_topic:
        notes.append(f"(Harness note: topic={forced_topic} is forced; "
                     "pass it in search.)")
    if forced_about:
        notes.append(f"(Harness note: the user means photo {forced_about}; "
                     "use that id in photo tools.)")
    user_content = message + ("\n" + "\n".join(notes) if notes else "")
    messages = [{"role": "system",
                 "content": ROUTER_PROMPT.replace(
                     "{state}", json.dumps(cstate, ensure_ascii=False))},
                {"role": "user", "content": user_content}]
    ctx = {"engine": engine, "cstate": cstate, "message": message,
           "allowed": state_ids(cstate), "seen": set(state_ids(cstate)),
           "trace": [], "tools_used": [], "rounds": 0, "path": "native",
           "used_fallback": False, "forced_topic": forced_topic,
           "forced_about": forced_about, "last_rows": [],
           "label": None, "topic": None, "options": None, "about": None,
           "abouts": None, "took": None, "differences": None}
    try:
        out = yield from _rounds(engine, ctx, messages)
    except _Terminal as t:
        out = t.out
    out = _finish(ctx, out)
    if out.get("topic") is None:
        out["topic"] = dict(st.get("topic") or {"id": 0, "label": ""},
                            new=False)
    n = len(out.get("results") or [])
    yield ("step", "wrote", f"Reply ready with {n} photos."
           if n else "Reply ready.")
    yield ("result", out)
