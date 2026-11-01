"""Studio narration voice: Kokoro-82M on Modal, cached by line hash.

Each narration line is synthesized once; the WAV is cached in
data/audio/<hash>.wav (git-ignored) and served to the player and
the exporter. Settings (names only): STUDIO_VOICE_URL (the
deployed Modal endpoint), STUDIO_VOICE_KEY (shared secret, also in
the Modal secret "reelworld-tts"), STUDIO_VOICE_TIMEOUT (seconds,
default 180). See modal/tts.py and docs/studio_voice.md.
"""
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import llm

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "data" / "audio"
MODEL = "kokoro-82m"
VOICES = ("af_heart", "af_sarah", "am_adam", "am_michael",
          "bf_emma", "bm_george")
DEFAULT_VOICE = "af_heart"
MAX_CHARS = 500


class StudioVoiceError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def line_hash(text, voice):
    """Cache key for one line (pure): sha1(model|voice|text), 16 hex."""
    canon = f"{MODEL}|{voice}|{(text or '').strip()}"
    return hashlib.sha1(canon.encode()).hexdigest()[:16]


def check_line(text, voice):
    """(clean text, voice); raises StudioVoiceError(400) when invalid."""
    clean = (text or "").strip()
    if not clean:
        raise StudioVoiceError(400, "text must not be empty.")
    if len(clean) > MAX_CHARS:
        raise StudioVoiceError(
            400, f"text must be {MAX_CHARS} characters or fewer.")
    voice = (voice or "").strip() or DEFAULT_VOICE
    if voice not in VOICES:
        raise StudioVoiceError(
            400, f"voice must be one of: {', '.join(VOICES)}.")
    return clean, voice


def configured():
    """True when the Modal endpoint URL is set (key checked on use)."""
    return bool((llm.setting("STUDIO_VOICE_URL") or "").strip())


def _timeout():
    try:
        return max(10, int(llm.setting("STUDIO_VOICE_TIMEOUT", 180)))
    except (TypeError, ValueError):
        return 180


def synthesize(text, voice):
    """Raw WAV bytes from the Modal endpoint (one HTTP call).

    Raises StudioVoiceError(501) when unconfigured, (502) when the
    call fails. Returns (bytes, seconds).
    """
    url = (llm.setting("STUDIO_VOICE_URL") or "").strip()
    key = llm.setting("STUDIO_VOICE_KEY") or ""
    if not url or not key:
        raise StudioVoiceError(501, "Studio voice is not configured.")
    body = json.dumps({"text": text, "voice": voice,
                       "key": key}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"},
        method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as res:
            raw = res.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = (json.loads(e.read().decode()).get("detail") or "")
        except Exception:
            detail = ""
        raise StudioVoiceError(
            502, f"studio voice failed (HTTP {e.code})"
                 + (f": {detail}" if detail else ""))
    except Exception as e:
        raise StudioVoiceError(
            502, f"studio voice failed: {type(e).__name__}: {e}"[:160])
    if len(raw) < 1000:
        raise StudioVoiceError(502, "studio voice returned no audio.")
    return raw, round(time.monotonic() - t0, 2)


def speak(text, voice=None, cache_dir=None):
    """(hash, wav_bytes, cached): synthesized line, cached by hash.

    Cache hits skip the Modal call entirely. Raises
    StudioVoiceError on bad input (400), missing config (501) or
    synthesis failure (502).
    """
    clean, voice = check_line(text, voice)
    rug = line_hash(clean, voice)
    path = (Path(cache_dir) if cache_dir else AUDIO_DIR) / f"{rug}.wav"
    try:
        raw = path.read_bytes()
        if len(raw) >= 1000:
            return rug, raw, True
    except OSError:
        pass
    raw, _secs = synthesize(clean, voice)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    except OSError:
        pass
    return rug, raw, False


def read_cached(rug, cache_dir=None):
    """Cached WAV bytes for a hash, or None (pure file read)."""
    if not isinstance(rug, str) or len(rug) != 16:
        return None
    try:
        int(rug, 16)
    except ValueError:
        return None
    try:
        raw = ((Path(cache_dir) if cache_dir else AUDIO_DIR)
               / f"{rug}.wav").read_bytes()
        return raw if len(raw) >= 1000 else None
    except OSError:
        return None
