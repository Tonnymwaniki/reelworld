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
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, Field
from supabase import create_client

import annotate as annotate_mod
import chat as chat_module
import llm as llm_mod
import place_pass as place_pass_mod
from chat import (ANSWER_PROMPT, EMPTY_SPEC, Engine, extract_json)
from retrieval import is_specific, meta_for, score_against, search_text
from story_engine import StoryError

ROOT = Path(__file__).resolve().parent.parent
PHOTOS_DIR = ROOT / "data" / "photos"
FRONTEND_DIR = ROOT / "frontend"
INDEX_HTML = FRONTEND_DIR / "index.html"
# Hash views the app may fetch. Anything else under frontend/ (notably
# frontend/design/) is never served, so exports stay out of the page bundle.
VIEW_NAMES = ("home", "photo", "add", "connected", "place", "stories",
              "builder", "showcase", "library", "browse",
              "404", "about", "credits")

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
_turn_lock = threading.RLock()  # one turn at a time; turns mutate session state

# Heavy/internal row fields the API never sends to clients.
DROP_KEYS = ("embedding", "lex")


def get_engine(session_id: str) -> Engine:
    sid = (session_id or "").strip() or "default"
    with _sessions_lock:
        eng = _sessions.get(sid)
        if eng is None:
            eng = Engine()
            eng.session_id = sid
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
_clients_lock = threading.Lock()


def get_sb():
    """Shared Supabase client for the /api/* read endpoints."""
    global _sb
    with _clients_lock:
        if _sb is None:
            _sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
        return _sb


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


@app.post("/api/llm/probe")
def llm_probe(request: Request = None, response: Response = None):
    """Re-probe whether the primary provider accepts images.

    Returns the provider names/hosts plus the saved capability result.
    No keys are ever returned."""
    _guard_or_429(request, response)
    cfg = llm_mod.config()
    caps = llm_mod.probe_images()
    return {
        "primary": {"name": llm_mod.provider_name(cfg["primary"]["base_url"]),
                    "model": cfg["primary"]["model"],
                    "host": llm_mod.provider_host(cfg["primary"]["base_url"])},
        "fallback": {"name": llm_mod.provider_name(cfg["fallback"]["base_url"]),
                     "model": cfg["fallback"]["model"],
                     "host": llm_mod.provider_host(cfg["fallback"]["base_url"])},
        "images": caps,
    }


@app.get("/api/llm/status")
def llm_status():
    """Provider status: names, hosts, models, speeds, success rate,
    today's tokens, budget left, last error, image capability.
    Makes no model calls; never returns keys."""
    return llm_mod.status()


DEMO_MODE = os.getenv("DEMO_MODE", "true").strip().lower() == "true"
DEMO_CODE = os.getenv("DEMO_CODE", "")
FEATURE_OUTLINES = os.getenv("FEATURE_OUTLINES", "true").strip().lower() == "true"
ENABLE_SWAHILI = os.getenv("ENABLE_SWAHILI", "false").strip().lower() == "true"


def _demo_unlocked(request: Request) -> bool:
    if not DEMO_MODE:
        return True
    if not DEMO_CODE:
        return False
    return request.headers.get("x-demo-code", "") == DEMO_CODE


# ----- expensive-endpoint guard (model budget + visitor rate limits) -----

RESTING_TEXT = ("Reel is resting for a moment. Browse, place pages and the "
                "saved tour still work. Try again soon.")
VISITOR_COOKIE = "rw_visitor"

_rate_lock = threading.Lock()
_rate_hits = {}  # visitor -> {"minute": [ts...], "day": [ts...]}


def _visitor_id(request):
    """IP plus session cookie (no side effects)."""
    ip = request.client.host if request.client else "unknown"
    try:
        cookie = request.cookies.get(VISITOR_COOKIE, "") or ""
    except Exception:
        cookie = ""
    return f"{ip}:{cookie or 'none'}"


def _rate_settings():
    """Live (per-minute, per-day) request limits."""
    per_min = llm_mod.setting("REQUESTS_PER_MINUTE", 6)
    per_day = llm_mod.setting("REQUESTS_PER_DAY", 60)
    try:
        per_min = int(per_min)
    except (TypeError, ValueError):
        per_min = 6
    try:
        per_day = int(per_day)
    except (TypeError, ValueError):
        per_day = 60
    return max(1, per_min), max(1, per_day)


def _guard_expensive(request, response):
    """Rate + budget guard for model-calling endpoints.

    Returns None when allowed, else minute/day/budget. Mints the visitor
    cookie when missing. No limits at all when DEMO_MODE is false.
    A None request (direct in-process call, no HTTP visitor) skips
    rate accounting but still honors the budget."""
    if request is None:
        if not DEMO_MODE:
            return None
        if llm_mod.tokens_today() >= llm_mod.config()["budget"]:
            return "budget"
        return None
    try:
        has_cookie = request.cookies.get(VISITOR_COOKIE)
    except Exception:
        has_cookie = None
    if not has_cookie:
        try:
            response.set_cookie(VISITOR_COOKIE, uuid.uuid4().hex, samesite="lax")
        except Exception:
            pass
    if not DEMO_MODE:
        return None
    if llm_mod.tokens_today() >= llm_mod.config()["budget"]:
        return "budget"
    mult = 4 if _demo_unlocked(request) else 1
    per_min, per_day = _rate_settings()
    now = time.time()
    with _rate_lock:
        hits = _rate_hits.setdefault(_visitor_id(request), {"minute": [], "day": []})
        hits["minute"] = [t for t in hits["minute"] if now - t < 60]
        hits["day"] = [t for t in hits["day"] if now - t < 86400]
        if len(hits["minute"]) >= per_min * mult:
            return "minute"
        if len(hits["day"]) >= per_day * mult:
            return "day"
        hits["minute"].append(now)
        hits["day"].append(now)
    return None


def _guard_or_429(request, response):
    """_guard_expensive for non-chat endpoints: 429 with the calm message."""
    if _guard_expensive(request, response) is not None:
        raise HTTPException(status_code=429, detail=RESTING_TEXT)


_REST_LIMIT_DETAIL = {
    "minute": "Too many messages in a minute; resting briefly.",
    "day": "The daily message allowance is spent; back tomorrow.",
    "budget": "The daily model budget is spent; Browse, place pages and the saved tour still work.",
}


def _resting_payload(sid, eng, reason):
    """Normal /chat-shaped reply with kind resting (no model call)."""
    try:
        with _turn_lock:
            focus = (eng.state.get("focus") or {}) if eng else {}
            spec = dict(eng.state.get("spec") or {}) if eng else {}
    except Exception:
        focus, spec = {}, {}
    return {
        "session_id": sid,
        "text": RESTING_TEXT,
        "results": [],
        "focus_photo_id": focus.get("photo_id"),
        "spec": {k: spec.get(k) for k in ("query", "collection", "viewpoints",
                                          "max_people", "must_include", "avoid_terms")},
        "kind": "resting",
        "trace": [{"step": "rested",
                   "detail": _REST_LIMIT_DETAIL.get(reason, "Resting briefly.")}],
    }


def _demo_guard(request: Request):
    if _demo_unlocked(request):
        return
    if not DEMO_CODE:
        raise HTTPException(status_code=403, detail="Demo mode: writes are disabled and no demo code is configured.")
    raise HTTPException(status_code=403, detail="Demo mode: this needs the demo code.")


def _collection_counts():
    counts = {"world": None, "personal": None, "places": None, "themes": None}
    try:
        for coll in ("world", "personal"):
            res = (get_sb().table("photos").select("photo_id", count="exact", head=True)
                   .eq("collection", coll).execute())
            counts[coll] = res.count
    except Exception:
        pass
    try:
        rows = (get_sb().table("photos").select("place_key")
                .eq("collection", "world").execute().data or [])
        counts["places"] = len({r.get("place_key") for r in rows if r.get("place_key")})
    except Exception:
        pass
    try:
        manifest = list(csv.DictReader(
            open(ROOT / "data" / "manifest.csv", encoding="utf-8-sig")))
        counts["themes"] = len({(m.get("theme") or "").strip()
                                for m in manifest if (m.get("theme") or "").strip()})
    except Exception:
        pass
    return counts


def _evaluation_text():
    p = ROOT / "docs" / "evaluation.md"
    return p.read_text(encoding="utf-8") if p.exists() else None


@app.get("/api/config")
def api_config():
    return {"demo_mode": DEMO_MODE,
            "outlines_enabled": FEATURE_OUTLINES,
            "swahili_enabled": ENABLE_SWAHILI,
            "counts": _collection_counts(),
            "evaluation": _evaluation_text()}


