"""
ReelWorld: conversational search engine (terminal version), v2.

Each message is turned into a structured search spec by Muse Spark, then run
against Supabase (pgvector). The conversation keeps state, so you can refine:

    You: a busy street market with vegetables
    You: not this one, from a higher angle
    You: another angle of the second one
    You: what does the sign say?
    You: show me photos like this in my own photos

Actions
  search / refine   keep the running spec, change only what you ask, skip rejected photos
  another_angle     same place or landmark seen from a different viewpoint; says so
                    honestly when no other view of that place exists
  more_like_this    nearest photos by look first, place only as a small bonus
  question          answers from the stored annotation and says what is uncertain

Prerequisites
  * schema.sql and schema_v2.sql have been run in Supabase
  * load_supabase.py has loaded the photos
  * .env has BASETEN_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY

Run from the project root:
    python backend\\chat.py

Optional: use another model for understanding messages (for example Meta's own
API) by setting PARSER_BASE_URL, PARSER_KEY_ENV and PARSER_MODEL in .env.
Empty or paste_* values fall back to the Baseten defaults below; point
PARSER_KEY_ENV at META_API_KEY to use the Meta key once its endpoint is known.

Commands: "open 3" focuses result 3, "quit" exits.
"""
import json
import os
import re
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client

from retrieval import get_model, score_against, tokens

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

def _env_or(name, default):
    """Env value, or the default when unset, empty or still a paste_* placeholder."""
    v = (os.getenv(name) or "").strip()
    if not v or v.lower().startswith("paste_") or v.startswith("<"):
        return default
    return v


PARSER_BASE_URL = _env_or("PARSER_BASE_URL", "https://inference.baseten.co/v1")
PARSER_KEY = os.environ[_env_or("PARSER_KEY_ENV", "BASETEN_API_KEY")]
PARSER_MODEL = _env_or("PARSER_MODEL", "meta-models/muse-spark-open-1026")

VIEWPOINTS = ["ground_level", "elevated", "aerial", "interior", "water_level"]
COLLECTIONS = {"world": "world", "personal": "personal", "both": None}

VP_WORDS = {"ground_level": "ground level", "elevated": "from above",
            "aerial": "aerial", "interior": "indoors", "water_level": "water level"}
COLL_WORDS = {"world": "the world photos", "personal": "your photos",
              "both": "your photos and the world"}
COLL_FROM = {"world": "the world archive", "personal": "your photos",
             "both": "your photos and the world archive"}


def spec_words(spec):
    """The parsed spec in plain words, for the understood trace step."""
    bits = []
    if spec.get("query"):
        bits.append(f"“{spec['query']}”")
    bits.append("in " + COLL_WORDS.get(spec.get("collection"), "the world photos"))
    vps = [VP_WORDS.get(v, v) for v in spec.get("viewpoints") or []]
    if vps:
        bits.append(", ".join(vps))
    if spec.get("max_people") == 0:
        bits.append("no people")
    elif spec.get("max_people") is not None:
        bits.append(f"at most {spec['max_people']} people")
    if spec.get("must_include"):
        bits.append("must show: " + ", ".join(spec["must_include"]))
    if spec.get("avoid_terms"):
        bits.append("avoiding: " + ", ".join(spec["avoid_terms"]))
    return "Looking for " + ", ".join(bits)


def understood_step(intent, spec, anchor_txt=None, question=None, fell_back=False):
    action = intent.get("action", "search")
    if action == "question":
        detail = f"You asked about the photo in focus: “{question}”."
    elif action in ("another_angle", "more_like_this"):
        label = "another view of" if action == "another_angle" else "photos like"
        detail = f"You asked for {label} {anchor_txt or 'the photo in focus'}."
    else:
        detail = spec_words(spec)
    if fell_back:
        detail += " (I treated your message as a new search.)"
    return {"step": "understood", "detail": detail}


def rejected_step(exclude):
    n = len(exclude)
    return {"step": "rejected",
            "detail": f"Left out {n} photo{'s' if n != 1 else ''} you had rejected."}


EMPTY_SPEC = {"query": "", "collection": "world", "viewpoints": [],
              "max_people": None, "must_include": [], "avoid_terms": []}

