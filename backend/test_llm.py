"""Focused checks for the model switchboard (backend/llm.py).

Config, token floor, fallback, affinity header, budget, logging:
no network (the OpenAI client is stubbed). Run from the project
root:  python backend/test_llm.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta
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

for v, val in saved.items():
    if val is not None:
        os.environ[v] = val

print(f"test_llm.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
