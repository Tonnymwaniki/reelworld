"""Manual probe for Meta's API over the OpenAI-compatible path chat.py uses.

Needs META_API_BASE and META_MODEL in .env (from Meta's endpoint docs);
uses the META_API_KEY already there. Sends one tiny prompt and prints the
reply. Never prints the key. Not part of any test suite.

Run from the project root:
    python scripts\\probe_meta.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

base = (os.getenv("META_API_BASE") or "").strip()
model = (os.getenv("META_MODEL") or "").strip()
key = (os.getenv("META_API_KEY") or "").strip()
missing = [n for n, v in (("META_API_BASE", base), ("META_MODEL", model),
                          ("META_API_KEY", key)) if not v]
if missing:
    raise SystemExit(f"missing in .env: {', '.join(missing)} (see Meta's endpoint docs)")

resp = OpenAI(base_url=base, api_key=key).chat.completions.create(
    model=model, temperature=0, max_tokens=20,
    messages=[{"role": "user", "content": "Reply with only the word: ok"}])
print("meta api replied:", (resp.choices[0].message.content or "").strip()[:200])
