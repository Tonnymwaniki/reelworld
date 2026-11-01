"""Saved conversations: storage, expiry, snapshots (no model, no database).

Local use (DEMO_MODE=false) keeps every chat in data/chats/<id>.json
forever. The public demo scopes chats per anonymous visitor cookie
(data/chats/<visitor>/<id>.json) with 7-day expiry from the last
update; expired chats are cleaned lazily on every chats access.

A chat holds messages (user text; reel replies with spec, result
rows including verdicts, the real trace, photo binding, topic and
label) plus a router-state snapshot (spec, focus, last rows,
rejected ids, replies, topic) so opening a chat restores the thread
AND the exact state follow-up turns need. Reasoning content is
never captured anywhere in the pipeline, so it can never be stored
here — see scan_reasoning, which the tests run over every record.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHATS_DIR = Path(__file__).resolve().parent.parent / "data" / "chats"
EXPIRY_DAYS = 7
CHAT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TITLE_LEN = 48


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def valid_chat_id(cid):
    """Safe for paths: letters, digits, _ and - only (pure)."""
    return isinstance(cid, str) and bool(CHAT_ID_RE.match(cid))


def valid_scope(scope):
    """Same charset rule for visitor scopes (pure)."""
    return valid_chat_id(scope)


def scope_dir(scope):
    return CHATS_DIR / scope


def chat_path(scope, cid):
    return scope_dir(scope) / f"{cid}.json"


def _expired(chat, scope):
    """True when a demo-scope chat is older than 7 days (pure)."""
    if scope == "local":
        return False
    try:
        updated = datetime.fromisoformat(chat.get("updated_at") or "")
    except ValueError:
        return False
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - updated > timedelta(days=EXPIRY_DAYS)


def _read(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("id") else None


def new_chat_id(scope):
    """Next chat_YYYYMMDD_NNNN id for a scope (daily sequence)."""
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    taken = set()
    try:
        for p in scope_dir(scope).glob(f"chat_{day}_*.json"):
            taken.add(p.stem)
    except OSError:
        pass
    n = 1
    while f"chat_{day}_{n:04d}" in taken:
        n += 1
    return f"chat_{day}_{n:04d}"


def auto_title(text):
    """First user message squeezed to one short line (pure)."""
    line = " ".join((text or "").split())
    return line[:TITLE_LEN] if line else "New chat"


def create_chat(scope, title=None):
    """New empty chat, saved; title auto-fills from the first message."""
    cid = new_chat_id(scope)
    now = now_iso()
    chat = {"id": cid, "title": (title or "").strip() or "New chat",
            "title_auto": not (title or "").strip(),
            "created_at": now, "updated_at": now, "messages": [],
            "state": {"spec": {}, "focus": None, "last": [],
                      "rejected": [], "replies": [],
                      "topic": {"id": 0, "label": ""}}}
    save_chat(scope, chat)
    return chat


def save_chat(scope, chat):
    chat["updated_at"] = now_iso()
    scope_dir(scope).mkdir(parents=True, exist_ok=True)
    chat_path(scope, chat["id"]).write_text(
        json.dumps(chat, ensure_ascii=False), encoding="utf-8")
    return chat


def load_chat(scope, cid):
    """Chat dict, or None when missing, invalid or expired (deletes it)."""
    if not valid_chat_id(cid):
        return None
    chat = _read(chat_path(scope, cid))
    if chat is None:
        return None
    if _expired(chat, scope):
        try:
            chat_path(scope, cid).unlink()
        except OSError:
            pass
        return None
    return chat


def delete_chat(scope, cid):
    """True when a chat file was removed."""
    if not valid_chat_id(cid):
        return False
    try:
        chat_path(scope, cid).unlink()
        return True
    except OSError:
        return False


def delete_all(scope):
    """Remove every chat in a scope; returns the count."""
    n = 0
    try:
        files = list(scope_dir(scope).glob("chat_*.json"))
    except OSError:
        return 0
    for p in files:
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n


def cleanup_expired(scope):
    """Delete expired chats in a demo scope; returns the count.

    Local chats never expire. Runs lazily on every chats access,
    so no background job is needed.
    """
    if scope == "local":
        return 0
    n = 0
    try:
        files = list(scope_dir(scope).glob("chat_*.json"))
    except OSError:
        return 0
    for p in files:
        chat = _read(p)
        if chat is not None and _expired(chat, scope):
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
    return n


def thumb_of(chat):
    """First result photo {photo_id, file} in a chat, else None (pure)."""
    for m in chat.get("messages") or []:
        for r in m.get("results") or []:
            if r.get("photo_id"):
                return {"photo_id": r["photo_id"], "file": r.get("file")}
    return None


def summary(chat):
    """List-row shape for a chat (pure)."""
    return {"id": chat.get("id"), "title": chat.get("title"),
            "updated_at": chat.get("updated_at"),
            "message_count": len(chat.get("messages") or []),
            "thumb": thumb_of(chat)}


def list_chats(scope):
    """Summaries, newest first (expired demo chats cleaned first)."""
    cleanup_expired(scope)
    chats = []
    try:
        files = list(scope_dir(scope).glob("chat_*.json"))
    except OSError:
        return []
    for p in files:
        chat = _read(p)
        if chat is not None and not _expired(chat, scope):
            chats.append(chat)
    chats.sort(key=lambda c: c.get("updated_at") or "", reverse=True)
    return [summary(c) for c in chats]


def snapshot_state(estate):
    """Router state to a JSON-safe snapshot (pure)."""
    snap = json.loads(json.dumps({
        "spec": estate.get("spec") or {},
        "focus": estate.get("focus"),
        "last": estate.get("last") or [],
        "rejected": sorted(estate.get("rejected") or set()),
        "replies": estate.get("replies") or [],
        "topic": estate.get("topic") or {"id": 0, "label": ""}}))
    return snap


def apply_state(engine, chat):
    """Restore an engine from a chat snapshot (in place).

    Recent user texts are re-derived from the stored messages so
    follow-up turns reference the thread correctly.
    """
    snap = chat.get("state") or {}
    st = engine.state
    st["spec"] = dict(snap.get("spec") or {})
    st["focus"] = snap.get("focus")
    st["last"] = list(snap.get("last") or [])
    st["rejected"] = set(snap.get("rejected") or [])
    st["replies"] = list(snap.get("replies") or [])
    st["topic"] = dict(snap.get("topic") or {"id": 0, "label": ""})
    st["pending"] = None
    texts = [m.get("text") for m in chat.get("messages") or []
             if m.get("role") == "user" and m.get("text")]
    st["user_texts"] = texts[-3:]
    return engine


def append_turn(scope, cid, user_text, payload, snap):
    """Record one user message + reel reply; None when chat is gone."""
    chat = load_chat(scope, cid)
    if chat is None:
        return None
    chat["messages"].append({"role": "user", "text": user_text,
                             "time": now_iso()})
    topic = payload.get("topic") or {}
    chat["messages"].append({
        "role": "reel", "text": payload.get("text", ""),
        "kind": payload.get("kind", "ok"), "spec": payload.get("spec") or {},
        "results": payload.get("results") or [],
        "trace": payload.get("trace") or [],
        "about_photo_id": payload.get("about_photo_id"),
        "topic_id": topic.get("id", 0), "topic_new": topic.get("new", False),
        "topic_label": topic.get("label", ""),
        "label": payload.get("label"),
        "options": payload.get("options"),
        "time": now_iso()})
    if chat.get("title_auto"):
        chat["title"] = auto_title(user_text)
        chat["title_auto"] = False
    chat["state"] = snap
    return save_chat(scope, chat)


def scan_reasoning(obj):
    """True when any dict key mentions reasoning (pure, for tests)."""
    if isinstance(obj, dict):
        return any("reasoning" in str(k).lower() for k in obj) or any(
            scan_reasoning(v) for v in obj.values())
    if isinstance(obj, list):
        return any(scan_reasoning(v) for v in obj)
    return False
