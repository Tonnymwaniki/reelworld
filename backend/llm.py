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
import json
import os
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
DOTENV = ROOT / ".env"
DATA = ROOT / "data"
CACHE_DIR = DATA / "cache"
CALLS_PATH = DATA / "llm_calls.jsonl"

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
    """Best-effort reply text (reasoning models may null the main slot)."""
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
    extra = getattr(msg, "reasoning_content", None)
    return extra if isinstance(extra, str) else ""


def _image_block(image_path):
    """Image file as a base64 data-URL block, as annotate.py does."""
    p = Path(image_path)
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(p.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


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
