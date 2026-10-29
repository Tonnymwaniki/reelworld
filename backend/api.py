"""
ReelWorld: HTTP API - FastAPI wrapper around the Engine in chat.py.

Endpoints
  GET  /health                     liveness check (no model or DB access)
  POST /chat                       {"session_id": "...", "message": "..."}
  POST /api/search                 {"session_id": "...", "spec": {...}} (no LLM call)
  POST /sessions/{session_id}/reset  forget one conversation
  GET  /api/photos?collection=&limit=  photo grid listing (world | personal)
  GET  /api/photo/{photo_id}       record summary for the evidence panel
  POST /api/ask                    {"photo_id": "...", "question": "..."}
  POST /api/upload                 photo bytes -> background annotation job
  GET  /api/jobs/{job_id}          upload job status
  GET  /api/bridge/{photo_id}      other-collection matches, grouped by reason
  GET  /api/connected              per-personal-photo bridge index (cached)
  GET  /api/identify/{photo_id}    "where is this?" place verdict

Also serves the frontend page at / and the photo files at /photos/...

Notes
  * Conversation state (spec, focus, last results, rejected ids) is kept in
    memory, one Engine per session_id. Restarts clear it.
  * The embedding model is loaded once and shared by all sessions.
  * The /api/* reads use a shared Supabase client (no model load); /api/ask
    uses a shared LLM client. Only /chat builds an Engine.

Run from the project root:
    python -m uvicorn backend.api:app --reload

Then open http://127.0.0.1:8000 in a browser.
"""
from __future__ import annotations

import base64
import csv
import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, Field
from supabase import create_client

import annotate as annotate_mod
import chat as chat_module
import place_pass as place_pass_mod
from chat import (ANSWER_PROMPT, EMPTY_SPEC, PARSER_BASE_URL, PARSER_KEY, PARSER_MODEL,
                  Engine, extract_json)
from retrieval import meta_for, score_against, search_text

ROOT = Path(__file__).resolve().parent.parent
PHOTOS_DIR = ROOT / "data" / "photos"
FRONTEND_DIR = ROOT / "frontend"
INDEX_HTML = FRONTEND_DIR / "index.html"
# Hash views the app may fetch. Anything else under frontend/ (notably
# frontend/design/) is never served, so exports stay out of the page bundle.
VIEW_NAMES = ("home", "photo", "add", "connected", "place", "story")

# ----- share one embedding model across all sessions -----
_model_lock = threading.Lock()
_shared_embedder: Any = None
_orig_get_model = chat_module.get_model


def _singleton_get_model():
    """Load the fastembed model once; every Engine reuses it."""
    global _shared_embedder
    with _model_lock:
        if _shared_embedder is None:
            _shared_embedder = _orig_get_model()
        return _shared_embedder


chat_module.get_model = _singleton_get_model  # Engine.__init__ picks this up

# ----- one Engine (conversation state) per session_id -----
_sessions: Dict[str, Engine] = {}
_sessions_lock = threading.Lock()
_turn_lock = threading.Lock()  # one turn at a time; turns mutate session state

# Heavy/internal row fields the API never sends to clients.
DROP_KEYS = ("embedding", "lex")


def get_engine(session_id: str) -> Engine:
    sid = (session_id or "").strip() or "default"
    with _sessions_lock:
        eng = _sessions.get(sid)
        if eng is None:
            eng = Engine()
            _sessions[sid] = eng
        return eng


def public_row(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in DROP_KEYS}


def attach_credits(rows):
    """Attach photographer credit to result rows: the world's
    {author, license, source_url, title} from record.provided, else None."""
    ids = [r.get("photo_id") for r in rows if r.get("photo_id")]
    by_id = {}
    if ids:
        try:
            recs = (get_sb().table("photos").select("photo_id,collection,record")
                    .in_("photo_id", ids).execute().data or [])
            by_id = {r["photo_id"]: r for r in recs}
        except Exception:
            by_id = {}
    for r in rows:
        hit = by_id.get(r.get("photo_id"))
        credit = None
        if hit and hit.get("collection") == "world":
            prov = ((hit.get("record") or {}).get("provided") or {})
            credit = {"author": prov.get("author"), "license": prov.get("license"),
                      "source_url": prov.get("source_url"), "title": prov.get("title")}
        r["credit"] = credit
    return rows


# ----- shared lightweight clients (no embedding model) -----
_sb = None
_llm = None
_clients_lock = threading.Lock()


def get_sb():
    """Shared Supabase client for the /api/* read endpoints."""
    global _sb
    with _clients_lock:
        if _sb is None:
            _sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
        return _sb


def get_llm():
    """Shared LLM client for /api/ask."""
    global _llm
    with _clients_lock:
        if _llm is None:
            _llm = OpenAI(base_url=PARSER_BASE_URL, api_key=PARSER_KEY)
        return _llm


def photo_url(file):
    """Turn a stored path like data/photos/world/x.jpg into /photos/world/x.jpg."""
    p = str(file or "").replace("\\", "/")
    if p.startswith("/photos/"):
        return p
    if "data/photos/" in p:
        p = p.replace("data/photos/", "", 1)
    return "/photos/" + p.lstrip("/")


class ChatRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1)
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    session_id: str
    text: str
    results: List[dict]
    focus_photo_id: Optional[str] = None
    spec: Dict[str, Any] = Field(default_factory=dict)
    kind: str = "ok"
    trace: List[dict] = Field(default_factory=list)


app = FastAPI(title="ReelWorld API")

app.mount("/photos", StaticFiles(directory=str(PHOTOS_DIR)), name="photos")


@app.get("/")
def index():
    if not INDEX_HTML.exists():
        raise HTTPException(status_code=503, detail="frontend not built")
    return FileResponse(str(INDEX_HTML))


@app.get("/app.js")
def app_js():
    p = FRONTEND_DIR / "app.js"
    if not p.exists():
        raise HTTPException(status_code=503, detail="frontend not built")
    return FileResponse(str(p), media_type="application/javascript")


