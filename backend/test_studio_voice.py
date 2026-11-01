"""Focused checks for the studio voice cache (backend/studio_voice.py).

Hashing, validation, cache hits and honest errors: pure code plus
a stubbed Modal call. No model, no network.
Run from the project root:  python backend/test_studio_voice.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import studio_voice as sv  # noqa: E402  (needs the sys.path line above)

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


h1 = sv.line_hash("Hello there.", "af_heart")
check(len(h1) == 16 and all(c in "0123456789abcdef" for c in h1),
      "hash is 16 hex")
check(sv.line_hash("Hello there.", "af_heart") == h1, "hash stable")
check(sv.line_hash("  Hello there. ", "af_heart") == h1, "hash trims")
check(sv.line_hash("Hello there.", "am_adam") != h1, "hash hears the voice")
check(sv.line_hash("Other line.", "af_heart") != h1, "hash hears the text")

clean, voice = sv.check_line("  Hello. ", "")
check((clean, voice) == ("Hello.", "af_heart"), "line cleaned, default voice")
for bad in ("", "   "):
    try:
        sv.check_line(bad, None)
        check(False, "empty line rejected")
    except sv.StudioVoiceError as e:
        check(e.status == 400, "empty line rejected")
try:
    sv.check_line("x" * 501, None)
    check(False, "long line rejected")
except sv.StudioVoiceError as e:
    check(e.status == 400, "long line rejected")
try:
    sv.check_line("Hello.", "mickey")
    check(False, "unknown voice rejected")
except sv.StudioVoiceError as e:
    check(e.status == 400, "unknown voice rejected")

tmp = tempfile.TemporaryDirectory()
cache = Path(tmp.name)
calls = []


def fake_synth(text, voice):
    calls.append((text, voice))
    return b"RIFF" + bytes(2000), 1.2


orig_synth = sv.synthesize
sv.synthesize = fake_synth
try:
    rug, raw, cached = sv.speak("Hello there.", "af_heart", cache_dir=cache)
    check(rug == h1 and raw == b"RIFF" + bytes(2000) and cached is False
          and calls == [("Hello there.", "af_heart")]
          and (cache / f"{h1}.wav").exists(), "miss synthesizes and saves")
    rug2, raw2, cached2 = sv.speak("Hello there.", "af_heart",
                                   cache_dir=cache)
    check((rug2, raw2, cached2) == (h1, raw, True) and len(calls) == 1,
          "repeat is a cache hit")
    rug3, _raw3, cached3 = sv.speak("Hello there.", "am_adam",
                                    cache_dir=cache)
    check(cached3 is False and rug3 != h1, "new voice re-synthesizes")
    (cache / f"{h1}.wav").write_bytes(b"tiny")
    rug4, _raw4, cached4 = sv.speak("Hello there.", "af_heart",
                                    cache_dir=cache)
    check(cached4 is False and len(calls) == 3, "short file re-synthesizes")
    check(sv.read_cached(h1, cache_dir=cache) == b"RIFF" + bytes(2000),
          "read_cached serves the file")
finally:
    sv.synthesize = orig_synth
check(sv.read_cached("nope", cache_dir=cache) is None, "bad hash reads None")
check(sv.read_cached("0" * 16, cache_dir=cache) is None,
      "missing hash reads None")
check(sv.read_cached(h1) is None or isinstance(sv.read_cached(h1), bytes),
      "default cache dir readable")

print(f"test_studio_voice.py: {total - fails}/{total} checks passed")
