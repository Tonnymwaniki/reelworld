"""Model switchboard: primary provider with automatic fallback.

Every model call in the app goes through ask(). The primary provider
comes from PARSER_BASE_URL / PARSER_KEY_ENV / PARSER_MODEL; the
fallback from FALLBACK_BASE_URL / FALLBACK_KEY_ENV / FALLBACK_MODEL
(defaulting to Baseten). On any error, timeout or empty answer the
call is retried once on the fallback.

Settings are read live (process env first, then .env) so toggles like
FORCE_PRIMARY_FAIL apply without a restart. Keys are read by name and
never printed, logged or returned.
"""
import base64
import hashlib
import io
import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from openai import OpenAI
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DOTENV = ROOT / ".env"
DATA = ROOT / "data"
CACHE_DIR = DATA / "cache"
CALLS_PATH = DATA / "llm_calls.jsonl"
CAPS_PATH = CACHE_DIR / "llm_caps.json"
ANSWER_CACHE_DIR = CACHE_DIR / "llm"
CACHE_TTL_HOURS = 24

MIN_TOKENS = 8000  # reasoning answers starve below this (except "simple")
FALLBACK_DEFAULTS = {
    "base_url": "https://inference.baseten.co/v1",
    "key_env": "BASETEN_API_KEY",
    "model": "meta-models/muse-spark-open-1026",
}
NAIROBI = timezone(timedelta(hours=3))  # Kenya has no daylight saving

_calls = deque(maxlen=100)  # last 100 calls, in memory


class LLMBudgetSpent(RuntimeError):
    """Daily token budget is spent (callers answer resting/429)."""


def _env(name, default=None):
    """Live setting: process env wins, else the .env file, else default."""
    v = os.getenv(name)
    if v not in (None, ""):
        return v
    try:
        lines = DOTENV.read_text(encoding="utf-8").splitlines()
    except OSError:
        return default
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, val = line.partition("=")
        if k.strip() == name:
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
                val = val[1:-1]
            return val
    return default


def _int_env(name, default):
    try:
        return int(_env(name, default))
    except (TypeError, ValueError):
        return default


def setting(name, default=None):
    """Public read of a live setting (process env first, then .env)."""
    return _env(name, default)


def provider_name(base_url):
    """Short provider name from a base URL (pure)."""
    host = (urlparse(base_url or "").hostname or "").lower()
    for key in ("modal", "baseten", "meta.ai", "meta", "llama", "openai"):
        if key in host:
            return key.replace(".ai", "")
    return host or "unknown"


def provider_host(base_url):
    """Host part of a base URL only, for status output (pure)."""
    return urlparse(base_url or "").hostname or ""


def config():
    """Resolved primary/fallback provider configs (no key values)."""
    primary = {"base_url": _env("PARSER_BASE_URL") or "",
               "key_env": _env("PARSER_KEY_ENV") or "",
               "model": _env("PARSER_MODEL") or ""}
    fallback = {"base_url": _env("FALLBACK_BASE_URL", FALLBACK_DEFAULTS["base_url"]),
                "key_env": _env("FALLBACK_KEY_ENV", FALLBACK_DEFAULTS["key_env"]),
                "model": _env("FALLBACK_MODEL", FALLBACK_DEFAULTS["model"])}
    return {"primary": primary, "fallback": fallback,
            "timeout": _int_env("LLM_TIMEOUT_SECONDS", 90),
            "budget": _int_env("DAILY_TOKEN_BUDGET", 3000000)}


def _call_one(base_url, key, model, content, temperature, max_tokens,
              timeout, affinity_key):
    """Single attempt on one provider. Returns (text, prompt_tok, compl_tok, seconds)."""
    client = OpenAI(base_url=base_url, api_key=key, timeout=timeout)
    kw = {}
    if affinity_key:
        kw["extra_headers"] = {"Modal-Routing-Affinity-Key": affinity_key}
    t0 = time.monotonic()
    resp = client.chat.completions.create(
        model=model, temperature=temperature, max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}], **kw)
    seconds = time.monotonic() - t0
    usage = getattr(resp, "usage", None)
    pt = getattr(usage, "prompt_tokens", 0) or 0
    ct = getattr(usage, "completion_tokens", 0) or 0
    return _extract_text(resp).strip(), pt, ct, seconds