@app.get("/og-image.png")
def og_image():
    p = FRONTEND_DIR / "og-image.png"
    if not p.exists():
        raise HTTPException(status_code=404, detail="share preview image not built yet")
    return FileResponse(str(p), media_type="image/png")


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request = None, response: Response = None):
    limited = _guard_expensive(request, response)
    if limited is not None:
        _sid = req.session_id.strip() or "default"
        return _resting_payload(_sid, get_engine(_sid), limited)
    sid = req.session_id.strip() or "default"
    try:
        eng = get_engine(sid)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"engine unavailable: {e}")
    with _turn_lock:
        try:
            out = eng.turn(req.message)
        except llm_mod.LLMBudgetSpent:
            return _resting_payload(sid, eng, "budget")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"search failed: {e}")
        return _chat_payload(sid, eng, out)


def _chat_payload(sid, eng, out):
    """Same bookkeeping as chat.main(): new results become last/focus."""
    with _turn_lock:
        if out.get("results"):
            eng.state["last"] = out["results"]
            eng.state["focus"] = out["results"][0]
        focus = eng.state.get("focus") or {}
        spec = eng.state.get("spec") or {}
    rows = [public_row(r) for r in out.get("results", [])]
    attach_credits(rows)
    trace = list(out.get("trace", []))
    calls = getattr(eng, "turn_llm", None) or []
    if calls:
        provs = ", ".join(sorted({c["provider"] for c in calls}))
        secs = sum(c["seconds"] for c in calls)
        trace.append({"step": "model",
                      "detail": f"Reasoning by {provs} in {secs:.1f}s ({len(calls)} calls)."})
    return {
        "session_id": sid,
        "text": out.get("text", ""),
        "results": rows,
        "focus_photo_id": focus.get("photo_id"),
        "spec": {k: spec.get(k) for k in ("query", "collection", "viewpoints",
                                          "max_people", "must_include", "avoid_terms")},
        "kind": out.get("kind", "ok"),
        "trace": trace,
    }


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/chat/stream")
def chat_stream(req: ChatRequest, request: Request = None,
                response: Response = None):
    """Same turn as POST /chat, streamed: `step` events (understood /
    searched / checked / wrote) as each stage really runs, then one
    `result` event with the full /chat payload. Mid-stream failures
    arrive as an `error` event."""
    limited = _guard_expensive(request, response)
    if limited is not None:
        def gen_resting():
            _sid = req.session_id.strip() or "default"
            yield _sse("result", _resting_payload(_sid, get_engine(_sid), limited))
        return StreamingResponse(gen_resting(), media_type="text/event-stream")
    sid = req.session_id.strip() or "default"
    try:
        eng = get_engine(sid)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"engine unavailable: {e}")

    def gen():
        try:
            with _turn_lock:
                for item in eng.turn_stream(req.message):
                    if item[0] == "step":
                        yield _sse("step", {"step": item[1], "detail": item[2]})
                    else:
                        yield _sse("result", _chat_payload(sid, eng, item[1]))
        except llm_mod.LLMBudgetSpent:
            yield _sse("result", _resting_payload(sid, eng, "budget"))
        except Exception as e:
            yield _sse("error", {"detail": f"search failed: {e}"})

    return StreamingResponse(gen(), media_type="text/event-stream")


LICENSE_DEEDS = {
    "CC BY-SA 4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC BY-SA 3.0": "https://creativecommons.org/licenses/by-sa/3.0/",
    "CC BY-SA 2.0": "https://creativecommons.org/licenses/by-sa/2.0/",
    "CC BY 4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC BY 2.0": "https://creativecommons.org/licenses/by/2.0/",
    "CC0": "https://creativecommons.org/publicdomain/zero/1.0/",
}
LICENSE_ORDER = (("cc-by-sa", "CC BY-SA 4.0"), ("cc-by", "CC BY 4.0"),
                 ("cc0", "Public Domain / CC0"))


def _license_key(lic):
    low = (lic or "").lower()
    if "by-sa" in low or "by_sa" in low:
        return "cc-by-sa"
    if low.startswith("cc0") or "public domain" in low:
        return "cc0"
    if re.search(r"\bby\b", low):
        return "cc-by"
    return "other"


def _area_of_key(key):
    parts = [p for p in str(key or "").split("/") if p]
    if len(parts) >= 3:
        return " / ".join(p.replace("-", " ").title() for p in parts[1:-1])
    return ""


@app.get("/api/credits")
def api_credits():
    """Per-photo credits for the world collection: data/manifest.csv
    (author, license, source) joined with stored captions and places."""
    try:
        manifest = list(csv.DictReader(
            open(ROOT / "data" / "manifest.csv", encoding="utf-8-sig")))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"cannot read manifest: {e}")
    try:
        db = (get_sb().table("photos").select("photo_id,file,record")
              .eq("collection", "world").execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"credits lookup failed: {e}")
    by_base = {}
    for r in db:
        by_base.setdefault((r.get("file") or "").replace("\\", "/").split("/")[-1].lower(), r)
    rows, lic_counts = [], {}
    for m in manifest:
        base = (m.get("file") or "").replace("\\", "/").split("/")[-1].lower()
        d = by_base.get(base, {})
        rec = d.get("record") or {}
        obs, inf = rec.get("observed") or {}, rec.get("inferred") or {}
        place = inf.get("place") or {}
        lic = (m.get("license") or "").strip()
        key = _license_key(lic)
        lic_counts[key] = lic_counts.get(key, 0) + 1
        cap = str(obs.get("caption") or m.get("title") or "").strip()
        rows.append({
            "photo_id": d.get("photo_id") or base.rsplit(".", 1)[0],
            "src": photo_url(d.get("file")) if d.get("file") else None,
            "subject": place.get("name") or (cap[:70] if cap else d.get("photo_id")),
            "area": _area_of_key(place.get("key")),
            "scene": str((obs.get("scene") or {}).get("type") or ""),
            "author": (m.get("author") or "Unknown").strip(),
            "license": lic or "Unknown",
            "license_key": key,
            "deed_url": LICENSE_DEEDS.get(lic),
            "source_url": (m.get("source_url") or "").strip() or None,
        })
    rows.sort(key=lambda r: r["photo_id"])
    licenses = [{"key": k, "label": lbl, "count": lic_counts.get(k, 0)}
                for k, lbl in LICENSE_ORDER]
    if lic_counts.get("other"):
        licenses.append({"key": "other", "label": "Other",
                         "count": lic_counts["other"]})
    authors = {r["author"] for r in rows} - {"Unknown"}
    return {"count": len(rows), "photographers": len(authors),
            "licenses": licenses, "rows": rows}


FLAG_REASONS = ("wrong_place", "wrong_text", "wrong_features",
                "not_relevant", "other")


class FlagRequest(BaseModel):
    target: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    note: Optional[str] = None
    route: Optional[str] = None


_flags_lock = threading.Lock()


@app.post("/api/flag")
def api_flag(req: FlagRequest):
    """Anonymous correction flag, appended to data/flags.jsonl (git-ignored)
    for human review. Not demo-gated: flagging is always allowed."""
    if req.reason not in FLAG_REASONS:
        raise HTTPException(status_code=400,
                            detail=f"reason must be one of: {', '.join(FLAG_REASONS)}")
    p = ROOT / "data" / "flags.jsonl"
    with _flags_lock:
        seq = sum(1 for _ in open(p, encoding="utf-8")) if p.exists() else 0
        fid = f"FLG-{datetime.now(timezone.utc):%Y%m%d}-{seq + 1:04d}"
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": fid, "ts": datetime.now(timezone.utc).isoformat(),
                                "target": req.target.strip()[:200],
                                "reason": req.reason,
                                "note": (req.note or "").strip()[:140] or None,
                                "route": (req.route or "").strip()[:120] or None},
                               ensure_ascii=False) + "\n")
    return {"ok": True, "id": fid}


class OutlineRequest(BaseModel):
    photo_id: str = Field(min_length=1)
    prompt: Optional[str] = None


