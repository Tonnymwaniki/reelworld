"""
ReelWorld: HTTP API (step 1) - FastAPI wrapper around the Engine in chat.py.

Endpoints
  GET  /health                     liveness check (no model or DB access)
  POST /chat                       {"session_id": "...", "message": "..."}
  POST /sessions/{session_id}/reset  forget one conversation

Notes
  * Conversation state (spec, focus, last results, rejected ids) is kept in
    memory, one Engine per session_id. Restarts clear it.
  * The embedding model is loaded once and shared by all sessions.
  * Existing scripts are untouched: this module only imports Engine.

Run from the project root (project .venv active):
    python -m uvicorn backend.api:app --reload

Interactive docs: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import chat as chat_module
from chat import Engine

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


class ChatRequest(BaseModel):
    session_id: str = Field(default="default", min_length=1)
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    session_id: str
    text: str
    results: List[dict]
    focus_photo_id: Optional[str] = None
    spec: Dict[str, Any] = Field(default_factory=dict)


app = FastAPI(title="ReelWorld API")


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
    return {
        "session_id": sid,
        "text": out.get("text", ""),
        "results": [public_row(r) for r in out.get("results", [])],
        "focus_photo_id": focus.get("photo_id"),
        "spec": {k: spec.get(k) for k in ("query", "collection", "viewpoints",
                                          "max_people", "must_include", "avoid_terms")},
    }


@app.post("/sessions/{session_id}/reset")
def reset_session(session_id: str):
    sid = (session_id or "").strip() or "default"
    with _sessions_lock:
        _sessions.pop(sid, None)
    return {"session_id": sid, "reset": True}