def _extract_text(resp):
    """Best-effort reply text; reasoning content is never used."""
    try:
        msg = resp.choices[0].message
    except (AttributeError, IndexError, TypeError):
        return ""
    content = getattr(msg, "content", None)
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") in ("text", "output_text")]
        if "".join(parts).strip():
            return "".join(parts)
    # Never fall back to reasoning_content: reasoning text must not
    # reach the browser or saved chats. llm.ask treats "" as failure
    # and retries on the fallback provider.
    return ""


def _image_data_block(raw, mime):
    """Raw image bytes as a base64 data-URL block, as annotate.py does."""
    b64 = base64.b64encode(raw).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _image_block(image_path):
    """Image file as a base64 data-URL block, as annotate.py does."""
    p = Path(image_path)
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return _image_data_block(p.read_bytes(), mime)


_caps_lock = threading.Lock()


def _tiny_image_bytes():
    """16px generated PNG for the capability probe."""
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def probe_images():
    """Force-probe: does the primary accept images? Saves + returns caps.

    Acceptance is transport success on one tiny image call (the reply
    text does not matter). Ignores FORCE_PRIMARY_FAIL and the budget:
    this tests real capability. Never raises; failures are recorded.
    """
    cfg = config()
    prov = cfg["primary"]
    caps = {"primary_accepts_images": False, "checked_at": None, "error": ""}
    name = provider_name(prov["base_url"])
    try:
        key = _env(prov["key_env"]) or ""
        if not prov["base_url"] or not prov["model"] or not key:
            raise RuntimeError("primary provider is not configured")
        content = [{"type": "text",
                    "text": "What is in this image? Reply with one word."},
                   _image_data_block(_tiny_image_bytes(), "image/png")]
        _text, pt, ct, secs = _call_one(
            prov["base_url"], key, prov["model"], content,
            0.0, MIN_TOKENS, cfg["timeout"], None)
        caps["primary_accepts_images"] = True
        caps["checked_at"] = datetime.now(timezone.utc).isoformat()
        _log_call({"timestamp": caps["checked_at"], "provider": name,
                   "model": prov["model"], "purpose": "probe",
                   "seconds": round(secs, 2), "prompt_tokens": pt,
                   "completion_tokens": ct, "ok": True, "error": "",
                   "fallback_used": False})
    except Exception as e:
        caps["error"] = f"{type(e).__name__}: {e}"[:200]
        _log_call({"timestamp": datetime.now(timezone.utc).isoformat(),
                   "provider": name, "model": prov["model"], "purpose": "probe",
                   "seconds": 0.0, "prompt_tokens": 0, "completion_tokens": 0,
                   "ok": False, "error": caps["error"], "fallback_used": False})
    try:
        CAPS_PATH.parent.mkdir(parents=True, exist_ok=True)
        CAPS_PATH.write_text(json.dumps(caps, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return caps


def image_capability():
    """Cached caps, probing on first image use (never raises)."""
    caps = _caps_file()
    if caps is not None:
        return caps
    with _caps_lock:
        caps = _caps_file()
        if caps is not None:
            return caps
        return probe_images()


def _log_call(row):
    """Append one call row to memory + jsonl; logging never breaks the call."""
    _calls.append(row)
    try:
        CALLS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CALLS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def recent_calls(n=50):
    """Last n logged calls, newest last."""
    return list(_calls)[-n:]


def log_call(provider, model, purpose, seconds, ok, error=""):
    """Log a non-chat model call (e.g. studio voice synthesis).

    TTS has no tokens, so it never spends the token budget, but it
    shares the budget gate (resting blocks it) and shows up in the
    status averages. Never raises.
    """
    try:
        _log_call({"timestamp": datetime.now(timezone.utc).isoformat(),
                   "provider": provider, "model": model, "purpose": purpose,
                   "seconds": round(seconds, 2), "prompt_tokens": 0,
                   "completion_tokens": 0, "ok": bool(ok),
                   "error": (error or "")[:200], "fallback_used": False})
    except Exception:
        pass


def _record_version(record):
    """Content hash of a stored record: any annotation edit invalidates."""
    canon = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(canon.encode()).hexdigest()[:16]


def cache_key(purpose, photo_ids, question, records):
    """Cache key from photo ids (ordered), question and record versions."""
    canon = {"purpose": purpose, "photo_ids": list(photo_ids),
             "question": (question or "").strip(),
             "records": [_record_version(r) for r in records]}
    return hashlib.sha1(json.dumps(canon, sort_keys=True).encode()).hexdigest()[:16]


def cache_get(key):
    """Cached answer payload, or None when missing/expired/corrupt."""
    try:
        raw = json.loads((ANSWER_CACHE_DIR / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or "payload" not in raw:
        return None
    try:
        created = datetime.fromisoformat(raw.get("created_at", ""))
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - created > timedelta(hours=CACHE_TTL_HOURS):
        return None
    return raw["payload"]


def cache_put(key, payload):
    """Store an answer payload for 24h. Caching never breaks the call."""
    try:
        ANSWER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (ANSWER_CACHE_DIR / f"{key}.json").write_text(
            json.dumps({"created_at": datetime.now(timezone.utc).isoformat(),
                        "payload": payload}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _caps_file():
    """Saved capability result, or None when never probed (no probing)."""
    try:
        caps = json.loads(CAPS_PATH.read_text(encoding="utf-8"))
        if isinstance(caps, dict) and "primary_accepts_images" in caps:
            return caps
    except (OSError, ValueError):
        pass
    return None


def status():
    """Provider status for GET /api/llm/status. Makes no model calls
    and returns no keys."""
    cfg = config()
    primary = {"name": provider_name(cfg["primary"]["base_url"]),
               "model": cfg["primary"]["model"],
               "host": provider_host(cfg["primary"]["base_url"])}
    fallback = {"name": provider_name(cfg["fallback"]["base_url"]),
                "model": cfg["fallback"]["model"],
                "host": provider_host(cfg["fallback"]["base_url"])}
    window = recent_calls(50)
    secs: dict = {}
    for row in window:
        secs.setdefault(row.get("provider", "?"), []).append(row.get("seconds", 0) or 0)
    avg = {p: round(sum(v) / len(v), 2) for p, v in secs.items()}
    ok = sum(1 for row in window if row.get("ok"))
    last_err = ""
    for row in reversed(window):
        if not row.get("ok") and row.get("error"):
            last_err = row["error"]
            break
    caps = _caps_file()
    if caps is None:
        images = {"primary_accepts_images": None, "checked_at": None,
                  "error": "", "handled_by": "unknown (not probed yet)"}
    else:
        images = {"primary_accepts_images": caps.get("primary_accepts_images"),
                  "checked_at": caps.get("checked_at"), "error": caps.get("error", ""),
                  "handled_by": (primary["name"] if caps.get("primary_accepts_images")
                                 else fallback["name"])}
    used = tokens_today()
    budget = cfg["budget"]
    studio_url = _env("STUDIO_VOICE_URL") or ""
    studio = {"model": "kokoro-82m",
              "host": provider_host(studio_url) if studio_url else "",
              "configured": bool(studio_url.strip())}
    return {"primary": primary, "fallback": fallback,
            "avg_seconds_per_provider": avg, "window": len(window),
            "success_rate": (round(ok / len(window), 3) if window else None),
            "tokens_today": used, "daily_budget": budget,
            "budget_left": max(0, budget - used),
            "last_error": last_err, "images": images, "studio": studio}


def tokens_today():
    """Prompt + completion tokens used since midnight Africa/Nairobi."""
    try:
        lines = CALLS_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    today = datetime.now(NAIROBI).date()
    total = 0
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        try:
            ts = datetime.fromisoformat(row.get("timestamp", ""))
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts.astimezone(NAIROBI).date() == today:
            total += (row.get("prompt_tokens") or 0) + (row.get("completion_tokens") or 0)
    return total


def ensure_budget():
    """Raise LLMBudgetSpent when the daily budget is already spent."""
    budget = config()["budget"]
    if tokens_today() >= budget:
        raise LLMBudgetSpent("daily token budget spent")


def ask(prompt, max_tokens=8000, temperature=0.1, image_path=None,
        purpose="chat", session_id=None):
    """Ask the model via primary, retrying once on the fallback.

    Returns {"text", "provider", "model", "seconds", "prompt_tokens",
    "completion_tokens", "fallback_used"}. Raises LLMBudgetSpent when
    the daily budget is spent, RuntimeError when both providers fail.
    """
    if purpose != "simple":
        max_tokens = max(max_tokens, MIN_TOKENS)
    cfg = config()
    ensure_budget()
    content = [{"type": "text", "text": prompt}]
    if image_path is not None:
        content.append(_image_block(image_path))
    force_fail = (_env("FORCE_PRIMARY_FAIL", "false").strip().lower() == "true")
    attempts = [("primary", cfg["primary"]), ("fallback", cfg["fallback"])]
    if image_path is not None and not image_capability().get("primary_accepts_images"):
        if cfg["fallback"]["base_url"] and cfg["fallback"]["model"]:
            attempts = [("fallback", cfg["fallback"])]
    text, pt, ct, secs, err, used = "", 0, 0, 0.0, "", False
    for role, prov in attempts:
        name = provider_name(prov["base_url"])
        try:
            if role == "primary" and force_fail:
                raise RuntimeError("forced primary failure (FORCE_PRIMARY_FAIL)")
            key = _env(prov["key_env"]) or ""
            if not prov["base_url"] or not prov["model"] or not key:
                raise RuntimeError(f"{role} provider is not configured")
            affinity = (session_id if role == "primary" and session_id
                        and "modal" in provider_host(prov["base_url"]) else None)
            text, apt, act, asecs = _call_one(
                prov["base_url"], key, prov["model"], content,
                temperature, max_tokens, cfg["timeout"], affinity)
            pt, ct, secs = apt, act, asecs
            if not text:
                raise RuntimeError("model returned no text")
            used = (role == "fallback")
            err = ""
            provider, model = name, prov["model"]
            break
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:200]
            provider, model = name, prov["model"]
    else:
        _log_call({"timestamp": datetime.now(timezone.utc).isoformat(),
                   "provider": provider, "model": model, "purpose": purpose,
                   "seconds": round(secs, 2), "prompt_tokens": pt,
                   "completion_tokens": ct, "ok": False, "error": err,
                   "fallback_used": True})
        raise RuntimeError(f"model call failed on both providers: {err}")
    _log_call({"timestamp": datetime.now(timezone.utc).isoformat(),
               "provider": provider, "model": model, "purpose": purpose,
               "seconds": round(secs, 2), "prompt_tokens": pt,
               "completion_tokens": ct, "ok": True, "error": "",
               "fallback_used": used})
    return {"text": text, "provider": provider, "model": model,
            "seconds": round(secs, 2), "prompt_tokens": pt,
            "completion_tokens": ct, "fallback_used": used}


def _call_tools_one(base_url, key, model, messages, tools, temperature,
                    max_tokens, timeout, affinity_key):
    """Single tool-calling attempt. Returns (text, raw_calls, pt, ct, secs).

    raw_calls is [(call_id, name, args_str)]. Only the real content
    slot is read — reasoning_content is never used, shown or stored.
    """
    client = OpenAI(base_url=base_url, api_key=key, timeout=timeout)
    kw = {}
    if affinity_key:
        kw["extra_headers"] = {"Modal-Routing-Affinity-Key": affinity_key}
    t0 = time.monotonic()
    resp = client.chat.completions.create(
        model=model, temperature=temperature, max_tokens=max_tokens,
        messages=messages, tools=tools, **kw)
    seconds = time.monotonic() - t0
    usage = getattr(resp, "usage", None)
    pt = getattr(usage, "prompt_tokens", 0) or 0
    ct = getattr(usage, "completion_tokens", 0) or 0
    try:
        msg = resp.choices[0].message
    except (AttributeError, IndexError, TypeError):
        return "", [], pt, ct, seconds
    content = getattr(msg, "content", None)
    text = content.strip() if isinstance(content, str) else ""
    raw = []
    for tc in getattr(msg, "tool_calls", None) or []:
        fn = getattr(tc, "function", None)
        if fn is None:
            continue
        raw.append((getattr(tc, "id", "") or "",
                    getattr(fn, "name", "") or "",
                    getattr(fn, "arguments", "") or ""))
    return text, raw, pt, ct, seconds


def ask_tools(messages, tools, purpose="route", session_id=None,
              max_tokens=8000, temperature=0.1):
    """One tool-calling round, retrying once on the fallback provider.

    Returns {"text", "calls", "provider", "model", "seconds",
    "fallback_used", "malformed"}. calls is [{id, name, args}]
    with args parsed ({} when the JSON is broken, which marks the
    round malformed). A round with no calls and no text is also
    malformed — the caller falls back to a plain JSON prompt.
    FORCE_TOOLCALL_FAIL=true simulates a broken provider (for the
    fallback test): both attempts come back malformed without any
    network use. Raises LLMBudgetSpent when the budget is spent.
    """
    max_tokens = max(max_tokens, MIN_TOKENS)
    cfg = config()
    ensure_budget()
    force_fail = (_env("FORCE_TOOLCALL_FAIL", "false").strip().lower() == "true")
    attempts = [("primary", cfg["primary"]), ("fallback", cfg["fallback"])]
    text, calls, malformed = "", [], True
    provider, model, secs, pt, ct, used = "", "", 0.0, 0, 0, False
    for role, prov in attempts:
        name = provider_name(prov["base_url"])
        err = ""
        try:
            if force_fail:
                raise RuntimeError("forced tool-call failure (FORCE_TOOLCALL_FAIL)")
            key = _env(prov["key_env"]) or ""
            if not prov["base_url"] or not prov["model"] or not key:
                raise RuntimeError(f"{role} provider is not configured")
            affinity = (session_id if role == "primary" and session_id
                        and "modal" in provider_host(prov["base_url"]) else None)
            atext, araw, apt, act, asecs = _call_tools_one(
                prov["base_url"], key, prov["model"], messages, tools,
                temperature, max_tokens, cfg["timeout"], affinity)
            acalls, bad = [], False
            for cid, cname, cargs in araw:
                try:
                    args = json.loads(cargs or "{}")
                except ValueError:
                    args, bad = {}, True
                if not isinstance(args, dict):
                    args, bad = {}, True
                acalls.append({"id": cid, "name": cname, "args": args})
            if bad or (not acalls and not atext):
                raise RuntimeError("malformed tool-call reply")
            text, calls, malformed = atext, acalls, False
            pt, ct, secs = apt, act, asecs
            used = (role == "fallback")
            err = ""
            provider, model = name, prov["model"]
            ok = True
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:200]
            provider, model = name, prov["model"]
            ok = False
        _log_call({"timestamp": datetime.now(timezone.utc).isoformat(),
                   "provider": provider, "model": model, "purpose": purpose,
                   "seconds": round(secs if ok else 0.0, 2),
                   "prompt_tokens": pt if ok else 0,
                   "completion_tokens": ct if ok else 0, "ok": ok,
                   "error": err, "fallback_used": used})
        if ok:
            break
    return {"text": text, "calls": calls, "provider": provider,
            "model": model, "seconds": round(secs, 2),
            "fallback_used": used, "malformed": malformed}