@app.post("/api/outline")
def api_outline(req: OutlineRequest):
    """Subject outlines via SAM 3.1 (Meta Model API)."""



    if not FEATURE_OUTLINES:
        raise HTTPException(status_code=501, detail="Outlines are not enabled (FEATURE_OUTLINES=false).")
    from sam import SAM_MODEL, meta_key, outline_request
    if not meta_key():
        raise HTTPException(status_code=501, detail="Outlines need META_API_KEY in .env.")
    pid = req.photo_id.strip()
    try:
        rows = (get_sb().table("photos").select("record,file")
                .eq("photo_id", pid).execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"photo lookup failed: {e}")
    if not rows:
        raise HTTPException(status_code=404, detail="I could not find that photo.")
    prompt = (req.prompt or "").strip()
    if not prompt:
        try:
            ents = (rows[0]["record"].get("observed") or {}).get("entities") or []
            prompt = (ents[0].get("label") or "") if ents else ""
        except (AttributeError, IndexError, KeyError):
            prompt = ""
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required (no entity label to default to).")
    f = rows[0].get("file") or ""
    p = Path(f) if os.path.isabs(f) else ROOT / f
    try:
        photo_bytes = p.read_bytes()
    except OSError:
        raise HTTPException(status_code=502, detail="photo file is missing on disk.")
    mime = "image/png" if str(p).lower().endswith(".png") else "image/jpeg"
    try:
        matches, _raw = outline_request(photo_bytes, mime, prompt)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"photo_id": pid, "prompt": prompt, "model": SAM_MODEL,
            "count": len(matches), "matches": matches}



TOUR_STEPS = ("step1", "step2", "step3")


@app.get("/tour/{name}.json")
def tour_step(name: str):
    if name not in TOUR_STEPS:
        raise HTTPException(status_code=404, detail="unknown tour step")
    p = ROOT / "data" / "tour" / f"{name}.json"
    if not p.exists():
        raise HTTPException(status_code=404,
                            detail="tour not recorded yet; run scripts/record_tour.py")
    return FileResponse(str(p), media_type="application/json")


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
def ask(req: AskRequest, request: Request = None, response: Response = None):
    _guard_or_429(request, response)
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
    ckey = llm_mod.cache_key("ask", [pid], req.question, [rec])
    hit = llm_mod.cache_get(ckey)
    if hit is not None:
        hit["trace"] = (hit.get("trace") or []) + [
            {"step": "cache", "detail": "Answered earlier from the cache."}]
        return hit
    try:
        res = llm_mod.ask(ANSWER_PROMPT.format(
            record=json.dumps(compact, ensure_ascii=False), question=req.question),
            purpose="ask", session_id=req.session_id)
    except llm_mod.LLMBudgetSpent:
        raise HTTPException(status_code=429, detail=RESTING_TEXT)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"answer failed: {e}")
    answer = res["text"].strip()
    via = f" ({res['provider']}, {res['seconds']}s)"
    if not any(p in answer.lower() for p in ANNOTATION_MISS):
        out = {"photo_id": pid, "question": req.question, "answer": answer,
               "source": "annotation", "note": None,
               "trace": [{"step": "answered",
                          "detail": f"Answered from the stored annotation{via}."}]}
        llm_mod.cache_put(ckey, out)
        return out
    img_path = ROOT / str(rows[0].get("file") or "")
    if not img_path.exists():
        out = {"photo_id": pid, "question": req.question, "answer": answer,
               "source": "annotation", "note": None,
               "trace": [{"step": "answered",
                          "detail": f"Answered from the stored annotation{via}."}]}
        llm_mod.cache_put(ckey, out)
        return out
    try:
        res = llm_mod.ask(IMAGE_ANSWER_PROMPT.format(
            record=json.dumps(compact, ensure_ascii=False), question=req.question),
            image_path=str(img_path), purpose="ask", session_id=req.session_id)
    except llm_mod.LLMBudgetSpent:
        raise HTTPException(status_code=429, detail=RESTING_TEXT)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"image look failed: {e}")
    img_answer = " ".join(res["text"].strip().split()[:120])
    via = f" ({res['provider']}, {res['seconds']}s)"
    out = {"photo_id": pid, "question": req.question, "answer": img_answer,
           "source": "image", "note": "This answer came from looking at the photo again.",
           "trace": [{"step": "reinspected",
                      "detail": "The stored annotation could not answer, so I looked at the photo again."},
                     {"step": "answered",
                      "detail": f"Answered from looking at the photo again{via}."}]}
    llm_mod.cache_put(ckey, out)
    return out


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
def compare(req: CompareRequest, request: Request = None,
            response: Response = None):
    _guard_or_429(request, response)
    if req.photo_a == req.photo_b:
        raise HTTPException(status_code=400, detail="photo_a and photo_b must be different.")
    rec_a = _record_or_404(req.photo_a)
    rec_b = _record_or_404(req.photo_b)
    ckey = llm_mod.cache_key("compare", [req.photo_a, req.photo_b],
                             req.question, [rec_a, rec_b])
    hit = llm_mod.cache_get(ckey)
    if hit is not None:
        hit["trace"] = (hit.get("trace") or []) + [
            {"step": "cache", "detail": "Answered earlier from the cache."}]
        return hit
    try:
        res = llm_mod.ask(COMPARE_PROMPT.format(
            photo_a=req.photo_a,
            record_a=json.dumps(_compact_record(rec_a), ensure_ascii=False),
            photo_b=req.photo_b,
            record_b=json.dumps(_compact_record(rec_b), ensure_ascii=False),
            question=req.question or "(no question: summarise the main differences)"),
            purpose="compare")
    except llm_mod.LLMBudgetSpent:
        raise HTTPException(status_code=429, detail=RESTING_TEXT)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"compare failed: {e}")
    try:
        data = extract_json(res["text"])
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
    out = {"photo_a": req.photo_a, "photo_b": req.photo_b,
           "question": req.question, "answer": answer,
           "differences": diffs, "source": "annotation",
           "trace": [{"step": "compared",
                      "detail": ("Compared the two stored annotations "
                                 f"({res['provider']}, {res['seconds']}s).")}]}
    llm_mod.cache_put(ckey, out)
    return out


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

STORY_HEADING_PROMPT = """A photo-story chapter heading contradicts the photos chosen for it.
Old heading: {heading}
Problem: {problem}
What the chapter photos actually show (facts from their stored records, one line per photo):
{facts}
Write a replacement heading of at most 8 words that these photos support, or reply {{"drop": true}} if no honest heading fits. Draw only on the facts above; add nothing.
Return ONE JSON object and nothing else: {{"heading": "..."}} or {{"drop": true}}"""


# Closed-vocabulary claim checks: words in a planned heading against the
# stored facts (scene time_of_day, setting, row viewpoint) of its photos.
TIME_GROUPS = {"night": "night", "nighttime": "night",
               "evening": "twilight", "dawn": "twilight",
               "daytime": "day", "morning": "day"}
VP_GROUPS = {"aerial": "aerial", "elevated": "elevated",
             "ground_level": "ground", "water_level": "ground",
             "interior": "interior"}
CLAIM_RES = {
    "night": re.compile(r"\bnight\b|\bmidnight\b|\bafter dark\b|\bnight-?time\b"),
    "day": re.compile(r"\bday-?time\b|\bday-?light\b|\bmorning\b|\bafternoon\b"
                      r"|\bmidday\b|\bnoon\b|\bday\b"),
    "twilight": re.compile(r"\bdusk\b|\bdawn\b|\btwilight\b|\bsunset\b|\bsunrise\b"
                           r"|\bevening\b|\bgolden\b|\bsundown\b"),
    "indoor": re.compile(r"\bindoors?\b|\binterior\b|\binside\b"),
    "outdoor": re.compile(r"\boutdoors?\b|\bopen-?air\b|\bstreets?\b|\bavenue\b|\broad\b"),
    "above": re.compile(r"\baerial\b|\bfrom above\b|\bbird'?s?[ -]?eye\b|\babove\b"
                      r"|\belevated\b"),
    "ground": re.compile(r"\bstreet[ -]?level\b|\bground[ -]?level\b|\beye[ -]?level\b"),
}


def _words(vals):
    uniq = list(dict.fromkeys(vals))
    if len(uniq) == 1:
        return uniq[0]
    return ", ".join(uniq[:-1]) + " and " + uniq[-1]


def _photo_fact(row, compact):
    scene = (compact.get("observed") or {}).get("scene") or {}
    setting = str(scene.get("setting") or "").lower()
    return {
        "time": TIME_GROUPS.get(str(scene.get("time_of_day") or "").lower()),
        "setting": setting if setting in ("outdoor", "indoor", "mixed") else None,
        "viewpoint": VP_GROUPS.get(row.get("viewpoint")),
    }


