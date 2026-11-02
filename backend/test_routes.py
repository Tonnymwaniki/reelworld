"""Route-table regression checks (backend/api.py).

Every endpoint the docs and tests promise must stay registered.
Run from the project root:  python backend/test_routes.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import api  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

fails = 0
total = 0


def check(cond, label):
    global fails, total
    total += 1
    if not cond:
        fails += 1
        print(f"FAIL {label}")


routes = {(getattr(r, "path", None), tuple(sorted(getattr(r, "methods", None) or [])))
          for r in api.app.routes}

for path, methods in (("/api/llm/status", ("GET",)),
                      ("/api/llm/probe", ("POST",)),
                      ("/chat", ("POST",)),
                      ("/chat/stream", ("POST",)),
                      ("/api/ask", ("POST",)),
                      ("/api/compare", ("POST",)),
                      ("/api/explain", ("POST",)),
                      ("/api/story", ("POST",)),
                      ("/api/profile", ("GET",)),
                      ("/api/profile", ("PUT",)),
                      ("/api/profile", ("DELETE",)),
                      ("/api/owner-tags", ("POST",)),
                      ("/api/owner-tags/summary", ("GET",)),
                      ("/api/stories/{story_id}/refresh", ("POST",)),
                      ("/api/stories/{story_id}/publish", ("POST",)),
                      ("/api/face-reference", ("POST",)),
                      ("/api/face-reference", ("GET",)),
                      ("/api/face-reference", ("DELETE",)),
                      ("/api/face-scan", ("POST",)),
                      ("/api/films", ("POST",)),
                      ("/api/audio", ("POST",)),
                      ("/api/audio/{rug}", ("GET",)),
                      ("/api/chats", ("GET",)),
                      ("/api/chats", ("POST",)),
                      ("/api/chats/{chat_id}", ("GET",)),
                      ("/api/chats/{chat_id}", ("PATCH",)),
                      ("/api/chats/{chat_id}", ("DELETE",)),
                      ("/api/chats", ("DELETE",)),
                      ("/api/search", ("POST",)),
                      ("/api/related", ("POST",)),
                      ("/api/reject", ("POST",))):
    check((path, methods) in routes, f"route {methods[0]} {path}")


class FakeUploadReq:
    def __init__(self, declared):
        self.headers = {"content-type": "image/jpeg",
                        "content-length": str(declared),
                        "x-demo-code": "testcode"}

    async def body(self):
        return b"fake-bytes"


try:
    api.ExplainRequest(photo_a="", photo_b="market_001")
    check(False, "explain rejects empty ids")
except ValidationError:
    check(True, "explain rejects empty ids")

saved_mode = api.DEMO_MODE
api.DEMO_MODE = False
try:
    api.story(api.StoryRequest(theme="markets", voice="garbage"))
    check(False, "story rejects bad voice")
except HTTPException as e:
    check(e.status_code == 400, "story rejects bad voice")
finally:
    api.DEMO_MODE = saved_mode

try:
    api.clean_spec({"query": "x", "max_people": True})
    check(False, "max_people rejects bool")
except HTTPException as e:
    check(e.status_code == 400, "max_people rejects bool")
check(api.clean_spec({"query": "x", "max_people": 2})["max_people"] == 2,
      "max_people keeps int")

try:
    api._coerce_embedding("{oops")
    check(False, "corrupt embedding is 502")
except HTTPException as e:
    check(e.status_code == 502, "corrupt embedding is 502")
check(api._coerce_embedding([1.0]) == [1.0], "coerce passes lists through")

saved_mode, saved_code = api.DEMO_MODE, api.DEMO_CODE
api.DEMO_MODE, api.DEMO_CODE = True, "testcode"
try:
    asyncio.run(api.upload(FakeUploadReq(api.MAX_UPLOAD + 1), None))
    check(False, "oversized raw upload is 413")
except HTTPException as e:
    check(e.status_code == 413, "oversized raw upload is 413")
finally:
    api.DEMO_MODE, api.DEMO_CODE = saved_mode, saved_code

import inspect  # noqa: E402

for fn in (api.chat, api.chat_stream, api.ask, api.compare, api.explain,
           api.story, api.llm_probe, api.audio_speak, api.chats_list,
           api.chats_create, api.chats_get, api.chats_rename,
           api.chats_delete, api.chats_delete_all, api.api_search,
           api.api_related, api.api_reject):
    sig = inspect.signature(fn)
    params = sig.parameters
    check(params["request"].default is None and params["response"].default is None,
          f"{fn.__name__} keeps direct-call defaults")

print(f"test_routes.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