@app.get("/styles.css")
def styles_css():
    p = FRONTEND_DIR / "styles.css"
    if not p.exists():
        raise HTTPException(status_code=503, detail="frontend not built")
    return FileResponse(str(p), media_type="text/css")


@app.get("/views/{name}.html")
def view(name: str):
    if name not in VIEW_NAMES:
        raise HTTPException(status_code=404, detail="unknown view")
    p = FRONTEND_DIR / "views" / f"{name}.html"
    if not p.exists():
        raise HTTPException(status_code=503, detail="frontend not built")
    return FileResponse(str(p), media_type="text/html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    sid = req.session_id.strip() or "default"
    try:
        eng = get_engine(sid)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"engine unavailable: {e}")
    with _turn_lock:
        try:
            out = eng.turn(req.message)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"search failed: {e}")
        # Same bookkeeping as chat.main(): new results become last/focus.
        if out.get("results"):
            eng.state["last"] = out["results"]
            eng.state["focus"] = out["results"][0]
        focus = eng.state.get("focus") or {}
        spec = eng.state.get("spec") or {}
    rows = [public_row(r) for r in out.get("results", [])]
    attach_credits(rows)
    return {
        "session_id": sid,
        "text": out.get("text", ""),
        "results": rows,
        "focus_photo_id": focus.get("photo_id"),
        "spec": {k: spec.get(k) for k in ("query", "collection", "viewpoints",
                                          "max_people", "must_include", "avoid_terms")},
        "kind": out.get("kind", "ok"),
        "trace": out.get("trace", []),
    }


VIEWPOINTS = ("ground_level", "elevated", "aerial", "interior", "water_level")


class SearchRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1)
    spec: Dict[str, Any]


def clean_spec(raw):
    """EMPTY_SPEC defaults plus the caller's keys, validated. 400 on garbage."""
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="spec must be an object")
    spec = dict(EMPTY_SPEC)
    for k in spec:
        if k in raw:
            spec[k] = raw[k]
    if not isinstance(spec["query"], str) or not spec["query"].strip():
        raise HTTPException(status_code=400, detail="spec.query must be a non-empty string")
    if spec["collection"] not in ("world", "personal", "both"):
        raise HTTPException(status_code=400, detail="spec.collection must be world, personal or both")
    if (not isinstance(spec["viewpoints"], list)
            or any(v not in VIEWPOINTS for v in spec["viewpoints"])):
        raise HTTPException(status_code=400,
                            detail=f"spec.viewpoints must be a list of: {', '.join(VIEWPOINTS)}")
    if spec["max_people"] is not None and (
            not isinstance(spec["max_people"], int) or spec["max_people"] < 0):
        raise HTTPException(status_code=400, detail="spec.max_people must be null or >= 0")
    for k in ("must_include", "avoid_terms"):
        if not isinstance(spec[k], list) or any(not isinstance(w, str) for w in spec[k]):
            raise HTTPException(status_code=400, detail=f"spec.{k} must be a list of strings")
        spec[k] = [w.strip().lower() for w in spec[k] if w.strip()]
    return spec


@app.post("/api/search", response_model=ChatResponse)
def api_search(req: SearchRequest):
    """Run a spec directly: no language-model call. Honours the session's
    rejected ids and stores the spec (powers instant chip removal)."""
    spec = clean_spec(req.spec)
    sid = req.session_id.strip() or "default"
    try:
        eng = get_engine(sid)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"engine unavailable: {e}")
    with _turn_lock:
        try:
            rows, note, trace = eng.search(spec, eng.state["rejected"])
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"search failed: {e}")
        eng.state["spec"] = spec
        if rows:
            eng.state["last"] = rows
            eng.state["focus"] = rows[0]
        focus = eng.state.get("focus") or {}
    out_rows = [public_row(r) for r in rows]
    attach_credits(out_rows)
    trace.append({"step": "answered", "detail":
                  (f"Nothing clearly matched; showing the {len(rows)} closest photos." if note
                   else f"Showing {len(rows)} photos.")})
    return {
        "session_id": sid,
        "text": note or "Here is what I found:",
        "results": out_rows,
        "focus_photo_id": focus.get("photo_id"),
        "spec": {k: spec.get(k) for k in ("query", "collection", "viewpoints",
                                          "max_people", "must_include", "avoid_terms")},
        "kind": "no_strong_match" if note else "ok",
        "trace": trace,
    }


@app.post("/sessions/{session_id}/reset")
def reset_session(session_id: str):
    sid = (session_id or "").strip() or "default"
    with _sessions_lock:
        _sessions.pop(sid, None)
    return {"session_id": sid, "reset": True}


class AskRequest(BaseModel):
    photo_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    session_id: Optional[str] = None


class CompareRequest(BaseModel):
    photo_a: str = Field(min_length=1)
    photo_b: str = Field(min_length=1)
    question: Optional[str] = None


ANNOTATION_MISS = ("cannot tell", "can't tell", "can not tell")

COMPARE_PROMPT = """You compare two stored photo records, A and B. Answer ONLY from
the records below; never add outside facts.
Rules: keep "answer" under 150 words; name the evidence (say which record
each claim comes from); state uncertainty plainly ("the records cannot
tell"); never identify a person (no names; people only by count,
activity or clothing).
Compare viewpoint, time of day, scene, what is present in one and not
the other, signs read, and place. If the question below is empty,
summarise the main differences; otherwise answer it from the records.
Return ONE JSON object and nothing else:
{{"answer": "...", "differences": [{{"aspect": "...", "a": "...", "b": "..."}}]}}
Include one entry per aspect you can compare (at most 6). Where a side
is not covered, write "not stated in the record" for that side.

Record A ({photo_a}):
{record_a}

Record B ({photo_b}):
{record_b}

Question: {question}"""

IMAGE_ANSWER_PROMPT = """Look at the attached photo and answer the question. The stored
annotation below is context, but what you can see in the photo wins.
Rules: answer only what is visible; keep it under 120 words; never
identify a person (no names; describe people only by count, activity or
clothing). If the photo does not show the answer, say you cannot tell
from the photo.

Stored annotation:
{record}

Question: {question}"""