def _heading_problems(heading, facts):
    """Plain-language contradictions between heading claims and photo facts.
    A claim contradicts only when NO photo supports it and at least one
    photo positively opposes it; unknown values abstain."""
    h = heading.lower()
    problems = []
    times = [f["time"] for f in facts if f["time"]]
    if CLAIM_RES["night"].search(h) and times and "night" not in times:
        problems.append(f"claims night but the photos are {_words(times)}")
    if CLAIM_RES["day"].search(h) and times and not (set(times) & {"day", "twilight"}):
        problems.append(f"claims daytime but the photos are {_words(times)}")
    if CLAIM_RES["twilight"].search(h) and times and not (set(times) & {"twilight", "night"}):
        problems.append(f"claims dusk/evening but the photos are {_words(times)}")
    settings = [f["setting"] for f in facts if f["setting"]]
    if CLAIM_RES["indoor"].search(h) and settings and not (set(settings) & {"indoor", "mixed"}):
        problems.append(f"claims indoors but the photos are {_words(settings)}")
    if CLAIM_RES["outdoor"].search(h) and settings and not (set(settings) & {"outdoor", "mixed"}):
        problems.append(f"claims outdoors but the photos are {_words(settings)}")
    vps = [f["viewpoint"] for f in facts if f["viewpoint"]]
    if CLAIM_RES["above"].search(h) and vps and not (set(vps) & {"aerial", "elevated"}):
        problems.append(f"claims a view from above but the photos are {_words(vps)}")
    if CLAIM_RES["ground"].search(h) and vps and not (set(vps) & {"ground", "elevated", "interior"}):
        problems.append(f"claims street level but the photos are {_words(vps)}")
    return problems


def _photo_brief(row, compact):
    obs = compact.get("observed") or {}
    ents = sorted(obs.get("entities") or [], key=lambda e: e.get("salience", 0), reverse=True)
    things = ", ".join(e.get("label") for e in ents[:4] if e.get("label"))
    f = _photo_fact(row, compact)
    bits = [f"{k} {v}" for k, v in
            (("time", f["time"]), ("setting", f["setting"]), ("view", f["viewpoint"])) if v]
    cap = str(obs.get("caption") or "")[:200]
    return f"{row['photo_id']} ({'; '.join(bits)}; shows: {things or 'nothing notable'}): {cap}"


def _rewrite_heading(heading, problem, briefs):
    try:
        data = _llm_json(STORY_HEADING_PROMPT.format(
            heading=heading, problem=problem, facts="\n".join(briefs)),
            0.2, 4000, tries=2)
    except llm_mod.LLMBudgetSpent:
        raise
    except Exception:
        return None
    if data.get("drop"):
        return None
    return str(data.get("heading") or "").strip() or None


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
            res = llm_mod.ask(prompt, max_tokens=max_tokens, temperature=temperature,
                              purpose="story")
            return extract_json(res["text"])
        except llm_mod.LLMBudgetSpent:
            raise
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


@app.post("/api/story")
def story(req: StoryRequest, request: Request = None,
          response: Response = None):
    """A small agent: plan chapters, run a real engine search per chapter,
    pick 1-2 unused photos each, and write record-only chapter text."""
    _guard_or_429(request, response)
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
    except llm_mod.LLMBudgetSpent:
        raise HTTPException(status_code=429, detail=RESTING_TEXT)
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
        try:
            compacts = [(r, _compact_record(_record_or_404(r["photo_id"]))) for r in picked]
        except Exception:
            trace.append({"step": "dropped", "detail":
                          f"Dropped {heading!r}: a photo record went missing."})
            continue
        facts = [_photo_fact(r, c) for r, c in compacts]
        problems = _heading_problems(heading, facts)
        if problems:
            problem = "; ".join(problems)
            try:
                new_heading = _rewrite_heading(
                    heading, problem, [_photo_brief(r, c) for r, c in compacts])
            except llm_mod.LLMBudgetSpent:
                raise HTTPException(status_code=429, detail=RESTING_TEXT)
            if new_heading and not _heading_problems(new_heading, facts):
                trace.append({"step": "rewrote", "detail":
                              f"Rewrote {heading!r} as {new_heading!r}: {problem}."})
                heading = new_heading
            else:
                trace.append({"step": "dropped", "detail":
                              f"Dropped {heading!r}: {problem}; no honest heading fit."})
                continue
        text, attempt_sets = None, [picked, picked[:1]]
        for att in attempt_sets:
            try:
                ids = {r["photo_id"] for r in att}
                recs = [{r["photo_id"]: c} for r, c in compacts if r["photo_id"] in ids]
                text = str(_llm_json(STORY_TEXT_PROMPT.format(
                    heading=heading, records=json.dumps(recs, ensure_ascii=False)),
                    0.2, 8000, tries=1).get("text") or "").strip()
                if text:
                    picked = att
                    break
            except llm_mod.LLMBudgetSpent:
                raise HTTPException(status_code=429, detail=RESTING_TEXT)
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


def _upload_focal_bytes(photo_id):
    for ext in (".jpg", ".png"):
        p = UPLOAD_DIR / f"{photo_id}{ext}"
        if p.exists():
            return p.read_bytes(), "image/png" if ext == ".png" else "image/jpeg"
    return None


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
        try:
            from focal import ensure_focal
            ensure_focal([photo_id], load_bytes=_upload_focal_bytes)
        except Exception as e:
            print(f"(focal compute failed for {photo_id}: {e})")
    except Exception as e:
        _job_set(job_id, status="error", error=str(e)[:500])


@app.post("/api/upload", status_code=202)
async def upload(request: Request, background_tasks: BackgroundTasks,
                 owner_note: Optional[str] = None, note: Optional[str] = None):
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    _demo_guard(request)
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


# ----- Phase 3: connected rings, overview, self links, explain -----

RING_DEFS = (("same_place", "Same place", "R1"),
             ("another_angle", "Another angle", "R2"),
             ("where_stood", "Where you stood", "R3"),
             ("in_background", "In the background", "R4"),
             ("similar", "Looks similar", "R5"))
RING_LIMIT = 8
# Rings 1-4 are earned by place/landmark evidence; ring 5 has only the
# similarity score behind it, so it needs a floor to mean anything.
RING_SIMILAR_FLOOR = 0.5
_VP_ORDER = ("ground_level", "elevated", "aerial", "interior", "water_level")


def ring_of(src, cand):
    """Ring key for one candidate row (pure; each photo lands in one ring).

    src/cand carry place_key, taken_from_key, landmark_keys, viewpoint.
    """
    direct = (src.get("place_key") and src["place_key"] == cand.get("place_key")
              and is_specific(cand["place_key"]))
    if direct and src.get("viewpoint") != cand.get("viewpoint"):
        return "another_angle"
    if direct:
        return "same_place"
    if ((src.get("taken_from_key") and src["taken_from_key"] == cand.get("place_key"))
            or (cand.get("taken_from_key") and cand["taken_from_key"] == src.get("place_key"))):
        return "where_stood"
    if ((src.get("place_key") and src["place_key"] in (cand.get("landmark_keys") or []))
            or (cand.get("place_key") and cand["place_key"] in (src.get("landmark_keys") or []))):
        return "in_background"
    return "similar"


def _norm_text(t):
    return re.sub(r"[^a-z0-9]+", " ", str(t or "").lower()).strip()


def _lm_index(lms):
    by_key, by_name = {}, {}
    for lm in lms or []:
        disp = lm.get("name") or lm.get("key") or "landmark"
        if lm.get("key"):
            by_key.setdefault(lm["key"], disp)
        nm = _norm_text(lm.get("name"))
        if nm:
            by_name.setdefault(nm, disp)
    return by_key, by_name


def link_facts(rec_a, rec_b):
    """Deterministic shared evidence between two records (pure)."""
    obs_a, inf_a = rec_a.get("observed") or {}, rec_a.get("inferred") or {}
    obs_b, inf_b = rec_b.get("observed") or {}, rec_b.get("inferred") or {}
    place_a, place_b = inf_a.get("place") or {}, inf_b.get("place") or {}
    taken_a = (inf_a.get("taken_from") or {}).get("key")
    taken_b = (inf_b.get("taken_from") or {}).get("key")
    signs_a = {_norm_text(t.get("text")) for t in obs_a.get("visible_text") or []} - {""}
    signs_b = {_norm_text(t.get("text")) for t in obs_b.get("visible_text") or []} - {""}
    ents_a = {_norm_text(e.get("label")) for e in obs_a.get("entities") or []} - {""}
    ents_b = {_norm_text(e.get("label")) for e in obs_b.get("entities") or []} - {""}
    ka, na = _lm_index(inf_a.get("landmarks"))
    kb, nb = _lm_index(inf_b.get("landmarks"))
    shared_lm = [ka[k] for k in ka if k in kb]
    seen = {_norm_text(s) for s in shared_lm}
    shared_lm += [disp for nm, disp in na.items() if nm in nb and nm not in seen]
    return {
        "same_place": bool(place_a.get("key") and place_a["key"] == place_b.get("key")),
        "place_name": place_a.get("name") or place_b.get("name"),
        "taken_cross": bool((taken_a and taken_a == place_b.get("key"))
                            or (taken_b and taken_b == place_a.get("key"))),
        "shared_landmarks": sorted(set(shared_lm)),
        "shared_signs": sorted(signs_a & signs_b),
        "shared_entities": sorted(ents_a & ents_b),
    }


