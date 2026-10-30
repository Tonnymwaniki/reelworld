"""Story drafts on disk: CRUD + validation.

No web layer, no model calls, no database: photos are validated through
a caller-supplied fetch(photo_id) returning {"people": int} or None.
Chapter heading checks live api-side (_heading_problems); the engine
only stores what the API validated.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

STORIES_DIR = Path(__file__).resolve().parent.parent / "data" / "stories"
TONES = ("postcard", "field-notes", "documentary")
SOURCES = ("mine", "world", "both")
TARGETS = ("short", "medium")
STATUSES = ("draft", "published")
ID_RE = re.compile(r"^st-\d{8}-\d{4}$")
MAX_SCENES = 12


class StoryError(Exception):
    def __init__(self, status, detail, extra=None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.extra = extra or {}


def _dir():
    STORIES_DIR.mkdir(parents=True, exist_ok=True)
    return STORIES_DIR


def _path(sid):
    if not ID_RE.match(sid or ""):
        raise StoryError(404, "I could not find that story.")
    return _dir() / (sid + ".json")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _next_id(today=None):
    day = today or datetime.now(timezone.utc).strftime("%Y%m%d")
    best = 0
    if STORIES_DIR.is_dir():
        for p in STORIES_DIR.glob(f"st-{day}-*.json"):
            m = re.match(r"^st-\d{8}-(\d{4})\.json$", p.name)
            if m:
                best = max(best, int(m.group(1)))
    return f"st-{day}-{best + 1:04d}"


def load(sid):
    p = _path(sid)
    if not p.exists():
        raise StoryError(404, "I could not find that story.")
    return json.loads(p.read_text(encoding="utf-8"))


def save(story):
    _path(story["id"]).write_text(json.dumps(story, ensure_ascii=False, indent=1),
                                  encoding="utf-8")


def list_stories(status=None):
    if status is not None and status not in STATUSES:
        raise StoryError(400, "status must be 'draft' or 'published'.")
    out = []
    if STORIES_DIR.is_dir():
        for p in sorted(STORIES_DIR.glob("st-*.json")):
            try:
                s = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if status is not None and s.get("status") != status:
                continue
            ch = s.get("chapters") or []
            out.append({"id": s.get("id"), "title": s.get("title"),
                        "status": s.get("status"), "tone": s.get("tone"),
                        "target": s.get("target"), "created_at": s.get("created_at"),
                        "published_at": s.get("published_at"), "scenes": len(ch),
                        "seconds": sum(c.get("seconds", 0) for c in ch),
                        "cover": ch[0].get("photo_id") if ch else None})
    out.sort(key=lambda s: s.get("created_at") or "", reverse=True)
    return out


def _check_chapters(chapters, fetch):
    if not isinstance(chapters, list) or not chapters:
        raise StoryError(400, "chapters must be a non-empty list.")
    if len(chapters) > MAX_SCENES:
        raise StoryError(400, f"at most {MAX_SCENES} scenes per story.")
    out = []
    for i, ch in enumerate(chapters):
        if not isinstance(ch, dict) or not ch.get("photo_id"):
            raise StoryError(400, f"scene {i + 1} needs a photo_id.")
        info = fetch(ch["photo_id"])
        if info is None:
            raise StoryError(400, f"unknown photo: {ch['photo_id']}.")
        secs = ch.get("seconds", 4)
        if isinstance(secs, bool) or not isinstance(secs, (int, float)) \
                or not 1 <= secs <= 15:
            raise StoryError(400, f"scene {i + 1}: seconds must be 1..15.")
        out.append({"photo_id": ch["photo_id"], "seconds": secs,
                    "heading": str(ch.get("heading") or "")[:80],
                    "caption": str(ch.get("caption") or "")[:280],
                    "text": str(ch.get("text") or "")[:1200],
                    "people": info.get("people", 0)})
    return out


def create(*, title="", prompt="", tone="postcard", source="both",
           target="short", chapters, fetch):
    if tone not in TONES:
        raise StoryError(400, "tone must be postcard, field-notes or documentary.")
    if source not in SOURCES:
        raise StoryError(400, "source must be mine, world or both.")
    if target not in TARGETS:
        raise StoryError(400, "target must be short or medium.")
    story = {"id": _next_id(), "title": (title or "").strip()[:80] or "Untitled story",
             "prompt": (prompt or "").strip()[:280], "tone": tone, "source": source,
             "target": target, "status": "draft", "created_at": _now(),
             "published_at": None, "chapters": _check_chapters(chapters, fetch)}
    save(story)
    return story


def update(sid, *, title=None, tone=None, target=None, chapters=None, fetch):
    story = load(sid)
    if title is not None:
        story["title"] = str(title).strip()[:80] or story["title"]
    if tone is not None:
        if tone not in TONES:
            raise StoryError(400, "tone must be postcard, field-notes or documentary.")
        story["tone"] = tone
    if target is not None:
        if target not in TARGETS:
            raise StoryError(400, "target must be short or medium.")
        story["target"] = target
    if chapters is not None:
        story["chapters"] = _check_chapters(chapters, fetch)
        if story.get("status") == "published":
            _require_faceless(story)
    save(story)
    return story


def remove(sid):
    p = _path(sid)
    if not p.exists():
        raise StoryError(404, "I could not find that story.")
    p.unlink()


def chapters_with_people(story):
    return [c["photo_id"] for c in story.get("chapters") or [] if c.get("people", 0) > 0]


def _require_faceless(story):
    blocked = chapters_with_people(story)
    if blocked:
        raise StoryError(409, "Publishing is blocked: people are visible in "
                              + ", ".join(blocked) + ". Faces are never published; "
                              "remove those scenes first.",
                         {"blocked": blocked})


def publish(sid, fetch):
    story = load(sid)
    if story.get("status") == "published":
        return story
    fresh = [dict(c, people=(fetch(c["photo_id"]) or {}).get("people", 0))
             for c in story.get("chapters") or []]
    story["chapters"] = fresh
    _require_faceless(story)
    story["status"] = "published"
    story["published_at"] = _now()
    save(story)
    return story
