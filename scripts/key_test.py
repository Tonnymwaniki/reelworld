"""Probe the Meta Model API (dev.meta.ai key) at api.meta.ai.

1. GET /v1/models  -> proves auth, lists real model ids.
2. Tiny chat completion on the Muse Spark model (auto-picked from the
   list when the configured id is absent).
Reads META_API_KEY from .env. Never prints the key. Stdlib only.

Run from the project root:
    python scripts\\key_test.py
"""
import json
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://api.meta.ai/v1"
WANT_MODEL = "muse-spark-1.3"

env = (Path(__file__).resolve().parent.parent / ".env").read_text(encoding="utf-8")
vals = {}
for line in env.splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        vals[k.strip()] = v.strip()
key = vals.get("META_API_KEY", "")
model = vals.get("META_API_MODEL", "") or WANT_MODEL
if not key:
    raise SystemExit("META_API_KEY is empty in .env")


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]


st, body = call("GET", "/v1/models")
print("models: HTTP", st)
ids = []
if st == 200:
    try:
        ids = [m.get("id", "?") for m in json.loads(body).get("data", [])]
    except ValueError:
        pass
    print("models:", ", ".join(ids[:12]) or "(unparseable)")
else:
    print(body[:300])

pick = model
low = [i.lower() for i in ids]
if ids and model not in ids:
    for i in ids:
        if "spark" in i.lower():
            pick = i
            break
    else:
        pick = ids[0]
    print(f"note: {model} not listed, trying {pick}")

st, body = call("POST", "/chat/completions",
                {"model": pick,
                 "messages": [{"role": "user", "content": "say ok"}],
                 "max_tokens": 10})
print("chat: HTTP", st)
if st == 200:
    try:
        out = json.loads(body)
        msg = (out.get("choices") or [{}])[0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):  # block-style content
            content = " ".join(
                b.get("text", "") for b in content if isinstance(b, dict))
        if content:
            print("reply:", str(content).strip()[:200])
        else:
            print("message keys:", sorted(msg.keys()))
            print("raw:", body[:600])
    except ValueError:
        print(body[:300])
else:
    print(body[:300])