def _compact_record(rec):
    return {"observed": {k: rec["observed"].get(k) for k in
                         ["caption", "description", "scene", "camera", "entities",
                          "spatial_relations", "visible_text", "people"]},
            "inferred": {k: rec["inferred"].get(k) for k in
                         ["landmarks", "place", "taken_from", "cultural_context",
                          "uncertainties"]}}


@app.get("/api/photos")
def list_photos(collection: str = "world", limit: int = 24):
    if collection not in ("world", "personal"):
        raise HTTPException(status_code=400, detail="collection must be 'world' or 'personal'")
    limit = max(1, min(int(limit), 200))
    try:
        rows = (get_sb().table("photos")
                .select("photo_id,collection,file,caption,viewpoint,place_name,place_key")
                .eq("collection", collection).order("photo_id").limit(limit).execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"photo list failed: {e}")
    return {"collection": collection, "count": len(rows),
            "photos": [{"photo_id": r["photo_id"], "collection": r["collection"],
                        "src": photo_url(r.get("file")), "caption": r.get("caption"),
                        "viewpoint": r.get("viewpoint"), "place": r.get("place_name"),
                        "place_key": r.get("place_key")}
                       for r in rows]}


@app.get("/api/photo/{photo_id}")
def photo_detail(photo_id: str):
    try:
        rows = (get_sb().table("photos")
                .select("photo_id,collection,file,caption,viewpoint,place_name,record")
                .eq("photo_id", photo_id).execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"photo lookup failed: {e}")
    if not rows:
        raise HTTPException(status_code=404, detail="I could not find that photo.")
    return _photo_detail_shape(rows[0])


def _place_shape(p):
    if not p:
        return None
    return {"name": p.get("name"), "key": p.get("key"), "status": p.get("status"),
            "evidence": p.get("evidence") or [], "confidence": p.get("confidence")}


def _suggested_questions(signs, place, people_count):
    out = []
    if signs:
        out.append("What does the sign say?")
    if place:
        out.append("Where was this taken?")
    out.append("What is happening here?")
    if (people_count or 0) > 0:
        out.append("How many people are visible?")
    return out[:3]


def _photo_detail_shape(r):
    """Stable evidence-panel shape, shared by /api/photo and job results."""
    rec = r.get("record") or {}
    obs = rec.get("observed") or {}
    inf = rec.get("inferred") or {}
    scene = obs.get("scene") or {}
    people_count = (obs.get("people") or {}).get("count", 0) or 0
    ents = sorted(obs.get("entities") or [], key=lambda e: e.get("salience", 0), reverse=True)
    signs = [{"text": t.get("text"), "legibility": t.get("legibility"),
              "confidence": t.get("confidence"), "where": t.get("location_in_image")}
             for t in (obs.get("visible_text") or [])]
    place = _place_shape(inf.get("place"))
    prov = rec.get("provided") or {}
    credit = None
    if r.get("collection") == "world":
        credit = {"author": prov.get("author"), "license": prov.get("license"),
                  "source_url": prov.get("source_url"), "title": prov.get("title")}
    return {
        "photo_id": r["photo_id"], "collection": r["collection"],
        "file": r.get("file"), "src": photo_url(r.get("file")),
        "caption": r.get("caption") or obs.get("caption"),
        "description": obs.get("description"), "viewpoint": r.get("viewpoint"),
        "scene": {"type": scene.get("type"), "time_of_day": scene.get("time_of_day"),
                  "setting": scene.get("setting")},
        "people_count": people_count,
        "things": [{"label": e.get("label"), "attributes": e.get("attributes") or [],
                    "salience": e.get("salience"), "confidence": e.get("confidence")}
                   for e in ents[:8]],
        "signs": signs,
        "place": place,
        "taken_from": _place_shape(inf.get("taken_from")),
        "landmarks": [{"name": lm.get("name"), "status": lm.get("status"),
                       "evidence": lm.get("evidence") or []}
                      for lm in (inf.get("landmarks") or [])],
        "uncertainties": inf.get("uncertainties") or [],
        "credit": credit,
        "suggested_questions": _suggested_questions(signs, place, people_count),
    }


@app.post("/api/ask")
def ask(req: AskRequest):
    pid = req.photo_id.strip()
    try:
        rows = (get_sb().table("photos").select("record,file")
                .eq("photo_id", pid).execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"photo lookup failed: {e}")
    if not rows:
        raise HTTPException(status_code=404, detail="I could not find that photo.")
    rec = rows[0]["record"]
    compact = _compact_record(rec)
    try:
        resp = get_llm().chat.completions.create(
            model=PARSER_MODEL, temperature=0.1, max_tokens=3000,
            messages=[{"role": "user", "content": ANSWER_PROMPT.format(
                record=json.dumps(compact, ensure_ascii=False), question=req.question)}])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"answer failed: {e}")
    answer = (resp.choices[0].message.content or "").strip()
    if not any(p in answer.lower() for p in ANNOTATION_MISS):
        return {"photo_id": pid, "question": req.question, "answer": answer,
                "source": "annotation", "note": None,
                "trace": [{"step": "answered",
                           "detail": "Answered from the stored annotation."}]}
    img_path = ROOT / str(rows[0].get("file") or "")
    if not img_path.exists():
        return {"photo_id": pid, "question": req.question, "answer": answer,
                "source": "annotation", "note": None,
                "trace": [{"step": "answered",
                           "detail": "Answered from the stored annotation."}]}
    mime = "image/png" if img_path.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(img_path.read_bytes()).decode()
    try:
        vision = OpenAI(base_url=annotate_mod.BASE_URL, api_key=os.environ["BASETEN_API_KEY"])
        resp = vision.chat.completions.create(
            model=annotate_mod.MODEL, temperature=0.1, max_tokens=3000,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": IMAGE_ANSWER_PROMPT.format(
                    record=json.dumps(compact, ensure_ascii=False), question=req.question)},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]}])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"image look failed: {e}")
    img_answer = " ".join((resp.choices[0].message.content or "").strip().split()[:120])
    return {"photo_id": pid, "question": req.question, "answer": img_answer,
            "source": "image", "note": "This answer came from looking at the photo again.",
            "trace": [{"step": "reinspected",
                       "detail": "The stored annotation could not answer, so I looked at the photo again."},
                      {"step": "answered",
                       "detail": "Answered from looking at the photo again."}]}


