"""Direct key test: POST to the Llama compat endpoint without app code.

Reads META_API_KEY + LLAMA_WONDER_MODEL from .env, prints one HTTP
status and the reply or error body. Never prints the key. Stdlib only.

Run from the project root:
    python scripts\\key_test.py
"""
import json
import urllib.error
import urllib.request
from pathlib import Path

env = (Path(__file__).resolve().parent.parent / ".env").read_text(encoding="utf-8")
vals = {}
for line in env.splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        vals[k.strip()] = v.strip()
key = vals.get("META_API_KEY", "")
model = vals.get("LLAMA_WONDER_MODEL", "Llama-4-Maverick-17B-128E-Instruct")
if not key:
    raise SystemExit("META_API_KEY is empty in .env")

body = json.dumps({"model": model,
                   "messages": [{"role": "user", "content": "say ok"}],
                   "max_tokens": 10}).encode()
req = urllib.request.Request(
    "https://api.llama.com/compat/v1/chat/completions", data=body,
    headers={"Content-Type": "application/json",
             "Authorization": "Bearer " + key})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.loads(r.read().decode("utf-8", "replace"))
    print("HTTP", r.status)
    print("reply:", out["choices"][0]["message"]["content"].strip()[:200])
except urllib.error.HTTPError as e:
    print("HTTP", e.code)
    print(e.read().decode("utf-8", "replace")[:500])
