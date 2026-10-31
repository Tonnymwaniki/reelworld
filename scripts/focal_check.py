"""One-shot focal probe (live vision, cached).

Usage from the project root (up to 8 ids, one contact sheet):
  python scripts/focal_check.py [--refresh] <photo_id> [<photo_id> ...]
  python scripts/focal_check.py --show-raw <photo_id> [<photo_id> ...]

Loads photo bytes via the photos table, runs ensure_focal, prints the
entries and the trace. --refresh deletes the cached entries first so
vision runs again. --show-raw prints the model's raw reply instead
(one sheet, no parsing, no cache writes). Prints no keys.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import llm  # noqa: E402
from api import ROOT, get_sb  # noqa: E402
from focal import (FOCAL_DIR, build_contact_sheet, build_focal_prompt,  # noqa: E402
                   ensure_focal)


def load_bytes(pid):
    rows = (get_sb().table("photos").select("file").eq("photo_id", pid)
            .execute().data or [])
    if not rows:
        return None
    p = ROOT / str(rows[0].get("file") or "")
    if not p.exists():
        return None
    return p.read_bytes(), "image/png" if p.suffix.lower() == ".png" else "image/jpeg"


def main(ids):
    trace = []
    out = ensure_focal(ids, load_bytes=load_bytes, trace=trace)
    print(json.dumps({"entries": out, "trace": trace}, ensure_ascii=False, indent=1))


def show_raw(ids):
    items = []
    for pid in ids:
        got = load_bytes(pid)
        if got is None:
            print(f"(no bytes for {pid})")
        else:
            items.append((pid, got[0]))
    if not items:
        sys.exit(1)
    sheet, _ = build_contact_sheet(items)
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(sheet)
        tmp_sheet = f.name
    print(llm.ask(build_focal_prompt([p for p, _ in items]),
                  image_path=tmp_sheet, purpose="focal")["text"][:3000])


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--show-raw"]:
        if len(args) < 2:
            print("usage: python scripts/focal_check.py --show-raw <photo_id> [...]")
            sys.exit(2)
        show_raw(args[1:9])
    else:
        if args[:1] == ["--refresh"]:
            for pid in args[1:9]:
                (FOCAL_DIR / f"{pid}.json").unlink(missing_ok=True)
            args = args[1:]
        if not args:
            print("usage: python scripts/focal_check.py [--refresh] <photo_id> [...]")
            sys.exit(2)
        main(args[:8])