def _record_or_404(pid):
    try:
        rows = (get_sb().table("photos").select("record")
                .eq("photo_id", pid.strip()).execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"photo lookup failed: {e}")
    if not rows:
        raise HTTPException(status_code=404, detail="I could not find that photo.")
    return rows[0]["record"]


@app.post("/api/compare")
def compare(req: CompareRequest):
    if req.photo_a == req.photo_b:
        raise HTTPException(status_code=400, detail="photo_a and photo_b must be different.")
    rec_a = _record_or_404(req.photo_a)
    rec_b = _record_or_404(req.photo_b)
    try:
        resp = get_llm().chat.completions.create(
            model=PARSER_MODEL, temperature=0.1, max_tokens=8000,
            messages=[{"role": "user", "content": COMPARE_PROMPT.format(
                photo_a=req.photo_a,
                record_a=json.dumps(_compact_record(rec_a), ensure_ascii=False),
                photo_b=req.photo_b,
                record_b=json.dumps(_compact_record(rec_b), ensure_ascii=False),
                question=req.question or "(no question: summarise the main differences)")}])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"compare failed: {e}")
    try:
        data = extract_json(resp.choices[0].message.content or "")
    except Exception:
        raise HTTPException(status_code=502, detail="compare failed: bad model reply.")
    diffs = []
    raw = data.get("differences") or []
    if isinstance(raw, list):
        for d in raw[:6]:
            if isinstance(d, dict):
                diffs.append({"aspect": str(d.get("aspect", "")),
                              "a": str(d.get("a", "")), "b": str(d.get("b", ""))})
    answer = " ".join(str(data.get("answer", "")).split()[:150])
    return {"photo_a": req.photo_a, "photo_b": req.photo_b,
            "question": req.question, "answer": answer,
            "differences": diffs, "source": "annotation"}


class StoryRequest(BaseModel):
    theme: str = Field(min_length=1)
    collection: str = "world"
    lang: Optional[str] = "en"


STORY_PLAN_PROMPT = """You plan a photo story: a short visual tour of one theme told with photos from a Nairobi photo archive.
Theme: {theme}
Return ONE JSON object and nothing else:
{{"title": "a short story title", "chapters": [{{"heading": "...", "query": "..."}}]}}
Rules: 3 to 5 chapters. Every chapter query must be a plain, concrete, visual photo-search query in English that a photo archive could answer (things, places, views, times of day). Do not repeat queries. Do not plan chapters that need dates, names of people, or outside facts."""

STORY_TEXT_PROMPT = """You write one chapter of a photo story. Chapter heading: {heading}
You may use ONLY facts stated in the photo records below. Never add outside facts: no dates, no history, no causes, no names of people, no claims about anything not in the records. If the records say little, write little. Write one or two sentences. Never identify a person (people only by count, activity or clothing).
Records:
{records}
Return ONE JSON object and nothing else: {{"text": "..."}}"""


def _story_search(eng, query, collection, used):
    spec = dict(EMPTY_SPEC)
    spec["query"] = query
    spec["collection"] = collection
    rows, _note, _trace = eng.search(spec, used)
    return [r for r in rows if r["photo_id"] not in used]


def _story_credits(photo_ids):
    credits, seen = [], set()
    if not photo_ids:
        return credits
    try:
        recs = (get_sb().table("photos").select("photo_id,collection,record")
                .in_("photo_id", photo_ids).execute().data or [])
    except Exception:
        return credits
    for r in recs:
        if r.get("collection") != "world":
            continue
        prov = ((r.get("record") or {}).get("provided")) or {}
        if not prov.get("author") and not prov.get("license"):
            continue
        if (prov.get("author"), prov.get("license")) in seen:
            continue
        seen.add((prov.get("author"), prov.get("license")))
        credits.append({"author": prov.get("author"), "license": prov.get("license"),
                        "source_url": prov.get("source_url")})
    return credits


def _llm_json(prompt, temperature, max_tokens, tries=3):
    """One JSON-object model call, retried for transient API failures."""
    last = None
    for attempt in range(tries):
        try:
            resp = get_llm().chat.completions.create(
                model=PARSER_MODEL, temperature=temperature, max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}])
            return extract_json(resp.choices[0].message.content or "")
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


