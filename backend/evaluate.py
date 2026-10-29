"""
ReelWorld: honest retrieval evaluation.

  python backend\\evaluate.py build   steps 1-3: top-10 label sheet per query
                                     in data/eval/queries.json, plus the
                                     sign-accuracy sheet. No labels guessed.
  python backend\\evaluate.py score   step 4: hit@5, p@5, MRR@5 and sign
                                     accuracy from YOUR hand labels, written
                                     with an honest failure list to
                                     docs/evaluation.md.

What is measured: retrieval only (Engine.search over the world
collection, no language-model calls). Message parsing (message -> spec)
is not covered; each spec in queries.json is the literal reading of
its message. Label cells left blank are excluded from every metric.
"""
import csv
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chat import EMPTY_SPEC, Engine  # noqa: E402  (needs the sys.path line above)

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "data" / "eval"
QUERIES_PATH = EVAL_DIR / "queries.json"
LABEL_PATH = EVAL_DIR / "label_sheet.csv"
SIGN_PATH = EVAL_DIR / "sign_sheet.csv"
REPORT_PATH = ROOT / "docs" / "evaluation.md"

SIGN_SAMPLE = 20
SIGN_SEED = 7


def load_queries():
    data = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    default_coll = data.get("collection", "world")
    out = []
    for q in data["queries"]:
        spec = dict(EMPTY_SPEC)
        spec["query"] = q["query"]
        spec["collection"] = q.get("collection", default_coll)
        for k in ("viewpoints", "max_people", "must_include", "avoid_terms"):
            if k in q:
                spec[k] = q[k]
        out.append({"id": q["id"], "query": q["query"], "spec": spec})
    return out


def top_ten(eng, spec):
    """Top 10 exactly as the engine ranks them: two top-5 calls, the
    second excluding the first five ids. Same scoring, no duplication."""
    first, _, _ = eng.search(spec, set())
    ids = {r["photo_id"] for r in first}
    second, _, _ = eng.search(spec, ids)
    return (first + second)[:10]


def cmd_build():
    queries = load_queries()
    print(f"Loading engine ({len(queries)} queries, world collection) ...")
    eng = Engine()
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    with open(LABEL_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["query_id", "query", "rank", "photo_id", "caption", "file", "relevant"])
        for q in queries:
            rows = top_ten(eng, q["spec"])
            print(f"  {q['id']}: {q['query'][:60]!r} -> {len(rows)} results")
            for n, r in enumerate(rows, 1):
                w.writerow([q["id"], q["query"], n, r["photo_id"],
                            r.get("caption") or "", r.get("file") or "", ""])
    print(f"wrote {LABEL_PATH}")
    photos = (eng.sb.table("photos").select("photo_id,file,record")
              .eq("collection", "world").execute().data or [])
    with_signs = [p for p in photos
                  if ((p.get("record") or {}).get("observed") or {}).get("visible_text")]
    print(f"{len(with_signs)} world photos have signs read; sampling {SIGN_SAMPLE} (seed {SIGN_SEED})")
    sample = random.Random(SIGN_SEED).sample(with_signs, min(SIGN_SAMPLE, len(with_signs)))
    n_signs = 0
    with open(SIGN_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["photo_id", "file", "sign_text", "legibility", "correct"])
        for p in sorted(sample, key=lambda p: p["photo_id"]):
            vt = (p["record"]["observed"] or {}).get("visible_text") or []
            for s in vt:
                if not isinstance(s, dict):
                    continue
                w.writerow([p["photo_id"], p.get("file") or "",
                            s.get("text") or "", s.get("legibility") or "", ""])
                n_signs += 1
    print(f"wrote {SIGN_PATH} ({len(sample)} photos, {n_signs} signs)")
    print("Fill the empty columns by hand: relevant with 1 or 0, correct with 1 or 0.")
    print("Then run: python backend\\evaluate.py score")


def cell01(raw):
    t = (raw or "").strip().lower()
    if t in ("1", "yes", "y", "true", "t"):
        return 1
    if t in ("0", "no", "n", "false", "f"):
        return 0
    return None


