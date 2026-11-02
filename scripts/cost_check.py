"""Token/cost acceptance check for one story creation.

Usage from the project root:
  python scripts/cost_check.py <iso_timestamp>

Sums every llm_calls.jsonl row logged after <iso_timestamp>
(use the minute before the creation call): calls by purpose,
prompt/completion tokens, seconds, and cost at Modal prices
($1.25 per million prompt tokens, $4.25 per million completion
tokens). Prints no keys.
"""
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROMPT_PER_M = 1.25
COMPLETION_PER_M = 4.25


def main(since):
    root = Path(__file__).resolve().parent.parent
    path = root / "data" / "llm_calls.jsonl"
    start = datetime.fromisoformat(since)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    purposes: Counter = Counter()
    pt = ct = 0
    secs = 0.0
    n = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
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
        if ts < start:
            continue
        n += 1
        purposes[row.get("purpose", "?")] += 1
        pt += row.get("prompt_tokens") or 0
        ct += row.get("completion_tokens") or 0
        secs += row.get("seconds") or 0
    cost = pt / 1e6 * PROMPT_PER_M + ct / 1e6 * COMPLETION_PER_M
    print(f"calls since {since}: {n}")
    for purpose, count in sorted(purposes.items()):
        print(f"  {purpose}: {count}")
    print(f"prompt tokens: {pt}")
    print(f"completion tokens: {ct}")
    print(f"model seconds (summed): {round(secs, 1)}")
    print(f"estimate: ${cost:.4f} "
          f"(@ ${PROMPT_PER_M}/M prompt, ${COMPLETION_PER_M}/M completion)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: cost_check.py <iso-start>")
    main(sys.argv[1])
