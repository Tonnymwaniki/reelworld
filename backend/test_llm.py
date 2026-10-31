"""Focused checks for the model switchboard (backend/llm.py).

Config, token floor, fallback, affinity header, budget, logging:
no network (the OpenAI client is stubbed). Run from the project
root:  python backend/test_llm.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm  # noqa: E402

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


# isolate from the real .env and call log
tmp = tempfile.TemporaryDirectory()
llm.DOTENV = Path(tmp.name) / ".env"
llm.CALLS_PATH = Path(tmp.name) / "calls.jsonl"
llm.CAPS_PATH = Path(tmp.name) / "caps.json"
llm.ANSWER_CACHE_DIR = Path(tmp.name) / "answers"
llm._calls.clear()
VARS = ("PARSER_BASE_URL", "PARSER_KEY_ENV", "PARSER_MODEL",
        "FALLBACK_BASE_URL", "FALLBACK_KEY_ENV", "FALLBACK_MODEL",
        "FORCE_PRIMARY_FAIL", "LLM_TIMEOUT_SECONDS", "DAILY_TOKEN_BUDGET",
        "PKEY", "FKEY")
saved = {v: os.environ.pop(v, None) for v in VARS}
llm.DOTENV.write_text(
    "PARSER_BASE_URL=https://modal.example.com/v1\n"
    "PARSER_KEY_ENV=PKEY\nPARSER_MODEL=primary-model\n"
    "FALLBACK_BASE_URL=https://fallback.example.com/v1\n"
    "FALLBACK_KEY_ENV=FKEY\nFALLBACK_MODEL=fallback-model\n"
    "PKEY=secret1\nFKEY=secret2\n",
    encoding="utf-8")


def fake_resp(text, pt=5, ct=7):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text,
                                                         reasoning_content=None))],
        usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct))


CREATED, BEHAVIOR = [], {}


class FakeCompletions:
    def __init__(self, base_url):
        self.base_url = base_url

    def create(self, **kw):
        CREATED.append((self.base_url, kw))
        how = BEHAVIOR.get(self.base_url, "ok")
        if isinstance(how, Exception):
            raise how
        if how == "empty":
            return fake_resp("")
        if isinstance(how, str) and how != "ok":
            return fake_resp(how)
        return fake_resp("primary says hi")


class FakeClient:
    def __init__(self, base_url=None, api_key=None, timeout=None):
        self.init = {"base_url": base_url, "api_key": api_key, "timeout": timeout}
        self.chat = SimpleNamespace(completions=FakeCompletions(base_url))
        CREATED.append(("__init__", self.init))


llm.OpenAI = FakeClient

# pure helpers
check(llm.provider_name("https://x.modal.com/v1") == "modal", "modal name")
check(llm.provider_name("https://inference.baseten.co/v1") == "baseten",
      "baseten name")
check(llm.provider_host("https://inference.baseten.co/v1") == "inference.baseten.co",
      "host only")
cfg = llm.config()
check(cfg["primary"]["model"] == "primary-model"
      and cfg["fallback"]["model"] == "fallback-model"
      and cfg["timeout"] == 90 and cfg["budget"] == 3000000, "config from .env")

# token floor + affinity header
BEHAVIOR["https://modal.example.com/v1"] = "ok"
r = llm.ask("hi", max_tokens=100, purpose="chat", session_id="s1")
last = CREATED[-1][1]
check(last["max_tokens"] == 8000, "8000 floor")
check(last["extra_headers"] == {"Modal-Routing-Affinity-Key": "s1"}, "affinity sent")
check(r["provider"] == "modal" and not r["fallback_used"]
      and r["prompt_tokens"] == 5 and r["completion_tokens"] == 7, "result shape")
r = llm.ask("hi", max_tokens=100, purpose="simple")
check(CREATED[-1][1]["max_tokens"] == 100, "simple keeps small budget")
r = llm.ask("hi", purpose="chat")
check("extra_headers" not in CREATED[-1][1], "no affinity without session")

# fallback paths
BEHAVIOR["https://modal.example.com/v1"] = RuntimeError("boom")
BEHAVIOR["https://fallback.example.com/v1"] = "fallback says hi"
r = llm.ask("hi", purpose="chat")
check(r["text"] == "fallback says hi" and r["fallback_used"]
      and r["provider"] == "fallback.example.com", "fallback on error")
BEHAVIOR["https://modal.example.com/v1"] = "empty"
r = llm.ask("hi", purpose="chat")
check(r["fallback_used"], "fallback on empty answer")
BEHAVIOR["https://fallback.example.com/v1"] = RuntimeError("down")
try:
    llm.ask("hi", purpose="chat")
    check(False, "both fail raises")
except RuntimeError as e:
    check("both providers" in str(e), "both fail raises")
row = llm.recent_calls(1)[0]
check(row["ok"] is False and row["fallback_used"] and row["error"].startswith("RuntimeError"),
      "failure logged")
os.environ["FORCE_PRIMARY_FAIL"] = "true"
BEHAVIOR["https://modal.example.com/v1"] = "ok"
BEHAVIOR["https://fallback.example.com/v1"] = "fallback says hi"
r = llm.ask("hi", purpose="chat")
check(r["fallback_used"], "forced primary failure")
del os.environ["FORCE_PRIMARY_FAIL"]

# images ride as data URLs, as annotate.py does
img = Path(tmp.name) / "tiny.jpg"
img.write_bytes(b"\xff\xd8fakejpeg")
BEHAVIOR["https://modal.example.com/v1"] = "sees it"
r = llm.ask("what?", image_path=str(img), purpose="chat")
blocks = CREATED[-1][1]["messages"][0]["content"]
check(r["text"] == "sees it" and len(blocks) == 2
      and blocks[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"),
      "image data URL")

# logging + budget
import json  # noqa: E402
rows = [json.loads(line) for line in llm.CALLS_PATH.read_text(encoding="utf-8").splitlines()]
need = {"timestamp", "provider", "model", "purpose", "seconds",
        "prompt_tokens", "completion_tokens", "ok", "error", "fallback_used"}
check(bool(rows) and all(need <= set(r) for r in rows)
      and all("secret" not in json.dumps(r) for r in rows), "jsonl rows, no keys")
check(len(llm.recent_calls(200)) <= 100, "memory bounded")
now_nbo = datetime.now(llm.NAIROBI)
with open(llm.CALLS_PATH, "a", encoding="utf-8") as f:
    f.write(json.dumps({"timestamp": (now_nbo - timedelta(hours=26)).isoformat(),
                        "prompt_tokens": 1000, "completion_tokens": 1000}) + "\n")
os.environ["DAILY_TOKEN_BUDGET"] = "10"
try:
    llm.ask("hi", purpose="chat")
    check(False, "spent budget raises")
except llm.LLMBudgetSpent:
    check(True, "spent budget raises")
check(llm.tokens_today() < 1000 + 1000 + 50, "yesterday excluded")
del os.environ["DAILY_TOKEN_BUDGET"]

# timeout + .env value shapes
os.environ["LLM_TIMEOUT_SECONDS"] = "12"
BEHAVIOR["https://modal.example.com/v1"] = "ok"
llm.ask("hi", purpose="chat")
check(CREATED[-2][1]["timeout"] == 12, "timeout passes through")
del os.environ["LLM_TIMEOUT_SECONDS"]
with open(llm.DOTENV, "a", encoding="utf-8") as f:
    f.write('QUOTED="a=b"\n')
check(llm._env("QUOTED") == "a=b", ".env quotes and equals")

# image capability probe
BEHAVIOR["https://modal.example.com/v1"] = "red"
caps = llm.probe_images()
check(caps["primary_accepts_images"] and caps["checked_at"]
      and json.loads(llm.CAPS_PATH.read_text())["primary_accepts_images"],
      "probe success cached")
BEHAVIOR["https://modal.example.com/v1"] = RuntimeError("no images here")
caps = llm.probe_images()
check(not caps["primary_accepts_images"] and "no images here" in caps["error"],
      "probe failure recorded")
CREATED.clear()
check(llm.image_capability()["primary_accepts_images"] is False
      and not CREATED, "caps cache hit makes no call")
llm.CAPS_PATH.write_text(json.dumps({"primary_accepts_images": False,
                                     "checked_at": None, "error": "x"}))
BEHAVIOR["https://fallback.example.com/v1"] = "fallback sees it"
CREATED.clear()
r = llm.ask("what?", image_path=str(img), purpose="chat")
tried = [u for u, _ in CREATED if u != "__init__"]
check(r["fallback_used"] and "https://modal.example.com/v1" not in tried
      and tried[0] == "https://fallback.example.com/v1",
      "images go straight to fallback")
llm.CAPS_PATH.write_text(json.dumps({"primary_accepts_images": True,
                                     "checked_at": "t", "error": ""}))
BEHAVIOR["https://modal.example.com/v1"] = "modal sees it"
CREATED.clear()
r = llm.ask("what?", image_path=str(img), purpose="chat")
tried = [u for u, _ in CREATED if u != "__init__"]
check(not r["fallback_used"] and tried[0] == "https://modal.example.com/v1",
      "images use primary when accepted")
os.environ["FORCE_PRIMARY_FAIL"] = "true"
check(llm.probe_images()["primary_accepts_images"], "probe ignores fail switch")
os.environ["DAILY_TOKEN_BUDGET"] = "1"
check(llm.probe_images()["primary_accepts_images"], "probe bypasses budget")
del os.environ["FORCE_PRIMARY_FAIL"]
del os.environ["DAILY_TOKEN_BUDGET"]

# status assembly (seeded rows only)
llm._calls.clear()
llm.CALLS_PATH.write_text("", encoding="utf-8")
now = datetime.now(timezone.utc).isoformat()


def _row(provider, seconds, ok, error=""):
    return {"timestamp": now, "provider": provider, "model": "m",
            "purpose": "chat", "seconds": seconds, "prompt_tokens": 10,
            "completion_tokens": 5, "ok": ok, "error": error,
            "fallback_used": False}


for seed in (_row("modal", 2.0, True), _row("modal", 4.0, True),
             _row("baseten", 6.0, False, "Boom")):
    llm._log_call(seed)
st = llm.status()
check(st["avg_seconds_per_provider"] == {"modal": 3.0, "baseten": 6.0},
      "avg seconds per provider")
check(st["success_rate"] == round(2 / 3, 3) and st["window"] == 3,
      "success rate + window")
check(st["tokens_today"] == 45 and st["daily_budget"] == 3000000
      and st["budget_left"] == 3000000 - 45, "tokens + budget left")
check(st["last_error"] == "Boom", "last error")
check(st["primary"]["host"] == "modal.example.com"
      and "secret" not in json.dumps(st), "hosts only, no keys")
check(st["images"]["handled_by"] == "modal", "images handled by primary")
llm.CAPS_PATH.unlink()
st = llm.status()
check(st["images"]["primary_accepts_images"] is None
      and st["images"]["handled_by"] == "unknown (not probed yet)",
      "status never probes")

# answer cache
rec = {"observed": {"caption": "a street"}, "n": 1}
k1 = llm.cache_key("ask", ["p1"], " What? ", [rec])
k2 = llm.cache_key("ask", ["p1"], "What?", [rec])
check(k1 == k2 and len(k1) == 16, "key stable, whitespace ignored")
check(llm.cache_key("ask", ["p1"], "When?", [rec]) != k1, "question matters")
check(llm.cache_key("ask", ["p1"], "What?", [{"n": 2}]) != k1, "record matters")
check(llm.cache_key("ask", ["p1", "p2"], "What?", [rec, rec])
      != llm.cache_key("ask", ["p2", "p1"], "What?", [rec, rec]), "id order matters")
check(llm.cache_get(k1) is None, "miss on empty cache")
llm.cache_put(k1, {"answer": "hi"})
check(llm.cache_get(k1) == {"answer": "hi"}, "roundtrip")
old = datetime.now(timezone.utc) - timedelta(hours=25)
(llm.ANSWER_CACHE_DIR / f"{k1}.json").write_text(
    json.dumps({"created_at": old.isoformat(), "payload": {"answer": "stale"}}))
check(llm.cache_get(k1) is None, "expired entries miss")
(llm.ANSWER_CACHE_DIR / f"{k1}.json").write_text("not json{{")
check(llm.cache_get(k1) is None, "corrupt entries miss")

for v, val in saved.items():
    if val is not None:
        os.environ[v] = val

print(f"test_llm.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