def cmd_score():
    if not LABEL_PATH.exists() or not SIGN_PATH.exists():
        print("Sheets are missing; run: python backend\\evaluate.py build")
        sys.exit(1)
    by_query = {}
    order = []
    with open(LABEL_PATH, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            qid = (row.get("query_id") or "").strip()
            if not qid:
                continue
            if qid not in by_query:
                by_query[qid] = {"query": (row.get("query") or "").strip(), "rows": []}
                order.append(qid)
            try:
                rank = int((row.get("rank") or "0").strip())
            except ValueError:
                rank = 0
            by_query[qid]["rows"].append({
                "rank": rank, "photo_id": (row.get("photo_id") or "").strip(),
                "caption": (row.get("caption") or "").strip(),
                "label": cell01(row.get("relevant"))})
    scored, partial, hits, precs, mrrs, failures = [], [], [], [], [], []
    for qid in order:
        info = by_query[qid]
        rows = sorted(info["rows"], key=lambda r: r["rank"])
        top5 = [r for r in rows if 1 <= r["rank"] <= 5]
        if len(top5) < 5 or any(r["label"] is None for r in top5):
            partial.append(qid)
            continue
        scored.append(qid)
        rel = [r for r in top5 if r["label"] == 1]
        hits.append(1 if rel else 0)
        precs.append(len(rel) / 5)
        mrrs.append(1 / min(r["rank"] for r in rel) if rel else 0)
        if not rel:
            failures.append((qid, info["query"], [r["photo_id"] for r in top5]))
    sign_rows = 0
    sign_ok = 0
    sign_bad = []
    with open(SIGN_PATH, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            v = cell01(row.get("correct"))
            if v is None:
                continue
            sign_rows += 1
            sign_ok += v
            if not v:
                sign_bad.append(((row.get("photo_id") or "").strip(),
                                 (row.get("sign_text") or "").strip()))
    if not scored and not sign_rows:
        print("No hand labels found yet: fill the 'relevant' column of")
        print(f"{LABEL_PATH} and the 'correct' column of {SIGN_PATH} with 1 or 0,")
        print("then re-run: python backend\\evaluate.py score")
        sys.exit(1)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def avg(xs):
        return sum(xs) / len(xs) if xs else 0.0

    lines = [
        "# ReelWorld evaluation",
        "",
        f"Scored {now} from hand labels. Retrieval only: `Engine.search`",
        "over the world collection (no language-model calls); parsing",
        "(message -> spec) is not covered. Queries: `data/eval/queries.json`;",
        f"sign sample: {SIGN_SAMPLE} seeded photos (seed {SIGN_SEED}).",
        "Blank label cells are excluded from every metric.",
        "",
        "## Search",
        "",
        f"Queries scored: {len(scored)} of {len(order)}" +
        (f" ({len(partial)} incomplete: {', '.join(partial)})" if partial else ""),
        "",
        f"- hit rate@5: {avg(hits):.3f} (share of queries with a relevant photo in the top 5)",
        f"- precision@5: {avg(precs):.3f} (mean relevant share of the top 5)",
        f"- MRR@5: {avg(mrrs):.3f} (mean 1/rank of the first relevant photo in the top 5)",
        "",
    ]
    if failures:
        lines += ["### Queries with nothing relevant in the top 5", ""]
        for qid, q, ids in failures:
            lines.append(f"- {qid} {q!r}: showed {', '.join(ids)}")
        lines.append("")
    else:
        lines += ["Every scored query had a relevant photo in the top 5.", ""]
    lines += [
        "## Sign reading",
        "",
        (f"Signs marked: {sign_rows}; accuracy: {sign_ok / sign_rows:.3f} "
         f"({sign_ok}/{sign_rows} correct)" if sign_rows else "No signs marked yet."),
        "",
    ]
    if sign_bad:
        lines += ["### Signs marked wrong", ""]
        for pid, text in sign_bad:
            lines.append(f"- {pid}: stored {text!r}")
        lines.append("")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {REPORT_PATH}")
    print(f"search: {len(scored)}/{len(order)} queries, "
          f"hit@5 {avg(hits):.3f}, p@5 {avg(precs):.3f}, MRR@5 {avg(mrrs):.3f}")
    if sign_rows:
        print(f"signs: {sign_ok}/{sign_rows} = {sign_ok / sign_rows:.3f}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("build", "score"):
        print("usage: python backend\\evaluate.py [build|score]")
        sys.exit(2)
    {"build": cmd_build, "score": cmd_score}[sys.argv[1]]()
