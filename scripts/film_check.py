"""Directed-film probe (grows one step at a time; step 2: beat sheet).

Usage from the project root:
  python scripts/film_check.py --prompt "my day at KICC" [--source mine|world|both]
                               [--target short|medium] [--style postcard]
                               [--ids p1,p2,p3]

With --ids the search is skipped. Prints the beat sheet, its source
(director / director-retry / fallback) and the trace. Prints no keys.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from api import ROOT, get_sb  # noqa: E402
from chat import EMPTY_SPEC, Engine  # noqa: E402
from director import (TARGET_SCENES, fallback_beats, plan_beats,  # noqa: E402
                      summarize_record)
from focal import ensure_focal  # noqa: E402

SOURCE_MAP = {"mine": "personal", "world": "world", "both": "both"}


def fetch_rows(ids):
    rows = (get_sb().table("photos")
            .select("photo_id,viewpoint,file,record,collection")
            .in_("photo_id", ids).execute().data or [])
    by_id = {r["photo_id"]: r for r in rows}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"unknown photo ids: {', '.join(missing)}")
    return [by_id[i] for i in ids]


def search_ids(prompt, source, target):
    eng = Engine()
    spec = dict(EMPTY_SPEC)
    spec["query"] = prompt
    spec["collection"] = SOURCE_MAP[source]
    rows, _note, _trace = eng.search(spec, set())
    hi = TARGET_SCENES[target][1]
    ids = [r["photo_id"] for r in rows[:hi]]
    if not ids:
        raise SystemExit("no photos found for that prompt.")
    return ids


def load_bytes_for(by_file):
    def load(pid):
        p = ROOT / str(by_file[pid])
        return (p.read_bytes(), "image/png" if p.suffix.lower() == ".png"
                else "image/jpeg") if p.exists() else None
    return load


def main(ns):
    if ns.ids:
        ids = [i.strip() for i in ns.ids.split(",") if i.strip()]
    else:
        ids = search_ids(ns.prompt, ns.source, ns.target)
    rows = fetch_rows(ids)
    briefs = [summarize_record(r["photo_id"], r.get("viewpoint"),
                               r.get("record") or {}) for r in rows]
    trace = []
    by_file = {r["photo_id"]: r.get("file") for r in rows}
    focals = ensure_focal(ids, load_bytes=load_bytes_for(by_file), trace=trace)
    sheet, source = plan_beats(ns.prompt or "untitled", ns.style, ns.target,
                               briefs, focals, trace=trace)
    print(json.dumps({"source": source, "beatsheet": sheet, "trace": trace,
                      "focal_fallbacks": sorted(p for p, f in focals.items()
                                                if f.get("fallback"))},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="")
    ap.add_argument("--source", default="both", choices=sorted(SOURCE_MAP))
    ap.add_argument("--target", default="short", choices=["short", "medium"])
    ap.add_argument("--style", default="postcard")
    ap.add_argument("--ids", default="")
    ns = ap.parse_args()
    if not ns.prompt and not ns.ids:
        ap.error("give --prompt or --ids")
    main(ns)