PARSE_PROMPT = """You turn a user's message in a photo-search chat into a structured action.
Return ONE JSON object and nothing else.

Current search spec (what the user is already looking for):
{spec}

Photo currently in focus (may be null):
{focus}

User message: {message}

Return:
{{
  "action": "search | refine | another_angle | more_like_this | question",
  "spec": {{
    "query": "visual description of the wanted photo, as it would look (no words like 'show me')",
    "collection": "world | personal | both",
    "viewpoints": [],
    "max_people": null,
    "must_include": [],
    "avoid_terms": []
  }},
  "anchor": null,
  "focus_index": null,
  "reject_focus": false,
  "question": null
}}

Rules:
- "search": a brand-new request. "refine": the user wants changes to the current
  results; carry the previous spec forward and change ONLY what they ask.
- "not this one" / "not what I meant": action "refine", reject_focus true, and keep
  the spec (add details if they gave any).
- "another angle / different view of this": action "another_angle". "more like
  this" / "similar": action "more_like_this". For both, anchor is "focus", or a
  photo id if they named one.
- A question about what a photo shows, says or contains: action "question", with
  the question text in "question".
- focus_index is a number 1-5 if they refer to a result ("the second one", "open 3").
- viewpoints uses only: {viewpoints}. "from above / higher / from a tall building" =
  ["elevated", "aerial"]; "from the ground / street level" = ["ground_level"];
  "inside" = ["interior"]. Leave [] if they did not ask.
- max_people: 0 for "no people / empty"; otherwise null.
- collection: "personal" for "my photos / my gallery"; "both" for "everything /
  mine and the world"; otherwise "world".
- must_include: the concrete things the user asks for, as single lowercase words
  (for example "vegetables", "watermelons", "sign", "palm"). Always fill it for a
  search or refine when the user names specific objects. Include only words they
  actually used or clearly implied.
- avoid_terms: things they do not want, as single lowercase words.
"""

ANSWER_PROMPT = """You answer a question about ONE photo using ONLY the stored annotation below.
Rules:
- If the annotation does not contain the answer, say you cannot tell from the stored
  annotation, and suggest looking at the photo itself.
- Mention the evidence (signs, objects, where they are) and anything uncertain,
  including partial text or low confidence.
- Never identify a person. Keep the answer under 120 words.

Annotation:
{record}

Question: {question}
"""


def extract_json(text):
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found")
    return json.loads(text[start:end + 1])


