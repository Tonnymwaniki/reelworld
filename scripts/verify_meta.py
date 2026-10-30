"""End-to-end verification of the configured reasoning backend.

Exercises probe, parse, Engine.answer, /api/ask, /api/compare and
/api/story with real inputs and writes a JSON report the agent can read.
Never prints or writes key material (key NAME only).

Run from the project root (needs your Python env + network):
    python scripts\\verify_meta.py [--quick]

Report: data/verify_report.json (git-ignored). Exit 0 if every step
passed, 1 otherwise (the report is still written).
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from openai import OpenAI

import api as api_mod
from chat import resolve_parser

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "data" / "verify_report.json"
QUICK = "--quick" in sys.argv[1:]


def cut(v, n=300):
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    return s if len(s) <= n else s[:n] + "..."


def step(report, name, fn):
    t0 = time.time()
    try:
        detail = fn()
        report["steps"][name] = {"ok": True, "seconds": round(time.time() - t0, 1),
                                 "detail": detail}
        print(f"[ok] {name} ({report['steps'][name]['seconds']}s)")
    except Exception as e:  # noqa: BLE001 - every step must report, not abort
        report["steps"][name] = {"ok": False, "seconds": round(time.time() - t0, 1),
                                 "error": cut(f"{type(e).__name__}: {e}")}
        print(f"[FAIL] {name}: {report['steps'][name]['error']}")


def main():
    report = {"when": datetime.now(timezone.utc).isoformat(), "steps": {}}
    base, key_env, model = resolve_parser()
    report["backend"] = {"base": base, "model": model, "key_env": key_env,
                         "meta": "llama.com" in (base or "")}
    print(f"backend: base={base} model={model} key_env={key_env}")

    import os
    key = os.environ[key_env]

    def do_keyshape():
        raw = os.environ.get(key_env, "")
        s = raw.strip()
        return {"length": len(s), "edge_whitespace": raw != s,
                "quoted": len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'",
                "internal_space": any(c.isspace() for c in s),
                "nonprint": sum(1 for c in s if ord(c) < 32 or ord(c) > 126)}

    def do_probe():
        resp = OpenAI(base_url=base, api_key=key).chat.completions.create(
            model=model, temperature=0, max_tokens=20,
            messages=[{"role": "user", "content": "Reply with only the word: ok"}])
        return {"reply": cut((resp.choices[0].message.content or "").strip(), 60)}

    eng = api_mod.get_engine("verify")

    def do_parse():
        out = eng.parse("a busy street market with fresh vegetables")
        if isinstance(out, tuple):
            intent, fell = out
        else:
            intent, fell = out, None
        if fell:
            raise RuntimeError("parser fell back (LLM unusable)")
        return {"fell_back": fell, "intent": cut(intent, 500)}

    def do_answer():
        text = eng.answer("landmarks_003", "What signs are visible?")
        return {"chars": len(text or ""), "text": cut(text or "")}

    def do_ask():
        r = api_mod.ask(api_mod.AskRequest(photo_id="landmarks_003",
                                           question="What signs are visible?"))
        return {"source": r.get("source"), "note": cut(r.get("note") or ""),
                "answer": cut(r.get("answer") or "")}

    def do_compare():
        r = api_mod.compare(api_mod.CompareRequest(photo_a="landmarks_003",
                                                   photo_b="cbd_002"))
        return {"differences": len(r.get("differences") or []),
                "answer": cut(r.get("answer") or "")}

    def do_outline():
        r = api_mod.api_outline(api_mod.OutlineRequest(photo_id="landmarks_003",
                                                       prompt="tower"))
        return {"count": r.get("count"), "model": r.get("model"),
                "first": cut((r.get("matches") or [{}])[0])}

    def do_story():
        r = api_mod.story(api_mod.StoryRequest(theme="markets", collection="world"))
        ch = r.get("chapters") or []
        return {"title": cut(r.get("title") or ""), "chapters": len(ch),
                "first_heading": cut((ch[0].get("heading") if ch else "") or "")}

    step(report, "keyshape", do_keyshape)
    step(report, "probe", do_probe)
    step(report, "parse", do_parse)
    step(report, "answer", do_answer)
    step(report, "ask", do_ask)
    step(report, "compare", do_compare)
    step(report, "outline", do_outline)
    if QUICK:
        report["steps"]["story"] = {"ok": True, "seconds": 0, "detail": "skipped (--quick)"}
        print("[ok] story (skipped --quick)")
    else:
        step(report, "story", do_story)

    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    failed = [n for n, s in report["steps"].items() if not s["ok"]]
    print(f"report: {REPORT} failed={failed or 'none'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