@app.post("/api/story")
def story(req: StoryRequest):
    """A small agent: plan chapters, run a real engine search per chapter,
    pick 1-2 unused photos each, and write record-only chapter text."""
    theme = req.theme.strip()
    if not theme:
        raise HTTPException(status_code=400, detail="theme must be a non-empty string.")
    if req.collection not in ("world", "personal", "both"):
        raise HTTPException(status_code=400,
                            detail="collection must be 'world', 'personal' or 'both'.")
    if (req.lang or "en").lower() != "en":
        raise HTTPException(status_code=400, detail="only 'en' is supported.")
    try:
        eng = get_engine("story")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"engine unavailable: {e}")
    try:
        plan = _llm_json(STORY_PLAN_PROMPT.format(theme=theme), 0.3, 4000)
    except Exception:
        raise HTTPException(status_code=502, detail="story planning failed.")
    raw = plan.get("chapters") or []
    if not isinstance(raw, list):
        raise HTTPException(status_code=502, detail="story planning failed: bad plan shape.")
    trace = [{"step": "planned",
              "detail": f"Planned {len(raw[:5])} chapters for {theme!r}."}]
    chapters, used, photo_ids = [], set(), []
    for ch in raw[:5]:
        if not isinstance(ch, dict):
            continue
        heading = str(ch.get("heading") or "").strip()
        query = str(ch.get("query") or "").strip()
        if not heading or not query:
            trace.append({"step": "dropped",
                          "detail": "Skipped a planned chapter with no heading or query."})
            continue
        try:
            with _turn_lock:
                found = _story_search(eng, query, req.collection, used)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"story search failed: {e}")
        picked = found[:2]
        if not picked:
            trace.append({"step": "dropped", "detail":
                          f"Dropped {heading!r}: the {req.collection} collection has "
                          f"no unused photo for {query!r}."})
            continue
        trace.append({"step": "searched", "detail":
                      f"{heading!r}: searched {query!r}; kept "
                      + ", ".join(r["photo_id"] for r in picked) + "."})
        text, attempt_sets = None, [picked, picked[:1]]
        for att in attempt_sets:
            try:
                recs = [{r["photo_id"]: _compact_record(_record_or_404(r["photo_id"]))}
                        for r in att]
                text = str(_llm_json(STORY_TEXT_PROMPT.format(
                    heading=heading, records=json.dumps(recs, ensure_ascii=False)),
                    0.2, 8000, tries=1).get("text") or "").strip()
                if text:
                    picked = att
                    break
            except Exception:
                text = None
        if not text:
            trace.append({"step": "dropped", "detail":
                          f"Dropped {heading!r}: no chapter text came back."})
            continue
        for r in picked:
            used.add(r["photo_id"])
            photo_ids.append(r["photo_id"])
        trace.append({"step": "written", "detail":
                      f"Wrote {heading!r} from {len(picked)} photo record(s)."})
        chapters.append({"heading": heading,
                         "photos": [{"photo_id": r["photo_id"], "collection": r.get("collection"),
                                     "src": photo_url(r.get("file")), "caption": r.get("caption")}
                                    for r in picked],
                         "text": text})
    title = str(plan.get("title") or theme).strip() or theme
    if chapters:
        n = len(chapters)
        intro = f"{title} — a photo story in {n} chapter{'s' if n != 1 else ''}."
    else:
        intro = f"I could not build a photo story about {theme!r} from this collection."
    return {"theme": theme, "collection": req.collection, "title": title, "intro": intro,
            "chapters": chapters, "credits": _story_credits(photo_ids), "trace": trace}


# ----- photo uploads: background annotation jobs -----
UPLOAD_DIR = ROOT / "data" / "photos" / "personal"
PERSONAL_ANN = ROOT / "data" / "annotations" / "personal"
NOTES_CSV = ROOT / "data" / "personal_manifest.csv"
MAX_UPLOAD = 10 * 1024 * 1024
RAW_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png"}

_jobs: Dict[str, dict] = {}
_jobs_lock = threading.Lock()
_reserved_ids: set = set()
_alloc_lock = threading.Lock()


def _job_new(photo_id):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    job = {"job_id": uuid.uuid4().hex, "status": "queued", "stage": "uploaded",
           "result": None,
           "photo_id": photo_id, "error": None,
           "created_at": now, "updated_at": now}
    with _jobs_lock:
        _jobs[job["job_id"]] = job
    return job


def _job_set(job_id, **kw):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.update(kw)
        job["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")


def next_personal_id():
    """Next free personal_NNN id, reserved so concurrent uploads cannot collide."""
    with _alloc_lock:
        used = set(_reserved_ids)
        if PERSONAL_ANN.exists():
            used.update(p.stem for p in PERSONAL_ANN.glob("personal_*.json"))
        try:
            rows = (get_sb().table("photos").select("photo_id")
                    .eq("collection", "personal").execute().data or [])
            used.update(r["photo_id"] for r in rows)
        except Exception:
            pass  # offline: local scan only; upsert is still by photo_id
        n = 0
        for pid in used:
            m = re.fullmatch(r"personal_(\d+)", pid)
            if m:
                n = max(n, int(m.group(1)))
        while True:
            n += 1
            cand = f"personal_{n:03d}"
            if (cand not in used
                    and not (PERSONAL_ANN / f"{cand}.json").exists()
                    and not (UPLOAD_DIR / f"{cand}.jpg").exists()
                    and not (UPLOAD_DIR / f"{cand}.png").exists()):
                _reserved_ids.add(cand)
                return cand