def kinds_of(facts, vp_a=None, vp_b=None):
    """Link-kind chips from facts (pure). Empty means no verifiable link."""
    kinds = []
    if facts["same_place"]:
        kinds.append("another_angle" if (vp_a and vp_b and vp_a != vp_b) else "same_place")
    if facts["taken_cross"]:
        kinds.append("where_stood")
    if facts["shared_landmarks"]:
        kinds.append("shared_landmark")
    if facts["shared_signs"]:
        kinds.append("shared_sign")
    return kinds


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _photos_by_ids(ids, cols="photo_id,collection,file,caption,viewpoint,place_key,place_name,record,embedding"):
    try:
        rows = (get_sb().table("photos").select(cols)
                .in_("photo_id", list(ids)).execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"photo lookup failed: {e}")
    return {r["photo_id"]: r for r in rows}


def _self_mini(r):
    return {"photo_id": r["photo_id"], "src": photo_url(r.get("file")),
            "caption": r.get("caption"), "viewpoint": r.get("viewpoint"),
            "place": r.get("place_name")}


@app.get("/api/rings/{photo_id}")
def rings(photo_id: str):
    src = _bridge_src(photo_id.strip())
    other = "personal" if src["collection"] == "world" else "world"
    cands = _bridge_candidates(_coerce_embedding(src["embedding"]), other, src["photo_id"])
    scored = sorted(_score_bridge(src, cands), key=lambda s: s["score"], reverse=True)
    buckets = {key: [] for key, _, _ in RING_DEFS}
    for s in scored:
        key = ring_of(src, s["row"])
        if key == "similar" and (s["row"].get("similarity") or 0) < RING_SIMILAR_FLOOR:
            continue
        if len(buckets[key]) >= RING_LIMIT:
            continue
        buckets[key].append(s)
    member_ids = [s["row"]["photo_id"] for bl in buckets.values() for s in bl]
    recs = (_photos_by_ids([src["photo_id"]] + member_ids, "photo_id,record")
            if member_ids else {})
    src_rec = (recs.get(src["photo_id"]) or {}).get("record") or {}
    out_rings = []
    for key, label, tag in RING_DEFS:
        members = []
        for s in buckets[key]:
            facts = link_facts(src_rec, (recs.get(s["row"]["photo_id"]) or {}).get("record") or {})
            item = _bridge_item(s)
            item["ring"] = key
            item["facts"] = facts
            members.append(item)
        attach_credits(members)
        out_rings.append({"key": key, "label": label, "tag": tag, "members": members})
    kept = sum(len(r["members"]) for r in out_rings)
    return {"photo_id": src["photo_id"], "collection": src["collection"],
            "src": photo_url(src.get("file")), "caption": src.get("caption"),
            "viewpoint": src.get("viewpoint"), "place": src.get("place_name"),
            "place_key": src.get("place_key"), "other_collection": other,
            "rings": out_rings,
            "counts": {r["key"]: len(r["members"]) for r in out_rings},
            "trace": [{"step": "searched",
                       "detail": f"Compared {src['photo_id']} with {len(cands)} {other} photos."},
                      {"step": "answered",
                       "detail": f"Kept {kept} links in "
                                 f"{sum(1 for r in out_rings if r['members'])} rings."}]}


@app.get("/api/places/overview")
def places_overview():
    try:
        rows = (get_sb().table("photos")
                .select("photo_id,collection,place_key,place_name,viewpoint")
                .execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"overview failed: {e}")
    places = {}
    for r in rows:
        key = r.get("place_key") or "unplaced"
        e = places.setdefault(key, {"key": key, "name": r.get("place_name") or key,
                                    "world": {"total": 0, "by_viewpoint": {}},
                                    "mine": {"total": 0, "by_viewpoint": {}},
                                    "mine_ids": []})
        if r.get("place_name"):
            e["name"] = r["place_name"]
        bucket = e["mine"] if r["collection"] == "personal" else e["world"]
        bucket["total"] += 1
        vp = r.get("viewpoint") or "unknown"
        bucket["by_viewpoint"][vp] = bucket["by_viewpoint"].get(vp, 0) + 1
        if r["collection"] == "personal":
            e["mine_ids"].append(r["photo_id"])
    mine_places = [e for e in places.values() if e["mine"]["total"] > 0]
    for e in mine_places:
        e["gaps"] = [vp for vp in _VP_ORDER
                     if e["world"]["by_viewpoint"].get(vp, 0) > 0
                     and e["mine"]["by_viewpoint"].get(vp, 0) == 0]
    mine_places.sort(key=lambda e: (-e["mine"]["total"], e["name"]))
    return {"places": mine_places,
            "summary": {
                "captures": sum(e["mine"]["total"] for e in mine_places),
                "counterparts": sum(e["world"]["total"] for e in mine_places),
                "places": len(mine_places),
                "gaps": sum(1 for e in mine_places if e["gaps"])}}


@app.get("/api/connected/self")
def connected_self(limit: int = 24):
    limit = max(1, min(int(limit), 60))
    try:
        ids = [r["photo_id"] for r in get_sb().table("photos").select("photo_id")
               .eq("collection", "personal").order("photo_id").execute().data or []]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"self links failed: {e}")
    by_id = _photos_by_ids(ids) if ids else {}
    pairs = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = by_id[ids[i]], by_id[ids[j]]
            facts = link_facts(a.get("record") or {}, b.get("record") or {})
            kinds = kinds_of(facts, a.get("viewpoint"), b.get("viewpoint"))
            sim = _cosine(_coerce_embedding(a.get("embedding") or []),
                          _coerce_embedding(b.get("embedding") or []))
            if not kinds and sim < RING_SIMILAR_FLOOR:
                continue
            if not kinds:
                kinds = ["similar"]
            pairs.append({"a": _self_mini(a), "b": _self_mini(b), "kinds": kinds,
                          "facts": facts, "similarity": round(sim, 3)})
    pairs.sort(key=lambda p: (0 if p["kinds"] != ["similar"] else 1, -p["similarity"]))
    return {"count": len(pairs), "pairs": pairs[:limit]}


EXPLAIN_PROMPT = """You explain how two photos are connected. Answer ONLY from
the link facts and records below; never add outside facts.
Rules: under 120 words; name the evidence (say which photo each claim
comes from); state uncertainty plainly; never identify a person (no
names; people only by count, activity or clothing); never invent
measurements, angles, distances, dates, counts or names that are not
written below. Where a detail is absent, say the records do not state it.

Link facts:
{facts}

Record A ({photo_a}):
{record_a}

Record B ({photo_b}):
{record_b}"""


class ExplainRequest(BaseModel):
    photo_a: str
    photo_b: str


def _safe_compact(rec):
    rec = rec or {}
    return _compact_record(rec) if "observed" in rec and "inferred" in rec else {}


