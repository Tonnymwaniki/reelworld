"""Compute visual attributes for photos (resumable).

Usage from the project root:
  python scripts/attrs_run.py [--limit N] [--refresh-failed]

Reads photo ids + files from the built index, judges each photo
from the image itself (4 per vision call), caches at
data/attributes/<photo_id>.json, then prints the distribution.
Cached entries are skipped, so rerunning is safe; --refresh-failed
recomputes cached fallbacks first. Prints no keys.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from attributes import ATTR_DIR, ensure_attributes  # noqa: E402

SLOTS = ("atmosphere", "light", "time_of_day", "water_visible",
         "vegetation", "crowd")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--refresh-failed", action="store_true")
    args = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    meta = json.loads((root / "data" / "index" / "meta.json").read_text(
        encoding="utf-8"))
    files = {m["photo_id"]: root / m["file"] for m in meta}
    if args.limit:
        files = dict(list(files.items())[:args.limit])

    def load_bytes(pid):
        try:
            return files[pid].read_bytes(), "image/jpeg"
        except (OSError, KeyError):
            return None

    if args.refresh_failed:
        for pid in files:
            p = ATTR_DIR / f"{pid}.json"
            try:
                if json.loads(p.read_text(encoding="utf-8")).get("fallback"):
                    p.unlink()
            except (OSError, ValueError):
                pass
    trace = []
    out = ensure_attributes(list(files), load_bytes=load_bytes, trace=trace)
    for t in trace:
        print(f"[{t['step']}] {t['detail']}")

    dist = {s: Counter() for s in SLOTS}
    fallbacks, missing = [], []
    for pid in files:
        p = ATTR_DIR / f"{pid}.json"
        try:
            entry = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            missing.append(pid)
            continue
        if entry.get("fallback"):
            fallbacks.append(pid)
        for s in SLOTS:
            dist[s][(entry.get(s) or {}).get("value", "?")] += 1
    print(f"\nphotos: {len(files)} judged: {len(out)} "
          f"fallbacks: {len(fallbacks)} missing: {len(missing)}")
    if fallbacks:
        print("fallback ids: " + ", ".join(sorted(fallbacks)))
    if missing:
        print("missing ids: " + ", ".join(sorted(missing)))
    for s in SLOTS:
        vals = ", ".join(f"{v}={n}" for v, n in sorted(dist[s].items()))
        print(f"{s}: {vals}")


if __name__ == "__main__":
    main()