def append_personal_note(photo_id, note):
    NOTES_CSV.parent.mkdir(parents=True, exist_ok=True)
    if not NOTES_CSV.exists():
        NOTES_CSV.write_text("photo_id,owner_note\n", encoding="utf-8")
    else:
        with open(NOTES_CSV, "rb+") as f:
            f.seek(0, 2)
            if f.tell() > 0:
                f.seek(-1, 2)
                if f.read(1) != b"\n":
                    f.write(b"\n")
    with open(NOTES_CSV, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([photo_id, note])


def load_personal_notes():
    """Same shape as place_pass.load_notes but skips malformed rows."""
    notes = {}
    if not NOTES_CSV.exists():
        return notes
    with open(NOTES_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if not isinstance(row, dict):
                continue
            clean, bad = {}, False
            for k, v in row.items():
                if k is None or not isinstance(v, str):
                    bad = True  # ragged row: more fields than the header
                    break
                clean[k.strip().lower()] = v.strip()
            if bad:
                continue
            if clean.get("photo_id"):
                notes[clean["photo_id"]] = clean.get("owner_note", "")
    return notes


def run_upload_job(job_id, photo_id, owner_note):
    """Pass A -> Pass B -> embed -> Supabase upsert. Runs in a worker thread."""
    _job_set(job_id, status="running", stage="looking")
    try:
        client = OpenAI(base_url=annotate_mod.BASE_URL, api_key=os.environ["BASETEN_API_KEY"])
        photo_path = None
        for ext in (".jpg", ".png"):
            cand = UPLOAD_DIR / f"{photo_id}{ext}"
            if cand.exists():
                photo_path = cand
                break
        if photo_path is None:
            raise RuntimeError("uploaded file went missing")
        _, status = annotate_mod.annotate(client, photo_path, annotate_mod.load_manifest(), True)
        if not status.startswith("ok"):
            raise RuntimeError(f"Pass A failed: {status}")

        _job_set(job_id, stage="placing")
        if owner_note:
            append_personal_note(photo_id, owner_note)
        _, status, _ = place_pass_mod.process(
            client, PERSONAL_ANN / f"{photo_id}.json",
            place_pass_mod.load_registry(), load_personal_notes(), True)
        if not status.startswith("ok"):
            raise RuntimeError(f"Pass B failed: {status}")

        _job_set(job_id, stage="connecting")
        rec = json.loads((PERSONAL_ANN / f"{photo_id}.json").read_text(encoding="utf-8"))
        text = search_text(rec)
        m = meta_for(rec, text)
        vec = np.array(list(chat_module.get_model().embed([text]))[0], dtype="float32")
        vec = vec / np.linalg.norm(vec)

        _job_set(job_id, stage="connecting")
        get_sb().table("photos").upsert({
            "photo_id": m["photo_id"], "collection": m["collection"], "file": m["file"],
            "caption": m["caption"], "place_key": m["place_key"],
            "place_name": m["place_name"], "taken_from_key": m["taken_from_key"],
            "landmark_keys": m["landmark_keys"], "viewpoint": m["viewpoint"],
            "scene_type": m["scene_type"], "people_count": m["people_count"],
            "lex": m["lex"], "record": rec, "embedding": vec.tolist(),
        }, on_conflict="photo_id").execute()
        try:
            refresh_connected()
        except Exception as e:
            print(f"(connected refresh failed: {e})")
        full = (get_sb().table("photos").select(
            "photo_id,collection,file,caption,viewpoint,place_key,place_name,"
            "taken_from_key,landmark_keys,record,embedding")
            .eq("photo_id", photo_id).execute().data or [None])[0]
        result = None
        try:
            if full is None:
                raise RuntimeError("stored photo went missing")
            bc = _bridge_candidates(_coerce_embedding(full["embedding"]), "world", photo_id)
            result = {"photo": _photo_detail_shape(full),
                      "identify": _identify_shape(photo_id),
                      "bridge": _bridge_groups(_score_bridge(full, bc), 4)}
        except Exception as e:
            print(f"(job result assembly failed: {e})")
        _job_set(job_id, status="done", stage="done", result=result)
        with _jobs_lock:
            snap = dict(_jobs.get(job_id) or {})
        _record_duration(snap)
    except Exception as e:
        _job_set(job_id, status="error", error=str(e)[:500])


@app.post("/api/upload", status_code=202)
async def upload(request: Request, background_tasks: BackgroundTasks,
                 owner_note: Optional[str] = None, note: Optional[str] = None):
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    data, text = None, (note or owner_note)
    if ctype.startswith("multipart/"):
        try:
            form = await request.form(max_part_size=MAX_UPLOAD)
        except (RuntimeError, AssertionError):
            raise HTTPException(501, "multipart uploads need python-multipart: pip install python-multipart")
        except Exception:
            raise HTTPException(400, "could not parse multipart body")
        up = form.get("photo")
        if up is None or not hasattr(up, "read"):
            raise HTTPException(400, "multipart field 'photo' with an image file is required")
        data = await up.read()
        if form.get("note") or form.get("owner_note"):
            text = str(form.get("note") or form.get("owner_note"))
    elif ctype in RAW_IMAGE_TYPES:
        data = await request.body()
    else:
        raise HTTPException(400, "send multipart/form-data with a 'photo' file, "
                                 "or raw image bytes with Content-Type image/jpeg or image/png")
    if not data:
        raise HTTPException(400, "empty photo")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "photo is larger than 10 MB")
    if data.startswith(b"\x89PNG"):
        ext = ".png"
    elif data.startswith(b"\xff\xd8"):
        ext = ".jpg"
    else:
        raise HTTPException(400, "photo must be a JPEG or PNG image")
    photo_id = next_personal_id()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / f"{photo_id}{ext}").write_bytes(data)
    job = _job_new(photo_id)
    background_tasks.add_task(run_upload_job, job["job_id"], photo_id,
                              (text or "").strip()[:200] or None)
    return {"job_id": job["job_id"], "status": "queued", "stage": "uploaded"}


STAGES = ("uploaded", "looking", "placing", "connecting", "done")
_durations = []
_durations_lock = threading.Lock()


def _record_duration(job):
    try:
        start = datetime.fromisoformat(job["created_at"])
        end = datetime.fromisoformat(job["updated_at"])
        with _durations_lock:
            _durations.append(max(0.0, (end - start).total_seconds()))
            del _durations[:-20]
    except Exception:
        pass


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "unknown job id")
        job = dict(job)
    try:
        start = datetime.fromisoformat(job["created_at"])
    except Exception:
        start = None
    if job["status"] in ("done", "error"):
        eta = 0.0
        try:
            end = datetime.fromisoformat(job["updated_at"])
            elapsed = max(0.0, (end - start).total_seconds()) if start else 0.0
        except Exception:
            elapsed = 0.0
    elif start is not None:
        elapsed = max(0.0, (datetime.now(timezone.utc) - start).total_seconds())
        with _durations_lock:
            eta = round(sum(_durations) / len(_durations), 1) if _durations else 60.0
    else:
        elapsed, eta = 0.0, 60.0
    job["stage_index"] = STAGES.index(job["stage"]) if job["stage"] in STAGES else 0
    job["stage_count"] = len(STAGES)
    job["elapsed_seconds"] = round(elapsed, 1)
    job["eta_seconds"] = eta
    return job


PLACES_PATH = ROOT / "data" / "places.json"
_places_cache = None
_places_lock = threading.Lock()


def load_places():
    """data/places.json, cached in memory (restart picks up edits)."""
    global _places_cache
    with _places_lock:
        if _places_cache is None:
            try:
                _places_cache = json.loads(PLACES_PATH.read_text(encoding="utf-8"))
            except Exception:
                _places_cache = {}
        return _places_cache