@app.post("/api/explain")
def explain(req: ExplainRequest, request: Request = None,
            response: Response = None):
    _guard_or_429(request, response)
    a_id, b_id = req.photo_a.strip(), req.photo_b.strip()
    by_id = _photos_by_ids([a_id, b_id])
    if a_id not in by_id or b_id not in by_id:
        raise HTTPException(status_code=404, detail="I could not find that photo.")
    a, b = by_id[a_id], by_id[b_id]
    facts = link_facts(a.get("record") or {}, b.get("record") or {})
    kinds = kinds_of(facts, a.get("viewpoint"), b.get("viewpoint"))
    minis = [_self_mini(a), _self_mini(b)]
    base = {"photo_a": a_id, "photo_b": b_id, "kinds": kinds,
            "facts": facts, "photos": minis}
    if not kinds:
        pa, pb = a.get("place_name"), b.get("place_name")
        if pa and pb and pa != pb:
            why = f"they are placed differently ({pa} vs {pb})"
        elif not pa or not pb:
            why = "at least one of them has no place verdict"
        else:
            why = "they share no signs, landmarks or entities in their records"
        return {**base, "linked": False,
                "text": (f"{a_id} and {b_id} share no verifiable connection: {why}. "
                         "Try two photos of the same place."),
                "trace": [{"step": "answered",
                           "detail": "Compared the two records; no shared evidence found."}]}
    prompt = EXPLAIN_PROMPT.format(
        facts=json.dumps(facts, ensure_ascii=False),
        photo_a=a_id, photo_b=b_id,
        record_a=json.dumps(_safe_compact(a.get("record")), ensure_ascii=False),
        record_b=json.dumps(_safe_compact(b.get("record")), ensure_ascii=False))
    ckey = llm_mod.cache_key("explain", [a_id, b_id], "",
                             [a.get("record") or {}, b.get("record") or {}])
    hit = llm_mod.cache_get(ckey)
    if hit is not None:
        hit["trace"] = (hit.get("trace") or []) + [
            {"step": "cache", "detail": "Answered earlier from the cache."}]
        return hit
    try:
        res = llm_mod.ask(prompt, max_tokens=800, temperature=0.1, purpose="explain")
    except llm_mod.LLMBudgetSpent:
        raise HTTPException(status_code=429, detail=RESTING_TEXT)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"explain failed: {e}")
    text = res["text"].strip()
    via = f" ({res['provider']}, {res['seconds']}s)"
    if not text:
        text = ("The records link these photos (" + ", ".join(kinds) + ") but "
                "the model returned no wording; the facts above are the evidence.")
    out = {**base, "linked": True, "text": text,
           "trace": [{"step": "checked",
                      "detail": "Compared captions, signs, landmarks and place verdicts."},
                     {"step": "wrote",
                      "detail": f"Wrote the connection from the records{via}."}]}
    llm_mod.cache_put(ckey, out)
    return out


# ----- Phase 4: story drafts (engine) + publish -----

class StoryCreateRequest(BaseModel):
    title: Optional[str] = None
    prompt: Optional[str] = None
    tone: str = "postcard"
    source: str = "both"
    target: str = "short"
    photo_ids: Optional[List[str]] = None


class StoryPatchRequest(BaseModel):
    title: Optional[str] = None
    tone: Optional[str] = None
    target: Optional[str] = None
    chapters: Optional[List[Dict[str, Any]]] = None


def _story_fetch_for(ids):
    """fetch() closure for the engine backed by one photo query."""
    try:
        rows = (get_sb().table("photos").select("photo_id,record")
                .in_("photo_id", list(ids)).execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"photo lookup failed: {e}")
    by_id = {r["photo_id"]: r for r in rows}

    def fetch(pid):
        r = by_id.get(pid)
        if r is None:
            return None
        obs = ((r.get("record") or {}).get("observed") or {})
        return {"people": (obs.get("people") or {}).get("count", 0) or 0}

    return fetch


def _story_full(story):
    """Stored story + live photo data, heading problems and face flags."""
    ids = [c["photo_id"] for c in story.get("chapters") or []]
    by_id = _photos_by_ids(ids) if ids else {}
    chapters = []
    for c in story.get("chapters") or []:
        r = by_id.get(c["photo_id"]) or {}
        obs = ((r.get("record") or {}).get("observed") or {})
        chapters.append({"photo_id": c["photo_id"], "seconds": c.get("seconds", 4),
                         "heading": c.get("heading") or "", "text": c.get("text") or "",
                         "caption": c.get("caption") or r.get("caption") or c["photo_id"],
                         "src": photo_url(r.get("file")), "collection": r.get("collection"),
                         "viewpoint": r.get("viewpoint"), "place": r.get("place_name"),
                         "people": (obs.get("people") or {}).get("count", 0) or 0})
    attach_credits(chapters)
    problems = {}
    for i, c in enumerate(story.get("chapters") or []):
        if not (c.get("heading") or "").strip():
            continue
        r = by_id.get(c["photo_id"])
        if r is None:
            continue
        try:
            compact = _compact_record(r.get("record") or {})
            facts = [_photo_fact(r, compact)]
        except (KeyError, TypeError, AttributeError):
            continue
        bad = _heading_problems(c["heading"], facts)
        if bad:
            problems[str(i)] = bad
    return {"story": story, "chapters": chapters,
            "totals": {"scenes": len(chapters),
                       "seconds": sum(c.get("seconds", 0) for c in chapters)},
            "problems": problems,
            "faces_blocked": [c["photo_id"] for c in chapters if c["people"] > 0]}


def _story_err(fn, *a, **k):
    try:
        return fn(*a, **k)
    except StoryError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)


@app.post("/api/stories")
def stories_create(req: StoryCreateRequest):
    from story_engine import MAX_SCENES, create
    prompt = (req.prompt or "").strip()
    ids = [i.strip() for i in (req.photo_ids or []) if i.strip()]
    if bool(prompt) == bool(ids):
        raise HTTPException(status_code=400,
                            detail="give exactly one of prompt or photo_ids.")
    source = {"mine": "personal", "world": "world", "both": "both"}.get(req.source)
    if source is None:
        raise HTTPException(status_code=400, detail="source must be mine, world or both.")
    if prompt:
        planned = story(StoryRequest(theme=prompt, collection=source))
        if not planned["chapters"]:
            raise HTTPException(status_code=502,
                                detail=f"no story photos found for {prompt!r}.")
        per_scene = 4 if req.target == "short" else 5
        cap = 5 if req.target == "short" else MAX_SCENES
        chapters, trace = [], list(planned["trace"])
        for ch in planned["chapters"]:
            for p in ch["photos"]:
                if len(chapters) >= cap:
                    break
                chapters.append({"photo_id": p["photo_id"], "seconds": per_scene,
                                 "heading": ch["heading"], "text": ch["text"]})
        trace.append({"step": "built",
                      "detail": f"Built {len(chapters)} scenes from {len(planned['chapters'])} chapters."})
        title = (req.title or "").strip() or planned["title"]
    else:
        per_scene = 4 if req.target == "short" else 5
        chapters = [{"photo_id": i, "seconds": per_scene} for i in ids]
        trace = [{"step": "built", "detail": f"Built {len(chapters)} scenes from your photos."}]
        title = (req.title or "").strip()
    fetch = _story_fetch_for([c["photo_id"] for c in chapters])
    made = _story_err(create, title=title, prompt=prompt, tone=req.tone,
                      source=req.source, target=req.target, chapters=chapters, fetch=fetch)
    return {**_story_full(made), "trace": trace}


@app.get("/api/stories")
def stories_list(status: Optional[str] = None):
    from story_engine import list_stories
    found = _story_err(list_stories, status)
    covers = [s["cover"] for s in found if s.get("cover")]
    by_id = _photos_by_ids(covers) if covers else {}
    for s in found:
        r = by_id.get(s.get("cover") or "")
        s["cover_src"] = photo_url(r.get("file")) if r else None
    return {"stories": found}


@app.get("/api/stories/{story_id}")
def story_detail(story_id: str):
    from story_engine import load
    return _story_full(_story_err(load, story_id.strip()))


@app.patch("/api/stories/{story_id}")
def story_update(story_id: str, req: StoryPatchRequest):
    from story_engine import load, update
    current = _story_err(load, story_id.strip())
    ids = [c.get("photo_id") for c in (req.chapters if req.chapters is not None
                                       else current.get("chapters") or []) if c.get("photo_id")]
    fetch = _story_fetch_for(ids)
    made = _story_err(update, story_id.strip(), title=req.title, tone=req.tone,
                      target=req.target, chapters=req.chapters, fetch=fetch)
    return _story_full(made)


@app.delete("/api/stories/{story_id}")
def story_delete(story_id: str):
    from story_engine import remove
    _story_err(remove, story_id.strip())
    return {"ok": True, "id": story_id.strip()}


@app.post("/api/stories/{story_id}/publish")
def story_publish(story_id: str, request: Request):
    # Drafts are local and private (ungated, like flags); publishing puts
    # the story on the public Showcase, so it needs the demo code.
    _demo_guard(request)
    from story_engine import load, publish
    current = _story_err(load, story_id.strip())
    fetch = _story_fetch_for([c["photo_id"] for c in current.get("chapters") or []])
    made = _story_err(publish, story_id.strip(), fetch=fetch)
    return _story_full(made)


# ----- Phase 5: library albums, world browse, gaps, correction, deletion, export -----

