"""Script-rules acceptance check for a directed film.

Usage from the project root:
  python scripts/script_check.py <film_json>

<film_json> is a saved POST /api/films response ({"film": ...}).
Reports, per scene: words vs duration fit, banned phrases,
duplicate openers, silent scenes + reasons, the closing echo,
and focus/held-back presence. Prints no keys. Exit 1 on any
rule break. Over-long lines break (they overrun their scene);
under-minimum lines are noted but pass: the editor shortens
lines to stay truthful, and a short line simply breathes.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from film import FINAL_SHORT_WORDS, _content_words, _fit_range  # noqa: E402
from voices import BANNED  # noqa: E402


def opener(text):
    return " ".join(text.split()[:3]).lower()


def main(path):
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("utf-16")
    data = json.loads(text)
    film = data.get("film", data)
    scenes = film.get("scenes") or []
    bad = 0
    print(f"title: {film.get('title')}")
    print(f"scenes: {len(scenes)}")
    seen_openers = {}
    silent = 0
    for pos, s in enumerate(scenes):
        pid = s.get("photo_id")
        narr = s.get("narration") or ""
        cap = s.get("caption") or ""
        secs = s.get("seconds") or 0
        foc = (s.get("focus_detail") or {}).get("text") or ""
        if s.get("caption_note"):
            print(f"- {pid}: FIXED vantage line ({secs}s): {narr}")
            print(f"  focus: {foc or 'MISSING'}; "
                  f"held back: {len(s.get('held_back') or [])}")
            if not foc:
                bad += 1
            continue
        if not narr.strip():
            silent += 1
            print(f"- {pid}: SILENT ({secs}s) reason: "
                  f"{s.get('silent_reason') or 'MISSING'}")
            if not (s.get("silent_reason") or "").strip():
                bad += 1
            continue
        words = len(narr.split())
        lo, hi = _fit_range(secs)
        need = [s for s in scenes if not s.get("caption_note")]
        last = need and pid == need[-1].get("photo_id")
        if last:
            hi = min(FINAL_SHORT_WORDS, hi)
        over = words > hi
        short = (not last) and words < lo
        if over:
            bad += 1
        mark = "MISFIT" if over else ("short: breathes" if short else "ok")
        need_txt = f"≤{hi} words, final" if last else f"{lo}-{hi} words"
        print(f"- {pid}: {words}w in {secs}s "
              f"(needs {need_txt}) [{mark}]")
        found = [b for b in BANNED if b in narr.lower() or b in cap.lower()]
        if found:
            bad += 1
            print(f"  BANNED: {', '.join(found)}")
        op = opener(narr)
        if op in seen_openers:
            bad += 1
            print(f"  OPENER repeats {seen_openers[op]}: {op!r}")
        else:
            seen_openers[op] = pid
        foc = (s.get("focus_detail") or {}).get("text") or ""
        print(f"  focus: {foc or 'MISSING'}; "
              f"held back: {len(s.get('held_back') or [])}")
        if not foc:
            bad += 1
    need = [s for s in scenes if not s.get("caption_note")]
    if need and silent * 4 > len(need):
        bad += 1
        print(f"TOO SILENT: {silent} of {len(need)} (max a quarter)")
    else:
        print(f"silent: {silent} of {len(need)} scripted (max a quarter)")
    first = (need[0].get("narration") or "") if need else ""
    last_n = (need[-1].get("narration") or "") if need else ""
    if first.strip() and last_n.strip():
        echo = sorted(_content_words(first, []) & _content_words(last_n, []))
        print(f"closing echo: {', '.join(echo) if echo else 'NONE'}")
        if not echo:
            bad += 1
    print("PASS" if bad == 0 else f"FAIL ({bad} breaks)")
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: script_check.py <film-json>")
    sys.exit(main(sys.argv[1]))