@app.get("/api/place/{place_key:path}")
def place_page(place_key: str, collection: str = "world"):
    key = (place_key or "").strip().strip("/").lower()
    places = load_places()
    info = places.get(key)
    if not info:
        raise HTTPException(status_code=404, detail="I could not find that place.")
    if collection not in ("world", "personal", "both"):
        raise HTTPException(status_code=400,
                            detail="collection must be 'world', 'personal' or 'both'.")
    want_personal = collection in ("personal", "both")
    try:
        rows = (get_sb().table("photos")
                .select("photo_id,collection,file,caption,viewpoint,place_key,record")
                .order("photo_id").execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"place lookup failed: {e}")
    counted = []
    for r in rows:
        inf = (r.get("record") or {}).get("inferred") or {}
        if (r.get("place_key") or inf.get("place_key")) == key:
            counted.append(r)
            continue
        for lm in inf.get("landmarks") or []:
            if (isinstance(lm, dict) and lm.get("key") == key
                    and lm.get("status") == "confirmed"):
                counted.append(r)
                break
    shown = [r for r in counted
             if r.get("collection") == "world"
             or (want_personal and r.get("collection") == "personal")]
    by_viewpoint = {}
    for r in shown:
        by_viewpoint.setdefault(r.get("viewpoint") or "unknown", []).append(
            {"photo_id": r["photo_id"], "collection": r.get("collection"),
             "src": photo_url(r.get("file")), "caption": r.get("caption")})
    signs = {}
    for r in shown:
        seen_here = set()
        vt = ((r.get("record") or {}).get("observed") or {}).get("visible_text") or []
        for s in vt:
            if not isinstance(s, dict):
                continue
            if str(s.get("legibility") or "").lower() != "clear":
                continue
            t = str(s.get("text") or "").strip()
            if not t:
                continue
            n = t.casefold()
            e = signs.setdefault(n, {"text": t, "photos": 0})
            if n not in seen_here:
                seen_here.add(n)
                e["photos"] += 1
    sign_list = sorted(({"text": e["text"], "photos": e["photos"]}
                        for e in signs.values()),
                       key=lambda d: (-d["photos"], d["text"]))
    credits, seen_c = [], set()
    for r in shown:
        prov = ((r.get("record") or {}).get("provided")) or {}
        if not prov.get("author") and not prov.get("license"):
            continue
        if (prov.get("author"), prov.get("license")) in seen_c:
            continue
        seen_c.add((prov.get("author"), prov.get("license")))
        credits.append({"author": prov.get("author"), "license": prov.get("license"),
                        "source_url": prov.get("source_url")})
    related = {}
    for r in shown:
        inf = (r.get("record") or {}).get("inferred") or {}
        seen_rel = set()
        for lm in inf.get("landmarks") or []:
            if not isinstance(lm, dict) or not lm.get("key") or lm.get("key") == key:
                continue
            e = related.setdefault(lm["key"], {"key": lm["key"],
                                               "name": lm.get("name"), "photos": 0, "via": set()})
            if lm["key"] not in seen_rel:
                seen_rel.add(lm["key"])
                e["photos"] += 1
            e["via"].add("landmark")
            if not e["name"]:
                e["name"] = places.get(lm["key"], {}).get("name") or lm.get("name")
        tf = inf.get("taken_from") or {}
        if isinstance(tf, dict) and tf.get("key") and tf.get("key") != key:
            e = related.setdefault(tf["key"], {"key": tf["key"],
                                               "name": tf.get("name"), "photos": 0, "via": set()})
            if tf["key"] not in seen_rel:
                seen_rel.add(tf["key"])
                e["photos"] += 1
            e["via"].add("taken_from")
            if not e["name"]:
                e["name"] = places.get(tf["key"], {}).get("name") or tf.get("name")
    rel_list = sorted(({"key": e["key"], "name": e["name"], "photos": e["photos"],
                        "via": sorted(e["via"])} for e in related.values()),
                      key=lambda d: (-d["photos"], d["key"]))
    parts = key.split("/")
    hierarchy = []
    for i in range(1, len(parts)):
        pre = "/".join(parts[:i])
        if pre in places:
            hierarchy.append({"key": pre, "name": places[pre].get("name")})
    hierarchy.append({"key": key, "name": info.get("name")})
    return {"key": key, "name": info.get("name"), "type": info.get("type"),
            "aliases": info.get("aliases") or [], "hierarchy": hierarchy,
            "collection": collection, "total_photos": len(shown),
            "by_viewpoint": by_viewpoint, "signs": sign_list,
            "credits": credits, "related": rel_list}


# ----- the bridge: matches from the other collection, grouped by reason -----
BRIDGE_GROUPS = (("same_place", "Same place"), ("another_angle", "Another angle"),
                 ("taken_from_here", "Taken from here"), ("similar_look", "Looks similar"))
# Reasons that count as a real place-based connection. similar_look is shown
# only in the photo detail view, never in /api/connected or its summary.
PLACE_LINKED = ("same_place", "another_angle", "taken_from_here")
BRIDGE_COLS = ("photo_id,collection,file,caption,place_key,place_name,taken_from_key,"
               "landmark_keys,viewpoint,embedding")


def _bridge_src(photo_id):
    try:
        rows = (get_sb().table("photos").select(BRIDGE_COLS)
                .eq("photo_id", photo_id).execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"photo lookup failed: {e}")
    if not rows:
        raise HTTPException(status_code=404, detail="I could not find that photo.")
    return rows[0]


def _bridge_candidates(src_emb, other, exclude_id):
    try:
        return (get_sb().rpc("search_photos", {
            "query_embedding": src_emb, "match_count": 60,
            "filter_collection": other, "exclude_ids": [exclude_id],
        }).execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"bridge search failed: {e}")


def _coerce_embedding(emb):
    return json.loads(emb) if isinstance(emb, str) else emb


def _score_bridge(src, cands):
    scored = []
    for r in cands:
        score, reasons, subject, different, taken = score_against(src, r, False)
        if subject and different:
            reason = "another_angle"
        elif subject:
            reason = "same_place"
        elif taken:
            reason = "taken_from_here"
        else:
            reason = "similar_look"
        scored.append({"reason": reason, "score": score, "reasons": reasons, "row": r})
    return scored