class Engine:
    def __init__(self):
        self.sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
        self.llm = OpenAI(base_url=PARSER_BASE_URL, api_key=PARSER_KEY)
        self.embedder = get_model()
        self.state = {"spec": dict(EMPTY_SPEC), "focus": None, "last": [], "rejected": set()}

    # ----- helpers -----

    def ask(self, prompt, max_tokens=6000):
        print("(thinking ...)", flush=True)
        resp = self.llm.chat.completions.create(
            model=PARSER_MODEL, temperature=0.1, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}])
        return resp.choices[0].message.content or ""

    def embed(self, text):
        v = np.array(next(iter(self.embedder.query_embed(text))), dtype="float32")
        return (v / np.linalg.norm(v)).tolist()

    def rpc_search(self, embedding, spec, exclude, count=40, use_filters=True):
        params = {"query_embedding": embedding, "match_count": count}
        coll = COLLECTIONS.get(spec.get("collection", "world"), "world")
        if coll:
            params["filter_collection"] = coll
        if use_filters:
            vps = [v for v in spec.get("viewpoints") or [] if v in VIEWPOINTS]
            if vps:
                params["filter_viewpoints"] = vps
            if spec.get("max_people") is not None:
                params["max_people"] = int(spec["max_people"])
        if exclude:
            params["exclude_ids"] = sorted(exclude)
        return self.sb.rpc("search_photos", params).execute().data or []

    # ----- understanding the message -----

    def parse(self, message):
        focus = self.state["focus"]
        focus_txt = (json.dumps({"photo_id": focus["photo_id"], "caption": focus["caption"],
                                 "place": focus.get("place_name")}) if focus else "null")
        prompt = PARSE_PROMPT.format(spec=json.dumps(self.state["spec"]), focus=focus_txt,
                                     message=message, viewpoints=", ".join(VIEWPOINTS))
        try:
            data = extract_json(self.ask(prompt))
            spec = {**EMPTY_SPEC, **(data.get("spec") or {})}
            if not spec["query"]:
                spec["query"] = message
            data["spec"] = spec
            return data, False
        except Exception as e:
            print(f"(could not understand the message structure: {e}; treating it as a new search)")
            return ({"action": "search", "spec": {**EMPTY_SPEC, "query": message}, "anchor": None,
                    "focus_index": None, "reject_focus": False, "question": None}, True)

    # ----- the actions -----

    def search(self, spec, exclude):
        trace = []
        if exclude:
            trace.append(rejected_step(exclude))
        emb = self.embed(spec["query"])
        rows = self.rpc_search(emb, spec, exclude)
        toks = tokens(spec["query"])
        for r in rows:
            hit = [t for t in toks if t in r["lex"]]
            lex = (len(hit) / len(toks)) if toks else 0.0
            inc = [t for t in spec.get("must_include") or [] if t.lower() in r["lex"]]
            avoid = [t for t in spec.get("avoid_terms") or [] if t.lower() in r["lex"]]
            r["score"] = (r["similarity"] + 0.25 * lex + 0.12 * min(3, len(inc))
                          - 0.30 * min(2, len(avoid)))
            r["reasons"] = [f"meaning {r['similarity']:.2f}"]
            words = sorted(set(hit) | {t.lower() for t in inc})
            if words:
                r["reasons"].append("matches: " + ", ".join(words))
            if avoid:
                r["reasons"].append("mentions (unwanted): " + ", ".join(avoid))
        rows.sort(key=lambda r: r["score"], reverse=True)
        top = rows[:5]
        filters = []
        vps = [VP_WORDS.get(v, v) for v in spec.get("viewpoints") or []]
        if vps:
            filters.append(", ".join(vps))
        if spec.get("max_people") == 0:
            filters.append("no people")
        elif spec.get("max_people") is not None:
            filters.append(f"at most {spec['max_people']} people")
        if spec.get("must_include"):
            filters.append("must show " + ", ".join(spec["must_include"]))
        if spec.get("avoid_terms"):
            filters.append("avoiding " + ", ".join(spec["avoid_terms"]))
        trace.append({"step": "searched", "detail":
                      f"Searched {COLL_WORDS.get(spec.get('collection'), 'the world photos')} "
                      f"({'; '.join(filters) if filters else 'no filters'}); "
                      f"{len(rows)} candidates, kept the top {len(top)}."})
        words = spec.get("must_include") or []
        if words and not any(any(w.lower() in r["lex"] for w in words) for r in top):
            note = ("I could not find a photo that clearly shows " + ", ".join(words)
                    + ". Here are the closest matches:")
        else:
            note = None
        return top, note, trace

    def fetch_photo(self, photo_id, columns):
        data = self.sb.table("photos").select(columns).eq("photo_id", photo_id).execute().data
        return data[0] if data else None

    def related(self, anchor_id, spec, exclude, angle_mode):
        """Returns (rows, note). note is set when no true other view of the place exists."""
        cols = "photo_id,collection,file,caption,place_key,taken_from_key,landmark_keys,viewpoint,embedding"
        src = self.fetch_photo(anchor_id, cols)
        if not src:
            return [], None, []
        trace = []
        if exclude:
            trace.append(rejected_step(exclude))
        emb = src["embedding"]
        emb = json.loads(emb) if isinstance(emb, str) else emb
        rows = self.rpc_search(emb, spec, set(exclude) | {anchor_id}, count=60, use_filters=False)
        mode = ("by place and viewpoint, looking for a different viewpoint"
                if angle_mode else "by look, favouring the same place")
        trace.append({"step": "searched", "detail":
                      f"Compared {anchor_id} with {len(rows)} candidates from "
                      f"{COLL_FROM.get(spec.get('collection'), 'the world archive')} {mode}."})
        found_angle = False
        for r in rows:
            score, reasons, subject, different, _ = score_against(src, r, angle_mode)
            if subject and different:
                found_angle = found_angle or angle_mode
            r["score"] = score
            r["reasons"] = reasons
        note = None
        if angle_mode and not found_angle:
            rows.sort(key=lambda r: r["similarity"], reverse=True)
            for r in rows:
                r["reasons"] = [f"looks similar ({r['similarity']:.2f})"]
            note = (f"I could not find another view of the same place as {anchor_id} in this "
                    f"collection. Here are the most similar photos instead:")
            trace.append({"step": "fallback", "detail":
                          "No other view of the same place exists, so I showed the most similar photos instead."})
        else:
            rows.sort(key=lambda r: r["score"], reverse=True)
        return rows[:5], note, trace

    def answer(self, photo_id, question):
        row = self.fetch_photo(photo_id, "record")
        if not row:
            return "I could not find that photo."
        rec = row["record"]
        compact = {"observed": {k: rec["observed"].get(k) for k in
                                ["caption", "description", "scene", "camera", "entities",
                                 "spatial_relations", "visible_text", "people"]},
                   "inferred": {k: rec["inferred"].get(k) for k in
                                ["landmarks", "place", "taken_from", "cultural_context", "uncertainties"]}}
        return self.ask(ANSWER_PROMPT.format(record=json.dumps(compact, ensure_ascii=False),
                                             question=question), max_tokens=3000).strip()

    # ----- one conversation turn -----

    def turn(self, message):
        result = None
        for item in self.turn_stream(message):
            if item[0] == "result":
                result = item[1]
        return result

    def turn_stream(self, message):
        """Same turn as turn(), but yields live progress: ("step", name,
        detail) for understood/searched/checked/wrote as each stage really
        runs, then ("result", response dict). Stages that do not run are
        never emitted."""
        st = self.state
        trace = []
        m = re.fullmatch(r"\s*open\s+(\d)\s*", message, re.I)
        if m and st["last"] and 1 <= int(m.group(1)) <= len(st["last"]):
            st["focus"] = st["last"][int(m.group(1)) - 1]
            detail = f"Focused on result {m.group(1)}: {st['focus']['photo_id']}."
            trace.append({"step": "answered", "detail": detail})
            yield ("step", "understood", detail)
            yield ("step", "wrote", "Reply ready.")
            yield ("result", {"text": f"Focused on {st['focus']['photo_id']}: {st['focus']['caption']}", "results": [], "kind": "ok", "trace": trace})
            return

        intent, fell_back = self.parse(message)
        idx = intent.get("focus_index")
        if isinstance(idx, int) and st["last"] and 1 <= idx <= len(st["last"]):
            st["focus"] = st["last"][idx - 1]
        if intent.get("reject_focus") and st["focus"]:
            st["rejected"].add(st["focus"]["photo_id"])
        st["spec"] = intent["spec"]
        action = intent.get("action", "search")

        if action == "question":
            if not st["focus"]:
                u = understood_step(intent, st["spec"], question=intent.get("question") or message, fell_back=fell_back)
                trace.append(u)
                yield ("step", "understood", u["detail"])
                trace.append({"step": "answered", "detail": "No photo is in focus, so I asked you to open one first."})
                yield ("step", "wrote", "Reply ready.")
                yield ("result", {"text": "Open a photo first (say 'open 1'), then ask about it.", "results": [], "kind": "need_focus", "trace": trace})
                return
            q = intent.get("question") or message
            u = understood_step(intent, st["spec"], question=q, fell_back=fell_back)
            yield ("step", "understood", u["detail"])
            text = self.answer(st["focus"]["photo_id"], q)
            yield ("step", "checked", "Looked up the stored annotation for the photo in focus.")
            trace.append(u)
            trace.append({"step": "answered", "detail": "Answered from the stored annotation."})
            yield ("step", "wrote", "Reply ready.")
            yield ("result", {"text": text, "results": [], "kind": "question_answer", "trace": trace})
            return

        raw_anchor = intent.get("anchor")
        anchor_txt = (raw_anchor if isinstance(raw_anchor, str)
                      and raw_anchor.strip().lower() not in ("", "focus") else "the photo in focus")
        if action in ("another_angle", "more_like_this"):
            anchor = intent.get("anchor")
            if (anchor is None or (isinstance(anchor, str)
                    and anchor.strip().lower() in ("", "focus"))) and not st["focus"]:
                u = understood_step(intent, st["spec"], anchor_txt=anchor_txt, fell_back=fell_back)
                trace.append(u)
                yield ("step", "understood", u["detail"])
                trace.append({"step": "answered", "detail": "No photo to work from, so I asked you to search first."})
                yield ("step", "wrote", "Reply ready.")
                yield ("result", {"text": "Search for a photo first, then ask for other angles of it.",
                        "results": [], "kind": "need_focus", "trace": trace})
                return
            anchor_id = st["focus"]["photo_id"] if anchor in (None, "focus") and st["focus"] else anchor
            anchor_txt = anchor_id or anchor_txt
            if not anchor_id:
                u = understood_step(intent, st["spec"], anchor_txt=anchor_txt, fell_back=fell_back)
                trace.append(u)
                yield ("step", "understood", u["detail"])
                trace.append({"step": "answered", "Detail": "No photo to work from, so I asked you to search first."})
                yield ("step", "wrote", "Reply ready.")
                yield ("result", {"text": "Tell me which photo, or search first so there is one in focus.", "results": [], "kind": "need_focus", "trace": trace})
                return
            if not self.fetch_photo(anchor_id, "photo_id"):
                u = understood_step(intent, st["spec"], anchor_txt=anchor_txt, fell_back=fell_back)
                trace.append(u)
                yield ("step", "understood", u["detail"])
                trace.append({"step": "answered", "Detail": f"{anchor_id} is not in the archive."})
                yield ("step", "wrote", "Reply ready.")
                yield ("result", {"text": "I could not find that photo.", "results": [], "kind": "not_found", "trace": trace})
                return
            u = understood_step(intent, st["spec"], anchor_txt=anchor_id, fell_back=fell_back)
            yield ("step", "understood", u["detail"])
            rows, note, sub = self.related(anchor_id, st["spec"], st["rejected"], action == "another_angle")
            for t in sub:
                if t["step"] == "searched":
                    yield ("step", "searched", t["detail"])
            if note:
                yield ("step", "checked", f"Checked: no other view of {anchor_id} exists in this collection.")
            else:
                yield ("step", "checked", f"Checked candidates against {anchor_id}; kept {len(rows)}.")
            label = "other angles of" if action == "another_angle" else "photos like"
            kind = "no_other_angle" if note else "ok"
            trace.append(u)
            trace.extend(sub)
            trace.append({"step": "answered", "detail":
                          (f"Showed the {len(rows)} most similar photos instead." if note
                           else f"Showing {label} {anchor_id}.")})
            yield ("step", "wrote", f"Reply ready with {len(rows)} photos.")
            yield ("result", {"text": note or f"Showing {label} {anchor_id}:", "results": rows, "kind": kind, "trace": trace})
            return

        u = understood_step(intent, st["spec"], fell_back=fell_back)
        yield ("step", "understood", u["detail"])
        rows, note, sub = self.search(st["spec"], st["rejected"])
        for t in sub:
            if t["step"] == "searched":
                yield ("step", "searched", t["detail"])
        if note:
            words = ", ".join(st["spec"].get("must_include") or [])
            yield ("step", "checked", f"Checked the top {len(rows)} photos: nothing clearly shows {words}.")
        elif st["rejected"]:
            yield ("step", "checked", f"Skipped {len(st['rejected'])} rejected photo(s); verified the top {len(rows)} against your filters.")
        else:
            yield ("step", "checked", f"Verified the top {len(rows)} photos against your filters.")
        kind = "no_strong_match" if note else "ok"
        trace.append(u)
        trace.extend(sub)
        trace.append({"step": "answered", "detail":
                      (f"Nothing clearly matched; showing the {len(rows)} closest photos." if note
                       else f"Showing {len(rows)} photos.")})
        yield ("step", "wrote", f"Reply ready with {len(rows)} photos.")
        yield ("result", {"text": note or "Here is what I found:", "results": rows, "kind": kind, "trace": trace})


def show(rows):
    for n, r in enumerate(rows, 1):
        print(f"{n}. {r['photo_id']:<14} [{r['viewpoint']}] {r['caption'][:90]}")
        print(f"     {' | '.join(r['reasons'])}")
        print(f"     file: {r['file']}")


def main():
    print("Loading ...")
    eng = Engine()
    print("ReelWorld chat. Describe a photo to find it. Say 'open 2' to focus a result, 'quit' to exit.")
    while True:
        try:
            message = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not message:
            continue
        if message.lower() in ("quit", "exit"):
            break
        out = eng.turn(message)
        print(out["text"])
        if out["results"]:
            eng.state["last"] = out["results"]
            eng.state["focus"] = out["results"][0]
            show(out["results"])
            print(f"\n(in focus: {eng.state['focus']['photo_id']}; rejected so far: {len(eng.state['rejected'])})")


if __name__ == "__main__":
    main()