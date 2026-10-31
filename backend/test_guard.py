"""Focused checks for the expensive-endpoint guard (backend/api.py).

Visitor identity, rate windows, demo multiplier, budget, resting
shape: no network (fake requests). Run from the project root:
  python backend/test_guard.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import api  # noqa: E402

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


class FakeClient:
    def __init__(self, host):
        self.host = host


class FakeReq:
    def __init__(self, host="1.2.3.4", cookies=None, headers=None):
        self.client = FakeClient(host)
        self.cookies = cookies or {}
        self.headers = headers or {}


class FakeResp:
    def __init__(self):
        self.set = {}

    def set_cookie(self, k, v, **kw):
        self.set[k] = v


saved_demo, saved_code = api.DEMO_MODE, api.DEMO_CODE
orig_tokens = api.llm_mod.tokens_today
api.DEMO_MODE = True
api.DEMO_CODE = "testcode"
api.llm_mod.tokens_today = lambda: 0

check(api._visitor_id(FakeReq()) == "1.2.3.4:none", "visitor ip without cookie")
check(api._visitor_id(FakeReq(cookies={"rw_visitor": "abc"})) == "1.2.3.4:abc",
      "visitor ip plus cookie")

resp = FakeResp()
check(api._guard_expensive(FakeReq(), resp) is None and "rw_visitor" in resp.set,
      "mint cookie on first hit")
resp = FakeResp()
check(api._guard_expensive(FakeReq(cookies={"rw_visitor": "abc"}), resp) is None
      and not resp.set, "no cookie when present")

api._rate_hits.clear()


def minute_req():
    return FakeReq(cookies={"rw_visitor": "minute-test"})


out = [api._guard_expensive(minute_req(), FakeResp()) for _ in range(7)]
check(out[:6] == [None] * 6 and out[6] == "minute", "6 per minute, 7th rests")

api._rate_hits.clear()
code = {"x-demo-code": "testcode"}


def vip_req():
    return FakeReq(cookies={"rw_visitor": "vip"}, headers=code)


out = [api._guard_expensive(vip_req(), FakeResp()) for _ in range(25)]
check(out[:24] == [None] * 24 and out[24] == "minute", "demo code quadruples")

os.environ["REQUESTS_PER_DAY"] = "2"
api._rate_hits.clear()
out = [api._guard_expensive(FakeReq(cookies={"rw_visitor": "day-test"}), FakeResp())
       for _ in range(3)]
check(out[:2] == [None, None] and out[2] == "day", "daily cap")
del os.environ["REQUESTS_PER_DAY"]

api.DEMO_MODE = False
api._rate_hits.clear()
out = [api._guard_expensive(FakeReq(cookies={"rw_visitor": "local"}), FakeResp())
       for _ in range(10)]
check(all(o is None for o in out), "no limits when DEMO_MODE false")
api.DEMO_MODE = True

api.llm_mod.tokens_today = lambda: 10 ** 9
check(api._guard_expensive(FakeReq(cookies={"rw_visitor": "rich"}), FakeResp())
      == "budget", "spent budget rests")
api.llm_mod.tokens_today = lambda: 0

p = api._resting_payload("s", None, "minute")
check(p["kind"] == "resting" and p["results"] == []
      and "resting" in p["text"].lower()
      and p["trace"][0]["step"] == "rested", "resting shape")

api._rate_hits.clear()
try:
    for _ in range(7):
        api._guard_or_429(FakeReq(cookies={"rw_visitor": "429"}), FakeResp())
    check(False, "429 raised")
except Exception as e:
    check(getattr(e, "status_code", None) == 429, "429 raised")

api.DEMO_MODE, api.DEMO_CODE = saved_demo, saved_code
api.llm_mod.tokens_today = orig_tokens

print(f"test_guard.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