BURST_SIMILAR = 0.85
LIBRARY_JSON = ROOT / "data" / "library.json"
_GAP_VPS = ("ground_level", "elevated", "aerial", "interior")


class LibraryError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _library_err(fn, *a, **k):
    try:
        return fn(*a, **k)
    except LibraryError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)


def _library_prefs():
    try:
        return json.loads(LIBRARY_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_library_prefs(prefs):
    LIBRARY_JSON.write_text(json.dumps(prefs, ensure_ascii=False, indent=1), encoding="utf-8")


def cluster_bursts(ids, sim):
    """Transitive similarity groups (pure); singles dropped, sorted by first id.

    sim maps (a, b) with a < b to a float. Filenames are synthetic
    (personal_NNN), so bursts group near-duplicate frames by meaning.
    """
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for (a, b), s in sim.items():
        if s >= BURST_SIMILAR and a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    groups = {}
    for i in ids:
        groups.setdefault(find(i), []).append(i)
    return sorted([sorted(g) for g in groups.values() if len(g) > 1], key=lambda g: g[0])


def _personal_rows():
    try:
        return (get_sb().table("photos")
                .select("photo_id,file,caption,viewpoint,place_key,place_name,record,embedding")
                .eq("collection", "personal").order("photo_id").execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"library lookup failed: {e}")


def _lib_mini(r):
    return {"photo_id": r["photo_id"], "src": photo_url(r.get("file")),
            "caption": r.get("caption"), "viewpoint": r.get("viewpoint"),
            "place": r.get("place_name"), "place_key": r.get("place_key")}


@app.get("/api/albums")
def albums():
    rows = _personal_rows()
    by_id = {r["photo_id"]: r for r in rows}
    ids = [r["photo_id"] for r in rows]
    infos = {}
    for r in rows:
        obs = ((r.get("record") or {}).get("observed") or {})
        inf = ((r.get("record") or {}).get("inferred") or {})
        vt = obs.get("visible_text") or []
        infos[r["photo_id"]] = {
            "signs": sum(1 for s in vt if isinstance(s, dict) and (s.get("text") or "").strip()),
            "people": (obs.get("people") or {}).get("count", 0) or 0,
            "uncertain": bool((r.get("record") or {}).get("uncertainties")),
            "confirmed": ((inf.get("place") or {}).get("status") == "confirmed"),
        }
    vecs = {r["photo_id"]: _coerce_embedding(r.get("embedding") or []) for r in rows}
    sim = {}
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            sim[(ids[i], ids[j])] = _cosine(vecs[ids[i]], vecs[ids[j]])
    covers = (_library_prefs().get("burst_covers") or {})
    bursts = []
    for g in cluster_bursts(ids, sim):
        key = "b-" + g[0]
        cover = covers.get(key) if covers.get(key) in g else g[0]
        bursts.append({"key": key, "count": len(g), "cover": cover, "ids": g})
    places = {}
    for r in rows:
        key = r.get("place_key") or "unplaced"
        e = places.setdefault(key, {"key": key, "name": r.get("place_name") or key, "ids": []})
        if r.get("place_name"):
            e["name"] = r["place_name"]
        e["ids"].append(r["photo_id"])
    above_ids = [i for i in ids if by_id[i].get("viewpoint") in ("elevated", "aerial")]
    signs_ids = [i for i in ids if infos[i]["signs"]]
    people_ids = [i for i in ids if infos[i]["people"]]
    look_ids = [i for i in ids if not by_id[i].get("place_key")
                or not infos[i]["confirmed"] or infos[i]["uncertain"]]
    return {
        "count": len(rows),
        "albums": [
            {"key": "all", "label": "All photos", "count": len(ids), "ids": ids},
            {"key": "places", "label": "Places", "count": len(places),
             "groups": sorted(places.values(),
                              key=lambda e: (-len(e["ids"]), e["name"]))},
            {"key": "above", "label": "From above",
             "count": len(above_ids), "ids": above_ids},
            {"key": "signs", "label": "With signs",
             "count": len(signs_ids), "ids": signs_ids},
            {"key": "people", "label": "With people",
             "count": len(people_ids), "ids": people_ids},
            {"key": "look", "label": "Needs a look",
             "count": len(look_ids), "ids": look_ids},
            {"key": "bursts", "label": "Bursts", "count": len(bursts), "sets": bursts},
        ],
        "photos": {i: _lib_mini(by_id[i]) for i in ids},
    }


class CoverRequest(BaseModel):
    cover: str = Field(min_length=1)


@app.patch("/api/bursts/{burst_key}")
def burst_cover(burst_key: str, req: CoverRequest):
    # A local display preference (ungated, like story drafts).
    rows = _personal_rows()
    ids = [r["photo_id"] for r in rows]
    vecs = {r["photo_id"]: _coerce_embedding(r.get("embedding") or []) for r in rows}
    sim = {}
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            sim[(ids[i], ids[j])] = _cosine(vecs[ids[i]], vecs[ids[j]])
    target = [g for g in cluster_bursts(ids, sim) if "b-" + g[0] == burst_key.strip()]
    if not target:
        raise HTTPException(status_code=404, detail="I could not find that burst.")
    if req.cover.strip() not in target[0]:
        raise HTTPException(status_code=400, detail="that photo is not in this burst.")
    prefs = _library_prefs()
    prefs.setdefault("burst_covers", {})[burst_key.strip()] = req.cover.strip()
    _save_library_prefs(prefs)
    return {"ok": True, "key": burst_key.strip(), "cover": req.cover.strip()}


def _theme_of(path):
    parts = str(path or "").replace("\\", "/").split("/")
    try:
        return parts[parts.index("world") + 1]
    except (ValueError, IndexError):
        return ""


@app.get("/api/world")
def world(place_key: Optional[str] = None, theme: Optional[str] = None,
          viewpoint: Optional[str] = None, people: Optional[str] = None,
          q: Optional[str] = None, limit: int = 60, offset: int = 0):
    limit = max(1, min(int(limit or 60), 60))
    offset = max(0, int(offset or 0))
    try:
        rows = (get_sb().table("photos")
                .select("photo_id,file,caption,viewpoint,place_key,place_name,record")
                .eq("collection", "world").order("photo_id").execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"world lookup failed: {e}")
    for r in rows:
        r["_theme"] = _theme_of(r.get("file"))
        obs = ((r.get("record") or {}).get("observed") or {})
        r["_people"] = (obs.get("people") or {}).get("count", 0) or 0
    places, themes, vps = {}, {}, {}
    for r in rows:
        if r.get("place_key"):
            e = places.setdefault(r["place_key"],
                                  {"key": r["place_key"],
                                   "name": r.get("place_name") or r["place_key"], "count": 0})
            e["count"] += 1
        if r["_theme"]:
            themes[r["_theme"]] = themes.get(r["_theme"], 0) + 1
        vp = r.get("viewpoint") or "unknown"
        vps[vp] = vps.get(vp, 0) + 1
    want_q = (q or "").strip().casefold()
    out = []
    for r in rows:
        if place_key and r.get("place_key") != place_key:
            continue
        if theme and r["_theme"] != theme.strip().lower():
            continue
        if viewpoint and (r.get("viewpoint") or "unknown") != viewpoint:
            continue
        if people == "yes" and not r["_people"]:
            continue
        if people == "no" and r["_people"]:
            continue
        if want_q and want_q not in (((r.get("caption") or "") + " " +
                                      (r.get("place_name") or "")).casefold()):
            continue
        prov = ((r.get("record") or {}).get("provided") or {})
        out.append({"photo_id": r["photo_id"], "src": photo_url(r.get("file")),
                    "caption": r.get("caption"), "viewpoint": r.get("viewpoint"),
                    "place": r.get("place_name"), "place_key": r.get("place_key"),
                    "theme": r["_theme"], "people": r["_people"],
                    "credit": {"author": prov.get("author"), "license": prov.get("license"),
                               "source_url": prov.get("source_url")}
                    if (prov.get("author") or prov.get("license")) else None})
    return {"total": len(out), "limit": limit, "offset": offset,
            "photos": out[offset:offset + limit],
            "facets": {
                "places": sorted(places.values(), key=lambda e: (-e["count"], e["name"])),
                "themes": sorted([{"key": k, "label": k.capitalize(), "count": v}
                                  for k, v in themes.items()], key=lambda e: -e["count"]),
                "viewpoints": sorted([{"key": k, "count": v} for k, v in vps.items()],
                                     key=lambda e: -e["count"])}}


def gap_list(world_rows, registry):
    """Thin and empty places (pure over rows + registry map)."""
    by_place = {}
    for r in world_rows:
        key = r.get("place_key")
        if not key:
            continue
        e = by_place.setdefault(key, {"count": 0, "vps": set(), "sample": []})
        e["count"] += 1
        if r.get("viewpoint"):
            e["vps"].add(r["viewpoint"])
        if len(e["sample"]) < 3:
            e["sample"].append(r["photo_id"])
    out = []
    for key, info in registry.items():
        if key.startswith("unknown/"):
            continue
        e = by_place.get(key, {"count": 0, "vps": set(), "sample": []})
        missing = [vp for vp in _GAP_VPS if vp not in e["vps"]] if e["count"] else ["all"]
        kinds = []
        if not e["count"]:
            kinds.append("empty")
        elif e["count"] == 1:
            kinds.append("single")
        if "elevated" in missing or "aerial" in missing:
            kinds.append("high")
        if "interior" in missing:
            kinds.append("interior")
        if not kinds:
            continue
        out.append({"key": key, "name": (info or {}).get("name") or key,
                    "type": (info or {}).get("type") or "place",
                    "count": e["count"], "missing": missing, "kinds": kinds,
                    "sample": e["sample"]})
    out.sort(key=lambda g: (g["count"], g["name"]))
    return out


@app.get("/api/gaps")
def gaps():
    try:
        rows = (get_sb().table("photos").select("photo_id,place_key,viewpoint")
                .eq("collection", "world").execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"gaps lookup failed: {e}")
    found = gap_list(rows, load_places())
    return {"count": len(found), "gaps": found[:60]}


class CorrectRequest(BaseModel):
    caption: Optional[str] = None
    place_key: Optional[str] = None
    place_name: Optional[str] = None
    note: Optional[str] = None


def apply_correction(record, body):
    """Owner overrides on a copy of the record (pure).

    Overrides only — no model rerun. The owner's word is ground truth
    for their own photo, so a corrected place verdict is final.
    """
    rec = json.loads(json.dumps(record or {}))
    changed = []
    if (body.get("caption") or "").strip():
        rec.setdefault("observed", {})["caption"] = body["caption"].strip()[:500]
        changed.append("caption")
    if (body.get("place_key") or "").strip():
        key = body["place_key"].strip().lower()[:160]
        name = (body.get("place_name") or "").strip()[:160] or key
        why = "Corrected by the photo owner"
        if (body.get("note") or "").strip():
            why += ": " + body["note"].strip()[:200]
        rec.setdefault("inferred", {})["place"] = {
            "key": key, "name": name, "status": "human_review",
            "evidence": [why], "confidence": 1.0}
        changed.append("place")
    if not changed:
        raise LibraryError(400, "nothing to correct: give a caption and/or a place.")
    rec["corrected_by"] = "you"
    rec["corrected_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return rec, changed


def _one_photo(pid, cols="photo_id,collection,file,caption,record"):
    try:
        rows = (get_sb().table("photos").select(cols)
                .eq("photo_id", pid).execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"photo lookup failed: {e}")
    if not rows:
        raise HTTPException(status_code=404, detail="I could not find that photo.")
    return rows[0]


@app.post("/api/photo/{photo_id}/correct")
def correct_photo(photo_id: str, req: CorrectRequest, request: Request):
    _demo_guard(request)
    pid = photo_id.strip()
    row = _one_photo(pid)
    if row.get("collection") != "personal":
        raise HTTPException(status_code=400, detail="Corrections apply to your photos; "
                            "flag world photos from their dossier instead.")
    body = {"caption": req.caption, "place_key": req.place_key,
            "place_name": req.place_name, "note": req.note}
    new_rec, changed = _library_err(apply_correction, row.get("record") or {}, body)
    ann = ROOT / "data" / "annotations" / "personal" / (pid + ".json")
    try:
        ann.parent.mkdir(parents=True, exist_ok=True)
        ann.write_text(json.dumps({**new_rec, "photo_id": pid},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=502, detail=f"annotation write failed: {e}")
    inf = (new_rec.get("inferred") or {}).get("place") or {}
    patch = {"caption": (new_rec.get("observed") or {}).get("caption") or row.get("caption"),
             "place_key": inf.get("key"), "place_name": inf.get("name"), "record": new_rec}
    reembedded = False
    try:
        text = search_text(new_rec)
        vec = np.array(list(chat_module.get_model().embed([text]))[0], dtype="float32")
        patch["embedding"] = (vec / np.linalg.norm(vec)).tolist()
        reembedded = True
    except Exception as e:
        print(f"(re-embed failed for {pid}: {e})")
    try:
        get_sb().table("photos").update(patch).eq("photo_id", pid).execute()
        try:
            refresh_connected()
        except Exception as e:
            print(f"(connected refresh failed: {e})")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"photo update failed: {e}")
    return {"ok": True, "photo_id": pid, "corrected": changed, "reembedded": reembedded,
            "note": "Run `python backend/retrieval.py build` to refresh the local index."}


def _delete_personal(pid):
    row = _one_photo(pid, "photo_id,collection,file")
    if row.get("collection") != "personal":
        raise HTTPException(status_code=400, detail="Only your own photos can be deleted.")
    out = {"db": False, "file": False, "annotation": False}
    get_sb().table("photos").delete().eq("photo_id", pid).execute()
    out["db"] = True
    f = str(row.get("file") or "")
    if f.startswith("data/photos/personal/"):
        p = ROOT / f
        if p.exists():
            p.unlink()
            out["file"] = True
    ann = ROOT / "data" / "annotations" / "personal" / (pid + ".json")
    if ann.exists():
        ann.unlink()
        out["annotation"] = True
    prefs = _library_prefs()
    covers = prefs.get("burst_covers") or {}
    if pid in covers.values():
        prefs["burst_covers"] = {k: v for k, v in covers.items() if v != pid}
        _save_library_prefs(prefs)
    return out


@app.delete("/api/photo/{photo_id}")
def delete_photo(photo_id: str, request: Request):
    _demo_guard(request)
    pid = photo_id.strip()
    try:
        out = _delete_personal(pid)
        try:
            refresh_connected()
        except Exception as e:
            print(f"(connected refresh failed: {e})")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"delete failed: {e}")
    return {"ok": True, "photo_id": pid, "deleted": out,
            "note": "Links update automatically; run `python backend/retrieval.py build` "
                    "to refresh the local index."}


@app.delete("/api/photos/mine")
def delete_all_my_photos(request: Request):
    _demo_guard(request)
    try:
        ids = [r["photo_id"] for r in get_sb().table("photos").select("photo_id")
               .eq("collection", "personal").order("photo_id").execute().data or []]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"photo lookup failed: {e}")
    done, errors = {}, {}
    for pid in ids:
        try:
            done[pid] = _delete_personal(pid)
        except Exception as e:
            errors[pid] = str(e)
    try:
        refresh_connected()
    except Exception as e:
        print(f"(connected refresh failed: {e})")
    return {"ok": not errors, "deleted": len(done), "photos": done, "errors": errors}


