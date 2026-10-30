"""Manual probe for the configured reasoning backend (Meta Llama or Baseten).

Reads the same resolve_parser() chat.py uses, prints which backend is
active (base URL, model, key NAME only -- never the key), sends one tiny
prompt and prints the reply. Not part of any test suite.

Run from the project root:
    python scripts\\probe_meta.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from openai import OpenAI

from chat import resolve_parser  # noqa: E402  (needs the sys.path line above)

base, key_env, model = resolve_parser()
print(f"parser: base={base} model={model} key_env={key_env}")
try:
    key = os.environ[key_env]
except KeyError:
    raise SystemExit(f"key var {key_env} is not set in .env")

resp = OpenAI(base_url=base, api_key=key).chat.completions.create(
    model=model, temperature=0, max_tokens=20,
    messages=[{"role": "user", "content": "Reply with only the word: ok"}])
print("api replied:", (resp.choices[0].message.content or "").strip()[:200])
