"""Route-table regression checks (backend/api.py).

Every endpoint the docs and tests promise must stay registered.
Run from the project root:  python backend/test_routes.py
"""
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


routes = {(getattr(r, "path", None), tuple(sorted(getattr(r, "methods", None) or [])))
          for r in api.app.routes}

for path, methods in (("/api/llm/status", ("GET",)),
                      ("/api/llm/probe", ("POST",)),
                      ("/chat", ("POST",)),
                      ("/chat/stream", ("POST",)),
                      ("/api/ask", ("POST",)),
                      ("/api/compare", ("POST",)),
                      ("/api/explain", ("POST",)),
                      ("/api/story", ("POST",))):
    check((path, methods) in routes, f"route {methods[0]} {path}")

import inspect  # noqa: E402

for fn in (api.chat, api.chat_stream, api.ask, api.compare, api.explain,
           api.story, api.llm_probe):
    sig = inspect.signature(fn)
    params = sig.parameters
    check(params["request"].default is None and params["response"].default is None,
          f"{fn.__name__} keeps direct-call defaults")

print(f"test_routes.py: {total - fails}/{total} checks passed")
sys.exit(1 if fails else 0)