@app.get("/api/export")
def export_mine():
    # Your own data out (a read, like flagging): not demo-gated.
    import io
    import zipfile
    try:
        rows = (get_sb().table("photos")
                .select("photo_id,file,caption,viewpoint,place_key,place_name,record")
                .eq("collection", "personal").order("photo_id").execute().data or [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"export lookup failed: {e}")
    buf = io.BytesIO()
    names = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            base = Path(str(r.get("file") or "")).name or (r["photo_id"] + ".jpg")
            try:
                zf.write(str(ROOT / str(r.get("file") or "")), "photos/" + base)
            except OSError:
                names.append({"photo_id": r["photo_id"], "file": None, "missing_file": True})
                continue
            zf.writestr("annotations/" + r["photo_id"] + ".json",
                        json.dumps(r.get("record") or {}, ensure_ascii=False, indent=1))
            names.append({"photo_id": r["photo_id"], "file": "photos/" + base,
                          "caption": r.get("caption"), "place": r.get("place_name")})
        zf.writestr("manifest.json", json.dumps(
            {"exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "count": len(names), "photos": names}, ensure_ascii=False, indent=1))
        zf.writestr("README.txt", "ReelWorld personal export.\n"
                    f"{len(names)} photos with annotations, exported "
                    f"{datetime.now(timezone.utc).date().isoformat()}.\n")
    data = buf.getvalue()

    def gen():
        yield data

    return StreamingResponse(gen(), media_type="application/zip", headers={
        "Content-Disposition": "attachment; filename=reelworld-my-photos.zip"})