def _bridge_item(s):
    """A standard result row plus its reason text."""
    r = public_row(s["row"])
    r["src"] = photo_url(s["row"].get("file"))
    r["place"] = s["row"].get("place_name")
    r["score"] = s["score"]
    r["reasons"] = s["reasons"]
    r["reason_text"] = "; ".join(s["reasons"])
    return r


def _bridge_groups(scored, limit):
    groups = {}
    for reason, _label in BRIDGE_GROUPS:
        members = sorted((s for s in scored if s["reason"] == reason),
                         key=lambda s: s["score"], reverse=True)[:limit]
        groups[reason] = [_bridge_item(s) for s in members]
    attach_credits([i for g in groups.values() for i in g])
    return groups


@app.get("/api/bridge/{photo_id}")
def bridge(photo_id: str, limit: int = 4):
    limit = max(1, min(int(limit), 8))
    src = _bridge_src(photo_id)
    other = "personal" if src["collection"] == "world" else "world"
    cands = _bridge_candidates(_coerce_embedding(src["embedding"]), other, src["photo_id"])
    groups = _bridge_groups(_score_bridge(src, cands), limit)
    kept = sum(len(g) for g in groups.values())
    used = sum(1 for g in groups.values() if g)
    return {"photo_id": src["photo_id"], "collection": src["collection"],
            "other_collection": other,
            "labels": {reason: label for reason, label in BRIDGE_GROUPS},
            "groups": groups,
            "trace": [{"step": "searched",
                       "detail": f"Compared {src['photo_id']} with {len(cands)} candidates "
                                 f"from the {other} collection."},
                      {"step": "answered",
                       "detail": f"Kept {kept} matches in {used} groups."}]}


def _identify_shape(photo_id):
    """Place verdict for one photo, data-only (no model call)."""
    try:
        rows = (get_sb().table("photos")
                .select("photo_id,collection,place_key,record,embedding")
                .eq("photo_id", photo_id).execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"photo lookup failed: {e}")
    if not rows:
        raise HTTPException(status_code=404, detail="I could not find that photo.")
    r = rows[0]
    inf = ((r.get("record") or {}).get("inferred") or {})
    place = inf.get("place") or None
    cands = [{"name": c.get("name"), "key": c.get("key"),
              "confidence": c.get("confidence"), "evidence": c.get("evidence") or []}
             for c in (inf.get("place_candidates") or [])[:3]]
    if not cands:
        cands = [{"name": lm.get("name"), "key": lm.get("key"),
                  "confidence": lm.get("confidence"), "evidence": lm.get("evidence") or []}
                 for lm in (inf.get("landmarks") or [])[:3]]
    nearest = []
    if place and place.get("key"):
        try:
            q = (get_sb().table("photos").select("photo_id,file,caption,place_name")
                 .eq("collection", "world").eq("place_key", place["key"])
                 .neq("photo_id", photo_id).limit(5).execute().data or [])
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"identify search failed: {e}")
        nearest = [{"photo_id": w["photo_id"], "src": photo_url(w.get("file")),
                    "caption": w.get("caption"), "place": w.get("place_name")} for w in q]
    else:
        for w in _bridge_candidates(_coerce_embedding(r["embedding"]), "world", photo_id)[:5]:
            nearest.append({"photo_id": w["photo_id"], "src": photo_url(w.get("file")),
                            "caption": w.get("caption"), "place": w.get("place_name")})
    return {"photo_id": r["photo_id"], "primary": _place_shape(place),
            "candidates": cands, "nearest_world_photos": nearest}


@app.get("/api/identify/{photo_id}")
def identify(photo_id: str):
    return _identify_shape(photo_id.strip())


_connected = {"updated_at": None, "photos": None, "summary": None}
_connected_lock = threading.Lock()
_CONNECTED_LIMIT = 8


def refresh_connected():
    """Rebuild the in-memory per-personal-photo bridge index. Returns the snapshot."""
    try:
        rows = (get_sb().table("photos").select(BRIDGE_COLS)
                .eq("collection", "personal").order("photo_id").execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"connected index failed: {e}")
    photos = []
    for src in rows:
        cands = _bridge_candidates(_coerce_embedding(src["embedding"]), "world", src["photo_id"])
        matches = []
        for s in sorted(_score_bridge(src, cands), key=lambda s: s["score"], reverse=True):
            item = _bridge_item(s)
            item["reason"] = s["reason"]
            matches.append(item)
        attach_credits(matches)
        photos.append({"photo_id": src["photo_id"], "src": photo_url(src.get("file")),
                       "caption": src.get("caption"), "matches": matches})
    linked = [m for p in photos for m in p["matches"] if m["reason"] in PLACE_LINKED]
    places = {m.get("place_key") for m in linked if m.get("place_key")}
    snap = {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "photos": photos,
            "summary": {"photos_connected": sum(
                            1 for p in photos
                            if any(m["reason"] in PLACE_LINKED for m in p["matches"])),
                        "places_connected": len(places),
                        "matches_total": len(linked)}}
    with _connected_lock:
        _connected.clear()
        _connected.update(snap)
    return snap


@app.get("/api/connected")
def connected(limit: int = 2):
    limit = max(1, min(int(limit), _CONNECTED_LIMIT))
    with _connected_lock:
        snap = dict(_connected) if _connected["photos"] is not None else None
    if snap is None:
        snap = refresh_connected()
    out = []
    for p in snap["photos"]:
        groups = {}
        for reason, _label in BRIDGE_GROUPS:
            if reason not in PLACE_LINKED:
                continue  # similar_look lives only in the photo detail view
            groups[reason] = [m for m in p["matches"] if m["reason"] == reason][:limit]
        linked = [m for m in p["matches"] if m["reason"] in PLACE_LINKED]
        out.append({"photo": {"photo_id": p["photo_id"], "src": p["src"],
                              "caption": p["caption"]},
                    "groups": groups, "match_count": len(linked)})
    return {"updated_at": snap["updated_at"], "count": len(out),
            "summary": snap["summary"], "photos": out}
